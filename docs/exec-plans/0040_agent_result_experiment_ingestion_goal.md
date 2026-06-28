# 0040 AgentResult Experiment Ingestion Goal

## Goal

Promote runner-produced AgentResult artifacts into the same in-product result surfaces used by baselines. When an agent returns `experiment_metrics`, `feature_recipe`, or `visualization_spec` artifacts, the harness should interpret them, register ExperimentRun and VisualizationSpec records, and link them to the source AgentTask without mutating EvaluationSpec or SplitManifest.

## Implementation

- Added `services/agent_result_ingestion.py`.
- Extended LocalStubAgentRunner to write:
  - `feature_recipe.json`
  - `experiment_metrics.json`
  - `visualization_spec.json`
  - `agent_result.json`
  - `agent_task_report.md`
- LocalStub metrics explicitly use `execution_status=not_executed` and `model_code_executed=false`; no benchmark or model performance is fabricated.
- Idea AgentTask execution and planned AgentTask execution both call the shared ingestion service.
- Ingestion creates:
  - ExperimentRun when an `experiment_metrics` artifact exists
  - VisualizationSpec rows from ingested `visualization_spec` artifacts
  - lineage from job, AgentTask source, metrics/feature artifacts, EvaluationSpec, SplitManifest, DatasetSnapshot, run, and visualization
- Job outputs now include `experiment_run_id`, `agent_metrics_artifact_id`, `agent_feature_recipe_artifact_id`, and `visualization_ids`.

## Validation Plan

- Update the full API flow test so planned and Idea LocalStub runs produce five ingested artifacts, not-executed ExperimentRuns, and VisualizationSpec records.
- Ensure baseline-oriented tests no longer depend on "latest run" ordering.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for planned LocalStub execution and AgentResult experiment ingestion.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: ran UCI benchmark fixture smoke in the container, planned an AgentTaskContract, executed LocalStub, and verified a `not_executed` ExperimentRun plus metrics artifact ingestion.

## Deferred

- Creating ModelVersion records from real agent-produced model packages.
- Accepting succeeded leaderboard metrics from Codex execution; the current LocalStub path remains explicitly non-scoring.
- Schema hardening for `experiment_metrics.v1` and `feature_recipe.v1`.
- Human approval workflow before treating agent-produced metrics as decision-grade evidence.
