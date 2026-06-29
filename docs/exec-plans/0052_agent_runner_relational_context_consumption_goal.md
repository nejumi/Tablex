# Goal 0052: Agent Runner Relational Context Consumption

## Objective

Carry materialized relational workspace context through runner execution, AgentResult ingestion, AgentTaskResults summaries, and UI display. The goal is not to hard-code a modeling recipe; it is to make relational evidence and deferred safety checks visible to Codex, Skill, LocalStub, and future runners while the harness retains EvaluationSpec, SplitManifest, artifacts, lineage, and safety ownership.

## Implemented Scope

- Added `runner_context.py` to summarize `relational_context_artifact` entries from workspace manifests together with contract-level recipe and diagnostics summaries.
- Extended `WorkspaceRef` with optional `context_summary` for safe harness-owned runner context.
- Updated `LocalStubAgentRunner` to include relational context inventory, preview feature counts, scenario recommendations, deferred safety checks, and runner guidance in:
  - `agent_task_report`
  - `feature_recipe`
  - `experiment_metrics`
  - `relational_runner_context_summary`
  - relational context `visualization_spec`
- Added relational summary artifact id and source count to planned LocalStub job output.
- Extended AgentTaskResults API and Experiments UI with a Relational column and preview/download actions for the relational context summary.
- Added Home Credit-like integration coverage for prepare workspace, run LocalStub, ingest relational context artifacts, and show AgentTaskResults relational summaries.
- Marked relational context as advisory, not prescriptive: runners may reject, revise, replace, or request more research around the suggested approaches while still respecting harness-owned evaluation, safety, artifact, and lineage constraints.

## Deferred Scope

- Real Codex runner execution that reads `.harness/context/relational/` and writes implementation patches.
- SplitManifest-aware relational feature fitting and model training.
- Rich UI visualization dedicated to scenario comparison and deferred check drill-down.

## Risks And Open Decisions

- LocalStub only proves context propagation and artifact ingestion. It deliberately does not validate model lift or execute relational feature generation.
- Future runners must not read secrets or connector credentials, and must continue registering important outputs as artifacts.
- Relational preview CSVs remain planning evidence until a runner or Skill implements train-fold-safe feature construction.
- The product must avoid becoming a closed set of predefined recipes. Structured context should make runner decisions auditable, not prevent Codex from using new project-specific evidence, Skills, or current research.
