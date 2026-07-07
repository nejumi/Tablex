# 0121 Workstream I3 Related Outputs And Assets Evidence

Date: 2026-07-08

## Scope

Implemented the first I3 user-facing asset-discovery slice:

- Added a shared `RelatedOutputsDrawer` component.
- Reused the drawer from Research Plan node expansion for attached artifacts.
- Reused the same drawer from Leaderboard rows for notebooks, diagnostic artifacts, and pipeline bundles.
- Changed the Assets inventory from a primary/supporting split into a visible all-output inventory with fixed asset-type categories, search, and Research Plan node filtering.
- Kept artifact classification on explicit structured fields (`asset_type`, `research_plan_node_id`, attached Research Plan artifact links); no natural-language matching was added.
- Added one-hop artifact lineage metadata to artifact/report preview responses.
- Added a shared lineage panel to preview surfaces so users can see what an output was built from and where it is used.

## Verification

Frontend build:

```bash
cd apps/frontend && npm run build
```

Result:

```text
✓ built in 336ms
```

Targeted component lint:

```bash
cd apps/frontend && ./node_modules/.bin/eslint src/components/LeaderboardTab.tsx src/components/ResearchPlanTimeline.tsx src/components/RelatedOutputsDrawer.tsx src/components/ArtifactLineagePanel.tsx src/components/ArtifactPreview.tsx
```

Result: passed with no output.

Backend preview lineage test:

```bash
.venv/bin/python -m py_compile apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/schemas/api.py
.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_artifact_preview_includes_one_hop_lineage -q
.venv/bin/ruff check apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/schemas/api.py apps/backend/tests/test_api_flow.py
```

Result:

```text
1 passed, 1 warning in 5.10s
All checks passed!
```

Full backend regression after preview schema extension:

```bash
.venv/bin/python -m pytest apps/backend/tests -q
```

Result:

```text
447 passed, 6 warnings in 149.12s
```

Full frontend lint was also checked:

```bash
cd apps/frontend && npm run lint
```

Result: failed on pre-existing unused imports/functions in `App.tsx`, `AgentActivityRail.tsx`, and `RawAgentStream.tsx` (`no-control-regex`). The I3 component files above pass targeted lint.
