# Model Diagnostics Evidence Quality Goal

## Goal

Make model diagnostics evidence readable enough for a human decision loop. A top run should open with interpretation, sanity-floor context, read order, visual evidence, and one clear next action instead of a raw notebook artifact list.

## Implementation

- Reworked the model diagnostics readiness figure from mixed-scale bars into metric cards for primary metric, prediction coverage, diagnostics readiness, and quality.
- Added sanity-floor comparison to model diagnostics evidence, including metric direction handling for higher-is-better and lower-is-better metrics.
- Added a `Result interpretation` callout to Notebook Evidence Review HTML with verdict, narrative, sanity-floor delta, and next one action.
- Propagated interpretation, metric comparison, and sanity-floor data into the notebook evidence bundle for future UI and runner consumption.
- Updated Notebooks `Ask Codex next` prompts so task-like prompts are visually distinct and create targeted notebook follow-up handoffs instead of acting like passive chat.
- Verified the Home Credit project can generate and display an evidence review for the top run with `pr_auc=0.225423`, `61,503` prediction rows, and sanity floor comparison.

## Boundaries

- No secret, connector credential, or `.env` access.
- EvaluationSpec and SplitManifest remain source-of-truth context and are not rewritten by notebook evidence generation.
- Notebook cells are still not executed in this path; the harness renders safe static evidence from stored artifacts.
- This improves the evidence reading and follow-up handoff loop, not the underlying model replay engine.

## Validation

- Backend unit and integration tests cover metric direction handling and rendered evidence fields.
- Browser verification confirmed:
  - `Leaderboard` is a primary project tab between `Notebooks` and `Reports`.
  - `Notebook Evidence` updates the Result Readout preview in place.
  - Notebooks opens with the current story preview, result interpretation, read order, story cards, and guarded next prompts.
  - A task-like Notebook prompt creates a human-readable Runner Handoff response and routes to `Approach`.

## Follow-Up

- Execute the notebook follow-up runner to materialize real feature importance, permutation importance, calibration, threshold, slice, and worst-example artifacts.
- Replace static evidence capture with controlled executed notebooks when the runner workspace can safely replay model packages.
- Keep reducing raw artifact shelves and make the next useful evidence gap the primary screen element.
