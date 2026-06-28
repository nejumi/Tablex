# 0036 Planned Agent Workspace Handoff Goal

## Goal

Materialize planner-generated `agent_task_contract` artifacts into controlled runner workspaces without requiring an Idea record or starting Codex execution.

## Implementation

- Added `services/planned_agent_workspace.py`.
- Added `prepare_planned_agent_workspace` job type.
- Added `POST /api/agent-task-contracts/{artifact_id}/prepare-workspace`.
- The service validates the contract artifact, creates a workspace under the artifact root, and writes:
  - `.harness/task_contract.json`
  - `.harness/agent_result.schema.json`
  - `.harness/execution_policy.json`
  - copied context artifacts from `available_context_artifacts`
  - copied library asset artifacts from recommended `AssetVersion` records
  - `README.md`
- Stores an `agent_workspace_manifest` artifact with source counts, skipped sources, safety policy, files, and runner handoff status.
- Adds lineage from the job, source contract artifact, context artifacts, and asset versions to the workspace manifest.
- Adds Approach UI action to prepare a workspace from AgentTaskContracts and preview the manifest.

## Validation Plan

- Unit tests for context target path safety and filename sanitization.
- API integration test for contract planning, workspace preparation, manifest download, and job artifact resolver output.
- Full ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.

## Deferred

- Running real Codex or MCP agents from the workspace.
- Network-enabled research execution.
- Streaming runner logs, patch review, and approval checkpoints.
- Workspace garbage collection and quota management.
