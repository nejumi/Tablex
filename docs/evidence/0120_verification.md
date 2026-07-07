# 0120 Verification

Date: 2026-07-07

## Workstream H1

Implemented:
- Primary table is no longer required before upload.
- Bundle upload can register DatasetSnapshot records for every uploaded table while leaving project primary unset.
- Codex can later register `set_primary_table`, `register_derived_table`, and `commit_task_spec` through `.tablex/requests/data/`.
- `task_spec.v1` supports non-supervised task shapes with empty targets.
- Column-name leakage hints are isolated under `name_based_hints` and are not promoted to target/leakage UI guidance.
- Frontend upload and target-column UI copy no longer forces a primary/target decision before data understanding.
- The visible target candidate chip strip was removed from Data Upload. The objective/target input still has lightweight datalist completion for typed column names, but Tablex no longer renders ranked target chips or leakage badges.
- The objective/target input placeholder is now short (`列名または目的を書く` / `Column or objective`), with the longer flexibility guidance kept in field help text so it does not truncate inside the input.
- Active data import/profile jobs are now surfaced from the same structured Job state on both Home and Data. The Home page shows a prominent intake-progress card with percent, current processing step, and a direct Data Upload action while the import is running; Data Upload uses the same card instead of a low-visibility inline row.
- Target/objective suggestions no longer surface DuckDB-generated CSV placeholder names such as `column0` when the uploaded artifact metadata has real header names. This fixes CSVs with a blank first header cell, such as `HomeCredit_columns_description.csv`, where the lightweight SemanticCatalog previously stored `column0` alongside the real columns.
- Existing artifacts whose metadata was already polluted with generated names such as `column0` are corrected at `/api/projects/{project_id}/data/columns` response time by reading the native table header when available, so users do not need to re-upload data to clear stale placeholder suggestions.
- The frontend target/objective datalist and queued-file local header hints also filter generated placeholder names such as `column0`, so stale browser-side queued suggestions cannot reintroduce them even before upload finishes.
- Existing-primary-table selection no longer submits the current target/objective draft as a hidden side effect. Saving the primary table and saving the target/objective are separate, explicit actions.
- The target/objective save button now treats edited local input as an idempotent save action, so browser refreshes, back/forward navigation, primary-table saves, repeated same-value entry, and clearing an existing value do not strand the user with a disabled save control.
- Direct target/objective edits from the UI now create a `task_spec.v1` artifact with `status: user_confirmed` instead of only mutating the legacy project display field.
- Selecting an existing primary table with an explicitly submitted target also records a `user_confirmed` TaskSpec linked to that DatasetSnapshot. The primary-table save path still does not submit a hidden target draft.
- `set_primary_table` data requests now accept an uploaded table `artifact_id` even when no DatasetSnapshot exists yet. Tablex profiles that artifact into a DatasetSnapshot and selects it as primary, so primary-free uploads do not strand Codex before it can declare the row-grain table.

Verification:
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 401 passed, 6 warnings.
- `npm run build` in `apps/frontend` -> passed.
- `rg -n "target-suggestion-chip|target-suggestion-strip|targetSuggestionLeakageBadge|primaryTableRequired" apps/frontend/src` -> no target chip/leakage badge hits; remaining `primaryTableRequired` copy says primary can remain unset.
- `npm run build` in `apps/frontend` -> passed after removing the visible target chip strip.
- `npm run build` in `apps/frontend` -> passed after shortening the objective/target placeholder.
- `npm run build` in `apps/frontend` -> passed after adding the Home/Data data-intake progress card.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings after the data-intake progress UI and AgentSession output helper extraction.
- `.venv/bin/python -m pytest apps/backend/tests/test_data_upload_bundle.py -q` -> 3 passed after adding the blank-first-header CSV regression test.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "upload_data_bundle"` -> 2 passed, 127 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 408 passed, 6 warnings after the `column0` CSV-header fix.
- Verified against the affected local project `p_bcc2f275e9b4`: `HomeCredit_columns_description.csv` now returns `['Table', 'Row', 'Description', 'Special']` from `project_data_columns`, with `has_column0 False`.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/api/routes.py` -> passed after adding response-time stale metadata correction.
- `.venv/bin/python -m pytest apps/backend/tests/test_data_upload_bundle.py -q` -> 3 passed after covering stale artifact metadata that still contains `column0`.
- Runtime scan of `project_data_columns` against both `data/metadata/app.db` and `apps/backend/data/metadata/app.db` -> 0 tables returning `column*` suggestions.
- `npm run build` in `apps/frontend` -> passed after adding frontend-side target datalist filtering for generated placeholder names.
- `npm run build` in `apps/frontend` -> passed after separating primary-table save from target/objective save and making the target save action robust to edited local state.
- `project_column_catalog.v1` no longer returns `role`, `available_at_prediction_time`, or `is_leakage_suspect` in UI-facing `column_details`; the Data Upload helper sees neutral available columns rather than target/leakage guidance.
- Frontend Data Upload renamed the objective helper datalist from `target-column-suggestions` to `objective-column-options`, removed unused target-suggestion copy, and no longer carries leakage/role fields in `ProjectColumnCatalog` types.
- API-level upload coverage now verifies that two CSVs can be uploaded with no `primary_filename`, no `target_column`, and no objective; the project remains without a primary/target, `/data/columns` exposes neutral column details, and Full Auto can still start.
- Worker-level upload coverage now asserts that UI column details strip role/leakage/availability fields even when the stored SemanticCatalog contains them.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_upload_data_bundle_allows_primary_table_to_remain_open apps/backend/tests/test_data_upload_bundle.py apps/backend/tests/test_agent_data_requests.py -q` -> 11 passed, 1 warning.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/services/agent_requests/data.py` -> passed.
- `npm --prefix apps/frontend run build` -> passed.
- `rg -n "targetSuggestion|targetSuggestions|target-column-suggestions|availableAtPredictionTime|isLeakageSuspect|semanticType|roleTarget|is_leakage_suspect|available_at_prediction_time" apps/frontend/src/App.tsx apps/frontend/src/copy.ts apps/frontend/src/types.ts` -> no matches.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_requests/data.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_data_requests.py -q` -> 7 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_project_update_starts_main_session_after_target_change apps/backend/tests/test_api_flow.py::test_upload_data_bundle_profiles_primary_supporting_tables_and_er_hint apps/backend/tests/test_api_flow.py::test_upload_data_bundle_allows_primary_table_to_remain_open -q` -> 3 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 416 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_requests/data.py apps/backend/tests/test_agent_data_requests.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_data_requests.py -q` -> 8 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_upload_data_bundle_allows_primary_table_to_remain_open apps/backend/tests/test_data_upload_bundle.py apps/backend/tests/test_agent_data_requests.py -q` -> 12 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 417 passed, 6 warnings.

## Workstream H2

