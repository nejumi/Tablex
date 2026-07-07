# 0121 I6 Browser E2E And Evidence Grades

Date: 2026-07-08

## Scope

Workstream I6 adds browser-level evidence for the product path that unit and API tests cannot cover:

- Primary-free upload is accepted without selecting a primary table.
- Chat can open a linked native marimo notebook directly.
- Leaderboard rows show human-readable model description and can open the run-linked model notebook.
- Pipeline bundle download returns a zip for the leaderboard run.
- A pilot prediction batch can be created from the registered pipeline.
- Pilot scoring is visible from the Leaderboard surface.

The browser smoke uses a deterministic tiny fixture and temp data directory. It does not touch the local development DB.

## Implemented

- Added `apps/frontend/e2e/seed_golden_slice.py`.
  - Seeds a single project with first-class Tablex records: `DatasetSnapshot`, `ExperimentRun`, `ModelVersion`, native marimo `analysis_notebook`, `prediction_pipeline`, diagnostics artifacts, pilot deployment, prediction/outcome batches, scoring report, validation audit, and an artifact-backed Chat action.
  - The notebook is native marimo Python source and uses Plotly figures; no static HTML fallback is generated.
- Added `apps/frontend/e2e/golden_slice_smoke.mjs`.
  - Starts an isolated FastAPI backend, Vite frontend, local worker, and native marimo.
  - Uploads two CSV files without `primary_filename`, waits for ingest, asserts the project primary remains unset after upload, then seeds the rest of the slice.
  - Opens the notebook from Chat and from the Leaderboard row.
  - Downloads the pipeline bundle and verifies zip content.
  - Creates a pilot prediction batch through the public API and verifies pilot scoring display in the browser.
- Added `playwright` as a frontend dev dependency for deterministic local browser automation.
- Reduced the floating Agent Activity rail's finished-work TTL from 24 hours to 8 seconds.
  - Browser evidence exposed that stale terminal Activity cards could cover Leaderboard row actions.
  - Durable job/activity history remains in persisted surfaces; the floating rail is now a short live/completion surface.

## Browser Evidence

Command:

```bash
node apps/frontend/e2e/golden_slice_smoke.mjs
```

Result:

```text
exit code 0
project_id: p_887bbe7672d7
upload_primary_dataset_snapshot_id_after_upload: null
run_id: run_e2e_golden_slice
prediction_job_id: job_bb3d4a6fc67d
```

Artifacts:

- `output/playwright/0121_i6_golden_slice_result.json`
- `output/playwright/0121_i6_notebook_from_chat.png`
- `output/playwright/0121_i6_notebook_from_leaderboard.png`
- `output/playwright/0121_i6_leaderboard_pilot.png`

## Live Full Auto Evidence

Command:

```bash
node apps/frontend/e2e/live_full_auto_research_pilot_smoke.mjs
```

Result:

```text
status: passed_recovered_from_live_run_db
project_id: p_8d5d818b1cd4
agent_session_id: ags_6e37f258b692
research_findings_report: art_f9ba1b08b1ca
research_markdown_report: art_c10f02dc13c7
pilot_scoring_report: art_0fe54db0889e
validation_scheme_audit: art_5ecbb0403a27
validation audit verdict: partially_confirmed
```

Evidence artifact:

- `output/live/0121_i6_live_full_auto_research_pilot_passed_recovered_20260707T185948Z.json`

Notes:

- The live run used a real Codex main session with network-enabled workspace sandbox and `web_search="live"`.
- The research report registered 4 sources and 5 findings with a linked rich Markdown report.
- The pilot loop registered prediction, outcome scoring, and a Codex-authored validation audit linked to the scoring report.
- The first live smoke command completed the product path but the smoke assertion initially expected only `scoring_report_artifact_ids`; the registered audit payload uses `pilot_scoring_report_artifact_id`. The smoke now accepts both current and legacy shapes.

## Evidence Grades

Grades used for Tablex audit evidence:

