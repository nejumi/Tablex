---
id: assets-notebooks
title: Assets, reports, and notebooks
description: Understand where Tablex stores outputs and how to read notebooks, reports, and artifacts.
---

# Assets, reports, and notebooks

Tablex stores outputs as assets so they can be opened from the context where they matter: Data, Insight, Leaderboard, Home, or the Assets inventory.

## Assets

Assets are the canonical inventory. They include uploaded data, profiles, reports, notebooks, model results, prediction pipelines, figures, manifests, and validation outputs.

Use Assets when you need to search or audit everything that exists. Use the contextual links on Home, Insight, Data, or Leaderboard when you already know what you are trying to read.

## Reports

Reports should be human-readable. They are best for decisions, summaries, source-backed research, model comparison narratives, and final project handoffs.

## Native marimo notebooks

Notebook source is the artifact of record. Tablex opens native marimo notebooks in-product so the analysis remains executable and reusable by both humans and agents.

![A native marimo report running inside the Tablex notebook workspace](/img/screenshots/native-marimo-report.png)

If a notebook fails, Tablex should show the failure and let the agent repair the source. A static HTML fallback should not hide notebook errors.

## Screenshots and figures

Figures inside notebooks help human readers understand distributions, errors, feature behavior, and model diagnostics. Screenshots in this documentation use the public Home Credit demo so the product workflow can be shown without exposing private project data.
