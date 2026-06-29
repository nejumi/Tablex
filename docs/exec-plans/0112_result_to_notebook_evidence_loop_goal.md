# Result-to-Notebook Evidence Loop Goal

## Goal

Make the Result Readout's notebook evidence gap actionable. A human should be able to move from a top run to a readable model diagnostics evidence preview without knowing low-level notebook generation and capture endpoints.

## Implementation

- Added `prepare_result_notebook_evidence` as a harness-owned Job type.
- Added `POST /api/projects/{project_id}/results/notebook-evidence`.
- Added `tabular_harness.services.result_notebook_evidence` to select the current top run, reuse an existing model diagnostics notebook, generate one when missing, and create safe static evidence capture when needed.
- Added Evidence HTML, bundle, and figure artifact references to the notebook index.
- Added action metadata to `result_readout.v1.notebook` and routed the result read order directly to Notebooks evidence.
- Added Agent Chat intent/action for result-level notebook evidence requests.
- Added Result Evidence / Notebook Evidence actions in the Notebooks and Leaderboard UI surfaces.

## Boundaries

- No secret or connector credential access.
- No live marimo execution in this workflow.
- Notebook cells are not executed; capture uses harness-owned static evidence rendering and isolated syntax validation.
- EvaluationSpec and SplitManifest remain read-only context.
- This is a shortcut to current evidence, not a replacement for future Codex-authored deep notebook analysis.

## Follow-Up

- Let a controlled Codex runner author richer model diagnostics cells from the notebook authoring brief.
- Add executed feature importance, permutation importance, partial dependence, calibration, threshold, slice, and example-level artifacts when the runner can safely replay the model package.
- Improve UI preview transitions so a completed result evidence job can switch from Leaderboard to Notebooks only when that reduces cognitive load.
