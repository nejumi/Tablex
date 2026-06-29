# Controlled Codex Notebook Runner Goal

## Objective

Connect `author_analysis_notebook` contracts to a real controlled Codex execution path instead of stopping at handoff artifacts. Reuse Tablex-owned workspace preparation, readiness review, AgentResult ingestion, artifact registration, Evidence, Reports, and Lineage.

## Implemented Scope

- Added `run_planned_agent_task_codex` job type.
- Added `/api/agent-task-contracts/{artifact_id}/run-codex`.
- Added a `Run Codex CLI` action to the Agent Task Contracts UI table.
- Refactored planned execution so LocalStub and Codex share:
  - contract loading,
  - workspace auto-preparation,
  - readiness review,
  - context summary,
  - AgentResult artifact ingestion,
  - Experiment/Report/Evidence/Lineage creation.
- Strengthened `CodexCliRunner` prompt for `author_analysis_notebook`:
  - read `.harness/task_contract.json`,
  - read `skills/tablex-notebook-quality/SKILL.md` when present,
  - read the referenced `notebook_authoring_brief`,
  - inspect `.harness/context`,
  - use Kaggle Grandmaster-style source cards as craft inspiration only,
  - write requested notebook-specific artifacts and `outputs/result.json`.
- Added safe Codex failure handling for missing CLI binary and timeout.
- Adjusted readiness so missing target/evaluation is a warning for notebook authoring, not a blocker. Modeling tasks still require EvaluationSpec and SplitManifest before runner execution.
- Added tests for:
  - notebook authoring readiness without target/evaluation,
  - LocalStub notebook authoring plan output,
  - Codex prompt and missing-binary failure.

## Safety Boundaries

- Connector credentials are not copied to workspace context.
- Runner contracts still forbid secret access and destructive EvaluationSpec/SplitManifest changes.
- `run-codex` uses the same readiness gate as other planned AgentTask execution.
- Missing evaluation context allows data-understanding notebooks only; metric/lift/model claims remain blocked.

## Deferred Work

- Post-run notebook quality scorer that reviews the returned notebook against the authoring brief and Tablex Skill.
- A browser-visible Notebook Center surface that promotes Codex-authored notebooks ahead of raw artifact shelves.
- Real end-to-end Codex execution smoke on a local project after Codex auth is available.
