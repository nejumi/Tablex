# UX Recovery Goal

## Goal

Improve Tablex from a machine-readable artifact workbench into a human-usable agent workbench. The immediate focus is Agent Chat response quality, visible worker activity, a project-level escape hatch into a portal, and higher-quality analysis notebooks.

## Implemented

- Added `/api/projects/{project_id}/agent-chat`.
  - Returns `agent_chat_turn.v1` with assistant message, interpreted intent, actions, worker events, token telemetry estimates, and next focus.
  - Stores the chat turn as an `agent_chat_turn` artifact.
- Added intent handling for evaluation metric changes.
  - `metricはROC-AUCにして` is interpreted as `set_evaluation_metric`.
  - Mutable EvaluationCandidates and draft EvaluationSpecs can be updated.
  - Approved EvaluationSpecs and SplitManifests are not destructively changed; a review artifact is created instead.
- Updated the persistent Agent Chat UI.
  - Shows human-facing responses and action chips instead of only artifact IDs.
- Added a right-edge Agent Activity rail.
  - Shows agent/notebook/research worker cards, status, action summaries, estimated token series, and mini worker chat inputs.
  - Current token telemetry is explicitly marked as estimated until real Codex runner telemetry exists.
- Added a top-level Portal.
  - Project detail has a Back to Portal affordance.
  - Portal shows cross-project project portfolio status, recent updates, and a local idea inbox for follow-up thoughts.
- Upgraded generated data-understanding and model-diagnostics notebooks.
  - Added reader briefs, human review checklists, investigation queues, and next-analysis prompts.
- Added `skills/tablex-notebook-quality/SKILL.md` and included it in AgentTaskContract context files.

## Decisions

- Agent Chat should not expose raw artifact IDs as the primary answer. Artifact IDs remain available as supporting evidence, but the main response must explain what was understood, what happened, and what the user should inspect next.
- The worker rail should be visible and lively without pretending real Codex telemetry exists. Estimated token series are acceptable only when clearly labeled.
- Portal-level UX is necessary because users should not feel trapped inside one project workspace.
- Notebook quality should be treated as a reusable Codex skill/reference, not only a one-off template tweak.

## Deferred

- Persisted cross-project backend analytics for Portal job/artifact counts.
- Server-side product/UX inbox artifacts or GitHub issue promotion.
- Real Codex runner telemetry for token usage, sub-agent identity, step logs, and live status.
- Real sub-agent chat routing; current worker mini-chat sends scoped messages through the project Agent Chat endpoint.
- Full marimo execution with captured figures/tables.

## Risks

- The current Agent Chat intent parser is intentionally small and heuristic. It should grow through explicit, test-backed intents rather than becoming a brittle natural-language command router.
- Activity rail density can become distracting as real runners become noisier. It will need filters, collapse behavior, and severity-based prioritization.
