# Goal 0104: Runner Handoff Focus

## Intent

Make the latest AgentTaskContract readable as one focused runner handoff instead of requiring users to expand tables or open raw JSON previews.

## Implementation Scope

- Added `agent_task_contract_summary.v1` metadata when planning AgentTaskContracts.
- Included task type, human label, objective summary, required output count, quality check count, evaluation status, split-manifest policy, notebook follow-up context count, and next action.
- Moved the `approach-handoff` anchor to a dedicated Runner Handoff focus panel.
- Kept the Strategy Brief as its own `strategy-brief-focus` surface.
- Added Approach UI actions for readiness review, contract preview, workspace preparation, local stub, and Codex execution from the focused panel.
- Reused the same action handlers in the detailed AgentTaskContract table.

## Product Rule

The user should see the next controlled runner decision immediately: what task exists, what evidence it has, what constraints it must respect, and what to do next. Detailed tables remain available as supporting material, not the primary reading path.

## Deferred

- Rendering structured readiness results directly inside the focus panel after review.
- Choosing a single recommended execution button from readiness state.
- Hiding lower-level runner controls based on policy or approval state.
