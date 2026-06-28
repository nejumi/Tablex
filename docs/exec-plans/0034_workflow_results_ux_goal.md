# 0034 Workflow Results UX Goal

## Goal

Make long-running workflow jobs understandable from inside the product UI. Users should not need to inspect raw JSON output or local artifact folders to know what a workflow produced.

## Implementation

- Added `GET /api/jobs/{job_id}/artifacts`.
- The resolver extracts `artifact_id` and `artifact_ids` fields from nested job output and returns:
  - the Job payload
  - key benchmark/run/model/metric summary fields
  - ordered Artifact records
  - missing artifact ids, if any
- Jobs UI can inspect job artifacts, preview text/JSON/Markdown/CSV artifacts, and download artifacts.
- Data UI now surfaces recent `run_public_benchmark_workflow` results with run/model/metric/report/scenario preview actions.

## Validation

- Extended the public workflow integration test to assert resolver summary, artifact count, missing ids, and decision report artifacts.
- Frontend build/type checks cover the new UI types and panels.

## Deferred

- Realtime streaming job progress remains future work.
- Large artifact graph visualization remains in the existing Lineage tab scope.
- Resolver is read-only and does not change JobRead shape.
