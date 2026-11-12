"""Compare v1 and v2 on the same fixed L3 evaluation set."""
from __future__ import annotations

import json
import os
from pathlib import Path

DIRECTIONS = {
    "route_accuracy": "higher",
    "groundedness": "higher",
    "context_relevance": "higher",
    "faithfulness": "higher",
    "hallucination_rate": "lower",
}


def _value(report: dict, name: str) -> float:
    if name == "route_accuracy":
        return float(report["route_accuracy"])
    return float(report["metrics"][name])


def _scenario_ids(report: dict) -> list[str]:
    return [str(item["id"]) for item in report.get("results", [])]


def compare(before: dict, after: dict) -> dict:
    before_ids, after_ids = _scenario_ids(before), _scenario_ids(after)
    if before.get("total") != after.get("total") or before_ids != after_ids:
        raise ValueError(
            "Prompt variants must be evaluated on the exact same ordered scenario set; "
            f"v1 has {len(before_ids)} cases and v2 has {len(after_ids)} cases."
        )

    results = {}
    candidate_is_never_worse = True
    baseline_is_never_worse = True
    candidate_strictly_better = False
    baseline_strictly_better = False

    for name, direction in DIRECTIONS.items():
        v1, v2 = _value(before, name), _value(after, name)
        delta = v2 - v1
        improved = delta > 0 if direction == "higher" else delta < 0
        regressed = delta < 0 if direction == "higher" else delta > 0
        results[name] = {
            "v1": v1,
            "v2": v2,
            "delta_v2_minus_v1": delta,
            "change_percentage_points": delta * 100,
            "better": "v2" if improved else ("v1" if regressed else "tie"),
        }
        if regressed:
            candidate_is_never_worse = False
        if improved:
            baseline_is_never_worse = False
        candidate_strictly_better |= improved
        baseline_strictly_better |= regressed

    if candidate_is_never_worse and candidate_strictly_better:
        winner = "v2"
    elif baseline_is_never_worse and baseline_strictly_better:
        winner = "v1"
    elif not candidate_strictly_better and not baseline_strictly_better:
        winner = "tie"
    else:
        winner = "no_single_winner_tradeoff"

    return {
        "evaluation": "L3 paired prompt comparison",
        "baseline": before["prompt_version"],
        "candidate": after["prompt_version"],
        "same_dataset": True,
        "scenario_count": before["total"],
        "scenario_ids": before_ids,
        "winner": winner,
        "metric_results": results,
        "metric_definitions": before.get("metric_definitions", {}),
        "note": (
            "Positive deltas favour v2 for higher-is-better metrics; negative deltas "
            "favour v2 for hallucination_rate. A single winner is declared only when "
            "one version is no worse on every reported metric and better on at least one."
        ),
    }


def main() -> None:
    before = json.loads(Path(os.getenv("EVAL_V1_PATH", "/artifacts/eval-v1.json")).read_text())
    after = json.loads(Path(os.getenv("EVAL_V2_PATH", "/artifacts/eval-v2.json")).read_text())
    report = compare(before, after)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if output := os.getenv("EVAL_COMPARISON_PATH"):
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n")


if __name__ == "__main__":
    main()