Implemented:
- `.tablex/PROTOCOL.md` is materialized during AgentSession workspace preparation.
- `.tablex/context.json` now includes the protocol path.
- `build_turn_prompt` is shortened to a small session entry prompt and asserts under 4,000 chars in backend tests.
- Runner protocol details are moved out of the turn prompt and into `.tablex/PROTOCOL.md`.
- Workspace inbox writes now use `.tablex/inbox/<seq>_<kind>.json` envelopes with `schema_version: "tablex_inbox_entry.v1"`.
- Added inbox envelope listing and `.tablex/inbox/.processed` bookkeeping helpers.
- Rejection/request/observation/user-instruction inbox writes in AgentSession, experiment results, pipelines, model diagnostics, and pilot observation notification now use envelopes.
- Old fixed inbox filenames such as `progress_request.md`, `notebook_runtime_failure.md`, and `pilot_observation_available_*.md` are not written by backend code.
- Added a frozen compatibility-alias test so accepted legacy request aliases cannot expand accidentally.
- Extracted runner-facing prompt/protocol construction into `agent_prompting.py` as the first pure-refactor split out of `agent_sessions.py`.
- Extracted the schema-validated data request handler (`set_primary_table`, `register_derived_table`, `commit_task_spec`) into `services/agent_requests/data.py`. `agent_sessions.py` now keeps only a compatibility entrypoint that delegates to the request module and passes the transcript event callback.
- Extracted the schema-validated research request handler (`register_findings`, rich Markdown report, source/figure artifacts, no-findings records) into `services/agent_requests/research.py`. `agent_sessions.py` keeps only a compatibility entrypoint that delegates to the request module and passes transcript/chat callbacks.
- Restored shared fixed-format payload helpers used by notebook, pipeline, and pilot request validation after the extraction, so failed requests return structured ACK errors instead of Python `NameError` failures.
- Extracted the schema-validated pipeline request acceptance/ACK/worker-queue path into `services/agent_requests/pipelines.py`. `agent_sessions.py` now delegates request ingestion while worker-facing registration and smoke validation entrypoints remain compatible for existing imports.
- Updated the compatibility-alias freeze test to inspect the extracted pipeline request module as well as `agent_sessions.py`, preserving the same frozen alias surface after refactor.
- Extracted the schema-validated pilot validation-audit request handler into `services/agent_requests/pilot.py`. `agent_sessions.py` now delegates pilot request ingestion while preserving existing pilot ACK, rejection inbox, evidence, and ResearchPlan link behavior.
- Extracted the schema-validated notebook request acceptance/ACK/error-attention path into `services/agent_requests/notebooks.py`. `agent_sessions.py` now delegates notebook request ingestion while preserving native marimo validation, metadata/link registration, chat linking, and ResearchPlan attachment behavior.
- Extracted the schema-validated ResearchPlan request handler (`commit_revision`, `set_current_work`, `attach_artifact`, `request_human_attention`) into `services/agent_requests/research_plan.py`. `agent_sessions.py` now delegates request ingestion while preserving ACKs, failure attention, human-attention chat turns, artifact attach semantics, and compatibility warnings.
- Extracted the schema-validated model diagnostics request handler into `services/agent_requests/model_diagnostics.py`. `agent_sessions.py` now delegates diagnostic artifact ingestion while preserving required diagnostic check validation, artifact-pack registration, Evidence/Lineage creation, ResearchPlan attachment, stale-ACK reprocessing, and failure attention.
- Extracted AgentSession workspace preparation and context materialization into `services/agent_workspace.py`. `agent_sessions.py` re-exports the existing public entrypoints while workspace directory creation, `.tablex/PROTOCOL.md`, `.tablex/context.json`, dataset access links, runtime facts, research-plan context payloads, locale resolution, and equipped Skill context now live outside the supervisor/session orchestration module.
- Moved workspace path and raw Codex transcript path constants/functions to `services/agent_workspace.py`, leaving `agent_sessions.py` as an importer instead of a second definition site.
- Extracted transcript event indexing, transcript serialization, raw stream appending, Codex JSONL event decoding, and stream file tailing into `services/agent_transcript.py`. `agent_sessions.py` keeps import-compatible names while the transcript cache and stream parsing now live outside the session orchestration module.
- Moved prediction-pipeline registration execution, manifest normalization, requirements validation, isolated smoke-run setup, metric reproduction checks, and workspace path validation into `services/agent_requests/pipelines.py`. `agent_sessions.py` keeps import-compatible names, and worker jobs now import the pipeline execution helpers directly from the request module.
- Extracted AgentSession output artifact classification, metadata, deduplication, and notebook-kind helpers into `services/agent_outputs.py`, leaving `agent_sessions.py` as an importer.
- Extracted AgentSession inbox path helpers, default goal text, user/progress/research-plan/notebook/session-output inbox writers, and ResearchPlan contract request dedup helpers into `services/agent_session_inbox.py`. `agent_sessions.py` imports these names so existing tests and API imports remain compatible.
- Extracted native marimo notebook quality validation, model-diagnostics manifest checks, source/runtime preflight issue conversion, and quality feedback helpers into `services/agent_notebook_quality.py`, removing notebook-quality validation from the session orchestration module.
- Extracted notebook registration metadata normalization and visible-surface construction into `services/agent_notebook_registration.py`.
- Extracted AgentSession chat/attention surfaces, notebook chat-link registration, notebook context/quality reconciliation, notebook-to-ResearchPlan attachment, and Codex-authored `chat_update.md` registration into `services/agent_session_chat.py`. `agent_sessions.py` keeps import-compatible names while the UI-facing chat artifact construction now lives outside the session orchestration module.
- Extracted AgentSession workspace-output ingestion and rejected-output registration into `services/agent_workspace_outputs.py`. `agent_sessions.py` keeps orchestration-compatible wrappers, including the safe ingest wrapper used by the streaming Codex loop.
- Moved raw Codex transcript snapshot publication into `services/agent_transcript.py`.
- Moved notebook-request artifact resolution into `services/agent_notebook_registration.py`.
- Moved TaskSpec liveness nudging into `services/agent_task_spec_nudge.py`, keeping `agent_sessions.py` under the H2 2,000-line ceiling after the H6 follow-up work.

