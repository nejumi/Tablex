# 0121 Fable Audit Request: Current Tablex State And Remaining Product Gaps

Date: 2026-07-08

This is a request for an external audit of the current Tablex codebase and product behavior after the 0119/0120 implementation cycle.

Fable can read the repository directly. Please still use this note as the human/product framing, because the highest-risk issues are not only code correctness but whether the product now behaves like the intended Codex-sidecar workbench.

## Source Documents To Read First

- `AGENTS.md`
- `docs/agent_interface_spec.md`
- `README.md`
- `docs/exec-plans/0119_target_product_gap_closure_directive.md`
- `docs/exec-plans/0120_audit_response_directive.md`
- `docs/evidence/0120_verification.md`
- `docs/evidence/0120_e2e_run.md`

Useful recent commits:

- `d5984e4 Update README for current Tablex workflow`
- `f378584 Checkpoint full-auto harness and notebook workflow`
- Earlier visible sequence includes ResearchPlan substrate, notebook link repair, chat dedupe, primary-free upload, pipeline/pilot plumbing, and native marimo changes.

## Product Philosophy To Audit Against

Tablex is a tabular-first prediction meta-harness / agentic data science workbench around Codex or another `AgentRunner`.

The core product rule is that Tablex must run alongside Codex, not replace Codex reasoning:

- Codex should remain the autonomous reasoning and analysis body.
- Tablex should provide data access, artifacts, lineage, evaluation contracts, Skills, tool protocols, memory, UI, and safety/evaluation boundaries.
- Tablex should validate fixed-format submissions, not infer analytical meaning with brittle natural-language, column-name, or workflow heuristics.
- Full Auto should be a continuing main agent session, not a chain of tiny Codex jobs.
- Raw should be the real runner transcript.
- Chat should be human-facing accountability, not a filtered Raw log or maker-facing implementation commentary.
- Native marimo Python source is the notebook artifact of record. Static HTML snapshots must not be used as notebook evidence or fallback.
- Research Plan state and current work should come from Codex-authored plan artifacts or schema-validated ResearchPlan tool requests, not process presence or frontend inference.

## User-Visible Concerns That Still Motivate This Audit

### 1. Asset management is still hard to understand

From the user perspective, it is still not obvious where "assets" live or how to find the right generated output.

Please audit:

- Whether `Assets` clearly means project artifacts, library assets, reports, notebooks, model outputs, pipelines, pilot artifacts, and supporting records, or whether those concepts are still mixed in a confusing way.
- Whether a user can start from Chat, Research Plan, Data, Leaderboard, or Notebooks and reliably open the same relevant artifact without hunting.
- Whether asset discovery is centered around human tasks, such as "read the data understanding notebook", "open model diagnostics", "download pipeline", "inspect research report", instead of internal artifact types.
- Whether `Assets` hides important generated outputs as "supporting" records or buries them behind technical names.
- Whether there should be a clearer asset center, evidence graph, or context-specific "related outputs" drawer.

Specific suspicion: the code now has many links and backfills, but the user's mental model may still be broken.

### 2. marimo is too slow and error-prone

marimo is intended to be a first-class Tablex asset because it is both rich human-readable analysis and reusable Python text for Codex context. In practice, the user has repeatedly seen:

- very slow native marimo startup;
- runtime errors in notebooks;
- source errors such as repeated variable definitions;
- dynamic asset loading failures like missing `run-page-*.js`;
- Leaderboard notebook links opening the wrong notebook;
- notebooks being buried in a collapsed list instead of opened directly from the relevant context;
- cases where Codex appears to model or analyze but no useful marimo notebook is registered.

Please audit:

- `apps/backend/tabular_harness/services/marimo_sessions.py`
- native marimo proxy endpoints and session lifecycle;
- stale marimo session behavior and process cleanup;
- whether frontend iframe/proxy URLs can point to stale dynamic assets;
- whether restart behavior is sufficient or only a band-aid;
- whether native marimo can be prewarmed or reused safely;
- whether notebooks run with stable cwd and `.tablex/data` access;
- whether source validation catches common marimo issues before users open the notebook;
- whether runtime failure is surfaced clearly and routed back to Codex for repair;
- whether the current "native marimo only" contract is implemented without hiding failures.

