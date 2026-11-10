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
                            "passed": actual == scenario["expected_route"], "result": result})
    passed = sum(item["passed"] for item in results)
    verified = [bool(x["result"].get("finding", {}).get("verification", {}).get("passed")) for x in results]
    cited = [bool(x["result"].get("finding", {}).get("citations")) for x in results]
    grounded = sum(verified) / len(results)
    report = {"prompt_version": os.getenv("PROMPT_VERSION", "v1"), "total": len(results), "passed": passed,
              "route_accuracy": passed / len(results), "metrics": {"groundedness": grounded,
              "context_relevance": sum(cited) / len(results), "faithfulness": grounded,
              "hallucination_rate": 1 - grounded}, "results": results}
    print(json.dumps(report, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
