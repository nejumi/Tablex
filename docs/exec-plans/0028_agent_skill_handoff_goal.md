# 0028 Agent Skill Handoff Goal

## Goal

Implement Agent Skill Handoff v1 so ResearchPlan-recommended cross-project library assets become explicit runner context without turning them into fixed harness recipes.

## Spec And Context Reviewed

- `README.md`
- `AGENTS.md`
- `docs/dev.md`
- `docs/exec-plans/0001_initial_implementation_plan.md`
- `docs/exec-plans/0024_controlled_research_skill_planning_goal.md`
- `docs/exec-plans/0027_skill_feature_recipe_pack_goal.md`
- `schemas/agent_context_pack.schema.json`
- `schemas/agent_task_contract.schema.json`
- `schemas/agent_workspace_manifest.schema.json`
- `schemas/research_plan.schema.json`
- Backend services for ResearchPlan, AgentContextPack, AgentTask workspace materialization, and Asset Library seeding.

## Implementation Direction

- Keep the harness owner of evaluation, SplitManifest, artifact lineage, source policy, and safety controls.
- Treat Skill, FeatureRecipe, EvaluationPattern, PromptTemplate, and VisualizationTemplate assets as recommended references and citations for the runner.
- Do not hard-code a single baseline execution path into the handoff. The runner can still select and justify an approach using project context, ResearchPlan, Skills, and approved policy.
- Materialize only artifact-backed AssetVersion content into a controlled workspace. Do not materialize secrets, connector credentials, or external service state.

## Implemented Scope

- `AgentTaskContract.inputs` now carries ResearchPlan-derived recommended asset ids, recommended asset version ids, and source policy.
- `AgentContextPack` now includes:
  - `asset_recommendations`
  - `materialized_library_assets`
  - lineage from recommended AssetVersion records to the context artifact.
- Controlled agent workspace materialization now copies recommended library asset artifacts into `.harness/context/library_assets/`.
- Workspace manifest source entries record artifact id, asset id, asset version id, asset name, source, sources, and recommendation reason.
- Integration tests assert the full handoff path from ResearchPlan to AgentTaskContract, AgentContextPack, workspace manifest, and materialized library asset paths.

## Deferred Scope

- Real Codex execution against the materialized library assets.
- Network-enabled controlled literature or web search execution.
- UI-specific parsed rendering of AgentContextPack recommendations beyond the current JSON preview.
- Version conflict resolution when multiple ResearchPlans recommend different versions of the same asset.
- Runner-side ranking of recommended assets based on live experiment results.

## Risks And Open Questions

- ResearchPlan recommendations currently use latest active AssetVersion ids. Later work should support pinned recommendation versions and review/approval before runner execution.
- ContextPack preview can become large as more artifacts are attached. A structured UI panel for asset recommendations will be needed.
- Workspace materialization trusts harness-generated `context_path` after validating relative path safety. If third-party context packs are allowed later, schema and signature checks should be stricter.
- Asset artifacts are copied as-is. Some future asset types may need richer packaging or dependency metadata.

## Validation Plan

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- Frontend lint and build.
- Docker build and smoke test.
