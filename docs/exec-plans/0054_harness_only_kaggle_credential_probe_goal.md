# 0054 Harness-Only Kaggle Credential Probe Goal

## Goal

Enable Tablex to verify Kaggle competition access from the product without exposing credentials to Codex, AgentRunner workspaces, prompts, artifacts, or logs. This is an access/readiness probe only, not a benchmark downloader.

## Context Read

- `benchmarks/catalog.json`
- `apps/backend/tabular_harness/services/benchmarks.py`
- `apps/backend/tabular_harness/api/routes.py`
- `apps/backend/tabular_harness/services/jobs.py`
- `apps/frontend/src/main.tsx`
- `apps/frontend/src/styles.css`
- `docs/benchmarks.md`
- `docs/dev.md`
- `AGENTS.md`
- `tabular_prediction_meta_harness_spec_v2/docs/07_ui_ux_spec.md`

## Implementation Plan

- Add a `kaggle_probe` backend service that reads Kaggle env values inside the harness process only.
- Support `KAGGLE_API_TOKEN` JSON, `username:key`, `KAGGLE_USERNAME` plus `KAGGLE_API_TOKEN`, and legacy `KAGGLE_USERNAME` plus `KAGGLE_KEY`.
- Call Kaggle's competition file-list API for slug-level access verification, not file download.
- Store a `kaggle_credential_probe.v1` artifact containing status, HTTP status, credential source labels, auth scheme labels, and next actions, with no credential values.
- Add a synchronous `probe_kaggle_benchmark_access` Job and `/api/benchmarks/{benchmark_id}/kaggle/probe`.
- Extend benchmark source cards/import readiness with a `credential_probe` section.
- Add Data tab UI for credentialed Kaggle source cards: probe-ready badge, credential gate strip, and Probe action.
- Update docs and AGENTS with credential boundary and UI quality principles.

## Tech Stack

- Backend: FastAPI, SQLAlchemy Job model, local artifact store, stdlib `urllib.request`.
- Frontend: React/Vite, lucide icons, existing API helper and Data tab catalog surface.
- Schemas: `benchmark_source_card.schema.json`, new `kaggle_credential_probe.schema.json`.

## In Scope

- Secret-free credential discovery from environment or gitignored `.env`.
- Kaggle access probe artifact and job output.
- UI action and immediate session-level probe result display.
- Unit and integration tests with mocked network and no real credentials.

## Out of Scope

- Managed Kaggle dataset download.
- Kaggle competition rule acceptance.
- Passing Kaggle data or credentials into AgentRunner workspaces.
- Persisting credential values, usernames, token fragments, or response bodies.

## Risks And Open Questions

- Kaggle token conventions can vary. The implementation tries several safe auth candidates but records only source labels and auth schemes.
- The probe may return `forbidden_or_rules_required` when credentials are valid but competition rules have not been accepted.
- Future downloader work must remain harness-owned and must not widen AgentRunner credential access.
- The UI needs a broader product-wide visual design pass. This goal starts by making benchmark access gates richer and more decision-oriented, but the whole workbench should move toward a more exciting, inspectable experience.

## Verification Notes

- Unit/integration tests cover credential candidate selection, secret-free probe payloads, retry after unauthorized auth candidates, and endpoint artifact creation with mocked network.
- A real harness endpoint probe was run against `kaggle_home_credit_default_risk` using the local gitignored `.env`/process environment. It returned `probe_status=ok`, `http_status=200`, `can_access_competition_files=true`, and stored artifact `art_de479bbfae74`.
- The real probe output exposed only credential source labels and auth schemes, not credential values.
