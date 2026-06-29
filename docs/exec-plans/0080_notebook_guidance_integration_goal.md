# Notebook Guidance Integration Goal

## Goal

Make notebook evidence part of the guided project journey instead of a side surface. After experiments produce evidence, the workbench should steer users toward notebook generation and safe capture before final reporting.

## Implemented

- Added notebook-related supporting counts to ProjectGuidance:
  - `analysis_notebooks`,
  - `notebook_execution_plans`,
  - `notebook_execution_captures`.
- Added state fields for latest successful run and latest analysis notebook.
- Added `notebooks` recommended focus when:
  - successful runs exist but no analysis notebook exists,
  - analysis notebooks exist but no execution capture exists.
- Added endpoint actions for:
  - generating model diagnostics notebooks from the latest successful run,
  - capturing execution evidence for the latest notebook.
- Added an explicit `Notebooks` Guided Journey stage between Experiments and Reports.
- Updated frontend locale labels and journey-stage mapping for English/Japanese.
- Updated journey rail layout from seven to eight stages.
- Added API integration assertions for Notebooks stage and notebook supporting counts.

## Decisions

- Reports should not be the immediate next stage after experiments when notebook evidence is missing. Notebook previews and safe capture reduce cognitive load by collecting diagnostics, figures, and runner evidence before report review.
- Full marimo execution remains deferred; the journey stage is satisfied by safe static capture evidence for now.

## Deferred

- Rich ProjectGuidance summaries of specific missing notebook artifact types.
- Guidance actions for selecting a run when multiple successful runs exist.
- Decision Dashboard notebook evidence section.
- Full executed-cell notebook runner readiness gates.

## Risks

- The current guidance uses the latest successful run/latest notebook. A picker or stage-specific selection policy will be needed for projects with many parallel runs.
