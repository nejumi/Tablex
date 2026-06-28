# Idea Agent Task Stub Goal

## Goal

Connect Approach Ideas to an execution-ready AgentTask flow without enabling unrestricted Codex execution yet. The harness should be able to take an Idea's AgentTaskContract, run it through a safe LocalStubAgentRunner, validate AgentResult shape, and persist every important output as artifacts with evidence and lineage.

## Implemented Scope

- Extended `LocalStubAgentRunner` to generate a schema-validated AgentResult.
- Added `agent_tasks` service for Idea-backed AgentTask execution.
- Added `POST /api/ideas/{idea_id}/run-agent-task`.
- Stored LocalStub outputs as artifacts:
  - `agent_task_report`
  - `agent_result`
  - `visualization_spec`
- Created `Report` records for agent task reports.
- Created `Evidence` records from persisted AgentResult artifacts.
- Added lineage from Idea and Job to generated artifacts.
- Updated Idea status to `agent_stub_completed` after successful stub execution.
- Added Run Stub Task action to the Approach tab.
- Extended integration tests for Idea execution, AgentResult artifact creation, Evidence, Report, and updated Idea status.

## Safety Boundary

The runner does not execute Codex, run generated code, or perform web research. It validates contracts and materializes the expected result shape so the product can own the UI, DB, artifacts, reports, and lineage before a real runner is enabled.

## Deferred Scope

- Real CodexCliRunner execution from UI.
- Approval gates before non-stub AgentRunner execution.
- Workspace file capture and patch diff ingestion.
- Citation ingestion from web/literature research.
- Skill selection and version locking.
- Retry, cancellation, and async worker execution.

## Risks And Open Decisions

- Stub execution creates useful product state but not model improvements. UI labels must continue to make that distinction clear.
- AgentResult artifacts are trusted only because they are produced by the local stub. Real runner outputs will need stricter validation, artifact sandboxing, and review gates.
