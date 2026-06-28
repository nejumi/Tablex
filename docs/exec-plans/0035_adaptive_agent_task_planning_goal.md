# 0035 Adaptive Agent Task Planning Goal

## Goal

Create a harness-owned planner that generates runner-ready `AgentTaskContract` artifacts from current project context without turning Tablex into a fixed baseline recipe runner.

## Read Inputs

- Existing ResearchPlan, Idea, AgentContextPack, AgentRunner, Asset Library, job, artifact, and lineage services.
- `schemas/agent_task_contract.schema.json`
- `docs/dev.md`, `README.md`, and prior exec plans around flexible baseline strategy, controlled research, and agent skill handoff.

## Implementation

- Added `services/agent_task_planner.py`.
- Added `plan_agent_task` job type and `/api/projects/{project_id}/approach/agent-task-plan`.
- The planner seeds/reuses cross-project assets, reads DatasetSnapshot/SemanticCatalog, approved EvaluationSpec, SplitManifest, Assumptions, Questions, benchmark/relational artifacts, ResearchPlan, and library assets.
- It writes an `agent_task_contract` artifact with `agent_task_planning.v1` inputs:
  - dataset/profile context
  - evaluation contract and SplitManifest constraints
  - assumption/question context
  - benchmark and relational context
  - flexible approach candidates
  - controlled research queries
  - Skill/library recommendations
  - reporting requirements
  - artifact expectations
- Added lineage from project/job/dataset/evaluation/split/context artifacts/assets to the contract artifact.
- Extended Job artifact resolver summary for task contracts.
- Added Approach and Experiments UI actions plus AgentTaskContract preview/download tables.

## Validation Plan

- Unit test planner contract construction and schema validation.
- API integration test for contract generation, artifact preview, job artifact resolver, and project artifact listing.
- Run ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.

## Deferred

- Real Codex execution from this contract.
- Network-enabled literature/web search. Contract records queries and policy only.
- Automatic relational feature execution. The planner proposes it with guardrails; implementation remains an AgentTask/FeatureRecipe responsibility.
- Deployment, monitoring, and production database writes.
