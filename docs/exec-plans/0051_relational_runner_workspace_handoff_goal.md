# Goal 0051: Relational Runner Workspace Handoff

## Objective

Make the latest relational planning, recipe, preview, diagnostics, and report artifacts available inside controlled AgentRunner workspaces. The harness still owns artifact storage, lineage, safety policy, evaluation constraints, and runner gating; Codex or LocalStub receives inspectable context, not credentials or uncontrolled data access.

## Implemented Scope

- Added relational preview/profile/report artifacts to `AgentTaskContract.inputs.available_context_artifacts`.
- Materialized relational context artifacts under `.harness/context/relational/` instead of the generic context artifact directory.
- Added `relational_context_artifact` entries to `agent_workspace_manifest.materialized_sources` with role, asset type, artifact id, context path, content hash, and size bytes.
- Added `materialized_relational_context_count` to workspace artifact metadata and job output.
- Added an AgentTask readiness check that warns when relational context exists but no prepared workspace is available, and passes when relational context is materialized.
- Extended the Home Credit-like tiny integration flow to verify relational workspace files and readiness review state.

## Deferred Scope

- Real Codex execution from the prepared relational context.
- Train-fold-fitted relational feature generation for model runs.
- Point-in-time-safe joins across arbitrary production schemas.
- UI-specific relational workspace file browser grouping beyond existing manifest preview/download.

## Risks And Open Decisions

- Relational materialization copies bounded artifact files only; it is a handoff context, not a feature-generation runtime.
- Future runners must keep using harness-owned SplitManifest, EvaluationSpec, safety constraints, and artifact registration rather than creating untracked outputs.
- Large supporting tables remain excluded from runner context unless the harness deliberately exposes sampled or derived artifacts.
