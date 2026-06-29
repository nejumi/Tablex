# Focused Evidence Workspace Goal

## Goal

Reduce first-view cognitive load in the Data and Notebooks tabs while preserving the full harness evidence model. Users should see what matters now, why it matters, and the next action before seeing raw tables, benchmark catalogs, or notebook shelves.

## Context Read

- `apps/frontend/src/main.tsx`
- `apps/frontend/src/styles.css`
- `docs/dev.md`
- `docs/exec-plans/0099_streamlined_data_workspace_goal.md`
- `docs/exec-plans/0100_agent_activity_ephemeral_overlay_goal.md`

## Implementation

- Added a Data Evidence focus surface after upload/import controls.
  - Shows dataset readiness, profile mode, quality status, relational evidence, rows, columns, profile count, quality artifact count, and one next action.
  - Keeps target optional and does not force target selection before data understanding.
- Collapsed detailed Data shelves.
  - Benchmark collection plans, benchmark catalog, public workflows, evidence packs, dataset snapshots, profile readiness, and source artifacts are now in a supporting shelf.
  - Benchmark scenarios, workflow results, quality gates, and quality previews are in a second supporting shelf.
- Kept Relational Map as a primary surface.
  - ER-style relationship evidence remains visible before raw JSON or tabular shelves.
- Added a Notebook Focus surface before Analysis Story.
  - Shows recommended reading focus, evidence capture state, EDA review state, figure count, notebook count, captured count, run count, and one action.
  - Empty model diagnostics are explicitly routed back to Data Understanding when they lack useful evidence.
- Added responsive styling so focus surfaces collapse cleanly on narrow screens.

## Product Rule

The workbench should not make users parse the artifact system before showing the next meaningful decision. Raw tables, catalogs, and lineage are important, but they belong behind progressive disclosure unless they are the current task.

## Validation

- `npm run lint --prefix apps/frontend`
- `npm run build --prefix apps/frontend`

## Deferred

- Agent Chat should be able to open the exact focused surface and scroll to the relevant shelf.
- The Notebook Focus action should eventually call a richer analysis-guide endpoint rather than only preview/run actions.
- Data Focus should incorporate richer quality and leakage summaries once the quality bundle exposes stable typed fields.
