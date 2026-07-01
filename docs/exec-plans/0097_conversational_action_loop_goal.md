# 0097 Conversational Action Loop Goal

Date: 2026-06-30

## Goal

Make Agent Chat feel like an in-product guide and action loop, not a contract logger. A project-control request such as changing the metric or asking Codex to plan feature strategy should return a short human answer, a visible action state, a protected boundary, and a clear next place to inspect.

## Implemented

- Added `agent_action_summary.v1` to Agent Chat turns.
- Classified chat outcomes as `applied`, `planned`, `needs_review`, or `noted`.
- Added summary headlines, changed/review lists, next-step metadata, and harness boundary reminders.
- Preserved EvaluationSpec and SplitManifest immutability: chat can update mutable candidates and drafts, but approved evaluation assets require a revised design path.
- Updated the project Agent Chat dock to render the summary as the primary response before action buttons.
- Added API regression coverage for metric changes and generic Codex runner handoffs.

## Design Notes

- Artifact ids remain lineage details and must not be the user's main answer.
- Codex autonomy begins inside a harness-owned `AgentTaskContract`; the chat endpoint prepares and explains the controlled handoff.
- The UI should route the user to the next useful surface instead of making them infer which tab or artifact matters.

## Follow-Up

- Expand direct safe intents for objective-definition review, ER diagram upload/rendering, report generation, and notebook capture.
- Replace estimated token usage with real runner telemetry when Codex runner execution is wired in.
- Continue reducing first-viewport noise; keep raw shelves behind explicit detail disclosures.
