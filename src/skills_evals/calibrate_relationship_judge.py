"""Run the relationship judge against a small, human-labeled adversarial set."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from braintrust import Eval, init_function

ROOT = Path(__file__).resolve().parents[2]
PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
if not PROJECT:
    raise RuntimeError("Set BRAINTRUST_DEFAULT_PROJECT to the explicit Braintrust destination")

DATASET = ROOT / "data" / "relationship_calibration.jsonl"
SCORER_SLUG = os.getenv("RELATIONSHIP_SCORER_SLUG", "relationship-accuracy-v1")
EXPERIMENT_NAME = os.getenv("CALIBRATION_EXPERIMENT_NAME")
if not EXPERIMENT_NAME:
    raise RuntimeError("Set CALIBRATION_EXPERIMENT_NAME to identify this calibration run")

CALIBRATION_CASES = [
    json.loads(line)
    for line in DATASET.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
CASE_BY_ID = {case["id"]: case for case in CALIBRATION_CASES}
JUDGE = init_function(PROJECT, SCORER_SLUG)


def dataset():
    for case in CALIBRATION_CASES:
        yield {
            "input": {"case_id": case["id"], **case["input"]},
            "expected": case["expected"],
            "metadata": {
                "case_id": case["id"],
                "human_label": case["human_label"],
                "human_reason": case["human_reason"],
            },
            "tags": ["judge-calibration", "human-labeled"],
        }


def task(input: dict[str, Any]) -> str:
    return CASE_BY_ID[input["case_id"]]["output"]


def main() -> None:
    report = Eval(
        PROJECT,
        data=dataset,
        task=task,
        scores=[JUDGE],
        experiment_name=EXPERIMENT_NAME,
        metadata={
            "evaluation": "relationship-judge-calibration",
            "human_labeled": True,
            "calibration_dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
            "scorer_slug": SCORER_SLUG,
        },
        tags=["judge-calibration", "human-labeled"],
        max_concurrency=1,
        timeout=900,
    )

    exact = 0
    confusion: Counter[str] = Counter()
    rows = []
    for result in report.results:
        human = float((result.metadata or {})["human_label"])
        score_values = list(result.scores.values())
        predicted = float(score_values[0]) if score_values and score_values[0] is not None else None
        if predicted is not None:
            exact += int(abs(predicted - human) < 1e-8)
            confusion[f"human={human}:judge={predicted}"] += 1
        rows.append(
            {
                "case_id": (result.metadata or {}).get("case_id"),
                "human_label": human,
                "judge_score": predicted,
                "score_names": list(result.scores),
            }
        )

    accuracy = exact / len(rows) if rows else 0.0
    output_path = Path(os.getenv("CALIBRATION_REPORT_PATH", str(ROOT / "artifacts" / "relationship-calibration-latest.json")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "experiment_name": EXPERIMENT_NAME,
        "project": PROJECT,
        "scorer_slug": SCORER_SLUG,
        "case_count": len(rows),
        "exact_label_accuracy": accuracy,
        "confusion": dict(confusion),
        "cases": rows,
    }
    output_path.write_text(json.dumps(report_data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report_data, indent=2))


if __name__ == "__main__":
    main()
