# Notebook Execution Capture Goal

## Goal

Add the first harness-owned execution capture path for generated analysis notebooks. The product should persist runner evidence artifacts and UI previews without exposing secrets, connector credentials, external dashboards, or uncontrolled local files.

## Implemented

- Added `capture_notebook_execution` job type.
- Added `POST /api/analysis-notebooks/{artifact_id}/execution-capture`.
- Added safe static capture for Tablex-generated marimo notebooks:
  - validates source markers,
  - runs `python -I -m py_compile` in a temporary workspace,
  - does not execute notebook cells,
  - does not import marimo or user code,
  - does not materialize secrets or connector credentials.
- Added execution capture artifacts:
  - `notebook_execution_manifest`,
  - `notebook_execution_report`,
  - `notebook_execution_html`,
  - `notebook_figure_manifest`,
  - `notebook_execution_source`.
- Added lineage from source notebooks, plans, contracts, and linked notebook artifacts into capture outputs.
- Added Notebooks UI actions for capture and surfaced capture artifacts under Execution Evidence.
- Added integration coverage for manifest safety policy, static compile status, HTML preview, and figure manifest.

## Decisions

- This milestone intentionally does not run marimo cells. It is a controlled artifact-capture shape and syntax-readiness check for generated notebooks.
- The capture endpoint auto-creates a notebook execution plan/contract if one does not already exist, so the workflow remains question-driven but not blocked by missing plan clicks.
- Figure output is represented as planned slots until a restricted runtime can render and persist figure/table artifacts.

## Deferred

- Server-side marimo runtime execution.
- HTML export from executed marimo cells.
- Figure/table artifact capture with cell-level lineage.
- Approval UX for full notebook execution.
- Runtime dependency isolation beyond isolated Python compile.

## Risks

- Static compile confirms syntax only; it does not prove notebook cell runtime behavior.
- Future full execution must keep the same boundary: no secrets, no connector credentials, no external dashboards as required evidence, and no EvaluationSpec/SplitManifest mutation.
