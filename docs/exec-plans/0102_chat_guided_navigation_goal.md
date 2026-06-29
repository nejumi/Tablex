# Chat-Guided Navigation Goal

## Goal

Make Agent Chat move the user to the exact workbench surface that answers the request. A response should not only say "go to Data" or "go to Notebooks"; it should carry a stable anchor so the UI can switch tabs, scroll, and briefly highlight the target.

## Context Read

- `apps/backend/tabular_harness/services/agent_chat.py`
- `apps/backend/tests/test_api_flow.py`
- `apps/frontend/src/main.tsx`
- `apps/frontend/src/styles.css`
- `docs/dev.md`

## Implementation

- Added `target_anchor` to Agent Chat actions and action summaries.
- Added backend anchors for common intents:
  - `dataset-upload`
  - `data-focus`
  - `relational-map`
  - `notebook-focus`
  - `analysis-story`
  - `evaluation-design`
  - `approach-handoff`
  - `assumption-review`
  - `understanding-report`
  - `decision-report`
- Added frontend action routing through `navigateToTarget(tab, anchor)`.
- Added stable DOM anchors to focused Data, Notebook, Evaluation, Approach, Assumption, Understanding, and Report surfaces.
- Added short highlight animation on navigated surfaces.
- Updated Agent Chat action card labels to show the exact surface, for example `Data · Relational Map`.

## Validation

- API tests assert `target_anchor` on metric, relational, notebook, EDA, and AgentTask chat actions.
- Browser checked `ER図を表示して` on the Home Credit project:
  - chat response routed to Data,
  - action card showed `Data · Relational Map`,
  - the page landed on the Relational Map surface.

## Deferred

- Add anchor-aware guidance actions outside Agent Chat.
- Add explicit scroll/open behavior for collapsed supporting shelves when the anchor points inside a shelf.
- Move anchor names into a shared schema if they begin to appear outside the web UI.