Verification:
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 133 passed.
- Targeted prompt/protocol/alias tests -> 4 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_data_requests.py -q` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "data_request or turn_prompt_keeps or completed_plan"` -> 5 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "research_findings or research_request or research_registration"` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "research_findings_json_preview"` -> 2 passed, 1 warning.
- Targeted API-flow inbox tests -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "model_diagnostics_notebook_request_requires_diagnostic_manifest"` -> 1 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "pipeline_request_registers_prediction_pipeline_and_links_run"` -> 1 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "compatibility_alias_surface or pipeline_request or prediction_pipeline"` -> 12 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "pipeline"` -> 3 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "pilot_validation_audit or pilot_observation_followup or score_pilot or prediction_pipeline_worker"` -> 5 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "pilot"` -> 2 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 406 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/notebooks.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "notebook_request or notebook_file_request or model_diagnostics_notebook_request_requires_diagnostic_manifest"` -> 12 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "notebook or marimo"` -> 25 passed, 104 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 406 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/research_plan.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "research_plan_file_requests or research_plan_ingest_rejects or harness_objective_anchor or current_work_nudge or completed_plan"` -> 11 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_agent_request_compatibility_alias_surface_is_frozen -q` -> 1 passed after adding the extracted ResearchPlan request module to the frozen alias scan.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/model_diagnostics.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "codex_authored_chat_update or completed_plan_pause or waiting_plan_pauses or model_diagnostics_artifact_request or model_diagnostics_notebook_request or model_diagnostics_request"` -> 10 passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime apps/backend/tests/test_agent_sessions.py::test_turn_prompt_keeps_chat_update_human_facing_not_internal_changelog apps/backend/tests/test_agent_sessions.py::test_agent_request_compatibility_alias_surface_is_frozen -q` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "prepare_session_workspace or build_session_context or turn_prompt_keeps or protocol or data_manifest or chat_update or completed_plan"` -> 10 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_agent_chat_writes_active_session_instruction_to_workspace_inbox -q` -> 1 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "research_findings_request_registers or research_plan_contract_nudge or structured_model_results_attach or notebook_file_request_registers or research_plan_file_requests_commit or codex_authored_marimo_notebook"` -> 8 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_pilot_phase_vertical_loop_registers_pipeline_predicts_scores_and_notifies_session -q` -> 1 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_streaming_uses_workspace_file_transcript -q` -> 2 passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_transcript.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "transcript_index_reservation or streaming_uses_workspace_file_transcript or append_runner_stream or transcript_event_indexes or codex_stream_lines or StreamFileTailer"` -> 5 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "agent_chat or transcript or activity"` -> 51 passed, 78 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `npm run build` in `apps/frontend` -> passed.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/{data,research,pipelines}.py` -> `agent_sessions.py` 9,797 lines; extracted request modules total 1,380 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/pilot.py` -> `agent_sessions.py` 9,566 lines; `pilot.py` 317 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/{data,research,pipelines,pilot,notebooks}.py` -> `agent_sessions.py` 9,325 lines; extracted request modules total 1,946 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/{data,research,pipelines,pilot,notebooks}.py` after waiting-plan pause support -> `agent_sessions.py` 9,340 lines; extracted request modules total 1,946 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/{data,research,research_plan,pipelines,pilot,notebooks}.py` -> `agent_sessions.py` 8,967 lines; extracted request modules total 2,427 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/{data,research,research_plan,model_diagnostics,pipelines,pilot,notebooks}.py` -> `agent_sessions.py` 8,386 lines; extracted request modules total 3,208 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_requests/{data,research,research_plan,model_diagnostics,pipelines,pilot,notebooks}.py` -> `agent_sessions.py` 7,356 lines; `agent_workspace.py` 1,138 lines; extracted request/workspace modules total 4,346 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace.py` after moving duplicated workspace path constants/functions -> `agent_sessions.py` 7,339 lines; `agent_workspace.py` 1,138 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_transcript.py apps/backend/tabular_harness/services/agent_requests/{data,research,research_plan,model_diagnostics,pipelines,pilot,notebooks}.py` -> `agent_sessions.py` 7,088 lines; `agent_workspace.py` 1,138 lines; `agent_transcript.py` 282 lines; extracted request/workspace/transcript modules total 4,628 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_supervisor.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "supervisor or lease or stale or retry or timeout or runner or streaming"` -> 20 passed, 120 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_activity.py apps/backend/tests/test_agent_supervisor_cli.py -q` -> 4 passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_supervisor.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_transcript.py` -> `agent_sessions.py` 6,782 lines; `agent_supervisor.py` 352 lines; `agent_workspace.py` 1,138 lines; `agent_transcript.py` 282 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/pipelines.py apps/backend/tabular_harness/worker/jobs.py` -> passed.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_outputs.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "pipeline or prediction_pipeline"` -> 11 passed, 129 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "pipeline or prediction_pipeline or pilot_phase"` -> 3 passed, 126 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 140 passed.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_requests/pipelines.py apps/backend/tabular_harness/services/agent_supervisor.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_transcript.py` -> `agent_sessions.py` 5,980 lines; `pipelines.py` 1,047 lines; `agent_supervisor.py` 352 lines; `agent_workspace.py` 1,138 lines; `agent_transcript.py` 282 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_outputs.py` -> `agent_sessions.py` 5,893 lines; `agent_outputs.py` 111 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_session_inbox.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "progress_update_nudge or current_work_nudge or research_plan_contract or research_plan_request or notebook_request or notebook_context or notebook_quality or runtime_failure or session_output"` -> 13 passed, 127 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "agent_chat_writes_active_session_instruction_to_workspace_inbox or native_marimo_open_failure or upload_data_bundle"` -> 4 passed, 125 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 408 passed, 6 warnings.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_session_inbox.py` -> `agent_sessions.py` 5,152 lines; `agent_session_inbox.py` 792 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_notebook_quality.py apps/backend/tabular_harness/services/agent_session_inbox.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "notebook_quality or notebook_request or notebook_context or runtime_failure or model_diagnostics_notebook_request"` -> 3 passed, 137 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "native_marimo or notebook or marimo"` -> 25 passed, 104 deselected, 1 warning.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_notebook_quality.py apps/backend/tabular_harness/services/agent_session_inbox.py` -> `agent_sessions.py` 4,658 lines; `agent_notebook_quality.py` 515 lines; `agent_session_inbox.py` 790 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_notebook_registration.py apps/backend/tabular_harness/services/agent_notebook_quality.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "notebook_request or notebook_file_request or model_diagnostics_notebook_request or codex_authored_marimo_notebook or notebook_quality"` -> 14 passed, 126 deselected.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_session_chat.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "chat_update or attention or progress_update_nudge or notebook_chat or notebook_request or completed_plan_pause or waiting_plan_pauses or research_request_failed or model_diagnostics_request_failed"` -> 19 passed, 121 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 140 passed.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_session_chat.py apps/backend/tabular_harness/services/agent_notebook_registration.py apps/backend/tabular_harness/services/agent_notebook_quality.py` -> `agent_sessions.py` 2,442 lines; `agent_session_chat.py` 2,073 lines; `agent_notebook_registration.py` 235 lines; `agent_notebook_quality.py` 515 lines.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 140 passed after restoring safe workspace-output ingestion around the extracted implementation.
- `.venv/bin/python -m pytest apps/backend/tests/test_data_upload_bundle.py -q` -> 3 passed.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace_outputs.py` -> passed.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_workspace_outputs.py` -> `agent_sessions.py` 2,039 lines; `agent_workspace_outputs.py` 337 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_transcript.py apps/backend/tabular_harness/services/agent_notebook_registration.py apps/backend/tabular_harness/services/agent_session_chat.py apps/backend/tabular_harness/services/agent_session_results.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "research_plan_request_failed or raw_codex_transcript or notebook_request or notebook_file_request"` -> 14 passed, 126 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 140 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q -k "experiment_registration or agent_chat or research_plan"` -> 35 passed, 94 deselected, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 408 passed, 6 warnings.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_transcript.py apps/backend/tabular_harness/services/agent_notebook_registration.py` -> `agent_sessions.py` 1,977 lines; `agent_transcript.py` 312 lines; `agent_notebook_registration.py` 283 lines.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_task_spec_nudge.py` -> `agent_sessions.py` 1,985 lines; `agent_task_spec_nudge.py` 97 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_task_spec_nudge.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "task_spec_nudge or progress_update_nudge or current_work_nudge"` -> 9 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_turn_prompt_keeps_chat_update_human_facing_not_internal_changelog apps/backend/tests/test_agent_sessions.py::test_prepare_session_workspace_exposes_backend_python_runtime apps/backend/tests/test_agent_sessions.py::test_agent_request_compatibility_alias_surface_is_frozen -q` -> 3 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q` -> 147 passed.
- `.venv/bin/pytest apps/backend/tests -q` -> 424 passed, 6 warnings.
- Follow-up after H10/H11 work: `agent_sessions.py` had drifted back to 2,049 lines. Session lookup and stop helpers were moved into `agent_supervisor.py`, restoring the H2 line-count contract without changing behavior.
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_supervisor.py` -> `agent_sessions.py` 1,992 lines; `agent_supervisor.py` 414 lines.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_supervisor.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_agent_sessions.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "supervisor or lease or stale or retry or timeout or runner or streaming or stop or completed_plan"` -> 27 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "autonomy_stop or autonomous_loop"` -> 3 passed, 1 warning.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "turn_prompt_keeps or prepare_session_workspace_exposes_backend_python_runtime or compatibility_alias_surface or inbox or protocol"` -> 6 passed.
- `rg -n "progress_request\\.md|notebook_runtime_failure\\.md|pilot_observation_available_.*\\.md|target-suggestion-chip|target-suggestion-strip|targetSuggestionLeakageBadge" apps/backend apps/frontend/src` -> no matches.
- `.venv/bin/pytest apps/backend/tests -q` -> 437 passed, 6 warnings.

