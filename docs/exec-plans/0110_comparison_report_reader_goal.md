# 0110 Comparison Report Reader Goal

## Goal

Make Leaderboard a result-reading surface, not a detached scoreboard. A user should be able to ask Tablex to summarize top-run results and land on a readable comparison or decision report without hunting through raw artifact shelves.

## Implementation

- Added a `post_run_reading_workflow` job type.
- Added Agent Chat intent handling for post-run requests such as asking to summarize results with diagnostics and a decision report.
- The workflow:
  - requires at least one successful run;
  - diagnoses the top run when diagnostic inputs are available;
  - drafts a top-run report;
  - creates experiment comparison artifacts and report;
  - generates the current decision report;
  - routes the user to Reports first, with Leaderboard kept for rank-level detail.
- Updated Leaderboard Reader to auto-preview the latest `experiment_comparison_report`.
- Added a `Post-run Report` action next to top-run diagnostics, report, and notebook actions.

## Product Principle

Leaderboard evidence is useful only under a visible EvaluationSpec and SplitManifest. Ranking alone is not a decision. Missing diagnostics must remain visible as a gap; Tablex should not invent unavailable model evidence.

## Verification Plan

- Run targeted backend lint, type check, and API integration tests for Agent Chat and the full project flow.
- Run frontend lint and production build.
- Run full backend test suite before commit.
- Browser-check a project with a successful run and confirm Leaderboard shows the comparison reader and post-run action.

## Deferred

- Real-time streaming progress for the multi-step post-run workflow.
- Richer comparison visuals in the Leaderboard Reader beyond the current report preview.
- Deeper notebook-quality generation from comparison reports.
