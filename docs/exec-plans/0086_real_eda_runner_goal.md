# Real EDA Runner v1 Goal

## Objective

Move beyond static notebook scaffolds by adding a harness-owned EDA execution path that reads the uploaded dataset artifact, computes richer evidence with DuckDB, stores the result as first-class artifacts, and surfaces it as the first thing a human should read.

## Implemented Direction

- Add `/api/datasets/{dataset_id}/eda-review`.
- Create `run_eda_review` jobs with no external network, no connector credential materialization, and no user code execution.
- Generate first-class artifacts:
  - `eda_review_bundle`,
  - `eda_review_html`,
  - `eda_review_svg`,
  - `eda_review_report`,
  - `visualization_spec`.
- Register Report, Evidence, Insight, and lineage from DatasetSnapshot to all review artifacts.
- Compute real dataset-derived review evidence:
  - shape and target status,
  - missingness pressure,
  - numeric medians/IQR/outlier hints,
  - categorical cardinality/top values,
  - simple target relationships when a target exists,
  - numeric correlation candidates,
  - findings, read order, story cards, review playbook, and Codex next prompts.
- Add Agent Chat intent routing for EDA/Data Review requests.
- Add Notebooks tab action and Data Review evidence card so the output appears in the same Current Review surface.

## Quality Bar

- The review must read as a human-facing analysis artifact, not raw JSON or a smoke-test proof.
- The review must be generated from actual dataset content when available.
- If target is missing, the review should still be useful for understanding, while clearly stating that target-aware modeling is blocked.
- Claims must remain artifact-backed and lineage-tracked.
- Agent Chat is a valid command surface for running the review; specialized UI buttons are shortcuts.

## Deferred Work

- Controlled marimo execution/export with real plotly/matplotlib cells.
- More robust statistical testing and distribution comparison.
- Time-series-specific lags/rolling/day-of-week review when temporal semantics are confirmed.
- Relational/multi-table EDA review that uses relational catalogs and ER diagram hints.
- Richer visual layout and drill-down interactions in the frontend renderer.
