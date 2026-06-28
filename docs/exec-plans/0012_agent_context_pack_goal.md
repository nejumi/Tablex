# Agent Context Pack Goal

## Goal

Prepare future Codex, Skill, and controlled research runners without letting the runner become the product owner. The harness should materialize the exact execution context as an artifact before agent execution: data/evaluation references, SplitManifest context, artifact refs, locked library asset references, research policy, safety controls, and required output contract.

## Implemented

- Added `schemas/agent_context_pack.schema.json`.
- Added `tabular_harness.services.agent_context`.
- Added `prepare_agent_context` job type.
- Added endpoints:
  - `POST /api/ideas/{idea_id}/prepare-agent-context`
  - `GET /api/ideas/{idea_id}/context-packs`
- Context packs include:
  - project and Idea metadata
  - validated AgentTaskContract
  - allowed research modes from the contract
  - controlled web/literature citation requirements
  - secret and connector credential restrictions
  - feature generation guardrails
  - DatasetSnapshot reference
  - EvaluationSpec and SplitManifest reference
  - compact artifact preview/download refs
  - locked cross-project AssetReferences
  - required output contract
- Registered context packs as `agent_context_pack` artifacts.
- Added lineage from Idea, Job, DatasetSnapshot, EvaluationSpec, SplitManifest, and AssetReference records into the context pack artifact.
- Added Approach tab actions to prepare and preview context packs before running a stub task.
- Extended integration tests for context pack generation, preview, and artifact registration.

## Deferred

- Real Codex CLI execution against the context pack.
- Skill execution and live web/literature search.
- Harness-mediated dataset materialization inside a temporary workspace.
- Approval workflow for enabling external network access.
- Context pack diffing and immutable promotion statuses.

## Risks And Open Decisions

- Context packs currently include artifact references and compact metadata, not copied data. A future runner workspace materializer should decide which artifacts can be safely copied.
- Research policy is represented as text fields and contract flags. A stricter policy engine may be needed before real network access is enabled.
- Context pack generation is synchronous for MVP. Long-running workspace preparation should move to the worker layer later.
