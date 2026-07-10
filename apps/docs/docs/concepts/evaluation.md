---
id: evaluation
title: Evaluation
description: Understand provisional results, formal evaluation contracts, EvaluationSpec, and SplitManifest.
---

# Evaluation

Evaluation is the spine of a Tablex project. A model score is useful only when you know what rows were compared, how the split was made, what metric was used, and which leakage risks were controlled.

## Provisional vs formal results

Provisional results are useful for exploration. They may come from an internal cross-validation run created by the agent. Treat them as directional until the evaluation contract is approved.

Formal results are registered against an approved evaluation design. They are the numbers you should use for durable comparison.

## EvaluationSpec

An EvaluationSpec defines the metric and scoring policy. Examples include ROC-AUC for binary classification, MAE for regression, log loss for probability quality, or a domain-specific metric.

## SplitManifest

A SplitManifest defines which rows are train, validation, test, or fold assignments. It matters for leakage control, grouped entities, time-aware validation, and repeatable comparison.

## What to check before trusting a score

- The target is well-defined.
- The split matches the prediction scenario.
- Entities that should not cross folds stay together.
- Future information does not enter training features.
- The metric matches the decision you care about.
- The leaderboard row links to notebooks, diagnostics, or reports.

## Changing evaluation

Do not rewrite an approved evaluation in place. Create a new candidate or version, compare it, and make the reason for the change visible.
