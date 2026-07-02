# Grandmaster EDA Skill Plan

## Purpose

Tablex needs deeper data understanding without turning the harness into a brittle rule engine. This work adds an initial cross-project Skill that gives Codex high-quality EDA, hypothesis extraction, multi-table exploration, and marimo reporting expectations while preserving Codex autonomy.

## Sources Reviewed

- Kaggle: EDA for tabular data advanced technique collections.
- Kaggle: Home Credit Default Risk extensive EDA notebooks.
- NVIDIA Technical Blog: Kaggle Grandmasters playbook for tabular data.
- NVIDIA Technical Blog: Kaggle Grandmasters strategy interview.
- marimo documentation and product pages for reactive, Git-friendly, executable Python notebooks and HTML export.

## Implementation

- Add `skills/tablex-grandmaster-eda/SKILL.md`.
- Add reference material for EDA patterns and Tablex marimo output contracts.
- Seed `tablex_grandmaster_eda` as an organization-scope Skill in the Cross-project Asset Library.
- Include the Skill in AgentTaskContract context files for notebook and autonomous tasks.

## Design Decisions

- The Skill provides craft standards and expected artifacts, not deterministic EDA logic.
- Codex should infer objectives, choose analyses, and generate notebooks from evidence.
- Tablex should preserve outputs as assets: hypotheses, visual story cards, evidence bundles, notebooks, and next-analysis queues.
- External notebooks are treated as inspiration and citations, not copied content.

## Deferred

- Automatically attaching this Skill to every existing project in the UI.
- Forward-testing with a long-running Codex EDA session on the full Home Credit benchmark.
- Rich UI rendering for all new story-card fields beyond current asset views.
