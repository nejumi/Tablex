# GM-Style Notebook Authoring Brief Goal

## Objective

Move notebook quality work away from static smoke-test scaffolds and toward a source-backed Codex authoring handoff. Tablex should preserve harness-owned safety, lineage, and evaluation boundaries, while giving the runner enough notebook craft context to write or revise the analysis on the fly.

## Read Context

- `docs/dev.md`
- `README.md`
- `skills/tablex-notebook-quality/SKILL.md`
- `apps/backend/tabular_harness/services/analysis_notebooks.py`
- `apps/backend/tabular_harness/services/eda_review.py`
- `apps/backend/tabular_harness/services/agent_chat.py`
- `apps/backend/tabular_harness/services/agent_task_planner.py`

## Source-Backed Direction

The runner should use public Kaggle Grandmaster-style notebook craft as inspiration, not as copied content or a fixed section order. Initial source cards point to:

- Kaggle blog interview with Heads or Tails as a Kernels Grandmaster.
- Heads or Tails Hidden Gems competition design notes.
- Public Heads or Tails Kaggle code profile as a style-pattern reference.

These references are encoded as `source_inspirations` inside a `notebook_authoring_brief` artifact. The brief also carries principles, sample analytical moves, current project artifacts, and a Codex contract.

## Implemented Scope

- Added `tabular_harness.services.notebook_authoring`.
- Added `/api/projects/{project_id}/notebook-authoring/brief`.
- Added `create_notebook_authoring_brief` job type.
- Deprecated: natural-language Agent Chat detection was removed. Notebook authoring is started by explicit controls or future schema-validated agent proposals that create:
  - a `notebook_authoring_brief`,
  - a `notebook_authoring_report`,
  - an `author_analysis_notebook` AgentTaskContract.
- `author_analysis_notebook` AgentTaskContracts request notebook-specific outputs instead of generic modeling reports:
  - marimo notebook source,
  - notebook reader report,
  - figure manifest,
  - evidence bundle,
  - quality review,
  - citation audit.
- LocalStub execution now emits a `notebook_authoring_plan` artifact for this task type, so the handoff can be inspected before a real Codex runner writes the final notebook.
- AgentTaskContracts now include latest `notebook_authoring_brief`, EDA review, and EDA review HTML context when present.
- The Tablex notebook quality Skill now states that the brief is craft context for dynamic Codex authoring, not a deterministic template.
- API tests verify that a Japanese high-quality notebook request produces the authoring brief and contract inputs.

## Quality Bar

- Notebook generation must not be a fixed recipe.
- Codex must read the current brief and linked Tablex artifacts before writing.
- Public sources are craft references only; do not copy notebook prose, code, or structure.
- Every claim in the generated notebook should be backed by Tablex artifacts, figures, metrics, or explicit assumptions.
- EvaluationSpec, SplitManifest, secrets, and connector credentials remain harness-controlled.

## Deferred Work

- Actual Codex CLI/app-server execution of `author_analysis_notebook`.
- A controlled executed marimo runner that captures real Plotly/matplotlib outputs from Codex-authored notebooks.
- More source-card ingestion from a curated public notebook-quality corpus.
- UI surface for inspecting the `notebook_authoring_brief` directly before execution.
- Automated notebook quality review scoring after Codex returns the notebook.

## Risks

- Without real Codex execution, this goal improves the handoff but does not yet produce the final GM-quality notebook artifact.
- Public Kaggle notebook inspiration must stay within copyright and attribution constraints.
- The quality bar can regress if future runner code ignores the brief and falls back to static notebook generation.
