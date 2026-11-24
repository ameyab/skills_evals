from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / os.getenv("SKILLS_DIR", "skills")
MODEL = os.getenv("CODEX_MODEL", "gpt-6-luna")
SANDBOX = os.getenv("CODEX_SANDBOX", "read-only")
TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "300"))

ENV_ALLOWLIST = (
    "PATH", "HOME", "CODEX_HOME", "TMPDIR", "TEMP", "TMP", "TERM", "LANG", "LC_ALL",
    "OPENAI_API_KEY", "CODEX_API_KEY", "BRAINTRUST_API_KEY", "BRAINTRUST_ORG_NAME",
    "BRAINTRUST_DEFAULT_PROJECT", "BRAINTRUST_PROFILE", "BRAINTRUST_API_URL", "BRAINTRUST_APP_URL",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
)


def controlled_environment(project: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    env["BRAINTRUST_DEFAULT_PROJECT"] = project
    return env


def file_tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_skill(case: dict[str, Any]) -> tuple[Path, str]:
    skill_name = case["input"].get("skill")
    if not skill_name:
        raise ValueError(f"case {case.get('id')} does not name a skill")
    skill_dir = (SKILLS_ROOT / skill_name).resolve()
    if SKILLS_ROOT.resolve() not in skill_dir.parents:
        raise ValueError(f"invalid skill path: {skill_name}")
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        raise ValueError(f"skill not found: {skill_path}")
    return skill_dir, skill_path.read_text(encoding="utf-8")


def _safe_fixture_path(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"fixture path must stay under its root: {relative}")
    path = (root / Path(*candidate.parts)).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"fixture path must stay under its root: {relative}")
    return path


def materialize_fixture(case: dict[str, Any], fixture: Path, activation_mode: str) -> tuple[str, str | None]:
    task = case["input"]
    fixture.mkdir(parents=True, exist_ok=True)
    for relative, content in task.get("files", {}).items():
        path = _safe_fixture_path(fixture, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")

    skill_dir, skill_text = load_skill(case) if task.get("skill") else (None, "")
    skill_hash = file_tree_hash(skill_dir) if skill_dir else None
    if activation_mode == "injected":
        prompt = (
            f"Follow the {task['skill']} skill below. Return only the requested artifact.\n\n"
            f"--- BEGIN SKILL: {task['skill']} ---\n{skill_text}\n--- END SKILL ---\n\n"
            f"Task: {task['prompt']}"
        )
    elif activation_mode == "discovery":
        library = fixture / ".agents" / "skills"
        shutil.copytree(SKILLS_ROOT, library, dirs_exist_ok=True)
        prompt = task["prompt"]
    else:
        raise ValueError("activation_mode must be 'injected' or 'discovery'")
    return prompt, skill_hash


def _parse_session(stdout: str) -> tuple[str | None, str, list[dict[str, Any]]]:
    session_id = None
    final = ""
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get("type") == "thread.started":
            session_id = event.get("thread_id")
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                final = item.get("text", final)
    return session_id, final or stdout.strip(), events


def _run_codex(command: list[str], env: dict[str, str], fixture: Path) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        result = subprocess.run(
            command,
            cwd=fixture,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"Codex exceeded the {TIMEOUT_SECONDS}-second case timeout") from error
    session_id, final, events = _parse_session(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Codex failed ({result.returncode}):\n{result.stderr}\n{result.stdout}")
    if not session_id:
        raise RuntimeError(f"Codex returned no session ID:\n{result.stderr}\n{result.stdout}")
    return session_id, final, events


def run_case(
    case: dict[str, Any],
    *,
    trace: bool = False,
    project: str = "skills_evals",
    trace_metadata: dict[str, Any] | None = None,
    parent_span_export: str | None = None,
    eval_metadata: dict[str, Any] | None = None,
    activation_mode: str = "injected",
) -> str:
    task = case["input"]
    with tempfile.TemporaryDirectory(prefix=f"codex-eval-{case['id']}-", dir="/private/tmp") as tmp:
        fixture = Path(tmp)
        prompt, skill_hash = materialize_fixture(case, fixture, activation_mode)
        model = os.getenv("CODEX_MODEL", MODEL)
        sandbox = os.getenv("CODEX_SANDBOX", SANDBOX)
        command = [
            "codex", "exec", "--json", "--ignore-user-config", "--skip-git-repo-check", "--model", model,
            "--sandbox", sandbox, "--cd", str(fixture), prompt,
        ]
        env = controlled_environment(project)
        if not trace:
            # Ephemeral sessions cannot be imported, so preserve only ordinary run sessions.
            command.insert(2, "--ephemeral")
            return _run_codex(command, env, fixture)[1]

        session_id, final, events = _run_codex(command, env, fixture)
        serialized_events = json.dumps(events, ensure_ascii=False)
        installed_skill_paths = [
            f".agents/skills/{path.name}/SKILL.md"
            for path in SKILLS_ROOT.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        ] if activation_mode == "discovery" else []
        observed_skill_paths = [
            path for path in installed_skill_paths
            if path in serialized_events or path.replace("/", "\\") in serialized_events
        ]
        metadata = {
            "traffic_type": "eval",
            "environment": "eval",
            "trace_source": "codex_session_import",
            "dataset_case_id": case["id"],
            "skill": task.get("skill"),
            "skill_revision": os.getenv("SKILLS_REVISION", "working-tree"),
            "skill_sha256": skill_hash,
            "activation_mode": activation_mode,
            "skill_library_available_count": len(installed_skill_paths),
            "skill_load_paths_observed_in_codex_events": observed_skill_paths,
            "model": model,
            "sandbox": sandbox,
        }
        if trace_metadata:
            metadata.update(trace_metadata)
        if not env.get("BRAINTRUST_ORG_NAME"):
            raise RuntimeError("Set BRAINTRUST_ORG_NAME to the explicit Braintrust organization")
        import_command = [
            "bt", "trace", "import", "codex", session_id,
            "--org", env.get("BRAINTRUST_ORG_NAME", ""),
            "--project", project,
            "--additional-metadata", json.dumps(metadata),
            "--tag", "codex-skills-eval", "--json",
        ]
        if parent_span_export:
            import_command.extend(["--parent", parent_span_export])
        else:
            project_id = os.getenv("BRAINTRUST_PROJECT_ID")
            if not project_id:
                raise RuntimeError("Set BRAINTRUST_PROJECT_ID to import a trace outside an Eval row")
            import_command.extend(["--destination", f"project_logs:{project_id}"])
        imported = subprocess.run(
            import_command,
            cwd=fixture,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
        if imported.returncode:
            raise RuntimeError(f"Codex trace import failed:\n{imported.stderr}\n{imported.stdout}")
        try:
            summary = json.loads(imported.stdout).get("summaries", [{}])[0]
        except (json.JSONDecodeError, IndexError):
            summary = {}
        if eval_metadata is not None:
            eval_metadata.update(
                {
                    "trace_root_span_id": summary.get("root_span_id"),
                    "trace_span_count": summary.get("span_count"),
                    "trace_source": "codex_session_import",
                }
            )
        return final
