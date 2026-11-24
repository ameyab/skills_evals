from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from braintrust import Eval, init_dataset, init_function

from skills_evals.runner import ROOT, SKILLS_ROOT, file_tree_hash, run_case
from skills_evals.scoring import mechanical_format

PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
if not PROJECT:
    raise RuntimeError("Set BRAINTRUST_DEFAULT_PROJECT to the explicit Braintrust destination")
PROJECT_ID = os.getenv("BRAINTRUST_PROJECT_ID")
ORG = os.getenv("BRAINTRUST_ORG_NAME")
if not PROJECT_ID or not ORG:
    raise RuntimeError("Set BRAINTRUST_PROJECT_ID and BRAINTRUST_ORG_NAME explicitly")

DATASET_PATH = Path(os.getenv("CODEX_EVAL_DATASET", str(ROOT / "data" / "demo.jsonl"))).resolve()
EXPERIMENT_NAME = os.getenv("BRAINTRUST_EXPERIMENT_NAME")
if not EXPERIMENT_NAME:
    raise RuntimeError("Set BRAINTRUST_EXPERIMENT_NAME to identify this experiment")

MODEL = os.getenv("CODEX_MODEL", "gpt-6-luna")
SANDBOX = os.getenv("CODEX_SANDBOX", "read-only")
TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "300"))
ACTIVATION_MODE = os.getenv("SKILL_ACTIVATION_MODE", "injected")
SKILLS_REVISION = os.getenv("SKILLS_REVISION", "working-tree")
RELATIONSHIP_SCORER_SLUG = os.getenv("RELATIONSHIP_SCORER_SLUG", "relationship-accuracy-v1")
REMOTE_DATASET_NAME = os.getenv("BRAINTRUST_DATASET_NAME", "codex-skills-demo-v1")
JUDGE = init_function(PROJECT, RELATIONSHIP_SCORER_SLUG)
REMOTE_DATASET = init_dataset(
    project=PROJECT,
    project_id=PROJECT_ID,
    org_name=ORG,
    name=REMOTE_DATASET_NAME,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases() -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = {value.strip() for value in os.getenv("EVAL_CASE_IDS", "").split(",") if value.strip()}
    return [case for case in cases if not selected or case["id"] in selected]


CASES = load_cases()
if not CASES:
    raise RuntimeError("The selected eval dataset contains no cases")
UNKNOWN_CASE_IDS = {
    value.strip() for value in os.getenv("EVAL_CASE_IDS", "").split(",") if value.strip()
} - {case["id"] for case in CASES}
if UNKNOWN_CASE_IDS:
    raise RuntimeError(f"Unknown eval case IDs: {sorted(UNKNOWN_CASE_IDS)}")

DATASET_HASH = sha256_file(DATASET_PATH)
SKILL_HASHES = {
    name: file_tree_hash(SKILLS_ROOT / name)
    for name in sorted({case["input"].get("skill") for case in CASES if case["input"].get("skill")})
}
SKILL_MANIFEST_HASH = hashlib.sha256(
    json.dumps(SKILL_HASHES, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
CODEX_VERSION = subprocess.run(
    ["codex", "--version"], capture_output=True, text=True, check=True, timeout=15
).stdout.strip()


def selected_remote_cases():
    """Focused case runs use a filtered iterator over the versioned BT dataset."""
    for record in REMOTE_DATASET.fetch():
        if record.get("input", {}).get("_case_id") in {case["id"] for case in CASES}:
            yield record


def task(input: dict[str, Any], hooks=None) -> str:
    case_id = input.get("_case_id", "eval-case")
    case_input = {key: value for key, value in input.items() if key != "_case_id"}
    eval_metadata = hooks.metadata if hooks is not None else None
    return run_case(
        {"id": case_id, "input": case_input},
        trace=True,
        project=PROJECT,
        trace_metadata={
            "dataset_sha256": DATASET_HASH,
            "skill_manifest_sha256": SKILL_MANIFEST_HASH,
            "codex_cli_version": CODEX_VERSION,
            "codex_timeout_seconds": TIMEOUT_SECONDS,
        },
        parent_span_export=hooks.span.export() if hooks is not None else None,
        eval_metadata=eval_metadata,
        activation_mode=ACTIVATION_MODE,
    )


def run_eval():
    comparison = os.getenv("COMPARE_TO_EXPERIMENT")
    selected_ids = {value.strip() for value in os.getenv("EVAL_CASE_IDS", "").split(",") if value.strip()}
    eval_data = selected_remote_cases if selected_ids else REMOTE_DATASET
    Eval(
        PROJECT,
        data=eval_data,
        task=task,
        scores=[mechanical_format, JUDGE],
        experiment_name=EXPERIMENT_NAME,
        base_experiment_name=comparison,
        metadata={
            "harness": "codex exec --json + bt trace import",
            "skills_revision_label": SKILLS_REVISION,
            "skill_manifest_sha256": SKILL_MANIFEST_HASH,
            "dataset_sha256": DATASET_HASH,
            "codex_cli_version": CODEX_VERSION,
            "codex_model": MODEL,
            "codex_sandbox": SANDBOX,
            "codex_timeout_seconds": TIMEOUT_SECONDS,
            "skill_activation_mode": ACTIVATION_MODE,
            "case_ids": [case["id"] for case in CASES],
        },
        tags=["codex-skills-eval", "offline-eval", ACTIVATION_MODE],
        timeout=int(os.getenv("BRAINTRUST_EVAL_TIMEOUT_SECONDS", "3600")),
        max_concurrency=1,
        description=(
            "Codex skill quality experiment. Relationship accuracy is LLM-judged against "
            "structured expected facts; mechanical_format checks presentation only."
        ),
    )


run_eval()
