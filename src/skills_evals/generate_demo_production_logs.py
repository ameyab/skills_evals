"""Generate synthetic Codex traces to exercise Braintrust online scoring."""

from __future__ import annotations

import os

from skills_evals.runner import run_case

PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT", "skills_evals")
TRACE_METADATA = {
    "traffic_type": "synthetic",
    "trace_source": "online_scoring_demo",
    "environment": "demo",
}

CASES = [
    {
        "id": "synthetic-production-customer-reply-001",
        "input": {
            "skill": "customer-reply",
            "title": "Explain a delayed shipment",
            "prompt": (
                "Write a reply to a customer whose package is four days late. "
                "Verified facts: the carrier scan shows the parcel at the regional "
                "facility this morning; the cause of the delay is not known; support "
                "will check again tomorrow if there is no new scan. Do not promise "
                "a delivery date or refund. Keep it under 100 words."
            ),
        },
    },
    {
        "id": "synthetic-production-meeting-actions-001",
        "input": {
            "skill": "meeting-actions",
            "title": "Separate commitments from discussion",
            "prompt": (
                "Turn these notes into concise action items and open questions. "
                "Notes: Priya will send the revised launch checklist by Friday. "
                "The analytics team will confirm whether the dashboard is ready, "
                "but no date was agreed. We discussed a possible pilot with two "
                "customers; nobody committed to running it."
            ),
        },
    },
    {
        "id": "synthetic-production-incident-handoff-001",
        "input": {
            "skill": "incident-handoff",
            "title": "Prepare a webhook delay handoff",
            "prompt": (
                "Create an internal incident handoff. Confirmed: webhook delivery "
                "latency rose above 20 minutes starting at 14:10 UTC; 18 customer "
                "integrations are affected; retries are still running. The cause "
                "and recovery time are unknown. Do not claim data loss or recovery. "
                "Include reasonable next investigation steps without inventing an owner."
            ),
        },
    },
]


def main() -> None:
    if not os.getenv("BRAINTRUST_ORG_NAME") or not os.getenv("BRAINTRUST_PROJECT_ID"):
        raise RuntimeError(
            "Set BRAINTRUST_ORG_NAME and BRAINTRUST_PROJECT_ID to the explicit Braintrust destination"
        )
    for case in CASES:
        print(f"Running {case['id']} through Codex and logging to {PROJECT}...", flush=True)
        output = run_case(
            case,
            trace=True,
            project=PROJECT,
            trace_metadata=TRACE_METADATA,
        )
        print(f"Completed {case['id']} ({len(output.split())} output words).", flush=True)


if __name__ == "__main__":
    main()
