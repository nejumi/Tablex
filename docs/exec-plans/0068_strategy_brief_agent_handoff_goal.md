# 0068 Strategy Brief Agent Handoff Goal

## Goal

Make the Adaptive Strategy Brief part of AgentRunner handoff, not only a UI guidance surface.

## Rationale

The product direction is that the harness guides the overall data science flow while Codex keeps flexibility for project-specific approaches. If the UI shows a Strategy Brief but the AgentTaskContract does not carry it, Codex can miss the same guidance the user sees.

## Implemented Scope

- Added latest `adaptive_strategy_brief`, `adaptive_strategy_report`, and adaptive strategy `visualization_spec` artifacts to AgentTask planning context.
- Added `adaptive_strategy_brief` summary inputs to AgentTaskContract payloads:
  - recommended next action
  - candidate lanes
  - Codex handoff policy
  - reporting plan
  - fixed recipe policy
- Marked `open_ended_approach_space.strategy_brief_available`.
- Materialized the Strategy Brief artifacts into planned controlled workspaces through existing `available_context_artifacts`.
- Added AgentTask readiness check `adaptive_strategy_context`.
- Added LocalStub approach decision trace fields for Strategy Brief guidance.
- Updated planner and integration tests.

## Design Choices

- Keep the contract summary small and copy the full artifact into workspace context.
- Treat Strategy Brief as product guidance, not a recipe lock.
- Keep materialization in the generic context artifact pipeline rather than adding a separate workspace path mechanism.

## Out Of Scope

- Real Codex execution using the Strategy Brief.
- A UI diff between Strategy Brief versions.
- Approval workflow for accepting a Strategy Brief as the official plan.

## Risks And Open Questions

- If multiple `visualization_spec` artifacts exist, planner selects the one tagged with `visualization_scope=adaptive_strategy`.
- Strategy Brief snapshots should be refreshed when evaluation, assumptions, or research context materially changes.
