---
name: tablex-notebook-quality
description: Use when generating or revising Tablex marimo notebooks, EDA reports, model diagnostics, visual analysis, or human-facing prediction workbench narratives. Focuses on high-quality, artifact-backed, evaluation-first analysis rather than fixed modeling recipes.
---

# Tablex Notebook Quality

Use this skill when a Tablex task asks for a notebook, data understanding report, model diagnostics, visualization narrative, or analysis artifact.

## Core Standard

Write for a human analyst first, while preserving harness-owned evaluation boundaries.

- Do not treat Tablex notebook generation as a fixed template. Use the current `notebook_authoring_brief`, Data Review evidence, project artifacts, and cited public notebook-craft inspirations to decide the narrative on the fly.
- Use public Kaggle Grandmaster-style work as craft inspiration: detailed EDA before modeling, question-driven flow, high-signal visuals, clear storytelling, strong structure, original insight, and transparent next actions. Do not copy public notebook text, code, or section order verbatim.
- Start with a reader brief: what question the notebook answers and what the user should inspect first.
- Tell a data story: row meaning, target meaning, leakage risk, time/group structure, missingness, and prediction-time availability.
- Keep EvaluationSpec and SplitManifest visible before discussing model lift.
- Use clear section flow: executive read, EDA quality rubric, data shape, target/profile, feature landscape, evaluation guardrails, model diagnostics, failure analysis, next actions.
- Prefer a few high-signal plots with interpretation over many disconnected charts.
- Every important claim should be backed by an artifact, metric, table, plot, or explicit assumption.
- Include a next-analysis queue for Codex or a human: permutation importance, native feature importance for tree-based models, partial dependence for the most important features, SHAP inspection when the runtime/model supports it, calibration, threshold analysis, slice metrics, residual/error review, and prediction examples when relevant.

## Quality Rubric

Make these areas explicit in generated notebooks and reports:

- Reader journey: hook, question ladder, evidence, interpretation, caveat, next action.
- Visual quality: a small number of purposeful figures with captions, not a dashboard dump.
- Storytelling: each section should change what the analyst believes or knows.
- Structure: progressive disclosure from verdict to evidence to appendix.
- Insight quality: prioritize findings that alter evaluation, feature strategy, or runner work.
- Originality: adapt to the dataset's actual semantics instead of reusing generic Titanic/Home Credit sections.
- Data story: row semantics, decision timing, collection process, profile boundary.
- Target-aware EDA: target construction, distribution, imbalance/outliers, missing target values, metric suitability.
- Leakage and availability: post-outcome fields, duplicate rows/entities, prediction-time availability, temporal leakage.
- Evaluation guardrails: random/stratified/time/group scenarios, SplitManifest constraints, unresolved assumptions.
- Feature landscape: numeric, categorical, text, datetime, group/entity, sparse, high-cardinality, and leakage-suspect queues.
- Model diagnostics: permutation importance, native feature importance for tree-based models, partial dependence plots for the most important features, SHAP inspection when supported, calibration, threshold analysis, slice metrics, residual/error review, prediction examples.

If evidence is missing, mark the area as missing/deferred and describe the next artifact or runner work needed. Do not pretend a static scaffold is an executed analysis.

## Avoid

- Do not output raw JSON dumps as the main user experience.
- Do not optimize a metric before explaining whether the metric is appropriate.
- Do not hide uncertainty. Label assumptions, sample boundaries, missing execution, and deferred checks.
- Do not copy external notebook structures blindly. Use public notebook craft as inspiration for narrative, not as fixed recipes.
- Do not require W&B, MLflow, Kaggle, or external dashboards to understand the result.
- Do not write a notebook that merely restyles existing Tablex HTML. The runner should add analysis, interpretation, and artifact-backed figures/tables.

## Tablex-Specific Requirements

- Never read secrets or connector credentials.
- Never include validation/test targets in feature-generation prompts.
- Do not destructively modify EvaluationSpec or SplitManifest from notebook code.
- Register the native marimo Python source, report, figure manifest, and execution/capture evidence as artifacts.
- Do not register static HTML as notebook evidence or preview fallback. If native marimo cannot open the source, surface the runtime failure and repair the notebook source.
- Make notebook outputs useful inside the Tablex UI: concise headings, metric cards, readable tables, charts with captions, and clear next actions.
- If `notebook_authoring_brief` is present, read it first. Treat its source cards and sample moves as craft context for Codex, not as deterministic harness sections.
- For `notebook_kind="model_diagnostics"`, register the notebook with `quality_manifest.model_diagnostics.checks`. Cover `permutation_importance`, `native_feature_importance`, `partial_dependence`, and `shap` using the fixed status vocabulary from Tablex. If a check cannot be run yet, say which model artifact, prediction artifact, dependency, or runtime support is missing instead of omitting the check.
