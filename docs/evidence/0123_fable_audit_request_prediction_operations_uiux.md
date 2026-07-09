# 0123 Fable Audit Request: Prediction, Pilot, And Operations UX

Date: 2026-07-09

This is a focused audit request for Tablex after the 0122 cycle and the latest prediction-pipeline UX fixes. Fable can read the repository and local evidence directly. Please use this document as the product framing for the next review.

The central question is:

> How should Tablex design test prediction, pilot validation, and eventual production-operation UX so that it stays simple for humans, flexible for real tabular problems, and does not constrain Codex into old AutoML-style fixed workflows?

## Read First

- `AGENTS.md`
- `README.md`
- `docs/agent_interface_spec.md`
- `docs/exec-plans/0121_audit_response_directive.md`
- `docs/exec-plans/0122_audit_response_directive.md`
- `docs/evidence/0122_fable_audit_request.md`
- `docs/evidence/0122_verification.md`
- `docs/evidence/0122_marimo_profile.md`

Recent commits worth inspecting:

- `093b0f4 Clarify completed full auto next actions`
- `bc29dfe Return prediction pipeline runtime failures to Codex`
- `d10b2bc Clarify prediction upload execution path`
- `ed01280 Preserve Full Auto start during data intake`
- `84299f4 Show marimo loading before notebook iframe`
- `8981b89 Open asset notebooks in native viewer`
- `5caf4a8 Show marimo action for notebook assets`
- `b00726c Poll marimo startup more responsively`
- `bb4ff6e Improve evaluation and marimo loading UX`
- `d69a9fd Read parquet prediction input columns`
- `b530aad Return prediction input failures to Codex`
- `b4f5dfc Show leaderboard model family`

## Product Principles To Preserve

Tablex is a harness and workbench around Codex, not a weaker replacement for Codex reasoning.

The intended split remains:

- Codex reasons about task framing, data semantics, evaluation design, modeling choices, feature engineering, notebooks, reports, pipeline repair, and next iterations.
- Tablex owns data access, artifact registration, lineage, fixed-format tool protocols, EvaluationSpec/SplitManifest consistency, safety boundaries, worker execution, and human-facing state.
- Tablex should validate fixed contracts and surface factual runtime boundaries. It should not infer intent from natural language keywords, column-name heuristics, or fake workflow gates.
- Prediction and pilot workflows must be flexible enough for single-table, multi-table, time-series, benchmark, external-test, and target-free operational inputs.
- Native marimo source remains the notebook artifact of record. Static HTML fallback is prohibited.
- Full Auto is a continuing main Codex session. When new pilot observations or runtime failures arise after completion, Tablex should be able to return the observation to that session rather than losing the loop.

## Current State And Recent Symptoms

The product has improved, but prediction/pilot UX is still the most uncertain area.

Recent concrete symptoms:

1. A user uploaded `application_test.csv` in the Leaderboard prediction panel. The upload was registered as a `prediction_input` artifact, not a `DatasetSnapshot`, so it did not appear in the DatasetSnapshot dropdown. UI copy implied the dropdown was the main path, causing confusion. This was partially fixed in `d10b2bc`.
2. Running the registered `lgbm_relational_aggregates_v1` pipeline failed:
   - `pipeline_manifest.json` declared only `SK_ID_CURR` as input.
   - `predict.py` actually expected a large application feature table and passed string columns such as `EMERGENCYSTATE_MODE` to LightGBM without the same preprocessing used at training time.
   - The failure exposed that pipeline packaging/manifest validation can pass smoke tests while still failing on realistic external test input.
   - `bc29dfe` changed runtime failures so they are summarized and returned to Codex as repair observations, instead of leaving users with a huge traceback only.
3. Full Auto can now stop after completing available analysis and ask for next input, with examples such as test prediction, evaluation revision, ensembles, feature engineering, and pilot validation (`093b0f4`). Please audit whether this is sufficient.
4. The user explicitly does not want "just run `model.predict()` mechanically." The desired product is a modern generative-AI-era harness that can inspect prediction input needs, tell users what is missing, ask clarifying questions, return repair work to Codex, and support complex operational data shapes.

## Focus 1: Prediction UX For External Test Data

Please audit the target flow for "use this model to predict on new/test data."

Questions:

- Should prediction always start from a Leaderboard row, because the model/pipeline context is necessary?
- Should there also be a project-level "Predictions" inventory, or would that fragment the UX?
- Is the current Leaderboard drawer model the right direction?
- What should the drawer show before upload?
  - pipeline readiness;
  - expected primary input;
  - required supporting/history tables;
  - target exclusion warning;
  - schema/table examples;
  - whether this pipeline is currently valid or repair-needed.
- What should happen after upload?
  - column/table validation report;
  - file preview;
  - inferred row count and ID column checks;
  - "ready to run" state;
  - missing table prompts;
  - mapping UI if column names differ.
