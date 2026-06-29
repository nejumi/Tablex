# Streamlined Project Command Center Goal

## Objective

Reduce cognitive load in the project workspace without removing capability. The UI should make one next action obvious, then let users expand evidence, alternate routes, and journey context only when they need it.

## Design Principle

Feature completeness is not permission to show everything at once. Tablex should keep the harness deep and flexible, while the first viewport remains simple:

- Now: the one focus that matters.
- Why: the shortest evidence-backed reason.
- Do: the next action.

Everything else is supporting detail.

## Implemented Scope

- Reworked the Project Focus Guide into a compact Now/Why/Do command center.
- Moved focus evidence and secondary navigation into collapsed supporting detail.
- Reworked Guided Journey to show only the current stage by default.
- Moved the full journey stage map and stage evidence into a collapsed `Journey map`.
- Grouped secondary project tabs under `More` so the primary workflow tabs stay visible without clipping.
- Reduced Portal Recent Updates to the top entries, with older raw updates collapsed.
- Preserved existing actions, tabs, Agent Chat, journey snapshot, and stage navigation.
- Added LocalePack keys for Now/Why/Do/Journey map in English and Japanese.
- Verified the Project first viewport with Playwright Firefox.

## Deferred Work

- Apply the same progressive-disclosure rule to Notebook Center, Agent Task Results, and artifact shelves.
- Add a compact "agent suggested next read" surface inside Notebook Center.
- Add UI-level tests or snapshots once the project has a stable frontend test harness.
