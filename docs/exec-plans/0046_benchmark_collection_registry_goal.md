# Benchmark Collection Registry Goal

## Goal

Implement Benchmark Collection & Source Registry v1 so practical benchmark datasets, especially Home Credit, can be discovered, prepared, and audited from inside Tablex without exposing secrets or forcing a fixed modeling recipe.

## Inputs Reviewed

- `benchmarks/catalog.json`
- `docs/benchmarks.md`
- `apps/backend/tabular_harness/services/benchmarks.py`
- Benchmark routes in `apps/backend/tabular_harness/api/routes.py`
- Data tab benchmark UI in `apps/frontend/src/main.tsx`
- Existing benchmark integration tests in `apps/backend/tests/test_api_flow.py`
- Official source URLs for Kaggle competitions, UCI datasets, and OpenML credit-g already captured in the catalog source cards.

## Implementation Plan

- Add catalog-wide `benchmark_collection_plan` and `benchmark_collection_report` artifacts for a project.
- Classify benchmarks by credential policy, public direct download availability, fixture availability, local readiness, multi-table shape, and time-series shape.
- Keep Kaggle and other credentialed sources as user-managed local downloads under `HARNESS_DATA_DIR/benchmarks`.
- Add `POST /api/projects/{project_id}/benchmarks/collection-plan`.
- Add Evidence, Report, VisualizationSpec, and Lineage for collection plans.
- Add Data tab UI to generate, preview, and download collection plans.
- Strengthen Kaggle source cards with verified official source URLs and credential-safety notes.
- Extend integration tests and developer docs.

## Technical Stack

- FastAPI synchronous MVP job endpoint.
- Existing benchmark catalog and local file readiness helpers.
- Local artifact store for JSON, Markdown, and visualization spec outputs.
- React Data tab using existing artifact preview/download APIs.

## Implemented Scope

- `benchmark_collection_plan.v1` JSON artifact.
- Markdown collection report with summary, recommended initial suite, readiness table, credential policy, and source audit.
- VisualizationSpec for credentialed, public, fixture, local-ready, and multi-table counts.
- Evidence and Report records with lineage from project/job to artifacts.
- Job output fields for benchmark counts and artifact ids.
- UI panel for collection plan generation and preview.
- Source card verification notes for Kaggle Home Credit Model Stability, IEEE-CIS Fraud, Store Sales, M5, Rossmann, and Instacart.

## Deferred Scope

- Downloading Kaggle competition files inside Tablex.
- Persisting Kaggle credentials or API tokens.
- Automated license acceptance or legal review.
- Full multi-table feature recipe execution for Home Credit real data.
- Benchmark score reporting against public leaderboards.

## Risks And Open Decisions

- Kaggle source URLs are catalog-level references; users must still comply with Kaggle competition terms outside Tablex.
- Local readiness only checks file presence and simple table metadata, not semantic correctness of every supporting table.
- Home Credit remains the primary practical multi-table benchmark, but real-data workflows need explicit EvaluationSpec, SplitManifest, leakage review, and relational FeatureRecipe/AgentTask design before scores should be trusted.
