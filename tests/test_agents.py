"""Agent flow with a scripted LLM and an in-memory corpus (no model download, no network)."""
import json

from common.llm import LLMError, LLMResult
from worker.agents import parse_json, run_screening
from worker.retrieval import CorpusTools

CHUNK = {"chunk_id": "T:p2:clause5", "doc_id": "TENDER-NITR-390", "clause_ref": "Clause 5", "page": 2,
         "doc_type": "tender", "status": "live", "date": "2026-11-05",
         "text": "The minimum average annual financial turnover of the bidder should be Rs. 1,50,00,000"}


POLICY = dict(CHUNK, chunk_id="P:p1:para1", doc_id="DOE-OM-2016-09-20", clause_ref="Para 2", doc_type="policy",
              text="criteria of prior turnover and prior experience for all Startups is relaxed")


class FakeTools(CorpusTools):
    def search_corpus(self, query, source_filter="any", k=4):
        self.calls += 1
        return [self._record(CHUNK), self._record(POLICY)]


class Scripted:
    def __init__(self, compliance_replies, category="startup", verdict="pass"):
        self.replies, self.category, self.verdict = list(compliance_replies), category, verdict

    def generate(self, prompt, *, prompt_version, step, run_id):
        if step == "classifier":
            out = {"category": self.category}
        elif step == "verifier":
            out = {"verdict": self.verdict, "issues": ["unsupported"] if self.verdict != "pass" else []}
        else:
            out = self.replies.pop(0)
        return LLMResult(json.dumps(out), 10, 5, 0.0, 1.0)


SEARCH = {"action": "tool", "tool": "search_corpus", "args": {"query": "turnover"}}
GOOD = {"action": "final", "route": "escalate_to_human", "summary": "s", "committee_questions": ["q"],
        "conditions": [{"condition": "turnover", "clause_ref": "Clause 5", "status": "unmet", "evidence": "e",
                        "citations": [{"chunk_id": "T:p2:clause5", "quote": "should be Rs. 1,50,00,000"}]}],
        "citations": [{"chunk_id": "T:p2:clause5", "quote": "should be Rs. 1,50,00,000"}]}
BID = {"bidder_category_claimed": "startup"}


def run(llm, bid=BID):
    return run_screening("r1", bid, [], llm, FakeTools(bid))[0]


def test_parse_json_tolerates_prose():
    assert parse_json('Sure: ```json\n{"a": {"b": "}"}}\n``` done') == {"a": {"b": "}"}}


def test_verified_run_returns_cited_finding():
    good = json.loads(json.dumps(GOOD))
    good["conditions"][0]["status"] = "met"
    f = run(Scripted([SEARCH, good]))
    assert f.route == "escalate_to_human" and f.verification.passed
    assert f.citations[0].doc_id == "TENDER-NITR-390" and f.tool_calls == 1


def test_fabricated_citation_never_returned_confidently():
    bad = dict(GOOD, route="reject_with_cited_condition", citations=[{"chunk_id": "T:p2:clause5", "quote": "invented"}],
               conditions=[])
    f = run(Scripted([SEARCH, bad, bad]))
    assert f.route == "escalate_to_human" and f.escalation_reason == "verification_failed"


def test_verifier_fail_retries_then_escalates():
    f = run(Scripted([SEARCH, GOOD, GOOD], verdict="fail"))
    assert f.escalation_reason == "verification_failed" and f.verification.attempts == 2


def test_unbounded_loop_is_cut_off():
    f = run(Scripted([SEARCH] * 50))
    assert f.escalation_reason == "run_incomplete"


def test_category_mismatch_and_unsupported_categories_escalate():
    assert run(Scripted([], category="large_enterprise")).escalation_reason == "bidder_category_unclear"
    f = run(Scripted([], category="foreign"), {"bidder_category_claimed": "foreign"})
    assert f.escalation_reason == "corpus_cannot_answer"


def test_llm_failure_escalates():
    class Down:
        def generate(self, *a, **k):
            raise LLMError("down")
    assert run(Down()).escalation_reason == "llm_unavailable"


def test_startup_finding_without_policy_search_fails_verification():
    class TenderOnly(FakeTools):
        def search_corpus(self, query, source_filter="any", k=4):
            self.calls += 1
            return [self._record(CHUNK)]
    f = run_screening("r1", BID, [], Scripted([SEARCH, GOOD, GOOD]), TenderOnly(BID))[0]
    assert f.escalation_reason == "verification_failed"


def test_startup_unmet_turnover_requires_rule_173i():
    # POLICY fake chunk is not GFR Rule 173(i), so an unmet turnover for a startup must fail verification
    f = run(Scripted([SEARCH, GOOD, GOOD]))
    assert f.escalation_reason == "verification_failed"
    assert any("173(i)" in i for i in f.verification.issues)


def test_startup_must_cite_both_doe_orders_and_emd_clause():
    class Full(FakeTools):
        def search_corpus(self, query, source_filter="any", k=4):
            self.calls += 1
            return [self._record(CHUNK), self._record(POLICY), self._record(dict(POLICY, chunk_id="G:173i", doc_id="GFR-2017-CH6", clause_ref="Rule 173(i)"))]
    bid = {"bidder_category_claimed": "startup", "emd_exemption_claimed": True}
    f = run_screening("r1", bid, [], Scripted([SEARCH, GOOD, GOOD]), Full(bid))[0]
    assert f.escalation_reason == "verification_failed"
    text = " ".join(f.verification.issues)
    assert "DOE-OM-2016-07-25" in text and "Clause 3" in text


def test_paid_emd_requires_clause_1_citation():
    good = json.loads(json.dumps(GOOD))
    good["route"] = "pass_to_technical_evaluation"
    good["conditions"][0]["status"] = "met"
    bid = {"bidder_category_claimed": "large_enterprise", "emd_paid_inr": 100000}
    f = run(Scripted([SEARCH, good, good], category="large_enterprise"), bid)
    assert f.escalation_reason == "verification_failed"
    assert any("Clause 1" in issue for issue in f.verification.issues)
