# 0122 Verification Log

This file records evidence for `docs/exec-plans/0122_audit_response_directive.md`.

Evidence grades:

- U: unit or integration test
- A: API-level verification
- B: browser/UI evidence
- L: live project evidence

## J1 Evaluation Contract Loop

Status: first implementation slice complete.

Implemented:

- Added `tablex_evaluation_request.v1` workspace request handling for:
  - `propose_evaluation`
  - `generate_split`
- Added `.tablex/requests/evaluation/` and `.tablex/acks/evaluation/` to prepared agent workspaces.
- Added evaluation request protocol details to session context and `.tablex/PROTOCOL.md`.
- `propose_evaluation` now validates fixed-format fields, referenced columns, metric names, and split-policy enum values, then registers an `EvaluationCandidate` and proposal artifact.
- `generate_split` now queues the existing split-manifest worker job for approved specs.
- Leaderboard API now returns `evaluation_grade` and `evaluation_grade_reason`.
- Leaderboard UI now labels rows as formal comparison or provisional internal validation.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_evaluation_requests.py apps/backend/tests/test_evaluation_splits.py -q`
  - Result: `9 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `git diff --check`
  - Result: passed
- B: Playwright opened Home Credit Test5 Leaderboard and captured provisional internal-validation labeling, missing evaluation-design and validation-evidence badges.
  - Evidence: `docs/evidence/playwright/0122_j1_leaderboard_provisional_badges.png`

Known remaining J1 evidence/work:

- L: live flow from Chat/Console instruction to proposal, approval, split generation, and formal rerun is still pending.
- Full directive coverage for `time`, `fold_column`, and `fixed_file` proposal paths now has targeted request-path tests.
- The Codex request → EvaluationCandidate → promoted/approved EvaluationSpec → SplitManifest generation path has an integrated test for a stratified split proposal.

## J2 Codex Console

Status: first implementation slice complete.

Implemented:

- Added `POST /api/projects/{project_id}/agent-session/console-message`.
- Console messages append a user `user_instruction` transcript event and a `.tablex/inbox` `user_instruction` envelope with `channel: "console"`.
- Console delivery bypasses the Agent Chat response composer and does not create an `agent_chat_turn` job.
- Completed main sessions are woken back to `between_turns` and the project is moved back to `AUTONOMOUS_LOOP`.
- Stopped sessions are not woken; the API returns `409` while preserving the stopped state.
- The Raw surface is renamed in the UI to Codex Console and sends to the new endpoint from both Home and the legacy Raw detail surface.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_console_message.py apps/backend/tests/test_agent_response_composer.py apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_streaming_uses_workspace_file_transcript apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_failure_does_not_mark_user_instructions_delivered -q`
  - Result: `13 passed, 1 warning`
  - Coverage: Console/Chat HTTP input writes a main-session `user_instruction`; the next turn prompt includes that instruction; the fake Codex runner receives the prompt and only successful turns mark instructions delivered.
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `.venv/bin/python -m py_compile apps/backend/tests/test_agent_console_message.py`
  - Result: passed
- B: Playwright opened Home Credit Test5, switched Agent display mode to Codex Console, and captured the direct-input transcript surface.
  - Evidence: `docs/evidence/playwright/0122_j2_codex_console_direct_input.png`

Known remaining J2 evidence/work:

- L: live direct Console input into an active Full Auto run is still pending; the browser proof currently shows the paused-state Console and historical transcript.

## J3 Chat Handoff

Status: first implementation slice complete.

Implemented:

- Agent Chat now reuses a completed Full Auto main session instead of falling back to the auxiliary response composer when the project remains in full-auto mode.
- Agent Chat now starts a missing Full Auto main session when the project is already in `AUTONOMOUS_LOOP`, instead of falling back to the auxiliary response composer.
- Agent Chat now also starts a missing Full Auto main session when the project is `full_auto` but still in an idle phase, keeping Chat aligned with the power state.
- A Chat turn delivered to a completed main session moves that session to `between_turns`, moves the project back to `AUTONOMOUS_LOOP`, writes the user instruction into transcript/inbox, and returns a `waiting_for_agent` main-session wait state.
- Chat assistant messages now display a provenance label that distinguishes main-session answers, saved-record answers, and status updates from fixed composer metadata.
- The auxiliary composer prompt and parser now support a structured `handoff_to_main_session` decision for cases where saved project records are not enough. This does not add filesystem or execution ability to the auxiliary composer.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_console_message.py apps/backend/tests/test_agent_response_composer.py apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_streaming_uses_workspace_file_transcript apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_failure_does_not_mark_user_instructions_delivered -q`
  - Result: `13 passed, 1 warning`
  - Coverage: Chat in Full Auto routes to the main session instead of local-only composition; completed/missing main sessions are reactivated; delivered user instructions are present in the next main-session prompt and remain pending after failed runner turns.
- U: `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_response_composer.py apps/backend/tabular_harness/services/agent_chat.py apps/backend/tabular_harness/api/routes.py`
  - Result: passed
- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_response_composer.py apps/backend/tests/test_agent_console_message.py apps/backend/tests/test_agent_evaluation_requests.py apps/backend/tests/test_evaluation_splits.py apps/backend/tests/test_api_flow.py::test_project_artifacts_include_surface_roles_for_assets_ui apps/backend/tests/test_api_flow.py::test_default_asset_seeding_includes_modeling_and_llm_skills apps/backend/tests/test_api_flow.py::test_password_auth_protects_api_and_persists_user_settings apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime -q`
  - Result: `20 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed

Known remaining J3 evidence/work:

- L: live-project verification for an inspection request that requires reading project files/scripts is still pending.
- Non-Full-Auto handoff currently returns an honest "start Full Auto" response instead of starting execution.

## J4 Prediction UX

Status: upload and multi-table execution slice complete.

Implemented:

- Leaderboard rows with registered prediction pipelines now expose a "predict with this model" action.
- The prediction panel stays inside the Leaderboard surface and does not add a new tab.
- The first slice lets the user choose an existing `DatasetSnapshot`, queues the existing `run_prediction_pipeline` worker job, runs it, registers the prediction batch artifact, previews it, and offers a predictions download link.
- Rows without a registered prediction pipeline keep the action disabled.
- `pipeline_manifest.v1` now accepts normalized `input_contract.required_tables` declarations, and Leaderboard rows expose the pipeline input contract so the prediction drawer can show expected columns and required tables before execution.
- Added `POST /api/projects/{project_id}/prediction-inputs` for drawer-local CSV/Parquet upload as a `prediction_input` artifact.
- Prediction input uploads return a fixed-format validation report with observed columns, expected columns, missing columns, unexpected columns, and dtype-check availability.
- The Leaderboard prediction drawer now supports file chooser/dropzone upload for single-table and per-required-table contracts, shows validation status inline, and only enables prediction when required inputs are present.
- `run_prediction_pipeline` jobs now accept `input_artifact_ids_by_table` and invoke pipeline `predict.py --input-dir ... --output ...` for multi-table prediction contracts.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_prediction_pipeline_worker_runs_predict_and_registers_batch apps/backend/tests/test_agent_sessions.py::test_prediction_pipeline_worker_runs_multitable_input_dir apps/backend/tests/test_agent_sessions.py::test_prediction_pipeline_worker_passes_history_for_time_series_features apps/backend/tests/test_api_flow.py::test_leaderboard_read_does_not_reconcile_existing_run_into_chat_links -q`
  - Result: `4 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `.venv/bin/python -m py_compile apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/worker/jobs.py apps/backend/tests/test_api_flow.py apps/backend/tests/test_agent_sessions.py`
  - Result: passed
- U: `git diff --check`
  - Result: passed
- B: Playwright opened Home Credit Test5, clicked the Leaderboard row prediction action, and captured the in-row prediction drawer.
  - Evidence: `docs/evidence/playwright/0122_j4_prediction_drawer_upload_dropzone.png`
  - Observation: the drawer opens in the Leaderboard surface, shows the expected input columns, and provides an in-place prediction file dropzone without adding a new tab.
- B: Playwright uploaded a CSV through the drawer file chooser after backend restart picked up the new route.
  - Evidence: `docs/evidence/playwright/0122_j4_prediction_drawer_uploaded_validation.png`
  - Observation: the drawer displayed `Input matches required columns` for the uploaded file.

Known remaining J4 evidence/work:

- Live prediction execution from a real external test file through a production-like model pipeline is still pending.
- Browser evidence currently uses the file chooser path; drag-drop uses the same upload handler but still needs a dedicated browser gesture capture.
- Parquet column inspection and dtype validation remain `not_available` in the first fixed-format validation report.

## J8 Native marimo Speed

Status: Leaderboard prewarm slice complete.

Implemented:

- Added `docs/evidence/0122_marimo_profile.md` with cold/reopen measurements for two registered Home Credit notebooks.
- Leaderboard result-notebook links now prewarm native marimo sessions when they become visible.
- Background prewarm calls use `wait_ready=false` so the visible UI path is not held by the marimo readiness wait.

Verification:

- U/A-style local measurement:
  - `art_19452d019824` cold ready in about 1.9s, warm ready in 15ms after session reuse.
  - `art_e4f7e6ee90e8` cold ready in about 1.9s, warm ready in 12ms after session reuse.
- B: Playwright clicked Leaderboard → Result notebooks → `Model comparison`; the Notebooks focus, marimo panel title, and read order all selected the model-comparison notebook instead of the recommended data-understanding notebook.
  - Evidence: `docs/evidence/playwright/0122_j8_model_comparison_notebook_selected.png`
  - Observation: the browser console still recorded native marimo proxy readiness 503s during iframe startup; that remains J8 lifecycle work, not a notebook routing issue.
- B: After removing the per-request proxy readiness probe, Playwright repeated the same Leaderboard → `Model comparison` notebook open on Home Credit Test5.
  - Evidence: `docs/evidence/playwright/0122_j8_model_comparison_proxy_clean.png`
  - Observation: the page reached the native marimo iframe with 0 console errors; remaining console entries were marimo iframe sandbox/preload warnings, not Tablex 503s.
