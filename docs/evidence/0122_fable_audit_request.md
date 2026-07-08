# 0122 Fable Audit Request: Modeling-To-Product Gap, Asset IA, Evaluation Scheme, Prediction UX, And Modern Tabular AI

Date: 2026-07-08

This is a request for another comprehensive audit of Tablex after the 0121 implementation cycle.

Fable can read the repository and local evidence directly. Please still use this document as the human/product framing, because the biggest remaining risks are now product coherence, UX, and whether the implemented abstractions support the intended agentic tabular workflow rather than only passing tests.

## Read First

- `AGENTS.md`
- `README.md`
- `docs/agent_interface_spec.md`
- `docs/exec-plans/0119_target_product_gap_closure_directive.md`
- `docs/exec-plans/0120_audit_response_directive.md`
- `docs/exec-plans/0121_audit_response_directive.md`
- `docs/evidence/0121_verification.md`
- `docs/evidence/0121_i1_marimo_reliability.md`
- `docs/evidence/0121_i2_storage_controls.md`
- `docs/evidence/0121_i3_related_outputs_and_assets.md`
- `docs/evidence/0121_i4_deliverable_expectations.md`
- `docs/evidence/0121_i5_chat_activity_quiet.md`
- `docs/evidence/0121_i6_browser_e2e_and_evidence_grades.md`

Recent commits worth inspecting:

- `3079d57 Clarify guidance for unlocked model evaluations`
- `d2b098f Fix default chat response model handling`
- `2f097e2 Stabilize data upload navigation`
- `8a79e06 Warm native marimo notebooks and cache data samples`
- `426caa6 Preserve completed research plan display text`
- `f3adb25 Document live smoke static checks`
- `f4448ac Record live Full Auto research pilot evidence`
- `f3aa970 Add browser golden slice evidence`
- `a9470ad Quiet repeated chat and activity status`
- `e02cf59 Add deliverable expectation ledger`
- `1fdf934 Add artifact preview lineage`
- `340289b Add related output drawers and asset filters`
- `e3e73d4 Add storage usage and artifact GC controls`
- `7e8d60d Improve native marimo session reliability`

## Product Philosophy To Audit Against

Tablex is a tabular-first prediction meta-harness and agentic data science workbench around Codex or another `AgentRunner`.

The intended split is:

- Codex/AgentRunner reasons, analyzes, models, researches, authors notebooks, writes reports, and decides what to try next.
- Tablex owns data access, artifacts, lineage, evaluation contracts, validated tool protocols, safety boundaries, runtime surfaces, memory, and the human interface.
- Tablex must validate fixed-format submissions, not replace Codex reasoning with brittle column-name, natural-language, or workflow heuristics.
- Full Auto should remain a continuing main Codex session.
- Raw should be the real runner transcript.
- Chat should be human accountability, not a filtered Raw log.
- Native marimo Python source is the notebook artifact of record; static HTML fallback is prohibited.
- Research Plan should come from Codex/tool substrate, not frontend inference or process presence.

## Current Human Assessment

The product has improved substantially. Modeling is now "somewhat working": on Home Credit-like projects, Codex can run data understanding, prior research, model comparison, diagnostics, leaderboard registration, notebook registration, and prediction pipeline registration.

However, the user still experiences several major gaps:

1. Asset management feels too complex and scattered.
2. Evaluation scheme handling is unclear.
3. Native marimo still feels extremely slow.
4. Test-data prediction UX is not yet obvious.
5. The modeling loop appears too LightGBM-centric and does not yet reflect the original broader concept: LLM-based feature/row augmentation, tabular foundation models such as TabPFN, and ensemble/model-diversity strategies.

Please audit whether these are implementation bugs, missing product surfaces, or deeper architectural mismatches.

## Focus 1: Asset Management And Information Architecture

The user now suspects that Tablex may not need many scattered "asset-ish" surfaces. A simpler model may be better:

