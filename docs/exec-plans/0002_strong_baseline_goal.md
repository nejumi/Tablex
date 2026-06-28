# Strong Baseline Goal

## Goal

Build a defensible first baseline for tabular prediction tasks. The baseline should be stronger than median or majority prediction while still respecting the harness-owned EvaluationSpec, SplitManifest, artifacts, lineage, and safety controls.

## Implemented Scope

- Added XGBoost as the primary local strong baseline.
- Kept LogisticRegression/Ridge and majority/mean baselines as fallback and sanity floor.
- Added BaselinePlan artifact output.
- Added FeatureRecipe artifact output.
- Added numeric median imputation.
- Added categorical ordinal encoding with unknown bucket.
- Added text-column detection and per-column TF-IDF features.
- Added datetime calendar features.
- Added safe lag/rolling covariate feature generation gated behind approved time splits.
- Added report sections for selected model, feature roles, ignored identifiers, text features, and metric summary.
- Updated UI tables to show baseline type and feature count.

## Safety Constraints

- Target column is always excluded from features.
- EvaluationSpec excluded columns are respected.
- SplitManifest train/valid assignments are respected.
- Validation/test target values are not used during feature fitting.
- Target-derived lag features are disabled in this milestone.
- Lag and rolling covariate features are enabled only when the approved EvaluationSpec is a time split.

## Deferred Scope

- Automatic external research and recipe proposal by AgentRunner.
- User approval UI for adopting or rejecting a BaselinePlan.
- Time split generation implementation.
- Target lag features with explicit forecasting semantics.
- Hyperparameter search and cross-validation.
- SHAP or feature importance views.

## Open Decisions

- Whether XGBoost should remain a required dependency or become optional with a degraded local fallback.
- How to represent BaselinePlan and FeatureRecipe as first-class DB models versus artifact-only assets.
- How much recipe selection should be heuristic versus agent-proposed.
