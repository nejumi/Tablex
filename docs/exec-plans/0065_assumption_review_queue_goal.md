# 0065 Assumption Review Queue Goal

## Goal

Reduce cognitive load inside the Assumptions tab by adding a harness-owned prioritized review queue.

## Rationale

The Focus Guide can point users to Assumptions, but a large assumption table still requires the user to decide what matters first. The harness already owns assumptions, questions, evidence, risk levels, fallback policies, and evaluation safety, so it should compute the next review item.

## Implementation

- Added `GET /api/projects/{project_id}/assumptions/review-queue`.
- Added `assumption_review_queue.v1` response schema.
- The queue merges:
  - unresolved Assumptions
  - unanswered Questions
  - linked Evidence summaries
- Priority scoring uses:
  - `risk_level`
  - `fallback_policy`
  - `requires_user_confirmation`
  - question priority and blocking flags
  - confidence for assumptions
- Updated the Assumptions tab to show a single Review Queue card before the supporting table.
- The card can:
  - confirm or challenge an assumption
  - answer a question with a choice and note
- The full table remains available as supporting detail.

## UX Notes

- The first visible task should be one review item, not the whole assumption inventory.
- Evidence is capped in the card to avoid turning it into another dashboard.
- Fallback policies remain visible because they explain what the harness will do if the user does not answer.

## Out Of Scope

- Persisting review queue snapshots.
- Multi-user assignment or review ownership.
- Rich filtering/sorting controls for every assumption.
- Automated resolution of challenged assumptions.

## Risks and Open Questions

- Deterministic priority scoring may need tuning as real projects grow.
- Question answers can confirm related assumptions only when `related_assumption_id` is present.
- Chosen answers should eventually create more explicit assumption/evaluation lineage in addition to the current Evidence record.
