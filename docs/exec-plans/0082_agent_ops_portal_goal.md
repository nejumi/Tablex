# Agent Ops and Portal Backend Goal

## Goal

Make cross-project Portal and agent activity less local/ephemeral while reducing project-screen cognitive load. Agent Activity should appear only while work is active or has just completed, and Portal ideas should be persisted as harness-owned artifacts instead of browser-only state.

## Implemented Scope

- Added backend Portal endpoints:
  - `GET /api/portal/overview`
  - `GET /api/portal/ideas`
  - `POST /api/portal/ideas`
- Added cross-project `portal_idea` artifacts with no project id.
- Added `GET /api/projects/{project_id}/agent-activity`.
- Normalized worker events from Job output with timestamps, active flags, target tabs, and estimated token telemetry.
- Expanded Agent Chat direct intents:
  - set evaluation metric,
  - generate Data Understanding notebook,
  - explain the next guided focus.
- Updated project UI:
  - Portal consumes backend summary/recent updates/ideas.
  - Agent Activity no longer reserves permanent right-side space.
  - Activity overlay appears only for active workers or recent completions.
  - Multiple worker cards can appear at once.
  - Token sparkline animates during active work.
  - Agent Chat shows an optimistic running worker immediately after submit.

## Deferred Scope

- True streaming telemetry via SSE/WebSocket.
- Real Codex runner token counts and per-subagent lifecycle events.
- Subagent fan-out orchestration beyond Job/agent-chat event normalization.
- Portal-level team analytics beyond first summary counts and recent updates.
- Editing, triaging, or promoting Portal ideas into project-scoped work items.

## EDA Quality Status

The current notebook work is not yet at "Kaggle Notebook Grandmaster / Heads or Tails-style" quality. It now has reader briefs, review checklists, investigation queues, notebook previews, execution planning, and capture artifacts, but it still needs richer target-aware narrative EDA and executed visual evidence.

The next notebook-quality milestone should preserve Codex flexibility while adding a quality rubric and context pack for:

- dataset story and audience-facing narrative,
- target distribution and metric relevance,
- missingness/duplicate/leakage/availability analysis,
- numeric, categorical, text, datetime, group, and temporal feature views,
- bivariate and multivariate target relationships,
- cohort/slice analysis,
- train/test or split-aware drift checks,
- baseline/model diagnostics, feature importance, permutation importance, partial dependence, calibration, residual/error analysis, and prediction examples,
- explicit "what to try next" hypotheses with artifact and lineage registration.

The product should not hard-code one fixed EDA recipe. The harness should provide safety boundaries, expected artifacts, evaluation constraints, and a quality rubric; Codex/Skills/research can choose the actual analysis approach based on dataset semantics and current evidence.

## Verification

- Backend targeted integration tests:
  - `test_portal_overview_ideas_and_agent_activity`
  - `test_agent_chat_updates_evaluation_metric_with_human_response`
- Frontend:
  - `npm run lint`
  - `npm run build`

## Risks

- Current activity animation is polling-based and estimated; it can feel live but is not true runner telemetry.
- Activity cards use recent-completion grace windows, so exact disappearance timing is client-side.
- Portal idea artifacts are append-only in this milestone.
- Notebook quality remains a product gap; calling the current output "Grandmaster-level" would be misleading.
