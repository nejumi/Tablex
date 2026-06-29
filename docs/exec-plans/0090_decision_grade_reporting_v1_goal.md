# Decision-Grade Reporting v1 Goal

## Goal

Replace smoke-style report surfaces with one in-product decision report that a human can read first. The report must synthesize Tablex-owned artifacts instead of sending users to raw JSON, notebooks, external trackers, or scattered tabs.

## Implemented Scope

- Added `decision_report_bundle.v1` as the structured source of truth for the current report.
- Added `decision_report` Markdown generation from the bundle.
- Added Report, Evidence, and Lineage records for generated decision reports.
- Added:
  - `POST /api/projects/{project_id}/decision-report/generate`
  - `GET /api/projects/{project_id}/decision-report/current`
- The bundle summarizes:
  - Data Review and quality/profile boundaries
  - assumptions and questions
  - EvaluationSpec and SplitManifest
  - experiment metrics, diagnostics, predictions, and model versions when available
  - notebook index and capture coverage
  - AgentRunner result summaries
  - citation audit state
  - benchmark and relational context
  - evidence coverage
  - next actions and safety boundaries
- The Reports tab now opens with Current Decision Report, next actions, report preview, and evidence coverage. Existing report/notebook/visualization shelves remain secondary under supporting details.

## Design Notes

- Complexity is treated as a product defect. The UI should show one report and one next action path before exposing supporting shelves.
- The bundle is deterministic and artifact-backed. It is not a substitute for richer Codex-authored narrative, but it is the harness-owned decision surface that future runner-authored reports should feed.
- Existing `decision_dashboard` remains for compatibility and visualization specs, but v1 report is the primary human reading surface.

## Deferred

- Full natural-language report authoring by Codex from the bundle.
- Rich inline charts directly inside Markdown/HTML report output.
- Dedicated report acceptance/review workflow.
- Automatic refresh after every major artifact creation.
- Strong citation validation for external claims beyond current source citation manifests.
