# Model Diagnostics Notebook Goal

## Goal

Extend Analysis Notebook support from Data Understanding into run-level model diagnostics so Tablex can show model evidence, predictions, validation status, and next analysis gaps inside the product without requiring external notebooks or trackers.

## Scope Implemented

- Added `generate_model_diagnostics_notebook` job type.
- Added `POST /api/runs/{run_id}/analysis-notebook`.
- Generated model diagnostics notebook artifacts:
  - `analysis_notebook` marimo `.py` source.
  - `notebook_html` static in-product preview.
  - `notebook_run_manifest` with source artifacts, extension points, and safety policy.
  - `notebook_report` Markdown report plus `Report` record.
  - `visualization_spec` metric-card summary plus `VisualizationSpec` record.
- Added lineage from ExperimentRun, ModelVersion, and source artifacts to the notebook and derived artifacts.
- Added Experiments UI action for generating a model diagnostics notebook from a run row.
- Added HTML artifact preview support in the Experiments preview panel.
- Added integration coverage for source preview, HTML preview, manifest inputs, and visualization ids.

## Design Decisions

- The notebook consumes existing artifacts instead of recomputing model diagnostics in-process. Current inputs include baseline metrics, prediction output, evaluation diagnostics, model validation metrics, model package reference, run report, and related source artifacts when present.
- The MVP remains `generated_not_executed`. It gives Codex, Skills, and future controlled runners a concrete notebook and extension points without silently running arbitrary analysis code.
- Feature importance, permutation importance, partial dependence, calibration, threshold analysis, and prediction-slice drilldowns are named extension points. They should become artifact-backed cells/results under runner control rather than fixed harness recipes.
- VisualizationSpec is emitted so notebook coverage is visible through the existing visualization/report workbench.
- No secrets, connector credentials, external dashboards, or external network access are embedded.

## Deferred Work

- Controlled notebook execution and capture of rendered plots/tables.
- Model package inspection for fitted estimator feature importance.
- SplitManifest-backed permutation importance and partial dependence computation.
- Run selection and notebook history comparison UI.
- Figure-level artifact references inside notebook manifests.

## Risks

- Notebook code is generated and previewed but not executed, so runtime compatibility is still a future controlled-runner concern.
- Metrics and prediction summaries are limited to already persisted artifacts.
- Feature importance and partial dependence are intentionally not faked; users must see them as missing until a runner materializes evidence.
