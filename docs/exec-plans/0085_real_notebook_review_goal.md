# Real Notebook Review v1 Goal

## Objective

Stop treating notebook artifacts as useful just because they exist. Notebook review must be content-aware, human-readable, and guided. Empty model diagnostics are readiness failures, not evidence.

## Implemented Direction

- Add notebook content signals to the project notebook index:
  - `readiness`,
  - `quality_score`,
  - read-order count,
  - story-card count,
  - playbook count,
  - prediction row count for model diagnostics.
- Prefer Data Understanding until a model diagnostics notebook has real metric, prediction, and diagnostics evidence.
- Penalize `model_diagnostics` notebooks with missing primary metric or zero prediction rows.
- Generate model-diagnostics evidence sections even when the run is incomplete:
  - readiness verdict,
  - prediction coverage,
  - metric/split context,
  - review playbook,
  - diagnostics guardrails,
  - Codex follow-up prompts.
- Render model-diagnostics evidence figures from available run context:
  - diagnostics readiness,
  - feature-family inventory,
  - prediction score bins,
  - diagnostics attention counts.
- Change generic evidence copy from "Notebook EDA Evidence" to "Notebook Evidence Review" so Model Diagnostics is not mislabeled as EDA.
- In the Notebook UI, route away from empty Model Diagnostics to Data Understanding when an older stale index would otherwise recommend it.

## Non-Negotiable Quality Rules

- A notebook with `prediction_rows=0` must not be presented as the primary model evidence.
- `No read order generated yet`, `No visual story cards generated yet`, and `No EDA playbook generated yet` are unacceptable in the primary review surface.
- Raw artifact shelves are secondary debug surfaces, not the main UX.
- The user should see one clear current review, why it is current, and what to ask Codex next.
- Model claims require artifact-backed metrics, predictions, diagnostics, and EvaluationSpec/SplitManifest boundaries.

## Deferred Work

- Execute marimo notebooks in a controlled runner and capture real plotly/matplotlib output.
- Add richer model diagnostics: feature importance, permutation importance, partial dependence, calibration, threshold curves, slice metrics, worst examples, and error narratives.
- Replace remaining table-heavy UI areas with guided summaries and progressive disclosure.
- Add artifact migration or regeneration guidance for stale notebooks created before this quality gate.
