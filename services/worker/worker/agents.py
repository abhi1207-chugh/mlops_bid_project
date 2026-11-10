"""LangGraph agents: classifier -> compliance (bounded tool loop) -> verifier -> route or escalate.

Hard rules enforced here: an incomplete or unverified run escalates (1); citations must resolve to passages
retrieved in this run (2); retrieval is a tool the agent chooses to call, in a loop bounded by steps, tool calls
and wall-clock time (5).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from common.config import get_settings
from common.llm import LLMClient, LLMError
from common.logging import log
from common.models import ConditionFinding, Finding, UsageRecord, Verification
from common.prompts import load_prompt
from common.safety import unsafe_output_reason
from common.tracing import span
from worker.retrieval import CorpusTools
from worker.verifier import resolve_citations

logger = logging.getLogger("agents")
ROUTES = {"pass_to_technical_evaluation", "seek_clarification", "reject_with_cited_condition", "escalate_to_human"}
MAX_ATTEMPTS = 2


class State(TypedDict, total=False):
    category: str
    attempt: int
    strategy: str
    draft: dict
    finding: Finding
    verification_issues: list[str]
    transcript: list[str]
    done: bool


def parse_json(text: str) -> dict | None:
    """First JSON object in text (models sometimes wrap output in prose or code fences)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


class RunContext:
    def __init__(self, run_id: str, bid: dict, flags: list[str], llm: LLMClient, tools: CorpusTools) -> None:
        s = get_settings()
        self.run_id, self.bid, self.flags, self.llm, self.tools = run_id, bid, flags, llm, tools
        self.deadline = time.monotonic() + s.max_seconds
        self.max_steps, self.max_tool_calls = s.max_steps, s.max_tool_calls
        self.steps = 0
        self.usage: list[UsageRecord] = []
        self.prompt_versions: dict[str, str] = {}
        self.trace: list[dict] = []

    def ask(self, name: str, **vars_: str) -> dict | None:
        """One LLM call. Returns parsed JSON or None on unparseable output."""
        prompt, version = load_prompt(name, **vars_)
        self.prompt_versions[name] = version
        with span(f"agent.{name}", run_id=self.run_id, prompt_version=version):
            res = self.llm.generate(prompt, prompt_version=version, step=name, run_id=self.run_id)
        self.usage.append(UsageRecord(step=name, prompt_version=version, prompt_tokens=res.prompt_tokens,
                                      completion_tokens=res.completion_tokens, cost=res.cost, latency_ms=res.latency_ms))
        self.steps += 1
        return parse_json(res.text)

    def budget_left(self) -> bool:
        return (self.steps < self.max_steps and self.tools.calls < self.max_tool_calls
                and time.monotonic() < self.deadline)

    def event(self, kind: str, **data: Any) -> None:
        self.trace.append({"t": time.time(), "kind": kind, **data})
        log(logger, kind, **data)


def escalation(ctx: RunContext, reason: str, summary: str, questions: list[str] | None = None,
               category: str | None = None, verification: Verification | None = None) -> Finding:
    return Finding(run_id=ctx.run_id, route="escalate_to_human", summary=summary, escalation_reason=reason,
                   committee_questions=questions or [], bidder_category=category, verification=verification,
                   steps=ctx.steps, tool_calls=ctx.tools.calls, prompt_versions=ctx.prompt_versions, usage=ctx.usage)