## Workstream H3

Implemented:
- Chat actions that target native Notebooks now fail visibly in the frontend when the linked artifact id is missing instead of silently navigating to a generic tab.
- Chat actions that target Assets now pass their `artifact_id` into the Assets preview surface; clicking a report/research action opens the artifact preview instead of merely landing on the Assets list.
- Notebook update, native marimo open-failure, and native marimo runtime-failure chat turns now preserve notebook `artifact_id` / `artifact_ids` on `next_focus`.
- Activity focus derived from chat `next_focus` now preserves structured artifact ids instead of dropping them.
- Research Findings chat actions now target `Assets` / `assets-artifact-preview` with the rich report or structured report artifact id.
- Progress-report actions for report evidence now target `Assets` / `assets-artifact-preview` with the report artifact id instead of landing on the generic asset library.
- Artifact-backed Chat actions now include `asset_type` alongside `artifact_id` / `artifact_ids`, and leaderboard actions preserve `entity_ids` / `run_id`.
- The H3 API contract is now covered for all eight target families:
  - Report: progress report action carries `artifact_id`, `artifact_ids`, and `asset_type`.
  - Notebook: notebook action carries `artifact_id`, `artifact_ids`, and `asset_type`.
  - Research Finding: research action opens the rich Markdown report artifact and keeps the structured report artifact as related evidence.
  - Leaderboard Run: leaderboard action carries `run_id` and `entity_ids`.
  - Pipeline Bundle: leaderboard rows expose `pipeline_artifact_id`, and `/api/experiment-runs/{run_id}/pipeline-bundle` returns the bundle.
  - Prediction Batch: pilot deployment index exposes each prediction batch id and `predictions_artifact_id`.
  - Pilot Scoring Report: pilot deployment index exposes the scoring report artifact id and `asset_type`.
- Validation Audit: pilot deployment index exposes the validation audit artifact id, `asset_type`, and linked scoring report artifact ids.
- Repeated model-result Chat notices are suppressed at creation time. If a later registration refers to the same `run_ids`, Tablex updates the existing Chat artifact even when the older artifact predates `result_set_fingerprint` / `notification_fingerprint` metadata.
- Repeated model-result Chat notices are now suppressed even after long autonomous sessions. The lookup no longer depends on the latest 200 chat artifacts, so an older result notice that has been pushed behind many Codex progress reports is updated instead of creating a second broken-record Chat entry.
- Repeated model-result registration failure notices are suppressed by fixed-format `operation` / `error_type` / `error_message` fingerprint, so a recurring schema error does not produce a broken-record Chat stream.
- Agent Chat history also dedupes repeated model-result success and failure notices during readout, keeping the latest state and merged actions.

Verification:
- `npm run build` in `apps/frontend` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_existing_notebook_registration_event_backfills_agent_chat_link apps/backend/tests/test_agent_sessions.py::test_notebook_file_request_registers_source_ack_chat_and_plan_link apps/backend/tests/test_api_flow.py::test_agent_chat_history_rewrites_legacy_notebook_preview_action_to_native_source apps/backend/tests/test_api_flow.py::test_native_marimo_open_failure_is_recorded_in_chat_and_inbox -q` -> 4 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_research_findings_request_registers_report_evidence_and_plan_link apps/backend/tests/test_agent_sessions.py::test_chat_update_links_registered_plan_evidence_without_parsing_message -q` -> 2 passed.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/api/routes.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_chat_update_links_registered_plan_evidence_without_parsing_message apps/backend/tests/test_agent_sessions.py::test_research_findings_request_registers_report_evidence_and_plan_link apps/backend/tests/test_api_flow.py::test_pilot_phase_vertical_loop_registers_pipeline_predicts_scores_and_notifies_session -q` -> 3 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 406 passed, 6 warnings.
- `npm run build` in `apps/frontend` -> passed after wiring Assets preview requests.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration_chat_dedupes_beyond_recent_chat_window or experiment_registration_chat_updates_legacy_run_id_notice or experiment_registration_chat_dedupes_when_visible_links_change"` -> 3 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "agent_chat_history_compaction_dedupes_experiment_registration_notices or agent_chat_history_compaction_replaces_legacy_experiment_registration_state"` -> 2 passed, 1 warning.
- Live API check on `p_bcc2f275e9b4` after backend restart: `/api/projects/p_bcc2f275e9b4/agent-chat/history` returned exactly one Chat turn containing `XGBoost hist model using numeric application features plus applicant-level history aggregates`.
- Browser confirmation with Playwright:
  - Opened `http://localhost:5173` in Chromium.
  - Opened project `Home Credit Test2`.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_agent_sessions.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration_chat or experiment_result_failure_chat"` -> 3 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "experiment_registration"` -> 5 passed, 1 warning.
