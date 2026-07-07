# Agent Interface Spec

This document defines the intended Tablex agent experience. It is a product contract, not an implementation note.

## Core Contract

Tablex runs alongside Codex. It supplies project context, artifacts, Skills, lineage, evaluation constraints, data access, safety boundaries, and a human interface. It must not replace Codex reasoning with brittle harness logic or put artificial steps in Codex's path.

Full Auto means one continuing main Codex session. Jobs may exist for support work such as model training, split generation, notebook rendering, artifact ingestion, or credential-safe downloads, but the main autonomous reasoning thread is not a chain of small tickets.

## Raw

Raw is the execution transcript surface. It should feel like watching Codex CLI:

- Codex messages, tool calls, command execution, code edits, errors, and token usage appear in order.
- Harness events may be interleaved only when they are sidecar records, clearly labeled as harness records.
- Raw must not be reconstructed from old Job summaries when a real `AgentSession` transcript exists.
- Stopping and restarting the power button must not erase the transcript.

## Chat

Chat is the human-facing accountability surface. It is not a filtered Raw stream.

Chat entries may come from:

- the user;
- a main Codex-authored progress report written as an artifact such as `reports/chat_update.md`;
- an explicit lightweight sidecar explanation request such as `/btw`;
- an error or availability boundary that Tablex can state factually.

Tablex must not build Chat by keyword-matching natural language, extracting random Raw fragments, or returning ticket text. When a human asks what is happening, Codex should explain project state, recent progress, uncertainty, blocked or unblocked work, and the next useful action in the user's language.

Chat submission must not be a long synchronous HTTP gate. The API acknowledges the user turn, persists any instruction for the main session, queues response composition work, and lets a worker save the Codex-authored response artifact. The UI may show a transient pending bubble, but it must not persist that pending copy as the final answer.

Fixed UI copy is acceptable for labels, buttons, timestamps, process state, validation errors, and file or artifact metadata. Fixed analytical prose, hypotheses, findings, notebook narrative, model interpretation, and conversational responses are not acceptable substitutes for Codex-authored content.

## Full Auto Loop

When the power button is ON:

- Tablex creates or resumes a persistent main `AgentSession`.
- The session receives the current goal, project context, artifact index, equipped Skills, locale, model preferences, and safety/evaluation boundaries.
- Backend startup must scan active Full Auto projects and resume their main sessions without relying on an open browser or `/agent-activity` polling.
- Supervisor recovery must treat unmonitored runner PIDs as stale, preserve the transcript, and resume the same session rather than leaving work suspended.
- Runner failures must use visible retry state and bounded backoff instead of hot-looping.
- User chat instructions sent while Codex is busy must be persisted and delivered to the next main-session turn by event index, not by a small recent-log window.
- If Codex returns control while Full Auto remains ON, Tablex should resume the same session with updated context instead of silently stopping.
- The only normal stop is the user turning power OFF. Hard safety boundaries and Codex's explicit last-resort Give Up state are exceptions.
- Approval prompts in Full Auto are timed intervention windows. If the user does not answer before the countdown expires, Tablex records the provisional assumption and Codex continues.

The runner must be able to keep working through data understanding, objective framing, research, evaluation design, modeling, error analysis, improvement ideas, reporting, and notebook authoring without waiting for harness-only pseudo-blockers.

## Research Plan

Research Plan is a flexible living plan, not a fixed linear recipe.

Initial anchors are:

- data upload;
- objective or task framing;
- data understanding;
- prior-knowledge research.

After those anchors, Codex may add, remove, reorder, branch, or refine plan blocks. A block is complete only when the relevant artifact-backed output exists or Codex explicitly records that no useful output is needed. Creating a brief, context pack, or Skill reference is preparation, not completion.

## marimo

marimo notebooks are first-class Tablex assets.

- Notebook source must be authored by Codex or another AgentRunner, not by backend templates.
- Tablex may create authoring briefs, validate source, start native marimo sessions, store figures and supporting artifacts, and register lineage.
- The native marimo source is the notebook artifact of record. Static HTML snapshots are not notebook evidence and must not be used as a fallback that hides notebook/runtime failures.
- Native marimo notebooks should open in-product from Chat, Data, Leaderboard, Assets, ResearchPlan, and related model/run views.
- Notebook language follows the user's locale because notebooks are both model context and human-facing reports.

## Skills And Research

Skills are equipment for Codex, not fixed recipes. Prior-knowledge research is complete only when Codex returns source-backed findings, a synthesis notebook/report, a reusable Skill, or an explicit no-finding decision.

Kaggle, arXiv, web, and domain research should be stored as Evidence/Insight/Report/Skill assets when used. The harness may manage safe download/probe plumbing, but interpretation belongs to Codex.

## Pilot Phase

Pilot Phase is a forward observation loop layered on top of a registered prediction pipeline.

- Tablex may start a pilot deployment for a registered `prediction_pipeline` artifact, run prediction batches, ingest outcome batches, join by declared keys, and compute fixed metrics from prediction/outcome pairs.
- When a pipeline declares history requirements, Tablex passes the registered history artifact to `predict.py`; feature construction such as lags or rolling windows remains inside the prediction pipeline.
- Tablex records the scoring result as a `pilot_scoring_report` artifact and stores lineage to the prediction batch, outcome batch, and deployment context.
- Tablex does not interpret validation drift, target mismatch, leakage, or model failure causes in harness code. It notifies the main Codex session that a scoring report is available.
- Codex is responsible for registering a `validation_scheme_audit` through the Pilot request protocol, including the verdict, gap decomposition, hypotheses, and next iteration focus.
- When Full Auto is ON, pilot observations should flow back into the same continuing main session so Codex can update Research Plan and continue the data understanding, research, modeling, and reporting loop without being split into a separate ticket.

## Observability

At all times, users should know whose turn it is:

- Codex working: Raw is moving or a live process is observed; Chat should receive periodic Codex-authored progress reports.
- User input expected: the input field is visually emphasized and the pending question or intervention window is visible.
- Between turns but Full Auto ON: Tablex shows that the supervisor is resuming the same session, not pretending work is happening.
- Stopped: power OFF is explicit and all active worker cards either disappear or show a cancelable terminal state.

No UI surface should leave the user with "something happened, then nothing changed" as the visible result.
