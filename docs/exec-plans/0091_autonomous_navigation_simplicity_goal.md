# 0091 Autonomous Navigation Simplicity Goal

## Goal

Move the project experience from "many visible workbench surfaces" toward one harness-owned next decision. The user should see the smallest meaningful next action, why it matters, and enough evidence to trust it. Full journey state, raw artifact shelves, jobs, and lineage remain available, but they should not be the default cognitive load.

## Design Principles

- Complexity is a cost. The primary surface should show one decision, not the system topology.
- Codex is an interactive runner and guide, not the product owner. Tablex owns UI, approvals, evaluation, lineage, artifact registration, and safety boundaries.
- Guidance should preserve flexible approach selection. The harness passes evidence, constraints, and prompts; it should not freeze modeling into old AutoML recipes.
- Artifact ids are supporting lineage. Agent Chat responses must explain what was understood, what happened, and where to inspect next.

## Implemented Scope

- Added `autonomous_navigation.v1` inside `project_guidance.v1`.
- Added one-decision metadata: status, headline, why, primary action, confidence/risk, evidence, journey progress, hidden complexity, and Codex navigation prompt.
- Replaced the visible project top area with an `AutonomousNavigator` that shows one primary action and folds the journey map behind disclosure.
- Updated generic Agent Chat fallback wording so runner handoffs are explained in human terms before artifact lineage details.
- Added tests for the navigation contract and non-artifact-first generic chat response.
- Documented the navigation contract and Agent Chat response rule in `docs/dev.md`.

## Deferred

- True LLM-authored navigation copy. Current copy is deterministic harness synthesis; later Codex runners can rewrite or localize Tier 3 narrative under the same contract.
- Rich live runner telemetry from real Codex execution. Token charts still use estimates until runner telemetry is connected.
- Deeper UI pruning across each individual tab. This goal reduces the top-level decision surface first.

## Risks

- The frontend still carries older Focus Guide and Guided Journey components as internal fallback/legacy code. They are no longer rendered from the main project surface, but should be removed once no tests or fallback paths depend on them.
- `autonomous_navigation.v1` is intentionally small. If future teams add many fields and expose them by default, the UX will regress.
