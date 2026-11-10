"""Deterministic local model substitute for the Phase 1 demo and load tests.

It deliberately follows the same tool loop as a model and cites only passages
returned during that loop. It is not a production legal reasoner.
"""
import asyncio
import json
import os
import re
from dataclasses import dataclass

from fastapi import FastAPI

app = FastAPI(title="stub-llm")
DELAY_MS = int(os.getenv("STUB_DELAY_MS", "1500"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _bid(prompt: str) -> dict:
    match = re.search(r"<bid_summary>\s*(\{.*?\})\s*</bid_summary>", prompt, re.S)
    try:
        return json.loads(match.group(1)) if match else {}
    except json.JSONDecodeError:
        return {}


def _classifier(prompt: str) -> dict:
    return {"category": _bid(prompt).get("bidder_category_claimed", "unknown"), "confidence": "high",
            "reason": "deterministic demo stub", "entities": {}}


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    doc_id: str
    clause_ref: str
    text: str

    def citation(self) -> dict:
        return {"chunk_id": self.chunk_id, "quote": " ".join(self.text.split())[:180]}


def _passages(prompt: str) -> list[Passage]:
    # Prefer actual tool-result JSON. The prompt template itself contains illustrative
    # citation placeholders which must never be mistaken for retrieved evidence.
    out = []
    for raw in re.findall(r"TOOL_RESULT:\s*(\[.*?\])(?:\nASSISTANT:|\nSYSTEM:|$)", prompt, re.S):
        try:
            for item in json.loads(raw):
                if {"chunk_id", "doc_id", "clause_ref", "text"} <= item.keys():
                    out.append(Passage(item["chunk_id"], item["doc_id"], item["clause_ref"], item["text"]))
        except (ValueError, TypeError):
            continue
    if out:
        return out
    pattern = re.compile(r'"chunk_id":\s*"([^"\\]+)".*?"doc_id":\s*"([^"\\]+)".*?'
                         r'"clause_ref":\s*"([^"\\]+)".*?"text":\s*"((?:[^"\\]|\\.)*)"', re.S)
    for cid, did, ref, text in pattern.findall(prompt):
        try:
            out.append(Passage(cid, did, ref, json.loads(f'"{text}"')))
        except json.JSONDecodeError:
            pass
    return out


def _cite(passages: list[Passage], doc: str, ref: str) -> dict:
    for passage in passages:
        if passage.doc_id == doc and passage.clause_ref == ref:
            return passage.citation()
    # Deliberately invalid: a broken tool loop must escalate at verification.
    return {"chunk_id": "missing", "quote": "missing retrieved passage"}


def _plan(bid: dict) -> list[dict]:
    get = lambda doc, ref: {"action": "tool", "tool": "get_clause", "args": {"doc_id": doc, "clause_ref": ref}}
    base = [get("TENDER-NITR-390", "Clause 5"), get("TENDER-NITR-390", "Clause 6")]
    if bid.get("bidder_category_claimed") == "startup":
        return base + [get("TENDER-NITR-390", "Clause 3"), get("DOE-OM-2016-07-25", "Para 3"),
                       get("DOE-OM-2016-09-20", "Para 2"), get("GFR-2017-CH6", "Rule 173(i)")]
    if bid.get("bidder_category_claimed") == "mse":
        return base + [get("TENDER-NITR-390", "Clause 2"), get("MSME-CIRCULAR-2016-03-10", "Para 4"),
                       get("GFR-2017-CH6", "Rule 173(i)")]
    return base + [get("TENDER-NITR-390", "Clause 1"), get("TENDER-NITR-390", "Clause 11")]


def _final(bid: dict, passages: list[Passage]) -> dict:
    category, turnover = bid.get("bidder_category_claimed"), float(bid.get("avg_annual_turnover_inr", 0))
    documents = set(bid.get("documents_submitted", []))
    c5, c6 = _cite(passages, "TENDER-NITR-390", "Clause 5"), _cite(passages, "TENDER-NITR-390", "Clause 6")
    if category == "startup":
        c3 = _cite(passages, "TENDER-NITR-390", "Clause 3")
        policies = [_cite(passages, "DOE-OM-2016-07-25", "Para 3"), _cite(passages, "DOE-OM-2016-09-20", "Para 2"), _cite(passages, "GFR-2017-CH6", "Rule 173(i)")]
        if not (bid.get("dpiit_recognition_number") or "dpiit_certificate" in documents):
            return {"action": "final", "route": "seek_clarification", "summary": "The claimed startup EMD exemption cannot be confirmed without DPIIT evidence.", "conditions": [{"condition": "EMD / bid security", "clause_ref": "Clause 3", "status": "unclear", "evidence": "DPIIT recognition evidence is absent.", "citations": [c3]}], "citations": [c3], "committee_questions": ["Provide the DPIIT recognition certificate."], "escalation_reason": None}
        return {"action": "final", "route": "escalate_to_human", "summary": "Tender turnover and experience conditions conflict with startup-relaxation policy provisions; committee review is required.", "conditions": [{"condition": "turnover", "clause_ref": "Clause 5", "status": "unmet", "evidence": f"Bid turnover is Rs. {turnover:,.0f}, below Rs. 1,50,00,000.", "citations": [c5]}, {"condition": "experience", "clause_ref": "Clause 6", "status": "unmet", "evidence": "The bid reports no similar-work supply experience.", "citations": [c6]}, {"condition": "EMD / bid security", "clause_ref": "Clause 3", "status": "met", "evidence": "DPIIT evidence and declaration are supplied.", "citations": [c3]}], "citations": [c5, c6, c3, *policies], "committee_questions": ["Does Rule 173(i) apply where this tender has no suitable provision?", "Does the bidder meet the quality and technical specifications?"], "escalation_reason": "tender_policy_conflict_or_undecidable"}
    if category == "mse":
        c2 = _cite(passages, "TENDER-NITR-390", "Clause 2")
        policies = [_cite(passages, "MSME-CIRCULAR-2016-03-10", "Para 4"), _cite(passages, "GFR-2017-CH6", "Rule 173(i)")]
        reason = "The committee must confirm whether the bidder is a trader excluded from the MSE EMD benefit." if bid.get("is_trader") else "The tender and MSE relaxation provisions require committee review."
        return {"action": "final", "route": "escalate_to_human", "summary": reason, "conditions": [{"condition": "turnover", "clause_ref": "Clause 5", "status": "unmet" if turnover < 15_000_000 else "met", "evidence": f"Bid turnover is Rs. {turnover:,.0f}.", "citations": [c5]}, {"condition": "EMD / bid security", "clause_ref": "Clause 2", "status": "unclear" if bid.get("is_trader") else "met", "evidence": "MSE exemption requires the tender conditions.", "citations": [c2]}], "citations": [c5, c2, *policies], "committee_questions": [reason], "escalation_reason": "tender_policy_conflict_or_undecidable"}
    c1, c11 = _cite(passages, "TENDER-NITR-390", "Clause 1"), _cite(passages, "TENDER-NITR-390", "Clause 11")
    if turnover < 15_000_000:
        return {"action": "final", "route": "reject_with_cited_condition", "summary": "The stated turnover is below the tender minimum; this is a screening finding for committee action.", "conditions": [{"condition": "turnover", "clause_ref": "Clause 5", "status": "unmet", "evidence": f"Bid turnover is Rs. {turnover:,.0f}, below Rs. 1,50,00,000.", "citations": [c5]}], "citations": [c5], "committee_questions": [], "escalation_reason": None}
    if bid.get("turnover_years_reported", 3) < 3 or bid.get("turnover_certificate_covers_three_years") is False:
        return {"action": "final", "route": "seek_clarification", "summary": "The turnover evidence does not demonstrate the required three financial years.", "conditions": [{"condition": "turnover evidence", "clause_ref": "Clause 5", "status": "unclear", "evidence": "The submitted turnover period is incomplete.", "citations": [c5]}], "citations": [c5], "committee_questions": ["Provide turnover evidence covering all required financial years."], "escalation_reason": None}
    missing = {"oem_authorization", "data_sheet"} - documents
    if missing:
        return {"action": "final", "route": "reject_with_cited_condition", "summary": "Required tender documents are missing; this is a screening finding for committee action.", "conditions": [{"condition": "mandatory documents", "clause_ref": "Clause 11", "status": "unmet", "evidence": "Missing: " + ", ".join(sorted(missing)) + ".", "citations": [c11]}], "citations": [c11], "committee_questions": [], "escalation_reason": None}
    return {"action": "final", "route": "pass_to_technical_evaluation", "summary": "The supplied summary meets the screened mandatory conditions and should proceed to technical evaluation.", "conditions": [{"condition": "turnover", "clause_ref": "Clause 5", "status": "met", "evidence": f"Bid turnover is Rs. {turnover:,.0f}, meeting the tender minimum.", "citations": [c5]}, {"condition": "experience", "clause_ref": "Clause 6", "status": "met", "evidence": "The bid reports similar-work experience.", "citations": [c6]}, {"condition": "EMD / bid security", "clause_ref": "Clause 1", "status": "met", "evidence": "The bid records EMD payment.", "citations": [c1]}, {"condition": "mandatory documents", "clause_ref": "Clause 11", "status": "met", "evidence": "The required documents are present in the bid summary.", "citations": [c11]}], "citations": [c5, c6, c1, c11], "committee_questions": [], "escalation_reason": None}


def _compliance(prompt: str) -> dict:
    bid, plan = _bid(prompt), _plan(_bid(prompt))
    completed = prompt.count("TOOL_RESULT:")
    return plan[completed] if completed < len(plan) else _final(bid, _passages(prompt))


@app.post("/v1/generate")
async def generate(payload: dict) -> dict:
    await asyncio.sleep(DELAY_MS / 1000)
    step, prompt = payload.get("step", ""), payload.get("prompt", "")
    body = {"classifier": _classifier, "compliance": _compliance}.get(step)
    out = body(prompt) if body else {"verdict": "pass", "issues": [], "suggested_strategy": ""}
    return {"text": json.dumps(out), "usage": {"prompt_tokens": max(1, len(prompt) // 4), "completion_tokens": 150}}
