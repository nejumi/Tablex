# 0121 Verification Rollup

Date: 2026-07-08

This file is the audit entry point for the 0121 response cycle. Detailed evidence remains in the linked workstream files.

## Workstream Status

| Workstream | Status | Primary Evidence |
| --- | --- | --- |
| I1 native marimo reliability | Done | `docs/evidence/0121_i1_marimo_reliability.md` |
| I2 storage usage and GC controls | Done | `docs/evidence/0121_i2_storage_controls.md` |
| I3 related outputs and human-centered asset access | Done | `docs/evidence/0121_i3_related_outputs_and_assets.md` |
| I4 expected deliverable ledger | Done | `docs/evidence/0121_i4_deliverable_expectations.md` |
| I5 Chat/Activity quieting and stop conditions | Done | `docs/evidence/0121_i5_chat_activity_quiet.md` |
| I6 browser evidence and evidence grades | Done | `docs/evidence/0121_i6_browser_e2e_and_evidence_grades.md` |

## Browser Evidence

The I6 browser smoke command is:

```bash
node apps/frontend/e2e/golden_slice_smoke.mjs
```

Latest recorded result:

```text
exit code 0
project_id: p_887bbe7672d7
upload_primary_dataset_snapshot_id_after_upload: null
run_id: run_e2e_golden_slice
prediction_job_id: job_bb3d4a6fc67d
```

Evidence artifacts:

- `output/playwright/0121_i6_golden_slice_result.json`
- `output/playwright/0121_i6_notebook_from_chat.png`
- `output/playwright/0121_i6_notebook_from_leaderboard.png`
- `output/playwright/0121_i6_leaderboard_pilot.png`

## Live Full Auto Evidence

The I6 live smoke command is:

```bash
node apps/frontend/e2e/live_full_auto_research_pilot_smoke.mjs
```

Latest recorded `L` result:

```text
project_id: p_8d5d818b1cd4
agent_session_id: ags_6e37f258b692
research_findings_report: art_f9ba1b08b1ca
research_markdown_report: art_c10f02dc13c7
pilot_scoring_report: art_0fe54db0889e
validation_scheme_audit: art_5ecbb0403a27
source_count: 4
finding_count: 5
validation audit verdict: partially_confirmed
```

Evidence artifact:

- `output/live/0121_i6_live_full_auto_research_pilot_passed_recovered_20260707T185948Z.json`

## Verification Coverage

- Primary-free upload: covered by unit/API evidence from 0120 and browser evidence in I6.
- Native marimo opening from Chat and Leaderboard: covered by browser evidence in I6.
- Leaderboard human-readable model row and pipeline bundle download: covered by browser evidence in I6.
- Pilot prediction and pilot scoring visibility: covered by browser evidence in I6.
- Source-backed live research plus pilot validation audit: covered by live Full Auto evidence in I6.
- Repeated Chat/Activity notices: covered by focused backend tests in I5.
- Storage usage and GC controls: covered by focused backend tests in I2.
