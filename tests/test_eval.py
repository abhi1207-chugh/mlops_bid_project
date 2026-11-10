from eval.run import quality_metrics
from eval.scenarios import twenty


def test_evaluation_set_has_twenty_cases_and_expected_support():
    import json
    scenarios = twenty(json.load(open("/app/eval/bidders.json")))
    assert len(scenarios) == 20
    b1 = next(item for item in scenarios if item["id"] == "B1")
    assert ("GFR-2017-CH6", "Rule 173(i)") in b1["expected_support"]


def test_quality_metrics_distinguish_relevant_verified_finding():
    result = {"expected": "escalate_to_human", "expected_support": [("DOC", "Clause 1")], "result": {"finding": {
        "verification": {"passed": True}, "citations": [{"doc_id": "DOC", "clause_ref": "Clause 1"}],
        "conditions": [{"evidence": "supported", "citations": [{"chunk_id": "x"}]}],
    }}}
    metrics = quality_metrics([result])
    assert metrics["groundedness"] == metrics["context_relevance"] == metrics["faithfulness"] == 1
    assert metrics["hallucination_rate"] == 0