- `U`: unit or focused backend/frontend test.
- `A`: API smoke or live API check without browser rendering.
- `B`: browser-level proof with Playwright or equivalent real browser automation.
- `L`: live Full Auto / real Codex session evidence.

| Claim | Grade | Evidence |
| --- | --- | --- |
| I1 native marimo session reliability has backend coverage for source hash, reuse, restart, LRU, prewarm, and runtime failure visibility. | U | `docs/evidence/0121_i1_marimo_reliability.md` |
| Native marimo opens from Chat and Leaderboard browser paths without static HTML fallback in the golden slice. | B | `output/playwright/0121_i6_notebook_from_chat.png`, `output/playwright/0121_i6_notebook_from_leaderboard.png` |
| I2 storage usage and dry-run GC controls are implemented with protected references. | U/A | `docs/evidence/0121_i2_storage_controls.md` |
| I3 related outputs are available from Research Plan / Leaderboard / Assets and artifact previews include one-hop lineage. | U/B | `docs/evidence/0121_i3_related_outputs_and_assets.md`, `output/playwright/0121_i6_notebook_from_leaderboard.png` |
| I4 expected deliverables ledger is non-blocking and exposes missing model notebooks / pipeline bundles as pending outputs. | U | `docs/evidence/0121_i4_deliverable_expectations.md` |
| I5 repeated Chat/Activity notices are compacted and completed plans wait for user input instead of continuing empty checks. | U | `docs/evidence/0121_i5_chat_activity_quiet.md` |
| Floating Activity no longer keeps finished upload/import/prediction cards over the workspace for a day. | B | Browser smoke initially failed due `Agent Activity` intercepting the Leaderboard notebook button; final smoke passed after terminal floating TTL reduction. |
| Primary-free upload is accepted and does not force primary/target before data understanding. | U/A/B | `docs/evidence/0120_verification.md`, `docs/evidence/0120_h5_primary_free_preflight_20260707T170226.json`, `output/playwright/0121_i6_golden_slice_result.json` |
| Leaderboard row shows model description and exposes pipeline bundle download. | U/B | `docs/evidence/0121_i4_deliverable_expectations.md`, `output/playwright/0121_i6_leaderboard_pilot.png`, `output/playwright/0121_i6_golden_slice_result.json` |
| Pilot prediction batch and pilot scoring path are visible in-product. | U/B | `output/playwright/0121_i6_leaderboard_pilot.png`, `output/playwright/0121_i6_golden_slice_result.json` |
| Live Full Auto can proceed from primary-free upload into Codex-authored task-shape work. | L | `docs/evidence/0120_h5_live_e2e_after_artifact_primary_fix_20260707T185042.json`, `docs/evidence/0120_h5_resume_after_primary_p_244186adcdec_20260707T185645.json` |
| Live Full Auto has a clean source-backed research findings plus pilot loop recording after I1-I6. | L | `output/live/0121_i6_live_full_auto_research_pilot_passed_recovered_20260707T185948Z.json` |

## Verification

Static checks:

```bash
.venv/bin/python -m py_compile apps/frontend/e2e/seed_golden_slice.py
.venv/bin/ruff check apps/frontend/e2e/seed_golden_slice.py
node --check apps/frontend/e2e/golden_slice_smoke.mjs
(cd apps/frontend && npm exec eslint -- src/components/AgentActivityRail.tsx e2e/golden_slice_smoke.mjs --max-warnings=0)
npm --prefix apps/frontend run build
```

Result: passed.

Browser smoke:

```bash
node apps/frontend/e2e/golden_slice_smoke.mjs
```

Result: passed with exit code 0.

Live smoke:

```bash
node apps/frontend/e2e/live_full_auto_research_pilot_smoke.mjs
```

Result: live run evidence recorded with grade `L`.

## Follow-Up For Next Audit

- Keep the deterministic browser smoke separate from live Codex runs.
- Add a scheduled or manually-triggered longer demo capture after marimo and asset IA changes, rather than widening this audit smoke.
