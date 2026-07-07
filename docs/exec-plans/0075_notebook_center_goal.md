# Notebook Center Goal

## Goal

Make generated analysis notebooks easy to find and choose from inside Tablex. The UI should guide users to the most relevant notebook instead of asking them to interpret raw artifact lists.

## Scope Implemented

- Added `GET /api/projects/{project_id}/analysis-notebooks`.
- Added `analysis_notebook_index.v1` response with:
  - total and by-kind notebook counts,
  - recommended notebook,
  - grouped notebook history,
  - linked source/report/manifest/visualization artifact ids,
  - coverage flags,
  - next actions.
- Added Reports tab Notebook Center panel with:
  - recommended notebook card,
  - native marimo open/download actions,
  - compact coverage metrics,
  - recent notebook history table.
- Added integration coverage for indexing both Data Understanding and Model Diagnostics notebooks.

## Design Decisions

- The index is derived from persisted artifacts and Report/VisualizationSpec rows. It does not create new durable state.
- The recommended notebook favors model diagnostics when available because it is usually more actionable after a run, but data understanding remains the recommended starting point when model notebooks do not exist.
- Notebook Center keeps the raw Analysis Notebooks artifact table available below the guided panel.
- The center opens native marimo source notebooks directly. Static HTML snapshots are not notebook evidence and are not used as fallback.

## Deferred Work

- Notebook comparison/diff view.
- Figure-level artifact inventory.
- Full notebook execution history.
- Filtering by run, model version, dataset, and evaluation spec.

## Risks

- The index is metadata-derived and can be incomplete if older artifacts lack expected metadata.
- Recommendation scoring is intentionally simple and should become stage-aware as notebook volume grows.