- Backend restarted on `http://127.0.0.1:8000`; `/api/health` returned `{"status":"ok"}`.
- Live `Home Credit Test3` check: `/api/projects/p_bcc2f275e9b4/agent-chat/history?locale=ja-JP` now returns one `experiment_results_registered` turn for run ids `run_47989f93dd4f`, `run_b2d74a04676a`, `run_6287741c1629`, and `run_8054f27e6f60`.
- After the final restart, the same live endpoint returned `registered 1` and `failed 2`; the remaining failed notices correspond to distinct fixed-format errors, while the repeated successful 4-run Leaderboard notice is no longer duplicated.

## Workstream H7

Implemented:
- Added canonical `research_plan.commit_revision` and `research_plan.set_current_work` accepted-request examples to `.tablex/PROTOCOL.md`.
- The `commit_revision` example uses `payload.document.timeline_blocks`, preserves existing completed/open nodes, and adds/updates coarse plan chapters rather than replacing anchors.
- The `set_current_work` example uses `payload.node_id` and states that the node must exist in the active ResearchPlan revision.
- No new request aliases were added; the turn prompt remains short and still points to `.tablex/PROTOCOL.md` for the detailed fixed-format contract.

Verification:
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_prompting.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "turn_prompt_includes_living_research_plan_contract or turn_prompt_keeps or prepare_session_workspace_exposes_backend_python_runtime or compatibility_alias_surface"` -> 4 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration_chat or experiment_result_failure_chat or turn_prompt_includes_living_research_plan_contract or turn_prompt_keeps or prepare_session_workspace_exposes_backend_python_runtime or compatibility_alias_surface"` -> 7 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "experiment_registration"` -> 5 passed, 1 warning.
- Backend restarted on `http://127.0.0.1:8000`; `/api/health` returned `{"status":"ok"}`.
  - Clicked the existing Chat action `レポートを開く / Open Assets · assets artifact preview`.
  - Result: the UI navigated to Assets and populated the `Artifact Preview` panel with the linked Markdown report; the user did not have to search the asset table.
  - Screenshot: `output/playwright/0120_h3_chat_report_action_assets_preview.png`.

Remaining H3 work:
- Notebook direct-open browser confirmation is still covered by existing native marimo action tests, but a future H5 E2E run should record the full Chat -> Notebook and Chat -> Leaderboard paths in the same scenario.

## Workstream H4

Implemented:
- `tablex_research_request.v1` now accepts `payload.report_workspace_path` for a Codex-authored rich Markdown research report.
- Research registration stores the structured JSON report, the rich Markdown report, and local Markdown image references as separate first-class artifacts.
- The JSON research artifact records `rich_report_artifact_id` and `figure_artifact_ids`; lineage links the JSON report to the rich report and the rich report to its figures.
- Agent Chat research actions open the rich Markdown artifact when present, while preserving the structured JSON artifact id as related evidence.
- Artifact preview for structured research JSON prefers the linked rich Markdown report and rewrites local image references to artifact download URLs.
- Frontend artifact preview now renders Markdown headings, paragraphs, lists, tables, code blocks, links, and images as readable report content instead of a raw preformatted text block.
- Home `Ideas & Findings` research cards now route directly to `Assets` / `assets-artifact-preview` and prefer `rich_report_artifact_id` when present, instead of landing on the generic Insight/Reports surface.

Verification:
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_research_findings_request_registers_report_evidence_and_plan_link apps/backend/tests/test_api_flow.py::test_research_findings_json_preview_renders_source_link_list apps/backend/tests/test_api_flow.py::test_research_findings_json_preview_prefers_rich_markdown_report -q` -> 3 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 401 passed, 6 warnings.
- `npm run build` in `apps/frontend` -> passed.
- Strengthened rich Markdown preview coverage so `test_research_findings_json_preview_prefers_rich_markdown_report` verifies a Markdown table and two local figure references rewritten to artifact download URLs.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_research_findings_json_preview_prefers_rich_markdown_report apps/backend/tests/test_agent_sessions.py::test_research_findings_request_registers_report_evidence_and_plan_link -q` -> 2 passed, 1 warning.
- `npm --prefix apps/frontend run build` -> passed.
- Browser investigation found that the existing Home research card labelled `Open research findings` landed on the generic Insight report surface instead of opening the report artifact. Screenshot: `output/playwright/0120_h4_research_card_generic_landing_issue.png`.
- `npm run build` in `apps/frontend` -> passed after routing Home research memory cards to the rich report artifact preview.

Remaining H4 work:
- Run a browser/manual E2E pass with an actual Codex-authored research report containing multiple figures and tables, then capture evidence under `docs/evidence/`.
- Consider richer Markdown coverage only as needed by real Codex-authored reports; do not add template narrative or harness-side report prose.

## Chat Accountability Follow-Up

Implemented:
- Automatic progress nudges are no longer sent solely because time passed. For stale periodic updates, Tablex now requires new Codex transcript output after the last registered Codex-authored Chat update.
- When visible project state and the Codex-authored Chat message are unchanged, pending Chat jobs are completed from the existing Chat turn instead of creating another identical user-facing post. This keeps a completed or input-waiting Full Auto session from repeatedly posting the same notebook/leaderboard/report links.
- Repeated stale-progress nudges for the same Codex output are suppressed until new Codex output arrives.
- User Chat messages still request a progress response immediately because the user is actively waiting.
- Progress-request wording now asks for user-visible status, uncertainty, and next review surfaces without asking Codex to discuss resume mechanics, inbox/ack checks, or protocol checks.
- User-facing recovery and leaderboard follow-up copy no longer says "same session" / "同じセッション".
- Codex-authored `reports/chat_update.md` registrations are now coalesced by a structured visible-state fingerprint instead of message text. If ResearchPlan revision, current node, datasets, runs, model versions, relevant artifacts, and action targets are unchanged, a rewritten progress file is not posted again.
- ResearchPlan and leaderboard registration attention messages no longer expose maker-facing phrases such as `構造化エラー`, `ACK`, or `structured validation error`; they state that the visible plan/leaderboard was preserved and that corrected results or decisions will appear in later progress.
- Explicit user Chat requests still bypass that coalescing so a waiting user receives an answer even when the project state did not change.
- ResearchPlan current-work nudges are no longer sent when the active plan has no open top-level blocks.
- When the active ResearchPlan has no open blocks, no undelivered user instruction exists, and no newer dataset/result artifact requires another pass, Full Auto marks the session complete, turns the project back to idle, and posts one factual "next input needed" Chat event instead of spending tokens on repeated health checks.
- When the active ResearchPlan has no runnable blocks because the remaining top-level work is `waiting` or `blocked`, Full Auto also marks the session complete and asks for new external input instead of continuing health-check loops. This covers the case where modeling iterations have been exhausted and the next meaningful step is test data, an operational scoring sample, or user direction.
- Legacy attention/progress artifacts are no longer treated as new project work that must be re-reported before a completed ResearchPlan can pause. This prevents repeated "still checking the same session" style updates after Codex has exhausted the current reversible work.
- The streaming supervisor now checks the completed-plan pause condition during long-running turns after workspace ingestion, terminates the active process when the plan is complete, and leaves the session in `completed` rather than rewriting it to `stopped`.

