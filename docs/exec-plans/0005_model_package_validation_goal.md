# Model Package Validation Goal

## Goal

Verify that a saved `ModelVersion` package is reproducible inside the harness before adding broader prediction-serving flows. The validation path should reload `model_package.joblib`, replay validation predictions using the linked `DatasetSnapshot`, `EvaluationSpec`, and `SplitManifest`, compare metrics against stored run metrics, and persist the result as first-class artifacts with lineage.

## Implemented Scope

- Added a `model_versions` service for `model_package.joblib` loading and replay validation.
- Added `validate_model_package` as a supported synchronous Job type.
- Added `POST /api/model-versions/{model_version_id}/validate`.
- Rebuilt validation rows from the original DatasetSnapshot and SplitManifest.
- Reused the saved strong-baseline feature builder and model object from the model package.
- Recomputed classification and regression metrics for the validation split.
- Compared replay metrics with stored ModelVersion metrics and recorded per-metric deltas plus `max_abs_metric_delta`.
- Stored validation outputs as artifacts:
  - `model_validation_report`
  - `model_validation_metrics`
  - `prediction_replay`
- Added lineage edges from `model_version` to the validation artifacts.
- Added an Assets-tab action to trigger validation from the ModelVersions table.
- Extended the API integration test to cover package validation and artifact creation.
- Follow-up Goal `0006_job_validation_history_goal.md` adds UI/API visibility for validation history and all project jobs.

## Validation Policy

The current validation status is `passed` when the maximum absolute numeric metric delta is at or below `1e-9`; otherwise it is `warning`. This is intentionally strict because the MVP replay uses the same local package, same split, and same library environment as the original run. A later compatibility layer should loosen or contextualize this when packages move across runtime versions.

## Deferred Scope

- General batch or online prediction API.
- ModelVersion approval, archival, and deployment-blocking state transitions.
- Cross-environment model package compatibility checks.
- Explicit model card page.
- Human review workflow for validation warnings.
- Versioned model package schema migrations.

## Risks And Open Decisions

- `joblib` package replay is trusted only for locally produced artifacts in this MVP. Loading arbitrary uploaded model packages would require isolation and policy checks.
- Metric equality is strict and suitable for same-process/same-environment smoke validation. Cross-platform validation needs tolerances and environment metadata.
- The UI exposes the action from Assets but does not yet show a dedicated validation history panel.
