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

Persisted Chat turns are immutable records of what was known and linked when the turn was created. History reads must not attach current notebooks, runs, research, or navigation actions to an older turn that did not reference them. A newly registered output gets its own factual registration turn, or is linked from a Codex-authored turn that explicitly names that output.

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
- Power OFF is an execution boundary, not a display preference. Tablex must stop the main Codex process tree, cancel queued and running token-consuming jobs, prevent restart recovery from re-queuing them, and reject new Agent Chat work until the user explicitly turns power on again. A worker finishing after cancellation must not overwrite the cancelled state.
- Project deletion first applies the same power boundary, then verifies Codex, child compute, marimo, and project artifact cleanup. It must not report `deleted=true` or remove the project metadata when active execution or artifact deletion cannot be verified.

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

Research must preserve its provenance boundary. When the runner has internet access or registered local source packs, Codex should return source-backed findings with citations or artifact-backed source references. When the runner has no internet access and no registered sources for the topic, Codex may still use its internal prior knowledge to propose hypotheses, known patterns, or search directions, but those outputs must be labeled as non-source-backed prior knowledge rather than Evidence. Offline prior knowledge can guide analysis and Skill selection; it does not by itself complete a source-backed research plan block unless Codex explicitly records that no source-backed research is needed for the current project.

## Compute Resources

- Compute choice is agent judgment informed by observed facts, not a fixed GPU-first workflow. The context pack should expose CPU, memory, visible accelerators, compute capability, driver limits, installed libraries, and real library probes without prescribing a model family.
- A structured compute request may ask for `cpu`, `gpu`, or `auto` and must declare its fallback policy. Tablex executes the requested script without a shell, records requested, selected, and agent-reported actual device, stores resource/log/output evidence, and links that evidence to any resulting ExperimentRun.
- Child compute uses a durable execution ID. Worker or executor restart must reattach to that execution or restart it with a bounded attempt count rather than silently losing it or starting duplicates. While child compute is active, the main Codex session returns control instead of polling; Tablex resumes the same session with the terminal acknowledgement and registered artifacts.
- GPU visibility alone is not GPU readiness. Each supported library is available only after its minimal probe succeeds in the current runtime. A failed probe is a factual capability observation; it does not prevent Codex from choosing another compatible library or CPU.
- The isolated compute executor has no Codex authentication, project connector credentials, metadata database, or external network. CPU fallback must remain usable on hosts without accelerators. Hosted deployments may replace the local executor with leased compute while preserving the same request, evidence, artifact, and lineage contracts.

## Prediction And Operations

Prediction starts from a registered model or pipeline, not from a separate AutoML-style workflow.

- The primary user entrypoint is the relevant Leaderboard/model surface. A user should be able to choose a model, inspect its input contract, run a test prediction, start pilot validation, and request or download a local pipeline bundle without searching across tabs. Predict opens a visible focused workspace at the point of action; it must not silently render a panel outside the current viewport.
- Leaderboard membership is a prediction-enablement contract, not a synonym for either a successful experiment or a complete local distribution. Every promoted run must link a model-specific runtime that preserves fitted state, feature construction, preprocessing, dependency and input contracts, accepts target-free raw input, and passes the same isolated smoke invocation used by UI prediction. A score-only run remains visible in experiment history until this runtime is ready. Missing export files must not hide an otherwise prediction-enabled candidate or block scientific iteration.
- Export-ready is a separate, user-triggered promotion. A complete local bundle adds the training entrypoint, usage documentation, dependency lock/requirements, self-test material, and claim/replay evidence needed for local training and prediction. The model menu starts this work asynchronously for the selected run. UI prediction and export must share the same canonical inference implementation.
- A `prediction_pipeline` must be self-contained enough for Tablex to run a fixed smoke test using the same invocation shape as real prediction. If the pipeline declares multiple required tables, the self-test must use an input directory with fixtures for those tables.
- Multi-table input integrity has two separate meanings. Feature-bearing table files are required at prediction time unless a separately smoke-tested and evidence-linked omission policy is declared; entity-level history coverage may naturally be partial. Before invoking the model, Tablex records a `prediction_input_integrity.v1` artifact with join-key coverage, row-density, and deliberately declared monitored-column facts for the actual batch.
- Prediction is owned by the continuing main Codex session rather than invoked as an unobserved Python job. The UI creates a waiting prediction operation and a `prediction_context_pack.v1` with the selected pipeline, actual input artifacts, model/run/evaluation lineage, prediction purpose, and available evidence. Codex inspects the real inputs and decides which validation is material before issuing the schema-validated `execute_prediction` command. Tablex then executes the canonical pipeline as a child capability and returns the actual output plus factual runtime/artifact context to the same session.
- Existing project tables with matching fixed table identifiers may be structurally revalidated and offered immediately. This discovery must not synchronously rescan large registered tables, wait for every relationship input before enabling the operation, silently synthesize absent tables as all-null, or decide whether partial coverage is analytically acceptable. The context pack records declared, provided, and missing required tables for Codex to interpret.
- A successful process exit does not make a prediction Ready. Codex may inspect input/output distributions against local validation or OOF evidence, temporal or relational coverage, business semantics, or any other project-specific signal; these are suggested reasoning tools rather than a fixed harness checklist. Codex may investigate, repair, and rerun before issuing `complete_prediction_review` with a supported `trustworthy`, `usable_with_caveats`, or `rejected` judgment. Only then does the UI expose the result as reviewed. The harness blocks only factual integrity failures such as a missing required file/key, forbidden target input, or an unvalidated silent fallback. Low or zero relationship coverage is surfaced as evidence for Codex rather than treated as a universal failure.
- Prediction inputs are not evaluation datasets by default. They are operational inputs for test prediction, benchmark submission, or pilot validation, and should be recorded with their own batch kind and lineage.
- Tablex may validate file formats, declared columns, forbidden columns, declared tables, row counts, command exit status, and artifact lineage. It must not infer why a prediction failed from stderr text. Failures should be shown as factual runtime state and returned to the continuing main Codex session for repair.
- If Full Auto is ON, user-triggered prediction failures, new pilot outcomes, and operational observations should wake the same main session when it is completed or waiting. Power OFF remains authoritative and must not be bypassed.
- The durable operational context is the pipeline version lineage, evaluation contract reference, input contract, prediction/outcome batch ledger, and Codex-authored decision record. A leaderboard run alone is not enough to describe operations.
- Validated experiment candidates should register an `experiment_evidence.v1` artifact linking the hypothesis, parent run, concrete change set, approved SplitManifest, fold metrics, OOF predictions, Codex-authored learning verdict, and next decision. The harness validates references, OOF row/fold integrity, full labeled-row coverage, frozen DatasetSnapshot labels, and metric replay. It does not judge whether the hypothesis is insightful. Exploratory runs remain visible when this evidence is absent and are labeled accordingly.
- Version changes, repair versions, challenger runs, promotion, rollback, and production handoff should be recorded as lineage and human-approved state transitions. Tablex should not silently replace a user's operational model.
- Production serving is not the core Tablex boundary. Tablex may support batch scoring, pilot validation, approved promotion or rollback records, and exportable pipeline bundles, but production handoff should remain explicit and human-approved.

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
