# 0116 Codex Sidecar Architecture Goal

## Context

The Full Auto power button exposed a core architecture problem: Tablex was doing too much synchronous harness work before Codex/AgentRunner execution could visibly begin. That created database locks, long request waits, opaque failures, and UX that felt worse than using Codex directly.

## Product Principle

Tablex must not become a brittle AutoML-style gate in front of Codex. Codex should receive the project goal, data context, artifacts, skills, evaluation constraints, and available tools as directly as possible. The harness should operate as a sidecar: it stores assets, tracks lineage, protects credentials and evaluation integrity, supplies reusable knowledge, and translates runner activity into a human-facing interface.

## Implementation Direction

- Start/control APIs should acknowledge quickly and never wait for an entire data science loop to finish.
- Long-running EDA, modeling, notebook authoring, report generation, and agent execution should run in background jobs or workers with visible activity.
- Raw Agent Workspace should show the runner transcript as the primary record, with harness sidecar events interleaved but clearly labeled.
- Chat should explain Codex activity to humans; it should not replace Codex with fixed harness-generated ticket text.
- Harness workflow steps should be light guidance and state organization, not hard gates, except for real safety, credential, production-write, or evaluation-integrity constraints.

## Current Follow-up

- Replace remaining synchronous agent-control paths with worker-backed execution.
- Stream or poll runner transcript and job progress into Agent Workspace.
- Keep Skill, Idea, Insight, Evidence, Report, and Artifact registration as sidecar services available to Codex rather than a pre-run bottleneck.