- Should uploaded prediction files become `DatasetSnapshot`, `prediction_input`, or a separate "prediction batch input" object? Current behavior uses `prediction_input`; audit whether that is correct.
- Should prediction input upload be reusable across models, or scoped to a model pipeline because each pipeline has a different contract?
- How should the UI distinguish:
  - validation split predictions;
  - external test predictions;
  - benchmark submission predictions;
  - pilot/operational predictions;
  - production predictions.
- What should happen when a user uploads a target-bearing file? Should Tablex warn, strip, ask Codex, or refuse only when the fixed contract marks the target as forbidden?
- How should failed prediction runs be represented in Chat, Activity, Leaderboard, Assets, and Codex Console?

Please propose the ideal UI flow and the minimum fixed-format protocol behind it.

## Focus 2: Multi-Table And Time-Series Prediction Inputs

Multi-table and time-aware prediction are where old AutoML-style UX breaks down.

Please audit how Tablex should handle:

- A model trained from a primary table plus supporting/history tables.
- A pipeline that requires new primary rows plus new history rows.
- A pipeline that can predict from primary rows alone but improves with optional history.
- A time-series forecast where test data may require:
  - future covariates;
  - historical context windows;
  - calendar tables;
  - entity keys;
  - prediction horizon;
  - cutoff/as-of timestamps.
- A fixed benchmark test set with no target.
- A production scoring batch where the target will arrive later as outcomes.

Questions:

- Is `pipeline_manifest.input_contract.required_tables` enough?
- Should manifest use a richer distinction such as:
  - `primary_input`;
  - `supporting_inputs`;
  - `history_inputs`;
  - `future_covariates`;
  - `outcome_join_keys`;
  - `as_of_column`;
  - `prediction_horizon`;
  - `entity_keys`;
  - `target_forbidden`;
  - `optional_quality_improving_inputs`;
  - `minimum_viable_inputs`.
- Should Tablex validate only fixed properties (columns, types, keys, row counts, target presence) and leave semantic adequacy to Codex?
- How should Tablex ask the user for missing files without becoming a rigid wizard?
- How should Codex repair a pipeline when the manifest says one thing and `predict.py` actually needs another?
- Should `predict.py` be required to support both `--input` and `--input-dir`, or should multi-table pipelines standardize on `--input-dir`?
- How should Tablex express "this pipeline is not currently runnable for your uploaded files" without implying user error when the pipeline contract is wrong?

Please propose a manifest shape, UI state machine, and failure-handling policy.

## Focus 3: Pipeline Artifact Quality And Repair Loop

Recent failure showed that smoke validation can be too weak.

Please audit:

- Registration-time smoke validation:
  - Is one synthetic row enough?
  - Should validation use a real held-out/sample row from the declared source data when available?
  - Should smoke inputs include realistic categorical/string columns when the source data has them?
  - Should manifest columns be checked against model bundle feature requirements when discoverable?
  - Should Tablex require a "pipeline self-test" directory with small realistic fixtures?
- Runtime failure handling:
  - `bc29dfe` now summarizes failures and returns them to Codex inbox/transcript. Is this enough?
  - Should a prediction pipeline failure automatically wake a completed Full Auto session, or only record a repair observation until the user asks?
  - Should Chat receive a concise failure message and next action every time, or only when the user initiated the prediction run?
  - How should repeated identical failures be deduplicated?
- Repair semantics:
  - Existing pipeline artifacts should be immutable.
  - Repairs should create a new pipeline artifact version.
  - Leaderboard should indicate which runs have runnable, failed, or repair-needed pipelines.
  - Should repaired pipelines supersede earlier pipeline artifacts in the UI while preserving lineage?
- Codex autonomy:
  - Codex should decide whether the right fix is preprocessing, manifest correction, asking for missing tables, or explaining that the model cannot be used for this input.
  - Tablex should provide the fixed failure facts and artifact IDs, not hard-code pipeline repair strategies.

Please propose the target repair loop and acceptance tests.

## Focus 4: Pilot Validation UX

The Pilot Phase already exists conceptually: prediction batches, outcome ingestion, fixed metric scoring, and Codex-authored validation audits.

Please audit whether the product UX should be:

- model-contextual under Leaderboard;
- project-level under a "Validation/Pilot" surface;
- part of Data;
- part of Assets;
- primarily surfaced through Home.

Questions:

- How does a user start a pilot from a model?
- What is the minimal input?
  - prediction batch;
  - outcome batch;
  - join keys;
  - outcome column;
  - time window/as-of;
  - metric scheme.
- How should Tablex distinguish "external test prediction" from "pilot prediction awaiting outcomes"?
- How should outcomes be uploaded and matched to predictions?
- How should fixed metric scoring be presented?
- What should Codex do after a scoring report is registered?
  - validation scheme audit;
  - drift/gap decomposition;
  - next iteration focus;
  - plan update;
  - pipeline repair or feature iteration.
- Should Pilot observations wake a completed Full Auto session automatically? 0120 moved in this direction; please verify if the current behavior is sufficient.
- How should the UI avoid making pilot validation look like production deployment?

Please propose a simple pilot UX that a user can understand in one screen.

## Focus 5: Production Operations Boundary

