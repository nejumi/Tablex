# Analysis Notebook Goal

## Goal

Make visualization and analysis artifacts first-class inside Tablex by generating a marimo-based analysis notebook from the current Data Understanding context, together with a manifest, report, native marimo viewing path, and lineage.

## Scope Implemented

- Added a `generate_data_understanding_notebook` job type.
- Added `POST /api/projects/{project_id}/analysis-notebooks/data-understanding`.
- Generated notebook-related artifacts:
  - `analysis_notebook`: editable marimo `.py` source.
  - `notebook_run_manifest`: execution policy and artifact mapping.
  - `notebook_report`: Markdown report plus `Report` record.
- Added lineage from DatasetSnapshot and source artifacts to the notebook and derived report/manifest artifacts.
- Extended artifact preview support for `.html` and `.py`.
- Added Reports tab UI for notebook generation, native marimo opening, and source download.
- Added API integration coverage for notebook generation and preview.

## Design Decisions

- Notebook generation is artifact-first and self-contained. Users can open the native marimo notebook inside Tablex and download the marimo source without opening external dashboards.
- The MVP endpoint does not execute marimo. It records `generated_not_executed` in the manifest and keeps future execution modes explicit.
- The generated notebook includes pandas, matplotlib, and Plotly cells for data understanding. Modeling diagnostics sections are present and intended to consume future ExperimentRun/model artifacts such as feature importance, permutation importance, partial dependence, slice metrics, and prediction analysis.
- Superseded: static HTML notebook snapshots are not notebook evidence and must not be used as fallback. Native marimo source is the notebook artifact of record.
- Secrets, connector credentials, and external network access are explicitly excluded from notebook generation and manifest metadata.

## Deferred Work

- Persisted notebook execution outputs as separate figure/table artifacts.
- Model diagnostic notebook generation from a selected ExperimentRun or ModelVersion.
- UI drill-down for notebook lineage and figure-level artifacts.

## Risks

- The marimo source is generated but not executed in this milestone; syntax/runtime compatibility should be validated when a controlled notebook runner is added.
- Native marimo runtime failures must surface as repair targets rather than being hidden behind snapshots.
- Future diagnostic notebooks must keep EvaluationSpec and SplitManifest constraints explicit to avoid post-hoc leakage.
