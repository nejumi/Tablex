---
name: tablex-notebook-quality
description: Use when generating or revising Tablex marimo notebooks, EDA reports, model diagnostics, visual analysis, or human-facing prediction workbench narratives. Focuses on high-quality, artifact-backed, evaluation-first analysis rather than fixed modeling recipes.
---

# Tablex Notebook Quality

Use this skill when a Tablex task asks for a notebook, data understanding report, model diagnostics, visualization narrative, or analysis artifact.

## Core Standard

Write for a human analyst first, while preserving harness-owned evaluation boundaries.

- Start with a reader brief: what question the notebook answers and what the user should inspect first.
- Tell a data story: row meaning, target meaning, leakage risk, time/group structure, missingness, and prediction-time availability.
- Keep EvaluationSpec and SplitManifest visible before discussing model lift.
- Use clear section flow: executive read, EDA quality rubric, data shape, target/profile, feature landscape, evaluation guardrails, model diagnostics, failure analysis, next actions.
- Prefer a few high-signal plots with interpretation over many disconnected charts.
- Every important claim should be backed by an artifact, metric, table, plot, or explicit assumption.
- Include a next-analysis queue for Codex or a human: feature importance, permutation importance, partial dependence, calibration, threshold analysis, slice metrics, residual/error review, and prediction examples when relevant.

## Quality Rubric

Make these areas explicit in generated notebooks and reports:

- Data story: row semantics, decision timing, collection process, profile boundary.
- Target-aware EDA: target construction, distribution, imbalance/outliers, missing target values, metric suitability.
- Leakage and availability: post-outcome fields, duplicate rows/entities, prediction-time availability, temporal leakage.
- Evaluation guardrails: random/stratified/time/group scenarios, SplitManifest constraints, unresolved assumptions.
- Feature landscape: numeric, categorical, text, datetime, group/entity, sparse, high-cardinality, and leakage-suspect queues.
- Model diagnostics: feature importance, permutation importance, PDP, calibration, threshold analysis, slice metrics, residual/error review, prediction examples.

If evidence is missing, mark the area as missing/deferred and describe the next artifact or runner work needed. Do not pretend a static scaffold is an executed analysis.

## Avoid

- Do not output raw JSON dumps as the main user experience.
- Do not optimize a metric before explaining whether the metric is appropriate.
- Do not hide uncertainty. Label assumptions, sample boundaries, missing execution, and deferred checks.
- Do not copy external notebook structures blindly. Use public notebook craft as inspiration for narrative, not as fixed recipes.
- Do not require W&B, MLflow, Kaggle, or external dashboards to understand the result.

## Tablex-Specific Requirements

- Never read secrets or connector credentials.
- Never include validation/test targets in feature-generation prompts.
- Do not destructively modify EvaluationSpec or SplitManifest from notebook code.
- Register generated source, HTML preview, report, figure manifest, and execution/capture evidence as artifacts.
- Make notebook outputs useful inside the Tablex UI: concise headings, metric cards, readable tables, charts with captions, and clear next actions.
