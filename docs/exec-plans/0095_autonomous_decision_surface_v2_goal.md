# 0095 Autonomous Decision Surface v2 Goal

## Goal

Make Tablex's next-decision surface more than a visual recommendation. The harness should synthesize a compact decision brief that humans and Codex runners can share: one question, why now, evidence to check, the primary action, what not to do yet, and the harness boundaries.

## Implemented Scope

- Added embedded `autonomous_decision_brief.v1` to `autonomous_navigation.v1`.
- Added `POST /api/projects/{project_id}/guidance/decision-brief`.
- Saved decision briefs as `autonomous_decision_brief` JSON artifacts and `autonomous_decision_brief_report` Markdown report artifacts with lineage.
- Updated Agent Chat's "next step" response to use the same decision brief language.
- Updated the Autonomous Navigator UI to show the decision question and keep brief persistence inside the collapsed map/details area.
- Added tests for the brief schema, persistence endpoint, report preview, and Agent Chat convergence.

## Design Notes

- The brief is not a new dashboard shelf. It is a small checkpoint for handoff, audit, or runner context.
- The primary UI still keeps attention budget at one.
- Codex remains free to choose the approach after receiving evidence and constraints; the brief only names the current product-owned decision.

## Deferred

- Selecting prior decision briefs from a history drawer.
- Deep linking saved decision briefs from Agent Chat action buttons.
- Letting a real Codex runner rewrite Tier 3 brief prose in the user's locale.
