# Decision Dashboard & Report Goal

## Goal

Aggregate the growing project artifact set into an in-product decision surface. Users should not need to inspect external dashboards or individual JSON files to understand readiness, risks, next actions, benchmark fixture caveats, or reporting status.

## Implemented Scope

- Added `decision_dashboard` JSON artifacts and `decision_report` Markdown artifacts.
- Added `/api/projects/{project_id}/decision-dashboard/generate`.
- Added `schemas/decision_dashboard.schema.json`.
- Decision dashboard includes project summary, readiness stages, artifact completeness, risk register, next actions, unresolved assumptions, open questions, benchmark context, artifact refs, and visualization specs.
- Generation creates a Report record and three decision VisualizationSpecs: readiness stages, artifact completeness, and risk summary.
- Reports tab can generate the dashboard, list decision artifacts, preview them, and download them.

## Design Notes

- This is a harness-owned decision layer. It summarizes local Tablex artifacts and records lineage; it does not depend on W&B, MLflow, or external dashboards.
- Benchmark fixture results are explicitly marked as workflow smoke checks, not model-quality or benchmark-score claims.
- Missing artifacts become next actions instead of blocking the workflow by default.

## Deferred Scope

- Interactive drill-down from dashboard rows into the exact source artifacts.
- Rich chart rendering beyond existing portable VisualizationSpec previews.
- Human approval workflow tied directly to readiness status.
- Decision diffs across multiple dashboard versions.

## Validation

- Integration tests cover dashboard generation, report preview, JSON preview, visualization creation, and artifact listing.
- Full checks should run through ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.
