---
id: modeling
title: Modeling and diagnostics
description: How Tablex presents model runs, diagnostics, notebooks, and deeper feature engineering.
---

# Modeling and diagnostics

The Leaderboard is the promotion surface for prediction-ready model candidates. A row appears only after its downloadable pipeline passes an isolated prediction smoke test, starts its training entrypoint in the same isolated dependency environment, matches the run's primary metric at numerical precision, and includes the manifest, training and prediction entrypoints, dependencies, and local usage instructions. Score-only runs remain in experiment history until that contract is complete.

Every Leaderboard row can be used for prediction from the UI and downloaded as a self-contained local pipeline bundle. The displayed score, model implementation, and exported bundle therefore stay one versioned deliverable rather than three unrelated claims.

![Leaderboard comparing model scores, evaluation quality, diagnostics, and prediction readiness](/img/screenshots/leaderboard-model-evidence.png)

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
