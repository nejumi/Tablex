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
  - Result: `8 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `git diff --check`
  - Result: passed

Known remaining J1 evidence/work:

- B: browser evidence for provisional/formal leaderboard labeling is still pending.
- L: live flow from Chat/Console instruction to proposal, approval, split generation, and formal rerun is still pending.
- Full directive coverage for `time`, `fold_column`, and `fixed_file` proposal paths now has targeted request-path tests. Generated split execution remains covered for the group split path.

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

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_console_message.py -q`
  - Result: `2 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: backend `py_compile` for touched route/schema/inbox files
  - Result: passed

Known remaining J2 evidence/work:

- B: browser evidence for the Console UI is still pending.
- U/E2E: fake runner proof that console input appears in the next main-session turn prompt is still pending.

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

- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_response_composer.py apps/backend/tests/test_agent_console_message.py -q`
  - Result: `11 passed, 1 warning`
- U: `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_response_composer.py apps/backend/tabular_harness/services/agent_chat.py apps/backend/tabular_harness/api/routes.py`
  - Result: passed
- U/A: `.venv/bin/pytest apps/backend/tests/test_agent_response_composer.py apps/backend/tests/test_agent_console_message.py apps/backend/tests/test_agent_evaluation_requests.py apps/backend/tests/test_evaluation_splits.py apps/backend/tests/test_api_flow.py::test_project_artifacts_include_surface_roles_for_assets_ui apps/backend/tests/test_api_flow.py::test_default_asset_seeding_includes_modeling_and_llm_skills apps/backend/tests/test_api_flow.py::test_password_auth_protects_api_and_persists_user_settings apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime -q`
  - Result: `20 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed

Known remaining J3 evidence/work:

- Full fake-runner and live-project verification for inspection requests is still pending.
- Non-Full-Auto handoff currently returns an honest "start Full Auto" response instead of starting execution.

## J4 Prediction UX

Status: first UI slice complete.

Implemented:

- Leaderboard rows with registered prediction pipelines now expose a "predict with this model" action.
- The prediction panel stays inside the Leaderboard surface and does not add a new tab.
- The first slice lets the user choose an existing `DatasetSnapshot`, queues the existing `run_prediction_pipeline` worker job, runs it, registers the prediction batch artifact, previews it, and offers a predictions download link.
- Rows without a registered prediction pipeline keep the action disabled.
- `pipeline_manifest.v1` now accepts normalized `input_contract.required_tables` declarations, and Leaderboard rows expose the pipeline input contract so the prediction drawer can show expected columns and required tables before execution.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_leaderboard_read_does_not_reconcile_existing_run_into_chat_links apps/backend/tests/test_agent_sessions.py::test_pipeline_manifest_normalizes_required_tables_contract -q`
  - Result: `2 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `git diff --check`
  - Result: passed

Known remaining J4 evidence/work:

- B: browser evidence for the Leaderboard prediction panel is still pending.
- D&D upload directly inside the prediction drawer and `--input-dir` execution for multi-table prediction are still pending.
- `pipeline_manifest.v1` `input_contract.required_tables` declaration/display is implemented; `--input-dir` multi-table prediction execution is still pending.
- Fixed-format validation report for column/dtype mismatch in the drawer is still pending.

## J8 Native marimo Speed

Status: backend profile slice complete.

Implemented:

- Added `docs/evidence/0122_marimo_profile.md` with cold/reopen measurements for two registered Home Credit notebooks.

Verification:

- U/A-style local measurement:
  - `art_19452d019824` cold ready in about 1.9s, warm ready in 15ms after session reuse.
  - `art_e4f7e6ee90e8` cold ready in about 1.9s, warm ready in 12ms after session reuse.

Known remaining J8 evidence/work:

- Browser-side Playwright/network timing is still required; backend readiness does not explain the reported slow UI by itself.
- Prewarm-on-link-display and iframe unmount avoidance are still pending.
- Notebook authoring contract checks for top-level full-data loads are still pending.

## J7 Canonical Asset Inventory

Status: first UI/API slice complete.

Implemented:

- The Assets table now treats the asset list as the canonical inventory instead of a type-first stock list.
- The primary table columns are now output title, human category, created time, origin, size, and actions.
- Internal `asset_type` is no longer a primary column; it is retained as detail text with the version in the output cell.
- Search now includes title, name, id, category, type detail, and origin text.
- Rows are sorted newest-first in the UI.
- Origin is displayed from fixed artifact metadata and research-plan links: plan node, dataset, run, model, job, workspace path, or project fallback.
- Supporting records remain visible through the same inventory rather than being hidden behind a separate default-excluded surface.

Verification:

- U/A: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_project_artifacts_include_surface_roles_for_assets_ui -q`
  - Result: `1 passed, 1 warning`
- U: `npm run build` in `apps/frontend`
  - Result: passed
- U: `git diff --check`
  - Result: passed

Known remaining J7 evidence/work:

- B: browser evidence for finding a data-understanding notebook, final report, and pipeline from Assets search is still pending.
- Insights/Reports still need to be folded into the same canonical inventory as filter presets.
- Markdown report preview with inline figure handling needs a targeted verification pass.

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
