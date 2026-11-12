from pathlib import Path
import json

import pytest

from eval.compare import compare
from eval.run import quality_metrics
from eval.scenarios import twenty


def test_evaluation_set_has_twenty_supported_cases_including_b1():
    data_path = Path(__file__).parents[1] / "eval" / "bidders.json"
    scenarios = twenty(json.loads(data_path.read_text()))
    assert len(scenarios) == 20
    assert len({item["id"] for item in scenarios}) == 20
    assert all(item.get("expected_route") and item.get("expected_support") for item in scenarios)
    assert all(
        passage.get("doc_id") and passage.get("clause_ref") and len(passage.get("passage", "")) > 30
        for item in scenarios
        for passage in item["expected_support"]
    )
    b1 = next(item for item in scenarios if item["id"] == "B1")
    assert b1["expected_route"] == "escalate_to_human"
    assert any(
        passage["doc_id"] == "GFR-2017-CH6" and passage["clause_ref"] == "Rule 173(i)"
        for passage in b1["expected_support"]
    )


def test_quality_metrics_deduplicate_citations_and_score_evidence():
    result = {
        "expected": "escalate_to_human",
        "expected_support": [{"doc_id": "DOC", "clause_ref": "Clause 1", "passage": "support"}],
        "result": {"finding": {
            "verification": {"passed": True},
            "citations": [{"doc_id": "DOC", "clause_ref": "Clause 1"}],
            "conditions": [
                {"evidence": "supported", "citations": [{"doc_id": "DOC", "clause_ref": "Clause 1"}]},
            ],
        }},
    }
    metrics = quality_metrics([result])
    assert metrics["evaluated_scenarios"] == 1
    assert metrics["groundedness"] == 1
    assert metrics["context_relevance"] == 1
    assert metrics["faithfulness"] == 1
    assert metrics["hallucination_rate"] == 0
    assert metrics["counts"]["all_unique_citations"] == 1


def test_quality_metrics_count_missing_finding_as_failure():
    metrics = quality_metrics([
        {"expected": "pass_to_technical_evaluation",
         "expected_support": [{"doc_id": "DOC", "clause_ref": "Clause 1", "passage": "support"}],
         "result": {"status": "failed"}}
    ])
    assert metrics["groundedness"] == 0
    assert metrics["context_relevance"] == 0
    assert metrics["faithfulness"] == 0
    assert metrics["hallucination_rate"] == 1


def test_quality_metrics_exclude_quarantined_intake_cases():
    metrics = quality_metrics([
        {"expected": "quarantine", "expected_support": [], "result": {"status": "quarantined"}}
    ])
    assert metrics["evaluated_scenarios"] == 0


def test_prompt_comparison_rejects_different_scenario_sets():
    metrics = {name: 1 for name in (
        "groundedness", "context_relevance", "faithfulness", "hallucination_rate"
    )}
    v1 = {"prompt_version": "v1", "total": 1, "results": [{"id": "B1"}],
          "route_accuracy": 1, "metrics": metrics}
    v2 = {"prompt_version": "v2", "total": 1, "results": [{"id": "B2"}],
          "route_accuracy": 1, "metrics": metrics}
    with pytest.raises(ValueError):
        compare(v1, v2)


def test_prompt_comparison_uses_hallucination_lower_is_better():
    metrics_v1 = {"groundedness": 0.8, "context_relevance": 0.8,
                  "faithfulness": 0.8, "hallucination_rate": 0.2}
    metrics_v2 = {"groundedness": 0.9, "context_relevance": 0.9,
                  "faithfulness": 0.9, "hallucination_rate": 0.1}
    v1 = {"prompt_version": "v1", "total": 1, "results": [{"id": "B1"}],
          "route_accuracy": 0.8, "metrics": metrics_v1}
    v2 = {"prompt_version": "v2", "total": 1, "results": [{"id": "B1"}],
          "route_accuracy": 0.9, "metrics": metrics_v2}
    report = compare(v1, v2)
    assert report["winner"] == "v2"