- B: Playwright reloaded Home Credit Test5 Leaderboard and observed background prewarm calls for visible result notebooks with `wait_ready=false`, then opened `Model comparison`.
  - Evidence: `docs/evidence/playwright/0122_j8_leaderboard_prewarmed_open.png`
  - Timing: click-to-native-iframe was 1,431 ms.
  - Observation: the path stayed below the 3 second prewarmed target and recorded 0 browser console errors.

Known remaining J8 evidence/work:

- Browser-side cold timing from a fresh backend with no prewarm is still pending.
- Chat-link open timing is still pending.
- Iframe unmount avoidance is still pending.
- Notebook authoring contract checks for top-level full-data loads are still pending.

## J7 Canonical Asset Inventory

Status: canonical inventory slice complete.

Implemented:

- The Assets table now treats the asset list as the canonical inventory instead of a type-first stock list.
- The primary table columns are now output title, human category, created time, origin, size, and actions.
- Internal `asset_type` is no longer a primary column; it is retained as detail text with the version in the output cell.
- Search now includes title, name, id, category, type detail, and origin text.
- Rows are sorted newest-first in the UI.
- The canonical inventory now appears first in the Assets tab before secondary model/notebook/library panels.
- Search/filter results prioritize human-openable deliverables such as notebooks, reports, and prediction pipelines over supporting records with the same search terms.
- Origin is displayed from fixed artifact metadata and research-plan links: plan node, dataset, run, model, job, workspace path, or project fallback.
- Supporting records remain visible through the same inventory rather than being hidden behind a separate default-excluded surface.
- `prediction_input`, `prediction_batch`, `decision_report_bundle`, `agent_session_report`, and notebook figure artifacts now map to human categories instead of falling through to Other.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_project_artifacts_include_surface_roles_for_assets_ui -q`
  - Result: `1 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `git diff --check`
  - Result: passed
- B: Assets search found the data-understanding notebook artifact as a Notebooks-row before its supporting marimo session JSON record.
  - Evidence: `docs/evidence/playwright/0122_j7_assets_search_data_notebook_artifact.png`
- B: Assets search found the final summary markdown report as a Reports-row.
  - Evidence: `docs/evidence/playwright/0122_j7_assets_search_report.png`
- B: Assets search found the relational LightGBM prediction pipeline as a Models and predictions-row before the supporting zip output record.
  - Evidence: `docs/evidence/playwright/0122_j7_assets_search_pipeline.png`
- B: Assets report preview rendered the final summary markdown with headings, prose, and a model metric table in the same surface.
  - Evidence: `docs/evidence/playwright/0122_j7_assets_report_markdown_preview.png`

Known remaining J7 evidence/work:

- Insights/Reports still need to be folded into the same canonical inventory as filter presets.
- Inline image handling for markdown reports with embedded relative figures still needs a dedicated artifact fixture.

## J5 Modeling Strategy As Skill Equipment

Status: first Skill equipment slice complete.

Implemented:

- Added `skills/tablex-modeling-strategy/SKILL.md`.
- Registered `tablex_modeling_strategy` as a library Skill and equipped it by default for new projects.
- The Skill covers sanity floors, linear models, tree ensembles, relational aggregation, text/mixed-type models, calibration, ensembling, foundation tabular models, time-aware models, target-free analysis, diagnostics, and prediction pipeline packaging.
- Added runtime facts for `catboost`, `tabpfn`, `torch`, and `nvidia-smi` availability to `.tablex/context.json`.
- No new model-selection logic, diversity gate, entity, or request type was added.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_default_asset_seeding_includes_modeling_and_llm_skills apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime apps/backend/tests/test_api_flow.py::test_password_auth_protects_api_and_persists_user_settings -q`
  - Result: `3 passed, 1 warning`
- U: `git diff --check`
  - Result: passed

Known remaining J5 evidence/work:

- Ensemble pipeline registration and prediction E2E proof is still pending.
- TabPFN or another foundation tabular model live trial remains pending and should happen only after the evaluation contract UX is usable.
- Leaderboard display of optional `model_family` still needs a focused pass.

## J6 LLM Feature Augmentation Skill

Status: Skill registration slice complete.

Implemented:

- Added `skills/tablex-llm-feature-augmentation/SKILL.md`.
- Registered `tablex_llm_feature_augmentation` as a library Skill without default project equipment.
- The Skill covers fit signals, leakage discipline, deterministic `(model, prompt_hash, row_hash, schema_version)` cache patterns, feature design patterns, cost/approval awareness, provenance, and prediction pipeline packaging.
- No new harness-owned generation workflow, entity, request type, or feature-generation executor was added.

Verification:

- U/A: covered by the default asset seeding test above, which now asserts the Skill is present in the library.

Known remaining J6 evidence/work:

- Live validation on a text-rich dataset is pending.
- A generated-feature run and reproducible pipeline bundle should be demonstrated after J1-J4 are stable enough for formal comparison and prediction UX.
