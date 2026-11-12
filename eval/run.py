"""Run the fixed L3 evaluation set against a running API.

Usage:
  EVAL_API_URL=http://api:8000 python -m eval.run

The default command always writes its report, even when scenarios fail. Set
EVAL_FAIL_ON_ROUTE_ERRORS=1 in CI when a non-zero exit is desired.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from eval.scenarios import twenty

BASE_URL = os.getenv("EVAL_API_URL", "http://api:8000").rstrip("/")
POLL_SECONDS = float(os.getenv("EVAL_POLL_SECONDS", "1"))
TIMEOUT_SECONDS = float(os.getenv("EVAL_TIMEOUT_SECONDS", "180"))


def _finding(item: dict) -> dict:
    return (item.get("result") or {}).get("finding") or {}


def _citation_refs(finding: dict) -> set[tuple[str, str]]:
    """Collect unique document/clause references from finding and conditions."""
    refs: set[tuple[str, str]] = set()
    citations = list(finding.get("citations") or [])
    for condition in finding.get("conditions") or []:
        if isinstance(condition, dict):
            citations.extend(condition.get("citations") or [])
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        doc_id, clause_ref = citation.get("doc_id"), citation.get("clause_ref")
        if doc_id and clause_ref:
            refs.add((str(doc_id), str(clause_ref)))
    return refs


def quality_metrics(results: list[dict]) -> dict:
    """Compute deterministic L3 metrics over in-scope cases.

    Groundedness: verified findings / all evaluated scenarios.
    Context relevance: unique cited document/clause references matching the
      scenario's labelled supporting passages / all unique cited references.
    Faithfulness: verified findings with a citation on every condition containing
      an evidence statement / all evaluated scenarios.
    Hallucination rate: 1 - faithfulness.

    Timeouts and failed runs remain in the denominator as unsuccessful findings.
    Quarantine-only intake cases are excluded because no model or retrieval call
    should be made for them; the contract and guardrail tests cover those cases.
    """
    eligible = [item for item in results if item.get("expected") != "quarantine"]
    total = len(eligible)
    grounded_count = relevant_citations = all_citations = faithful_count = 0
    support_covered = support_total = 0

    for item in eligible:
        finding = _finding(item)
        verified = bool((finding.get("verification") or {}).get("passed"))
        grounded_count += int(verified)

        expected = {(passage["doc_id"], passage["clause_ref"])
                    for passage in item.get("expected_support", [])}
        actual = _citation_refs(finding)
        relevant_citations += len(actual & expected)
        all_citations += len(actual)
        support_covered += len(actual & expected)
        support_total += len(expected)

        conditions = finding.get("conditions") or []
        all_evidence_cited = bool(finding) and bool(conditions) and all(
            not str(condition.get("evidence", "")).strip()
            or bool(condition.get("citations"))
            for condition in conditions
            if isinstance(condition, dict)
        )
        faithful_count += int(verified and all_evidence_cited and bool(actual))

    return {
        "evaluated_scenarios": total,
        "groundedness": grounded_count / total if total else 0.0,
        "context_relevance": relevant_citations / all_citations if all_citations else 0.0,
        "faithfulness": faithful_count / total if total else 0.0,
        "hallucination_rate": 1 - (faithful_count / total) if total else 0.0,
        "counts": {
            "grounded_findings": grounded_count,
            "relevant_citations": relevant_citations,
            "all_unique_citations": all_citations,
            "expected_support_passages_cited": support_covered,
            "expected_support_passages": support_total,
            "faithful_findings": faithful_count,
        },
    }


def run_scenario(client: httpx.Client, scenario: dict) -> dict:
    submitted = client.post(f"{BASE_URL}/v1/screenings", json=scenario["bid"])
    if submitted.status_code == 422:
        result = submitted.json()
        actual = "quarantine"
    else:
        submitted.raise_for_status()
        run_id = submitted.json()["run_id"]
        deadline = time.monotonic() + TIMEOUT_SECONDS
        result = {"run_id": run_id, "status": "timed_out"}
        while time.monotonic() < deadline:
            response = client.get(f"{BASE_URL}/v1/screenings/{run_id}")
            response.raise_for_status()
            result = response.json()
            if result.get("status") in ("done", "escalated", "failed"):
                break
            time.sleep(POLL_SECONDS)
        actual = (result.get("finding") or {}).get("route", result.get("status", "unknown"))

    return {
        "id": scenario["id"],
        "description": scenario.get("description", ""),
        "expected": scenario["expected_route"],
        "actual": actual,
        "expected_support": scenario.get("expected_support", []),
        "passed": actual == scenario["expected_route"],
        "result": result,
    }


def main() -> None:
    data_path = Path(__file__).with_name("bidders.json")
    scenarios = twenty(json.loads(data_path.read_text()))
    if len(scenarios) < 20 or any(not item.get("expected_support") for item in scenarios):
        raise ValueError("L3 requires at least 20 scenarios, each with expected outcome and supporting passage")

    results: list[dict] = []
    with httpx.Client(timeout=30) as client:
        for scenario in scenarios:
            results.append(run_scenario(client, scenario))

    passed = sum(item["passed"] for item in results)
    metrics = quality_metrics(results)
    prompt_versions = {}
    for item in results:
        finding = _finding(item)
        for agent, version in (finding.get("prompt_versions") or {}).items():
            prompt_versions.setdefault(agent, set()).add(version)

    report = {
        "evaluation": "L3 fixed tender-bid screening evaluation",
        "prompt_version": os.getenv("COMPLIANCE_PROMPT_VERSION", os.getenv("PROMPT_VERSION", "v1")),
        "prompt_versions_observed": {agent: sorted(versions) for agent, versions in prompt_versions.items()},
        "provider": os.getenv("LLM_PROVIDER", "configured"),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "route_accuracy": passed / len(results) if results else 0.0,
        "metric_definitions": {
            "groundedness": "verified findings / all in-scope scenarios",
            "context_relevance": "unique cited document-clause references matching labelled support / all unique cited references",
            "faithfulness": "verified findings with citations on every evidence-bearing condition / all in-scope scenarios",
            "hallucination_rate": "1 - faithfulness",
        },
        "metrics": metrics,
        "results": results,
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if output := os.getenv("EVAL_OUTPUT_PATH"):
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n")

    if os.getenv("EVAL_FAIL_ON_ROUTE_ERRORS", "0").lower() in {"1", "true", "yes"} and passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
