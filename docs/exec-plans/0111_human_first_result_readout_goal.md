# 0111 Human-First Result Readout Goal

## Goal

Make post-run reading start from one human-readable result surface instead of scattered tables. Leaderboard remains evidence, but the first thing a user sees should be the top result, evaluation contract, diagnostics/comparison state, decision report state, gaps, and the next action.

## Implementation

- Added `/api/projects/{project_id}/results/readout`.
- Added `result_readout.v1` response schema.
- The readout aggregates existing Tablex-owned evidence without writing new artifacts:
  - top successful run;
  - primary metric story;
  - approved EvaluationSpec and SplitManifest;
  - latest experiment comparison and comparison report;
  - top-run diagnostics and diagnostics report;
  - notebook evidence state;
  - current decision report state;
  - evidence gaps and next action.
- Updated Agent Chat result-reading routes to target `Leaderboard` / `result-readout`.
- Updated Leaderboard UI so `Result Readout` is the first surface.
- Moved raw leaderboard rows, evaluation context, diagnostics artifact tables, and diagnostics preview into supporting details.

## Product Principle

Humans should not have to assemble meaning from raw rank tables. The UI should present one readable result first, then let users drill down only when they need supporting evidence. The readout must not claim that the leaderboard is a decision; it exposes missing evidence and keeps EvaluationSpec/SplitManifest boundaries visible.

## Verification Plan

- Backend lint/type check.
- Targeted API integration test for empty result route, successful run readout, comparison report state, and post-run decision-report state.
- Frontend lint and production build.
- Full backend test suite.
- Browser check that Leaderboard opens on Result Readout and raw tables are disclosed as supporting evidence.

## Deferred

- A dedicated Results tab may be useful later, but this pass avoids adding another navigation choice.
- Real-time streaming status inside the readout.
- Rich inline visual summaries for comparison and diagnostics.
