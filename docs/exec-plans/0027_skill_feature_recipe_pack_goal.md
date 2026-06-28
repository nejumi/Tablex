# Cross-project Skill & FeatureRecipe Pack Goal

## Goal

Expand the cross-project asset library so runner planning can reference reusable Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates without hard-coding one modeling recipe into the harness.

## Implemented Scope

- Expanded default seeded assets from a minimal set to a broader pack covering:
  - controlled tabular approach research
  - mixed-type XGBoost-style tabular baselines
  - train-fold TF-IDF text features
  - causal time lag and rolling features
  - relational aggregation
  - time-series forward validation
  - relational/entity leakage review
  - evaluation diagnostics interpretation
  - decision report prompting
  - decision readiness visualization
- ResearchPlan context now includes EvaluationDiagnostics, BenchmarkScenarioPack, and DecisionDashboard artifacts.
- ResearchPlan asset recommendation now uses semantic tags plus text/time/relational/benchmark/decision/diagnostic context to explain why assets are relevant.
- Library UI now shows semantic tags.

## Design Notes

- These assets guide runner planning; they do not force a fixed baseline or modeling recipe.
- Feature recipes explicitly reference SplitManifest, train-fold fitting, prediction-time availability, and leakage controls.
- Decision/reporting assets keep output understandable inside Tablex.

## Deferred Scope

- Full asset search/ranking UI.
- Asset version diffing and promotion workflows.
- Automatic Skill execution.
- Import/export of organization asset packs.

## Validation

- Integration tests cover seed pack names and ResearchPlan recommendation output.
- Full checks should run through ruff, mypy, pytest, frontend lint/build, and Docker smoke before commit.
