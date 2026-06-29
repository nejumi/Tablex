# Goal 0105: Runner Readiness Inline Feedback

## Intent

Keep the user inside the Runner Handoff focus after reviewing readiness. The result should answer whether the runner can proceed, what blocks it, and the next action without requiring a raw preview.

## Implementation Scope

- Added `pass_count`, `next_action_count`, and `first_next_action` metadata to `agent_task_readiness_review` artifacts.
- Added `pass_count` and top `next_actions` to readiness review job output.
- Added frontend `RunnerReadinessFeedback` hydration from latest readiness artifacts.
- Added inline readiness result rendering inside the Runner Handoff focus panel.
- Updated tests and docs so future changes keep the focused feedback path intact.

## Product Rule

Runner execution should not feel like a blind button press. The user sees readiness status where they are already deciding, while detailed reports remain available as supporting evidence.

## Deferred

- Persisting a full structured readiness summary endpoint.
- Automatically selecting the single safest next execution action from readiness state.
- Policy-based hiding of Codex execution when approval or workspace preparation is missing.