Verification:
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_progress_update_nudge_writes_inbox_without_faking_heartbeat apps/backend/tests/test_agent_sessions.py::test_progress_update_nudge_waits_for_new_codex_output apps/backend/tests/test_agent_sessions.py::test_supervisor_safe_progress_update_uses_project_locale_without_browser_polling -q` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_codex_cli_turn_streaming_uses_workspace_file_transcript apps/backend/tests/test_agent_sessions.py::test_progress_update_nudge_writes_inbox_without_faking_heartbeat apps/backend/tests/test_agent_sessions.py::test_progress_update_nudge_waits_for_new_codex_output apps/backend/tests/test_agent_sessions.py::test_supervisor_safe_progress_update_uses_project_locale_without_browser_polling -q` -> 4 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_agent_chat_writes_active_session_instruction_to_workspace_inbox -q` -> 1 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_turn_prompt_keeps_chat_update_human_facing_not_internal_changelog -q` -> 1 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 134 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "chat_update or progress_update_nudge or current_work_nudge or completed_plan_pauses"` -> 12 passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 406 passed, 6 warnings.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "completed_plan or completed_session or safe_completed"` -> 5 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "completed_plan or waiting_plan_pauses or progress_update_nudge or current_work_nudge"` -> 10 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "codex_authored_chat_update or completed_plan_pause or waiting_plan_pauses"` -> covered duplicate Chat completion without another visible post.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 407 passed, 6 warnings.

## ResearchPlan / Leaderboard Consistency Follow-Up

Problem observed:
- A live Full Auto run registered model evaluations on the Leaderboard while ResearchPlan still showed Data Understanding as the current node.
- Root cause: experiment-result registration accepted model results without an explicit `research_plan_node_id` and could fall back to the currently visible ResearchPlan node during registration or visibility restore.

Implemented:
- Experiment-result payloads now require `payload.research_plan_node_id` or per-run `research_plan_node_id` whenever an active ResearchPlan revision exists.
- Unknown ResearchPlan node ids now reject the experiment-result registration instead of registering runs with a warning and no visible plan attachment.
- ExperimentRun visibility restore no longer attaches node-less historical runs to the current ResearchPlan node.
- The turn prompt and experiment request contract now tell Codex to update ResearchPlan/current work before registering evaluation/modeling results when it moves beyond data understanding.
- Tests cover both structured `model_results.v1` artifacts and `.tablex/requests/experiments/` requests for missing/unknown ResearchPlan nodes.
- Leaderboard registration Chat turns are now deduplicated by visible-state fingerprint. If the same run set, same visible links, and same missing pipeline/model-diagnostics/notebook status are seen again from another source path, Tablex does not post another identical human-facing Chat message.
- Leaderboard registration Chat turns now also carry a stable notification fingerprint based on the registered result set and missing-output categories. If link metadata changes later, the existing Chat turn is updated instead of adding another copy. Chat history also deduplicates adjacent experiment-registration notices with the same fingerprint, so legacy duplicate artifacts no longer show as repeated user-facing messages.
- The registration message no longer says that internal follow-up was handed to Codex. It reports the registered result and lists any still-needed outputs in one short sentence.
- Follow-up fix: Leaderboard registration Chat turns now also carry a result-set fingerprint independent of pipeline/diagnostic/notebook readiness. When the same model result set is seen again after a session resume or after supporting outputs are registered, Tablex updates the existing Chat card instead of posting another one.
- Chat history now deduplicates experiment-registration turns globally, not only adjacent groups. Legacy records without fingerprints fall back to `run_ids`, so an old "still needed" state is replaced by the later state for the same result set.

Verification:
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_prompting.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "structured_model_results_attach_to_single_active_research_plan_node or structured_model_results_reject_unknown_research_plan_node or structured_model_results_reject_missing_research_plan_node_when_plan_exists or existing_experiment_run_restores_chat_and_research_plan_link or structured_model_results_ignore_stale_current_work_when_revision_moved_on or experiment_result_request_rejects_unknown_research_plan_node or experiment_result_request_rejects_missing_research_plan_node_when_plan_exists or experiment_result_request_links_runs_to_research_plan_node"` -> 8 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_leaderboard_reconciles_existing_run_into_chat_and_plan_links -q` -> 1 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 416 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_codex_structured_model_results_materialize_leaderboard_runs_and_chat_link apps/backend/tests/test_agent_sessions.py -q -k "experiment_results_registered or structured_model_results"` -> 9 passed.
- `.venv/bin/python -m pytest apps/backend/tests -q` -> 416 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_agent_sessions.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_experiment_registration_chat_dedupes_when_visible_links_change apps/backend/tests/test_agent_sessions.py::test_codex_structured_model_results_materialize_leaderboard_runs_and_chat_link apps/backend/tests/test_agent_sessions.py::test_experiment_result_file_request_registers_leaderboard_run_with_ack -q` -> 3 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_agent_chat_history_compaction_dedupes_experiment_registration_notices apps/backend/tests/test_api_flow.py::test_agent_chat_history_compaction_groups_adjacent_notebook_updates -q` -> 2 passed, 1 warning.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 143 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py -q` -> 132 passed, 6 warnings.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_agent_sessions.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_experiment_registration_chat_dedupes_when_visible_links_change apps/backend/tests/test_api_flow.py::test_agent_chat_history_compaction_dedupes_experiment_registration_notices apps/backend/tests/test_api_flow.py::test_agent_chat_history_compaction_replaces_legacy_experiment_registration_state -q` -> 3 passed, 1 warning.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration or model_results or leaderboard_runs_and_chat_link"` -> 9 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "experiment_registration or leaderboard_reconcile or activity_uses_experiment_registration or compaction"` -> 10 passed, 1 warning.
- Live check against project `p_bcc2f275e9b4`: `GET /api/projects/p_bcc2f275e9b4/agent-chat/history` now returns 1 `experiment_results_registered` Chat turn for the repeated 4-run Leaderboard result set.
- Follow-up live check after backend restart: the same history endpoint returned 28 visible turns and exactly 1 visible Chat turn containing `4件のモデル評価をLeaderboardに登録しました`.

## Workstream H6

Implemented:
- When a main autonomous session has a registered primary `DatasetSnapshot` but no `task_spec` artifact, Tablex now writes one non-blocking `task_spec_request` inbox entry for Codex.
- The request asks Codex to submit `.tablex/requests/data/` `commit_task_spec` after data understanding. It explicitly allows `targets: []` for clustering, anomaly detection, exploratory work, and other no-explicit-target task shapes.
- The request is based only on fixed structured state: `Project.primary_dataset_snapshot_id` exists and no project `task_spec` artifact exists.
- The request does not infer a target, rank columns, or interpret natural language. It does not block reversible analysis.
- Duplicate requests are suppressed per session and primary DatasetSnapshot id.
- The safe supervisor nudge path now emits this TaskSpec request alongside existing plan/progress nudges.

Verification:
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_inbox.py apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q -k "task_spec_nudge or progress_update_nudge or current_work_nudge"` -> 9 passed, 138 deselected.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py::test_supervisor_safe_nudge_requests_missing_task_spec_after_primary apps/backend/tests/test_agent_sessions.py::test_task_spec_nudge_requests_commit_after_primary_without_task_spec apps/backend/tests/test_agent_sessions.py::test_task_spec_nudge_skips_when_task_spec_artifact_exists apps/backend/tests/test_agent_sessions.py::test_task_spec_nudge_dedupes_same_primary_in_session -q` -> 4 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_sessions.py -q` -> 147 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_agent_data_requests.py -q` -> 8 passed.
- `.venv/bin/python -m pytest apps/backend/tests/test_api_flow.py::test_upload_data_bundle_allows_primary_table_to_remain_open apps/backend/tests/test_data_upload_bundle.py -q` -> 4 passed, 1 warning.

## 2026-07-07 Checklist Reconciliation

The unchecked acceptance items in `docs/exec-plans/0120_audit_response_directive.md` were re-audited against the current worktree rather than assumed from earlier notes.

H1:
- Playwright captured the Data Upload surface without ranked target chips or leakage badges: `docs/evidence/playwright/0120_h1_data_upload_no_target_chips.png`.
- The screenshot shows the objective/target field as a neutral input (`Column or objective`) with datalist support, no visible target candidate chip strip, and no leakage badge.
- `rg -n "targetSuggestion|targetSuggestions|target-column-suggestions|target-suggestion-chip|target-suggestion-strip|targetSuggestionLeakageBadge|availableAtPredictionTime|isLeakageSuspect|semanticType|roleTarget|is_leakage_suspect|available_at_prediction_time" apps/frontend/src/App.tsx apps/frontend/src/copy.ts apps/frontend/src/types.ts` -> no matches.
- `npm --prefix apps/frontend run build` -> passed.

H3/H4:
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "research_findings_request_registers_report_evidence_and_plan_link or chat_action or agent_chat or prediction_pipeline or pilot_scoring or validation_audit"` -> 13 passed, 144 deselected.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "research_findings_json_preview_prefers_rich_markdown_report or agent_chat_history or pipeline_bundle or pilot_phase_vertical_loop"` -> 20 passed, 116 deselected, 1 warning.
- `npm --prefix apps/frontend run build` -> passed.

H6/H8/H9:
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "task_spec_nudge or data_framing_nudge or pipeline_registration or structured_model_results"` -> 15 passed, 142 deselected.
- The tests cover non-blocking TaskSpec requests after primary selection, non-blocking data-framing requests before primary selection, exact-payload dedupe, and pipeline-registration requests after structured model-result ingestion.

