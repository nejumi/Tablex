# 0072 Guided Journey History Goal

## Goal

Make saved Guided Journey snapshots useful over time by adding latest-two snapshot comparison, report generation, visualization, and an in-product history surface.

## Implemented Scope

- Added `POST /api/projects/{project_id}/guidance/snapshots/compare`.
- The endpoint compares the latest two saved `guided_journey_snapshot` artifacts.
- It stores:
  - `guided_journey_comparison` JSON artifact
  - `guided_journey_comparison_report` Markdown artifact and `Report` row
  - `visualization_spec` stage-status artifact and `VisualizationSpec` row
  - lineage from both source snapshots to the comparison artifact, report, and visualization
- Added `compare_guided_journey_snapshots` to the job type registry.
- Added a Reports-tab `Guidance History` panel.
- Added a `Compare Journey` action that previews the generated comparison report when complete.
- Extended API integration coverage for comparison and report preview.

## Design Notes

- Comparison uses saved snapshots only. It does not silently compare against transient UI state.
- The comparison records stage status deltas, current-stage changes, focus changes, and source snapshot artifact ids.
- It remains navigation/readiness evidence, not an approach prescription.

## Deferred

- User-selected snapshot pair comparison.
- Timeline charts and richer diff rendering.
- Snapshot notes or labels supplied by users before save.
