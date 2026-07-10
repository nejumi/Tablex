---
id: workbench
title: Workbench concepts
description: Understand Projects, Full Auto, Agent Chat, Codex Console, Research Plan, and Skills.
---

# Workbench concepts

Tablex is a workbench around an agent. The agent does the reasoning and analysis; Tablex keeps the data, artifacts, evaluation state, safety boundaries, and UI navigation coherent.

## Project

A Project is the container for one prediction or analysis effort. It holds datasets, objectives, evaluation candidates, model results, notebooks, reports, assets, and pilot validation records.

## Full Auto

Full Auto is a continuing agent session. It should feel like one data scientist staying with the project, not a chain of unrelated jobs. Support jobs may train, profile, render, or validate, but the main reasoning context stays with the agent.

## Agent Chat

Agent Chat is for human-facing progress and decisions. It should tell you what changed, what is uncertain, what needs attention, and where to look next.

## Codex Console

Codex Console is the raw execution view. Use it when you need to inspect what the runner actually did. It is not the normal reading surface for project conclusions.

## Research Plan

The Research Plan is the agent's project plan. It should be backed by registered outputs. A completed node should link to evidence, such as a notebook, report, model run, evaluation candidate, or source-backed research finding.

## Skills

Skills are reusable craft knowledge for the agent: EDA approaches, modeling strategies, feature engineering patterns, diagnostic habits, or domain-specific playbooks. A Skill guides the agent; it is not a rigid workflow imposed by the harness.
