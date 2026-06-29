# Goal 0048: Relational Feature Recipe Execution Preview

## Objective

Implement a preview-only relational feature recipe builder that turns the latest `relational_feature_plan` into artifact-backed, inspectable aggregation features for small local multi-table benchmark fixtures. The harness owns safety, artifacts, lineage, and UI context; AgentRunner/Codex receives the recipe as evidence and context, not as a fixed modeling mandate.

## Implemented Scope

- Added `build_relational_feature_recipe` service.
- Added `POST /api/projects/{project_id}/features/relational-recipe/build`.
- Added `build_relational_feature_recipe` job type.
- Stored `relational_feature_recipe`, `relational_feature_preview`, `relational_feature_preview_profile`, `relational_feature_recipe_report`, `visualization_spec`, Evidence, Report, and Lineage.
- Executed DuckDB preview joins for small registered supporting-table artifacts.
- Generated count/nunique/numeric aggregate previews while excluding target, leakage, test, and holdout-suspect columns.
- Deferred point-in-time-unconfirmed or missing-artifact steps instead of silently executing them.
- Propagated latest recipe summaries into AgentTaskContracts, ResearchBrief/Idea generation, and AgentContextPacks.
- Added Data tab actions and artifact preview/download rows for recipe outputs.
- Extended Home Credit tiny fixture integration coverage across recipe build, preview download, AgentTaskContract, and AgentContextPack.

## Deferred Scope

- Full production `FeatureRecipe` execution and training-fold materialization.
- General point-in-time joins, as-of windows, and time-aware relational aggregation fitting.
- Multi-hop relational joins and large supporting table execution.
- Runner-executed model training using the preview recipe.
- Automated external literature/web research for benchmark-specific relational approaches.

## Risks And Open Decisions

- Preview aggregates are intentionally simple and should not be interpreted as final production features.
- Numeric aggregation typing relies on RelationalCatalog physical-type inference and DuckDB execution.
- Point-in-time candidates are deferred until the harness has stronger time semantics and user/domain confirmation.
- Future runner tasks should compare primary-table-only, safe relational aggregates, and benchmark-informed alternatives under the approved EvaluationSpec and SplitManifest.
