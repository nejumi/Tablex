---
id: prediction-pilot
title: Prediction and pilot validation
description: Run target-free prediction inputs, add outcomes later, and use pilot validation to improve the project.
---

# Prediction and pilot validation

Prediction is where a trained candidate meets new target-free data. Pilot validation is where later outcomes come back and the project learns from the gap between predictions and reality.

![Prediction drawer placeholder](/img/screenshots/prediction-placeholder.svg)

## Test prediction

Open a leaderboard row and choose Predict. Tablex shows the pipeline contract: required columns or required tables, forbidden target columns, and any self-test information supplied by the agent.

Upload or select a target-free prediction input. For multi-table pipelines, provide the tables declared by the pipeline contract.

## When prediction fails

A prediction failure should not be a dead end. Tablex should show the factual failure and feed it back to the agent as an observation so the agent can repair the pipeline, clarify missing inputs, or ask for the correct data shape.

## Pilot validation

Pilot validation starts with a prediction batch. Later, add outcomes with join keys and observed-at information when available. Tablex can score the batch and register a validation audit.

## Production handoff

Tablex is not meant to be a full serving platform at this stage. The practical handoff is a reproducible pipeline bundle, manifest, evaluation contract, and operational notes that another system can run.

## Good pilot questions

- Did the score hold up on later data?
- Which segments are worse than expected?
- Did the input distribution shift?
- Are outcomes delayed or partially missing?
- Should the model be repaired, recalibrated, retrained, or replaced?
