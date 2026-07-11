---
id: common-issues
title: Common issues
description: Fix common Tablex issues around upload, Full Auto, notebooks, prediction, and documentation.
---

# Common issues

## Tablex opens, but Codex features do not work

A healthy web page is not enough for Full Auto. Check the host companion and Codex runtime:

```bash
scripts/tablex setup
```

If authentication fails, run `codex login --device-auth`. If the sandbox check fails on Linux, install the official Codex bubblewrap/AppArmor prerequisites; do not disable the host restriction globally. Then run `scripts/tablex up`. Use `scripts/tablex status` and `scripts/tablex logs` for runtime state. `OPENAI_API_KEY` is not required for the default Codex path.

On Ubuntu 24.04, install and load the distribution-provided bubblewrap profile, then rerun the model-free check:

```bash
sudo apt-get update
sudo apt-get install -y apparmor-profiles apparmor-utils bubblewrap
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
scripts/tablex setup
```

For other Linux distributions, follow the [official Codex sandbox prerequisites](https://learn.chatgpt.com/docs/sandboxing).

## Data upload appears stuck

Large relational datasets can take time to profile. Check Home and Data for import progress. If the activity remains for a long time after downstream outputs exist, refresh the project and inspect Jobs.

## The target cannot be selected

The target may be intentionally deferred, the primary table may not be set, or the objective may need to be expressed as natural language. Do not force a target when the project needs derived targets, clustering, anomaly detection, or aggregation first.

## Full Auto stopped

If the project says it is waiting for input, read the latest Agent Chat message. It should explain what is complete and give examples of next actions such as test prediction, deeper feature engineering, evaluation approval, or pilot outcomes.

## A marimo notebook does not open

A native marimo notebook can fail if the source has errors, dependencies are missing, or the session needs restarting. The failure should be visible. Ask the agent to repair the notebook source rather than relying on a static fallback.

## Leaderboard results are provisional

Provisional results mean the run was useful for exploration but not yet tied to an approved evaluation contract. Open Evaluation to review or approve the metric and split.

## Prediction fails

Check whether the input satisfies the pipeline contract. Missing tables, target columns, unsupported dtypes, or mismatched categorical preprocessing can all break prediction. The failure should be sent back to the agent for repair or clarification.

## An asset exists but is hard to find

Use Assets for the full inventory. For normal reading, prefer contextual links from Home, Insight, Data, Leaderboard, and Notebooks.
