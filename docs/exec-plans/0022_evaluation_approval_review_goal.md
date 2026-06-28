# Evaluation Approval Review Goal

## Goal

Add an explicit review step before approving an EvaluationSpec. Tablex should not silently approve an evaluation design when required questions or deployment-blocking assumptions remain, but it should still support assumption-backed progress for non-blocking uncertainty.

## Implemented

- Added `schemas/evaluation_approval_review.schema.json`.
- Added `review_evaluation_approval` job type.
- Added `POST /api/evaluation-specs/{spec_id}/approval-review`.
- Updated `POST /api/evaluation-specs/{spec_id}/approve` to generate an approval review, block explicit blockers, then write an approved EvaluationSpec artifact when approval succeeds.
- Review payload integrates:
  - EvaluationSpec
  - DatasetSnapshot
  - latest EvaluationScenarioComparison artifact
  - latest DataQualityGate artifact
  - latest RelationalCatalog artifact
  - open Questions
  - active Assumptions
- Approval review artifacts record blockers, assumption-backed proceed context, findings, warning counts, and decision support.
- Added lineage from EvaluationSpec, DatasetSnapshot, and context artifacts to the approval review.
- Added Evaluation UI actions to create, preview, and download approval review artifacts.
- Added Assumptions UI actions to confirm or challenge assumptions.
- Added integration coverage for both non-blocking assumption-backed approval and blocking required-question approval.

## Design Choices

- Approval reviews are artifacts rather than a new metadata table in this MVP.
- The blocker policy is narrow: unanswered `block_until_answered`, `blocks_next_phase`, `can_proceed_without_answer=false`, and blocking/deployment-blocking assumptions.
- Non-blocking uncertainty is not hidden. It remains in `assumption_backed_proceed` with fallback policy, status, confidence, and risk.
- Approval does not alter split definitions or candidate history. It updates only EvaluationSpec status and writes a new spec artifact version.

## Deferred

- A dedicated rich review diff UI.
- Manual override reasons for approving against comparison recommendations.
- Runtime JSON Schema validation of stored approval review artifacts.
- Per-organization approval policy configuration.

## Risks And Open Decisions

- `require_before_deployment` currently blocks EvaluationSpec approval. This is conservative and may be split into research approval vs deployment approval later.
- Review scoring remains rule-based. Cross-project EvaluationPattern assets and Skill outputs should eventually contribute findings.
- Blocking approval currently returns HTTP 409 and rolls back DB writes from the approve attempt; users should create an approval review explicitly to persist blocked review context.
