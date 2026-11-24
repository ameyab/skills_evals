"""Run synthetic Codex sessions and import their multi-span traces to Braintrust.

`bt trace run codex` captures each session; `bt trace import` finalizes and
stores that session as a root trace in the demo project.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT = os.getenv("BRAINTRUST_DEFAULT_PROJECT")
PROJECT_ID = os.getenv("BRAINTRUST_PROJECT_ID")
ORG = os.getenv("BRAINTRUST_ORG_NAME")
MODEL = os.getenv("CODEX_MODEL", "gpt-6-luna")
SANDBOX = os.getenv("CODEX_SANDBOX", "read-only")
TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "300"))
SKILL_NAME = "incident-handoff"

SCENARIOS = [
    {
        "id": "webhook-latency-handoff",
        "status": (
            "Confirmed: webhook delivery latency is above 20 minutes.\n"
            "Confirmed: 18 customer integrations are affected.\n"
            "Confirmed: retries are still running.\n"
            "Unknown: cause and recovery time.\n"
            "No data loss has been confirmed.\n"
        ),
        "alerts": (
            "2026-11-11T14:10:02Z webhook_delivery_p95=20m24s\n"
            "2026-11-11T14:18:09Z affected_integrations=18\n"
            "2026-11-11T14:24:31Z retry_worker=running queued_events=1880\n"
        ),
        "task": "Produce an internal incident handoff.",
    },
    {
        "id": "email-queue-backlog",
        "status": (
            "Confirmed: outbound email queue is delayed.\n"
            "Confirmed: 6,420 messages are queued.\n"
            "Confirmed: the delivery workers are running but draining slowly.\n"
            "Unknown: whether the delay is caused by provider throttling.\n"
            "No messages are confirmed lost.\n"
        ),
        "alerts": (
            "2026-11-11T15:02:10Z email_queue_oldest_age=17m\n"
            "2026-11-11T15:08:42Z queued_messages=6420\n"
            "2026-11-11T15:14:05Z delivery_workers=running drain_rate=slow\n"
        ),
        "task": "Prepare an internal incident handoff for the on-call team.",
    },
    {
        "id": "billing-webhook-retries",
        "status": (
            "Confirmed: billing webhook retries increased after 16:20 UTC.\n"
            "Confirmed: 73 deliveries are pending retry.\n"
            "Confirmed: new webhook events are still being accepted.\n"
            "Unknown: whether any customer invoices were delayed.\n"
            "Unknown: cause and recovery time.\n"
        ),
        "alerts": (
            "2026-11-11T16:20:17Z billing_webhook_retry_rate=12/min\n"
            "2026-11-11T16:27:51Z pending_deliveries=73\n"
            "2026-11-11T16:31:08Z event_ingest=healthy\n"
        ),
        "task": "Summarize the incident for an internal handoff, preserving what is known and unknown.",
    },
]


def main() -> None:
    if not os.getenv("BRAINTRUST_API_KEY"):
        raise RuntimeError("Set BRAINTRUST_API_KEY before running the trace demo")
    if not PROJECT or not PROJECT_ID or not ORG:
        raise RuntimeError(
            "Set BRAINTRUST_ORG_NAME, BRAINTRUST_DEFAULT_PROJECT, and "
            "BRAINTRUST_PROJECT_ID to the explicit Braintrust destination"
        )

    skill_path = PROJECT_ROOT / "skills" / SKILL_NAME / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8")
    demo_dir = Path(tempfile.mkdtemp(prefix="codex-plugin-trace-demo-", dir="/private/tmp"))
    for scenario in SCENARIOS:
        run_dir = demo_dir / scenario["id"]
        incident_dir = run_dir / "incident"
        incident_dir.mkdir(parents=True)
        (incident_dir / "status.md").write_text(
            "# Incident status\n\n" + scenario["status"], encoding="utf-8"
        )
        (incident_dir / "alerts.log").write_text(scenario["alerts"], encoding="utf-8")

        prompt = f"""Use the `{SKILL_NAME}` skill below.

--- BEGIN SKILL ---
{skill_text}
--- END SKILL ---

Task: Inspect `incident/status.md` and `incident/alerts.log` in this workspace. {scenario['task']} Use the skill's required sections: Impact, Confirmed facts, Unknowns, and Next actions. Preserve exact timestamps and distinguish confirmed facts from unknowns. Do not modify any files. Base the handoff only on the files; do not invent owners, deadlines, cause, recovery time, or data loss."""

        metadata = json.dumps(
            {
                "traffic_type": "synthetic",
                "environment": "demo",
                "trace_source": "codex_plugin_multi_span_demo",
                "demo_case": scenario["id"],
                "skill": SKILL_NAME,
                "skill_revision": "demo-v1",
            }
        )
        event_log = run_dir / "codex-session.jsonl"
        command = [
            "bt", "trace", "--org", ORG, "--project", PROJECT,
            "run", "--additional-metadata", metadata,
            "--tag", "synthetic-codex-plugin-demo", "codex", "exec", "--json",
            "--ignore-user-config", "--skip-git-repo-check", "--model", MODEL,
            "--sandbox", SANDBOX, "--cd", str(run_dir), prompt,
        ]
        result = subprocess.run(
            command, cwd=PROJECT_ROOT, text=True, capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
        event_log.write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(
                f"Traced Codex run {scenario['id']} failed ({result.returncode}).\n"
                f"{result.stderr}\nSession output saved in {event_log}"
            )

        final_messages = []
        session_id = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id")
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                final_messages.append(item.get("text", ""))
        if not session_id:
            raise RuntimeError(
                f"Codex did not return a session ID for {scenario['id']}; "
                f"session output saved in {event_log}"
            )

        import_command = [
            "bt", "trace", "import", "codex", session_id,
            "--org", ORG, "--project", PROJECT,
            "--destination", f"project_logs:{PROJECT_ID}",
            "--additional-metadata", metadata,
            "--tag", "synthetic-codex-plugin-demo", "--json",
        ]
        imported = subprocess.run(
            import_command, cwd=PROJECT_ROOT, text=True, capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
        if imported.returncode:
            raise RuntimeError(
                f"Braintrust import failed for {scenario['id']} ({imported.returncode}).\n"
                f"{imported.stderr or imported.stdout}\nSession output saved in {event_log}"
            )
        try:
            import_result = json.loads(imported.stdout)
            import_summary = import_result.get("summaries", [{}])[0]
        except (json.JSONDecodeError, IndexError):
            import_summary = {}
        print(f"Logged synthetic trace: {scenario['id']}")
        print(
            f"  Braintrust root: {import_summary.get('root_span_id', 'unknown')} "
            f"({import_summary.get('span_count', 'unknown')} spans)"
        )
        print(f"  Fixture: {run_dir}")
        print(f"  Session events: {event_log}")
        if final_messages:
            print("  Final response: " + final_messages[-1].replace("\n", " | "))
        if result.stderr.strip():
            print("  Codex/Braintrust output: " + result.stderr.strip())

    print(f"\nSent {len(SCENARIOS)} synthetic Codex plugin traces to Braintrust project {PROJECT}.")


if __name__ == "__main__":
    main()
