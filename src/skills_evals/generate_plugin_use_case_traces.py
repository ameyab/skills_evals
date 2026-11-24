"""Generate production-shaped multi-span traces through the Codex tracing plugin."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORG = os.getenv("BRAINTRUST_ORG_NAME")
PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
PROJECT_ID = os.getenv("BRAINTRUST_PROJECT_ID")
MODEL = os.getenv("CODEX_MODEL", "gpt-6-luna")
SANDBOX = os.getenv("CODEX_SANDBOX", "read-only")
TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "300"))
SCENARIOS = [
    {
        "id": "meeting-launch-actions",
        "skill": "meeting-actions",
        "file": "meeting_notes.md",
        "contents": (
            "Priya will send the revised launch checklist by Thursday. The analytics team will "
            "investigate dashboard readiness, but no date was agreed. The team discussed a "
            "two-customer pilot; nobody committed to running it."
        ),
        "prompt": (
            "Read meeting_notes.md and summarize the action items, owners, deadlines, and "
            "discussion-only items using the meeting-actions skill."
        ),
    },
    {
        "id": "customer-delayed-shipment",
        "skill": "customer-reply",
        "file": "shipment_status.md",
        "contents": (
            "The shipment is four days late. The carrier scan shows it at the regional facility "
            "this morning. The cause is unknown. Support can check again tomorrow if there is "
            "no new scan. No delivery date or refund has been promised."
        ),
        "prompt": (
            "Read shipment_status.md and draft a concise, empathetic customer reply using the "
            "customer-reply skill. Do not promise a delivery date or refund."
        ),
    },
    {
        "id": "incident-webhook-delay",
        "skill": "incident-handoff",
        "file": "incident_status.md",
        "contents": (
            "Confirmed: webhook delivery p95 is 20m24s; 18 integrations are affected; retries "
            "are running with 1,880 events queued. No data loss has been confirmed. Cause and "
            "recovery time are unknown."
        ),
        "prompt": (
            "Read incident_status.md and prepare an internal on-call handoff using the "
            "incident-handoff skill. Separate confirmed facts from unknowns and give next "
            "investigation steps without inventing owners or deadlines."
        ),
    },
]


def parse_session(stdout: str) -> tuple[str | None, str]:
    session_id = None
    final = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            session_id = event.get("thread_id")
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final = item.get("text", final)
    return session_id, final


def main() -> None:
    if not (os.getenv("BRAINTRUST_API_KEY") and ORG and PROJECT and PROJECT_ID):
        raise RuntimeError(
            "Set BRAINTRUST_API_KEY, BRAINTRUST_ORG_NAME, BRAINTRUST_DEFAULT_PROJECT, "
            "and BRAINTRUST_PROJECT_ID explicitly"
        )

    with tempfile.TemporaryDirectory(prefix="codex-plugin-use-cases-", dir="/private/tmp") as tmp:
        root = Path(tmp)
        for scenario in SCENARIOS:
            run_dir = root / scenario["id"]
            run_dir.mkdir()
            (run_dir / scenario["file"]).write_text(scenario["contents"], encoding="utf-8")
            skill_library = run_dir / ".agents" / "skills"
            shutil.copytree(ROOT / "skills", skill_library)

            metadata = {
                "traffic_type": "synthetic",
                "environment": "demo",
                "trace_source": "codex_braintrust_plugin",
                "demo_case": scenario["id"],
                "skill": scenario["skill"],
                "skill_revision": "candidate-v1",
                "activation_mode": "discovery",
            }
            run_command = [
                "bt", "trace", "--org", ORG, "--project", PROJECT, "run",
                "--additional-metadata", json.dumps(metadata),
                "--tag", "synthetic-production-shaped", "codex", "exec", "--json",
                "--model", MODEL, "--sandbox", SANDBOX, "--skip-git-repo-check",
                "--cd", str(run_dir), scenario["prompt"],
            ]
            run = subprocess.run(
                run_command, cwd=ROOT, text=True, capture_output=True,
                timeout=TIMEOUT_SECONDS,
            )
            (run_dir / "codex-session.jsonl").write_text(run.stdout, encoding="utf-8")
            if run.returncode:
                raise RuntimeError(f"Codex plugin run {scenario['id']} failed:\n{run.stderr}\n{run.stdout}")
            session_id, final = parse_session(run.stdout)
            if not session_id:
                raise RuntimeError(f"Codex plugin run {scenario['id']} returned no session ID")

            import_command = [
                "bt", "trace", "import", "codex", session_id,
                "--org", ORG, "--project", PROJECT,
                "--destination", f"project_logs:{PROJECT_ID}",
                "--additional-metadata", json.dumps(metadata),
                "--tag", "synthetic-production-shaped", "--json",
            ]
            imported = subprocess.run(
                import_command, cwd=ROOT, text=True, capture_output=True,
                timeout=TIMEOUT_SECONDS,
            )
            if imported.returncode:
                raise RuntimeError(
                    f"Trace import {scenario['id']} failed:\n{imported.stderr}\n{imported.stdout}"
                )
            summary = json.loads(imported.stdout).get("summaries", [{}])[0]
            print(
                json.dumps(
                    {
                        "case": scenario["id"],
                        "skill": scenario["skill"],
                        "session_id": session_id,
                        "root_span_id": summary.get("root_span_id"),
                        "span_count": summary.get("span_count"),
                        "traffic_type": "synthetic",
                        "final_response": final,
                    }
                )
            )


if __name__ == "__main__":
    main()
