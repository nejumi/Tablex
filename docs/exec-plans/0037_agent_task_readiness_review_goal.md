# 0037 Agent Task Readiness Review Goal

## Goal

Add an in-product readiness review for planned AgentTasks so users can understand pre-run blockers, warnings, and next actions without reading raw contract/workspace JSON.

## Implementation

- Added `services/agent_task_readiness.py`.
- Added `review_agent_task_readiness` job type.
- Added `POST /api/agent-task-contracts/{artifact_id}/readiness-review`.
- The review reads an `agent_task_contract` artifact and the latest matching `agent_workspace_manifest`, then checks:
  - contract schema validity
  - target context
  - EvaluationSpec and SplitManifest availability
  - required outputs
  - secret/credential/SplitManifest safety policy
  - high-risk assumptions and blocking questions
  - context artifacts
  - library asset recommendations/materialization
  - workspace manifest readiness
  - reporting and artifact expectations
- Persists:
  - `agent_task_readiness_review` JSON artifact
  - `agent_task_readiness_report` Markdown artifact and Report record
  - `visualization_spec` artifact/record using `stage_status`
- Adds lineage from job, contract, workspace, review, report, and visualization.
- Adds an Approach UI action to trigger readiness review and preview the report.

## Validation Plan

- Unit test for blocker generation when evaluation context is missing.
- API flow test covering contract planning, workspace preparation, readiness review, report preview, and artifact inventory.
- Full ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.

## Deferred

- Real runner execution gates based on readiness status.
- Human approval workflow around readiness blockers.
- Streaming logs and patch review for Codex execution.
- Richer visualization components beyond the existing `stage_status` table.
