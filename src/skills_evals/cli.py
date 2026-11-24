from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from skills_evals.runner import run_case


def load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(prog="skills-evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one dataset case through Codex")
    run.add_argument("case_id")
    run.add_argument("--trace", action="store_true", help="Log the Codex trajectory to Braintrust")
    run.add_argument("--project", default=os.getenv("BRAINTRUST_DEFAULT_PROJECT", "skills_evals"))
    run.add_argument("--dataset", type=Path, default=Path("data/demo.jsonl"))
    sub.add_parser("eval", help="Run the Braintrust evaluation against the local demo dataset")
    sub.add_parser("list", help="List dataset cases")
    bootstrap = sub.add_parser("bootstrap", help="Create or refresh the demo dataset in an existing Braintrust project")
    bootstrap.add_argument("--org", default=os.getenv("BRAINTRUST_ORG_NAME"))
    bootstrap.add_argument("--project", default=os.getenv("BRAINTRUST_DEFAULT_PROJECT", "skills_evals"))
    bootstrap.add_argument("--project-id", default=os.getenv("BRAINTRUST_PROJECT_ID"))
    bootstrap.add_argument("--dataset", default=os.getenv("BRAINTRUST_DATASET_NAME", "codex-skills-demo-v1"))
    args = parser.parse_args()
    if args.command == "run":
        case = next((item for item in load_cases(args.dataset) if item["id"] == args.case_id), None)
        if case is None:
            parser.error(f"unknown case id: {args.case_id}")
        print(run_case(case, trace=args.trace, project=args.project))
    elif args.command == "eval":
        import subprocess
        subprocess.run(["bt", "eval", "--language", "python", "src/skills_evals/eval.py"], check=True)
    elif args.command == "list":
        for case in load_cases(Path("data/demo.jsonl")):
            print(f'{case["id"]}: {case["input"]["skill"]} — {case["input"]["title"]}')
    elif args.command == "bootstrap":
        import subprocess
        if not args.org or not args.project_id:
            parser.error("set BRAINTRUST_ORG_NAME and BRAINTRUST_PROJECT_ID or pass --org and --project-id")
        env = os.environ.copy()
        env.update(
            BRAINTRUST_ORG_NAME=args.org,
            BRAINTRUST_DEFAULT_PROJECT=args.project,
            BRAINTRUST_PROJECT_ID=args.project_id,
            BRAINTRUST_DATASET_NAME=args.dataset,
        )
        subprocess.run([sys.executable, "-m", "skills_evals.bootstrap_dataset"], check=True, env=env)


if __name__ == "__main__":
    main()
