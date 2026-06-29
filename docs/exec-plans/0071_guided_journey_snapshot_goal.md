# 0071 Guided Journey Snapshot Goal

## Goal

Make Guided Journey state persistable as first-class in-product evidence. Users should be able to save the current harness guidance state as artifacts and reports without relying on ephemeral UI or external dashboards.

## Implemented Scope

- Added `POST /api/projects/{project_id}/guidance/snapshot`.
- The endpoint runs synchronously as `save_guided_journey_snapshot`.
- It stores:
  - `guided_journey_snapshot` JSON artifact
  - `guided_journey_report` Markdown artifact and `Report` row
  - `visualization_spec` artifact and `VisualizationSpec` row using `stage_status`
  - Lineage from project to snapshot and from snapshot to report/visualization
- Added a `Save snapshot` action to the Guided Journey rail.
- Extended API integration coverage for snapshot persistence and report preview.

## Design Notes

- The snapshot records the same `project_guidance.v1` payload the UI uses, plus status counts, current stage, recommended focus, and a persistence policy.
- The report explicitly states that the Approach stage is handoff readiness, not a fixed modeling recipe.
- Network and connector credential policy remains disabled/forbidden because this is a harness-owned summarization step.

## Deferred

- User naming/version notes for snapshots.
- Direct “open saved report” toast in the UI after save.
- Diffing two journey snapshots over time.
