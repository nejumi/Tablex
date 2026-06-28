# Controlled Research & Skill Planning Goal

## Goal

Add a harness-owned ResearchPlan layer before ResearchBrief, Idea generation, and AgentRunner execution. The plan should support flexible, evidence-backed approach selection without hard-coding a single baseline recipe or handing product control to Codex.

## Implemented Scope

- Added `research_plan` artifacts with `schema_version: research_plan.v1`.
- Added `/api/projects/{project_id}/approach/research-plan`.
- The plan summarizes project, dataset, EvaluationSpec, DataQualityGate, RelationalCatalog, EvaluationScenarioComparison, EvaluationApprovalReview, and BaselineStrategyPlan context.
- The plan emits controlled web/literature query candidates, cross-project asset availability, recommended Skill/FeatureRecipe/EvaluationPattern references, missing asset suggestions, source policy, credential policy, expected Evidence shape, and reporting/visualization requirements.
- ResearchBrief source lists now include the latest ResearchPlan when available.
- generated Ideas include `research_plan_artifact_id` in their AgentTaskContract inputs.
- AgentContextPack now includes `research_plan_context`.
- Controlled agent workspaces copy `research_plan.json` when available.
- Approach UI can generate, list, preview, and download ResearchPlan artifacts.

## Design Notes

- Network search is still disabled by default. The ResearchPlan is a contract for a future controlled research runner, not a hidden external dependency.
- Credentials and connector secrets remain forbidden and are never materialized for agents.
- Cross-project Skill assets are recommendations and references. Project-specific artifacts remain in the project workspace.
- Baseline and approach selection remain flexible: the harness guides evaluation, safety, lineage, and reporting, while the runner can later use Skills and timely research to justify modeling choices.

## Deferred Scope

- Actual web or literature search execution.
- Citation ingestion UI beyond artifact/Evidence placeholders.
- Rich source ranking and deduplication.
- Automatic Skill installation or remote package fetching.
- Human approval workflow for enabling network search.

## Validation

- Backend unit/integration tests should cover ResearchPlan generation, ResearchBrief source propagation, Idea contract propagation, AgentContextPack propagation, and workspace materialization.
- Frontend lint/build should cover Approach UI additions.
- Docker smoke should verify the single-image app still serves health and benchmark catalog endpoints.
