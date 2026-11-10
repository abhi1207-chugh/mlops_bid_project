"""Run the committed evaluation scenarios against a running API.

Usage: EVAL_API_URL=http://api:8000 python -m eval.run
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
TIMEOUT_SECONDS = float(os.getenv("EVAL_TIMEOUT_SECONDS", "120"))


def quality_metrics(results: list[dict]) -> dict:
    """Deterministic equivalent of a groundedness evaluator.

    Groundedness is an independently verified finding; context relevance means a
    citation contains one of the scenario's expected corpus passages; faithfulness
    requires every condition with evidence to carry a resolved citation; and the
    hallucination rate is the share of evaluated findings failing faithfulness.
    Invalid inputs are not included because they must never invoke retrieval/LLM.
    """
    eligible = [item for item in results if item["expected"] != "quarantine"]
    grounded = relevant = faithful = 0
    for item in eligible:
        finding = item["result"].get("finding") or {}
        verified = bool((finding.get("verification") or {}).get("passed"))
        citations = {(c.get("doc_id"), c.get("clause_ref")) for c in finding.get("citations", [])}
        expected = {tuple(pair) for pair in item.get("expected_support", [])}
        condition_cited = all(not c.get("evidence") or c.get("citations") for c in finding.get("conditions", []))
        grounded += verified
        relevant += bool(expected & citations)
        faithful += bool(verified and condition_cited)
    total = len(eligible)
    return {"evaluated_findings": total, "groundedness": grounded / total if total else 0,
            "context_relevance": relevant / total if total else 0,
            "faithfulness": faithful / total if total else 0,
            "hallucination_rate": 1 - (faithful / total) if total else 0}


def main() -> None:
    scenarios = twenty(json.loads(Path("/app/eval/bidders.json").read_text()))
    results: list[dict] = []
    with httpx.Client(timeout=20) as client:
        for scenario in scenarios:
            submitted = client.post(f"{BASE_URL}/v1/screenings", json=scenario["bid"])
            if submitted.status_code == 422:
                actual = "quarantine"
                result = submitted.json()
            else:
                submitted.raise_for_status()
                run_id = submitted.json()["run_id"]
                deadline = time.monotonic() + TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    result = client.get(f"{BASE_URL}/v1/screenings/{run_id}").json()
                    if result["status"] in ("done", "escalated", "failed"):
                        break
                    time.sleep(POLL_SECONDS)
                else:
                    result = {"status": "timed_out", "run_id": run_id}
                actual = result.get("finding", {}).get("route", result["status"])
            results.append({"id": scenario["id"], "expected": scenario["expected_route"], "actual": actual,
                            "expected_support": scenario.get("expected_support", []),
                            "passed": actual == scenario["expected_route"], "result": result})
    passed = sum(item["passed"] for item in results)
    report = {"prompt_version": os.getenv("PROMPT_VERSION", "v1"), "total": len(results), "passed": passed,
              "route_accuracy": passed / len(results), "metrics": quality_metrics(results), "results": results}
    print(json.dumps(report, indent=2))
    if output := os.getenv("EVAL_OUTPUT_PATH"):
        Path(output).write_text(json.dumps(report, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
