# Benchmark Fixture And Smoke Harness Goal

## Goal

Make benchmark-driven development easier without storing external datasets or credentials. Tablex should be able to generate tiny local fixtures that mimic useful benchmark structures and then run a minimal in-product flow to validate import, lineage, evaluation, and planning surfaces.

## Implemented

- Added fixture support metadata to benchmark catalog responses.
- Added `POST /api/benchmarks/{benchmark_id}/fixtures/generate`.
- Added `run_benchmark_fixture_smoke` job type.
- Added `POST /api/projects/{project_id}/benchmarks/{benchmark_id}/fixture-smoke`.
- Added synthetic fixtures for:
  - Home Credit Default Risk-like multi-table credit risk
  - Store Sales-like retail time series
  - UCI Bank Marketing-like single-table classification
- The smoke harness runs:
  - fixture generation
  - benchmark import
  - DataQualityGate
  - EvaluationScenarioComparison
  - EvaluationApprovalReview
  - EvaluationSpec approval when no explicit blockers exist
  - SplitManifest generation
  - BaselineStrategyPlan generation
- Added UI buttons for fixture generation and fixture smoke execution from the Benchmark Catalog panel.
- Added integration tests for UCI fixture import and Home Credit fixture smoke.

## Design Choices

- Fixtures are synthetic files written under `HARNESS_DATA_DIR/benchmarks/{benchmark_id}`.
- UI fixture generation does not overwrite existing files by default.
- Smoke harness creates artifacts but does not run the full baseline model, keeping it fast enough for product checks.
- Kaggle credentials remain outside Tablex. Fixture endpoints require no external account or secret.

## Deferred

- CLI wrapper for fixture generation.
- Fixture generators for IEEE-CIS, Rossmann, Instacart, M5, and Home Credit Model Stability.
- Larger benchmark sample packs with richer target drift and missingness patterns.
- Fixture-specific report dashboards.

## Risks And Open Decisions

- Fixtures can validate product wiring but cannot validate model quality claims.
- The smoke harness currently approves the generated EvaluationSpec if no explicit blockers exist; future policy may require manual approval for some benchmark modes.
- Store Sales fixture support exists, but the first smoke test uses Home Credit because it exercises relational catalog behavior more directly.
