"""Compare two persisted prompt-variant evaluation reports."""
from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    before = json.loads(Path(os.getenv("EVAL_V1_PATH", "/artifacts/eval-v1.json")).read_text())
    after = json.loads(Path(os.getenv("EVAL_V2_PATH", "/artifacts/eval-v2.json")).read_text())
    names = ("route_accuracy", "groundedness", "context_relevance", "faithfulness", "hallucination_rate")
    values = {name: {"v1": before.get(name, before["metrics"].get(name)),
                     "v2": after.get(name, after["metrics"].get(name))} for name in names}
    for item in values.values():
        item["delta"] = item["v2"] - item["v1"]
    report = {"baseline": before["prompt_version"], "candidate": after["prompt_version"], "metrics": values,
              "winner": "v2" if values["faithfulness"]["delta"] >= 0 and values["route_accuracy"]["delta"] >= 0 else "v1"}
    print(json.dumps(report, indent=2))
    if output := os.getenv("EVAL_COMPARISON_PATH"):
        Path(output).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