Important: do not recommend static HTML fallback as a solution. Static HTML snapshots were explicitly rejected because they hide the failure mode and defeat the marimo-first product choice.

### 3. Codex does not always create the required notebook or report

Even after request protocols and quality checks, the user still suspects that Codex can finish modeling or data understanding without producing the expected human-readable marimo notebook or rich report.

Please audit:

- Whether data understanding, prior research, model diagnostics, leaderboard model comparison, pipeline registration, and pilot scoring have clear required deliverables that Codex can submit through fixed-format tools.
- Whether missing deliverables are returned to Codex as structured, non-blocking correction requests without pretending the work is complete.
- Whether the Research Plan can mark a node complete when the human-facing notebook/report is missing.
- Whether a registered notebook is linked to DatasetSnapshot, ExperimentRun, ModelVersion, Research Plan node, Chat, Data, Leaderboard, and Assets consistently.
- Whether notebook quality checks enforce figures/interactive visuals where appropriate without turning into brittle template prose or harness-authored analysis.
- Whether reports can contain images, tables, media, and source-backed evidence as rich Codex-authored Markdown, not just JSON pretty-printing.

### 4. Research Plan may still desynchronize from real work

The tool substrate is supposed to prevent inconsistent states such as "data understanding still current while models are already on the leaderboard" or "future blocks complete before earlier deliverables exist".

Please audit:

- Whether the active ResearchPlan revision is the only displayed plan source.
- Whether frontend heuristics or process presence still infer plan state.
- Whether `set_current_work`, `commit_revision`, and `attach_artifact` enforce enough structure without constraining Codex's analytical freedom.
- Whether completed/open nodes are immutable enough to prevent accidental deletion or skip inconsistencies.
- Whether the granularity of plan nodes is appropriate: not too fine-grained as pseudo-subtasks, but not so coarse that deliverables disappear.
- Whether current work should support multiple concurrent strands or subtask expansion for child agents without breaking the main left-to-right user story.

### 5. Chat and Activity still risk broken-record behavior

The user has seen repeated Chat messages such as the same model-result notice or repeated "same session resumed" language. Some status messages have exposed implementation details.

Please audit:

- Whether model registration success/failure notices dedupe across long sessions and after history compaction.
- Whether progress nudges ask Codex for useful accountability without causing repeated identical reports.
- Whether a completed project keeps burning tokens by repeatedly checking there is nothing to do.
- Whether Full Auto should stop/pause itself and ask for test data, outcome data, or user instruction after all reversible work is exhausted.
- Whether Chat messages avoid internal terms and explain the situation as a user would expect.
- Whether Activity distinguishes live work, scheduled continuation, completed work, waiting for user input, and stopped state clearly.
- Whether stale activity rows and old upload jobs can remain visible after the real work has moved on.

### 6. Data upload and task/objective definition must stay flexible

The product must not regress into 2010s AutoML where upload requires a primary table and a single target column. It must support:

- primary table deferred until data understanding;
- derived primary tables;
- derived targets;
- multiple targets;
- clustering / anomaly detection / forecasting / inverse optimization / exploratory analysis;
- natural-language objective text;
- no target when appropriate.

Please audit:

- Whether primary-free upload is truly supported in UI, API, worker, and Full Auto.
- Whether `TaskSpec` is now first-class enough, or whether legacy `Project.target_column` still dominates.
- Whether target/objective input is robust across input order, browser refresh/back, primary-table save before target save, clearing value, and repeated save.
- Whether generated placeholder columns such as `column0` are fully removed from suggestions for both new and existing uploaded data.
- Whether upload progress for large files is visible enough on Home and Data, and whether stale import jobs are cleared without deleting useful history.
- Whether column-name or statistical heuristics still nudge target/task inference in user-facing UI.

### 7. Leaderboard, model diagnostics, pipelines, and pilot loop

The product needs more than a metric table:

- model rows should explain what the model is;
- leaderboard evidence should open the right model-diagnostics notebook, not a generic data-understanding notebook;
- each model should be downloadable as a prediction pipeline bundle when available;
- test/inference data prediction is essential;
- pilot scoring and validation audit should feed back into the same Full Auto session.

Please audit:

