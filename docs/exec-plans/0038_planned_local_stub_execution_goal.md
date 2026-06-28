# 0038 Planned LocalStub Agent Execution Goal

## Goal

Allow a planner-generated `agent_task_contract` artifact to be executed through a controlled LocalStubAgentRunner path without going through an Idea record. Execution must remain harness-owned: the API creates a Job, verifies readiness, uses a prepared workspace, validates AgentResult shape, ingests declared artifacts, and records Report, Evidence, and Lineage.

## Implementation

- Added `services/planned_agent_execution.py`.
- Added `run_planned_agent_task_stub` job type.
- Added `POST /api/agent-task-contracts/{artifact_id}/run-local-stub`.
- The endpoint:
  - accepts only project-scoped `agent_task_contract` artifacts
  - creates a policy-scoped job with network disabled and no credential materialization
  - prepares a workspace automatically when one does not already exist
  - regenerates readiness review before execution
  - refuses execution when readiness has blockers
  - runs LocalStubAgentRunner against the controlled workspace
  - ingests declared AgentResult artifacts from workspace-relative paths
  - creates Report and Evidence rows
  - records lineage from job, contract, workspace, readiness review, ingested artifacts, report, and evidence
- Extended the frontend AgentTaskContracts table with a Run Stub action.
- Extended job output summaries with runner status, evidence id, and human-review flag.

## Validation Plan

- API flow test for successful planned stub execution after contract planning, workspace preparation, and readiness review.
- API flow test for blocked-readiness rejection before execution.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for the safety gate.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a project and planned AgentTaskContract in the container, then verified `run-local-stub` returns HTTP 400 when readiness has blockers.

## Deferred

- Real Codex execution or external research execution.
- Human approval workflow for ready-with-warnings tasks.
- Streaming runner logs, patch review, and cancellable long-running execution.
- Rich report visualization beyond the currently ingested visualization spec artifact.
