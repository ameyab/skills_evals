"""Create or update project automations for reference-free production scoring."""

from __future__ import annotations

import json
import os
import argparse
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = os.getenv("BRAINTRUST_API_URL", "https://api.braintrust.dev").rstrip("/")
SCORERS = (
    (
        "Codex production task completion",
        "CODEX_TASK_COMPLETION_SCORER_ID",
        "Score task completion using the request, final result, and observable tool outcomes.",
    ),
    (
        "Codex production instruction adherence",
        "CODEX_INSTRUCTION_ADHERENCE_SCORER_ID",
        "Score adherence to user constraints and skill instructions visible in the trace.",
    ),
)


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        raise RuntimeError("BRAINTRUST_API_KEY is required")
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Braintrust API returned HTTP {error.code}: {details}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure filtered Codex production scoring")
    parser.add_argument("--project-id", default=os.getenv("BRAINTRUST_PROJECT_ID"), required=not bool(os.getenv("BRAINTRUST_PROJECT_ID")))
    parser.add_argument("--sampling-rate", type=float, default=float(os.getenv("ONLINE_SCORING_SAMPLING_RATE", "0.1")))
    parser.add_argument("--btql-filter", default=os.getenv("ONLINE_SCORING_BTQL_FILTER", "metadata.traffic_type = 'production'"))
    parser.add_argument("--idle-seconds", type=int, default=int(os.getenv("ONLINE_SCORING_IDLE_SECONDS", "30")))
    args = parser.parse_args()
    if not 0 < args.sampling_rate <= 1:
        parser.error("--sampling-rate must be greater than 0 and at most 1")
    scorer_ids = {}
    for name, env_name, _description in SCORERS:
        scorer_id = os.getenv(env_name)
        if not scorer_id:
            parser.error(f"set {env_name} to the published scorer ID for {name}")
        scorer_ids[name] = scorer_id

    query = urllib.parse.urlencode({"project_id": args.project_id})
    existing = api("GET", f"/v1/project_score?{query}").get("objects", [])
    existing_by_name = {item.get("name"): item for item in existing}

    for name, env_name, description in SCORERS:
        scorer_id = scorer_ids[name]
        payload = {
            "project_id": args.project_id,
            "name": name,
            "description": description,
            "score_type": "online",
            "config": {
                "online": {
                    "status": "active",
                    "sampling_rate": args.sampling_rate,
                    "btql_filter": args.btql_filter,
                    "scope": {"type": "trace", "idle_seconds": args.idle_seconds},
                    "scorers": [{"type": "function", "id": scorer_id}],
                }
            },
        }
        current = existing_by_name.get(name)
        if current is None:
            saved = api("POST", "/v1/project_score", payload)
            action = "created"
        else:
            patch = {key: value for key, value in payload.items() if key != "project_id"}
            saved = api("PATCH", f"/v1/project_score/{current['id']}", patch)
            action = "updated"
        print(
            json.dumps(
                {
                    "action": action,
                    "name": name,
                    "project_id": args.project_id,
                    "scorer_id": scorer_id,
                    "automation_id": saved.get("id"),
                    "status": saved.get("config", {}).get("online", {}).get("status"),
                    "sampling_rate": saved.get("config", {}).get("online", {}).get("sampling_rate"),
                    "btql_filter": saved.get("config", {}).get("online", {}).get("btql_filter"),
                    "scope": saved.get("config", {}).get("online", {}).get("scope"),
                }
            )
        )


if __name__ == "__main__":
    main()
