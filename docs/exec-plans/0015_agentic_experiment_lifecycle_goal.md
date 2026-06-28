# Agentic Experiment Lifecycle & Flexible Approach Execution Goal

## Goal

Create a wider loop from Idea to runner-ready ExperimentPlan, run-level report, and cross-run comparison without turning Tablex into a fixed recipe runner. The harness should own evaluation locks, safety policy, artifacts, lineage, diagnostics, reports, and UI. AgentRunner implementations can still choose modeling details using project evidence, Skills, and controlled research policy.

## Implemented

- Added schema files:
  - `schemas/experiment_plan.schema.json`
  - `schemas/experiment_comparison.schema.json`
  - `schemas/run_report.schema.json`
- Added job types:
  - `create_experiment_plan`
  - `compare_experiments`
  - `draft_run_report`
- Added endpoints:
  - `POST /api/ideas/{idea_id}/experiment-plan`
  - `GET /api/ideas/{idea_id}/experiment-plans`
  - `POST /api/runs/{run_id}/report`
  - `POST /api/projects/{project_id}/experiments/compare`
- Added `experiment_plan` artifacts that include:
  - readiness and blocking items
  - research/source governance
  - EvaluationSpec and SplitManifest lock
  - flexible approach selection policy
  - scenario comparisons
  - AgentTaskContract and workspace policy
  - expected artifacts and review questions
- Added `run_report` Markdown artifacts and `Report` records backed by run metrics and diagnostics.
- Added `experiment_comparison` JSON artifacts, `experiment_comparison_report` Markdown artifacts, comparison `Report` records, and comparison VisualizationSpecs.
- Added Evidence, Insights, and Lineage for plans, reports, and comparisons.
- Extended Approach UI with ExperimentPlan creation and preview.
- Extended Experiments UI with run-report actions, compare-runs action, lifecycle artifacts table, and preview/download.
- Extended integration tests across the full project flow.

## Deferred

- Real Codex execution of ExperimentPlan tasks.
- Dynamic Skill execution and Skill dependency resolution.
- Controlled web/literature search with citation artifact ingestion.
- Multiple real agent experiment runs beyond the LocalStub and baseline path.
- Rich interactive comparison charts and slice drill-downs.
- Strict schema validation on every lifecycle artifact write.

## Risks And Open Decisions

- ExperimentPlan is intentionally a contract and decision scaffold, not a hard-coded modeling recipe.
- Comparison currently ranks successful runs by primary metric and uses diagnostics availability as a governance signal; it does not yet perform statistical significance testing.
- Run reports are deterministic summaries. Future AgentRunner reports should attach richer interpretation and source-backed claims while preserving harness-owned evidence.
- The worker still uses stub handlers for generic queued execution. Feature endpoints execute synchronously in the MVP.
