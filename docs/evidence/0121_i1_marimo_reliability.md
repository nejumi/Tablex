# 0121 I1 Marimo Reliability Evidence

Date: 2026-07-08

## Implemented

- Native marimo sessions now carry the source notebook SHA-256 hash.
- Opening the same notebook reuses an existing session only when the source hash still matches.
- If the source notebook changed, the old marimo process is terminated and a fresh native session is started.
- `TABLEX_MARIMO_MAX_SESSIONS` / `Settings.marimo_max_sessions` controls the number of live native marimo processes, with least-recently-used termination before creating a new session.
- Notebook registration requests enqueue a `prewarm_native_marimo_session` worker job after successful registration.
- The prewarm worker cleans stale sessions, starts or reuses the native marimo session, and reports the session id/status/source hash.
- The frontend native marimo frame polls session status and, when the session record disappears or the proxy is no longer available, requests a fresh native marimo session from the notebook artifact instead of leaving a dead iframe.
- Static HTML fallback remains absent. Runtime failures and unavailable sessions remain visible repair states.
- Notebook/chat/activity read endpoints remain read-only; stale tests that expected GET-side reconciliation were updated to the current contract.

## Verification

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/marimo_sessions.py apps/backend/tabular_harness/worker/jobs.py apps/backend/tabular_harness/services/agent_requests/notebooks.py apps/backend/tabular_harness/services/jobs.py apps/backend/tabular_harness/core/config.py apps/backend/tests/test_marimo_sessions.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_marimo_sessions.py -q` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_analysis_notebooks.py -q` -> 29 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_native_marimo_runtime_error_excerpt_prefers_traceback apps/backend/tests/test_api_flow.py::test_native_marimo_session_reports_starting_without_blocking -q` -> 2 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_marimo_sessions.py apps/backend/tests/test_analysis_notebooks.py apps/backend/tests/test_api_flow.py -q -k "marimo or notebook or native"` -> 57 passed, 112 deselected, 1 warning.
- `.venv/bin/ruff check apps/backend/tabular_harness/core/config.py apps/backend/tabular_harness/services/agent_requests/notebooks.py apps/backend/tabular_harness/services/jobs.py apps/backend/tabular_harness/services/marimo_sessions.py apps/backend/tabular_harness/worker/jobs.py apps/backend/tests/test_marimo_sessions.py apps/backend/tests/test_api_flow.py` -> passed.
- `npm run build` in `apps/frontend` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 441 passed, 6 warnings.

## Remaining I1 Evidence To Collect

- Browser-level proof that a backend restart or cleared marimo registry causes the frontend to recover by opening a fresh native marimo session.
- Browser-level proof that a registered notebook is prewarmed before first user open in the common worker path.
