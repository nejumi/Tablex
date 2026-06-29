# 0114 Artifact-Backed Model Diagnostics Runner Goal

## Goal

Implement Tablex Artifact-Backed Model Diagnostics Runner v1 so model behavior evidence is not a placeholder notebook section. The runner must materialize real artifacts from an existing ExperimentRun where possible, expose the result through Result Readout, Notebook Evidence Review, and Agent Chat, and keep EvaluationSpec and SplitManifest as read-only constraints.

## Implemented Scope

- Added an in-harness `materialize_model_diagnostics_artifacts` service.
- Added job/API support for `materialize_model_diagnostics_artifacts`.
- Materializes these project artifacts:
  - `feature_importance`
  - `permutation_importance`
  - `model_diagnostics_artifact_pack`
  - `model_diagnostics_artifact_report`
  - `visualization_spec`
- Uses the stored model package, validation predictions, EvaluationSpec, SplitManifest, and run diagnostics.
- Computes bounded validation-split permutation importance on a deterministic sample.
- Adds calibration bins, threshold review, slice metric pointers, worst-example pointers, interpretation, limitations, Evidence, Insight, and lineage edges.
- Blocks with explicit reasons instead of inventing charts when model, split, prediction, or replay inputs are missing.
- Updated model diagnostics notebook evidence so Notebook Evidence Review includes:
  - result interpretation
  - read order
  - visual story cards
  - native feature importance figure
  - permutation importance figure
  - prediction score bins
- Updated Result Readout/Leaderboard actions with a simple `Model Evidence` action.
- Updated Agent Chat so feature-importance/permutation requests create a controlled AgentTaskContract and immediately materialize model evidence when a top run has source artifacts.

## Home Credit Validation

Validated on project `p_9d0e521c26dc`, top run `run_64b7466ffa17`.

Latest checked artifacts:

- `feature_importance`: `art_0778fe0286e7`
- `permutation_importance`: `art_1f940cc233ce`
- `model_diagnostics_artifact_pack`: `art_25b37421805c`
- `model_diagnostics_artifact_report`: `art_8fe4d71d8888`
- `visualization_spec`: `art_8284faea8c69`
- Notebook Evidence HTML after regeneration: `art_88829e1f2271`

Observed availability:

- `native_feature_importance`: ready
- `permutation_importance`: ready
- `prediction_review`: ready
- `score_bins`: ready
- `slice_metrics`: ready
- `worst_examples`: ready

Key Home Credit evidence:

- Native importance top signals: `EXT_SOURCE_2`, `EXT_SOURCE_3`, `NAME_INCOME_TYPE`, `NAME_EDUCATION_TYPE`.
- Permutation importance top signals: `EXT_SOURCE_3`, `EXT_SOURCE_2`, `AMT_GOODS_PRICE`, `NAME_EDUCATION_TYPE`.
- Result Readout can show the markdown diagnostics report.
- Notebook Evidence Review renders `Native Feature Importance` and `Permutation Importance` figures in-browser.
- Agent Chat now routes model-evidence requests to Result Readout first when artifacts are materialized.

## Design Boundaries

- No W&B or MLflow dependency.
- No external network access from the chat/job action.
- No connector credentials or secrets are materialized.
- EvaluationSpec is not modified.
- SplitManifest is respected; permutation uses validation rows only.
- Permutation computation is bounded for UI-safe latency and records the sample policy.
- Feature importance is model behavior evidence, not causal evidence.

## Remaining Risks

- Repeated `Model Evidence` clicks currently create a new artifact pack each time. This is lineage-correct but may need a reuse/latest policy for heavy runs.
- Native importance is estimator-specific. XGBoost and sklearn-style `feature_importances_` are covered; linear coefficients and SHAP/PDP remain future extensions.
- Permutation importance densifies the bounded sample; very wide text feature spaces may still block with an explicit reason.
- The action can take around 20 seconds on the Home Credit run. The ephemeral Agent Activity UI should make this feel more alive in a future iteration.

## Follow-Up

- Add reusable cache/reuse semantics for identical model evidence materializations.
- Add linear model coefficient interpretation and optional PDP/ICE artifacts.
- Add cost-aware threshold notes when business cost assumptions exist.
- Add a slimmer visual treatment for long markdown diagnostics reports.
- Connect the controlled AgentTaskContract to a real Codex runner path for deeper notebook/report revisions.

