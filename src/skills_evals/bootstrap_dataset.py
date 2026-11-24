"""Create or synchronize the versioned demo cases in Braintrust."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from braintrust import init_dataset

from skills_evals.runner import ROOT

PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
PROJECT_ID = os.getenv("BRAINTRUST_PROJECT_ID")
ORG = os.getenv("BRAINTRUST_ORG_NAME")
DATASET_NAME = os.getenv("BRAINTRUST_DATASET_NAME", "codex-skills-demo-v1")
DATASET_PATH = Path(os.getenv("CODEX_EVAL_DATASET", str(ROOT / "data" / "demo.jsonl"))).resolve()


def main() -> None:
    if not (PROJECT and PROJECT_ID and ORG):
        raise RuntimeError(
            "Set BRAINTRUST_ORG_NAME, BRAINTRUST_DEFAULT_PROJECT, and "
            "BRAINTRUST_PROJECT_ID to the explicit Braintrust destination"
        )
    rows = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    digest = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    dataset = init_dataset(
        project=PROJECT,
        project_id=PROJECT_ID,
        org_name=ORG,
        name=DATASET_NAME,
        description="Versioned cases for evaluating Codex skill output quality.",
        metadata={"source_sha256": digest, "source_file": DATASET_PATH.name},
    )
    existing = {row.get("id"): row for row in dataset.fetch() if row.get("id")}
    for case in rows:
        record = {
            "input": {**case["input"], "_case_id": case["id"]},
            "expected": case["expected"],
            "metadata": {
                "case_id": case["id"],
                "prompt_condition": case["input"].get("prompt_condition", "unspecified"),
                "dataset_sha256": digest,
            },
            "tags": ["codex-skills-eval", case["input"].get("prompt_condition", "unspecified")],
        }
        if case["id"] in existing:
            dataset.update(id=case["id"], **record)
        else:
            dataset.insert(id=case["id"], **record)
    dataset.flush()
    print(
        json.dumps(
            {
                "project": PROJECT,
                "project_id": PROJECT_ID,
                "dataset": DATASET_NAME,
                "dataset_id": dataset.id,
                "rows": len(rows),
                "source_sha256": digest,
            }
        )
    )
    dataset.close()


if __name__ == "__main__":
    main()
