# Controlled Agent Workspace & Artifact Ingestion Goal

## Goal

Make agent execution more concrete while keeping the harness in control. AgentRunner implementations should receive a controlled workspace with harness-owned context, and returned AgentResult artifact declarations should be safely ingested into the local artifact store with lineage, evidence, reports, and job output.

## Implemented

- Added schema:
  - `schemas/agent_workspace_manifest.schema.json`
- LocalStubAgentRunner now writes declared output files into the workspace:
  - `reports/agent_task_report.md`
  - `artifacts/agent_result.json`
  - `artifacts/visualization_spec.json`
- `run_idea_agent_task_stub` now materializes a per-job workspace under the artifact root.
- Workspace materialization writes:
  - `.harness/task_contract.json`
  - `.harness/agent_result.schema.json`
  - `.harness/execution_policy.json`
  - `.harness/context/*` copied from AgentContextPack, ExperimentPlan, DataQualityGate, and diagnostics when present
  - `README.md` with safety rules
- Stores an `agent_workspace_manifest` artifact for each runner job.
- Ingests relative `AgentResult.artifacts` paths into the artifact store.
- Rejects empty, absolute, escaping, missing, non-file, or overly large agent artifact paths.
- Adds lineage from Idea and Job to workspace and ingested artifacts.
- Adds lineage from workspace manifest to AgentResult artifact.
- Extends run-agent-task job output with:
  - `workspace_artifact_id`
  - `ingested_artifact_ids`
- Extends Approach UI with workspace manifest preview.
- Extends integration tests to verify workspace manifest and ingested artifact behavior.

## Deferred

- Real CodexCliRunner execution from the UI.
- Runner selection and per-run policy editing.
- Workspace cleanup/retention policy.
- Fine-grained file allowlists by artifact type.
- Cryptographic workspace bundle export.
- Streaming logs and live execution events.

## Risks And Open Decisions

- The workspace path is local and intended for single-Docker MVP use.
- LocalStubAgentRunner proves artifact ingestion shape but does not execute modeling code.
- Future Codex execution must keep secrets and connector credentials out of the workspace and rely on harness-mediated data access.
