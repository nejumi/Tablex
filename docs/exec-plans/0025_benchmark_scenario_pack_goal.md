# Benchmark Scenario Pack Goal

## Goal

Make benchmark fixtures useful as workflow and product validation packs, not just data files. Home Credit-like multi-table smoke tests should surface supporting tables, relational context, evaluation readiness, ResearchPlan handoff, and reporting expectations inside Tablex.

## Implemented Scope

- Added `benchmark_scenario_pack` JSON artifacts and `benchmark_scenario_report` Markdown artifacts.
- Added `/api/projects/{project_id}/benchmarks/{benchmark_id}/scenario-pack`.
- Added lightweight scenario metadata for Home Credit Default Risk, Store Sales forecasting, and UCI Bank Marketing fixtures.
- Benchmark imports now register small supporting CSV/Parquet files as `benchmark_supporting_table` artifacts with a size cap.
- Home Credit fixture smoke now also creates a controlled ResearchPlan and BenchmarkScenarioPack/Report.
- Data tab UI can generate, list, preview, and download benchmark scenario artifacts.
- Scenario packs include intended use, fixture status, artifact context, relational summary, recommended workflow, runner guardrails, and reporting expectations.

## Design Notes

- Large real benchmark files are not copied blindly. Supporting table artifact registration uses a conservative size cap and records skipped files.
- Fixture scores remain product smoke checks, not benchmark performance claims.
- Kaggle credentials remain user-managed outside Tablex and are never stored or passed to agents.
- Multi-table feature generation remains a FeatureRecipe/AgentTask concern constrained by SplitManifest and prediction-time availability.

## Deferred Scope

- Full multi-table model training.
- Wide-to-long transformations for M5-style datasets.
- Rich benchmark-specific visualization renderers.
- Actual external benchmark download or leaderboard submission.
- Automated controlled web/literature search execution.

## Validation

- Integration tests cover UCI scenario metadata, manual scenario pack generation, Home Credit fixture smoke ResearchPlan/scenario artifacts, and supporting table artifact registration.
- Full checks should run through ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.