def build_graph(ctx: RunContext):
    claimed = ctx.bid.get("bidder_category_claimed")

    def classify(state: State) -> State:
        out = ctx.ask("classifier", bid=json.dumps(ctx.bid, indent=1), flags=json.dumps(ctx.flags))
        cat = (out or {}).get("category")
        ctx.event("classified", category=cat, claimed=claimed)
        if cat not in ("large_enterprise", "mse", "startup", "consortium", "foreign", "unknown"):
            return {"category": "unknown", "done": True, "finding": escalation(
                ctx, "classifier_output_invalid", "The bidder could not be classified; escalating.",
                ["Which bidder category applies?"])}
        if cat == "unknown" or cat != claimed:
            return {"category": cat, "done": True, "finding": escalation(
                ctx, "bidder_category_unclear",
                f"Claimed category '{claimed}' and classified category '{cat}' do not settle the bidder category.",
                ["Which bidder category applies, and on what evidence?"], category=cat)}
        if cat in ("consortium", "foreign"):
            return {"category": cat, "done": True, "finding": escalation(
                ctx, "corpus_cannot_answer",
                f"The corpus (tender, DoE/DPE orders, GFR Chapter 6, MSME circular) contains no provision on {cat} bidders; "
                "no determination can be supported.",
                [f"Which rules govern {cat} bidders for this tender?"], category=cat)}
        return {"category": cat, "attempt": 0, "strategy": ""}

    def compliance(state: State) -> State:
        attempt = state.get("attempt", 0) + 1
        strategy = state.get("strategy", "")
        strategy_txt = ""  # on a retry the failure and the rejected draft are appended to the transcript instead
        transcript: list[str] = list(state.get("transcript", []))
        while True:
            if not ctx.budget_left():
                ctx.event("budget_exhausted", steps=ctx.steps, tool_calls=ctx.tools.calls)
                return {"attempt": attempt, "done": True, "finding": escalation(
                    ctx, "run_incomplete", "The agent loop ran out of its step, tool-call or time budget before it could "
                    "produce a verified finding.", ["Please screen this bid manually."], category=state["category"])}
            out = ctx.ask("compliance", bid=json.dumps(ctx.bid, indent=1), flags=json.dumps(ctx.flags),
                          category=state["category"], strategy=strategy_txt,
                          transcript="\n".join(transcript) or "(no tool calls yet)")
            if out is None:
                transcript.append("SYSTEM: your last reply was not valid JSON. Reply with one JSON object.")
                continue
            if out.get("action") == "tool":
                tool, args = str(out.get("tool")), out.get("args") or {}
                try:
                    result = ctx.tools.call(tool, args if isinstance(args, dict) else {})
                except Exception as exc:  # unknown tool / bad args: tell the model, keep the bound
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                ctx.event("tool_call", tool=tool, args=args,
                          returned=[r.get("chunk_id") for r in result] if isinstance(result, list) else None)
                transcript.append(f"ASSISTANT: {json.dumps(out)}\nTOOL_RESULT: {json.dumps(result)}")
                continue
            if out.get("action") == "final":
                transcript.append(f"ASSISTANT: {json.dumps(out)}")
                return {"attempt": attempt, "draft": out, "transcript": transcript}
            transcript.append("SYSTEM: 'action' must be 'tool' or 'final'.")

    def verify(state: State) -> State:
        d = state["draft"]
        issues: list[str] = []
        route = d.get("route")
        if route not in ROUTES:
            issues.append(f"invalid route {route!r}")
        visible_text = " ".join([
            str(d.get("summary", "")),
            *(str(c.get("evidence", "")) for c in d.get("conditions", []) or []),
            *(str(q) for q in d.get("committee_questions", []) or []),
        ])
        if reason := unsafe_output_reason(visible_text):
            issues.append(f"final wording safety check failed: {reason}")
        top, iss = resolve_citations(d.get("citations", []), ctx.tools.retrieved)
        issues += iss
        conditions: list[ConditionFinding] = []
        for c in d.get("conditions", []) or []:
            cc, iss = resolve_citations(c.get("citations", []), ctx.tools.retrieved)
            issues += iss
            status = c.get("status") if c.get("status") in ("met", "unmet", "unclear") else "unclear"
            conditions.append(ConditionFinding(condition=str(c.get("condition", "")), clause_ref=c.get("clause_ref"),
                                               status=status, evidence=str(c.get("evidence", "")), citations=cc))
        if route in ("pass_to_technical_evaluation", "reject_with_cited_condition", "seek_clarification") and not (top or any(c.citations for c in conditions)):
            issues.append("a non-escalation route requires at least one resolved citation")
        if route == "reject_with_cited_condition" and not any(c.status == "unmet" and c.citations for c in conditions):
            issues.append("reject requires an unmet condition with a resolved citation")
        if route == "pass_to_technical_evaluation" and any(c.status != "met" for c in conditions):
            issues.append("pass route but a condition is not met")
        got = ctx.tools.retrieved.values()
        if not any(c["doc_type"] == "tender" for c in got):
            issues.append("no tender passage was retrieved; read the tender clauses first")
        if state["category"] in ("startup", "mse") and not any(c["doc_type"] == "policy" for c in got):
            issues.append("bidder is a startup/mse but no policy passage was retrieved; search policy documents for relaxations")
        if state["category"] in ("startup", "mse") and any(
                c.status != "met" and re.search(r"turnover|experience", c.condition, re.I) for c in conditions) \
                and not any(c["doc_id"] == "GFR-2017-CH6" and c["clause_ref"] == "Rule 173(i)" for c in got):
            issues.append('turnover/experience is not met for a startup/mse but GFR Rule 173(i) was not read; '
                          'call get_clause with doc_id "GFR-2017-CH6" and clause_ref "Rule 173(i)"')
        cited = {(c.doc_id, c.clause_ref) for c in top} | {(c.doc_id, c.clause_ref) for cd in conditions for c in cd.citations}
        cited_docs = {d for d, _ in cited}
        cat = state["category"]
        relax_needed = cat in ("startup", "mse") and any(
            c.status != "met" and re.search(r"turnover|experience", c.condition, re.I) for c in conditions)
        if relax_needed:
            need = ["DOE-OM-2016-07-25", "DOE-OM-2016-09-20"] if cat == "startup" else ["MSME-CIRCULAR-2016-03-10"]
            hint = {"DOE-OM-2016-07-25": "Para 3", "DOE-OM-2016-09-20": "Para 2", "MSME-CIRCULAR-2016-03-10": "Para 4"}
            for doc in need:
                if doc not in cited_docs:
                    issues.append(f"the relaxation order {doc} must be cited for a {cat} with unmet turnover/experience: call get_clause "
                                  f'with doc_id "{doc}" and clause_ref "{hint[doc]}", then cite the returned chunk_id with a verbatim quote '
                                  "in the final answer's citations")
        if ctx.bid.get("emd_exemption_claimed") and cat in ("startup", "mse"):
            ref = "Clause 3" if cat == "startup" else "Clause 2"
            if ("TENDER-NITR-390", ref) not in cited:
                issues.append(f"an EMD exemption is claimed: add an EMD condition and cite tender {ref} (get_clause it if needed)")
        if ctx.bid.get("emd_paid_inr", 0) > 0 and ("TENDER-NITR-390", "Clause 1") not in cited:
            issues.append("EMD payment is recorded: add an EMD / bid security condition and cite tender Clause 1 (get_clause it if needed)")
        suggestion = ""
        if not issues:  # independent LLM verifier, separate prompt
            passages = "\n".join(f"[{cid}] ({c['doc_id']} {c['clause_ref']}): {c['text']}" for cid, c in ctx.tools.retrieved.items())
            v = ctx.ask("verifier", bid=json.dumps(ctx.bid, indent=1), passages=passages, finding=json.dumps(d, indent=1))
            if v is None or v.get("verdict") != "pass":
                issues += [str(i) for i in (v or {}).get("issues", [])] or ["verifier did not pass the finding"]
                suggestion = str((v or {}).get("suggested_strategy", ""))
        attempt = state["attempt"]
        ctx.event("verified", passed=not issues, issues=issues, attempt=attempt)
        ver = Verification(passed=not issues, attempts=attempt, issues=issues)
        if issues:
            if attempt < MAX_ATTEMPTS and ctx.budget_left():
                note = ("SYSTEM: the verifier REJECTED your final answer. Problems:\n- " + "\n- ".join(issues + ([suggestion] if suggestion else [])) +
                        "\nYour earlier tool results are still above. Make ONLY the missing tool calls the problems ask for "
                        "(exact get_clause / search_corpus calls), then send a corrected final answer that cites every required provision.")
                return {"transcript": state.get("transcript", []) + [note], "verification_issues": issues}
            return {"done": True, "finding": escalation(
                ctx, "verification_failed", "The draft finding could not be verified against the retrieved passages; "
                "escalating rather than returning an unverified answer.", ["Please screen this bid manually."],
                category=state["category"], verification=ver)}
        route = d["route"]
        finding = Finding(
            run_id=ctx.run_id, route=route, summary=str(d.get("summary", "")), conditions=conditions, citations=top,
            committee_questions=[str(q) for q in d.get("committee_questions", []) or []],
            escalation_reason=(str(d.get("escalation_reason")) if route == "escalate_to_human" and d.get("escalation_reason")
                               else ("tender_policy_conflict_or_undecidable" if route == "escalate_to_human" else None)),
            verification=ver, bidder_category=state["category"], steps=ctx.steps, tool_calls=ctx.tools.calls,
            prompt_versions=ctx.prompt_versions, usage=ctx.usage)
        return {"done": True, "finding": finding}

    g = StateGraph(State)
    g.add_node("classify", classify)
    g.add_node("compliance", compliance)
    g.add_node("verify", verify)
    g.set_entry_point("classify")
    g.add_conditional_edges("classify", lambda s: END if s.get("done") else "compliance")
    g.add_conditional_edges("compliance", lambda s: END if s.get("done") else "verify")
    g.add_conditional_edges("verify", lambda s: END if s.get("done") else "compliance")
    return g.compile()


def run_screening(run_id: str, bid: dict, flags: list[str], llm: LLMClient, tools: CorpusTools | None = None) -> tuple[Finding, list[dict]]:
    """Never raises: any failure becomes an escalation (hard rule 1)."""
    tools = tools or CorpusTools(bid)
    ctx = RunContext(run_id, bid, flags, llm, tools)
    try:
        final = build_graph(ctx).invoke({}, {"recursion_limit": 60})
        finding = final["finding"]
    except LLMError as exc:
        ctx.event("llm_unavailable", error=str(exc))
        finding = escalation(ctx, "llm_unavailable", "The language model could not be reached; escalating rather than guessing.",
                             ["Please screen this bid manually."])
    except Exception as exc:  # noqa: BLE001 - last line of defence for rule 1
        ctx.event("run_error", error=f"{type(exc).__name__}: {exc}")
        finding = escalation(ctx, "run_error", "The screening run failed unexpectedly; escalating.", ["Please screen this bid manually."])
    ctx.trace.extend({"kind": f"cache_{event}"} for event in getattr(tools, "cache_events", []))
    return finding, ctx.trace
