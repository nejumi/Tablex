# Goal 0108: Focused Evidence Reader

## Objective

Make Chat-triggered and workflow-triggered evidence land in a simple first reading surface. Users should not have to infer that a small preview button controls a distant panel, nor scan raw tables before seeing the next useful decision.

## Implemented Scope

- Added a shared frontend Evidence Reader pattern for Data, Evaluation, Leaderboard, and Reports.
- Data now auto-loads the latest quality/profile evidence preview into the first reader.
- Evaluation now auto-loads the latest scenario comparison into the first reader and keeps approval/SplitManifest actions explicit.
- Reports now shows the current decision report preview inside the primary reader instead of a separate distant text panel.
- Leaderboard is restored as a primary project tab instead of being hidden under More.
- Leaderboard now starts with comparable-evidence context: run count, approved spec count, split manifest count, diagnostics count, and a clear warning that ranks require the same evaluation contract.

## Design Rules

- First viewport should answer: what is this evidence, can I trust it, what changed, what should I do next?
- Raw artifact tables are supporting shelves, not the primary reading path.
- Leaderboard is not an AutoML scoreboard. It is decision evidence under EvaluationSpec, SplitManifest, and diagnostics context.
- Keep Codex flexible for approach selection, but keep harness-owned evaluation and reporting boundaries visible.

## Validation Plan

- `npm run build`
- `npm run lint`
- `ruff check apps/backend`
- `mypy apps/backend/tabular_harness`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest apps/backend/tests`
- Browser check:
  - Leaderboard appears in the primary tab row.
  - Data Chat quality request lands on Data Evidence Reader with an inline preview.
  - Evaluation comparison lands on Evaluation Evidence Reader with inline scenario preview.
  - Decision report generation lands on Decision Report Reader with inline report preview.

## Deferred

- Add direct Agent Chat routing for "show leaderboard" and "compare top runs".
- Add a backend summary endpoint if reader content needs server-side synthesis beyond artifact previews.
- Add user-specific persisted last-opened reader state.
