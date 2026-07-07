# EDA Quality v1 Goal

## Goal

Move generated Data Understanding notebooks from a basic profile dump toward a human-readable, target-aware EDA narrative. The harness should provide a quality rubric, storyboard, guardrails, and artifact expectations while leaving the actual analysis approach flexible for Codex, Skills, and future controlled notebook runners.

## Implemented Scope

- Extended Data Understanding notebook summary payload with:
  - EDA quality rubric,
  - EDA quality score,
  - analysis storyboard,
  - target readiness summary,
  - feature review queues,
  - leakage and evaluation guardrails,
  - richer analysis questions.
- Updated generated marimo source to put quality, target readiness, storyboard, and guardrails before raw column tables.
- Updated the notebook source and native marimo viewing path so the same narrative sections are available inside the workbench.
- Updated notebook report and run manifest with quality metadata.
- Updated `skills/tablex-notebook-quality/SKILL.md` with a concrete quality rubric for future Codex runners.
- Added integration assertions for notebook source registration and manifest quality fields.

## Deferred Scope

- Executed marimo cells and captured rendered figure/table artifacts.
- Dataset-specific bivariate/multivariate plotting selected by Codex.
- Full target-aware distribution plots, cohort analysis, drift checks, and split-aware plots.
- Model diagnostics generated from actual model artifacts: feature importance, permutation importance, PDP, calibration, threshold analysis, slice metrics, residual/error review, and prediction examples.
- Literature/web-informed dataset-specific EDA pattern selection.

## Design Notes

- This milestone intentionally does not hard-code a single EDA recipe. It records a quality bar and investigation queues so a future Codex runner can choose analysis tactics based on dataset semantics, target construction, EvaluationSpec, SplitManifest, assumptions, and available artifacts.
- The current output is a stronger scaffold and reader experience, not yet a fully executed Kaggle Grandmaster-style notebook.
- Missing execution, missing target, sample-backed profiles, and deferred diagnostics are labeled explicitly instead of hidden.

## Verification

- `python3 -m ruff check apps/backend/tabular_harness/services/analysis_notebooks.py apps/backend/tests/test_api_flow.py`
- `python3 -m mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest apps/backend/tests/test_api_flow.py::test_project_upload_profile_evaluation_split_flow -q`
- `python3 /home/yuya/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/tablex-notebook-quality`
