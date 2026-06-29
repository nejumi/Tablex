# 0093 Assumptions Review Simplicity Goal

## Goal

Make the Assumptions tab match the Autonomous Navigator principle. When users are routed to Assumptions, they should see the single most important review item first, not a full audit table.

## Implemented Scope

- Kept `AssumptionReviewQueuePanel` as the primary surface.
- Moved the full assumptions table, evidence-link table, and batch fallback action behind a supporting-details disclosure.
- Preserved assumption confirm/challenge actions, evidence visibility, fallback policy visibility, and lineage-facing tables.
- Added localized summary copy for the disclosure label.

## Design Notes

- Full tables are still available for audit and debugging, but they are not the default task surface.
- The first screen should answer: what needs review, why, what can I do now?
- Batch fallback remains available, but it should feel deliberate rather than the first obvious click.

## Deferred

- Per-risk grouped assumption shelves.
- Inline evidence previews inside the review card.
- A dedicated "review complete" state with next Navigator handoff.