- one canonical asset center showing every notebook, Markdown report, research finding, model output, prediction pipeline, diagnostic artifact, figure, data artifact, and supporting JSON;
- visible type/category tags;
- timestamps;
- source/context links;
- search/filter;
- direct open actions;
- contextual related-output drawers from Chat, Research Plan, Data, Leaderboard, and Notebooks.

Please audit:

- Whether current Assets, Notebooks, Insights/Reports, Leaderboard related outputs, Research Plan evidence, Chat actions, and Data evidence are too fragmented.
- Whether users can answer "where is the data understanding notebook?", "where is the model diagnostics notebook?", "where is the final report?", "where is the prediction pipeline?", and "what did Codex produce?" without hunting.
- Whether `RelatedOutputsDrawer` and asset filters introduced in 0121 are enough, or whether the product still needs a clearer canonical asset list.
- Whether every asset row should show at minimum: human title, type/category tags, created time, source context, linked project stage/model/run, and primary action.
- Whether internal `asset_type` values still leak into human-facing IA.
- Whether "supporting records" are still hiding important objects.
- Whether lineage should remain a one-hop contextual panel or become a stronger browsing model.

Important: do not recommend new tabs casually. Prefer reorganizing current surfaces unless a new surface is clearly justified.

## Focus 2: Evaluation Scheme, User-Controlled Splits, And Formal Comparison

A current confusing state occurred:

- Codex completed internal CV modeling and registered 3 leaderboard runs.
- `ExperimentRun` rows existed.
- But `EvaluationSpec`, `SplitManifest`, and `EvaluationCandidate` were all 0.
- Chat correctly said modeling was done on current data but evaluation was not formally locked.
- The guidance previously repeated "Compare evaluation scenarios", which has now been adjusted to "Review evaluation boundary for existing model results".

Please audit:

- Whether Tablex's intended evaluation hierarchy is clear to a user:
  - provisional Codex internal CV;
  - EvaluationCandidate;
  - approved EvaluationSpec;
  - SplitManifest;
  - comparable ExperimentRun;
  - leaderboard result with formal evaluation evidence.
- Whether a user can specify validation/test split policy before or during Full Auto:
  - random split;
  - stratified split;
  - group split;
  - time split;
  - fixed validation file;
  - explicit fold column;
  - holdout table;
  - rolling/forward validation for time series;
  - custom natural-language evaluation objective that Codex turns into a schema-validated proposal.
- Whether the UI makes it obvious how to provide that split instruction without reducing Tablex to rigid AutoML.
- Whether Codex can propose EvaluationSpec/SplitManifest via tools, and Tablex validates the fixed format without inferring semantics.
- Whether leaderboard rows that lack approved EvaluationSpec/SplitManifest should be visually labeled as "provisional internal validation" rather than appearing equal to formal runs.
- Whether existing runs should be attachable to a later EvaluationSpec, or whether they must be rerun under the approved SplitManifest.
- Whether test data and validation data are distinguished clearly.

Please propose the target evaluation UX, including where this belongs in Home/Data/Evaluation/Leaderboard.

## Focus 3: Native marimo Speed And Reliability

0121 added native marimo reliability work: session restart, source hash checks, max sessions, prewarm, browser smoke evidence, and no static HTML fallback.

The user still feels marimo is far too slow. The desired outcome is not a card preview or static fallback. The desired outcome is that native marimo itself opens quickly enough to feel natural.

Please audit:

- Whether prewarming is actually effective in realistic projects, not just tests.
- Whether prewarming occurs at the right time: immediately after notebook registration, for the most relevant notebook from Chat/Leaderboard/Data, and before the user clicks.
- Whether the marimo process can be kept warm per project/session/notebook safely.
- Whether startup time is dominated by:
  - marimo server boot;
  - notebook Python imports;
  - reading large CSV/parquet files;
  - Plotly/JS asset loading;
  - proxy/WebSocket setup;
  - frontend iframe reloads;
  - repeated cold starts after backend restart.
