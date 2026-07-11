---
id: quickstart
title: Quickstart
description: Start a Tablex project, upload data, run Full Auto, and review the first useful outputs.
---

# Quickstart

This guide walks through the first successful Tablex project. The goal is not to force a modeling workflow too early; it is to get data, objective, evaluation, and human-readable outputs into one project.

## 0. Start the complete runtime

Install and authenticate the latest Codex CLI on the host, then use the Tablex launcher:

```bash
codex login --device-auth  # only when needed
scripts/tablex up
```

The launcher reuses host Codex authentication, creates its managed companion runtime on first use, and checks authentication plus local sandbox support before Docker starts. Host `pip` and `python3-venv` are not required; the launcher bootstraps the companion runtime from a digest-pinned official uv image. Open `http://localhost:8080`. Later starts use the same `scripts/tablex up`; stop with `scripts/tablex down`.

## 1. Create a project

Open Tablex and create a project from the portal. Use a short name that describes the dataset or business question.

## 2. Upload data

You can upload a single table or a bundle of related tables. A primary table is optional at upload time. Leave it unset when the prediction row grain, derived table, target, or task type should be decided after data understanding.

For large datasets, keep the page open and watch the import status. Tablex profiles tables in the background and keeps the status visible on Home and Data.

## 3. Set or defer the objective

If the target is obvious, set it in Data. If not, describe the goal in natural language and let the agent inspect the data first.

Examples:

- Predict customer churn next month.
- Find anomalous transactions for review.
- Cluster products by purchasing behavior.
- Build an applicant-level risk model from multiple history tables.

## 4. Start Full Auto

Full Auto starts a continuing agent session. The agent can inspect data, author notebooks, register research findings, propose evaluation, train models, and submit artifacts through Tablex validation.

Home shows the current state. Codex Console preserves the execution transcript. Agent Chat is the human-facing explanation surface.

## 5. Review the first outputs

After the first pass, open:

- Data notebooks for data understanding.
- Insight reports for source-backed conclusions and summaries.
- Evaluation candidates for metric and split assumptions.
- Leaderboard rows for model comparisons and evidence.
- Assets when you need the full inventory.

## 6. Decide the next step

Common next steps are:

- approve or revise the evaluation split,
- ask for deeper feature engineering,
- run test prediction on target-free input,
- add outcome data for pilot validation,
- request a better report or notebook.
