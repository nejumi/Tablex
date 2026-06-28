# Report & Visualization Workbench Goal

## Goal

Make result communication a first-class part of the harness from the start. Reports, insights, and visualization specs should be generated, stored, previewed, downloaded, and traced inside the product UI without requiring users to inspect the filesystem or external experiment tools.

## Implemented

- Added `Insight` as a metadata DB model.
- Added `InsightRead` API schema.
- Added `tabular_harness.services.reporting` for:
  - deterministic project insight generation
  - `insight_set` artifact creation
  - Evidence records for each generated insight
  - lineage from source assets to insights and from insights to artifacts/evidence
  - VisualizationSpec dashboard generation
- Extended `/api/projects/{project_id}/visualizations/generate` to produce a dashboard set:
  - `metric_cards`
  - `category_bars`
  - `stage_status`
  - `leaderboard_bar`
- Added endpoints:
  - `POST /api/projects/{project_id}/insights/generate`
  - `GET /api/projects/{project_id}/insights`
  - `GET /api/reports/{report_id}/preview`
  - `GET /api/reports/{report_id}/download`
- Extended report drafting so generated reports include Insight and Visualization sections.
- Extended the Reports tab with:
  - Generate Insights action
  - Visualization Dashboard action
  - Insight cards
  - Report preview/download actions
  - generic previews for metric cards, category bars, stage status, and leaderboard bars
- Added unit tests for reporting spec/insight helpers.
- Extended the integration flow for insights, dashboard specs, report preview, and insight artifacts.

## Deferred

- Real charting library integration such as Vega-Lite, Plotly, or ECharts.
- Insight scoring from external citations or live literature/web research.
- Report publishing, version comparison, and export formats beyond Markdown artifact download.
- Human approval workflow for insight/report claims.
- Agent-generated visualization specs beyond the current LocalStubAgentRunner artifact shape.

## Risks And Open Decisions

- VisualizationSpec is still a small internal JSON format. It is enough for MVP previews, but a stable schema or external chart grammar may be needed.
- Insight generation is deterministic and heuristic. It should remain advisory until evidence-weighted generation and user review are implemented.
- Report preview is Markdown-as-text for now. Rich Markdown rendering can be added later, but the current form keeps artifact fidelity obvious.