- Whether `.tablex/cache/dataset_profiles` and `.tablex/cache/dataset_samples` are enough, or whether notebooks need stronger data-access contracts and cached figure/data artifacts.
- Whether notebook authoring guidance should require lazy loading, sampling, cached aggregates, and user-triggered heavy cells.
- Whether generated notebooks are too heavy at top-level and should avoid reading all large data at import time.
- Whether native marimo session health/restart UX is currently clear enough.
- Whether there are still stale `run-page-*.js` or proxy asset failure modes.

Please propose concrete profiling steps and implementation workstreams to make native marimo feel fast without reintroducing static HTML fallback.

## Focus 4: Test Data Prediction UX

Prediction on new/test data is essential. The user references DataRobot's UX:

> Click a leaderboard model, open the prediction tab, drag-and-drop the prediction file, then receive predictions.

Please audit the current Tablex prediction/pilot implementation and propose a better Tablex-native flow.

Questions:

- Should prediction entry points live on each Leaderboard row, a project-level Predictions surface, Data tab, or a drawer?
- Should clicking a model open a "Predict with this model" panel with:
  - expected input schema;
  - required supporting/history tables;
  - target column exclusion warning;
  - drag-and-drop input;
  - column mapping;
  - validation report;
  - run button;
  - downloadable predictions;
  - lineage to model/pipeline/input data?
- How should multi-table prediction work for relational datasets like Home Credit?
- How should pipeline manifests declare required tables, join keys, history windows, and as-of columns?
- How should failed prediction schema validation be shown to users and returned to Codex?
- How should prediction batches connect to pilot outcome ingestion and validation audits?
- How should Tablex distinguish:
  - validation split predictions;
  - external test set predictions;
  - production/pilot prediction batches;
  - benchmark submission files?
- Should there be a single "Predictions" section, or should Predictions be model-contextual inside Leaderboard?

Please propose an ideal UX and the underlying fixed-format protocol.

## Focus 5: Model Diversity, Ensembles, TabPFN, And Tabular Foundation Models

The original product concept was not only "Codex harness around LightGBM." It also included applying modern generative AI and tabular foundation model techniques to tabular data.

Current user observation:

- Runs appear mostly LightGBM-centric.
- Ensembles do not appear prominently.
- TabPFN or other tabular foundation models do not appear to be used.
- There is no obvious systematic model family exploration policy.

Please audit:

- Whether current Skills and prompts over-constrain Codex toward LightGBM.
- Whether Tablex gives Codex enough context/tools to decide when to try:
  - linear/logistic baselines;
  - tree ensembles;
  - gradient boosting;
  - random forests/extra trees;
  - calibrated models;
  - stack/weighted/blended ensembles;
  - TabPFN / TabICL-like tabular foundation models when dataset shape permits;
  - time-series models for temporal tasks;
  - anomaly detection/clustering when no target exists.
- Whether model family choice should be a Codex decision recorded as plan/research artifacts, not a harness rule.
- Whether Tablex should provide optional model-runner capabilities for TabPFN or similar libraries, with resource/shape constraints.
- Whether the leaderboard should show model family, feature sources, training cost, inference cost, and constraints.
- Whether ensembles should be first-class ExperimentRuns/Pipelines or only reports.
- Whether current prediction pipeline registration can package ensembles.

Please propose how to introduce model diversity without violating the "Codex decides, Tablex validates fixed formats" principle.

## Focus 6: LLM-Based Row/Feature Augmentation

The original concept included using LLMs to enrich tabular rows, similar in spirit to RAG query rewriting:

- use row text columns or the whole row;
- prompt an LLM to add useful world-knowledge-informed features or normalized text;
- horizontally expand the row;
- evaluate whether these generated features help;
- preserve leakage boundaries and split discipline.

Please audit whether Tablex currently has any safe substrate for this. If not, propose one.

Important constraints:

- No validation/test targets may be included in augmentation prompts.
- Feature generation must respect SplitManifest; train-fold generation must not leak validation labels.
- For prediction/test data, augmentation must be reproducible and part of the registered prediction pipeline.
- Generated features must be stored as artifacts with prompt/version/model/provenance.
- Cost, privacy, and external model policy must be visible.
- Codex should decide whether augmentation is worth trying; Tablex should validate schemas, lineage, and evaluation boundaries.

Questions:

- Should this be modeled as `FeatureAugmentationRecipe`, `GeneratedFeatureSet`, or part of prediction pipelines?
- How should prompts be authored: by Codex as artifacts, by Skills, or user-provided?
- How should deterministic caching work?
- How should privacy and external API use approvals work?
- How should generated text features be displayed and audited?
- How should Tablex avoid "LLM feature generation" becoming a hidden leakage machine?

## Focus 7: Reports And Research Assets

The user still worries that reports are often not worth reading, hard to find, or not rendered in a rich way.

Please audit:

- Whether Markdown reports are human-readable and directly openable from Chat/Plan/Assets.
- Whether prior research reports can include source-backed tables, images, charts, and media references where appropriate.
- Whether reports are Codex-authored rather than harness-authored prose.
- Whether JSON artifacts are being surfaced as reports by mistake.
- Whether a report has a clear "what to read first" structure without being a fixed template.
- Whether research findings are linked to Evidence/Report/Plan/Chat/Assets.
- Whether figures referenced by reports are displayed inline or easy to open.

## Focus 8: Upload Robustness And Data Flow

The user has repeatedly seen upload/profiling issues:

- upload operation feels heavy;
- progress is not visible enough;
- tab switching or browser refresh can make uploads appear lost;
- projects can appear to lose data;
- primary table/target input order can break flows.

Some fixes were recently made:

- Home D&D upload entry;
- upload draft state lifted above DataTab;
- beforeunload guard during active upload;
- refresh fallback keeps previous datasets/jobs/artifacts;
- stale upload activity cleanup.

Please audit whether these are sufficient.

Questions:

- What state must survive tab switch?
- What state can survive browser refresh, and what cannot because browser `File` objects are gone?
- Is the user warned at the right time?
- After upload reaches server-side staging, is recovery robust?
- Can a user upload first, inspect, then set primary table and target later?
- Can a user change primary table safely?
- Can a user set derived target/task objective instead of column target?
- Are target suggestions free from placeholder columns such as `column0`?
- Are large-file profile jobs cancellable and observable?

## Focus 9: Chat As An Actionable Agent Interface, Raw, And Developer/Project Boundary

Recent confusion:

- A user asked why this external development conversation does not appear in Tablex Raw.
- The correct answer is that Tablex Raw is per-project main AgentSession transcript, not external development Codex.
- Another confusion: Chat reply generated by auxiliary `agent_chat_turn` may not appear in Raw because it is not the main session.
- A more serious failure mode occurred when the user asked: "How exactly was the provisional validation split done?" The Chat answer explained that the user should inspect scripts/notebooks, but did not actually inspect them. From the user's perspective, this is unacceptable: the request was clearly for Tablex/Codex to perform the check and report the result.
- The user expects Chat to be a real operating surface for Codex. If the instruction is answerable from saved project state, Chat should answer directly. If it requires artifact/code inspection, Chat should dispatch or wake the main Codex session, show that it is checking, and return the Codex-authored result. It should not act like a non-executing proxy.
- The user also expects natural-language Chat instructions to be sufficient for evaluation setup, for example "Use ROC-AUC" or "Use a stratified 5-fold split" or "Group by customer id." Codex should turn that into a schema-validated EvaluationSpec/SplitManifest proposal and Tablex should validate fixed fields. Chat should not merely explain that the Evaluation tab exists.

Please audit:

- Whether Tablex communicates this boundary clearly enough.
- Whether Chat responses generated by auxiliary composers should link to their artifact/log for auditability.
- Whether Raw should show user chat instructions delivered to the main session but not auxiliary reply composition.
- Whether the user can distinguish:
  - main Full Auto Codex session;
  - sidecar/auxiliary response composition;
  - local worker jobs;
  - external development Codex outside Tablex.
