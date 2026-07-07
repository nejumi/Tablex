# 0121 I5 Chat/Activity Quieting Evidence

Date: 2026-07-08

## Scope

Workstream I5 tightened the user-facing Chat and Activity surfaces without adding harness-side analysis prose:

- Consecutive identical assistant chat turns are compacted by exact structured display identity.
- Existing experiment registration compaction remains in place.
- Completed plans stay quiet: no progress nudge is requested once the current ResearchPlan has no runnable work.
- Activity waiting state names the next acceptable inputs: test data, outcomes, or user instruction.
- Terminal upload/import activity cards are limited to the latest five while Jobs keeps the full history.
- Chat/Activity copy avoids runner/retry/session/process wording on user-facing surfaces.

## Verification

Backend targeted tests:

```bash
.venv/bin/pytest apps/backend/tests/test_api_flow.py -k "compaction_dedupes_experiment_registration_notices or compaction_dedupes_identical_progress_reports or compaction_dedupes_identical_attention_turns or visible_activity_workers_limit_terminal_upload_import_cards or completed_plan_waits_for_new_input_options or portal_overview_limits_terminal_upload_import_activity_cards or runner_retry_state or stale_codex_runner or turn_state_waits_for_user or activity_hides_future_autonomous_heartbeat or activity_hides_queued_autonomous_worker_when_project_idle"
```

Result: 11 passed.

Completed-plan direct tests:

```bash
.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -k "completed_plan_pause or completed_plan_pauses or progress_update_nudge_skips_completed_plan or safe_completed_plan_pause"
```

Result: 3 passed.

Backend full suite:

```bash
.venv/bin/pytest apps/backend/tests
```

Result: 456 passed, 6 warnings.

Backend lint on touched files:

```bash
.venv/bin/ruff check apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/services/portal.py apps/backend/tabular_harness/services/agent_session_chat.py apps/backend/tests/test_api_flow.py
```

Result: all checks passed.

Frontend build:

```bash
npm --prefix apps/frontend run build
```

Result: passed.

Frontend lint on touched file:

```bash
npm --prefix apps/frontend exec eslint -- apps/frontend/src/copy.ts --max-warnings=0
```

Result: passed.

Frontend full lint was not used as the gate for this change because existing unrelated lint failures remain in `App.tsx`, `AgentActivityRail.tsx`, and `RawAgentStream.tsx`.
