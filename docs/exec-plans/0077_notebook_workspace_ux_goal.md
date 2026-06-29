# Notebook Workspace UX Goal

## Goal

Make analysis notebooks discoverable as a first-class project surface. Users should not need to know that notebook artifacts are nested inside Reports or Experiments to find generated marimo notebooks, previews, execution plans, and source downloads.

## Implemented

- Added a dedicated `Notebooks` project tab.
- Added locale-backed tab labels for English and Japanese.
- Added a Notebook Workspace with:
  - data notebook generation,
  - latest-run model diagnostics notebook generation,
  - recommended notebook execution planning,
  - recommended notebook card,
  - notebook coverage metrics,
  - notebook history table,
  - execution plan / AgentTaskContract table,
  - in-product preview panel for HTML, Markdown, JSON, and notebook source artifacts.
- Added Notebook tab references to Focus Guide secondary navigation after approach, experiment, and report stages.

## Decisions

- The existing Reports and Experiments notebook actions remain available for workflow-local context, but the Notebooks tab is the primary discovery surface.
- The dedicated tab intentionally previews static HTML and artifacts rather than launching a live marimo runtime.
- Controlled execution remains plan-only until a runner can enforce workspace isolation, secret boundaries, artifact capture, and human review.

## Deferred

- Live embedded marimo runtime.
- Notebook version comparison.
- Figure-level gallery and cell-level lineage.
- Stage-aware notebook recommendation using ProjectGuidance API.

## Risks

- The new tab adds another navigation item, so future UX work should keep the Guided Journey and Focus Guide opinionated enough that users are not asked to scan every tab.
- Latest-run notebook generation currently uses the first run returned by the API; a richer run picker should follow once projects have many runs.
