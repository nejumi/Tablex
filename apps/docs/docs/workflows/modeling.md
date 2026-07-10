---
id: modeling
title: Modeling and diagnostics
description: How Tablex presents model runs, diagnostics, notebooks, and deeper feature engineering.
---

# Modeling and diagnostics

The Leaderboard is where model candidates become comparable. A good row should explain not only the score, but also what the model used, why it was tried, what evidence supports it, and what remains missing.

![Leaderboard placeholder](/img/screenshots/leaderboard-placeholder.svg)

## Baselines first

Baselines are sanity floors. They help detect target leakage, broken splits, impossible metrics, or a model that is not learning. Baselines should remain visible even after stronger models appear.

## Feature engineering

Feature engineering should be hypothesis-driven. For relational data, this often means aggregating behavior at the prediction entity, inspecting individual trajectories, and then generalizing micro-level observations into reusable features.

## Diagnostics

Useful diagnostics include:

- feature importance for tree models,
- permutation importance,
- partial dependence or related feature-response plots,
- SHAP-style summaries when feasible,
- slice metrics for important groups,
- calibration and error analysis.

## Model notebooks

A model notebook should stand alone. It should explain the task, evaluation, data used, feature groups, modeling intent, score, diagnostics, limitations, and next experiments.

## Duplicate or unclear model rows

If two leaderboard rows represent the same model and evidence, the agent should avoid submitting both. Tablex may hide duplicate display noise, but the better fix is for the agent to submit clean, versioned results.
