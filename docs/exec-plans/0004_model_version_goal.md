# Model Version Goal

## Goal

Promote successful strong baseline outputs from a run-only result into reusable model assets owned by the harness. A baseline run should leave a persisted package artifact and a `ModelVersion` record with evaluation context, metrics, lineage, and UI visibility.

## Implemented Scope

- Added `ModelVersion` SQLAlchemy model.
- Added `ModelVersionRead` API schema.
- Added project-level and single-record ModelVersion API endpoints.
- Added `model_version_id` to baseline job output, run list, and leaderboard entries.
- Serialized successful XGBoost baseline packages to `model_package.joblib`.
- Registered the package as a `model_package` artifact.
- Linked `ExperimentRun`, `model_package`, `baseline_plan`, `feature_recipe`, and `ModelVersion` through lineage edges.
- Updated Assets UI to show ModelVersions and their package artifact ids.
- Added API integration coverage for model version creation.
- Follow-up Goal `0005_model_package_validation_goal.md` adds saved package replay validation.

## Model Package Contents

- XGBoost model object.
- Fitted `StrongFeatureBuilder`.
- Optional label encoder for classification.
- BaselinePlan.
- FeatureRecipe.
- Metrics.
- Run metadata with dataset, EvaluationSpec, SplitManifest, and target column references.

## Deferred Scope

- General prediction API.
- ModelVersion promotion states such as candidate, approved, archived, deployment-blocked.
- Model package compatibility checks across library versions.
- Explicit model card/report page.
- ModelVersion comparison UI.
