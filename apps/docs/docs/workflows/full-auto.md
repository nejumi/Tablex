---
id: full-auto
title: Full Auto workflow
description: How Full Auto runs, when it stops, and how to give instructions.
---

# Full Auto workflow

Full Auto lets the agent continue a project from the current state. It is useful when you want Tablex to move from data understanding through evaluation, modeling, notebooks, and reports without prompting for every small step.

## What happens when Full Auto starts

The agent receives the project context, data manifest, equipped Skills, artifact references, evaluation state, and safety boundaries. It can inspect files, write notebooks and reports, submit structured requests, and react to validation errors.

## Giving instructions

Use Agent Chat for normal instructions. If the main agent is running, Tablex should deliver the instruction to that session and record the answer when it returns.

Use Codex Console when you need to talk to the execution session more directly or inspect raw execution.

## When Full Auto should pause

Full Auto should pause when the useful local work is complete and human input or new data is needed.

Examples:

- test data is needed for prediction,
- outcomes are needed for pilot validation,
- evaluation assumptions need approval,
- the user needs to choose between modeling directions,
- the agent has produced the agreed deliverables.

When it pauses, Chat should say what is complete and give examples of useful next instructions.

## What not to expect

Full Auto is not a fixed AutoML wizard. It should not force a target at upload time, assume a modeling objective from a column name, or hide uncertainty behind a polished score.