- Whether Chat should avoid mentioning "Codex CLI exited" or other implementation details in user-facing copy.
- Whether `POST /api/projects/{project_id}/agent-chat` should always route action-bearing user requests to the main session when Full Auto is on, and whether a completed/idle main session should be restarted for user-requested inspection work.
- Whether the current pairing model of `agent_chat_turn` jobs to later `chat_update.md` artifacts is too indirect for "please check and report" interactions.
- Whether Chat needs an explicit "checked by main session" / "answered from saved state only" provenance label that is human-friendly and not implementation jargon.
- Whether natural-language evaluation instructions should produce an evaluation proposal workflow:
  - user says the desired metric/split in Chat;
  - main Codex inspects current data and writes an EvaluationCandidate/EvaluationSpec proposal request;
  - Tablex validates fixed-format fields and evidence;
  - the user can approve or let Full Auto continue under explicit assumptions;
  - the Chat answer reports the resulting concrete split/metric, not just a suggested tab to open.
- Whether Chat should have a short synchronous path for low-cost project artifact inspection, or whether all inspection must go through the main session. If a short path is recommended, define safety boundaries so it does not become a brittle harness-side reasoning substitute.

## Focus 10: Performance, Storage, And Operational Stability

0121 added storage usage and GC controls, but the user still worries about large projects and unclear storage usage.

Please audit:

- Whether `data/` growth is now controlled in real projects, not just unit tests.
- Whether GC protects important artifacts but can reclaim duplicated generated files, old workspace copies, pipeline envs, and marimo workdirs.
- Whether project deletion is robust for large artifact trees.
- Whether heavy Home Credit-like uploads can finish without deadlocking the project.
- Whether backend restarts leave orphaned marimo/Codex/worker processes.
- Whether SQLite locks remain a risk under upload + marimo + worker + polling.
- Whether GET endpoints remain read-only and fast.

## Specific Questions For Fable

Please answer these directly:

1. What are the top 15 remaining product gaps after 0121?
2. Which are UX/IA problems versus backend correctness problems versus agent-protocol problems?
3. Should Tablex simplify asset management into one canonical timestamped asset list with type tags, while retaining contextual related-output links?
4. What is the ideal evaluation-scheme UX for user-specified validation/test split policies?
5. How should Tablex label and handle provisional internal-CV leaderboard runs versus formal EvaluationSpec/SplitManifest runs?
6. What is the fastest path to make native marimo feel "instant enough" without static HTML fallback?
7. What should the prediction UX look like from a Leaderboard model row?
8. How should relational/multi-table prediction input be represented and validated?
9. What should Tablex implement for ensembles, TabPFN/tabular foundation models, and model-family diversity?
10. What safe substrate should exist for LLM-generated feature/row augmentation?
11. Are current reports/research assets worth reading and easy to find? If not, what should change?
12. Are upload and target/objective flows robust enough for arbitrary user input order and browser refresh?
13. Is Chat currently a real actionable interface to the main Codex session, or is it still acting too often as a non-executing response proxy?
14. How should natural-language Chat instructions create or update evaluation proposals without brittle keyword routing?
15. Are Chat/Raw/Activity responsibilities clear to a normal user?
16. Are current tests/evidence sufficient, or are they missing the real UX failures?
17. What should the next implementation directive be, with workstreams and acceptance criteria?

## Requested Output Format

Please return:

1. Executive summary.
2. Severity-ranked findings with file/function references.
3. User-facing failure modes that still remain.
4. A proposed target UX/IA for:
   - assets;
   - evaluation setup;
   - prediction on test data;
   - marimo notebook opening;
   - model diagnostics;
   - model diversity;
   - actionable Chat requests and evaluation instructions.
5. A concrete implementation directive in workstreams with acceptance criteria.
6. "Do not do" list to prevent shortcuts such as static HTML fallback, harness-authored analysis prose, new brittle heuristics, or hard-coded model recipes.