H2 drift check:
- `wc -l apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tabular_harness/services/agent_supervisor.py apps/backend/tabular_harness/services/agent_prompting.py` -> `agent_sessions.py` 1,992 lines; `agent_supervisor.py` 414 lines; `agent_prompting.py` 224 lines.
- Final backend suite after checklist reconciliation: `.venv/bin/pytest apps/backend/tests -q` -> 437 passed, 6 warnings.

## Workstream H8

Implemented:

- When a main autonomous session has uploaded `DatasetSnapshot` records but no primary DatasetSnapshot and no `task_spec` artifact, Tablex now writes one non-blocking `data_framing_request` inbox entry for Codex.
- The request asks Codex to submit `set_primary_table`, `register_derived_table`, and/or `commit_task_spec` when the data framing is ready. It explicitly allows `targets: []`.
- The request is based only on fixed structured state: project DatasetSnapshots exist, `Project.primary_dataset_snapshot_id` is empty, and no project `task_spec` artifact exists.
- The request does not infer a target, rank columns, or interpret natural language. It does not block reversible analysis.
- Duplicate requests are suppressed per session and DatasetSnapshot id set.
- The safe supervisor nudge path now emits this data-framing request before the primary-dependent TaskSpec request.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_task_spec_nudge.py apps/backend/tabular_harness/services/agent_session_inbox.py apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "data_framing_nudge or task_spec_nudge"` -> 7 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "data_framing_nudge or task_spec_nudge or supervisor_safe_nudge_requests_data_framing or supervisor_safe_nudge_requests_missing_task_spec"` -> 9 passed.
- Live bounded check: project `p_5ed5352cb35f` uploaded two CSVs through `/datasets/upload-bundle` with no primary or target, started Full Auto, emitted transcript event `data_framing_requested` at event `#4`, and was stopped cleanly.
- Follow-up regression: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_upload_data_bundle_allows_primary_table_to_remain_open apps/backend/tests/test_data_upload_bundle.py -q` -> 4 passed, 1 warning.

## Experiment Registration Notice Deduplication Follow-Up

Problem observed:

- A live Full Auto run posted the same "4 model evaluations registered" Chat card more than once for the same result set.
- The same invalid `model_results.json` artifact was also re-ingested repeatedly and produced duplicate `.tablex/inbox` rejection entries with the same fixed-format validation error.

Implemented:

- Leaderboard registration Chat lookup now scans all fixed-format experiment-registration Chat artifacts for the project instead of a recent 200-artifact window.
- The lookup is restricted to artifacts whose metadata marks them as `main_agent_session_experiment_registration`, so unrelated chat history does not affect deduplication.
- Experiment result artifact rejection writing is now idempotent for the same source artifact id, workspace path, result schema, error type, and error message.
- If Codex submits a different fixed result or hits a different validation error, Tablex still writes a new structured rejection so Codex can self-correct.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "malformed_structured_model_results_are_announced_in_agent_chat or experiment_registration_chat_dedupes_beyond_recent_chat_window or experiment_registration_chat_updates_legacy_run_id_notice or experiment_registration_chat_dedupes_when_visible_links_change"` -> 4 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "agent_chat_history_compaction_dedupes_experiment_registration_notices or agent_chat_history_compaction_replaces_legacy_experiment_registration_state"` -> 2 passed, 1 warning.

## H5 Follow-Up: Experiment Result Plan-Link Protocol Clarity

Problem observed:

- In project `p_8853a9724f88`, Codex saved `artifacts/model_results.json` with valid model rows but no `research_plan_node_id`.
- Tablex correctly rejected the result because an active ResearchPlan existed, but the runner-facing protocol described `payload.research_plan_node_id`, which is precise for `.tablex/requests/experiments/` but ambiguous for a plain `artifacts/model_results.json` file.

Implemented:

- `.tablex/PROTOCOL.md` now distinguishes the two valid submission shapes:
  - `.tablex/requests/experiments/`: use `payload.research_plan_node_id`.
  - `artifacts/model_results.json`: use top-level `research_plan_node_id`.
  - Per-run `research_plan_node_id` remains valid for either shape.
- The workspace context contract now includes an explicit `example_model_results_file` with top-level `research_plan_node_id`.
- The fixed-format rejection message now gives the same file-vs-request distinction so Codex can repair the submitted result without guessing.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_prompting.py apps/backend/tabular_harness/services/agent_workspace.py apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "turn_prompt_includes_living_research_plan_contract or structured_model_results_reject_missing_research_plan_node_when_plan_exists or malformed_structured_model_results_are_announced_in_agent_chat"` -> 3 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "session_context or protocol"` -> 2 passed.

## Workstream H9

Problem observed:

- In H5 project `p_d2a02af77c2d`, Codex registered five ExperimentRuns from `artifacts/model_results.json` and later repaired model diagnostics, but no prediction pipeline bundle was requested or registered.
- The `.tablex/requests/experiments/` path already emits pipeline follow-up requests for newly registered runs. The structured artifact auto-registration path emitted diagnostics requests but not pipeline requests.
- When Codex later retried the same result set through `.tablex/requests/experiments/`, all runs were duplicates, so the ack contained no `registered_runs` and no pipeline request.

Implemented:

- Structured result artifact auto-registration now checks `experiment_pipeline_registration_status(runs)` for newly created ExperimentRuns.
- If pipeline bundles are missing, Tablex writes a `pipeline_registration_request` inbox entry with the registered run ids and fixed status payload.
- Existing ExperimentRuns restored through visibility reconciliation also request missing pipeline bundles, using the same fixed-format payload dedupe. This lets sessions recover after older artifact-based registrations that predate H9.
- Pipeline, model diagnostics artifact, and model diagnostics notebook follow-up requests now dedupe by exact fixed-format payload to avoid repeated inbox spam.
- Completed-plan pause now checks the workspace inbox. If an unprocessed actionable `request`, `rejection`, or `observation` remains, the main session is not marked complete before Codex can read it. Stale `progress_request` and `research_plan_current_work_request` entries remain non-blocking.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_session_results.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_codex_structured_model_results_materialize_leaderboard_runs_and_chat_link apps/backend/tests/test_agent_sessions.py::test_malformed_structured_model_results_are_announced_in_agent_chat -q` -> 2 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration or structured_model_results or pipeline_registration"` -> 11 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_existing_experiment_run_restores_chat_and_research_plan_link apps/backend/tests/test_agent_sessions.py::test_codex_structured_model_results_materialize_leaderboard_runs_and_chat_link -q` -> 2 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "experiment_registration or structured_model_results or pipeline_registration or existing_experiment_run_restores"` -> 12 passed.
- `.venv/bin/python -m py_compile apps/backend/tabular_harness/services/agent_sessions.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py::test_completed_plan_pauses_main_session_until_new_input apps/backend/tests/test_agent_sessions.py::test_safe_completed_plan_pause_marks_session_completed_once -q` -> 2 passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "completed_plan or waiting_plan_pauses or experiment_registration or structured_model_results or pipeline_registration or existing_experiment_run_restores"` -> 17 passed.

## Workstream H10

Problem observed:

- The H5 project could register a prediction pipeline, create a pilot prediction batch, and score observed outcomes.
- The first pilot scoring report (`job_6b9de9755a99`, artifact `art_f1812ae7e747`) did not notify the main session because the session had already completed available reversible work and the project had returned to `IDLE`.
- Uploading the future/pilot CSVs also moved the project out of `AUTONOMOUS_LOOP`, so no continuation job was scheduled.

Implemented:

- Pilot outcome scoring now treats a `completed` main session as eligible for structured pilot observation delivery.
- `stopped` sessions remain excluded.
- When a full-auto project receives a pilot observation for an eligible session, the project phase is restored to `AUTONOMOUS_LOOP` before queuing continuation.
- The delivered inbox entry is fixed-format `pilot_observation_available`; it contains report artifact ids, batch ids, metrics, matched row count, and as-of violation summary without interpreting natural language or columns.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/worker/jobs.py apps/backend/tests/test_agent_sessions.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "pilot_scoring_wakes_completed or pilot_scoring_does_not_wake_stopped or pilot_outcome_scoring_worker_registers_report"` -> 3 passed.
- Live H5 second scoring job `job_b4b80750097f` -> succeeded.
- Live output included `notified_agent_session_id=ags_bb7a8644ae23` and `session_continuation_job_id=job_8d6bf824eaac`.
- Project `p_d2a02af77c2d` moved to `AUTONOMOUS_LOOP` after the second pilot scoring job.
- Workspace inbox contains `.tablex/inbox/000039_observation.json` with `type=pilot_observation_available` and `pilot_scoring_report_workspace_path=.tablex/pilot_observations/art_226858433571.json`.

