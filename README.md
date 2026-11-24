# Codex + skills quality eval

This project compares Codex outputs with a baseline skill and a candidate skill. The primary eval injects the selected `SKILL.md` into the prompt. It measures instruction following for a known skill; it does not measure skill discovery or activation. A separate discovery eval installs complete skill directories in the fixture and tests relevant and irrelevant requests.

## Setup

Requirements: Python 3.13+, `uv`, Codex CLI, Braintrust CLI, Codex authentication, and a Braintrust API key.

```sh
uv sync
export BRAINTRUST_API_KEY=...
export BRAINTRUST_ORG_NAME="Braintrust Demos"
export BRAINTRUST_DEFAULT_PROJECT=skills_evals
export BRAINTRUST_PROJECT_ID=14b80865-aa15-4dce-8b89-d37c4fa7dea6
export BRAINTRUST_DATASET_NAME=codex-skills-demo-v1
```

The demo project is [skills_evals](https://www.braintrust.dev/app/Braintrust%20Demos/p/skills_evals), project ID `14b80865-aa15-4dce-8b89-d37c4fa7dea6`. Seed or refresh its eight-row dataset:

```sh
uv run python -m skills_evals.bootstrap_dataset
```

The canonical source is `data/demo.jsonl`; Braintrust stores the versioned copy as `codex-skills-demo-v1`. The expected values describe actions, owners, deadlines, commitment state, facts, and uncertainty. Full experiments read directly from the Braintrust dataset, and record its ID on the experiment. A focused run selected with `EVAL_CASE_IDS` reads matching records from that same dataset.

## Scorers and calibration

`mechanical_format` checks only word limits and exact required headings. `relationship-accuracy-v1` is a Braintrust LLM judge that compares the response to the case’s structured expected relationships. It treats negation and uncertainty semantically and fails fabricated owners, dates, actions, or commitments.

Publish these new scorers additively. The command fails if either slug already exists; set `SCORER_IF_EXISTS=replace` only when you intend to replace these scorers.

```sh
cd src
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_DEFAULT_PROJECT=skills_evals SCORER_IF_EXISTS=error \
  bt functions push --if-exists error --language python \
  --runner ../.venv/bin/python --requirements ../scorer-requirements.txt \
  skills_evals/publish_scorers.py
cd ..
```

Eight human-labeled cases cover fabricated owners and deadlines, missing discussion items, false recovery claims, and negated recovery statements. Run the calibration before relying on the judge:

```sh
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_DEFAULT_PROJECT=skills_evals \
CALIBRATION_EXPERIMENT_NAME=relationship-judge-calibration-YYYYMMDD \
  ./.venv/bin/python -m skills_evals.calibrate_relationship_judge
```

The script logs a Braintrust experiment and writes per-case agreement to `artifacts/relationship-calibration-latest.json`. Treat agreement as a calibration check, not proof of judge validity. Review disagreements and update human labels or the rubric before using the score as a gate.

## Compare baseline and candidate skills

Each run uses the same dataset, pinned model alias, read-only sandbox, one concurrent Codex task, controlled environment-variable allowlist, isolated fixture directory, and per-case timeout. The experiment and imported trace record the Codex CLI version, dataset SHA-256, and selected skill file-tree SHA-256. `SKILLS_REVISION` is a display label; the hash identifies the actual skill contents.

Run the baseline:

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_PROJECT_ID="$BRAINTRUST_PROJECT_ID" \
SKILLS_DIR=skill_versions/baseline-v1 \
SKILLS_REVISION=baseline-v1 \
CODEX_MODEL=gpt-6-luna CODEX_SANDBOX=read-only CODEX_TIMEOUT_SECONDS=300 \
BRAINTRUST_EXPERIMENT_NAME=skills-baseline-20261118 \
  uv run python -m skills_evals.eval
```

Run the candidate on the same cases and compare it with the baseline:

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_PROJECT_ID="$BRAINTRUST_PROJECT_ID" \
SKILLS_DIR=skills SKILLS_REVISION=candidate-v1 \
CODEX_MODEL=gpt-6-luna CODEX_SANDBOX=read-only CODEX_TIMEOUT_SECONDS=300 \
COMPARE_TO_EXPERIMENT=skills-baseline-20261118 \
BRAINTRUST_EXPERIMENT_NAME=skills-candidate-20261118 \
  uv run python -m skills_evals.eval
```

Set `EVAL_CASE_IDS=meeting-002,incident-002` to run a focused subset. Use a fresh experiment name for each run. Keep the model, dataset, sandbox, timeout, and case IDs fixed when comparing skill revisions.

The prompts include both natural requests that rely on the skill and explicitly constrained requests. Each case records its prompt condition so results can be compared by group.

## Skill discovery and activation eval

The primary eval inserts `SKILL.md` into the task prompt and tests the skill body only. It does not load bundled references, templates, or other files. To test normal discovery, `activation_mode=discovery` copies the complete `skills/` directory into the fixture’s `.agents/skills/` directory, then sends the task without embedding or naming the skill. Codex can select a relevant skill or leave it unused for an unrelated request. The directory layout follows Codex’s project skill discovery convention ([Codex skill installation](https://developers.openai.com/api/reference/cli)).

Run the separate relevant/irrelevant activation set:

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_PROJECT_ID="$BRAINTRUST_PROJECT_ID" \
CODEX_EVAL_DATASET=data/activation.jsonl \
BRAINTRUST_DATASET_NAME=codex-skills-activation-v1 \
  uv run python -m skills_evals.bootstrap_dataset
```

Then run the discovery experiment:

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_PROJECT_ID="$BRAINTRUST_PROJECT_ID" \
CODEX_EVAL_DATASET=data/activation.jsonl BRAINTRUST_DATASET_NAME=codex-skills-activation-v1 \
SKILL_ACTIVATION_MODE=discovery SKILLS_DIR=skills \
CODEX_MODEL=gpt-6-luna CODEX_SANDBOX=read-only CODEX_TIMEOUT_SECONDS=300 \
BRAINTRUST_EXPERIMENT_NAME=skill-discovery-YYYYMMDD \
  uv run python -m skills_evals.eval
```

Inspect the imported turn and tool spans to confirm whether Codex read a skill’s `SKILL.md`. The run metadata records skill paths observed in Codex events; absence of a path is inconclusive if the runtime loaded the skill without a visible file-read event.

## Trace shape and experiment linkage

The runner creates an isolated fixture, launches Codex with an explicit model and sandbox, captures the session ID, then imports the actual Codex session with `bt trace import`. It does not synthesize model/tool spans from completed event summaries. In an eval, the import is attached to the Braintrust task span through `hooks.span.export()`, so the experiment row should open the corresponding trace tree. A standalone `skills-evals run --trace` imports to project logs because it has no experiment parent.

To verify one case without running the whole set:

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="$BRAINTRUST_ORG_NAME" BRAINTRUST_PROJECT_ID="$BRAINTRUST_PROJECT_ID" \
SKILLS_DIR=skills SKILLS_REVISION=trace-check-v1 \
CODEX_MODEL=gpt-6-luna CODEX_SANDBOX=read-only \
EVAL_CASE_IDS=meeting-002 \
BRAINTRUST_EXPERIMENT_NAME=trace-check-meeting-002 \
  uv run python -m skills_evals.eval
```

Open `skills-candidate-dataset-20261118` in Braintrust. The experiment has eight rows linked to imported Codex session trees. Each tree includes the Eval row, task span, Codex session, turn, model calls, actual tool spans, and scorer spans. Its Codex span metadata includes the prompt mode, skill hash, dataset hash, and `traffic_type=eval`. The separate discovery experiment confirmed a visible read of `.agents/skills/meeting-actions/SKILL.md` for the relevant request and no skill read for the unrelated arithmetic request.

On this single paired run, baseline relationship accuracy was 75% and candidate accuracy was 100%, with three improved cases and no regressions. Treat this as an initial result: repeat trials and human review are needed before concluding the skill change consistently improves quality.

## Production online scoring

The production judges are reference-free; they score visible trace content. Set the scorer IDs and destination explicitly. The default rule samples 10% and only accepts traces marked `metadata.traffic_type = 'production'`. Synthetic examples use `synthetic`; eval traces use `eval` and are excluded. Configure the production Codex tracing destination as this project and have the tracing integration attach `traffic_type=production` to each real session’s root trace metadata; without that field, the online rules intentionally do not run.

The local Codex tracing plugin is configured for this destination. To configure another intended production Codex environment, run:

```sh
bt trace --org "$BRAINTRUST_ORG_NAME" --project "$BRAINTRUST_DEFAULT_PROJECT" \
  enable codex --additional-metadata '{"traffic_type":"production","skill_family":"skills_evals"}' \
  --tag production-codex
```

Restart Codex after enabling the plugin. This route labels each captured session as production; use a separate route or another traffic label for development and synthetic runs.

```sh
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_ORG_NAME="Braintrust Demos" \
BRAINTRUST_PROJECT_ID=14b80865-aa15-4dce-8b89-d37c4fa7dea6 \
CODEX_TASK_COMPLETION_SCORER_ID=5769a62a-3dee-4cf9-8be1-c231dc2c6bbb \
CODEX_INSTRUCTION_ADHERENCE_SCORER_ID=9a3f9e28-72c4-465f-89bb-1e34a6a3b8a9 \
ONLINE_SCORING_SAMPLING_RATE=0.1 \
ONLINE_SCORING_BTQL_FILTER="metadata.traffic_type = 'production'" \
  ./.venv/bin/python -m skills_evals.setup_online_scoring
```

The script prints the project, filter, sampling rate, scope, and scorer IDs it applied. Set the sampling rate to `1.0` for deliberate low-volume coverage while retaining the production filter. Review online scores against human-labeled traces before treating them as a quality gate.

Active production rules in `skills_evals` are `dd7d8b56-f513-4978-b401-1a7a82d5711a` (task completion) and `d434b7d6-1cb1-41ad-b106-b336562e2642` (instruction adherence). Both use trace scope, 30 seconds of idle time, 10% sampling, and the production-only filter.

## Generate synthetic plugin traces for demo use cases

```sh
BRAINTRUST_ORG_NAME="Braintrust Demos" \
BRAINTRUST_DEFAULT_PROJECT=skills_evals \
BRAINTRUST_PROJECT_ID=14b80865-aa15-4dce-8b89-d37c4fa7dea6 \
  uv run python -m skills_evals.generate_plugin_use_case_traces
```

The generator launches each case with `bt trace run codex`, installs the complete skill library in an isolated fixture, and imports the captured session trace into the [project logs](https://www.braintrust.dev/app/Braintrust%20Demos/p/skills_evals). Cases cover meeting actions, a delayed shipment reply, and an incident handoff. Each trace has two model spans and a skill-use span. They are tagged `traffic_type=synthetic` so the production scoring rules exclude them. Current roots: `ba2e1829-0735-5b61-a32a-241720358d9e`, `8c9810ab-056b-522c-8fc7-9b20b7bb7d75`, and `f5303731-ee17-581c-9c27-3ad35c155720`.
