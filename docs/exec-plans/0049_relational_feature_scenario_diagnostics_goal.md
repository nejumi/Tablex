# Goal 0049: Relational Feature Scenario Diagnostics

## Objective

Connect relational feature recipe previews to evaluation-first decision support without hard-coding a model strategy. The harness should summarize whether generated relational features are usable, risky, or deferred, then pass that evidence into AgentTask planning and context packs.

## Implemented Scope

- Added `diagnose_relational_feature_scenarios` service.
- Added `POST /api/projects/{project_id}/features/relational-scenarios/diagnose`.
- Added `diagnose_relational_feature_scenarios` job type.
- Stored `relational_feature_scenario_diagnostics`, `relational_feature_scenario_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage.
- Computed generated feature coverage, missingness, constant/high-cardinality flags, split compatibility, target availability policy, deferred reason summaries, scenario comparison, and recommended AgentTask scenarios.
- Propagated diagnostics summaries into AgentTaskContracts, ResearchBrief/Idea generation, and AgentContextPacks.
- Added Data tab action and preview/download rows for diagnostics artifacts.
- Extended the Home Credit tiny integration test across diagnostics, report preview, AgentTaskContract, and AgentContextPack handoff.

## Deferred Scope

- Model training or leaderboard registration for relational lift.
- Fold-fitted relational feature materialization.
- Time-aware point-in-time feature windows.
- Automated literature/web retrieval for benchmark-specific feature choices.

## Risks And Open Decisions

- Diagnostics are preview-level heuristics; they should guide runner planning, not authorize deployment.
- Missingness and cardinality thresholds are intentionally simple and should become configurable.
- Real relational lift must be tested later under the approved EvaluationSpec and SplitManifest.
