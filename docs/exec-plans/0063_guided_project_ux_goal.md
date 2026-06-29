# 0063 Guided Project UX Goal

## Goal

Reduce cognitive load in the project workspace by letting the harness recommend the next useful surface instead of exposing every project signal at the same visual priority.

## User Feedback

- The UI looks data-driven, but too much information is visible at once.
- Human users need stronger navigation than an AI agent because they cannot absorb many parallel signals.
- The agent/harness should guide what to inspect next.

## Implementation Plan

- Add a project-level Focus Guide above the tab content.
- Derive the recommended focus from current project state:
  - no dataset -> Data
  - no understanding report -> Understanding
  - high-risk assumptions -> Assumptions
  - no approved EvaluationSpec -> Evaluation
  - no experiment runs -> Approach
  - no reports -> Experiments
  - otherwise -> Reports
- Keep secondary tabs visible as useful alternatives without making them compete with the primary recommendation.
- Simplify Overview so it shows only at-a-glance metrics and a short action list by default.
- Move high-risk assumption tables, recent jobs, and recent artifacts into supporting details.

## Design Notes

- The guide is harness-owned and deterministic for now, but it should later be fed by agent-generated project diagnosis, user intent, and report readiness signals.
- The recommendation should not force a workflow. It should explain why a surface is useful and let the user navigate elsewhere.
- The UI should preserve the rich Tablex feel while reducing the number of visible decisions on first read.

## Out Of Scope

- Personalized user-level workflow memory.
- Agent-generated natural language coaching beyond deterministic state rules.
- Persisting dismissed or accepted focus recommendations.
- Reworking every tab's internal information architecture.

## Risks and Open Questions

- Current focus rules are intentionally simple and may over-prioritize high-risk assumptions after they have already been reviewed.
- The next version should add explicit reviewed/ignored states or user-dismissed focus records.
- Tab-level empty states still need a broader pass so each tab has one obvious primary action.
