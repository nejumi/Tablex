# 0043 Agent Task Results Workbench Goal

## Goal

Make AgentTask execution results self-contained in the workbench UI. Users should be able to inspect a completed planned or Idea-backed runner task from the AgentTask perspective, including reports, metrics, ExperimentRun registration, citation audit, Evidence, workspace/readiness artifacts, and downloads without reading raw job JSON or relying on an external dashboard.

## Implementation

- Added `services/agent_task_results.py`.
- Added `GET /api/projects/{project_id}/agent-task-results`.
- The endpoint summarizes `run_planned_agent_task_stub` and `run_agent_task` jobs with:
  - source reference: AgentTaskContract or Idea
  - agent status, final message, readiness, human review flag
  - ExperimentRun id, status, split/evaluation refs, and metrics
  - agent report and citation audit report refs
  - agent result Evidence and citation audit Evidence refs
  - source citation manifest, citation audit report, feature recipe, metrics, workspace, readiness, and visualization artifacts
  - citation source/citation counts and network/credential audit flags
- Added `AgentTaskResult` frontend types and project refresh loading.
- Added an `Agent Task Results` panel to the Experiments tab with preview/download actions for agent reports, citation audit reports, and source citation manifests.

## Validation Plan

- Extend the API flow test to assert planned and Idea-backed LocalStub runs appear in `agent-task-results`.
- Backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for the endpoint and citation report preview.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a fixture-backed project in the container, generated a Research Source Pack and AgentTaskContract, ran LocalStub, verified `agent-task-results`, and previewed the citation audit report from the returned summary.

## Deferred

- Dedicated AgentTask detail page.
- Filtering by Idea, contract, runner implementation, and citation risk.
- Rich visual comparison of agent task outputs beyond the current table and report preview.
- Real Codex execution result grouping once a non-stub runner is enabled.