Production operation is not the immediate MVP, but the UX should not paint Tablex into a corner.

Please audit the intended boundary:

- Tablex local MVP should not add production connectors, production writes, monitoring systems, Kubernetes, W&B/MLflow, auth, or alerting unless explicitly requested.
- But the conceptual model should leave room for:
  - scheduled scoring;
  - model version selection;
  - rollback;
  - drift monitoring;
  - outcome feedback;
  - human approval gates;
  - production-write safety boundaries.
- How should UI language avoid prematurely claiming "deployment" when it is only local pilot scoring?
- Should terms be:
  - "Test prediction";
  - "Pilot validation";
  - "Production handoff";
  rather than "Deploy"?
- What fixed-format objects would be needed later for real production, and which should be deferred?

Please propose a staged operations model: now, next, later.

## Focus 6: Home-Centered Human Story

The user should not need to hunt through tabs after modeling finishes.

Please audit how Home should narrate:

1. What Codex completed.
2. What model is currently strongest and under what evaluation grade.
3. Whether the model has a runnable prediction pipeline.
4. Whether test prediction is available.
5. Whether pilot validation is available or waiting for outcomes.
6. What next human actions are useful:
   - run predictions on test data;
   - provide outcome data;
   - revise evaluation;
   - request ensembles / deeper feature engineering;
   - repair a failed pipeline;
   - start pilot validation.

Questions:

- Should Home have a "Next Decision" card that changes after modeling completes?
- Should pipeline repair-needed state appear in Home?
- Should prediction/pilot readiness be summarized as a single model operations status?
- How should Chat avoid repeating stale links and instead present one clear next action?

Please propose the Home UX in words or a small wireframe.

## Focus 7: Chat, Console, And Codex Autonomy In Prediction Operations

Prediction operations are not just button clicks. Users will ask:

- "Run this model on application_test.csv."
- "What files are missing?"
- "Why did this prediction fail?"
- "Use ROC-AUC, group by customer, and rerun."
- "Try an ensemble before predicting."
- "Can this handle time-series future covariates?"

Please audit:

- Whether Chat currently hands off actionable inspection/modification requests to the main session correctly.
- Whether Raw/Codex Console is sufficiently direct for advanced users.
- Whether prediction pipeline failures should trigger a Codex repair turn automatically in Full Auto.
- Whether the user should see whether a response came from saved state or from the main session inspecting artifacts.
- Whether natural language prediction/evaluation instructions can become schema-validated proposals without keyword routing.

Please be strict about the anti-patterns:

- no keyword-based natural-language routers;
- no harness-authored analytical prose;
- no brittle fixed workflows that block Codex from reasoning;
- no fake readiness gates;
- no hiding runtime failures.

## Focus 8: Asset And Lineage Model For Operations

Prediction and pilot create many artifacts:

- prediction input file;
- validated input report;
- prediction batch;
- pipeline bundle;
- runtime failure record;
- pilot deployment/validation context;
- outcome batch;
- scoring report;
- validation audit;
- repaired pipeline version;
- follow-up notebooks/reports.

Please audit:

- Which of these should be first-class assets?
- Which should appear in the canonical Assets list?
- Which should be surfaced primarily through Leaderboard model context?
- Which should be shown on Home?
- How should lineage make it obvious that:
  - prediction batch came from model pipeline X and input file Y;
  - outcome batch matched prediction batch Z;
  - scoring report used metric scheme M;
  - Codex audit A caused pipeline repair B.
- How much lineage should be visible by default before it overwhelms the user?

Please propose the simplest information architecture that still preserves traceability.

## Focus 9: Tests And Evidence

Please specify acceptance tests and evidence for the recommended design.

Desired evidence levels:

- Unit/API tests for fixed-format manifest validation, prediction input validation, runtime failure feedback, pilot scoring, and Codex inbox delivery.
- Browser tests for Leaderboard row -> predict drawer -> upload -> validation -> run -> download.
- Browser tests for multi-table upload and missing-table UX.
- Browser tests for failed pipeline -> clear message -> repair-needed status.
- Live evidence with a real Codex session for:
  - external test prediction;
  - failed pipeline repair and re-registration;
  - pilot scoring with outcome upload;
  - Codex-authored validation audit after pilot scoring.

Please recommend a minimal "hero demo" scenario that exercises this without becoming too expensive or too slow.

## Requested Output

Please return:

1. A concise severity-ordered audit report.
2. A recommended target UX for:
   - test prediction;
   - multi-table/time-series prediction inputs;
   - pilot validation;
   - eventual production handoff.
3. The minimum fixed-format backend/protocol changes needed.
4. What should remain Codex reasoning / Skill guidance rather than harness logic.
5. What to remove or avoid.
6. A prioritized workstream plan with acceptance criteria.
7. Any updates needed to `docs/agent_interface_spec.md` or `AGENTS.md`.

Please be especially strict about preserving the core philosophy:

> Tablex should make hard tabular prediction operations inspectable and recoverable, but it should not turn Codex into a rigid old AutoML wizard.