- Whether Leaderboard API and UI use `model_description`, `features_used`, human labels, and useful metrics instead of internal IDs.
- Whether related notebook ordering prefers model diagnostics for model rows.
- Whether pipeline bundle download works and is easy to find.
- Whether prediction batch and outcome batch flows work from the UI, not just tests.
- Whether pilot observations wake a completed Full Auto session without restarting stopped sessions.
- Whether feature importance, permutation importance, PDP, and SHAP-style diagnostic artifacts are supported and visible when available.
- Whether model diagnostics notebook/report generation is required after leaderboard registration or can still be skipped.

### 8. Prior-knowledge research and rich research reports

Prior research should not be a placeholder. It should search or inspect real sources when enabled, then store source-backed findings and a readable report.

Please audit:

- Whether Codex actually has network/web-search capability in main sessions when policy allows it.
- Whether `register_research_findings` and rich Markdown report registration are implemented cleanly.
- Whether source-backed findings are linked to Evidence, Reports, ResearchPlan nodes, Chat, and Assets.
- Whether "no useful findings" is explicit rather than silently marking prior research done.
- Whether external claims are stored with enough provenance for later reuse.

### 9. Performance and operational reliability

The user has seen UI not loading, SQLite locks, slow GET endpoints, stale activity, huge data directories, and marimo slowness.

Please audit:

- Whether GET endpoints are now read-only and fast enough.
- Whether chat history, runs, leaderboard, notebook index, assets, and activity endpoints avoid expensive write reconciliation on read.
- Whether polling intervals and timeout behavior are appropriate.
- Whether native marimo process cleanup is safe and avoids orphaned/stale sessions.
- Whether upload/profile jobs for large data are cancellable, observable, and cannot deadlock a project.
- Whether project deletion is robust for large artifact trees and running jobs.
- Whether `data/` growth and artifact duplication are under control.

### 10. Test and evidence coverage may not prove real UX

The verification file reports many passing tests, but the user still sees UX failures. Please distinguish:

- implemented and unit-tested;
- implemented and API-smoke-tested;
- verified in a real browser;
- verified through a true Full Auto E2E with actual Codex, large data, notebooks, leaderboard, pipeline, and pilot loop.

Please audit `docs/evidence/` and identify which claims are genuinely supported by real evidence and which remain mostly unit-test-level.

## Specific Questions For Fable

1. What are the top 10 remaining gaps between the intended Tablex philosophy and the current implementation?
2. Which gaps are structural design problems rather than isolated bugs?
3. Does the current asset model/UI make sense to a human user? If not, what should the target information architecture be?
4. Is native marimo currently implemented in a way that can become reliable and fast? What should be changed first?
5. Are there still hidden harness heuristics that infer target, plan state, notebook relevance, or user intent?
6. Are ResearchPlan tools enforcing the right invariants without over-constraining Codex?
7. Are missing deliverables, like model notebooks or pipelines, returned to Codex properly, or can the product present incomplete work as done?
8. Does the Full Auto loop know when to stop, pause, or ask for new data after meaningful work is exhausted?
9. Are Chat/Activity/Raw responsibilities cleanly separated?
10. What should the next implementation directive be, in Workstreams with acceptance criteria?

## Requested Audit Output Format

Please return:

1. Executive summary: whether Tablex is closer to the intended product after 0119/0120, and where it still falls short.
2. Severity-ranked findings, with file/function references where possible.
3. User-facing failure modes: what a user would still experience as broken or confusing.
4. Structural root causes: large files, state-machine conflicts, missing contracts, expensive endpoints, lifecycle issues, etc.
5. Concrete implementation directive: Workstreams I1, I2, ... with:
   - current state;
   - target behavior;
   - implementation instructions;
   - acceptance criteria;
   - tests/evidence to produce.
6. A short "do not do" section to prevent superficial fixes, especially around static notebook fallbacks, harness-authored prose, new heuristic gates, or UI patchwork.

## Current Human Priority

If you must prioritize, focus on this product slice:

> Upload data or resume a project -> Full Auto proceeds through data understanding, research, evaluation, modeling, diagnostics, notebook/report authoring, leaderboard, pipeline, prediction/pilot loop -> the user can always see what happened, open the right asset from the right context, and trust that missing notebooks/reports/pipelines are visible repair targets rather than hidden failures.

