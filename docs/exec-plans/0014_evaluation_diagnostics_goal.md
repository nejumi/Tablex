# Evaluation Diagnostics & Error Analysis Goal

## Goal

Add a first diagnostics loop after a baseline or experiment run so Tablex can explain where a run is weak without sending users to an external experiment tracker. Diagnostics should be artifact-backed, visible from the UI, and linked to Evidence, Insight, VisualizationSpec, and Lineage.

## Implemented

- Added run diagnostics endpoint:
  - `POST /api/runs/{run_id}/diagnostics`
- Added job type:
  - `analyze_evaluation_diagnostics`
- Reads the run's saved `prediction_output`, DatasetSnapshot, EvaluationSpec, and SplitManifest.
- Produces `evaluation_diagnostics` JSON artifacts with:
  - classification accuracy, error count, and confusion pairs
  - regression MAE, RMSE, mean error, and max absolute error
  - slice metrics for low-cardinality columns
  - score bins for classification and error bins for regression
  - worst examples with compact feature context
  - prediction/split sanity checks
- Produces an `evaluation_diagnostics_report` Markdown artifact.
- Produces a `visualization_spec` artifact for slice or error-bin charts.
- Creates Evidence and an `evaluation_diagnostics` Insight.
- Adds lineage from ExperimentRun, prediction output, EvaluationSpec, SplitManifest, Insight, and diagnostics artifacts.
- Adds Leaderboard UI actions to generate diagnostics per run.
- Adds Leaderboard UI panels for diagnostics artifacts and preview/download.
- Extends integration tests to generate diagnostics after the baseline flow.

## Deferred

- Full leakage analysis beyond prediction/split consistency checks.
- Multi-cut time-series diagnostics and drift-by-time plots.
- Calibration curves with probability vectors for multiclass classification.
- Interactive filtering of worst examples and slices in the UI.
- Runner-generated narrative diagnostics backed by Skill or literature research.
- Async worker execution for the diagnostics endpoint. It currently records the job and executes synchronously like other MVP feature endpoints.

## Risks And Open Decisions

- Slice metrics are heuristic and limited to low-cardinality columns to keep artifacts readable.
- The current prediction artifact stores a single score, not full class probabilities, so calibration-style bins are approximate.
- Worst examples intentionally include compact source feature context. Future privacy controls should govern which source values can be shown or exported.
- Diagnostics are generated from validation predictions only. Future agent runs should persist comparable prediction artifacts so the same diagnostics path works across runner implementations.
