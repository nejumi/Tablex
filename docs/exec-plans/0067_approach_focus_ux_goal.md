# 0067 Approach Focus UX Goal

## Goal

Reduce cognitive load in the Approach tab after adding the Adaptive Strategy Brief.

## Rationale

The Approach tab accumulated useful but dense surfaces: ResearchPlans, ResearchSourcePacks, ResearchSyntheses, AgentTaskContracts, ResearchBriefs, Ideas, and preview panels. Showing every table at once makes the user decide what matters, which conflicts with the product direction that the harness should guide the workflow.

## Implemented Scope

- Kept Adaptive Strategy Brief as the first visible surface.
- Kept quick action buttons visible directly below the brief.
- Grouped supporting panels into progressive-disclosure sections:
  - Research context
  - Runner handoff
  - Previews and manifests
- Preserved all existing actions and previews.
- Added compact count labels to each group summary.
- Added responsive CSS so the groups remain readable on mobile.

## Out Of Scope

- Reworking every Approach panel into a custom compact card.
- Removing any existing artifact tables or download actions.
- Backend changes beyond the already added Strategy Brief API.

## Risks And Open Questions

- `details/summary` is intentionally simple; future UX may want remembered open state per user.
- Research Briefs currently live under Runner handoff because they are mostly used to create or inspect Ideas; this can move if research browsing becomes a primary workflow.
- The quick action toolbar may eventually become contextual to the recommended action instead of showing every action.
