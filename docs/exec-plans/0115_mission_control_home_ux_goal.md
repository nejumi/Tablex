# 0115 Mission Control Home UX Goal

## Goal

Reframe the project workspace around a human-first `Home` surface instead of many equally weighted tabs. Tablex should feel like an agentic data-science harness: the user sees the next decision, current plan, active work, chat history, and evidence destinations without hunting through implementation-shaped screens.

## Product Stance

- Tablex owns the workflow, evidence, safety gates, assets, lineage, evaluation, and UI.
- Codex remains a flexible execution engine. The harness should guide it with data-science structure, not reduce it to keyword routing or fixed recipes.
- Full Auto and Approval Based are project modes:
  - `full_auto`: ask questions, record assumptions, apply fallback policies, and keep moving.
  - `approval_based`: pause for human approval at risky evaluation, data semantics, external execution, and deployment-facing decisions.
- Most daily interaction should happen from `Home`.
- Top-level project tabs should be simple: `Home`, `Data`, `Insight`, `Leaderboard`, `Assets`, and `More`.
- Notebooks are assets and contextual evidence surfaces, not a separate destination users must understand upfront.
- Insight includes findings, ideas, reports, research notes, notebooks, and synthesized evidence.
- Assets includes project artifacts and cross-project assets such as Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates.

## Implemented This Iteration

- Added `Project.autonomy_mode` with `approval_based` default and `full_auto` alternative.
- Exposed `autonomy_mode` through Project create/read/update APIs.
- Added SQLite backfill for existing `projects.autonomy_mode`.
- Added an API integration test for autonomy mode persistence.
- Added frontend `Home` and `Insight` tabs.
- Reduced top-level navigation to `Home`, `Data`, `Insight`, `Leaderboard`, `Assets`, with legacy detail surfaces under `More`.
- Redirected legacy `Overview` and `Approach` navigation targets to `Home`; `Reports` and `Notebooks` to `Insight`; `Library` and `Lineage` to `Assets`.
- Added a Mission Control Home surface with:
  - current recommendation
  - Full Auto / Approval Based selector
  - ResearchPlan and strategy controls
  - active task panel
  - persistent multi-turn Agent Chat panel
  - evidence links to Data, Insight, Leaderboard, and Assets
- Increased retained and visible Agent Chat history to support multi-turn use.
- Folded cross-project Asset Library access into the `Assets` tab so Skill assets are not isolated behind a hidden Library tab.

## Deferred

- Real backend policy enforcement for Full Auto vs Approval Based job approval gates.
- A dedicated ResearchPlan aggregate API instead of deriving Home state from existing artifacts.
- A stronger Home agent loop that streams progress and updates ResearchPlan steps in real time.
- Rewriting Data/Insight/Leaderboard surfaces to match the new Home-first information architecture end to end.
- Deep EDA generator upgrades for ID trajectories, target-conditioned missingness, duplicates, relational joins, leakage search, and Grandmaster-style notebook writing.

## UX Risks

- `Home` now organizes the first view, but some legacy supporting tabs remain dense.
- Some backend guidance still names old surfaces; frontend normalization mitigates this, but backend copy should be updated.
- Full Auto currently persists as state; execution semantics are not enforced yet.
- Agent Chat can still return actions whose downstream job effects are not sufficiently visible unless the specific backend route is actionable.

## Next Milestone

Implement the execution-policy layer behind autonomy modes and connect Agent Chat responses to a visible ResearchPlan timeline: each user instruction should create or update a plan step, start the appropriate job or approval request, and surface the result in Home with a clear changed-state summary.
