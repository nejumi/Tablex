# 0121 Workstream I4 Deliverable Expectations Evidence

Date: 2026-07-08

## Scope

Implemented the non-blocking expected deliverables ledger:

- Added `DeliverableExpectation` records with `open`, `fulfilled`, and `waived` states.
- Created model diagnostics notebook expectations from successful `register_runs` requests when linked diagnostics notebooks are not already ready.
- Fulfilled model diagnostics notebook expectations only after a `register_notebook` request succeeds for `notebook_kind=model_diagnostics` and linked run ids.
- Fulfilled pipeline bundle expectations after successful prediction pipeline registration.
- Added `.tablex/requests/deliverables` with `waive_deliverable` for explicit Codex-authored unnecessary-output decisions with required rationale.
- Added one-time inbox observations for open expectations older than 30 minutes.
- Exposed run deliverable expectations on the leaderboard API and added a small non-blocking pending-output badge in the leaderboard evidence column.

No expectation blocks run registration, plan progress, or session continuation.

## Verification

Backend targeted tests:

```bash
.venv/bin/python -m pytest \
  apps/backend/tests/test_api_flow.py::test_deliverable_expectation_flow_from_runs_to_model_notebook \
  apps/backend/tests/test_api_flow.py::test_pipeline_bundle_fulfills_deliverable_expectation \
  apps/backend/tests/test_api_flow.py::test_waive_deliverable_requires_rationale_and_updates_expectation \
  apps/backend/tests/test_api_flow.py::test_open_deliverable_expectation_observation_is_sent_once -q
```

Result:

```text
4 passed, 1 warning in 7.61s
```

Backend syntax and focused lint:

```bash
.venv/bin/python -m py_compile apps/backend/tabular_harness/models/entities.py apps/backend/tabular_harness/services/deliverable_expectations.py apps/backend/tabular_harness/services/agent_requests/deliverables.py apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_workspace_outputs.py apps/backend/tabular_harness/worker/jobs.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_api_flow.py
.venv/bin/ruff check apps/backend/tabular_harness/services/deliverable_expectations.py apps/backend/tabular_harness/services/agent_requests/deliverables.py
```

Result:

```text
All checks passed!
```

Frontend targeted lint and build:

```bash
cd apps/frontend && ./node_modules/.bin/eslint src/components/LeaderboardTab.tsx src/types.ts src/copy.ts
cd apps/frontend && npm run build
```

Result:

```text
✓ built in 372ms
```

Full backend regression:

```bash
.venv/bin/python -m pytest apps/backend/tests -q
```

Result:

```text
451 passed, 6 warnings in 153.85s
```
