# Notebook Evidence Integration Goal

## Goal

Fold notebook execution capture into the notebook index and UI guidance so capture status is first-class evidence, not a raw artifact users must discover manually.

## Implemented

- Extended `analysis_notebook_index.v1` counts with:
  - `with_execution_plan`,
  - `with_execution_capture`.
- Extended each notebook index item with latest related artifacts:
  - execution plan,
  - AgentTaskContract,
  - execution manifest,
  - execution report,
  - execution HTML,
  - figure manifest,
  - execution source copy.
- Extended notebook coverage with plan/capture/report/HTML/figure status and latest capture status.
- Added capture-aware recommendation scoring and reasons.
- Added capture-focused next actions when notebooks exist without capture evidence.
- Updated Notebooks and Reports tab metrics/coverage labels to show capture state.
- Added integration coverage for capture-aware notebook index output.

## Decisions

- Notebook Index remains the primary API for notebook discovery. UI components should not rederive notebook readiness from raw artifact lists when index coverage is available.
- Capture status is tracked at notebook-item level, while raw capture artifacts remain available in the Execution Evidence table for inspection and download.
- Captured notebooks receive a higher recommendation score because they have stronger in-product evidence, but model diagnostics still remains naturally prioritized after experiments.

## Deferred

- ProjectGuidance API stage logic based on notebook capture gaps.
- Decision Dashboard notebook evidence summaries.
- Notebook diff/comparison across capture versions.
- Full executed-cell lineage once a restricted marimo runtime exists.

## Risks

- Multiple captures currently collapse to the latest artifact per notebook. A version history view should follow once repeated notebook refinement becomes common.
