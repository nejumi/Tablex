# Flexible Baseline Strategy Planner Goal

## Goal

Separate baseline strategy planning from baseline execution. Tablex should not imply that one fixed baseline recipe is universally correct; it should record candidate strategies, current constraints, selected execution, deferred AgentTask work, and risks as first-class artifacts.

## Implemented

- Added `schemas/baseline_strategy_plan.schema.json`.
- Added `plan_baseline_strategy` job type.
- Added `POST /api/projects/{project_id}/baseline/strategy-plan`.
- Strategy planning reads the current DatasetSnapshot, EvaluationSpec, SplitManifest, baseline feature inventory, DataQualityGate metadata, and RelationalCatalog metadata.
- The plan records:
  - sanity floor candidate
  - strong single-table XGBoost candidate
  - text TF-IDF branch
  - categorical ordinal encoding branch
  - datetime calendar branch
  - time-series lag/rolling branch
  - relational aggregation candidate that requires an AgentTask when supporting tables exist
- `run_baseline` now stores a `baseline_strategy_plan` artifact linked to the run.
- Baseline reports include a Strategy Plan section.
- Model packages include the strategy plan payload.
- Agent workspaces copy `baseline_strategy_plan.json` when available.
- Experiments UI can generate a strategy plan, and previews baseline strategy/plan/report/metrics artifacts.

## Design Choices

- The current executable local baseline remains the strong single-table runner.
- Relational features are explicitly marked `agent_required` until join semantics, aggregation windows, and prediction-time availability are confirmed.
- Strategy plans are artifacts, not DB tables, to keep the MVP schema stable.

## Deferred

- Strategy comparison UI beyond JSON preview.
- Baseline strategy approval workflow.
- Benchmark-specific starter FeatureRecipes.
- Actual relational aggregation feature execution.
- Online literature/search runner integration for baseline strategy selection.

## Risks And Open Decisions

- Candidate statuses are heuristic and should become evidence-backed as Skill and research runners mature.
- DataQualityGate metadata is summarized; full quality payload should be previewed for high-risk interpretation.
- Baseline strategy artifacts should be refreshed after EvaluationSpec, SplitManifest, or RelationalCatalog changes.
