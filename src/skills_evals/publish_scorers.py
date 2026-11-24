"""Publish additive demo scorers; replacement must be requested explicitly."""

from __future__ import annotations

import os
from typing import Any

import braintrust
from pydantic import BaseModel

from skills_evals.scoring import mechanical_format_result

PROJECT_NAME = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
if not PROJECT_NAME:
    raise RuntimeError("Set BRAINTRUST_DEFAULT_PROJECT to the explicit scorer destination")

JUDGE_MODEL = os.getenv("CODEX_JUDGE_MODEL", "gpt-5-mini")
IF_EXISTS = os.getenv("SCORER_IF_EXISTS", "error")
if IF_EXISTS not in {"error", "ignore", "replace"}:
    raise RuntimeError("SCORER_IF_EXISTS must be error, ignore, or replace")

project = braintrust.projects.create(name=PROJECT_NAME)


class ScorerInput(BaseModel):
    output: Any
    expected: dict[str, Any]


def mechanical_format_scorer(output: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Check word limits and exact section headings only."""
    return mechanical_format_result(str(output or ""), expected or {})


project.scorers.create(
    name="Mechanical format",
    slug="mechanical-format-v1",
    description="Checks word limits and required headings; does not judge factual or semantic correctness.",
    parameters=ScorerInput,
    handler=mechanical_format_scorer,
    metadata={"scorer_kind": "deterministic", "version": 1},
    tags=["skills_evals", "offline-eval", "mechanical"],
    if_exists=IF_EXISTS,
)

project.scorers.create(
    name="Relationship accuracy",
    slug="relationship-accuracy-v1",
    description=(
        "LLM judge comparing actions, owners, deadlines, commitment status, and uncertainty "
        "against a structured expected ledger. Calibrated on labeled negation and fabrication cases."
    ),
    messages=[
        {
            "role": "user",
            "content": """Judge the response against the task and structured expected relationships.

Task and source information:
{{input}}

Expected relationship ledger:
{{expected}}

Candidate response:
{{output}}

Assess meaning, not word overlap. Check whether every stated action has the correct owner and deadline, whether it was actually committed to, and whether discussion-only ideas remain non-commitments. Also check material facts and uncertainty where listed. Interpret negation and modality: for example, “has not recovered” and “recovery is unconfirmed” do not claim recovery. A word appearing in a prohibited-claim description is not itself a violation.

Choose exactly one grade:
A — Accurate: all material relationships and claims match the source; no invented commitment, owner, date, or certainty.
B — Partial: the output only omits or obscures a meaningful detail. It contains no unsupported factual claim, invented deadline/owner/action, or reversed uncertainty.
C — Incorrect: any material action, owner, deadline, commitment state, negation, or uncertainty is reversed, invented, or contradicted. One fabricated deadline or false commitment is enough for C even when the other items are correct.

Calibration examples:
- Expected: Marco will investigate the bounced invite; no deadline was agreed; the dashboard is discussion only. Output: “Marco will investigate by Friday. The team will build the dashboard.” Grade C. Friday and the dashboard commitment are invented.
- Expected: recovery has not been confirmed; data impact is unknown. Output: “The service has not recovered. Data loss is not confirmed.” Grade A when the response otherwise preserves the unknowns. These are negated/uncertain statements, not claims of recovery or data safety.
- Expected: data impact is unknown. Output: “Data is safe and the service recovered.” Grade C. Both claims exceed the evidence.

Return the grade and a concise evidence-based rationale. Do not expose hidden chain-of-thought.""",
        }
    ],
    model=JUDGE_MODEL,
    use_cot=True,
    choice_scores={"A": 1.0, "B": 0.5, "C": 0.0},
    metadata={"scorer_kind": "llm_judge", "evaluation": "relationship_accuracy", "version": 1},
    tags=["skills_evals", "offline-eval", "semantic"],
    if_exists=IF_EXISTS,
)

project.publish()