Follow-up found during live verification:

- Stop API cancelled the queued/running jobs and stopped the main session, but one planned child Codex process remained and had to be manually terminated.
- This should become a separate stop-cleanup workstream: power-off must stop active child runner processes as well as the main session and queued jobs.

## Workstream H11

Problem observed:

- During H10 live verification, the Stop API stopped the main AgentSession and cancelled queued/running jobs.
- One planned child Codex process remained alive after the stop response and had to be manually terminated.
- This violated the power-off contract: user power-off is one of the few boundaries where Tablex should stop Codex work, including child runner processes belonging to the same project.

Implemented:

- Stop API now runs a project-scoped Codex process cleanup step after cancelling jobs and stopping the main session.
- Cleanup uses fixed structured state only: `running_codex_processes_for_project(project_id)` scans command lines for Codex exec processes containing the project workspace marker.
- For each observed process, Tablex sends SIGTERM, waits briefly, escalates to SIGKILL if needed, and records structured status.
- Stop job output now includes `codex_process_cleanup` with `observed_count`, `terminated_count`, `remaining_count`, and per-process metadata.
- User-facing stop copy was not expanded with process internals.

Verification:

- `.venv/bin/python -m py_compile apps/backend/tabular_harness/api/routes.py apps/backend/tests/test_api_flow.py` -> passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "autonomy_stop"` -> 3 passed, 1 warning.
- `.venv/bin/pytest apps/backend/tests/test_agent_sessions.py -q -k "pilot_scoring_wakes_completed or pilot_scoring_does_not_wake_stopped or pilot_outcome_scoring_worker_registers_report"` -> 3 passed.
- `.venv/bin/pytest apps/backend/tests/test_api_flow.py -q -k "pilot_phase_vertical_loop or pilot"` -> 2 passed, 1 warning.
- Backend restarted with the new code; `GET /health` returned `{"status":"ok"}` and both `:8000` and `:5173` were listening.

Coverage notes:

- `test_autonomy_stop_terminates_observed_project_codex_processes` verifies that observed project Codex process ids are terminated and represented in `codex_process_cleanup`.
- `test_autonomy_stop_does_not_scan_or_stop_other_project_processes` verifies that stopping one project does not terminate another project's process ids.
- The existing stop cancellation test still verifies job cancellation and preservation of upload/primary-table jobs.
