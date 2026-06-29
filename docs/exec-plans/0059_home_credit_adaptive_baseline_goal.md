# 0059 Home Credit Adaptive Baseline Goal

## Goal

Validate that Tablex can move from Home Credit readiness into a strong local baseline and agent handoff without turning the product into a fixed AutoML recipe. Baseline planning should be fast and profile-driven; full baseline execution may be heavier, but it must preserve EvaluationSpec, SplitManifest, quality boundaries, artifacts, reports, diagnostics, and lineage.

## Implementation Plan

- Change `create_baseline_strategy_plan` to build the current baseline plan from `eda_profile` metadata instead of loading all split rows.
- Keep `run_baseline` as the execution path that loads approved split rows and trains/evaluates the model.
- Add `planning_source=eda_profile`, profile boundary, and `resource_guard` to baseline plans and strategy plans.
- Surface resource guard level and planning source in API job output, artifact metadata, and the Experiments UI strategy summary.
- Preserve flexible strategy language: XGBoost is a strong local candidate, not the only possible approach; richer relational/time-aware variants remain candidate strategies or AgentTasks.
- Add tests for profile-driven baseline planning and Home Credit ID heuristic behavior.

## In Scope

- Baseline strategy planning speed and metadata.
- Home Credit strong local XGBoost baseline smoke.
- Run diagnostics and run report generation after the baseline.
- UI/docs/tests for planning source and resource guard metadata.

## Out Of Scope

- Full relational Home Credit feature generation.
- Codex CLI execution of a custom Home Credit modeling approach.
- Hyperparameter search or leaderboard optimization.
- Deep-profile job implementation.

## Verification Notes

- Before this change, Home Credit `baseline/strategy-plan` took about 90 seconds because it loaded all split rows.
- After the change, the same endpoint completed in about 0.05 seconds with `planning_source=eda_profile` and `resource_guard_level=large_local_run`.
- Full Home Credit `baseline/run` completed in about 170 seconds on the approved stratified split:
  - baseline type: `xgboost_classifier`
  - train rows: 246008
  - valid rows: 61503
  - feature count: 214
  - PR-AUC: 0.22542263643463037
  - ROC-AUC: 0.7484397699599913
  - log loss: 0.2500398818848818
  - majority sanity floor PR-AUC: about 0.0807
- Evaluation diagnostics completed in about 31 seconds and run report generation completed immediately after.

## Risks and Open Questions

- Full local baseline still loads the approved split into Python dictionaries; this is acceptable for a smoke but should eventually become streaming or DuckDB-backed for larger datasets.
- Home Credit supporting tables are not yet part of the executed baseline. Relational aggregation remains a FeatureRecipe/AgentTask path with train-fold safety requirements.
- The strategy plan intentionally recommends approaches and guardrails without freezing the modeling approach. Future Codex/Skill runners should be allowed to reject or revise the suggested XGBoost candidate with evidence.
