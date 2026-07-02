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

- Keep Skill, Idea, Insight, Evidence, Report, and Artifact registration as sidecar services available to Codex rather than a pre-run bottleneck.
- Continue migrating legacy `continue_autonomous_session` and `run_planned_agent_task_codex` surfaces away from being the main Full Auto execution model. They may remain as compatibility or child-worker mechanisms, but not as the primary autonomous thread.

## Implemented In This Pass

- Added `AgentSession` as the first-class record for the main autonomous Codex thread.
- Added `AgentTranscriptEvent` as the ordered raw transcript store.
- Changed Full Auto + Codex runner start to create/resume a main `AgentSession`; the `start_autonomous_loop` Job is now only a control/audit record for this path.
- Added an AgentSession supervisor that writes `.tablex/context.json` and `.tablex/GOAL.md`, launches `codex exec --json`, stores Codex stdout JSONL directly as transcript events, records stderr separately, and registers workspace outputs as artifacts.
- Added `/api/projects/{project_id}/agent-session/current` and `/api/projects/{project_id}/agent-session/transcript`.
- Changed Agent Activity recovery so Full Auto ON + no session creates a main AgentSession instead of reviving the legacy continuation-job chain.
- Changed Agent Chat so user messages are appended as `user_instruction` transcript events for the active main AgentSession.
- Changed the Home Raw view to prefer AgentSession transcript events; Job-derived records are sidecar fallback, not the primary Raw surface.
