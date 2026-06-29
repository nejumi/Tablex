# Agent Activity Ephemeral Overlay Goal

## Goal

Make Agent Activity feel like live work, not persistent decoration. The right-edge worker cards should appear only for active or just-finished agent, notebook, or research activity, then disappear quickly so the project workspace remains simple and readable.

## Context Read

- `docs/dev.md`
- `docs/exec-plans/0081_ux_recovery_goal.md`
- `docs/exec-plans/0082_agent_ops_portal_goal.md`
- `apps/backend/tabular_harness/services/agent_chat.py`
- `apps/frontend/src/main.tsx`

## Implementation

- Stopped marking chat turns with `needs_review` as active worker events in backend chat responses.
- Tightened frontend worker visibility so stale `active: true` data is ignored unless the event status is actually `queued`, `running`, or `approval_required`.
- Kept recent non-running events briefly visible so users still see immediate feedback after an action completes or enters review.
- Kept animated token sparklines tied to truly active worker states.

## Product Rule

Review-needed work belongs in Agent Chat, action summaries, and next-step controls. It must not remain as a live worker card because that makes the UI look busy without real work happening and increases cognitive load.

## Validation

- `python3 -m ruff check apps/backend/tabular_harness apps/backend/tests`
- `python3 -m mypy apps/backend/tabular_harness`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest apps/backend/tests/test_api_flow.py::test_agent_chat_updates_evaluation_metric_with_human_response apps/backend/tests/test_api_flow.py::test_portal_overview_ideas_and_agent_activity -q`
- `npm run lint --prefix apps/frontend`
- `npm run build --prefix apps/frontend`

## Deferred

- Real Codex runner telemetry should replace estimated token series.
- True sub-agent chat channels should route to runner-owned execution contexts rather than project chat scoping.
- Long-running jobs should stream state over SSE or WebSocket instead of polling.
