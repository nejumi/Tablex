# Goal 0107: Chat-Driven Harness Actions

## Objective

Deprecated direction: natural-language Agent Chat must not directly run common harness actions. A user should be able to ask for help in natural language, while generated Jobs/artifacts come from explicit controls or schema-validated agent proposals with a protected boundary and human-readable result.

## Implemented Scope

- Deprecated: these Agent Chat natural-language intents were removed. Equivalent harness actions remain explicit endpoints or future schema-validated proposals for:
  - Data Quality Gate review.
  - EvaluationCandidate drafting.
  - Evaluation scenario comparison.
  - Baseline strategy planning when EvaluationSpec and SplitManifest prerequisites exist.
  - Decision Report generation.
- Direct actions create the same Job records and artifact outputs as the product endpoints.
- Missing prerequisites return `needs_review` and route to the exact product surface instead of failing silently.
- Baseline strategy remains a planning artifact, not a fixed AutoML recipe and not a deployment approval.
- Added API integration coverage for quality/evaluation/report chat actions and baseline strategy chat action after evaluation approval.

## Design Rules

- Chat can trigger safe harness-owned actions; it must not bypass EvaluationSpec, SplitManifest, approvals, artifact registration, or lineage.
- A direct action should produce an inspectable artifact or a clear `needs_review` reason.
- Natural language command routing is prohibited. Tests should prevent phrase-specific routers and verify explicit endpoints/proposal validation instead.
- The UI response should lead with what happened and where to inspect next; raw artifact ids remain supporting lineage.

## Validation Plan

- `ruff check apps/backend`
- `mypy apps/backend/tabular_harness`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest apps/backend/tests`
- `npm run lint`
- `npm run build`
- Browser check: submit a Chat request for a direct action and confirm the next-step card routes to the focused surface.

## Deferred

- Chat attachments for dataset files and ER diagrams.
- Full async background execution for all direct actions.
- Richer intent classification backed by locale packs and project state.
- Running baseline models directly from chat; this should stay guarded behind approved evaluation and explicit run controls.
