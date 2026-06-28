# 0030 Report Visualization Surface Goal

## Goal

Render stored `visualization_spec` records as useful in-product visuals instead of relying on raw JSON preview. Reports and decision views should stay understandable inside Tablex.

## Context Reviewed

- `schemas/visualization_spec.schema.json`
- `apps/backend/tabular_harness/services/reporting.py`
- `apps/backend/tabular_harness/services/diagnostics.py`
- `apps/backend/tabular_harness/services/experiment_lifecycle.py`
- `apps/backend/tabular_harness/agent/runners.py`
- `apps/frontend/src/main.tsx`

## Implemented Scope

- Kept the existing portable `visualization_spec.v1` contract.
- Extended the React renderer to use `encoding.x`, `encoding.y`, and `encoding.color` for generic bar charts.
- Preserved existing renderers for `metric_cards`, `category_bars`, and `stage_status`.
- Added explicit `artifact_checklist` rendering for agent task output contracts.
- Added fallback table rendering for unknown visualization specs with data rows.
- Improved compact bar labels with secondary detail from color/group encodings.

## Deferred Scope

- Full charting library integration.
- Vega-Lite/Plotly compatibility.
- Rich interactions such as filtering, brushing, and drill-down.
- Backend report-to-visualization linkage beyond current artifact/source ids.

## Validation Plan

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- Docker build and `/healthz` smoke.
