# Job And Validation History Goal

## Goal

Make synchronous MVP work visible inside Tablex rather than requiring developers to inspect logs, external tools, or raw database rows. Project users should be able to see all jobs in the UI and inspect ModelVersion package validation history from the ModelVersion asset surface.

## Implemented Scope

- Reused the existing project job listing API: `GET /api/projects/{project_id}/jobs`.
- Added `ModelValidationRead` API schema.
- Added `GET /api/model-versions/{model_version_id}/validations`.
- Aggregated validation history from `validate_model_package` Job input/output and validation artifact ids.
- Returned validation status, max metric delta, metrics, linked artifacts, and the source Job for each validation.
- Added `Jobs` to the Project detail tabs.
- Added a Job History UI with job type, status, timestamps, input, output, and error message visibility.
- Added latest validation summary to the ModelVersions table.
- Added a Model Package Validation History table in the Assets tab.
- Extended API integration tests to cover project jobs and model validation history.
- Follow-up Goal `0007_artifact_preview_goal.md` adds preview and download affordances for registered artifacts.

## Design Decision

No new persistence model was added for validation history. For this MVP, the Job row is the execution record and validation artifacts are the durable outputs. The read API composes a user-facing view from those records. A dedicated validation table can be added later if review state, approval, or deployment blocking policy needs stronger structure.

## Deferred Scope

- Dedicated validation detail page.
- Artifact preview/download links embedded directly in history rows.
- User review state for validation warnings.
- Async job queue, retries, resumability, and cancellation enforcement beyond the current stub.
- Filtering and pagination for large job histories.

## Risks And Open Decisions

- The history API currently filters validation jobs by JSON payload in application code, which is acceptable for the SQLite MVP but should become indexed metadata or a dedicated table as volume grows.
- Job input/output rendering in the UI is intentionally compact. Rich inspectors for contracts, artifacts, and error traces are still needed.
