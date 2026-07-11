from __future__ import annotations

import ast
import subprocess
import sys
import threading
import time
import zipfile
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import tabular_harness.services.agent_notebook_quality as agent_notebook_quality_module
import tabular_harness.services.agent_requests.pipelines as pipeline_requests_module
import tabular_harness.services.agent_requests.research_plan as research_plan_requests_module
import tabular_harness.services.agent_sessions as agent_sessions_module
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.config import get_settings
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.db.session import ensure_sqlite_mvp_columns
from tabular_harness.models.entities import (
    AgentSession,
    AgentSupervisorLease,
    AgentTranscriptEvent,
    Artifact,
    Base,
    DatasetSnapshot,
    DeliverableExpectation,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Job,
    LineageEdge,
    ModelVersion,
    PilotDeployment,
    PilotOutcomeBatch,
    PilotPredictionBatch,
    Project,
    Question,
    ResearchPlanCurrentWork,
    ResearchPlanRevision,
    SplitManifest,
    User,
    utc_now,
)
from tabular_harness.services.agent_inbox import (
    inbox_processed_path,
    list_inbox_entries,
    mark_inbox_entry_processed,
    write_inbox_entry,
)
from tabular_harness.services.agent_session_chat import (
    request_context_for_auto_registered_notebooks,
    request_quality_repair_for_session_notebooks,
)
from tabular_harness.services.agent_session_results import (
    experiment_acks_dir,
    experiment_artifact_rejection_path,
    experiment_model_diagnostics_artifact_status,
    experiment_request_rejection_path,
    experiment_requests_dir,
    ingest_registered_session_experiment_artifacts,
    model_diagnostics_artifact_request_path,
    model_diagnostics_notebook_request_path,
    pipeline_registration_request_path,
    register_experiment_registration_chat_turn,
    register_experiment_result_failure_chat_turn,
    restore_registered_session_experiment_visibility,
)
from tabular_harness.services.agent_sessions import (
    CODEX_RAW_TRANSCRIPT_FILENAME,
    CODEX_STDERR_LOG_FILENAME,
    StreamFileTailer,
    acquire_supervisor_lease,
    append_codex_stream_lines,
    append_runner_stream_to_workspace,
    append_session_event,
    asset_type_for_session_output,
    attention_chat_message,
    build_session_context,
    build_turn_prompt,
    chat_update_message_from_text,
    data_framing_request_path,
    ingest_session_workspace_outputs,
    latest_codex_transcript_output_at,
    latest_project_response_locale,
    main_session_should_pause_after_completed_plan,
    mark_user_instructions_delivered,
    maybe_register_chat_update_from_workspace_output,
    maybe_request_codex_progress_update,
    maybe_request_codex_progress_update_safely,
    maybe_request_data_framing_update,
    maybe_request_research_plan_contract_revision,
    maybe_request_research_plan_current_work_update,
    maybe_request_task_spec_update,
    metadata_for_session_output,
    model_diagnostics_acks_dir,
    model_diagnostics_request_rejection_path,
    model_diagnostics_requests_dir,
    notebook_acks_dir,
    notebook_context_request_path,
    notebook_quality_repair_path,
    notebook_request_rejection_path,
    notebook_requests_dir,
    pause_main_session_after_completed_plan,
    pause_main_session_after_completed_plan_safely,
    pilot_acks_dir,
    pilot_request_rejection_path,
    pilot_requests_dir,
    pipeline_acks_dir,
    pipeline_requests_dir,
    prepare_session_workspace,
    progress_request_path,
    publish_raw_codex_transcript_snapshot,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    register_agent_session_attention_chat_turn,
    register_agent_session_notebook_source_output,
    release_supervisor_lease,
    renew_supervisor_lease,
    research_acks_dir,
    research_plan_acks_dir,
    research_plan_artifact_rejection_path,
    research_plan_contract_request_path,
    research_plan_current_work_request_path,
    research_plan_request_rejection_path,
    research_plan_requests_dir,
    research_request_rejection_path,
    research_requests_dir,
    reserve_transcript_event_indexes,
    run_codex_cli_turn_streaming,
    session_output_artifact_name,
    session_protocol_text,
    should_register_session_output,
    start_active_main_session_supervisors,
    start_main_agent_session_supervisor_thread,
    start_supervisor_lease_heartbeat,
    supervisor_slot_active,
    task_spec_request_path,
)
from tabular_harness.services.analysis_notebooks import build_project_notebook_index
from tabular_harness.services.approach import store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.jobs import create_job
from tabular_harness.services.model_diagnostics_artifacts import latest_run_artifact
from tabular_harness.services.prediction_input_feedback import (
    maybe_send_prediction_input_validation_failure_to_codex,
)
from tabular_harness.services.research_plan_timeline import build_research_plan_timeline_response
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    commit_research_plan_revision,
    latest_research_plan_current_work,
    record_harness_dataset_upload_in_research_plan,
    record_harness_objective_in_research_plan,
    set_research_plan_current_work,
)
from tabular_harness.services.result_notebook_evidence import (
    latest_model_diagnostics_notebook_for_run,
)
from tabular_harness.worker.jobs import (
    register_prediction_pipeline_handler,
    run_prediction_pipeline_handler,
    score_pilot_outcomes_handler,
)
from tabular_harness.worker.runner import SyncWorker

VISUAL_MARIMO_NOTEBOOK_SOURCE = """import marimo

app = marimo.App()

@app.cell
def _():
    import pandas as pd
    import plotly.express as px
    _data = pd.DataFrame({"segment": ["A", "B", "C"], "value": [1, 3, 2]})
    _fig = px.bar(_data, x="segment", y="value", title="Segment comparison")
    _fig
    return
"""

RUNTIME_ERROR_MARIMO_NOTEBOOK_SOURCE = """import marimo

app = marimo.App()

@app.cell
def _():
    import pandas as pd
    import plotly.express as px
    _data = pd.DataFrame({"segment": ["A", "B"], "value": [1, 2]})
    _fig = px.bar(_data, x="segment", y="value", title="Segment comparison")
    _missing = _data["missing_column"].sum()
    _fig
    return
"""


def ready_notebook_quality_manifest() -> dict[str, Any]:
    return {
        "schema_version": "tablex_notebook_quality_manifest.v1",
        "figure_count": 3,
        "table_count": 1,
        "key_findings": ["The notebook contains visual diagnostics for human review."],
        "read_order": [{"label": "Visual summary"}],
        "data_sources_used": ["test_dataset"],
        "limitations": ["Synthetic test notebook."],
    }


def ready_model_diagnostics_quality_manifest() -> dict[str, Any]:
    manifest = ready_notebook_quality_manifest()
    manifest["figure_count"] = 5
    manifest["table_count"] = 2
    manifest["model_diagnostics"] = {
        "schema_version": "tablex_model_diagnostics_manifest.v1",
        "checks": [
            {
                "name": "permutation_importance",
                "status": "included",
                "evidence": ["notebooks/model_diagnostics.py"],
            },
            {
                "name": "native_feature_importance",
                "status": "not_applicable",
                "reason": "The fixture model is not a fitted tree model.",
            },
            {
                "name": "partial_dependence",
                "status": "included",
                "evidence": ["notebooks/model_diagnostics.py"],
            },
            {
                "name": "shap",
                "status": "needs_dependency",
                "reason": "The test runtime does not install shap.",
            },
        ],
    }
    return manifest


def run_queued_pipeline_registration_worker(db, store: LocalArtifactStore, project_id: str) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "register_prediction_pipeline")
        .order_by(Job.created_at.desc())
    )
    assert job is not None
    assert job.status == "queued"
    worker = SyncWorker(handlers={"register_prediction_pipeline": register_prediction_pipeline_handler}, store=store)
    worker.run_job(db, job)
    refreshed = db.get(Job, job.id)
    assert refreshed is not None
    return refreshed


def test_agent_session_marimo_notebook_outputs_are_analysis_notebooks() -> None:
    path = Path("notebooks/grandmaster_eda.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "data_understanding"


def test_agent_session_model_notebook_outputs_are_diagnostics_notebooks() -> None:
    path = Path("notebooks/salary_model_diagnostics.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "model_diagnostics"


def test_model_diagnostics_notebook_request_requires_diagnostic_manifest(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "model_diagnostics.py").write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    (requests_dir / "register_missing_diagnostics.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_missing_diagnostics",
                "operation": "register_notebook",
                "payload": {
                    "workspace_path": "notebooks/model_diagnostics.py",
                    "notebook_kind": "model_diagnostics",
                    "quality_manifest": ready_notebook_quality_manifest(),
                },
            }
        ),
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_model_diagnostics_manifest", name="Model Diagnostics Manifest")
        session = AgentSession(
            id="as_model_diagnostics_manifest",
            project_id=project.id,
            goal_text="Register model diagnostics notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_missing_diagnostics.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert ack["error"]["issues"][0]["code"] == "missing_model_diagnostics_manifest"


def test_prepare_session_workspace_exposes_backend_python_runtime(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    with sessionmaker(engine)() as db:
        project = Project(id="p_runtime", name="Runtime Project")
        db.add(project)
        db.flush()
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="runtime_dataset",
            filename="train.csv",
            text="x,y\n1,2\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_runtime",
            project_id=project.id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            source_ref="train.csv",
            row_count=1,
            column_count=2,
            schema_hash="runtime_schema",
        )
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="eda_profile",
            name="runtime_profile",
            filename="profile.json",
            text=dumps_json(
                {
                    "schema_version": "eda_profile.v1",
                    "profile_mode": "full",
                    "column_stat_scope": "full",
                    "sample_rows": [{"x": 1, "y": 2}],
                }
            ),
            metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
        )
        session = AgentSession(
            id="as_runtime",
            project_id=project.id,
            goal_text="Expose the notebook runtime.",
            workspace_path=str(workspace),
        )
        db.add_all([dataset, session])
        db.commit()

        prepared_workspace = prepare_session_workspace(db, store=store, project=project, session=session)
        db.commit()

    assert prepared_workspace == workspace
    assert (workspace / ".tablex" / "bin" / "python").exists()
    shim_executable = subprocess.check_output(
        [str(workspace / ".tablex" / "bin" / "python"), "-c", "import sys; print(sys.executable)"],
        text=True,
    ).strip()
    assert Path(shim_executable).resolve() == Path(sys.executable).resolve()
    assert notebook_requests_dir(workspace).is_dir()
    assert notebook_acks_dir(workspace).is_dir()
    assert (workspace / ".tablex" / "inbox").is_dir()
    protocol_path = workspace / ".tablex" / "PROTOCOL.md"
    assert protocol_path.exists()
    protocol_text = protocol_path.read_text(encoding="utf-8")
    assert ".tablex/requests/data/" in protocol_text
    assert ".tablex/requests/research_plan/" in protocol_text
    assert "reports/chat_update.md" in protocol_text
    assert (workspace / ".tablex" / "data_manifest.json").exists()
    assert (workspace / ".tablex" / "data" / "ds_runtime__train.csv").exists()
    data_manifest = loads_json((workspace / ".tablex" / "data_manifest.json").read_text(encoding="utf-8"), {})
    assert data_manifest["schema_version"] == "tablex_session_data_manifest.v1"
    assert data_manifest["root"] == ".tablex/data"
    assert data_manifest["cache_root"] == ".tablex/cache"
    assert "readable" in data_manifest["guarantee"]
    manifest_dataset = data_manifest["datasets"][0]
    assert manifest_dataset["fast_paths"]["profile_json"] == ".tablex/cache/dataset_profiles/ds_runtime__profile.json"
    assert manifest_dataset["fast_paths"]["sample_rows_json"] == ".tablex/cache/dataset_samples/ds_runtime__sample_rows.json"
    assert manifest_dataset["fast_paths"]["sample_rows_csv"] == ".tablex/cache/dataset_samples/ds_runtime__sample_rows.csv"
    assert (workspace / manifest_dataset["fast_paths"]["profile_json"]).exists()
    assert (workspace / manifest_dataset["fast_paths"]["sample_rows_json"]).exists()
    assert (workspace / manifest_dataset["fast_paths"]["sample_rows_csv"]).read_text(encoding="utf-8").splitlines()[0] == "x,y"
    context = loads_json((workspace / ".tablex" / "context.json").read_text(encoding="utf-8"), {})
    assert context["agent_capabilities"]["network_access_enabled"] is True
    assert context["agent_capabilities"]["web_search_enabled"] is True
    assert "register no_findings" in context["agent_capabilities"]["research_instruction"]
    assert context["protocol"]["path"] == ".tablex/PROTOCOL.md"
    prior_research = context["prior_research_status"]
    assert prior_research["schema_version"] == "prior_research_status.v1"
    assert prior_research["registered_report_count"] == 0
    assert "research_findings_report" in prior_research["completion_signal"]
    runtime = context["python_runtimes"]["tablex_backend"]
    assert runtime["workspace_python"] == str(workspace / ".tablex" / "bin" / "python")
    assert runtime["workspace_python_exists"] is True
    assert "marimo" in runtime["packages"]
    assert runtime["packages"]["japanize_matplotlib"]
    assert "tabpfn" in runtime["packages"]
    assert "catboost" in runtime["packages"]
    assert "torch" in runtime["packages"]
    assert "nvidia_smi_available" in runtime["gpu"]
    notebook_contract = context["output_contract"]["notebook_tool_requests"]
    assert notebook_contract["request_dir"] == ".tablex/requests/notebooks"
    assert notebook_contract["ack_dir"] == ".tablex/acks/notebooks"
    assert notebook_contract["schema_version"] == "tablex_notebook_request.v1"
    data_contract = context["output_contract"]["data_tool_requests"]
    task_spec_contract = data_contract["task_spec_contract"]
    assert data_contract["operations"] == ["set_primary_table", "register_derived_table", "commit_task_spec"]
    assert "supervised_regression" in task_spec_contract["task_shape_enum"]
    assert "supervised_classification" in task_spec_contract["task_shape_enum"]
    assert "distribution_prediction" in task_spec_contract["task_shape_enum"]
    assert "aggregate_prediction" in task_spec_contract["task_shape_enum"]
    assert "inverse_optimization" in task_spec_contract["task_shape_enum"]
    assert "regression" not in task_spec_contract["task_shape_enum"]
    assert "classification" not in task_spec_contract["task_shape_enum"]
    assert task_spec_contract["example_request"]["payload"]["task_spec"]["task_shape"] == "supervised_regression"
    target_example = task_spec_contract["example_request"]["payload"]["task_spec"]["targets"][0]
    assert target_example == {"table_ref": "ds_current", "column": "demand", "derivation": None}
    authoring_constraints = notebook_contract["register_notebook_contract"]["marimo_authoring_constraints"]
    assert any("unique across the notebook" in item for item in authoring_constraints)
    assert any("`.tablex/data`" in item for item in authoring_constraints)
    assert any("japanize_matplotlib" in item for item in authoring_constraints)
    research_contract = context["output_contract"]["research_tool_requests"]
    assert research_contract["schema_version"] == "tablex_research_request.v1"
    assert "source-backed findings" in research_contract["completion_contract"]
    assert "no_findings" in research_contract["completion_contract"]
    plan_contract = context["output_contract"]["research_plan_tool_requests"]["commit_revision_contract"]
    assert "research_findings" in plan_contract["known_output_types"]
    assert "prediction_pipeline" in plan_contract["known_output_types"]
    assert "model_diagnostics" in plan_contract["known_output_types"]
    assert "partial_dependence" in plan_contract["known_output_types"]
    assert "shap" in plan_contract["known_output_types"]
    assert "pilot_scoring" in plan_contract["known_output_types"]
    assert "validation_audit" in plan_contract["known_output_types"]
    pilot_contract = context["output_contract"]["pilot_tool_requests"]
    assert pilot_contract["schema_version"] == "tablex_pilot_request.v1"
    assert "register_validation_audit" in pilot_contract["operations"]
    assert "pilot observation envelope" in pilot_contract["observation_contract"]
    assert context["datasets"][0]["workspace_relative_path"] == ".tablex/data/ds_runtime__train.csv"
    assert context["dataset_access"]["root"] == ".tablex/data"
    assert context["dataset_access"]["cache_root"] == ".tablex/cache"
    assert "native marimo" in context["dataset_access"]["guarantee"]
    assert context["dataset_access"]["datasets"][0]["dataset_snapshot_id"] == "ds_runtime"
    assert context["dataset_access"]["datasets"][0]["workspace_relative_path"] == ".tablex/data/ds_runtime__train.csv"
    assert context["dataset_access"]["datasets"][0]["fast_paths"]["sample_rows_csv"] == ".tablex/cache/dataset_samples/ds_runtime__sample_rows.csv"
    assert context["dataset_access"]["files"][0]["workspace_relative_path"] == ".tablex/data/ds_runtime__train.csv"


def test_prepare_session_workspace_maps_container_data_path_on_host(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HARNESS_ARTIFACT_ROOT", str(data_dir / "artifacts"))
    get_settings.cache_clear()
    try:
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        Base.metadata.create_all(engine)
        store = LocalArtifactStore(data_dir / "artifacts")
        logical_workspace = Path("/data/artifacts/agent_sessions/p_logical/as_logical")
        physical_workspace = data_dir / "artifacts/agent_sessions/p_logical/as_logical"
        with sessionmaker(engine)() as db:
            project = Project(id="p_logical", name="Logical Path Project")
            session = AgentSession(
                id="as_logical",
                project_id=project.id,
                goal_text="Use the host runtime path.",
                workspace_path=str(logical_workspace),
            )
            db.add_all([project, session])
            db.commit()

            prepared_workspace = prepare_session_workspace(db, store=store, project=project, session=session)

        assert prepared_workspace == physical_workspace
        assert session.workspace_path == str(logical_workspace)
        assert (physical_workspace / ".tablex/context.json").is_file()
        assert (physical_workspace / ".tablex/data_manifest.json").is_file()
        context = loads_json((physical_workspace / ".tablex/context.json").read_text(encoding="utf-8"), {})
        assert context["dataset_access"]["manifest_path"] == str(
            physical_workspace / ".tablex/data_manifest.json"
        )
        assert context["python_runtimes"]["tablex_backend"]["workspace_python"] == str(
            physical_workspace / ".tablex/bin/python"
        )
    finally:
        get_settings.cache_clear()


def test_workspace_ingest_maps_container_path_and_processes_plan_request(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HARNESS_ARTIFACT_ROOT", str(data_dir / "artifacts"))
    get_settings.cache_clear()
    try:
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        Base.metadata.create_all(engine)
        store = LocalArtifactStore(data_dir / "artifacts")
        logical_workspace = Path("/data/artifacts/agent_sessions/p_ingest/as_ingest")
        physical_workspace = data_dir / "artifacts/agent_sessions/p_ingest/as_ingest"
        with sessionmaker(engine)() as db:
            project = Project(id="p_ingest", name="Mapped Ingest")
            session = AgentSession(
                id="as_ingest",
                project_id=project.id,
                goal_text="Keep the visible plan synchronized.",
                workspace_path=str(logical_workspace),
            )
            db.add_all([project, session])
            db.commit()
            prepare_session_workspace(db, store=store, project=project, session=session)
            initial_revision = db.scalar(
                select(ResearchPlanRevision)
                .where(ResearchPlanRevision.project_id == project.id)
                .order_by(ResearchPlanRevision.revision_index.desc())
            )
            assert initial_revision is not None
            next_document = loads_json(initial_revision.document_json, {})
            next_document["timeline_blocks"][0].update(
                {
                    "status": "done",
                    "no_output_required": True,
                    "no_output_required_rationale": "The empty test workspace needs no upload artifact.",
                }
            )
            next_document["timeline_blocks"][1]["status"] = "active"
            (physical_workspace / "reports/chat_update.md").write_text(
                "Objective framing is active.",
                encoding="utf-8",
            )
            request_dir = research_plan_requests_dir(physical_workspace)
            (request_dir / "advance_to_modeling.json").write_text(
                dumps_json(
                    {
                        "schema_version": "tablex_research_plan_request.v1",
                        "request_id": "advance_to_modeling",
                        "operation": "commit_revision",
                        "payload": {
                            "reason": "Advance the visible plan after workspace preparation.",
                            "document": next_document,
                        },
                    }
                ),
                encoding="utf-8",
            )

            ingest_session_workspace_outputs(
                db,
                store=store,
                project=project,
                session=session,
                workspace=physical_workspace,
            )
            db.commit()

            ack = loads_json(
                (research_plan_acks_dir(physical_workspace) / "advance_to_modeling.ack.json").read_text(
                    encoding="utf-8"
                ),
                {},
            )
            revision = db.scalar(
                select(ResearchPlanRevision)
                .where(ResearchPlanRevision.project_id == project.id)
                .order_by(ResearchPlanRevision.revision_index.desc())
            )

        assert ack["status"] == "succeeded", ack
        assert revision is not None
        document = loads_json(revision.document_json, {})
        active_nodes = [node["id"] for node in document["timeline_blocks"] if node["status"] == "active"]
        assert active_nodes == ["objective_framing"]
    finally:
        get_settings.cache_clear()


def test_agent_inbox_entries_are_enveloped_and_processed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    path = write_inbox_entry(
        workspace,
        kind="request",
        entry_type="progress_request",
        payload={"trigger": "test"},
        content="Update reports/chat_update.md.\n",
        title="Progress update requested",
    )

    entries = list_inbox_entries(workspace)
    assert len(entries) == 1
    assert entries[0]["schema_version"] == "tablex_inbox_entry.v1"
    assert entries[0]["kind"] == "request"
    assert entries[0]["type"] == "progress_request"
    assert entries[0]["payload"]["trigger"] == "test"
    assert entries[0]["content"] == "Update reports/chat_update.md.\n"

    mark_inbox_entry_processed(workspace, path, processed_by="test")
    processed = inbox_processed_path(workspace).read_text(encoding="utf-8")
    assert path.name in processed
    assert "test" in processed


def test_prediction_input_validation_failure_writes_codex_observation(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_prediction_input_feedback",
            name="Prediction input feedback",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="ags_prediction_input_feedback",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Repair prediction input issues.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_input",
            name="bad_prediction_input",
            filename="application.csv",
            text="row_id\nA\n",
            metadata={"project_id": project.id, "table_name": "application"},
        )
        artifact_id = artifact.id
        validation_report = {
            "schema_version": "prediction_input_validation_report.v1",
            "status": "failed",
            "table_name": "application",
            "observed_columns": ["row_id"],
            "expected_columns": [{"name": "x", "required": True}],
            "missing_columns": ["x"],
            "unexpected_columns": [],
            "dtype_checks": "not_available",
        }

        feedback = maybe_send_prediction_input_validation_failure_to_codex(
            db,
            project=project,
            artifact=artifact,
            pipeline_artifact_id="art_pipeline",
            table_name="application",
            batch_kind="external_test",
            validation_report=validation_report,
        )

        assert feedback["delivered"] is True
        event = db.get(AgentTranscriptEvent, feedback["transcript_event_id"])
        assert event is not None
        assert event.event_type == "prediction_input_validation_failed"
        event_payload = loads_json(event.payload_json, {})
        assert event_payload["validation_report"]["missing_columns"] == ["x"]

    entries = list_inbox_entries(workspace)
    prediction_feedback = [
        entry
        for entry in entries
        if entry["kind"] == "observation" and entry["type"] == "prediction_input_validation_failed"
    ]
    assert len(prediction_feedback) == 1
    assert prediction_feedback[0]["payload"]["artifact_id"] == artifact_id
    assert prediction_feedback[0]["payload"]["pipeline_artifact_id"] == "art_pipeline"
    assert prediction_feedback[0]["payload"]["validation_report"]["missing_columns"] == ["x"]
    assert "did not match the fixed input contract" in prediction_feedback[0]["content"]


def test_research_findings_request_registers_report_evidence_and_plan_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    report_path = workspace / "reports" / "prior.md"
    figure_path = workspace / "reports" / "figures" / "chart.png"
    figure_path.parent.mkdir(parents=True)
    figure_path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    report_path.write_text(
        "# Prior research\n\nThis is Codex-authored report text.\n\n![Validation chart](figures/chart.png)\n",
        encoding="utf-8",
    )
    request_dir = research_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "register_research.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_request.v1",
                "request_id": "register_research",
                "operation": "register_research_findings",
                "payload": {
                    "research_plan_node_id": "prior_research",
                    "report_workspace_path": "reports/prior.md",
                    "topic": "salary prediction prior knowledge",
                    "query_log": ["salary prediction job postings validation leakage"],
                    "sources": [
                        {
                            "url": "https://example.com/prior",
                            "title": "Prior source",
                            "source_type": "other",
                            "retrieved_at": "2026-07-06T00:00:00Z",
                            "key_claims": ["Group validation is useful when entities repeat."],
                            "reliability_notes": "Fixture source for request validation.",
                        }
                    ],
                    "findings": [
                        {
                            "claim": "Repeated companies should not be split across train and validation.",
                            "source_indexes": [0],
                            "implication_for_project": "Use company-aware validation when company_id is present.",
                            "recommended_action": "Register company-grouped split evidence before model comparison.",
                        }
                    ],
                    "no_findings": None,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_research_request", name="Research Request")
        session = AgentSession(
            id="as_research_request",
            project_id=project.id,
            goal_text="Register research findings.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {"id": "prior_research", "title": "Prior research", "granularity": "chapter", "status": "active"}
                ],
            },
            author_type="codex",
            reason="Prior research is underway.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_acks_dir(workspace) / "register_research.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        artifact = db.get(Artifact, ack["result"]["artifact_id"])
        assert artifact is not None
        assert artifact.asset_type == "research_findings_report"
        rich_report_artifact_id = ack["result"]["rich_report_artifact_id"]
        assert rich_report_artifact_id
        rich_report_artifact = db.get(Artifact, rich_report_artifact_id)
        assert rich_report_artifact is not None
        assert rich_report_artifact.asset_type == "research_markdown_report"
        assert artifact_primary_path(rich_report_artifact).read_text(encoding="utf-8").startswith("# Prior research")
        assert len(ack["result"]["figure_artifact_ids"]) == 1
        figure_artifact = db.get(Artifact, ack["result"]["figure_artifact_ids"][0])
        assert figure_artifact is not None
        assert figure_artifact.asset_type == "research_report_figure"
        evidence = db.scalar(select(Evidence).where(Evidence.project_id == project.id))
        assert evidence is not None
        assert evidence.evidence_type == "research_finding"
        assert evidence.source_artifact_id == artifact.id
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == artifact.id,
            )
        )
        assert edge is not None
        assert loads_json(edge.metadata_json, {})["node_id"] == "prior_research"
        rich_report_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "has_rich_report",
                LineageEdge.from_asset_id == artifact.id,
                LineageEdge.to_asset_id == rich_report_artifact_id,
            )
        )
        assert rich_report_edge is not None
        figure_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "references_figure",
                LineageEdge.from_asset_id == rich_report_artifact_id,
                LineageEdge.to_asset_id == figure_artifact.id,
            )
        )
        assert figure_edge is not None
        chat_artifact = db.scalar(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
                Artifact.metadata_json.contains("main_agent_session_research_registration"),
            )
        )
        assert chat_artifact is not None
        chat_payload = loads_json((Path(chat_artifact.uri) / "agent_chat_turn.json").read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "research_findings_registered"
        assert chat_payload["actions"][0]["target_tab"] == "Assets"
        assert chat_payload["actions"][0]["target_anchor"] == "assets-artifact-preview"
        assert chat_payload["actions"][0]["artifact_id"] == rich_report_artifact_id
        assert chat_payload["actions"][0]["asset_type"] == "research_markdown_report"
        assert artifact.id in chat_payload["actions"][0]["artifact_ids"]
        assert chat_payload["next_focus"]["target_anchor"] == "assets-artifact-preview"
        assert chat_payload["next_focus"]["artifact_id"] == rich_report_artifact_id
        assert chat_payload["next_focus"]["asset_type"] == "research_markdown_report"
        assert chat_payload["response_brief"]["rich_report_artifact_id"] == rich_report_artifact_id
        assert chat_payload["response_brief"]["source_count"] == 1
        assert chat_payload["response_brief"]["finding_count"] == 1
        context = build_session_context(db, project=project, session=session, response_locale="en-US")
        prior_research = context["prior_research_status"]
        assert prior_research["schema_version"] == "prior_research_status.v1"
        assert prior_research["registered_report_count"] == 1
        assert prior_research["source_count_total_latest"] == 1
        assert prior_research["finding_count_total_latest"] == 1
        assert prior_research["latest_reports"][0]["artifact_id"] == artifact.id
        assert prior_research["latest_reports"][0]["research_plan_node_id"] == "prior_research"

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "prior_research",
                        "title": "Prior research",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["research_findings"]},
                        "completion_evidence": [
                            {"output_type": "research_findings", "artifact_id": artifact.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered source-backed prior research findings.",
            strict_validation=True,
        )
        db.commit()
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert timeline["contract_validation"]["status"] == "ok"


def test_research_findings_request_rejects_out_of_range_source_index(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "bad_research.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_request.v1",
                "request_id": "bad_research",
                "operation": "register_research_findings",
                "payload": {
                    "topic": "bad source index",
                    "sources": [
                        {
                            "url": "https://example.com/source",
                            "title": "Source",
                            "source_type": "other",
                            "retrieved_at": "2026-07-06T00:00:00Z",
                            "key_claims": ["Claim"],
                        }
                    ],
                    "findings": [
                        {
                            "claim": "Finding",
                            "source_indexes": [1],
                            "implication_for_project": "Invalid index should fail.",
                            "recommended_action": "Fix the source_indexes field.",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_research_bad", name="Research Bad")
        session = AgentSession(
            id="as_research_bad",
            project_id=project.id,
            goal_text="Reject bad research findings.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_acks_dir(workspace) / "bad_research.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "out-of-range index" in ack["error"]["message"]
        rejection_text = research_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "tablex_research_request_rejection.v1" in rejection_text
        assert "bad_research" in rejection_text
        assert "out-of-range index" in rejection_text
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "research_request_failed",
            )
        )
        assert event is not None
        chat_artifact = db.scalar(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
            )
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "research_request_failed"
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.project_id == project.id)) == 0


def test_research_findings_request_registers_explicit_no_findings(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "no_findings.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_request.v1",
                "request_id": "no_findings",
                "operation": "register_research_findings",
                "payload": {
                    "topic": "domain search with no useful result",
                    "query_log": ["very specific tablex fixture query"],
                    "sources": [],
                    "findings": [],
                    "no_findings": {
                        "searched_queries": ["very specific tablex fixture query"],
                        "rationale": "The search did not produce a source that changes the project plan.",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_research_none", name="Research None")
        session = AgentSession(
            id="as_research_none",
            project_id=project.id,
            goal_text="Register no findings.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_acks_dir(workspace) / "no_findings.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        evidence = db.scalar(select(Evidence).where(Evidence.project_id == project.id))
        assert evidence is not None
        assert evidence.evidence_type == "research_no_findings"


def test_agent_session_research_plan_json_outputs_are_research_plans() -> None:
    assert asset_type_for_session_output(Path("outputs/research_plan.json")) == "research_plan"
    assert asset_type_for_session_output(Path("artifacts/research_plan_timeline.json")) == "research_plan"


def test_process_timeout_attention_message_is_human_readable() -> None:
    message = attention_chat_message(
        "process_timeout",
        details={"idle_timeout_seconds": 900},
        japanese=True,
    )

    assert "15分" in message
    assert "作業状態を保ったまま再開します" in message
    assert "traceback" not in message.lower()


def test_agent_session_raw_codex_transcript_outputs_are_transcript_artifacts() -> None:
    path = Path(f"artifacts/{CODEX_RAW_TRANSCRIPT_FILENAME}")

    assert asset_type_for_session_output(path) == "agent_session_transcript"
    assert metadata_for_session_output(path) == {"transcript_kind": "codex_cli_stdout_jsonl", "raw_codex_cli": True}


def test_agent_session_codex_stderr_outputs_are_log_artifacts() -> None:
    path = Path(f"artifacts/{CODEX_STDERR_LOG_FILENAME}")

    assert asset_type_for_session_output(path) == "agent_session_log"
    assert metadata_for_session_output(path) == {"transcript_kind": "codex_cli_stderr", "raw_codex_cli": True}


def test_workspace_output_artifact_names_include_relative_path_to_avoid_stem_collisions(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    reports_summary = workspace / "reports" / "summary.md"
    outputs_summary = workspace / "outputs" / "summary.md"
    reports_summary.parent.mkdir(parents=True)
    outputs_summary.parent.mkdir(parents=True)
    reports_summary.write_text("Reports summary", encoding="utf-8")
    outputs_summary.write_text("Outputs summary", encoding="utf-8")

    with session_factory() as db:
        project = Project(id="p_collision", name="Collision Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_collision",
            project_id=project.id,
            goal_text="Register outputs without name collisions.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        reports_name = session_output_artifact_name(session.id, reports_summary.relative_to(workspace))
        outputs_name = session_output_artifact_name(session.id, outputs_summary.relative_to(workspace))

        assert reports_name != outputs_name
        assert "reports_summary_md" in reports_name
        assert "outputs_summary_md" in outputs_name

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_session_report")
                .order_by(Artifact.name.asc())
            )
        )
        assert len(artifacts) == 2
        assert {artifact.name for artifact in artifacts} == {reports_name, outputs_name}
        assert {
            loads_json(artifact.metadata_json, {})["workspace_relative_path"]
            for artifact in artifacts
        } == {"reports/summary.md", "outputs/summary.md"}

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifact_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_session_report")
        )
        assert artifact_count == 2


def test_codex_stream_lines_are_persisted_and_published_without_rewriting_stdout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stdout_line = '{"type":"thread.started","thread_id":"abc"}\n'
    stderr_line = "2026-07-03T00:00:00Z ERROR example\n"

    append_runner_stream_to_workspace(workspace, stream_name="stdout", line=stdout_line)
    append_runner_stream_to_workspace(workspace, stream_name="stderr", line=stderr_line)

    assert raw_codex_transcript_path(workspace).read_text(encoding="utf-8") == stdout_line
    assert raw_codex_stderr_path(workspace).read_text(encoding="utf-8") == stderr_line

    published = publish_raw_codex_transcript_snapshot(workspace)

    assert workspace / "artifacts" / CODEX_RAW_TRANSCRIPT_FILENAME in published
    assert workspace / "artifacts" / CODEX_STDERR_LOG_FILENAME in published
    assert (workspace / "artifacts" / CODEX_RAW_TRANSCRIPT_FILENAME).read_text(encoding="utf-8") == stdout_line
    assert (workspace / "artifacts" / CODEX_STDERR_LOG_FILENAME).read_text(encoding="utf-8") == stderr_line


def test_stream_file_tailer_reads_new_complete_lines_without_replaying_prefix(tmp_path: Path) -> None:
    path = tmp_path / "codex_raw_transcript.jsonl"
    path.write_text('{"type":"thread.started"}\n', encoding="utf-8")
    tailer = StreamFileTailer(path, offset=path.stat().st_size)

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"turn.started"}\n{"type"')

    assert tailer.read_completed_lines() == ['{"type":"turn.started"}\n']

    with path.open("a", encoding="utf-8") as handle:
        handle.write(':"item.completed"}\n')

    assert tailer.read_completed_lines() == ['{"type":"item.completed"}\n']
    assert tailer.read_completed_lines() == []


def test_codex_cli_turn_streaming_uses_workspace_file_transcript(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
if [ "$1" = "sandbox" ]; then
  exit 0
fi
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"thread.started","thread_id":"thread_file_tail"}'
printf '%s\n' '{"type":"turn.started"}'
printf '%s\n' 'fake stderr line' >&2
printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}'
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        user = User(id="u_file_tail", email="file-tail@example.com", locale="ja-JP")
        project = Project(id="p_file_tail", name="File Tail", created_by=user.id)
        session = AgentSession(
            id="as_file_tail",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([user, project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content="この依頼を処理してください。",
            payload={},
        )
        db.commit()

    with session_factory() as db:
        project = db.get(Project, "p_file_tail")
        session = db.get(AgentSession, "as_file_tail")
        assert project is not None
        assert session is not None
        prompt = build_turn_prompt(db, project=project, session=session)
        assert "この依頼を処理してください。" in prompt.text
        assert prompt.delivered_user_event_indexes

    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_file_tail",
        session_id="as_file_tail",
        workspace=workspace,
        prompt=prompt.text,
        delivered_user_event_indexes=prompt.delivered_user_event_indexes,
        agent_model=None,
        timeout_seconds=30,
    )

    assert return_code == 0
    assert '"thread_id":"thread_file_tail"' in raw_codex_transcript_path(workspace).read_text(encoding="utf-8")
    assert raw_codex_stderr_path(workspace).read_text(encoding="utf-8") == "fake stderr line\n"
    assert progress_request_path(workspace).exists()
    assert "locale: ja-JP" in progress_request_path(workspace).read_text(encoding="utf-8")

    with session_factory() as db:
        session = db.get(AgentSession, "as_file_tail")
        assert session is not None
        assert session.codex_thread_id == "thread_file_tail"
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_file_tail")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert [event.event_type for event in events if event.source == "codex_cli"] == [
        "thread.started",
        "turn.started",
        "item.completed",
        "process_exited",
    ]
    process_started = next(event for event in events if event.event_type == "process_started")
    assert loads_json(process_started.payload_json, {})["stdout_mode"] == "workspace_file_tail"

    with session_factory() as db:
        project = db.get(Project, "p_file_tail")
        session = db.get(AgentSession, "as_file_tail")
        assert project is not None
        assert session is not None
        prompt_after_success = build_turn_prompt(db, project=project, session=session)
        assert "この依頼を処理してください。" not in prompt_after_success.text


def test_codex_cli_turn_failure_does_not_mark_user_instructions_delivered(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
if [ "$1" = "sandbox" ]; then
  exit 0
fi
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"turn.started"}'
printf '%s\n' 'simulated failure' >&2
exit 2
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        project = Project(id="p_retry_prompt", name="Retry Prompt")
        session = AgentSession(
            id="as_retry_prompt",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content="失敗しても次のturnで再度読んでください。",
            payload={},
        )
        db.commit()

    with session_factory() as db:
        project = db.get(Project, "p_retry_prompt")
        session = db.get(AgentSession, "as_retry_prompt")
        assert project is not None
        assert session is not None
        prompt = build_turn_prompt(db, project=project, session=session)
        assert "失敗しても次のturnで再度読んでください。" in prompt.text
        assert prompt.delivered_user_event_indexes

    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_retry_prompt",
        session_id="as_retry_prompt",
        workspace=workspace,
        prompt=prompt.text,
        delivered_user_event_indexes=prompt.delivered_user_event_indexes,
        agent_model=None,
        timeout_seconds=30,
    )

    assert return_code == 2
    with session_factory() as db:
        project = db.get(Project, "p_retry_prompt")
        session = db.get(AgentSession, "as_retry_prompt")
        assert project is not None
        assert session is not None
        retry_prompt = build_turn_prompt(db, project=project, session=session)
        assert "失敗しても次のturnで再度読んでください。" in retry_prompt.text
        delivered_events = list(
            db.scalars(
                select(AgentTranscriptEvent).where(
                    AgentTranscriptEvent.session_id == "as_retry_prompt",
                    AgentTranscriptEvent.event_type == "user_instructions_delivered_to_codex",
                )
            )
        )
        assert delivered_events == []


def test_codex_cli_turn_start_silence_recovers_with_chat_and_activity(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
if [ "$1" = "sandbox" ]; then
  exit 0
fi
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"thread.started","thread_id":"thread_silent"}'
/bin/sleep 30
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        user = User(id="u_silent", email="silent@example.com", locale="ja-JP")
        project = Project(id="p_silent", name="Silent Turn", created_by=user.id)
        session = AgentSession(
            id="as_silent",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
        )
        db.add_all([user, project, session])
        db.commit()

    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_silent",
        session_id="as_silent",
        workspace=workspace,
        prompt="hello",
        delivered_user_event_indexes=(),
        agent_model=None,
        timeout_seconds=30,
        turn_start_silence_timeout_seconds=1,
    )

    assert return_code not in {0, None}
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_silent")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        chat_artifacts = list(
            db.scalars(
                select(Artifact).where(
                    Artifact.project_id == "p_silent",
                    Artifact.asset_type == "agent_chat_turn",
                )
            )
        )

    timeout_events = [event for event in events if event.event_type == "process_timeout"]
    assert timeout_events
    assert loads_json(timeout_events[-1].payload_json, {})["timeout_kind"] == "turn_start_silence"
    assert any(event.event_type == "thread.started" for event in events)
    assert chat_artifacts
    stored_payloads = []
    for artifact in chat_artifacts:
        path = artifact_primary_path(artifact)
        if path.exists():
            stored_payloads.append(loads_json(path.read_text(encoding="utf-8"), {}))
    assert any(payload.get("intent", {}).get("message_kind") == "turn_start_silence" for payload in stored_payloads)
    assert any(payload.get("worker_events") for payload in stored_payloads)


def test_attention_chat_turn_dedupes_within_30_minute_window(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        user = User(id="u_attention", email="attention@example.com", locale="ja-JP")
        project = Project(id="p_attention", name="Attention Project", created_by=user.id)
        session = AgentSession(id="as_attention", project_id=project.id, goal_text="Continue.")
        db.add_all([user, project, session])
        db.commit()

        first = register_agent_session_attention_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            attention_key="process_timeout:idle:900",
            status="waiting",
            message_kind="process_timeout",
            details={"idle_timeout_seconds": 900},
        )
        second = register_agent_session_attention_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            attention_key="process_timeout:idle:900",
            status="waiting",
            message_kind="process_timeout",
            details={"idle_timeout_seconds": 900},
        )
        assert first is not None
        assert second is None
        first.created_at = utc_now() - timedelta(minutes=31)
        db.commit()

        third = register_agent_session_attention_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            attention_key="process_timeout:idle:900",
            status="waiting",
            message_kind="process_timeout",
            details={"idle_timeout_seconds": 900},
        )
        assert third is not None


def test_codex_cli_turn_streaming_cancels_when_supervisor_lease_is_lost(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
if [ "$1" = "sandbox" ]; then
  exit 0
fi
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"thread.started","thread_id":"thread_cancel"}'
/bin/sleep 30
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        project = Project(id="p_cancel_tail", name="Cancel Tail")
        session = AgentSession(
            id="as_cancel_tail",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

    cancel_event = threading.Event()
    cancel_event.set()
    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_cancel_tail",
        session_id="as_cancel_tail",
        workspace=workspace,
        prompt="hello",
        delivered_user_event_indexes=(),
        agent_model=None,
        timeout_seconds=30,
        cancel_event=cancel_event,
    )

    assert return_code not in {0, None}
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_cancel_tail")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
    event_types = [event.event_type for event in events]
    assert "process_cancelled" in event_types
    assert "process_exited" in event_types
    assert raw_codex_transcript_path(workspace).read_text(encoding="utf-8").strip()


def test_codex_stream_lines_are_indexed_in_one_batch(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_stream_batch", name="Stream Batch")
        session = AgentSession(id="as_stream_batch", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    append_codex_stream_lines(
        session_factory,
        project_id="p_stream_batch",
        session_id="as_stream_batch",
        lines=[
            ("stdout", '{"type":"thread.started","thread_id":"thread_1"}\n'),
            ("stdout", '{"type":"turn.started"}\n'),
            ("stderr", "warning line\n"),
        ],
    )

    with session_factory() as db:
        session = db.get(AgentSession, "as_stream_batch")
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_stream_batch")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert session is not None
    assert session.codex_thread_id == "thread_1"
    assert [event.event_index for event in events] == [0, 1, 2]
    assert [event.event_type for event in events] == ["thread.started", "turn.started", "codex_stderr"]
    assert events[-1].source == "codex_cli_stderr"


def test_supervisor_thread_releases_slot_when_global_runner_is_replaced(tmp_path: Path, monkeypatch: Any) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(id="p_slot_release", name="Slot Release")
        session = AgentSession(id="as_slot_release", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    calls: list[str] = []

    def fake_runner(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("ran")

    monkeypatch.setattr(agent_sessions_module, "run_main_agent_session_supervisor", fake_runner)

    thread = start_main_agent_session_supervisor_thread(
        session_factory,
        store,
        project_id="p_slot_release",
        session_id="as_slot_release",
    )

    assert thread is not None
    thread.join(timeout=2)
    assert calls == ["ran"]
    assert supervisor_slot_active("as_slot_release") is False


def test_startup_supervisor_recovers_full_auto_project_without_browser_polling(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_startup_recover",
            name="Startup Recover",
            autonomy_mode="full_auto",
            current_phase="AUTONOMOUS_LOOP",
        )
        db.add(project)
        db.commit()

    launched: list[tuple[str, str]] = []

    def fake_runner(
        session_factory_arg: object,
        store_arg: object,
        *,
        project_id: str,
        session_id: str,
        **kwargs: object,
    ) -> None:
        del session_factory_arg, store_arg, kwargs
        launched.append((project_id, session_id))

    threads = start_active_main_session_supervisors(
        session_factory,
        store,
        supervisor_runner=fake_runner,
    )

    assert threads == []
    assert len(launched) == 1
    assert launched[0][0] == "p_startup_recover"

    with session_factory() as db:
        session = db.get(AgentSession, launched[0][1])
        assert session is not None
        assert session.session_type == "main_autonomous"
        assert session.status == "starting"
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == session.id)
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert [event.event_type for event in events] == ["session_created"]


def test_startup_supervisor_clears_dead_stored_pid_before_launch(tmp_path: Path, monkeypatch: Any) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(agent_sessions_module, "pid_is_alive", lambda pid: False)

    with session_factory() as db:
        project = Project(
            id="p_startup_dead_pid",
            name="Startup Dead PID",
            autonomy_mode="full_auto",
            current_phase="AUTONOMOUS_LOOP",
        )
        session = AgentSession(
            id="as_startup_dead_pid",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue the existing session.",
            pid=987654321,
        )
        db.add_all([project, session])
        db.commit()

    launched: list[tuple[str, str]] = []

    def fake_runner(
        session_factory_arg: object,
        store_arg: object,
        *,
        project_id: str,
        session_id: str,
        **kwargs: object,
    ) -> None:
        del session_factory_arg, store_arg, kwargs
        launched.append((project_id, session_id))

    start_active_main_session_supervisors(
        session_factory,
        store,
        supervisor_runner=fake_runner,
    )

    assert launched == [("p_startup_dead_pid", "as_startup_dead_pid")]
    with session_factory() as db:
        session = db.get(AgentSession, "as_startup_dead_pid")
        assert session is not None
        assert session.pid is None
        assert session.status == "between_turns"
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == session.id)
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert [event.event_type for event in events] == ["startup_dead_runner_pid_cleared"]
        payload = loads_json(events[0].payload_json, {})
        assert payload["previous_pid"] == 987654321
        assert payload["process_alive"] is False


def test_startup_supervisor_does_not_emit_stale_pid_event_when_local_slot_is_active(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(agent_sessions_module, "pid_is_alive", lambda pid: True)

    with session_factory() as db:
        project = Project(
            id="p_startup_active_slot",
            name="Startup Active Slot",
            autonomy_mode="full_auto",
            current_phase="AUTONOMOUS_LOOP",
        )
        session = AgentSession(
            id="as_startup_active_slot",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue the existing session.",
            pid=12345,
        )
        db.add_all([project, session])
        db.commit()

    assert agent_sessions_module.acquire_supervisor_slot("as_startup_active_slot")
    try:
        launched: list[tuple[str, str]] = []

        def fake_runner(
            session_factory_arg: object,
            store_arg: object,
            *,
            project_id: str,
            session_id: str,
            **kwargs: object,
        ) -> None:
            del session_factory_arg, store_arg, kwargs
            launched.append((project_id, session_id))

        start_active_main_session_supervisors(
            session_factory,
            store,
            supervisor_runner=fake_runner,
        )
    finally:
        agent_sessions_module.release_supervisor_slot("as_startup_active_slot")

    assert launched == []
    with session_factory() as db:
        events = list(db.scalars(select(AgentTranscriptEvent).where(AgentTranscriptEvent.session_id == "as_startup_active_slot")))
        assert events == []


def test_startup_supervisor_does_not_emit_stale_pid_event_when_cross_process_lease_is_active(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(agent_sessions_module, "pid_is_alive", lambda pid: True)

    with session_factory() as db:
        project = Project(
            id="p_startup_active_lease",
            name="Startup Active Lease",
            autonomy_mode="full_auto",
            current_phase="AUTONOMOUS_LOOP",
        )
        session = AgentSession(
            id="as_startup_active_lease",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Continue the existing session.",
            pid=23456,
        )
        db.add_all([project, session])
        db.commit()

    assert acquire_supervisor_lease(
        session_factory,
        session_id="as_startup_active_lease",
        owner_id="other-supervisor",
        ttl_seconds=60,
    )
    try:
        launched: list[tuple[str, str]] = []

        def fake_runner(
            session_factory_arg: object,
            store_arg: object,
            *,
            project_id: str,
            session_id: str,
            **kwargs: object,
        ) -> None:
            del session_factory_arg, store_arg, kwargs
            launched.append((project_id, session_id))

        start_active_main_session_supervisors(
            session_factory,
            store,
            supervisor_runner=fake_runner,
        )
    finally:
        release_supervisor_lease(
            session_factory,
            session_id="as_startup_active_lease",
            owner_id="other-supervisor",
        )

    assert launched == []
    with session_factory() as db:
        events = list(db.scalars(select(AgentTranscriptEvent).where(AgentTranscriptEvent.session_id == "as_startup_active_lease")))
        assert events == []


def test_agent_supervisor_lease_prevents_duplicate_cross_process_owners(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_lease", name="Lease Project")
        session = AgentSession(id="as_lease", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    assert acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)
    assert not acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b", ttl_seconds=60)
    assert renew_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)

    with session_factory() as db:
        lease = db.get(AgentSupervisorLease, "as_lease")
        assert lease is not None
        lease.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    assert acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b", ttl_seconds=60)
    assert not renew_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)

    release_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a")
    with session_factory() as db:
        assert db.get(AgentSupervisorLease, "as_lease") is not None

    release_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b")
    with session_factory() as db:
        assert db.get(AgentSupervisorLease, "as_lease") is None


def test_supervisor_lease_heartbeat_signals_lost_lease(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_lease_heartbeat", name="Lease Heartbeat")
        session = AgentSession(id="as_lease_heartbeat", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    assert acquire_supervisor_lease(
        session_factory,
        session_id="as_lease_heartbeat",
        owner_id="owner-a",
        ttl_seconds=30,
    )
    stop_event, lease_lost_event, thread = start_supervisor_lease_heartbeat(
        session_factory,
        session_id="as_lease_heartbeat",
        owner_id="owner-a",
        ttl_seconds=3,
    )
    try:
        with session_factory() as db:
            lease = db.get(AgentSupervisorLease, "as_lease_heartbeat")
            assert lease is not None
            lease.owner_id = "owner-b"
            db.commit()

        deadline = time.monotonic() + 5
        while not lease_lost_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)

        assert lease_lost_event.is_set()
        with session_factory() as db:
            lease = db.get(AgentSupervisorLease, "as_lease_heartbeat")
            assert lease is not None
            assert lease.owner_id == "owner-b"
    finally:
        stop_event.set()
        thread.join(timeout=2)


def test_main_supervisor_stops_before_runner_when_lease_is_lost(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_lease_lost_supervisor",
            name="Lease Lost Supervisor",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_lease_lost_supervisor",
            project_id=project.id,
            goal_text="Continue.",
            status="between_turns",
        )
        db.add_all([project, session])
        db.commit()

    lost_event = threading.Event()
    lost_event.set()
    stop_event = threading.Event()
    dummy_thread = threading.Thread(target=lambda: None)
    dummy_thread.start()
    dummy_thread.join(timeout=1)

    monkeypatch.setattr(
        agent_sessions_module,
        "start_supervisor_lease_heartbeat",
        lambda *args, **kwargs: (stop_event, lost_event, dummy_thread),
    )
    runner_calls: list[str] = []

    def fail_if_runner_starts(*args: object, **kwargs: object) -> int:
        del args, kwargs
        runner_calls.append("started")
        return 0

    monkeypatch.setattr(agent_sessions_module, "run_codex_cli_turn_streaming", fail_if_runner_starts)

    agent_sessions_module.run_main_agent_session_supervisor(
        session_factory,
        store,
        project_id="p_lease_lost_supervisor",
        session_id="as_lease_lost_supervisor",
        max_turns=1,
        slot_acquired=True,
        lease_owner_id="owner-a",
    )

    assert runner_calls == []
    assert stop_event.is_set()
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_lease_lost_supervisor")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert [event.event_type for event in events] == ["supervisor_lease_lost"]
        assert db.get(AgentSupervisorLease, "as_lease_lost_supervisor") is None


def test_transcript_index_reservation_continues_after_sidecar_event(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_index_reservation", name="Index Reservation")
        session = AgentSession(id="as_index_reservation", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    with session_factory() as db:
        session = db.get(AgentSession, "as_index_reservation")
        assert session is not None
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="progress_update_requested",
            role="harness",
            title="Progress update requested",
            content="Progress update requested.",
            payload={},
        )
        db.commit()

    append_codex_stream_lines(
        session_factory,
        project_id="p_index_reservation",
        session_id="as_index_reservation",
        lines=[
            ("stdout", '{"type":"thread.started","thread_id":"thread_2"}\n'),
            ("stdout", '{"type":"turn.started"}\n'),
        ],
    )

    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_index_reservation")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert [event.event_index for event in events] == [0, 1, 2]
    assert [event.event_type for event in events] == [
        "progress_update_requested",
        "thread.started",
        "turn.started",
    ]


def test_transcript_index_reservation_is_shared_across_database_sessions(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_id = "as_database_index"

    with sessionmaker(engine)() as db:
        project = Project(id="p_database_index", name="Database Index")
        session = AgentSession(id=session_id, project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.flush()
        db.add(
            AgentTranscriptEvent(
                id="agte_existing_index",
                project_id=project.id,
                session_id=session.id,
                event_index=41,
                source="tablex_sidecar",
                event_type="existing",
            )
        )
        db.commit()

    with sessionmaker(engine)() as first_db:
        assert reserve_transcript_event_indexes(first_db, session_id=session_id, count=2) == 42
        first_db.commit()

    with sessionmaker(engine)() as second_db:
        assert reserve_transcript_event_indexes(second_db, session_id=session_id, count=3) == 44
        second_db.commit()

    assert agent_sessions_module._TRANSCRIPT_EVENT_NEXT_INDEX[session_id] == 47


def test_transcript_index_reservation_serializes_concurrent_database_writers(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"timeout": 10},
    )
    Base.metadata.create_all(engine)
    session_id = "as_concurrent_database_index"
    with sessionmaker(engine)() as db:
        project = Project(id="p_concurrent_database_index", name="Concurrent Database Index")
        session = AgentSession(id=session_id, project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    barrier = threading.Barrier(2)
    reservations: list[int] = []
    errors: list[Exception] = []

    def reserve() -> None:
        try:
            with sessionmaker(engine)() as db:
                barrier.wait(timeout=5)
                reservations.append(reserve_transcript_event_indexes(db, session_id=session_id, count=1))
                time.sleep(0.05)
                db.commit()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve), threading.Thread(target=reserve)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(reservations) == [0, 1]


def test_sqlite_schema_sync_repairs_duplicate_transcript_indexes(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_index_repair", name="Index Repair")
        session = AgentSession(id="as_index_repair", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.add_all(
            [
                AgentTranscriptEvent(
                    id="agte_dup_1",
                    project_id=project.id,
                    session_id=session.id,
                    event_index=0,
                    source="tablex_sidecar",
                    event_type="first",
                    payload_json="{}",
                ),
                AgentTranscriptEvent(
                    id="agte_dup_2",
                    project_id=project.id,
                    session_id=session.id,
                    event_index=0,
                    source="codex_cli",
                    event_type="second",
                    payload_json="{}",
                ),
            ]
        )
        db.commit()

    ensure_sqlite_mvp_columns(engine)

    with engine.connect() as connection:
        duplicates = list(
            connection.execute(
                select(AgentTranscriptEvent.session_id, AgentTranscriptEvent.event_index)
                .group_by(AgentTranscriptEvent.session_id, AgentTranscriptEvent.event_index)
                .having(func.count() > 1)
            )
        )
        indexes = [row[1] for row in connection.exec_driver_sql("PRAGMA index_list(agent_transcript_events)")]
        artifact_indexes = [row[1] for row in connection.exec_driver_sql("PRAGMA index_list(artifacts)")]

    assert duplicates == []
    assert "ux_agent_transcript_events_session_index" in indexes
    assert "ix_artifacts_project_created" in artifact_indexes
    assert "ix_artifacts_project_type_created" in artifact_indexes


def test_session_output_artifact_name_uses_relative_path_to_avoid_stem_collisions() -> None:
    report_name = session_output_artifact_name("as_path", Path("reports/summary.md"))
    output_name = session_output_artifact_name("as_path", Path("outputs/summary.md"))
    markdown_report_name = session_output_artifact_name("as_path", Path("reports/salary_band_report.md"))
    html_report_name = session_output_artifact_name("as_path", Path("reports/salary_band_report.html"))

    assert report_name != output_name
    assert markdown_report_name != html_report_name
    assert "reports_summary_md" in report_name
    assert "outputs_summary_md" in output_name
    assert "reports_salary_band_report_md" in markdown_report_name
    assert "reports_salary_band_report_html" in html_report_name


def test_session_workspace_ingest_rejects_static_html_outputs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    report_path = workspace / "reports" / "grandmaster_eda_static.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html><body>static notebook snapshot</body></html>", encoding="utf-8")

    assert asset_type_for_session_output(Path("reports/grandmaster_eda_static.html")) == "agent_session_output"

    with sessionmaker(engine)() as db:
        project = Project(id="p_reject_html", name="Reject HTML")
        session = AgentSession(
            id="as_reject_html",
            project_id=project.id,
            goal_text="Reject static notebook HTML.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        registered_paths = [
            loads_json(artifact.metadata_json, {}).get("workspace_relative_path")
            for artifact in db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
        ]
        assert "reports/grandmaster_eda_static.html" not in registered_paths

        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "workspace_output_rejected",
            )
        )
        assert event is not None
        event_payload = loads_json(event.payload_json, {})
        assert event_payload["workspace_relative_path"] == "reports/grandmaster_eda_static.html"
        assert event_payload["policy"] == "native_marimo_source_required"

        rejection_entries = [
            entry for entry in list_inbox_entries(workspace) if entry["kind"] == "rejection" and entry["type"] == "session_output_rejection"
        ]
        assert len(rejection_entries) == 1
        rejection_text = rejection_entries[0]["content"]
        assert "tablex_session_output_rejection.v1" in rejection_text
        assert "reports/grandmaster_eda_static.html" in rejection_text
        assert ".tablex/requests/notebooks/" in rejection_text

        chat = db.scalar(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
            )
        )
        assert chat is not None
        chat_metadata = loads_json(chat.metadata_json, {})
        assert chat_metadata["source"] == "main_agent_session_attention"
        assert chat_metadata["message_kind"] == "static_html_output_rejected"
        chat_payload = loads_json((Path(chat.uri) / "agent_chat_turn.json").read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "static_html_output_rejected"
        assert "grandmaster_eda_static.html" in chat_payload["assistant_message"]


def test_session_workspace_ingest_rejects_non_marimo_python_notebook_outputs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebook_path = workspace / "notebooks" / "analysis.py"
    notebook_path.parent.mkdir(parents=True)
    notebook_path.write_text("print('this is a script, not a marimo notebook')\n", encoding="utf-8")

    assert asset_type_for_session_output(Path("notebooks/analysis.py")) == "analysis_notebook"

    with sessionmaker(engine)() as db:
        project = Project(id="p_reject_non_marimo_py", name="Reject Non Marimo Python")
        session = AgentSession(
            id="as_reject_non_marimo_py",
            project_id=project.id,
            goal_text="Reject non-marimo notebook-looking Python files.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is None

        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "workspace_output_rejected",
            )
        )
        assert event is not None
        event_payload = loads_json(event.payload_json, {})
        assert event_payload["workspace_relative_path"] == "notebooks/analysis.py"
        assert event_payload["reason"] == "notebook_python_source_must_be_native_marimo"

        rejection_entries = [
            entry for entry in list_inbox_entries(workspace) if entry["kind"] == "rejection" and entry["type"] == "session_output_rejection"
        ]
        assert len(rejection_entries) == 1
        rejection_text = rejection_entries[0]["content"]
        assert "notebooks/analysis.py" in rejection_text
        assert "notebook_python_source_must_be_native_marimo" in rejection_text

        chat = db.scalar(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
            )
        )
        assert chat is not None
        chat_metadata = loads_json(chat.metadata_json, {})
        assert chat_metadata["source"] == "main_agent_session_attention"
        assert chat_metadata["message_kind"] == "notebook_source_rejected"


def test_session_output_registration_throttles_fast_intermediate_versions(tmp_path: Path) -> None:
    existing_path = tmp_path / "stored" / "report.md"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("old", encoding="utf-8")
    workspace_path = tmp_path / "workspace" / "reports" / "report.md"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("new", encoding="utf-8")
    existing = Artifact(
        id="art_recent",
        project_id="p_recent",
        asset_type="agent_session_report",
        name="agent_session_report",
        version=1,
        uri=str(existing_path.parent),
        content_hash="old",
        metadata_json=dumps_json({"primary_path": str(existing_path)}),
        created_at=utc_now(),
    )

    assert should_register_session_output(workspace_path, existing) is False

    existing.created_at = utc_now() - timedelta(seconds=45)
    assert should_register_session_output(workspace_path, existing) is True


def test_turn_prompt_delivers_all_undelivered_user_instructions_beyond_recent_raw_window(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_prompt", name="Prompt Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_prompt",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content="評価指標はROC-AUCにしてください。",
            payload={},
        )
        for index in range(120):
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="item.completed",
                role="runner",
                title="Codex event",
                content=f"raw event {index}",
                payload={"type": "item.completed"},
            )
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)
        assert "評価指標はROC-AUCにしてください。" in prompt.text
        assert prompt.delivered_user_event_indexes

        mark_user_instructions_delivered(
            session_factory,
            session_id=session.id,
            delivered_user_event_indexes=prompt.delivered_user_event_indexes,
        )
        prompt_after_delivery = build_turn_prompt(db, project=project, session=session)
        assert "評価指標はROC-AUCにしてください。" not in prompt_after_delivery.text


def test_chat_update_marks_delivered_agent_chat_job_succeeded(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    report_path = workspace / "reports" / "chat_update.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "給与データの粒度を確認しています。\n\n次に会社テーブルとのjoin coverageを見ます。",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_chat_complete",
            name="Chat Complete",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_chat_complete",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Keep the user informed.",
            workspace_path=str(workspace),
        )
        other_session = AgentSession(
            id="as_other_chat",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Other session.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session, other_session])
        db.flush()
        chat_job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "状況を説明してください",
                "locale": "ja-JP",
                "delivered_agent_session_id": session.id,
            },
            priority=90,
        )
        unrelated_job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "別セッションです",
                "locale": "ja-JP",
                "delivered_agent_session_id": other_session.id,
            },
            priority=90,
        )
        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_report",
            name="agent_session_reports_chat_update_md",
            filename="chat_update.md",
            text=report_path.read_text(encoding="utf-8"),
            metadata={"project_id": project.id, "agent_session_id": session.id},
        )

        maybe_register_chat_update_from_workspace_output(
            db,
            store=store,
            project=project,
            session=session,
            path=report_path,
            artifact=source_artifact,
        )
        db.commit()

        db.refresh(chat_job)
        db.refresh(unrelated_job)
        assert chat_job.status == "succeeded"
        assert unrelated_job.status == "queued"
        output = loads_json(chat_job.output_json, {})
        assert output["status"] == "answered_by_main_codex_session"
        assert output["agent_session_id"] == session.id
        assert output["response_locale"] == "ja-JP"
        assert isinstance(output.get("progress_artifact_id"), str)
        chat_artifacts = list(
            db.scalars(select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn"))
        )
        assert len(chat_artifacts) == 1
        metadata = loads_json(chat_artifacts[0].metadata_json, {})
        assert metadata["source"] == "main_codex_session_chat_update"
        assert metadata["source_transcript_event_type"] == "chat_update_registered"
        chat_payload = loads_json(artifact_primary_path(chat_artifacts[0]).read_text(encoding="utf-8"), {})
        source_event = chat_payload["response_brief"]["source_transcript_event"]
        assert source_event["event_type"] == "chat_update_registered"
        assert source_event["event_index"] == metadata["source_transcript_event_index"]


def test_chat_update_links_registered_plan_evidence_without_parsing_message(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    report_path = workspace / "reports" / "chat_update.md"
    report_path.parent.mkdir(parents=True)
    message = "分析結果を保存しました。次に確認する成果物があります。"
    report_path.write_text(message, encoding="utf-8")

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_chat_links",
            name="Chat Links",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_chat_links",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Keep the user informed.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="agent_session_notebooks_grandmaster_eda",
            filename="grandmaster_eda.py",
            text="import marimo\napp = marimo.App()\n",
            metadata={"project_id": project.id, "workspace_relative_path": "notebooks/grandmaster_eda.py"},
        )
        report_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_report",
            name="agent_session_reports_modeling_report",
            filename="modeling_report.md",
            text="# Modeling report\n",
            metadata={"project_id": project.id, "workspace_relative_path": "reports/modeling_report.md"},
        )
        run = ExperimentRun(
            id="run_chat_linked",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "ridge_text_masked"}),
            metrics_json=dumps_json({"mae": 123.4}),
        )
        db.add(run)
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "analysis_outputs",
                        "title": "Analysis outputs",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook", "experiment_run", "report"]},
                        "completion_evidence": [
                            {
                                "output_type": "notebook",
                                "artifact_id": notebook_artifact.id,
                                "workspace_path": "notebooks/grandmaster_eda.py",
                            },
                            {"output_type": "experiment_run", "experiment_run_id": run.id},
                            {
                                "output_type": "report",
                                "artifact_id": report_artifact.id,
                                "workspace_path": "reports/modeling_report.md",
                            },
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered notebook, run, and report evidence.",
        )
        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_report",
            name="agent_session_reports_chat_update_md",
            filename="chat_update.md",
            text=message,
            metadata={"project_id": project.id, "agent_session_id": session.id},
        )

        maybe_register_chat_update_from_workspace_output(
            db,
            store=store,
            project=project,
            session=session,
            path=report_path,
            artifact=source_artifact,
        )
        db.commit()

        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["assistant_message"] == message
        assert chat_payload["response_brief"]["linked_action_count"] == 3
        assert chat_payload["actions"][0]["target_tab"] == "Notebooks"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert chat_payload["actions"][0]["artifact_ids"] == [notebook_artifact.id]
        assert chat_payload["actions"][0]["asset_type"] == "analysis_notebook"
        assert chat_payload["actions"][1]["target_tab"] == "Leaderboard"
        assert chat_payload["actions"][1]["run_id"] == run.id
        assert chat_payload["actions"][1]["entity_ids"] == [run.id]
        assert chat_payload["actions"][2]["target_tab"] == "Assets"
        assert chat_payload["actions"][2]["target_anchor"] == "assets-artifact-preview"
        assert chat_payload["actions"][2]["artifact_id"] == report_artifact.id
        assert chat_payload["actions"][2]["artifact_ids"] == [report_artifact.id]
        assert chat_payload["actions"][2]["asset_type"] == "agent_session_report"
        assert chat_payload["next_focus"]["target_tab"] == "Notebooks"
        assert chat_payload["next_focus"]["artifact_id"] == notebook_artifact.id
        assert chat_payload["next_focus"]["asset_type"] == "analysis_notebook"


def test_turn_prompt_includes_living_research_plan_contract(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_plan", name="Plan Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_plan",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)

        assert ".tablex/PROTOCOL.md" in prompt.text
        assert len(prompt.text) < 4000
        protocol = session_protocol_text()
        assert "outputs/research_plan.json" in protocol
        assert "Do not remove or reopen completed nodes" in protocol
        assert '"operation": "commit_revision"' in protocol
        assert '"payload": {' in protocol
        assert '"document": {' in protocol
        assert '"timeline_blocks": [' in protocol
        assert '"operation": "set_current_work"' in protocol
        assert '"node_id": "objective_framing"' in protocol
        assert "completion evidence" in protocol
        assert "register_research_findings" in protocol
        assert "no_findings" in protocol
        assert "Do not mark prior-knowledge research done" in protocol
        assert "supervised_regression" in protocol
        assert "supervised_classification" in protocol
        assert "regression | classification" not in protocol
        assert "For `.tablex/requests/experiments/` use `payload.research_plan_node_id`" in protocol
        assert "for `artifacts/model_results.json` use top-level `research_plan_node_id`" in protocol
        assert '"schema_version": "model_results.v1"' in protocol
        assert '"research_plan_node_id": "modeling_and_diagnostics"' in protocol


def test_runner_failure_backoff_counts_attempts_not_sidecar_events(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_retry_count", name="Retry Count", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_retry_count",
            project_id=project.id,
            goal_text="Keep the main session alive.",
        )
        db.add_all([project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_unavailable",
            role="harness",
            title="Codex CLI is not available",
            content="Codex binary is missing.",
            payload={},
        )
        db.commit()

        assert agent_sessions_module.consecutive_runner_failure_count(db, session.id) == 1
        assert agent_sessions_module.retry_delay_seconds(1) == 5

        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_retry_scheduled",
            role="harness",
            title="Codex runner retry scheduled",
            content="Retry scheduled.",
            payload={"retry_delay_seconds": 5},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_unavailable",
            role="harness",
            title="Codex CLI is still not available",
            content="Codex binary is missing.",
            payload={},
        )
        db.commit()

        assert agent_sessions_module.consecutive_runner_failure_count(db, session.id) == 2
        assert agent_sessions_module.retry_delay_seconds(2) == 30


def test_turn_prompt_keeps_chat_update_human_facing_not_internal_changelog(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_chat_prompt", name="Chat Prompt", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_chat_prompt",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)

        assert ".tablex/PROTOCOL.md" in prompt.text
        assert len(prompt.text) < 4000
        assert "reports/chat_update.md" in prompt.text
        assert ".tablex/inbox/" in prompt.text
        protocol = session_protocol_text()
        assert ".tablex/inbox/" in protocol
        assert ".tablex/inbox/<seq>_<kind>.json" in protocol
        assert "not an internal changelog" in protocol
        assert "Avoid raw artifact ids" in protocol
        assert "do not make approval-waiting the headline" in protocol
        assert "Do not present Full Auto as stopped on approval" in protocol
        assert "which reversible analysis, modeling, diagnostics, notebook/report work, or research" in protocol
        assert "clustering" in protocol
        assert "anomaly_detection" in protocol
        assert "exploratory" in protocol


def test_agent_request_compatibility_alias_surface_is_frozen() -> None:
    compatibility_warning_strings: set[str] = set()
    for module in (agent_sessions_module, pipeline_requests_module, research_plan_requests_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "append":
                continue
            value = node.func.value
            if not isinstance(value, ast.Name) or value.id not in {"warnings", "compatibility_warnings"}:
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                compatibility_warning_strings.add(node.args[0].value)

    assert compatibility_warning_strings == {
        "Accepted research_plan_path as an explicit workspace JSON reference; prefer payload.document for new requests.",
        "Accepted research_plan_node_id as an explicit alias for node_id; prefer payload.node_id for new requests.",
        "pipeline_manifest.expected_metrics.metric_alias_normalized",
        "pipeline_manifest.history_requirements_array_normalized",
        "pipeline_manifest.history_requirements_moved_to_input_contract",
        "pipeline_manifest.input_contract.inference_format.string_columns_normalized",
        "pipeline_manifest.input_contract.required_columns_normalized",
        "pipeline_manifest.output_contract.required_columns_normalized",
        "pipeline_manifest.output_contract.string_columns_normalized",
        "payload.manifest_workspace_path_used",
        "payload.pipeline_manifest_path_alias_for_manifest_workspace_path",
        "payload.pipeline_name_derived_from_fixed_id",
        "payload.run_id_alias_for_experiment_run_ids",
        "payload.run_ids_alias_for_experiment_run_ids",
        "payload.workspace_path_alias_for_workspace_dir",
        "top_level_pipeline_payload_fields",
    }
    protocol = session_protocol_text()
    for legacy_field in ("research_plan_path", "pipeline_manifest_path", "run_ids", "workspace_path_alias"):
        assert legacy_field not in protocol


def test_project_response_locale_uses_latest_explicit_user_or_chat_locale(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    now = utc_now()

    with sessionmaker(engine)() as db:
        user = User(id="u_locale", email="locale@example.com", locale="en-US", updated_at=now)
        project = Project(id="p_locale", name="Locale Project", created_by=user.id)
        start_job = Job(
            id="job_start_locale",
            project_id=project.id,
            job_type="start_autonomous_loop",
            input_json=dumps_json({"locale": "ja-JP"}),
            created_at=now + timedelta(seconds=10),
        )
        db.add_all([user, project, start_job])
        db.commit()

        assert latest_project_response_locale(db, project) == "ja-JP"

        user.locale = "fr-FR"
        user.updated_at = now + timedelta(seconds=20)
        db.commit()

        assert latest_project_response_locale(db, project) == "fr-FR"

        chat_job = Job(
            id="job_chat_locale",
            project_id=project.id,
            job_type="agent_chat_turn",
            input_json=dumps_json({"message": "状況を説明して", "locale": "ja-JP"}),
            created_at=now + timedelta(seconds=30),
        )
        db.add(chat_job)
        db.commit()

        assert latest_project_response_locale(db, project) == "ja-JP"


def test_latest_codex_output_ignores_sidecar_events(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_codex_time", name="Codex Time", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_codex_time",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            last_heartbeat_at=utc_now() - timedelta(minutes=10),
        )
        db.add_all([project, session])
        db.flush()
        codex_event = append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="Working on analysis.",
            payload={},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="progress_update_requested",
            role="harness",
            title="Progress update requested",
            content="Sidecar nudge.",
            payload={},
            update_heartbeat=False,
        )
        db.commit()

        assert latest_codex_transcript_output_at(db, session_id=session.id) == codex_event.created_at


def test_progress_update_nudge_writes_inbox_without_faking_heartbeat(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"
    old_heartbeat = utc_now() - timedelta(minutes=20)

    with sessionmaker(engine)() as db:
        project = Project(id="p_nudge", name="Nudge Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_nudge",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
            last_heartbeat_at=old_heartbeat,
        )
        db.add_all([project, session])
        db.commit()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content="Dataset profiling advanced.",
            payload={},
            update_heartbeat=False,
        )
        db.commit()

        event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        db.commit()

        assert event is not None
        db.refresh(session)
        assert session.last_heartbeat_at is not None
        assert session.last_heartbeat_at.replace(tzinfo=timezone.utc) == old_heartbeat
        request_path = progress_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "reports/chat_update.md" in request_text
        assert "内部の再開処理" in request_text

        second_event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        assert second_event is None

        third_event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now() + timedelta(minutes=10),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        assert third_event is None


def test_progress_update_nudge_waits_for_new_codex_output(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_nudge_no_output", name="Nudge No Output", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_nudge_no_output",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.commit()

        event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        assert event is None
        assert not progress_request_path(workspace).exists()

        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content="A new model diagnostic artifact was prepared.",
            payload={},
            update_heartbeat=False,
        )
        db.commit()

        event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now() + timedelta(minutes=2),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        assert event is not None
        payload = loads_json(event.payload_json, {})
        assert payload["latest_codex_output_at"]


def test_research_plan_current_work_nudge_requests_codex_declaration(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"
    old_heartbeat = utc_now() - timedelta(minutes=20)

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_nudge", name="Current Nudge", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_current_nudge",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
            last_heartbeat_at=old_heartbeat,
        )
        db.add_all([project, session])
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Create an active plan without declaring current_work yet.",
        ).revision
        db.commit()

        event = maybe_request_research_plan_current_work_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            min_interval_seconds=300,
        )
        db.commit()

        assert event is not None
        assert event.event_type == "research_plan_current_work_requested"
        db.refresh(session)
        assert session.last_heartbeat_at is not None
        assert session.last_heartbeat_at.replace(tzinfo=timezone.utc) == old_heartbeat
        request_path = research_plan_current_work_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "tablex_research_plan_current_work_request.v1" in request_text
        assert "set_current_work" in request_text
        assert revision.id in request_text

        second_event = maybe_request_research_plan_current_work_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            min_interval_seconds=300,
        )
        assert second_event is None


def test_research_plan_current_work_nudge_skips_completed_plan(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_complete", name="Current Complete", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_current_complete",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            author_type="codex",
            reason="All available work is complete.",
        )
        db.commit()

        event = maybe_request_research_plan_current_work_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now() + timedelta(minutes=20),
            min_interval_seconds=300,
        )

        assert event is None
        assert not research_plan_current_work_request_path(workspace).exists()


def test_task_spec_nudge_requests_commit_after_primary_without_task_spec(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"
    old_heartbeat = utc_now() - timedelta(minutes=20)

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_task_spec_nudge",
            name="TaskSpec Nudge",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id="ds_primary",
        )
        dataset = DatasetSnapshot(
            id="ds_primary",
            project_id=project.id,
            artifact_id="art_primary",
            source_type="upload",
            source_ref="train.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-primary",
        )
        session = AgentSession(
            id="as_task_spec_nudge",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
            last_heartbeat_at=old_heartbeat,
        )
        db.add_all([project, dataset, session])
        db.commit()

        event = maybe_request_task_spec_update(db, project=project, session=session, locale="ja-JP")
        db.commit()

        assert event is not None
        assert event.event_type == "task_spec_requested"
        db.refresh(session)
        assert session.last_heartbeat_at is not None
        assert session.last_heartbeat_at.replace(tzinfo=timezone.utc) == old_heartbeat
        request_path = task_spec_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "tablex_task_spec_request.v1" in request_text
        assert "commit_task_spec" in request_text
        assert "targets: []" in request_text
        assert "ds_primary" in request_text
        assert "TARGET" not in request_text
        assert "column0" not in request_text
        assert "ranking" not in request_text.lower()
        inbox_entries = list_inbox_entries(workspace)
        assert inbox_entries[-1]["type"] == "task_spec_request"
        assert inbox_entries[-1]["payload"]["targets_empty_allowed"] is True


def test_data_framing_nudge_requests_primary_and_task_spec_when_primary_missing(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"
    old_heartbeat = utc_now() - timedelta(minutes=20)

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_data_framing_nudge",
            name="Data Framing Nudge",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id=None,
        )
        events = DatasetSnapshot(
            id="ds_events",
            project_id=project.id,
            artifact_id="art_events",
            source_type="upload",
            source_ref="events.csv",
            row_count=10,
            column_count=5,
            schema_hash="schema-events",
        )
        stores = DatasetSnapshot(
            id="ds_stores",
            project_id=project.id,
            artifact_id="art_stores",
            source_type="upload",
            source_ref="stores.csv",
            row_count=3,
            column_count=4,
            schema_hash="schema-stores",
        )
        session = AgentSession(
            id="as_data_framing_nudge",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
            last_heartbeat_at=old_heartbeat,
        )
        db.add_all([project, events, stores, session])
        db.commit()

        event = maybe_request_data_framing_update(db, project=project, session=session, locale="ja-JP")
        db.commit()

        assert event is not None
        assert event.event_type == "data_framing_requested"
        db.refresh(session)
        assert session.last_heartbeat_at is not None
        assert session.last_heartbeat_at.replace(tzinfo=timezone.utc) == old_heartbeat
        request_path = data_framing_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "tablex_data_framing_request.v1" in request_text
        assert "set_primary_table" in request_text
        assert "register_derived_table" in request_text
        assert "commit_task_spec" in request_text
        assert "targets: []" in request_text
        assert "ds_events" in request_text
        assert "ds_stores" in request_text
        assert "TARGET" not in request_text
        assert "column0" not in request_text
        assert "ranking" not in request_text.lower()
        inbox_entries = list_inbox_entries(workspace)
        assert inbox_entries[-1]["type"] == "data_framing_request"
        assert inbox_entries[-1]["payload"]["targets_empty_allowed"] is True
        assert inbox_entries[-1]["payload"]["dataset_snapshot_ids"] == ["ds_events", "ds_stores"]


def test_data_framing_nudge_skips_when_primary_exists(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_data_framing_primary",
            name="Data Framing Primary",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id="ds_primary",
        )
        dataset = DatasetSnapshot(
            id="ds_primary",
            project_id=project.id,
            artifact_id="art_primary",
            source_type="upload",
            source_ref="train.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-primary",
        )
        session = AgentSession(
            id="as_data_framing_primary",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, dataset, session])
        db.commit()

        event = maybe_request_data_framing_update(db, project=project, session=session, locale="ja-JP")

        assert event is None
        assert not data_framing_request_path(workspace).exists()


def test_data_framing_nudge_skips_when_task_spec_artifact_exists(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_data_framing_task_spec",
            name="Data Framing TaskSpec",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id=None,
        )
        dataset = DatasetSnapshot(
            id="ds_upload",
            project_id=project.id,
            artifact_id="art_upload",
            source_type="upload",
            source_ref="data.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-upload",
        )
        session = AgentSession(
            id="as_data_framing_task_spec",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, dataset, session])
        db.flush()
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="task_spec",
            name="task_spec_current",
            filename="task_spec.json",
            text=dumps_json({"schema_version": "task_spec.v1", "task_shape": "clustering", "targets": []}),
            metadata={"project_id": project.id},
        )
        db.commit()

        event = maybe_request_data_framing_update(db, project=project, session=session, locale="ja-JP")

        assert event is None
        assert not data_framing_request_path(workspace).exists()


def test_data_framing_nudge_dedupes_same_dataset_set(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_data_framing_dedupe",
            name="Data Framing Dedupe",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id=None,
        )
        dataset = DatasetSnapshot(
            id="ds_upload",
            project_id=project.id,
            artifact_id="art_upload",
            source_type="upload",
            source_ref="data.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-upload",
        )
        session = AgentSession(
            id="as_data_framing_dedupe",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, dataset, session])
        db.commit()

        first_event = maybe_request_data_framing_update(db, project=project, session=session, locale="ja-JP")
        db.commit()
        second_event = maybe_request_data_framing_update(db, project=project, session=session, locale="ja-JP")
        db.commit()

        assert first_event is not None
        assert second_event is None
        entries = [entry for entry in list_inbox_entries(workspace) if entry.get("type") == "data_framing_request"]
        assert len(entries) == 1
        event_count = db.scalar(
            select(func.count())
            .select_from(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "data_framing_requested",
            )
        )
        assert event_count == 1


def test_task_spec_nudge_skips_when_task_spec_artifact_exists(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_task_spec_present",
            name="TaskSpec Present",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id="ds_primary",
        )
        dataset = DatasetSnapshot(
            id="ds_primary",
            project_id=project.id,
            artifact_id="art_primary",
            source_type="upload",
            source_ref="train.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-primary",
        )
        session = AgentSession(
            id="as_task_spec_present",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, dataset, session])
        db.flush()
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="task_spec",
            name="task_spec_current",
            filename="task_spec.json",
            text=dumps_json({"schema_version": "task_spec.v1", "task_shape": "clustering", "targets": []}),
            metadata={"project_id": project.id},
        )
        db.commit()

        event = maybe_request_task_spec_update(db, project=project, session=session, locale="ja-JP")

        assert event is None
        assert not task_spec_request_path(workspace).exists()


def test_task_spec_nudge_dedupes_same_primary_in_session(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_task_spec_dedupe",
            name="TaskSpec Dedupe",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            primary_dataset_snapshot_id="ds_primary",
        )
        dataset = DatasetSnapshot(
            id="ds_primary",
            project_id=project.id,
            artifact_id="art_primary",
            source_type="upload",
            source_ref="train.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-primary",
        )
        session = AgentSession(
            id="as_task_spec_dedupe",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, dataset, session])
        db.commit()

        first_event = maybe_request_task_spec_update(db, project=project, session=session, locale="ja-JP")
        db.commit()
        second_event = maybe_request_task_spec_update(db, project=project, session=session, locale="ja-JP")
        db.commit()

        assert first_event is not None
        assert second_event is None
        entries = [entry for entry in list_inbox_entries(workspace) if entry.get("type") == "task_spec_request"]
        assert len(entries) == 1
        event_count = db.scalar(
            select(func.count())
            .select_from(AgentTranscriptEvent)
            .where(AgentTranscriptEvent.session_id == session.id, AgentTranscriptEvent.event_type == "task_spec_requested")
        )
        assert event_count == 1


def test_completed_plan_pauses_main_session_until_new_input(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_complete_pause", name="Complete Pause", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_complete_pause",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "diagnostics_reporting",
                        "title": "Diagnostics and reporting",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            author_type="codex",
            reason="All available reversible work is complete.",
        )
        db.commit()

        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is True

        append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content="追加でこの観点も確認して。",
            payload={},
        )
        db.commit()
        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is False

        mark_user_instructions_delivered(
            sessionmaker(engine),
            session_id=session.id,
            delivered_user_event_indexes=(1,),
        )
        db.expire_all()
        project = db.get(Project, project.id)
        session = db.get(AgentSession, session.id)
        assert project is not None and session is not None
        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is True
        pipeline_request = write_inbox_entry(
            workspace,
            kind="request",
            entry_type="pipeline_registration_request",
            payload={
                "schema_version": "tablex_pipeline_registration_request.v1",
                "run_ids": ["run_missing_pipeline"],
            },
            title="Pipeline registration requested",
        )
        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is False
        mark_inbox_entry_processed(workspace, pipeline_request, processed_by="codex")
        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is True
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content="No further reversible work is available.",
            payload={},
            update_heartbeat=False,
        )
        progress_event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="en-US",
            now=utc_now() + timedelta(minutes=20),
            stale_after_seconds=0,
            min_interval_seconds=0,
        )
        assert progress_event is None

        pause_main_session_after_completed_plan(db, store=store, project=project, session=session)
        db.commit()

        db.refresh(project)
        db.refresh(session)
        assert project.current_phase == "IDLE"
        assert session.status == "completed"
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert payload["intent"]["message_kind"] == "completed_waiting_for_input"
        assert "test data" in payload["assistant_message"]


def test_waiting_plan_pauses_main_session_for_external_input(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_waiting_pause", name="Waiting Pause", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_waiting_pause",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "modeling_iterations",
                        "title": "Modeling iterations",
                        "granularity": "chapter",
                        "status": "done",
                    },
                    {
                        "id": "test_data_review",
                        "title": "Test data review",
                        "granularity": "chapter",
                        "status": "waiting",
                    },
                ],
            },
            author_type="codex",
            reason="Modeling has reached the current data boundary; external test data is needed.",
        )
        db.commit()

        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is True

        pause_main_session_after_completed_plan(db, store=store, project=project, session=session)
        db.commit()

        db.refresh(project)
        db.refresh(session)
        assert project.current_phase == "IDLE"
        assert session.status == "completed"
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert payload["intent"]["message_kind"] == "completed_waiting_for_input"
        assert "test data" in payload["assistant_message"]


def test_completed_plan_pause_ignores_attention_artifact_noise(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_complete_attention", name="Complete Attention", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_complete_attention",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "modeling_complete",
                        "title": "Modeling complete",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            author_type="codex",
            reason="All available modeling iterations are complete.",
        )
        chat_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_chat_turn",
            name="codex_final_update",
            filename="agent_chat_turn.json",
            text=dumps_json({"schema_version": "agent_chat_turn.v1", "assistant_message": "Done."}),
            metadata={"source": "main_codex_session_chat_update", "agent_session_id": session.id},
        )
        chat_artifact.created_at = utc_now() - timedelta(minutes=5)
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_attention",
            name="legacy_attention_noise",
            filename="attention.json",
            text="{}",
            metadata={"source": "legacy_attention_noise"},
        )
        db.commit()

        assert main_session_should_pause_after_completed_plan(db, project=project, session=session) is True


def test_safe_completed_plan_pause_marks_session_completed_once(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(id="p_safe_complete", name="Safe Complete", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_safe_complete",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "available_work_done",
                        "title": "Available work done",
                        "granularity": "chapter",
                        "status": "done",
                    }
                ],
            },
            author_type="codex",
            reason="No further reversible work is available without new input.",
        )
        db.commit()

    assert pause_main_session_after_completed_plan_safely(
        session_factory,
        store=store,
        project_id="p_safe_complete",
        session_id="as_safe_complete",
    ) is True
    assert pause_main_session_after_completed_plan_safely(
        session_factory,
        store=store,
        project_id="p_safe_complete",
        session_id="as_safe_complete",
    ) is False

    with session_factory() as db:
        project = db.get(Project, "p_safe_complete")
        session = db.get(AgentSession, "as_safe_complete")
        assert project is not None and session is not None
        assert project.current_phase == "IDLE"
        assert session.status == "completed"
        chat_turns = list(db.scalars(select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")).all())
        assert len(chat_turns) == 1


def test_supervisor_does_not_rewrite_completed_session_to_stopped(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(id="p_completed_not_stopped", name="Completed Not Stopped", current_phase="IDLE", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_completed_not_stopped",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="completed",
            ended_at=utc_now(),
        )
        db.add_all([project, session])
        db.commit()

    agent_sessions_module.run_main_agent_session_supervisor(
        session_factory,
        store,
        project_id="p_completed_not_stopped",
        session_id="as_completed_not_stopped",
        max_turns=1,
        slot_acquired=True,
        lease_owner_id="owner-completed",
    )

    with session_factory() as db:
        session = db.get(AgentSession, "as_completed_not_stopped")
        assert session is not None
        assert session.status == "completed"


def test_research_plan_current_work_nudge_skips_latest_declared_current_work(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_declared", name="Current Declared", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_current_declared",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Create an active plan and declare current_work.",
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="data_understanding",
            summary="Understanding the uploaded table.",
            revision_id=revision.id,
        )
        db.commit()

        event = maybe_request_research_plan_current_work_update(
            db,
            session=session,
            locale="en-US",
            now=utc_now(),
            min_interval_seconds=300,
        )

        assert event is None
        assert not research_plan_current_work_request_path(workspace).exists()


def test_research_plan_current_work_nudge_refreshes_stale_declaration_after_codex_output(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_current_stale", name="Current Stale", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_current_stale",
            project_id=project.id,
            goal_text="Run the main autonomous project.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "objective_framing",
                        "title": "Objective framing",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Create a plan and declare an initial current_work.",
        ).revision
        current = set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="objective_framing",
            summary="Framing the objective.",
            revision_id=revision.id,
        )
        current.updated_at = utc_now() - timedelta(minutes=10)
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content="Running model training.",
            update_heartbeat=False,
        )
        db.commit()

        event = maybe_request_research_plan_current_work_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            min_interval_seconds=300,
        )
        db.commit()

        assert event is not None
        event_payload = loads_json(event.payload_json, {})
        assert event_payload["reason"] == "stale_after_codex_output"
        assert event_payload["current_node_id"] == "objective_framing"
        request_text = research_plan_current_work_request_path(workspace).read_text(encoding="utf-8")
        assert "reason: stale_after_codex_output" in request_text
        assert "current_node_id: objective_framing" in request_text
        assert "set_current_work" in request_text


def test_supervisor_safe_nudge_requests_research_plan_current_work(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    workspace = tmp_path / "workspace"

    with session_factory() as db:
        user = User(id="u_current_safe", email="current-safe@example.com", locale="ja-JP")
        project = Project(
            id="p_current_safe",
            name="Current Safe Nudge",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            created_by=user.id,
        )
        session = AgentSession(
            id="as_current_safe",
            project_id=project.id,
            goal_text="Run the main autonomous data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now(),
            started_at=utc_now(),
        )
        db.add_all([user, project, session])
        db.flush()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "project_id": project.id,
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Create an active plan without a declared current_work record.",
        ).revision
        revision_id = revision.id
        db.commit()

    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id="p_current_safe",
        session_id="as_current_safe",
    )

    request_path = research_plan_current_work_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "locale: ja-JP" in request_text
    assert revision_id in request_text
    assert "set_current_work" in request_text
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "as_current_safe",
                    AgentTranscriptEvent.event_type == "research_plan_current_work_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1


def test_supervisor_safe_nudge_requests_missing_task_spec_after_primary(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    workspace = tmp_path / "workspace"

    with session_factory() as db:
        user = User(id="u_task_spec_safe", email="task-spec-safe@example.com", locale="ja-JP")
        project = Project(
            id="p_task_spec_safe",
            name="TaskSpec Safe Nudge",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            created_by=user.id,
            primary_dataset_snapshot_id="ds_primary",
        )
        dataset = DatasetSnapshot(
            id="ds_primary",
            project_id=project.id,
            artifact_id="art_primary",
            source_type="upload",
            source_ref="train.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-primary",
        )
        session = AgentSession(
            id="as_task_spec_safe",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now(),
            started_at=utc_now(),
        )
        db.add_all([user, project, dataset, session])
        db.commit()

    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id="p_task_spec_safe",
        session_id="as_task_spec_safe",
    )

    request_path = task_spec_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "tablex_task_spec_request.v1" in request_text
    assert "commit_task_spec" in request_text
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "as_task_spec_safe",
                    AgentTranscriptEvent.event_type == "task_spec_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["primary_dataset_snapshot_id"] == "ds_primary"


def test_supervisor_safe_nudge_requests_data_framing_before_primary(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    workspace = tmp_path / "workspace"

    with session_factory() as db:
        user = User(id="u_data_framing_safe", email="data-framing-safe@example.com", locale="ja-JP")
        project = Project(
            id="p_data_framing_safe",
            name="Data Framing Safe Nudge",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            created_by=user.id,
            primary_dataset_snapshot_id=None,
        )
        dataset = DatasetSnapshot(
            id="ds_upload",
            project_id=project.id,
            artifact_id="art_upload",
            source_type="upload",
            source_ref="data.csv",
            row_count=10,
            column_count=3,
            schema_hash="schema-upload",
        )
        session = AgentSession(
            id="as_data_framing_safe",
            project_id=project.id,
            goal_text="Run primary-free Full Auto.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now(),
            started_at=utc_now(),
        )
        db.add_all([user, project, dataset, session])
        db.commit()

    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id="p_data_framing_safe",
        session_id="as_data_framing_safe",
    )

    request_path = data_framing_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "tablex_data_framing_request.v1" in request_text
    assert "set_primary_table" in request_text
    assert "register_derived_table" in request_text
    assert "commit_task_spec" in request_text
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "as_data_framing_safe",
                    AgentTranscriptEvent.event_type == "data_framing_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["dataset_snapshot_ids"] == ["ds_upload"]


def test_research_plan_contract_nudge_writes_inbox_and_chat_once(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_plan_contract_nudge", name="Plan Contract Nudge", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_plan_contract_nudge",
            project_id=project.id,
            goal_text="Keep the ResearchPlan coherent without stopping Codex.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([project, session])
        db.flush()
        timeline_blocks = [
            {
                "id": f"chapter_{index}",
                "title": f"Chapter {index}",
                "status": "done",
            }
            for index in range(1, 8)
        ]
        timeline_blocks.append({"id": "chapter_8", "title": "Chapter 8", "status": "pending"})
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={"schema_version": "research_plan.v2", "timeline_blocks": timeline_blocks},
            author_type="codex",
            reason="Legacy overly granular plan.",
        )
        db.commit()

        event = maybe_request_research_plan_contract_revision(
            db,
            store=store,
            project=project,
            session=session,
            locale="ja-JP",
        )
        db.commit()

        assert event is not None
        request_path = research_plan_contract_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "tablex_research_plan_contract_request.v1" in request_text
        assert "commit_revision" in request_text
        assert "top_level_plan_too_granular" in request_text
        assert ".tablex/requests/research_plan" in request_text

        payload = loads_json(event.payload_json, {})
        assert payload["validation"]["status"] == "needs_revision"
        assert payload["validation"]["error_count"] > 0
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "research_plan_contract_needs_revision"
        assert "Research Plan" in chat_payload["assistant_message"]

        second_event = maybe_request_research_plan_contract_revision(
            db,
            store=store,
            project=project,
            session=session,
            locale="ja-JP",
        )
        db.commit()

        assert second_event is None
        chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_count == 1


def test_session_context_prefers_active_research_plan_revision_over_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_context_plan", name="Context Plan", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_context_plan",
            project_id=project.id,
            goal_text="Use the canonical ResearchPlan revision.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="research_plan",
            name="legacy_plan_artifact",
            filename="research_plan.json",
            text=dumps_json(
                {
                    "schema_version": "research_plan.v1",
                    "timeline_blocks": [
                        {"id": f"legacy_{index}", "title": f"Legacy {index}", "status": "done"}
                        for index in range(1, 9)
                    ],
                }
            ),
            metadata={"project_id": project.id, "source": "legacy_artifact"},
        )
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Canonical plan revision.",
        ).revision
        db.commit()

        context = build_session_context(db, project=project, session=session, response_locale="en-US")

        plan_context = context["research_plan_display"]
        assert plan_context["source"] == "research_plan_revision"
        assert plan_context["source_revision_id"] == revision.id
        assert plan_context["contract_validation"]["status"] == "ok"


def test_session_context_ignores_invalid_legacy_research_plan_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_context_invalid_plan", name="Invalid Context Plan", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_context_invalid_plan",
            project_id=project.id,
            goal_text="Use a validated ResearchPlan context.",
            status="running",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        invalid_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="research_plan",
            name="invalid_legacy_plan_artifact",
            filename="research_plan.json",
            text=dumps_json(
                {
                    "schema_version": "research_plan.v1",
                    "timeline_blocks": [
                        {"id": f"legacy_{index}", "title": f"Legacy {index}", "status": "done"}
                        for index in range(1, 9)
                    ],
                }
            ),
            metadata={"project_id": project.id, "source": "legacy_artifact"},
        )
        db.commit()

        context = build_session_context(db, project=project, session=session, response_locale="en-US")

        plan_context = context["research_plan_display"]
        assert plan_context["source"] == "research_plan_revision"
        assert plan_context["source_revision_id"]
        assert plan_context["ignored_source_artifact"]["source_artifact_id"] == invalid_artifact.id
        assert plan_context["ignored_source_artifact"]["contract_validation"]["status"] == "needs_revision"
        block_ids = [block["id"] for block in plan_context["timeline_blocks"]]
        assert block_ids == ["data_upload", "objective_framing", "data_understanding", "prior_knowledge_research"]
        assert all(not block_id.startswith("legacy_") for block_id in block_ids)
        assert plan_context["contract_validation"]["status"] == "ok"


def test_supervisor_safe_progress_update_uses_project_locale_without_browser_polling(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    workspace = tmp_path / "workspace"
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        user = User(id="u_progress_locale", email="progress@example.com", locale="ja-JP")
        project = Project(
            id="p_safe_nudge",
            name="Safe Nudge Project",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            created_by=user.id,
        )
        session = AgentSession(
            id="as_safe_nudge",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([user, project, session])
        db.commit()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="assistant",
            title="Codex message",
            content="A meaningful workspace output changed.",
            payload={},
            update_heartbeat=False,
        )
        db.commit()

    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id="p_safe_nudge",
        session_id="as_safe_nudge",
        store=store,
    )

    request_path = progress_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "locale: ja-JP" in request_text
    assert "内部の再開処理" in request_text
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "as_safe_nudge",
                    AgentTranscriptEvent.event_type == "progress_update_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["locale"] == "ja-JP"
        chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == "p_safe_nudge", Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            ).all()
        )
        assert len(chat_artifacts) == 1
        chat_payload = loads_json(artifact_primary_path(chat_artifacts[0]).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "progress_update_requested"
        assert "進捗表示" in chat_payload["assistant_message"]
        assert chat_payload["actions"][0]["target_tab"] == "Home"


def test_chat_update_message_uses_latest_concise_tail_for_cumulative_files() -> None:
    text = "\n\n".join(
        [
            "2026-07-03 進捗: 古い進捗です。" + "詳細。" * 500,
            "2026-07-03 進捗: 最新の短い報告です。モデル候補を比較し、次にNotebookを更新します。",
        ]
    )

    message = chat_update_message_from_text(text, limit=200)

    assert "最新の短い報告" in message
    assert "古い進捗" not in message


def test_codex_authored_chat_update_is_registered_as_persistent_chat_turn(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True)
    chat_update = reports_dir / "chat_update.md"
    chat_update.write_text("データ理解を進めています。次に欠損と重複を確認します。", encoding="utf-8")

    with session_factory() as db:
        project = Project(id="p_chat", name="Chat Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_chat",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(chat_artifacts) == 1
        payload = loads_json(artifact_primary_path(chat_artifacts[0]).read_text(encoding="utf-8"), {})
        assert payload["user_message"] == ""
        assert payload["assistant_message"] == "データ理解を進めています。次に欠損と重複を確認します。"
        assert payload["intent"]["type"] == "autonomous_agent_progress_report"

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        unchanged_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(unchanged_chat_artifacts) == 1

        chat_update.write_text("データ理解を進めています。表現だけを更新します。", encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        same_state_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(same_state_chat_artifacts) == 1

        db.add(
            ExperimentRun(
                id="run_chat_state_changed",
                project_id=project.id,
                runner_type="codex_main_session",
                status="succeeded",
                metrics_json=dumps_json({"primary_metric_name": "auc", "primary_metric_value": 0.7}),
                params_json=dumps_json({"model_id": "new_visible_run"}),
            )
        )
        chat_update.write_text("モデル結果を追加しました。", encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        updated_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(updated_chat_artifacts) == 2

        create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "状況を説明してください",
                "locale": "ja-JP",
                "delivered_agent_session_id": session.id,
            },
            priority=90,
        )
        chat_update.write_text("ユーザーへの応答として同じ状態を説明します。\n", encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        user_waiting_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(user_waiting_chat_artifacts) == 3

        duplicate_job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "もう一度状況を説明してください",
                "locale": "ja-JP",
                "delivered_agent_session_id": session.id,
            },
            priority=90,
        )
        chat_update.write_text("ユーザーへの応答として同じ状態を説明します。", encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        db.refresh(duplicate_job)
        assert duplicate_job.status == "succeeded"
        duplicate_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(duplicate_chat_artifacts) == 3


def test_codex_structured_model_results_materialize_leaderboard_runs_and_chat_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "evaluation": {"split": "group_cv", "primary_metric": "mae"},
                "target": {"name": "salary"},
                "models": [
                    {"model_id": "median_baseline", "mae": 100.0, "rmse": 130.0, "r2": 0.1},
                    {"model_id": "gradient_boosting", "mae": 80.0, "rmse": 110.0, "r2": 0.3},
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        user = User(id="u_leaderboard", email="leaderboard@example.com", locale="ja-JP")
        project = Project(id="p_leaderboard", name="Leaderboard Project", created_by=user.id)
        session = AgentSession(
            id="as_leaderboard",
            project_id=project.id,
            goal_text="Register model results.",
            workspace_path=str(workspace),
            created_by=user.id,
        )
        db.add_all([user, project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
        assert len(runs) == 2
        metrics_by_model = {
            loads_json(run.params_json, {})["model_id"]: loads_json(run.metrics_json, {})
            for run in runs
        }
        assert metrics_by_model["median_baseline"]["primary_metric_name"] == "mae"
        assert metrics_by_model["median_baseline"]["primary_metric_value"] == 100.0
        assert metrics_by_model["gradient_boosting"]["primary_metric_value"] == 80.0

        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registered"
        assert chat_payload["actions"][0]["target_tab"] == "Leaderboard"
        assert chat_payload["actions"][0]["target_anchor"] == "result-readout"
        assert any(action["target_tab"] == "Assets" for action in chat_payload["actions"])
        assert chat_payload["visible_surfaces"]["leaderboard"]["run_ids"] == [run.id for run in runs]
        assert chat_payload["visible_surfaces"]["assets"]["target_anchor"] == "assets-artifact-preview"
        pipeline_requests = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "pipeline_registration_request"
        ]
        assert len(pipeline_requests) == 1
        pipeline_payload = pipeline_requests[0]["payload"]
        assert pipeline_payload["schema_version"] == "tablex_pipeline_registration_request.v1"
        assert pipeline_payload["run_ids"] == [run.id for run in runs]
        assert pipeline_payload["pipeline_registration"]["status"] == "missing"

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        pipeline_requests_after_rescan = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "pipeline_registration_request"
        ]
        assert len(pipeline_requests_after_rescan) == 1
        assert chat_payload["next_focus"]["target_anchor"] == "result-readout"

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run_count = db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run_count == 2
        experiment_chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert experiment_chat_count == 1
        replay_chat_artifact = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=None,
            source_request_id="manual_replay_same_visible_state",
        )
        db.commit()
        assert replay_chat_artifact is None
        experiment_chat_count_after_replay = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert experiment_chat_count_after_replay == 1


def test_experiment_registration_chat_dedupes_when_visible_links_change(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_notice_dedupe", name="Experiment Notice Dedupe")
        session = AgentSession(
            id="as_exp_notice_dedupe",
            project_id=project.id,
            goal_text="Keep model result notices stable.",
        )
        run = ExperimentRun(
            id="run_exp_notice_dedupe",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            started_at=utc_now(),
            ended_at=utc_now(),
            params_json=dumps_json(
                {
                    "agent_session_id": session.id,
                    "model_id": "fold_safe_xgboost",
                    "result_signature": "same-model-result",
                }
            ),
            metrics_json=dumps_json(
                {"primary_metric_name": "roc_auc", "primary_metric_value": 0.7674, "roc_auc": 0.7674}
            ),
            summary_md="XGBoost hist model using numeric application features plus applicant-level history aggregates.",
        )
        db.add_all([project, session, run])
        db.commit()

        first_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=[run],
            source_artifact=None,
            source_request_id="register_runs_first",
        )
        assert first_notice is not None
        first_notice_created_at = first_notice.created_at

        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_artifact",
            name="model_results_with_links",
            filename="model_results.json",
            text=dumps_json({"schema_version": "model_results.v1", "models": []}),
            metadata={"source": "main_agent_session_workspace", "agent_session_id": session.id},
        )
        params = loads_json(run.params_json, {})
        params["source_artifact_id"] = source_artifact.id
        run.params_json = dumps_json(params)

        second_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=[run],
            source_artifact=source_artifact,
            source_request_id=None,
        )
        db.commit()

        assert second_notice is None
        assert first_notice.created_at.replace(tzinfo=None) == first_notice_created_at.replace(tzinfo=None)
        experiment_chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert experiment_chat_count == 1
        chat_payload = loads_json(artifact_primary_path(first_notice).read_text(encoding="utf-8"), {})
        assert chat_payload["response_brief"]["notification_fingerprint"]
        assert chat_payload["visible_surfaces"]["assets"]["artifact_id"] == source_artifact.id
        resumed_session = AgentSession(
            id="as_exp_notice_dedupe_resumed",
            project_id=project.id,
            goal_text="Resume without repeating the same model result notice.",
        )
        db.add(resumed_session)
        third_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=resumed_session,
            runs=[run],
            source_artifact=None,
            source_request_id="register_runs_after_resume",
        )
        db.commit()

        assert third_notice is None
        assert first_notice.created_at.replace(tzinfo=None) == first_notice_created_at.replace(tzinfo=None)
        experiment_chat_count_after_resume = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert experiment_chat_count_after_resume == 1
        chat_metadata = loads_json(first_notice.metadata_json, {})
        assert chat_metadata["agent_session_id"] == resumed_session.id


def test_experiment_registration_chat_updates_legacy_run_id_notice(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_notice_legacy", name="Experiment Notice Legacy")
        session = AgentSession(
            id="as_exp_notice_legacy",
            project_id=project.id,
            goal_text="Avoid duplicate model-result notices.",
        )
        runs = [
            ExperimentRun(
                id=f"run_legacy_{index}",
                project_id=project.id,
                runner_type="codex_main_session",
                status="succeeded",
                started_at=utc_now(),
                ended_at=utc_now(),
                params_json=dumps_json(
                    {
                        "agent_session_id": session.id,
                        "model_id": f"model_{index}",
                        "result_signature": f"legacy-result-{index}",
                    }
                ),
                metrics_json=dumps_json(
                    {"primary_metric_name": "roc_auc", "primary_metric_value": 0.75 + index / 100}
                ),
                summary_md=f"Model {index}",
            )
            for index in range(2)
        ]
        db.add_all([project, session, *runs])
        db.commit()

        legacy_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=None,
            source_request_id="legacy_request_without_fingerprints",
        )
        assert legacy_notice is not None
        legacy_payload_path = artifact_primary_path(legacy_notice)
        legacy_payload = loads_json(legacy_payload_path.read_text(encoding="utf-8"), {})
        legacy_payload["response_brief"].pop("result_set_fingerprint", None)
        legacy_payload["response_brief"].pop("notification_fingerprint", None)
        legacy_payload_path.write_text(dumps_json(legacy_payload), encoding="utf-8")
        legacy_metadata = loads_json(legacy_notice.metadata_json, {})
        legacy_metadata.pop("result_set_fingerprint", None)
        legacy_metadata.pop("notification_fingerprint", None)
        legacy_metadata.pop("visible_state_fingerprint", None)
        legacy_notice.metadata_json = dumps_json(legacy_metadata)

        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_artifact",
            name="model_results_later_source",
            filename="model_results.json",
            text=dumps_json({"schema_version": "model_results.v1", "models": []}),
            metadata={"source": "main_agent_session_workspace", "agent_session_id": session.id},
        )
        for run in runs:
            params = loads_json(run.params_json, {})
            params["source_artifact_id"] = source_artifact.id
            run.params_json = dumps_json(params)

        new_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=source_artifact,
            source_request_id=None,
        )
        db.commit()

        assert new_notice is None
        experiment_chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert experiment_chat_count == 1
        updated_payload = loads_json(artifact_primary_path(legacy_notice).read_text(encoding="utf-8"), {})
        assert updated_payload["response_brief"]["run_ids"] == [run.id for run in runs]
        assert updated_payload["response_brief"]["source_artifact_id"] == source_artifact.id
        assert updated_payload["response_brief"]["result_set_fingerprint"]


def test_experiment_registration_chat_dedupes_beyond_recent_chat_window(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_notice_long_history", name="Experiment Notice Long History")
        session = AgentSession(
            id="as_exp_notice_long_history",
            project_id=project.id,
            goal_text="Avoid duplicate model-result notices in long chats.",
        )
        runs = [
            ExperimentRun(
                id=f"run_long_history_{index}",
                project_id=project.id,
                runner_type="codex_main_session",
                status="succeeded",
                started_at=utc_now(),
                ended_at=utc_now(),
                params_json=dumps_json(
                    {
                        "agent_session_id": session.id,
                        "model_id": f"long_history_model_{index}",
                        "result_signature": f"long-history-result-{index}",
                    }
                ),
                metrics_json=dumps_json(
                    {"primary_metric_name": "roc_auc", "primary_metric_value": 0.76 + index / 100}
                ),
                summary_md=f"Long history model {index}",
            )
            for index in range(4)
        ]
        db.add_all([project, session, *runs])
        db.commit()

        first_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=None,
            source_request_id="first_long_history_result",
        )
        assert first_notice is not None
        first_payload_path = artifact_primary_path(first_notice)
        first_payload = loads_json(first_payload_path.read_text(encoding="utf-8"), {})
        first_payload["response_brief"].pop("result_set_fingerprint", None)
        first_payload["response_brief"].pop("notification_fingerprint", None)
        first_payload_path.write_text(dumps_json(first_payload), encoding="utf-8")
        first_metadata = loads_json(first_notice.metadata_json, {})
        first_metadata.pop("result_set_fingerprint", None)
        first_metadata.pop("notification_fingerprint", None)
        first_metadata.pop("visible_state_fingerprint", None)
        first_notice.metadata_json = dumps_json(first_metadata)

        for index in range(220):
            store_text_artifact(
                db,
                store,
                project_id=project.id,
                asset_type="agent_chat_turn",
                name=f"long_history_progress_update_{index}",
                filename="agent_chat_turn.json",
                text=dumps_json(
                    {
                        "schema_version": "agent_chat_turn.v1",
                        "project_id": project.id,
                        "user_message": "",
                        "assistant_message": f"progress update {index}",
                        "intent": {"type": "autonomous_agent_progress_report", "status": "ready"},
                        "actions": [],
                        "action_summary": {},
                        "response_brief": {"schema_version": "agent_progress_report_brief.v1"},
                        "response_composer": {"mode": "main_codex_session", "status": "codex_authored"},
                        "worker_events": [],
                        "token_usage": {},
                        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace"},
                    }
                ),
                metadata={"source": "main_codex_session_chat_update", "agent_session_id": session.id},
            )

        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_artifact",
            name="long_history_model_results_with_links",
            filename="model_results.json",
            text=dumps_json({"schema_version": "model_results.v1", "models": []}),
            metadata={"source": "main_agent_session_workspace", "agent_session_id": session.id},
        )
        for run in runs:
            params = loads_json(run.params_json, {})
            params["source_artifact_id"] = source_artifact.id
            run.params_json = dumps_json(params)

        repeated_notice = register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=source_artifact,
            source_request_id=None,
        )
        db.commit()

        assert repeated_notice is None
        result_notice_count = 0
        for artifact in db.scalars(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        ):
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
            intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
            if intent.get("type") == "experiment_results_registered":
                result_notice_count += 1
        assert result_notice_count == 1
        updated_payload = loads_json(artifact_primary_path(first_notice).read_text(encoding="utf-8"), {})
        assert updated_payload["response_brief"]["source_artifact_id"] == source_artifact.id
        assert updated_payload["response_brief"]["result_set_fingerprint"]


def test_experiment_result_failure_chat_dedupes_same_error_across_requests(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_failure_dedupe", name="Experiment Failure Dedupe")
        session = AgentSession(
            id="as_exp_failure_dedupe",
            project_id=project.id,
            goal_text="Avoid duplicate result-registration failures.",
        )
        db.add_all([project, session])
        db.commit()

        first_failure = register_experiment_result_failure_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            request_id="art_bad_result_1",
            operation="auto_register_model_results.v1",
            error_type="ValueError",
            error_message="payload.runs must contain at least one run",
        )
        second_failure = register_experiment_result_failure_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            request_id="art_bad_result_2",
            operation="auto_register_model_results.v1",
            error_type="ValueError",
            error_message="payload.runs must contain at least one run",
        )
        db.commit()

        assert first_failure is not None
        assert second_failure is None
        failure_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert failure_count == 1
        payload = loads_json(artifact_primary_path(first_failure).read_text(encoding="utf-8"), {})
        assert payload["response_brief"]["failure_fingerprint"]


def test_codex_structured_model_results_accept_runs_array_with_nested_metric_summaries(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "dataset_snapshot_id": "ds_salary",
                "evaluation_spec_id": "eval_salary",
                "split_manifest_id": "split_salary",
                "primary_metric": "mae",
                "runs": [
                    {
                        "experiment_run_id": "run_salary_linear_ohe_repeated_cv_v1",
                        "model_name": "linear_ohe",
                        "model_description": "Linear model using one-hot categorical features.",
                        "feature_set": ["role", "level", "region", "years_experience"],
                        "primary_metric": "mae",
                        "primary_metric_value": 0.04,
                        "metrics": {
                            "mae": {"mean": 0.04, "std": 0.01},
                            "rmse": {"mean": 0.05},
                            "r2": {"mean": 0.99},
                        },
                    },
                    {
                        "experiment_run_id": "run_salary_tree_repeated_cv_v1",
                        "model_name": "tree",
                        "model_description": "Tree model for nonlinear checks.",
                        "feature_set": ["role", "level", "region", "years_experience"],
                        "primary_metric": "mae",
                        "primary_metric_value": 2.0,
                        "metrics": {
                            "mae": {"mean": 2.0, "std": 0.4},
                            "rmse": {"mean": 2.5},
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_nested_model_results", name="Nested Model Results")
        session = AgentSession(
            id="as_nested_model_results",
            project_id=project.id,
            goal_text="Register nested model results.",
            workspace_path=str(workspace),
        )
        start_job = Job(
            id="job_nested_model_results_start",
            project_id=project.id,
            job_type="start_autonomous_loop",
            input_json=dumps_json({"locale": "ja-JP"}),
        )
        db.add_all([project, session, start_job])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
        assert len(runs) == 2
        metrics_by_model = {
            loads_json(run.params_json, {})["model_id"]: loads_json(run.metrics_json, {})
            for run in runs
        }
        assert metrics_by_model["linear_ohe"]["mae"] == 0.04
        assert metrics_by_model["linear_ohe"]["primary_metric_value"] == 0.04
        params = loads_json(next(run.params_json for run in runs if loads_json(run.params_json, {})["model_id"] == "linear_ohe"), {})
        assert params["features_used"] == ["role", "level", "region", "years_experience"]
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert "Leaderboardに登録しました" in chat_payload["assistant_message"]


def test_malformed_structured_model_results_are_announced_in_agent_chat(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "models": [{"model_id": "candidate_without_metrics", "summary": "Missing numeric metrics."}],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        user = User(id="u_bad_leaderboard", email="bad-leaderboard@example.com", locale="ja-JP")
        project = Project(id="p_bad_leaderboard", name="Bad Leaderboard Project", created_by=user.id)
        session = AgentSession(
            id="as_bad_leaderboard",
            project_id=project.id,
            goal_text="Register malformed model results.",
            workspace_path=str(workspace),
            created_by=user.id,
        )
        db.add_all([user, project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run_count = db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run_count == 0
        rejection = experiment_artifact_rejection_path(workspace)
        assert rejection.exists()
        rejection_text = rejection.read_text(encoding="utf-8")
        assert "tablex_experiment_result_artifact_rejection.v1" in rejection_text
        assert "ExperimentRun records" in rejection_text
        assert "artifacts/model_results.json" in rejection_text
        rejection_entries = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "experiment_result_artifact_rejection"
        ]
        assert len(rejection_entries) == 1
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registration_failed"
        assert chat_payload["intent"]["status"] == "needs_attention"
        assert "構造化エラー" not in chat_payload["assistant_message"]
        assert "structured validation error" not in chat_payload["assistant_message"]
        assert "ACK" not in chat_payload["assistant_message"]
        assert chat_payload["actions"][0]["target_tab"] == "Home"
        assert chat_payload["actions"][0]["target_anchor"] == "agent-workspace"

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        rejection_entries = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "experiment_result_artifact_rejection"
        ]
        assert len(rejection_entries) == 1
        chat_count = db.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_count == 1


def test_structured_model_results_reject_mixed_primary_metrics(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "models": [
                    {
                        "model_id": "regression_candidate",
                        "primary_metric_name": "mae",
                        "mae": 42.0,
                    },
                    {
                        "model_id": "classification_candidate",
                        "primary_metric_name": "roc_auc",
                        "roc_auc": 0.82,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        user = User(id="u_mixed_artifact_metrics", email="mixed-artifact@example.com", locale="ja-JP")
        project = Project(id="p_mixed_artifact_metrics", name="Mixed Artifact Metrics", created_by=user.id)
        session = AgentSession(
            id="as_mixed_artifact_metrics",
            project_id=project.id,
            goal_text="Reject incomparable structured model result rows.",
            workspace_path=str(workspace),
            created_by=user.id,
        )
        db.add_all([user, project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run_count = db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run_count == 0
        rejection_text = experiment_artifact_rejection_path(workspace).read_text(encoding="utf-8")
        assert "same primary_metric_name" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registration_failed"
        assert "same primary_metric_name" in chat_payload["response_brief"]["error_message"]


def test_structured_model_results_attach_to_single_active_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "research_plan_node_id": "modeling_and_diagnostics",
                "models": [
                    {
                        "model_id": "fold_safe_tree",
                        "summary": "A fold-safe tree candidate.",
                        "primary_metric_name": "mae",
                        "mae": 42.0,
                        "rmse": 60.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_structured_plan_link", name="Structured Plan Link")
        session = AgentSession(
            id="as_structured_plan_link",
            project_id=project.id,
            goal_text="Register structured model results.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is working on model comparison.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run is not None
        params = loads_json(run.params_json, {})
        assert params["research_plan_node_id"] == "modeling_and_diagnostics"
        source_artifact = db.get(Artifact, params["source_artifact_id"])
        assert source_artifact is not None
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "research_plan_revision",
                LineageEdge.to_asset_type == "experiment_run",
                LineageEdge.to_asset_id == run.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
        )
        assert edge is not None
        assert loads_json(edge.metadata_json, {})["node_id"] == "modeling_and_diagnostics"
        source_plan_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == source_artifact.id,
            )
        )
        assert source_plan_edge is not None
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        block_links = timeline["blocks"][0]["attached_artifacts"]
        assert any(link["link_type"] == "experiment_run" and link["run_id"] == run.id for link in block_links)
        assert any(link["link_type"] == "artifact" and link["artifact_id"] == source_artifact.id for link in block_links)
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registered"
        assert chat_payload["response_brief"]["research_plan_node_ids"] == ["modeling_and_diagnostics"]
        assert chat_payload["visible_surfaces"]["leaderboard"]["run_ids"] == [run.id]
        assert chat_payload["visible_surfaces"]["assets"]["artifact_id"] == source_artifact.id
        assert any(action["target_tab"] == "Assets" for action in chat_payload["actions"])


def test_structured_model_results_reject_unknown_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "research_plan_node_id": "missing_modeling_node",
                "models": [
                    {
                        "model_id": "fold_safe_tree",
                        "summary": "A fold-safe tree candidate with an invalid plan link.",
                        "primary_metric_name": "mae",
                        "mae": 42.0,
                        "rmse": 60.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_structured_bad_plan_link", name="Structured Bad Plan Link")
        session = AgentSession(
            id="as_structured_bad_plan_link",
            project_id=project.id,
            goal_text="Reject structured model results with invalid plan links.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is working on model comparison.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run is None
        rejection_text = experiment_artifact_rejection_path(workspace).read_text(encoding="utf-8")
        assert "missing_modeling_node" in rejection_text
        assert "not present in the active revision" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registration_failed"
        assert "missing_modeling_node" in chat_payload["response_brief"]["error_message"]


def test_structured_model_results_reject_missing_research_plan_node_when_plan_exists(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "models": [
                    {
                        "model_id": "fold_safe_tree",
                        "summary": "A fold-safe tree candidate without a declared plan node.",
                        "primary_metric_name": "mae",
                        "mae": 42.0,
                        "rmse": 60.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_structured_missing_plan_link", name="Structured Missing Plan Link")
        session = AgentSession(
            id="as_structured_missing_plan_link",
            project_id=project.id,
            goal_text="Reject structured model results without plan links.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Codex is still declaring data understanding as current.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        assert db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id)) == 0
        rejection_text = experiment_artifact_rejection_path(workspace).read_text(encoding="utf-8")
        assert "research_plan_node_id" in rejection_text
        assert "when a ResearchPlan exists" in rejection_text
        assert "For `.tablex/requests/experiments/` use `payload.research_plan_node_id`" in rejection_text
        assert "for `artifacts/model_results.json` use top-level `research_plan_node_id`" in rejection_text
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert timeline["blocks"][0]["attached_artifacts"] == []
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registration_failed"
        assert "research_plan_node_id" in chat_payload["response_brief"]["error_message"]


def test_existing_experiment_run_restores_chat_and_research_plan_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"

    with sessionmaker(engine)() as db:
        project = Project(id="p_existing_run_visibility", name="Existing Run Visibility")
        session = AgentSession(
            id="as_existing_run_visibility",
            project_id=project.id,
            goal_text="Expose existing model results.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_artifact",
            name="existing_model_results",
            filename="model_results.json",
            text=dumps_json({"schema_version": "model_results.v1", "models": []}),
            metadata={
                "source": "main_agent_session_workspace",
                "agent_session_id": session.id,
                "workspace_relative_path": "artifacts/model_results.json",
            },
        )
        run = ExperimentRun(
            id="run_existing_visibility",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json(
                {
                    "agent_session_id": session.id,
                    "source_artifact_id": source_artifact.id,
                    "source_key": "existing_model_results:fold_safe_tree",
                    "model_id": "fold_safe_tree",
                    "research_plan_node_id": "modeling_and_diagnostics",
                }
            ),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 37.0, "mae": 37.0}),
            summary_md="Recovered fold-safe tree.",
        )
        db.add(run)
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is working on model comparison.",
            strict_validation=True,
        )
        db.commit()

        ingest_registered_session_experiment_artifacts(db, store=store, project=project, session=session)
        db.commit()

        db.refresh(run)
        params = loads_json(run.params_json, {})
        assert params["research_plan_node_id"] == "modeling_and_diagnostics"
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registered"
        assert chat_payload["actions"][0]["target_tab"] == "Leaderboard"
        assert chat_payload["actions"][0]["target_anchor"] == "result-readout"
        assert chat_payload["response_brief"]["run_ids"] == [run.id]
        assert chat_payload["response_brief"]["research_plan_node_ids"] == ["modeling_and_diagnostics"]
        assert chat_payload["visible_surfaces"]["leaderboard"]["run_ids"] == [run.id]
        assert chat_payload["visible_surfaces"]["assets"]["artifact_id"] == source_artifact.id
        assert any(action["target_tab"] == "Assets" for action in chat_payload["actions"])
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        block_links = timeline["blocks"][0]["attached_artifacts"]
        assert any(link["link_type"] == "experiment_run" and link["run_id"] == run.id for link in block_links)
        assert any(link["link_type"] == "artifact" and link["artifact_id"] == source_artifact.id for link in block_links)
        pipeline_requests = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "pipeline_registration_request"
        ]
        assert len(pipeline_requests) == 1
        assert pipeline_requests[0]["payload"]["run_ids"] == [run.id]

        restore_registered_session_experiment_visibility(db, store=store, project=project, session=session)
        db.commit()
        pipeline_requests_after_restore = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry.get("type") == "pipeline_registration_request"
        ]
        assert len(pipeline_requests_after_restore) == 1


def test_experiment_result_file_request_registers_leaderboard_run_with_ack(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "register_runs.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "exp_req_1",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "glm_baseline",
                            "model_description": "A fold-safe GLM baseline.",
                            "features_used": ["numeric_profile", "category_encoding"],
                            "feature_summary": "numeric profile + category encoding",
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0, "rmse": 60.0},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_request", name="Experiment Request")
        session = AgentSession(
            id="as_exp_request",
            project_id=project.id,
            goal_text="Register requested runs.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "register_runs.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        assert ack["result"]["registered_count"] == 1
        assert ack["result"]["pipeline_registration"]["status"] == "missing"
        assert ack["result"]["pipeline_registration"]["missing_count"] == 1
        assert ack["result"]["model_diagnostics_artifacts"]["status"] == "missing"
        assert ack["result"]["model_diagnostics_artifacts"]["missing_count"] == 1
        assert ack["result"]["model_diagnostics_artifacts"]["missing_runs"][0]["missing_checks"] == [
            "permutation_importance",
            "native_feature_importance",
            "partial_dependence",
            "shap",
        ]
        assert ack["result"]["model_diagnostics_notebook"]["status"] == "missing"
        assert ack["result"]["model_diagnostics_notebook"]["missing_count"] == 1
        pipeline_request = pipeline_registration_request_path(workspace)
        assert pipeline_request.exists()
        pipeline_request_text = pipeline_request.read_text(encoding="utf-8")
        assert "tablex_pipeline_registration_request.v1" in pipeline_request_text
        assert "register_prediction_pipeline" in pipeline_request_text
        diagnostics_artifact_request = model_diagnostics_artifact_request_path(workspace)
        assert diagnostics_artifact_request.exists()
        diagnostics_artifact_request_text = diagnostics_artifact_request.read_text(encoding="utf-8")
        assert "tablex_model_diagnostics_artifact_request.v1" in diagnostics_artifact_request_text
        assert "tablex_model_diagnostics_request.v1" in diagnostics_artifact_request_text
        assert "register_model_diagnostics_artifacts" in diagnostics_artifact_request_text
        assert "permutation_importance" in diagnostics_artifact_request_text
        assert "native_feature_importance" in diagnostics_artifact_request_text
        assert "partial_dependence" in diagnostics_artifact_request_text
        assert "shap" in diagnostics_artifact_request_text
        diagnostics_request = model_diagnostics_notebook_request_path(workspace)
        assert diagnostics_request.exists()
        diagnostics_request_text = diagnostics_request.read_text(encoding="utf-8")
        assert "tablex_model_diagnostics_notebook_request.v1" in diagnostics_request_text
        assert "permutation_importance" in diagnostics_request_text
        assert "partial_dependence" in diagnostics_request_text
        assert "shap" in diagnostics_request_text
        assert "related_run_ids" in diagnostics_request_text
        run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run is not None
        params = loads_json(run.params_json, {})
        assert params["model_id"] == "glm_baseline"
        assert params["model_description"] == "A fold-safe GLM baseline."
        assert params["features_used"] == ["numeric_profile", "category_encoding"]
        assert params["feature_summary"] == "numeric profile + category encoding"
        assert run.summary_md == "A fold-safe GLM baseline."
        assert loads_json(run.metrics_json, {})["primary_metric_value"] == 42.0
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["response_brief"]["pipeline_registration"]["status"] == "missing"
        assert chat_payload["response_brief"]["model_diagnostics_artifacts"]["status"] == "missing"
        assert chat_payload["response_brief"]["model_diagnostics_notebook"]["status"] == "missing"
        assert "Still needed:" in chat_payload["assistant_message"]
        assert "reproducible train/predict scripts" in chat_payload["assistant_message"]
        assert "model diagnostics data for permutation importance" in chat_payload["assistant_message"]
        assert "model-diagnostics notebooks" in chat_payload["assistant_message"]


def test_experiment_result_request_skips_duplicate_result_signature_with_ack(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    first_payload = {
        "schema_version": "tablex_experiment_result_request.v1",
        "request_id": "exp_req_first",
        "operation": "register_runs",
        "payload": {
            "runs": [
                {
                    "model_id": "lgbm_relational_aggregates",
                    "model_description": "LightGBM using application features plus target-free relational aggregates.",
                    "features_used": ["application_train_raw", "bureau_aggregates"],
                    "feature_summary": "application raw fields plus bureau aggregates",
                    "primary_metric_name": "roc_auc",
                    "metrics": {"roc_auc": 0.7894239655657451},
                }
            ]
        },
    }
    second_payload = {
        **first_payload,
        "request_id": "exp_req_duplicate",
        "payload": {
            "runs": [
                {
                    "model_id": "lgbm_relational_aggregates",
                    "model_description": "The same fitted LightGBM, now described with fold-safe relational features.",
                    "features_used": ["application_train_raw", "bureau_aggregates"],
                    "feature_summary": "application fields plus relational SK_ID_CURR aggregates",
                    "primary_metric_name": "roc_auc",
                    "metrics": {"roc_auc": 0.7894239655657451},
                }
            ]
        },
    }
    (request_dir / "first.json").write_text(dumps_json(first_payload), encoding="utf-8")

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_duplicate_ack", name="Experiment Duplicate ACK")
        session = AgentSession(
            id="as_exp_duplicate_ack",
            project_id=project.id,
            goal_text="Register requested runs.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        first_ack = loads_json((experiment_acks_dir(workspace) / "first.ack.json").read_text(encoding="utf-8"), {})
        assert first_ack["status"] == "succeeded"
        assert first_ack["result"]["registered_count"] == 1
        first_run_id = first_ack["result"]["registered_run_ids"][0]

        (request_dir / "duplicate.json").write_text(dumps_json(second_payload), encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        second_ack = loads_json(
            (experiment_acks_dir(workspace) / "duplicate.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert second_ack["status"] == "succeeded"
        assert second_ack["result"]["registered_count"] == 0
        assert second_ack["result"]["duplicate_count"] == 1
        assert second_ack["result"]["registered_run_ids"] == []
        duplicate = second_ack["result"]["skipped_duplicates"][0]
        assert duplicate["model_id"] == "lgbm_relational_aggregates"
        assert duplicate["existing_run_id"] == first_run_id
        assert duplicate["reason"] == "result_signature_already_registered"
        runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
        assert len(runs) == 1


def test_experiment_result_request_links_runs_to_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    reports_dir = workspace / "reports"
    request_dir = experiment_requests_dir(workspace)
    reports_dir.mkdir(parents=True)
    request_dir.mkdir(parents=True)
    (reports_dir / "model_results_summary.md").write_text(
        "# Model result summary\n\nFold-safe candidate metrics are summarized here.\n",
        encoding="utf-8",
    )
    (request_dir / "register_runs.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "exp_req_plan_link",
                "operation": "register_runs",
                "payload": {
                    "research_plan_node_id": "modeling_and_diagnostics",
                    "source_workspace_path": "reports/model_results_summary.md",
                    "split_manifest_id": "split_exp_plan_link",
                    "runs": [
                        {
                            "model_id": "xgb_candidate",
                            "model_description": "A fold-safe boosted candidate.",
                            "features_used": ["numeric_profile", "gradient_boosting_features"],
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 40.0, "rmse": 59.0},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_exp_plan_link", name="Experiment Plan Link")
        session = AgentSession(
            id="as_exp_plan_link",
            project_id=project.id,
            goal_text="Register requested runs with plan links.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="exp_plan_dataset_artifact",
            filename="dataset.csv",
            text="x,y\n1,2\n",
            metadata={"project_id": project.id},
        )
        split_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="split_manifest",
            name="exp_plan_split_artifact",
            filename="split.json",
            text="{}",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_exp_plan_link",
            project_id=project.id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=2,
            column_count=2,
            schema_hash="schema_hash",
        )
        evaluation_spec = EvaluationSpec(
            id="eval_exp_plan_link",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            name="Group CV",
            split_type="group_split",
            primary_metric="mae",
            rationale_md="Use stable split evidence for the registered run.",
            risk_level="medium",
            status="approved",
        )
        split_manifest = SplitManifest(
            id="split_exp_plan_link",
            project_id=project.id,
            evaluation_spec_id=evaluation_spec.id,
            artifact_id=split_artifact.id,
            train_count=1,
            valid_count=1,
        )
        db.add_all([dataset, evaluation_spec, split_manifest])
        db.commit()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare modeling work.",
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="modeling_and_diagnostics",
            summary="Register model runs.",
            expected_outputs=["experiment_run", "leaderboard_entry"],
            revision_id=revision.id,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run is not None
        params = loads_json(run.params_json, {})
        assert params["research_plan_node_id"] == "modeling_and_diagnostics"
        assert run.dataset_snapshot_id == dataset.id
        assert run.evaluation_spec_id == evaluation_spec.id
        assert run.split_manifest_id == split_manifest.id
        assert params["dataset_snapshot_id"] == dataset.id
        assert params["evaluation_spec_id"] == evaluation_spec.id
        assert params["split_manifest_id"] == split_manifest.id
        assert params["source_artifact_id"]
        source_artifact = db.get(Artifact, params["source_artifact_id"])
        assert source_artifact is not None
        assert loads_json(source_artifact.metadata_json, {})["workspace_relative_path"] == "reports/model_results_summary.md"
        ack = loads_json((experiment_acks_dir(workspace) / "register_runs.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        assert ack["result"]["registered_runs"][0]["dataset_snapshot_id"] == dataset.id
        assert ack["result"]["registered_runs"][0]["evaluation_spec_id"] == evaluation_spec.id
        assert ack["result"]["registered_runs"][0]["split_manifest_id"] == split_manifest.id
        assert ack["result"]["registered_runs"][0]["source_artifact_id"] == source_artifact.id
        assert ack["result"]["chat_artifact_id"]
        assert ack["result"]["visible_surfaces"]["leaderboard"]["target_tab"] == "Leaderboard"
        assert ack["result"]["visible_surfaces"]["leaderboard"]["run_ids"] == [run.id]
        assert ack["result"]["visible_surfaces"]["assets"]["artifact_id"] == source_artifact.id
        assert ack["result"]["visible_surfaces"]["assets"]["target_anchor"] == "assets-artifact-preview"
        assert ack["result"]["visible_surfaces"]["data"]["dataset_snapshot_id"] == dataset.id
        assert ack["result"]["visible_surfaces"]["evaluation"]["evaluation_spec_ids"] == [evaluation_spec.id]
        assert ack["result"]["visible_surfaces"]["evaluation"]["split_manifest_ids"] == [split_manifest.id]
        assert ack["result"]["visible_surfaces"]["research_plan"]["node_ids"] == ["modeling_and_diagnostics"]
        assert ack["result"]["visible_surfaces"]["chat"]["artifact_id"] == ack["result"]["chat_artifact_id"]
        source_lineage = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "artifact",
                LineageEdge.from_asset_id == source_artifact.id,
                LineageEdge.to_asset_type == "experiment_run",
                LineageEdge.to_asset_id == run.id,
                LineageEdge.relation_type == "materializes_metrics_for",
            )
        )
        assert source_lineage is not None
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "research_plan_revision",
                LineageEdge.to_asset_type == "experiment_run",
                LineageEdge.to_asset_id == run.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
        )
        assert edge is not None
        assert loads_json(edge.metadata_json, {})["node_id"] == "modeling_and_diagnostics"
        source_plan_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == source_artifact.id,
            )
        )
        assert source_plan_edge is not None
        assert loads_json(source_plan_edge.metadata_json, {})["role"] == "experiment_evidence"
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        block_links = timeline["blocks"][0]["attached_artifacts"]
        timeline_run_link = next(link for link in block_links if link["link_type"] == "experiment_run")
        timeline_source_link = next(
            link
            for link in block_links
            if link["link_type"] == "artifact" and link["artifact_id"] == source_artifact.id
        )
        assert timeline_run_link["run_id"] == run.id
        assert timeline_run_link["target_tab"] == "Leaderboard"
        assert timeline_source_link["role"] == "experiment_evidence"
        chat_artifact = db.scalar(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registered"
        assert chat_payload["response_brief"]["research_plan_node_ids"] == ["modeling_and_diagnostics"]
        assert chat_payload["visible_surfaces"]["leaderboard"]["run_ids"] == [run.id]
        assert chat_payload["visible_surfaces"]["assets"]["artifact_id"] == source_artifact.id
        assert chat_payload["visible_surfaces"]["data"]["dataset_snapshot_id"] == dataset.id
        assert chat_payload["visible_surfaces"]["evaluation"]["evaluation_spec_ids"] == [evaluation_spec.id]
        assert chat_payload["visible_surfaces"]["evaluation"]["split_manifest_ids"] == [split_manifest.id]
        assert any(action["target_tab"] == "Assets" for action in chat_payload["actions"])
        assert any(action["target_tab"] == "Data" for action in chat_payload["actions"])
        assert any(action["target_tab"] == "Evaluation" for action in chat_payload["actions"])


def test_experiment_visibility_restore_ignores_missing_source_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_stale_source_artifact", name="Stale Source Artifact")
        session = AgentSession(
            id="as_stale_source_artifact",
            project_id=project.id,
            goal_text="Restore visibility without stale artifact crashes.",
        )
        db.add_all([project, session])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare modeling work.",
            strict_validation=True,
        )
        run = ExperimentRun(
            id="run_stale_source_artifact",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json(
                {
                    "agent_session_id": session.id,
                    "source_artifact_id": "art_missing",
                    "research_plan_node_id": "modeling",
                    "model_id": "described_model",
                    "model_description": "A described model with a stale source artifact pointer.",
                }
            ),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 12.0, "mae": 12.0}),
            summary_md="A described model with a stale source artifact pointer.",
        )
        db.add(run)
        db.commit()

        restored = restore_registered_session_experiment_visibility(db, store=store, project=project, session=session)
        db.commit()

        assert [item.id for item in restored] == [run.id]
        run_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "research_plan_revision",
                LineageEdge.to_asset_type == "experiment_run",
                LineageEdge.to_asset_id == run.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
        )
        assert run_edge is not None
        stale_artifact_edge_count = db.scalar(
            select(func.count())
            .select_from(LineageEdge)
            .where(
                LineageEdge.project_id == project.id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == "art_missing",
            )
        )
        assert stale_artifact_edge_count == 0


def test_failed_experiment_result_file_request_is_announced_in_agent_chat(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "bad_register_runs.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "bad_exp_req",
                "operation": "register_runs",
                "payload": {"runs": []},
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_bad_exp_request", name="Bad Experiment Request")
        session = AgentSession(
            id="as_bad_exp_request",
            project_id=project.id,
            goal_text="Announce failed model result registration.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "bad_register_runs.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        rejection = experiment_request_rejection_path(workspace)
        assert rejection.exists()
        rejection_text = rejection.read_text(encoding="utf-8")
        assert "tablex_experiment_result_request_rejection.v1" in rejection_text
        assert "bad_exp_req" in rejection_text
        assert ".tablex/acks/experiments/bad_register_runs.ack.json" in rejection_text
        assert "did not create ExperimentRun records" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "experiment_results_registration_failed"
        assert chat_payload["intent"]["status"] == "needs_attention"


def test_experiment_result_request_rejects_wrong_schema_version(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "wrong_schema.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "request_id": "wrong_schema",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "glm_baseline",
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_wrong_exp_schema", name="Wrong Experiment Schema")
        session = AgentSession(
            id="as_wrong_exp_schema",
            project_id=project.id,
            goal_text="Reject wrong experiment schema.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "wrong_schema.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "tablex_experiment_result_request.v1" in ack["error"]["message"]
        assert db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id)) == 0


def test_pipeline_request_registers_prediction_pipeline_and_links_run(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "median_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "id_columns": [], "prediction_column": "prediction"},
        "training": {"dataset_snapshot_id": "ds_pipeline", "split_manifest_id": None, "evaluation_spec_id": None, "seed": 7, "deterministic": True},
        "expected_metrics": [{"name": "mae", "value": 1.0, "split": "validation"}],
        "runtime": {"python": ">=3.11", "timeout_seconds_predict": 120},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.output, 'w', encoding='utf-8', newline='') as f:\n"
        "    writer = csv.DictWriter(f, fieldnames=['prediction'])\n"
        "    writer.writeheader()\n"
        "    writer.writerow({'prediction': '1.0'})\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Median pipeline\n", encoding="utf-8")
    (pipeline_dir / ".tablex_smoke" / "register_pipeline").mkdir(parents=True)
    (pipeline_dir / ".tablex_smoke" / "register_pipeline" / "input.csv").write_text("x\n1\n", encoding="utf-8")
    (pipeline_dir / "__pycache__").mkdir()
    (pipeline_dir / "__pycache__" / "predict.cpython-313.pyc").write_bytes(b"cache")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "register_pipeline.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "register_pipeline",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "median_pipeline",
                    "workspace_dir": "pipelines/median_pipeline",
                    "experiment_run_ids": ["run_pipeline"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline", name="Pipeline Project")
        session = AgentSession(id="as_pipeline", project_id=project.id, goal_text="Register pipeline.", workspace_path=str(workspace))
        run = ExperimentRun(
            id="run_pipeline",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "median_model", "model_description": "A reproducible median pipeline.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="A reproducible median pipeline.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((pipeline_acks_dir(workspace) / "register_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "queued"
        assert ack["job_id"]
        assert db.scalar(select(func.count()).select_from(Artifact).where(Artifact.asset_type == "prediction_pipeline")) == 0

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "succeeded"

        ack = loads_json((pipeline_acks_dir(workspace) / "register_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        assert ack["job_id"] == job.id
        assert ack["result"]["smoke_validation"]["status"] == "passed"
        assert ack["result"]["smoke_validation"]["runtime_isolated"] is True
        assert ack["result"]["smoke_validation"]["requirements_hash"]
        assert ack["result"]["metric_reproduction"]["metric_reproduced"] is True
        artifact = db.get(Artifact, ack["result"]["pipeline_artifact_id"])
        assert artifact is not None
        assert artifact.asset_type == "prediction_pipeline"
        assert artifact_primary_path(artifact).name == "median_pipeline.zip"
        with zipfile.ZipFile(artifact_primary_path(artifact)) as archive:
            names = archive.namelist()
            assert "predict.py" in names
            assert "pipeline_manifest.json" in names
            assert not any(name.startswith(".tablex_smoke/") for name in names)
            assert not any("__pycache__/" in name for name in names)
            assert not any(name.endswith((".pyc", ".pyo")) for name in names)
        refreshed_run = db.get(ExperimentRun, "run_pipeline")
        assert refreshed_run is not None
        assert loads_json(refreshed_run.params_json, {})["pipeline_artifact_id"] == artifact.id
        assert loads_json(artifact.metadata_json, {})["metric_reproduction"]["metric_reproduced"] is True
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "experiment_run",
                LineageEdge.from_asset_id == "run_pipeline",
                LineageEdge.to_asset_id == artifact.id,
                LineageEdge.relation_type == "materializes_prediction_pipeline",
            )
        )
        assert edge is not None


def test_pipeline_manifest_normalizes_required_tables_contract() -> None:
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {"columns": ["x"]},
            "required_tables": [
                {
                    "name": "application",
                    "role": "primary",
                    "columns": ["x", {"name": "row_id", "dtype": "string", "required": False}],
                    "join_keys": ["row_id"],
                },
                {
                    "name": "bureau",
                    "role": "history",
                    "columns": [{"name": "balance", "dtype": "float"}],
                    "join_keys": ["row_id"],
                    "as_of_column": "event_time",
                    "history_window": "365d",
                    "optional": True,
                },
            ],
        },
        "output_contract": {"columns": ["prediction"], "prediction_column": "prediction"},
        "training": {},
        "runtime": {},
    }

    normalized, warnings = pipeline_requests_module.normalize_pipeline_manifest(manifest)

    assert "pipeline_manifest.input_contract.inference_format.string_columns_normalized" in warnings
    tables = normalized["input_contract"]["required_tables"]
    assert tables[0]["columns"] == [
        {"name": "x", "dtype": "string", "required": True},
        {"name": "row_id", "dtype": "string", "required": False},
    ]
    assert tables[1]["role"] == "history"
    assert tables[1]["as_of_column"] == "event_time"
    assert tables[1]["history_window"] == "365d"
    assert tables[1]["optional"] is True


def test_pipeline_smoke_uses_required_tables_selftest_input_dir(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "multitable_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv, json\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input-dir', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "manifest = json.loads((Path(args.input_dir) / 'manifest.json').read_text(encoding='utf-8'))\n"
        "tables = {item['name']: item for item in manifest['tables']}\n"
        "application_path = Path(args.input_dir) / tables['application']['filename']\n"
        "with application_path.open(encoding='utf-8', newline='') as src, open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    rows = list(csv.DictReader(src))\n"
        "    writer = csv.DictWriter(dst, fieldnames=['SK_ID_CURR', 'prediction'])\n"
        "    writer.writeheader()\n"
        "    for row in rows:\n"
        "        writer.writerow({'SK_ID_CURR': row['SK_ID_CURR'], 'prediction': '0.25'})\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    selftest_dir = pipeline_dir / "selftest" / "input"
    selftest_dir.mkdir(parents=True)
    (selftest_dir / "application.csv").write_text("SK_ID_CURR,AMT_CREDIT\n1,100\n2,200\n", encoding="utf-8")
    (selftest_dir / "bureau.csv").write_text("SK_ID_CURR,DAYS_CREDIT\n1,-10\n2,-20\n", encoding="utf-8")
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {"columns": [{"name": "SK_ID_CURR", "dtype": "string"}]},
            "required_tables": [
                {
                    "name": "application",
                    "role": "primary",
                    "columns": [
                        {"name": "SK_ID_CURR", "dtype": "string"},
                        {"name": "AMT_CREDIT", "dtype": "float"},
                    ],
                    "join_keys": ["SK_ID_CURR"],
                },
                {
                    "name": "bureau",
                    "role": "history",
                    "columns": [
                        {"name": "SK_ID_CURR", "dtype": "string"},
                        {"name": "DAYS_CREDIT", "dtype": "integer"},
                    ],
                    "join_keys": ["SK_ID_CURR"],
                },
            ],
        },
        "output_contract": {
            "columns": [{"name": "SK_ID_CURR", "dtype": "string"}, {"name": "prediction", "dtype": "float"}],
            "id_columns": ["SK_ID_CURR"],
            "prediction_column": "prediction",
        },
        "training": {},
        "expected_metrics": [],
        "runtime": {"timeout_seconds_predict": 120},
    }
    normalized, _warnings = pipeline_requests_module.normalize_pipeline_manifest(manifest)

    result = pipeline_requests_module.smoke_validate_prediction_pipeline(
        pipeline_dir,
        workspace=None,
        manifest=normalized,
        request_id="multitable_smoke",
    )

    assert result["status"] == "passed"
    assert result["input_mode"] == "input_dir"
    assert result["input_source"] == "selftest/input"
    assert result["input_rows"] == 2
    assert result["output_rows"] == 2


def test_pipeline_smoke_rejects_required_tables_without_selftest(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "missing_selftest_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text("print('unused')\n", encoding="utf-8")
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {"columns": [{"name": "SK_ID_CURR", "dtype": "string"}]},
            "required_tables": [
                {
                    "name": "application",
                    "role": "primary",
                    "columns": [{"name": "SK_ID_CURR", "dtype": "string"}],
                    "join_keys": ["SK_ID_CURR"],
                }
            ],
        },
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "prediction_column": "prediction"},
        "training": {},
        "expected_metrics": [],
        "runtime": {"timeout_seconds_predict": 120},
    }
    normalized, _warnings = pipeline_requests_module.normalize_pipeline_manifest(manifest)

    try:
        pipeline_requests_module.smoke_validate_prediction_pipeline(
            pipeline_dir,
            workspace=None,
            manifest=normalized,
            request_id="missing_selftest",
        )
    except pipeline_requests_module.PipelineToolValidationError as exc:
        assert "selftest/input" in str(exc)
        assert exc.issues[0]["pointer"] == "pipeline.selftest.input"
    else:
        raise AssertionError("required_tables smoke validation should require selftest/input files")


def test_pipeline_smoke_fails_when_predict_requires_columns_missing_from_manifest_selftest(tmp_path: Path) -> None:
    pipeline_dir = tmp_path / "underdeclared_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.input, encoding='utf-8', newline='') as src:\n"
        "    row = next(csv.DictReader(src))\n"
        "    _ = row['EMERGENCYSTATE_MODE']\n"
        "with open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    dst.write('prediction\\n0.5\\n')\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    selftest_dir = pipeline_dir / "selftest"
    selftest_dir.mkdir()
    (selftest_dir / "input.csv").write_text("SK_ID_CURR\n1\n", encoding="utf-8")
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {"columns": [{"name": "SK_ID_CURR", "dtype": "string"}]},
        },
        "output_contract": {
            "columns": [{"name": "prediction", "dtype": "float"}],
            "prediction_column": "prediction",
        },
        "training": {},
        "expected_metrics": [],
        "runtime": {"timeout_seconds_predict": 120},
    }
    normalized, _warnings = pipeline_requests_module.normalize_pipeline_manifest(manifest)

    try:
        pipeline_requests_module.smoke_validate_prediction_pipeline(
            pipeline_dir,
            workspace=None,
            manifest=normalized,
            request_id="underdeclared",
        )
    except pipeline_requests_module.PipelineToolValidationError as exc:
        assert exc.issues[0]["pointer"] == "pipeline.predict"
        assert "EMERGENCYSTATE_MODE" in exc.issues[0]["stderr_tail"]
    else:
        raise AssertionError("smoke validation should execute predict.py and catch undeclared required columns")


def test_pipeline_request_accepts_top_level_codex_aliases(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "alias_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {
            "columns": [{"name": "prediction", "dtype": "float"}],
            "id_columns": [],
            "prediction_column": "prediction",
        },
        "training": {
            "dataset_snapshot_id": "ds_alias_pipeline",
            "split_manifest_id": None,
            "evaluation_spec_id": None,
            "seed": 0,
            "deterministic": True,
        },
        "expected_metrics": [{"name": "mae", "value": 1.0, "split": "validation"}],
        "runtime": {"python": ">=3.11", "timeout_seconds_predict": 120},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.output, 'w', encoding='utf-8', newline='') as f:\n"
        "    writer = csv.DictWriter(f, fieldnames=['prediction'])\n"
        "    writer.writeheader()\n"
        "    writer.writerow({'prediction': '1.0'})\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Alias pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "register_alias_pipeline.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "register_alias_pipeline",
                "operation": "register_prediction_pipeline",
                "run_id": "run_alias_pipeline",
                "model_id": "alias_pipeline",
                "workspace_path": "pipelines/alias_pipeline",
                "pipeline_manifest_path": "pipelines/alias_pipeline/pipeline_manifest.json",
                "research_plan_node_id": "evaluation_modeling",
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_alias", name="Pipeline Alias")
        session = AgentSession(
            id="as_pipeline_alias",
            project_id=project.id,
            goal_text="Register alias-shaped pipeline.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(
            id="run_alias_pipeline",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json(
                {
                    "model_id": "alias_pipeline",
                    "model_description": "Alias shaped pipeline.",
                    "features_used": ["x"],
                }
            ),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Alias shaped pipeline.",
        )
        db.add_all([project, session, run])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "evaluation_modeling",
                        "title": "Evaluation and modeling",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Register pipeline for the active modeling node.",
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json(
            (pipeline_acks_dir(workspace) / "register_alias_pipeline.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert queued_ack["status"] == "queued"
        assert "payload.workspace_path_alias_for_workspace_dir" in queued_ack["compatibility_warnings"]
        assert "payload.run_id_alias_for_experiment_run_ids" in queued_ack["compatibility_warnings"]
        assert "payload.pipeline_name_derived_from_fixed_id" in queued_ack["compatibility_warnings"]

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "succeeded"
        ack = loads_json(
            (pipeline_acks_dir(workspace) / "register_alias_pipeline.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "succeeded"
        assert ack["result"]["experiment_run_ids"] == ["run_alias_pipeline"]
        artifact = db.get(Artifact, ack["result"]["pipeline_artifact_id"])
        assert artifact is not None
        assert artifact_primary_path(artifact).name == "alias_pipeline.zip"


def test_pipeline_request_accepts_live_codex_manifest_compatibility(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "live_pipeline"
    pipeline_dir.mkdir(parents=True)
    source_data = tmp_path / "source.csv"
    source_data.write_text("row_id,x,y\nrow_1,2.5,10\n", encoding="utf-8")
    data_dir = workspace / ".tablex" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "live.csv").symlink_to(source_data)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "model_id": "live_pipeline",
        "model_description": "Compatibility fixture.",
        "features_used": ["x"],
        "source_data_workspace_path": ".tablex/data/live.csv",
        "history_requirements": [],
        "input_contract": {
            "inference_format": {"columns": ["x", "row_id"]},
            "forbidden_columns_at_inference": ["y"],
            "target_column": "y",
            "requires_target_column": False,
        },
        "output_contract": {
            "format": "csv",
            "columns": ["row_id", "prediction"],
            "prediction_column": "prediction",
        },
        "training": {"target_column": "y"},
        "expected_metrics": [{"metric": "mae", "value": 1.0, "split": "validation"}],
        "runtime": {"python_version": "3.13", "requirements_file": "requirements.txt"},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.input, encoding='utf-8-sig', newline='') as src, open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    reader = csv.DictReader(src)\n"
        "    writer = csv.DictWriter(dst, fieldnames=['row_id', 'prediction'])\n"
        "    writer.writeheader()\n"
        "    for row in reader:\n"
        "        writer.writerow({'row_id': row.get('row_id', ''), 'prediction': '1.0'})\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Live pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "register_live_pipeline.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "register_live_pipeline",
                "operation": "register_prediction_pipeline",
                "pipeline_name": "live_pipeline",
                "workspace_dir": "pipelines/live_pipeline",
                "run_ids": ["run_live"],
                "manifest_workspace_path": "pipelines/live_pipeline/pipeline_manifest.json",
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_live", name="Pipeline Live")
        session = AgentSession(
            id="as_pipeline_live",
            project_id=project.id,
            goal_text="Register live-shaped pipeline.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(
            id="run_live",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "live_model", "model_description": "Live compatible.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Live compatible.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json(
            (pipeline_acks_dir(workspace) / "register_live_pipeline.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert queued_ack["status"] == "queued"
        assert "top_level_pipeline_payload_fields" in queued_ack["compatibility_warnings"]
        assert "payload.run_ids_alias_for_experiment_run_ids" in queued_ack["compatibility_warnings"]

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "succeeded"

        ack = loads_json((pipeline_acks_dir(workspace) / "register_live_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        warnings = ack["result"]["compatibility_warnings"]
        assert "top_level_pipeline_payload_fields" in warnings
        assert "payload.run_ids_alias_for_experiment_run_ids" in warnings
        assert "pipeline_manifest.input_contract.inference_format.string_columns_normalized" in warnings
        assert "pipeline_manifest.output_contract.string_columns_normalized" in warnings
        assert "pipeline_manifest.expected_metrics.metric_alias_normalized" in warnings
        assert ack["result"]["smoke_validation"]["input_source"] == "manifest.source_data_workspace_path"
        assert ack["result"]["metric_reproduction"]["metric_reproduced"] is True
        artifact = db.get(Artifact, ack["result"]["pipeline_artifact_id"])
        assert artifact is not None
        metadata = loads_json(artifact.metadata_json, {})
        assert metadata["pipeline_manifest"]["input_contract"]["inference_format"]["columns"][0]["name"] == "x"
        assert metadata["submitted_pipeline_manifest"]["input_contract"]["inference_format"]["columns"] == ["x", "row_id"]


def test_pipeline_request_reports_manifest_schema_issues_together(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "invalid_manifest"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "wrong",
        "input_contract": "not an object",
        "output_contract": {},
        "training": [],
        "runtime": None,
        "expected_metrics": "bad",
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text("print('predict')\n", encoding="utf-8")
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Invalid\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "invalid_manifest.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "invalid_manifest",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "invalid_manifest",
                    "workspace_dir": "pipelines/invalid_manifest",
                    "experiment_run_ids": ["run_invalid_manifest"],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_invalid_manifest", name="Pipeline Invalid Manifest")
        session = AgentSession(
            id="as_pipeline_invalid_manifest",
            project_id=project.id,
            goal_text="Reject invalid manifest.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(
            id="run_invalid_manifest",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "invalid", "model_description": "Invalid manifest.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Invalid manifest.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "invalid_manifest.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        issues = ack["error"]["issues"]
        pointers = {issue["pointer"] for issue in issues}
        assert "pipeline_manifest.schema_version" in pointers
        assert "pipeline_manifest.input_contract" in pointers
        assert "pipeline_manifest.output_contract.prediction_column" in pointers
        assert "pipeline_manifest.training" in pointers
        assert "pipeline_manifest.runtime" in pointers
        assert "pipeline_manifest.expected_metrics" in pointers


def test_pipeline_request_rejects_missing_required_file(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "broken_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {},
        "output_contract": {"prediction_column": "prediction"},
        "training": {},
        "runtime": {},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "broken_pipeline.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "broken_pipeline",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "broken_pipeline",
                    "workspace_dir": "pipelines/broken_pipeline",
                    "experiment_run_ids": ["run_missing"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_bad", name="Pipeline Bad")
        session = AgentSession(id="as_pipeline_bad", project_id=project.id, goal_text="Reject bad pipeline.", workspace_path=str(workspace))
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json((pipeline_acks_dir(workspace) / "broken_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert queued_ack["status"] == "queued"

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "broken_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert ack["job_id"] == job.id
        assert "missing required files" in ack["error"]["message"]
        assert db.scalar(select(func.count()).select_from(Artifact).where(Artifact.asset_type == "prediction_pipeline")) == 0


def test_pipeline_request_rejects_smoke_output_contract_violation(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "bad_output_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "prediction_column": "prediction"},
        "training": {"dataset_snapshot_id": None, "split_manifest_id": None, "evaluation_spec_id": None, "seed": 1, "deterministic": True},
        "runtime": {"python": ">=3.11", "timeout_seconds_predict": 120},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "with open(args.output, 'w', encoding='utf-8', newline='') as f:\n"
        "    writer = csv.DictWriter(f, fieldnames=['wrong_column'])\n"
        "    writer.writeheader()\n"
        "    writer.writerow({'wrong_column': '1.0'})\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Bad output pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "bad_output.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "bad_output",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "bad_output_pipeline",
                    "workspace_dir": "pipelines/bad_output_pipeline",
                    "experiment_run_ids": ["run_bad_output"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_bad_output", name="Pipeline Bad Output")
        session = AgentSession(id="as_pipeline_bad_output", project_id=project.id, goal_text="Reject bad output pipeline.", workspace_path=str(workspace))
        run = ExperimentRun(
            id="run_bad_output",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "bad_output", "model_description": "Bad output pipeline.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Bad output pipeline.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json((pipeline_acks_dir(workspace) / "bad_output.ack.json").read_text(encoding="utf-8"), {})
        assert queued_ack["status"] == "queued"

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "bad_output.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert ack["job_id"] == job.id
        assert "missing column" in ack["error"]["message"]
        assert ack["error"]["issues"][0]["pointer"] == "pipeline.output.columns"
        assert ack["error"]["issues"][0]["missing_columns"] == ["prediction"]
        assert db.scalar(select(func.count()).select_from(Artifact).where(Artifact.asset_type == "prediction_pipeline")) == 0


def test_pipeline_request_returns_structured_predict_failure_issue(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "missing_model_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "prediction_column": "prediction"},
        "training": {},
        "runtime": {"timeout_seconds_predict": 120},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import argparse, pathlib\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "parser.parse_args()\n"
        "pathlib.Path('model.joblib').read_bytes()\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Missing model pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "missing_model.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "missing_model",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "missing_model_pipeline",
                    "workspace_dir": "pipelines/missing_model_pipeline",
                    "experiment_run_ids": ["run_missing_model"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_missing_model", name="Pipeline Missing Model")
        session = AgentSession(
            id="as_pipeline_missing_model",
            project_id=project.id,
            goal_text="Reject incomplete pipeline.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(
            id="run_missing_model",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "missing_model", "model_description": "Missing model pipeline.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Missing model pipeline.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "missing_model.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "Prediction pipeline smoke run failed" in ack["error"]["message"]
        assert ack["error"]["issues"][0]["pointer"] == "pipeline.predict"
        assert ack["error"]["issues"][0]["exit_code"] == 1
        assert "model.joblib" in ack["error"]["issues"][0]["stderr_tail"]


def test_pipeline_request_rejects_unsupported_requirements_option(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "bad_requirements_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "prediction_column": "prediction"},
        "training": {},
        "runtime": {"timeout_seconds_predict": 120},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text("print('predict')\n", encoding="utf-8")
    (pipeline_dir / "requirements.txt").write_text("--extra-index-url https://example.invalid/simple\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Bad requirements pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "bad_requirements.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "bad_requirements",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "bad_requirements_pipeline",
                    "workspace_dir": "pipelines/bad_requirements_pipeline",
                    "experiment_run_ids": ["run_bad_requirements"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_bad_requirements", name="Pipeline Bad Requirements")
        session = AgentSession(id="as_pipeline_bad_requirements", project_id=project.id, goal_text="Reject bad requirements.", workspace_path=str(workspace))
        run = ExperimentRun(
            id="run_bad_requirements",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "bad_requirements", "model_description": "Bad requirements pipeline.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Bad requirements pipeline.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json((pipeline_acks_dir(workspace) / "bad_requirements.ack.json").read_text(encoding="utf-8"), {})
        assert queued_ack["status"] == "queued"

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "bad_requirements.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert ack["job_id"] == job.id
        assert "requirements.txt" in ack["error"]["message"]


def test_pipeline_request_rejects_smoke_timeout(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pipeline_dir = workspace / "pipelines" / "timeout_pipeline"
    pipeline_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {"inference_format": {"columns": [{"name": "x", "dtype": "float", "required": True}]}},
        "output_contract": {"columns": [{"name": "prediction", "dtype": "float"}], "prediction_column": "prediction"},
        "training": {},
        "runtime": {"timeout_seconds_predict": 1},
    }
    (pipeline_dir / "pipeline_manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    (pipeline_dir / "train.py").write_text("print('train')\n", encoding="utf-8")
    (pipeline_dir / "predict.py").write_text(
        "import time\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    (pipeline_dir / "requirements.txt").write_text("\n", encoding="utf-8")
    (pipeline_dir / "README.md").write_text("# Timeout pipeline\n", encoding="utf-8")
    request_dir = pipeline_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "timeout_pipeline.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_pipeline_request.v1",
                "request_id": "timeout_pipeline",
                "operation": "register_prediction_pipeline",
                "payload": {
                    "pipeline_name": "timeout_pipeline",
                    "workspace_dir": "pipelines/timeout_pipeline",
                    "experiment_run_ids": ["run_timeout_pipeline"],
                    "manifest": manifest,
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_timeout", name="Pipeline Timeout")
        session = AgentSession(id="as_pipeline_timeout", project_id=project.id, goal_text="Reject timeout pipeline.", workspace_path=str(workspace))
        run = ExperimentRun(
            id="run_timeout_pipeline",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"model_id": "timeout", "model_description": "Timeout pipeline.", "features_used": ["x"]}),
            metrics_json=dumps_json({"primary_metric_name": "mae", "primary_metric_value": 1.0, "mae": 1.0}),
            summary_md="Timeout pipeline.",
        )
        db.add_all([project, session, run])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        queued_ack = loads_json((pipeline_acks_dir(workspace) / "timeout_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert queued_ack["status"] == "queued"

        job = run_queued_pipeline_registration_worker(db, store, project.id)
        assert job.status == "failed"

        ack = loads_json((pipeline_acks_dir(workspace) / "timeout_pipeline.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert ack["job_id"] == job.id
        assert "timed out" in ack["error"]["message"]
        assert ack["error"]["issues"][0]["pointer"] == "pipeline.predict"
        assert ack["error"]["issues"][0]["timeout_seconds"] == 1


def test_prediction_pipeline_worker_runs_predict_and_registers_batch(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, shutil\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "shutil.copyfile(args.input, args.output)\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "predict.py", "predict.py")

    with sessionmaker(engine)() as db:
        project = Project(id="p_pipeline_run", name="Pipeline Run")
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "copy_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="copy_pipeline",
            version=version,
            source_path=bundle_path,
            filename="copy_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="copy_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "copy_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        input_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="prediction_input",
            filename="input.csv",
            text="x\n1\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_predict",
            project_id=project.id,
            artifact_id=input_artifact.id,
            source_type="upload",
            source_ref="input.csv",
            row_count=1,
            column_count=1,
            schema_hash="predict_schema",
        )
        deployment = PilotDeployment(
            id="pdep_predict",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        job = Job(
            id="job_predict",
            project_id=project.id,
            job_type="run_prediction_pipeline",
            input_json=dumps_json(
                {
                    "deployment_id": deployment.id,
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "dataset_snapshot_id": dataset.id,
                    "as_of": "2026-07-06T00:00:00Z",
                }
            ),
            status="running",
        )
        db.add_all([dataset, deployment, job])
        db.commit()

        output = run_prediction_pipeline_handler(db, job, store)
        db.commit()

        prediction_artifact = db.get(Artifact, output["prediction_batch_artifact_id"])
        assert prediction_artifact is not None
        assert prediction_artifact.asset_type == "prediction_batch"
        assert output["pilot_prediction_batch_id"] is not None
        pilot_batch = db.get(PilotPredictionBatch, output["pilot_prediction_batch_id"])
        assert pilot_batch is not None
        assert pilot_batch.deployment_id == deployment.id
        assert pilot_batch.row_count == 1
        assert pilot_batch.predictions_artifact_id == prediction_artifact.id
        assert artifact_primary_path(prediction_artifact).read_text(encoding="utf-8") == "x\n1\n"
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.from_asset_id == pipeline_artifact.id,
                LineageEdge.to_asset_id == prediction_artifact.id,
                LineageEdge.relation_type == "produces_prediction_batch",
            )
        )
        assert edge is not None


def test_prediction_pipeline_worker_runs_multitable_input_dir(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "multitable_pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input-dir', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "input_dir = Path(args.input_dir)\n"
        "with open(input_dir / 'application.csv', encoding='utf-8', newline='') as f:\n"
        "    app_rows = list(csv.DictReader(f))\n"
        "with open(input_dir / 'bureau.csv', encoding='utf-8', newline='') as f:\n"
        "    bureau_rows = list(csv.DictReader(f))\n"
        "with open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    dst.write('application_rows,bureau_rows\\n')\n"
        "    dst.write(f'{len(app_rows)},{len(bureau_rows)}\\n')\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "multitable_pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "predict.py", "predict.py")

    with sessionmaker(engine)() as db:
        project = Project(id="p_multitable_pipeline_run", name="Multitable Pipeline Run")
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "multitable_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="multitable_pipeline",
            version=version,
            source_path=bundle_path,
            filename="multitable_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="multitable_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "multitable_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        application_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_input",
            name="application_prediction_input",
            filename="application.csv",
            text="SK_ID_CURR,feature\n1,0.2\n2,0.4\n",
            metadata={"project_id": project.id, "table_name": "application"},
        )
        bureau_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_input",
            name="bureau_prediction_input",
            filename="bureau.csv",
            text="SK_ID_CURR,balance\n1,10\n1,20\n2,30\n",
            metadata={"project_id": project.id, "table_name": "bureau"},
        )
        job = Job(
            id="job_multitable_predict",
            project_id=project.id,
            job_type="run_prediction_pipeline",
            input_json=dumps_json(
                {
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "input_artifact_ids_by_table": {
                        "application": application_artifact.id,
                        "bureau": bureau_artifact.id,
                    },
                }
            ),
            status="running",
        )
        db.add(job)
        db.commit()

        output = run_prediction_pipeline_handler(db, job, store)
        db.commit()

        prediction_artifact = db.get(Artifact, output["prediction_batch_artifact_id"])
        assert prediction_artifact is not None
        assert output["row_source"].endswith("input_dir")
        assert artifact_primary_path(prediction_artifact).read_text(encoding="utf-8") == "application_rows,bureau_rows\n2,3\n"
        metadata = loads_json(prediction_artifact.metadata_json, {})
        assert metadata["input_artifact_ids_by_table"] == {
            "application": application_artifact.id,
            "bureau": bureau_artifact.id,
        }
        assert metadata["batch_kind"] == "external_test"


def test_prediction_pipeline_runtime_failure_is_summarized_and_returned_to_codex(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pipeline_dir = tmp_path / "failing_pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, sys\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "parser.parse_args()\n"
        "sys.stderr.write('ValueError: pandas dtypes must be int, float or bool.\\n')\n"
        "sys.stderr.write('Fields with bad pandas dtypes: EMERGENCYSTATE_MODE: str\\n')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "failing_pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "predict.py", "predict.py")

    with sessionmaker(engine)() as db:
        project = Project(id="p_predict_failure", name="Prediction Failure")
        session = AgentSession(
            id="ags_predict_failure",
            project_id=project.id,
            status="completed",
            goal_text="Repair failed prediction pipelines.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "failing_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="failing_pipeline",
            version=version,
            source_path=bundle_path,
            filename="failing_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="failing_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "failing_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        prediction_input = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_input",
            name="application_test",
            filename="application_test.csv",
            text="SK_ID_CURR,EMERGENCYSTATE_MODE\n1,No\n",
            metadata={"project_id": project.id, "table_name": "prediction_input"},
        )
        job = Job(
            id="job_predict_failure",
            project_id=project.id,
            job_type="run_prediction_pipeline",
            input_json=dumps_json(
                {
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "input_artifact_id": prediction_input.id,
                }
            ),
            status="running",
        )
        db.add(job)
        db.commit()

        output = run_prediction_pipeline_handler(db, job, store)
        db.commit()

        assert output["job_status"] == "failed"
        assert str(output["error_message"]) == "Prediction pipeline failed while running predict.py (exit code 1)."
        assert "EMERGENCYSTATE_MODE" not in str(output["error_message"])
        assert "前処理" not in str(output["error_message"])
        assert "stderr_tail" in output
        assert "EMERGENCYSTATE_MODE" in str(output["stderr_tail"])
        feedback = output["codex_feedback"]
        assert isinstance(feedback, dict)
        assert feedback["delivered"] is True
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "prediction_pipeline_runtime_failed",
            )
        )
        assert event is not None
        payload = loads_json(event.payload_json, {})
        assert payload["exit_code"] == 1
        assert payload["error_summary"] == "Prediction pipeline failed while running predict.py (exit code 1)."
        assert "EMERGENCYSTATE_MODE" not in payload["error_summary"]
        assert "EMERGENCYSTATE_MODE" in payload["stderr_tail"]
        inbox_entries = list_inbox_entries(workspace)
        runtime_failure_entries = [entry for entry in inbox_entries if entry.get("type") == "prediction_pipeline_runtime_failed"]
        assert len(runtime_failure_entries) == 1
        assert "Tablex has not inferred the root cause" in runtime_failure_entries[0]["content"]

        duplicate_job = Job(
            id="job_predict_failure_duplicate",
            project_id=project.id,
            job_type="run_prediction_pipeline",
            input_json=dumps_json(
                {
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "input_artifact_id": prediction_input.id,
                }
            ),
            status="running",
        )
        db.add(duplicate_job)
        db.commit()

        duplicate_output = run_prediction_pipeline_handler(db, duplicate_job, store)
        db.commit()

        assert duplicate_output["job_status"] == "failed"
        duplicate_feedback = duplicate_output["codex_feedback"]
        assert duplicate_feedback["delivered"] is True
        assert duplicate_feedback["deduplicated"] is True
        assert duplicate_feedback["attention_key"] == feedback["attention_key"]
        duplicate_inbox_entries = list_inbox_entries(workspace)
        duplicate_runtime_failure_entries = [
            entry for entry in duplicate_inbox_entries if entry.get("type") == "prediction_pipeline_runtime_failed"
        ]
        assert len(duplicate_runtime_failure_entries) == 1


def test_prediction_pipeline_worker_passes_history_for_time_series_features(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "history_pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "predict.py").write_text(
        "import argparse, csv\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--input', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "parser.add_argument('--history', required=True)\n"
        "args = parser.parse_args()\n"
        "history = {}\n"
        "with open(args.history, encoding='utf-8', newline='') as f:\n"
        "    for row in csv.DictReader(f):\n"
        "        history.setdefault(row['item_id'], []).append(float(row['sales']))\n"
        "with open(args.input, encoding='utf-8', newline='') as src, open(args.output, 'w', encoding='utf-8', newline='') as dst:\n"
        "    reader = csv.DictReader(src)\n"
        "    writer = csv.DictWriter(dst, fieldnames=['item_id', 'prediction'])\n"
        "    writer.writeheader()\n"
        "    for row in reader:\n"
        "        values = history.get(row['item_id'], [0.0])[-3:]\n"
        "        writer.writerow({'item_id': row['item_id'], 'prediction': sum(values) / len(values)})\n",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "history_pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "predict.py", "predict.py")

    with sessionmaker(engine)() as db:
        project = Project(id="p_history_pipeline_run", name="History Pipeline Run")
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "history_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="history_pipeline",
            version=version,
            source_path=bundle_path,
            filename="history_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="history_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "history_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        input_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="history_prediction_input",
            filename="input.csv",
            text="item_id,as_of\nA,2026-01-04\n",
            metadata={"project_id": project.id},
        )
        history_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_history",
            name="history_rows",
            filename="history.csv",
            text="item_id,date,sales\nA,2026-01-01,10\nA,2026-01-02,13\nA,2026-01-03,16\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_history_predict",
            project_id=project.id,
            artifact_id=input_artifact.id,
            source_type="upload",
            source_ref="input.csv",
            row_count=1,
            column_count=2,
            schema_hash="history_predict_schema",
        )
        job = Job(
            id="job_history_predict",
            project_id=project.id,
            job_type="run_prediction_pipeline",
            input_json=dumps_json(
                {
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "dataset_snapshot_id": dataset.id,
                    "history_artifact_id": history_artifact.id,
                }
            ),
            status="running",
        )
        db.add_all([dataset, job])
        db.commit()

        output = run_prediction_pipeline_handler(db, job, store)
        db.commit()

        prediction_artifact = db.get(Artifact, output["prediction_batch_artifact_id"])
        assert prediction_artifact is not None
        assert artifact_primary_path(prediction_artifact).read_text(encoding="utf-8") == "item_id,prediction\nA,13.0\n"
        assert loads_json(prediction_artifact.metadata_json, {})["history_artifact_id"] == history_artifact.id


def test_pilot_outcome_scoring_worker_registers_report_and_notifies_session(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "pipeline_manifest.json").write_text(
        dumps_json(
            {
                "schema_version": "pipeline_manifest.v1",
                "output_contract": {
                    "id_columns": ["id"],
                    "prediction_column": "prediction",
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "pipeline_manifest.json", "pipeline_manifest.json")

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_pilot_score",
            name="Pilot Score",
            target_column="actual",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "score_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="score_pipeline",
            version=version,
            source_path=bundle_path,
            filename="score_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="score_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "score_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        prediction_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_batch",
            name="pilot_predictions",
            filename="predictions.csv",
            text="id,prediction\n1,10\n2,20\n",
            metadata={"project_id": project.id},
        )
        outcome_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_outcomes",
            name="pilot_outcomes",
            filename="outcomes.csv",
            text="id,actual,observed_at\n1,11,2026-07-07T00:00:00Z\n2,17,2026-07-05T00:00:00Z\n",
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_score",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        prediction_batch = PilotPredictionBatch(
            id="ppb_score",
            deployment_id=deployment.id,
            as_of=utc_now().replace(year=2026, month=7, day=6, hour=0, minute=0, second=0, microsecond=0),
            input_artifact_id=prediction_artifact.id,
            predictions_artifact_id=prediction_artifact.id,
            row_count=2,
        )
        outcome_batch = PilotOutcomeBatch(
            id="pout_score",
            deployment_id=deployment.id,
            outcomes_artifact_id=outcome_artifact.id,
            join_keys_json=dumps_json(["id"]),
        )
        workspace = tmp_path / "agent_workspace"
        session = AgentSession(
            id="as_pilot_score",
            project_id=project.id,
            goal_text="Continue from pilot observations.",
            workspace_path=str(workspace),
            status="between_turns",
        )
        job = Job(
            id="job_score",
            project_id=project.id,
            job_type="score_pilot_outcomes",
            input_json=dumps_json(
                {
                    "deployment_id": deployment.id,
                    "outcome_batch_id": outcome_batch.id,
                    "prediction_batch_id": prediction_batch.id,
                    "observed_at_column": "observed_at",
                }
            ),
            status="running",
        )
        db.add_all([deployment, prediction_batch, outcome_batch, session, job])
        db.commit()

        output = score_pilot_outcomes_handler(db, job, store)
        db.commit()

        report_artifact = db.get(Artifact, output["pilot_scoring_report_artifact_id"])
        assert report_artifact is not None
        report = loads_json(artifact_primary_path(report_artifact).read_text(encoding="utf-8"), {})
        assert report["schema_version"] == "pilot_scoring_report.v1"
        assert report["matched_rows"] == 2
        assert report["metric_count"] == 2
        assert report["metrics"]["mae"] == 2.0
        assert round(report["metrics"]["rmse"], 6) == round(5 ** 0.5, 6)
        assert report["as_of_violations"]["count"] == 1
        assert db.get(PilotOutcomeBatch, outcome_batch.id).matched_rows == 2
        assert output["notified_agent_session_id"] == session.id
        assert output["session_continuation_job_id"]
        continuation = db.get(Job, output["session_continuation_job_id"])
        assert continuation is not None
        assert continuation.job_type == "continue_autonomous_session"
        assert loads_json(continuation.input_json, {})["reason"] == "pilot_scoring_report_available"
        notices = [
            entry for entry in list_inbox_entries(workspace) if entry["kind"] == "observation" and entry["type"] == "pilot_observation_available"
        ]
        assert len(notices) == 1
        notice_payload = notices[0]["payload"]
        assert notice_payload["pilot_scoring_report_artifact_id"] == report_artifact.id
        report_workspace_path = workspace / notice_payload["pilot_scoring_report_workspace_path"]
        assert report_workspace_path.exists()
        workspace_report = loads_json(report_workspace_path.read_text(encoding="utf-8"), {})
        assert workspace_report["schema_version"] == "pilot_scoring_report.v1"
        assert workspace_report["metrics"]["mae"] == 2.0


def test_pilot_scoring_wakes_completed_full_auto_session(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "pipeline_manifest.json").write_text(
        dumps_json(
            {
                "schema_version": "pipeline_manifest.v1",
                "output_contract": {
                    "id_columns": ["id"],
                    "prediction_column": "prediction",
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "pipeline_manifest.json", "pipeline_manifest.json")

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_pilot_completed",
            name="Pilot Completed",
            target_column="actual",
            current_phase="IDLE",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "completed_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="completed_pipeline",
            version=version,
            source_path=bundle_path,
            filename="completed_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="completed_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "completed_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        prediction_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_batch",
            name="completed_predictions",
            filename="predictions.csv",
            text="id,prediction\n1,10\n",
            metadata={"project_id": project.id},
        )
        outcome_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_outcomes",
            name="completed_outcomes",
            filename="outcomes.csv",
            text="id,actual,observed_at\n1,12,2026-07-08T00:00:00Z\n",
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_completed",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        prediction_batch = PilotPredictionBatch(
            id="ppb_completed",
            deployment_id=deployment.id,
            as_of=utc_now().replace(year=2026, month=7, day=7, hour=0, minute=0, second=0, microsecond=0),
            input_artifact_id=prediction_artifact.id,
            predictions_artifact_id=prediction_artifact.id,
            row_count=1,
        )
        outcome_batch = PilotOutcomeBatch(
            id="pout_completed",
            deployment_id=deployment.id,
            outcomes_artifact_id=outcome_artifact.id,
            join_keys_json=dumps_json(["id"]),
        )
        workspace = tmp_path / "completed_workspace"
        session = AgentSession(
            id="ags_completed_pilot",
            project_id=project.id,
            session_type="main_autonomous",
            status="completed",
            autonomy_mode="full_auto",
            goal_text="Continue from pilot observations.",
            workspace_path=str(workspace),
            ended_at=utc_now(),
        )
        job = Job(
            id="job_completed_score",
            project_id=project.id,
            job_type="score_pilot_outcomes",
            input_json=dumps_json(
                {
                    "deployment_id": deployment.id,
                    "outcome_batch_id": outcome_batch.id,
                    "prediction_batch_id": prediction_batch.id,
                    "observed_at_column": "observed_at",
                }
            ),
            status="running",
        )
        db.add_all([deployment, prediction_batch, outcome_batch, session, job])
        db.commit()

        output = score_pilot_outcomes_handler(db, job, store)
        db.commit()

        assert output["notified_agent_session_id"] == session.id
        assert output["session_continuation_job_id"]
        assert db.get(Project, project.id).current_phase == "AUTONOMOUS_LOOP"
        continuation = db.get(Job, output["session_continuation_job_id"])
        assert continuation is not None
        assert continuation.job_type == "continue_autonomous_session"
        assert loads_json(continuation.input_json, {})["reason"] == "pilot_scoring_report_available"
        notices = [
            entry
            for entry in list_inbox_entries(workspace)
            if entry["kind"] == "observation" and entry["type"] == "pilot_observation_available"
        ]
        assert len(notices) == 1
        assert notices[0]["payload"]["pilot_scoring_report_artifact_id"] == output["pilot_scoring_report_artifact_id"]


def test_pilot_scoring_does_not_wake_stopped_session(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline_dir = tmp_path / "pipeline_src"
    pipeline_dir.mkdir()
    (pipeline_dir / "pipeline_manifest.json").write_text(
        dumps_json(
            {
                "schema_version": "pipeline_manifest.v1",
                "output_contract": {
                    "id_columns": ["id"],
                    "prediction_column": "prediction",
                },
            }
        ),
        encoding="utf-8",
    )
    bundle_path = tmp_path / "pipeline.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(pipeline_dir / "pipeline_manifest.json", "pipeline_manifest.json")

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_pilot_stopped",
            name="Pilot Stopped",
            target_column="actual",
            current_phase="IDLE",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        version = next_artifact_version(db, project.id, "prediction_pipeline", "stopped_pipeline")
        target_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="stopped_pipeline",
            version=version,
            source_path=bundle_path,
            filename="stopped_pipeline.zip",
            metadata={"project_id": project.id, "primary_path": str(bundle_path)},
        )
        pipeline_artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="stopped_pipeline",
            uri=str(target_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "primary_path": str(target_dir / "stopped_pipeline.zip")},
            version=version,
            org_id=project.org_id,
        )
        prediction_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_batch",
            name="stopped_predictions",
            filename="predictions.csv",
            text="id,prediction\n1,10\n",
            metadata={"project_id": project.id},
        )
        outcome_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_outcomes",
            name="stopped_outcomes",
            filename="outcomes.csv",
            text="id,actual\n1,12\n",
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_stopped",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        prediction_batch = PilotPredictionBatch(
            id="ppb_stopped",
            deployment_id=deployment.id,
            as_of=utc_now().replace(year=2026, month=7, day=7, hour=0, minute=0, second=0, microsecond=0),
            input_artifact_id=prediction_artifact.id,
            predictions_artifact_id=prediction_artifact.id,
            row_count=1,
        )
        outcome_batch = PilotOutcomeBatch(
            id="pout_stopped",
            deployment_id=deployment.id,
            outcomes_artifact_id=outcome_artifact.id,
            join_keys_json=dumps_json(["id"]),
        )
        workspace = tmp_path / "stopped_workspace"
        session = AgentSession(
            id="ags_stopped_pilot",
            project_id=project.id,
            session_type="main_autonomous",
            status="stopped",
            autonomy_mode="full_auto",
            goal_text="Stopped by user.",
            workspace_path=str(workspace),
            ended_at=utc_now(),
        )
        job = Job(
            id="job_stopped_score",
            project_id=project.id,
            job_type="score_pilot_outcomes",
            input_json=dumps_json(
                {
                    "deployment_id": deployment.id,
                    "outcome_batch_id": outcome_batch.id,
                    "prediction_batch_id": prediction_batch.id,
                }
            ),
            status="running",
        )
        db.add_all([deployment, prediction_batch, outcome_batch, session, job])
        db.commit()

        output = score_pilot_outcomes_handler(db, job, store)
        db.commit()

        assert output["notified_agent_session_id"] is None
        assert "session_continuation_job_id" not in output
        assert db.get(Project, project.id).current_phase == "IDLE"
        assert list_inbox_entries(workspace) == []


def test_pilot_validation_audit_request_registers_artifact_evidence_and_plan_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = pilot_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    with sessionmaker(engine)() as db:
        project = Project(id="p_pilot_audit", name="Pilot Audit")
        session = AgentSession(
            id="as_pilot_audit",
            project_id=project.id,
            goal_text="Register validation audit.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        pipeline_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="audit_pipeline",
            filename="pipeline.zip",
            text="placeholder",
            metadata={"project_id": project.id},
        )
        scoring_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_scoring_report",
            name="audit_scoring_report",
            filename="pilot_scoring_report.json",
            text='{"schema_version":"pilot_scoring_report.v1"}',
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_audit",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        db.add(deployment)
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "pilot_review",
                        "title": "Pilot review",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is reviewing pilot observations.",
            strict_validation=True,
        )
        db.commit()

        (request_dir / "audit.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_pilot_request.v1",
                    "operation": "register_validation_audit",
                    "request_id": "audit_001",
                    "payload": {
                        "deployment_id": deployment.id,
                        "scoring_report_artifact_ids": [scoring_artifact.id],
                        "scheme_verdict": "partially_confirmed",
                        "gap_decomposition": [
                            {
                                "component": "covariate_shift",
                                "evidence": "Structured pilot scoring report indicates a distribution mismatch.",
                                "magnitude": "medium",
                                "confidence": "medium",
                            }
                        ],
                        "hypotheses": [
                            {
                                "id": "h1",
                                "statement": "Pilot rows may differ from validation rows.",
                                "test_plan": "Compare feature distributions.",
                                "expected_evidence": "Feature drift report.",
                            }
                        ],
                        "next_iteration_focus": "Compare pilot and validation feature distributions.",
                        "research_plan_node_id": "pilot_review",
                    },
                }
            ),
            encoding="utf-8",
        )
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((pilot_acks_dir(workspace) / "audit.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        artifact = db.get(Artifact, ack["result"]["artifact_id"])
        assert artifact is not None
        assert artifact.asset_type == "validation_scheme_audit"
        evidence = db.get(Evidence, ack["result"]["evidence_id"])
        assert evidence is not None
        assert evidence.evidence_type == "validation_scheme_audit"
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.to_asset_id == artifact.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
        )
        assert edge is not None
        assert loads_json(edge.metadata_json, {})["node_id"] == "pilot_review"

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "pilot_review",
                        "title": "Pilot review",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["pilot_scoring", "validation_audit"]},
                        "completion_evidence": [
                            {"output_type": "pilot_scoring", "artifact_id": scoring_artifact.id},
                            {"output_type": "validation_audit", "artifact_id": artifact.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered pilot scoring evidence and validation audit.",
            strict_validation=True,
        )
        db.commit()
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert timeline["contract_validation"]["status"] == "ok"


def test_pilot_observation_followup_can_commit_audited_next_iteration_plan(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    pilot_request_dir = pilot_requests_dir(workspace)
    plan_request_dir = research_plan_requests_dir(workspace)
    pilot_request_dir.mkdir(parents=True)
    plan_request_dir.mkdir(parents=True)

    with sessionmaker(engine)() as db:
        project = Project(id="p_pilot_followup", name="Pilot Followup")
        session = AgentSession(
            id="as_pilot_followup",
            project_id=project.id,
            goal_text="Continue from pilot observation.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        pipeline_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="followup_pipeline",
            filename="pipeline.zip",
            text="placeholder",
            metadata={"project_id": project.id},
        )
        scoring_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_scoring_report",
            name="followup_scoring_report",
            filename="pilot_scoring_report.json",
            text=dumps_json({"schema_version": "pilot_scoring_report.v1", "metrics": {"mae": 2.5}}),
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_followup",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        db.add(deployment)
        db.commit()

        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "pilot_review",
                        "title": "Pilot review",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "next_iteration",
                        "title": "Next iteration",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Codex is reviewing pilot observations.",
            strict_validation=True,
        )
        db.commit()

        (pilot_request_dir / "audit.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_pilot_request.v1",
                    "operation": "register_validation_audit",
                    "request_id": "audit_followup",
                    "payload": {
                        "deployment_id": deployment.id,
                        "scoring_report_artifact_ids": [scoring_artifact.id],
                        "scheme_verdict": "partially_confirmed",
                        "gap_decomposition": [
                            {
                                "component": "temporal_drift",
                                "evidence": "Pilot score moved after deployment.",
                                "magnitude": "medium",
                                "confidence": "medium",
                            }
                        ],
                        "hypotheses": [
                            {
                                "id": "pilot_shift",
                                "statement": "The pilot period differs from validation.",
                                "test_plan": "Compare validation and pilot feature distributions.",
                                "expected_evidence": "Drift notebook and updated split review.",
                            }
                        ],
                        "next_iteration_focus": "Revisit split and drift diagnostics before model updates.",
                        "research_plan_node_id": "pilot_review",
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        audit_ack = loads_json((pilot_acks_dir(workspace) / "audit.ack.json").read_text(encoding="utf-8"), {})
        assert audit_ack["status"] == "succeeded"
        audit_artifact_id = audit_ack["result"]["artifact_id"]

        (plan_request_dir / "next_iteration.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_research_plan_request.v1",
                    "operation": "commit_revision",
                    "request_id": "plan_followup",
                    "payload": {
                        "reason": "Pilot audit registered; continue with a drift-focused next iteration.",
                        "document": {
                            "schema_version": "research_plan.v2",
                            "timeline_blocks": [
                                {
                                    "id": "pilot_review",
                                    "title": "Pilot review",
                                    "granularity": "chapter",
                                    "status": "done",
                                    "deliverable_contract": {
                                        "expected_outputs": ["pilot_scoring", "validation_audit"]
                                    },
                                    "completion_evidence": [
                                        {"output_type": "pilot_scoring", "artifact_id": scoring_artifact.id},
                                        {"output_type": "validation_audit", "artifact_id": audit_artifact_id},
                                    ],
                                },
                                {
                                    "id": "next_iteration",
                                    "title": "Next iteration",
                                    "granularity": "chapter",
                                    "status": "active",
                                    "deliverable_contract": {
                                        "expected_outputs": ["notebook", "leaderboard_entry"]
                                    },
                                },
                            ],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        (plan_request_dir / "current_work.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_research_plan_request.v1",
                    "operation": "set_current_work",
                    "request_id": "current_work_followup",
                    "payload": {
                        "node_id": "next_iteration",
                        "summary": "Inspect pilot drift before revising the model.",
                        "expected_outputs": ["notebook", "leaderboard_entry"],
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        plan_ack = loads_json((research_plan_acks_dir(workspace) / "next_iteration.ack.json").read_text(encoding="utf-8"), {})
        current_ack = loads_json((research_plan_acks_dir(workspace) / "current_work.ack.json").read_text(encoding="utf-8"), {})
        assert plan_ack["status"] == "succeeded"
        assert current_ack["status"] == "succeeded"

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        blocks = {block["id"]: block for block in timeline["blocks"]}
        assert timeline["contract_validation"]["status"] == "ok"
        assert blocks["pilot_review"]["status"] == "done"
        assert blocks["next_iteration"]["status"] == "active"
        assert timeline["current_work"]["node_id"] == "next_iteration"
        assert timeline["current_work"]["expected_outputs"] == ["notebook", "leaderboard_entry"]
        assert any(link["artifact_id"] == audit_artifact_id for link in timeline["artifact_links"])


def test_pilot_validation_audit_request_rejects_invalid_component(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = pilot_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    with sessionmaker(engine)() as db:
        project = Project(id="p_pilot_bad_audit", name="Pilot Bad Audit")
        session = AgentSession(
            id="as_pilot_bad_audit",
            project_id=project.id,
            goal_text="Reject invalid validation audit.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        pipeline_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_pipeline",
            name="bad_audit_pipeline",
            filename="pipeline.zip",
            text="placeholder",
            metadata={"project_id": project.id},
        )
        scoring_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_scoring_report",
            name="bad_audit_scoring_report",
            filename="pilot_scoring_report.json",
            text='{"schema_version":"pilot_scoring_report.v1"}',
            metadata={"project_id": project.id},
        )
        deployment = PilotDeployment(
            id="pdep_bad_audit",
            project_id=project.id,
            pipeline_artifact_id=pipeline_artifact.id,
            status="active",
        )
        db.add(deployment)
        db.commit()
        (request_dir / "bad_audit.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_pilot_request.v1",
                    "operation": "register_validation_audit",
                    "request_id": "bad_audit_001",
                    "payload": {
                        "deployment_id": deployment.id,
                        "scoring_report_artifact_ids": [scoring_artifact.id],
                        "scheme_verdict": "confirmed",
                        "gap_decomposition": [{"component": "made_up"}],
                        "next_iteration_focus": "Continue.",
                    },
                }
            ),
            encoding="utf-8",
        )
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((pilot_acks_dir(workspace) / "bad_audit.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "component" in ack["error"]["message"]
        rejection = pilot_request_rejection_path(workspace)
        assert rejection.exists()
        rejection_text = rejection.read_text(encoding="utf-8")
        assert "tablex_pilot_request_rejection.v1" in rejection_text
        assert "bad_audit_001" in rejection_text
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "pilot_request_failed",
            )
        )
        assert event is not None
        chat_turn = db.scalar(
            select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
            )
        )
        assert chat_turn is not None
        chat_payload = loads_json(artifact_primary_path(chat_turn).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "pilot_request_failed"


def test_experiment_result_request_rejects_run_without_human_summary(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "missing_summary.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "missing_summary",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "opaque_model",
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_missing_exp_summary", name="Missing Experiment Summary")
        session = AgentSession(
            id="as_missing_exp_summary",
            project_id=project.id,
            goal_text="Reject opaque model rows.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "missing_summary.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "model_description is required" in ack["error"]["message"]
        assert db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id)) == 0


def test_experiment_result_request_rejects_mixed_primary_metrics(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "mixed_metrics.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "mixed_metrics",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "regression_candidate",
                            "model_description": "Regression candidate for comparable metric validation.",
                            "features_used": ["regression_features"],
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0, "rmse": 60.0},
                        },
                        {
                            "model_id": "classification_candidate",
                            "model_description": "Classification candidate for comparable metric validation.",
                            "features_used": ["classification_features"],
                            "primary_metric_name": "roc_auc",
                            "metrics": {"roc_auc": 0.82, "accuracy": 0.74},
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_mixed_exp_metrics", name="Mixed Experiment Metrics")
        session = AgentSession(
            id="as_mixed_exp_metrics",
            project_id=project.id,
            goal_text="Reject incomparable leaderboard rows.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "mixed_metrics.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "same primary_metric_name" in ack["error"]["message"]
        assert db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id)) == 0


def test_experiment_result_request_rejects_unknown_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "unknown_plan_node.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "unknown_plan_node",
                "operation": "register_runs",
                "payload": {
                    "research_plan_node_id": "missing_modeling_node",
                    "evaluation_spec_id": "eval_local_label",
                    "split_manifest_id": "split_local_label",
                    "runs": [
                        {
                            "model_id": "glm_baseline",
                            "model_description": "A GLM baseline linked to a missing plan node.",
                            "features_used": ["numeric_profile"],
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_unknown_plan_node", name="Unknown Plan Node")
        session = AgentSession(
            id="as_unknown_plan_node",
            project_id=project.id,
            goal_text="Reject result links to unknown plan nodes.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare modeling work.",
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "unknown_plan_node.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "missing_modeling_node" in ack["error"]["message"]
        assert "not present in the active revision" in ack["error"]["message"]
        assert (
            db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
            == 0
        )


def test_experiment_result_request_rejects_missing_research_plan_node_when_plan_exists(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "missing_plan_node.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "missing_plan_node",
                "operation": "register_runs",
                "payload": {
                    "runs": [
                        {
                            "model_id": "glm_baseline",
                            "model_description": "A GLM baseline without a declared plan node.",
                            "features_used": ["numeric_profile"],
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 42.0},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_missing_plan_node", name="Missing Plan Node")
        session = AgentSession(
            id="as_missing_plan_node",
            project_id=project.id,
            goal_text="Reject result links without plan nodes.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "modeling_and_diagnostics",
                        "title": "Modeling and diagnostics",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Current work is still data understanding.",
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "missing_plan_node.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "research_plan_node_id" in ack["error"]["message"]
        assert "when a ResearchPlan exists" in ack["error"]["message"]
        assert (
            db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
            == 0
        )


def test_experiment_result_request_rejects_pending_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = experiment_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "pending_plan_node.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_experiment_result_request.v1",
                "request_id": "pending_plan_node",
                "operation": "register_runs",
                "payload": {
                    "research_plan_node_id": "evaluation_modeling",
                    "runs": [
                        {
                            "model_id": "ridge_candidate",
                            "model_description": "A fold-safe ridge candidate.",
                            "features_used": ["numeric", "categorical"],
                            "primary_metric_name": "mae",
                            "metrics": {"mae": 12.0, "rmse": 18.0},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_pending_plan_node", name="Pending Plan Node")
        session = AgentSession(
            id="as_pending_plan_node",
            project_id=project.id,
            goal_text="Reject output links to a future plan node.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "evaluation_modeling",
                        "title": "Evaluation and modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Current work is still data understanding.",
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((experiment_acks_dir(workspace) / "pending_plan_node.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        assert "evaluation_modeling" in ack["error"]["message"]
        assert "still pending" in ack["error"]["message"]
        assert (
            db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id))
            == 0
        )


def test_research_plan_tool_rejects_later_done_node_before_open_predecessor(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "bad_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "bad_plan",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "pending",
                            },
                            {
                                "id": "modeling",
                                "title": "Modeling",
                                "granularity": "chapter",
                                "status": "done",
                            },
                        ],
                    },
                    "reason": "This should be rejected because the visible order is inconsistent.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_bad_plan", name="Bad Plan")
        session = AgentSession(
            id="as_bad_plan",
            project_id=project.id,
            goal_text="Reject invalid plan updates.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_plan_acks_dir(workspace) / "bad_plan.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        issue_codes = {issue["code"] for issue in ack["error"]["issues"]}
        assert "completed_after_open_predecessor" in issue_codes
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0


def test_research_plan_tool_rejects_done_node_without_deliverable_contract(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "missing_contract.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "missing_contract",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "done",
                                "completion_evidence": [
                                    {"output_type": "notebook", "workspace_path": "notebooks/data_understanding.py"}
                                ],
                            }
                        ],
                    },
                    "reason": "This should be rejected because output-producing done nodes need a contract.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_missing_contract", name="Missing Contract")
        session = AgentSession(
            id="as_missing_contract",
            project_id=project.id,
            goal_text="Reject missing deliverable contracts.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_plan_acks_dir(workspace) / "missing_contract.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        issue_codes = {issue["code"] for issue in ack["error"]["issues"]}
        assert "done_node_missing_deliverable_contract" in issue_codes
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0


def test_research_plan_tool_rejects_blank_current_work_summary(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "plan.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "plan",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "active",
                            }
                        ],
                    },
                    "reason": "Create an active node.",
                },
            }
        ),
        encoding="utf-8",
    )
    (request_dir / "blank_current_work.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "blank_current_work",
                "operation": "set_current_work",
                "payload": {
                    "node_id": "data_understanding",
                    "summary": "   ",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_blank_current_work", name="Blank Current Work")
        session = AgentSession(
            id="as_blank_current_work",
            project_id=project.id,
            goal_text="Reject blank current work summaries.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        plan_ack = loads_json((research_plan_acks_dir(workspace) / "plan.ack.json").read_text(encoding="utf-8"), {})
        current_ack = loads_json(
            (research_plan_acks_dir(workspace) / "blank_current_work.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert plan_ack["status"] == "succeeded"
        assert current_ack["status"] == "failed"
        assert "current_work.summary is required" in current_ack["error"]["message"]
        assert latest_research_plan_current_work(db, project_id=project.id) is None


def test_strict_research_plan_rejects_done_notebook_without_registered_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_missing_notebook_asset", name="Missing Notebook Asset")
        db.add(project)
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "data_understanding",
                            "title": "Data understanding",
                            "granularity": "chapter",
                            "status": "done",
                            "deliverable_contract": {"expected_outputs": ["notebook"]},
                            "completion_evidence": [
                                {"output_type": "notebook", "workspace_path": "notebooks/data_understanding.py"}
                            ],
                        }
                    ],
                },
                author_type="codex",
                reason="This should be rejected because the notebook is not registered.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            issue_codes = {issue["code"] for issue in exc.issues}
            assert "done_node_missing_registered_deliverables" in issue_codes
        else:
            raise AssertionError("Expected ResearchPlanValidationError")


def test_strict_research_plan_accepts_done_notebook_with_registered_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_registered_notebook_asset", name="Registered Notebook Asset")
        db.add(project)
        db.commit()
        notebook_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="registered_eda_notebook",
            filename="data_understanding.py",
            text="import marimo\n\napp = marimo.App()\n",
            metadata={"workspace_relative_path": "notebooks/data_understanding.py"},
        )
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "artifact_id": notebook_artifact.id},
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered notebook evidence should satisfy the contract.",
            strict_validation=True,
        )

        assert result.created is True
        assert result.revision.project_id == project.id


def test_strict_research_plan_rejects_leaderboard_without_registered_run(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_missing_leaderboard_run", name="Missing Leaderboard Run")
        db.add(project)
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "modeling",
                            "title": "Modeling",
                            "granularity": "chapter",
                            "status": "done",
                            "deliverable_contract": {"expected_outputs": ["leaderboard_entry"]},
                            "completion_evidence": [
                                {"output_type": "leaderboard_entry", "experiment_run_id": "run_missing"}
                            ],
                        }
                    ],
                },
                author_type="codex",
                reason="This should be rejected because no registered ExperimentRun exists.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            issue_codes = {issue["code"] for issue in exc.issues}
            assert "done_node_missing_registered_deliverables" in issue_codes
        else:
            raise AssertionError("Expected ResearchPlanValidationError")


def test_strict_research_plan_rejects_leaderboard_when_only_experiment_run_is_declared(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_leaderboard_requires_explicit_claim", name="Leaderboard Requires Explicit Claim")
        run = ExperimentRun(
            id="run_leaderboard_requires_explicit_claim",
            project_id=project.id,
            runner_type="codex_cli",
            status="succeeded",
            params_json=dumps_json({"model_id": "median_baseline"}),
            metrics_json=dumps_json({"mae": 1.0, "primary_metric_name": "mae", "primary_metric_value": 1.0}),
        )
        db.add_all([project, run])
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "modeling",
                            "title": "Modeling",
                            "granularity": "chapter",
                            "status": "done",
                            "deliverable_contract": {"expected_outputs": ["leaderboard_entry"]},
                            "completion_evidence": [
                                {"output_type": "experiment_run", "experiment_run_id": run.id}
                            ],
                        }
                    ],
                },
                author_type="codex",
                reason="A run is not the same thing as an explicitly reported leaderboard entry.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            issue_codes = {issue["code"] for issue in exc.issues}
            assert "done_node_missing_contract_deliverables" in issue_codes
        else:
            raise AssertionError("Expected ResearchPlanValidationError")


def test_strict_research_plan_rejects_leaderboard_for_non_succeeded_run(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_leaderboard_requires_success", name="Leaderboard Requires Success")
        run = ExperimentRun(
            id="run_leaderboard_requires_success",
            project_id=project.id,
            runner_type="codex_cli",
            status="failed",
            params_json=dumps_json({"model_id": "median_baseline"}),
            metrics_json=dumps_json({"mae": 1.0, "primary_metric_name": "mae", "primary_metric_value": 1.0}),
        )
        db.add_all([project, run])
        db.commit()

        try:
            commit_research_plan_revision(
                db,
                project_id=project.id,
                document={
                    "schema_version": "research_plan.v2",
                    "timeline_blocks": [
                        {
                            "id": "modeling",
                            "title": "Modeling",
                            "granularity": "chapter",
                            "status": "done",
                            "deliverable_contract": {"expected_outputs": ["leaderboard_entry"]},
                            "completion_evidence": [
                                {"output_type": "leaderboard_entry", "experiment_run_id": run.id}
                            ],
                        }
                    ],
                },
                author_type="codex",
                reason="A leaderboard row requires a succeeded registered run.",
                strict_validation=True,
            )
        except ResearchPlanValidationError as exc:
            issue_codes = {issue["code"] for issue in exc.issues}
            assert "done_node_missing_registered_deliverables" in issue_codes
        else:
            raise AssertionError("Expected ResearchPlanValidationError")


def test_strict_research_plan_accepts_leaderboard_with_registered_run(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_registered_leaderboard_run", name="Registered Leaderboard Run")
        run = ExperimentRun(
            id="run_registered_leaderboard",
            project_id=project.id,
            runner_type="codex_cli",
            status="succeeded",
            params_json=dumps_json({"model_id": "median_baseline"}),
            metrics_json=dumps_json({"mae": 1.0, "primary_metric_name": "mae", "primary_metric_value": 1.0}),
        )
        db.add_all([project, run])
        db.commit()

        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["experiment_run", "leaderboard_entry"]},
                        "completion_evidence": [
                            {"output_type": "leaderboard_entry", "experiment_run_id": run.id}
                        ],
                    }
                ],
            },
            author_type="codex",
            reason="Registered run evidence should satisfy the leaderboard contract.",
            strict_validation=True,
        )

        assert result.created is True
        assert result.revision.project_id == project.id


def test_research_plan_tool_rejects_open_plan_without_current_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "no_current.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "no_current",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "done",
                                "no_output_required": True,
                                "no_output_required_rationale": "No durable output is needed for this synthetic test.",
                            },
                            {
                                "id": "modeling",
                                "title": "Modeling",
                                "granularity": "chapter",
                                "status": "pending",
                            },
                        ],
                    },
                    "reason": "This should be rejected because open work has no current node.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_no_current_plan", name="No Current Plan")
        session = AgentSession(
            id="as_no_current_plan",
            project_id=project.id,
            goal_text="Reject missing current work.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_plan_acks_dir(workspace) / "no_current.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        issue_codes = {issue["code"] for issue in ack["error"]["issues"]}
        assert "missing_current_node" in issue_codes
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0


def test_research_plan_timeline_derives_current_work_from_active_revision_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_derived_current_work", name="Derived Current Work")
        db.add(project)
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "subtitle": "Codex is inspecting row semantics and leakage-sensitive fields.",
                        "granularity": "chapter",
                        "status": "active",
                        "deliverable_contract": {"expected_outputs": ["notebook"]},
                    }
                ],
            },
            author_type="codex",
            reason="Codex declared the current ResearchPlan node.",
            strict_validation=True,
        )
        db.commit()

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert timeline["current_work"]["node_id"] == "data_understanding"
        assert timeline["current_work"]["status"] == "active"
        assert timeline["current_work"]["source"] == "research_plan_revision_status"
        assert timeline["current_work"]["expected_outputs"] == ["notebook"]


def test_research_plan_timeline_prefers_active_revision_node_over_stale_current_work(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_stale_current_work", name="Stale Current Work")
        db.add(project)
        first = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Start with data understanding.",
            strict_validation=True,
        )
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="data_understanding",
            summary="Working on data understanding.",
            status="active",
            revision_id=first.revision.id,
        )
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "Synthetic test data understanding is complete.",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "subtitle": "Codex is comparing model candidates.",
                        "granularity": "chapter",
                        "status": "active",
                    },
                ],
            },
            author_type="codex",
            reason="Move to modeling.",
            strict_validation=True,
        )
        db.commit()

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        assert timeline["current_work"]["node_id"] == "modeling"
        assert timeline["current_work"]["status"] == "active"
        assert timeline["current_work"]["source"] == "research_plan_revision_status"


def test_structured_model_results_ignore_stale_current_work_when_revision_moved_on(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    artifacts_dir = workspace / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "model_results.json").write_text(
        dumps_json(
            {
                "schema_version": "model_results.v1",
                "research_plan_node_id": "modeling",
                "models": [
                    {
                        "model_id": "active_node_tree",
                        "summary": "A model result emitted after the plan moved to modeling.",
                        "primary_metric_name": "mae",
                        "mae": 31.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_stale_run_current_work", name="Stale Run Current Work")
        session = AgentSession(
            id="as_stale_run_current_work",
            project_id=project.id,
            goal_text="Register model results after the plan advances.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        first = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Start data understanding.",
            strict_validation=True,
        )
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="data_understanding",
            summary="Old current work record.",
            revision_id=first.revision.id,
        )
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "done",
                        "no_output_required": True,
                        "no_output_required_rationale": "The test moved past data understanding.",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "active",
                    },
                ],
            },
            author_type="codex",
            reason="Move to modeling.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == project.id))
        assert run is not None
        params = loads_json(run.params_json, {})
        assert params["research_plan_node_id"] == "modeling"
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        modeling_links = timeline["blocks"][1]["attached_artifacts"]
        assert any(link["link_type"] == "experiment_run" and link["run_id"] == run.id for link in modeling_links)


def test_research_plan_tool_rejects_fine_grained_top_level_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    (request_dir / "fine_grained.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "fine_grained",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "try_one_model",
                                "title": "Try one model",
                                "granularity": "experiment",
                                "status": "active",
                            },
                        ],
                    },
                    "reason": "This should be rejected because the top-level plan is too fine.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_fine_plan", name="Fine Plan")
        session = AgentSession(
            id="as_fine_plan",
            project_id=project.id,
            goal_text="Reject fine top-level work.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json((research_plan_acks_dir(workspace) / "fine_grained.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "failed"
        issue_codes = {issue["code"] for issue in ack["error"]["issues"]}
        assert "top_level_node_granularity_too_fine" in issue_codes
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0


def test_research_plan_tool_rejects_overly_granular_top_level_plan(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    request_dir = research_plan_requests_dir(workspace)
    request_dir.mkdir(parents=True)
    timeline_blocks = [
        {
            "id": f"chapter_{index}",
            "title": f"Chapter {index}",
            "granularity": "chapter",
            "status": "done",
            "no_output_required": True,
            "no_output_required_rationale": "Synthetic completed chapter for plan-size validation.",
        }
        for index in range(1, 8)
    ]
    timeline_blocks.append(
        {
            "id": "chapter_8",
            "title": "Chapter 8",
            "granularity": "chapter",
            "status": "active",
        }
    )
    (request_dir / "too_many_top_level.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "too_many_top_level",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": timeline_blocks,
                    },
                    "reason": "This should be rejected because detailed work belongs below chapter nodes.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_many_plan", name="Many Plan")
        session = AgentSession(
            id="as_many_plan",
            project_id=project.id,
            goal_text="Reject overly granular top-level plans.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json(
            (research_plan_acks_dir(workspace) / "too_many_top_level.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        issue_codes = {issue["code"] for issue in ack["error"]["issues"]}
        assert "top_level_plan_too_granular" in issue_codes
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0


def test_codex_authored_marimo_notebook_is_auto_registered_on_workspace_ingest(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "grandmaster_eda.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )
    with session_factory() as db:
        project = Project(id="p_notebook_registration", name="Notebook Registration")
        session = AgentSession(
            id="as_notebook_registration",
            project_id=project.id,
            goal_text="Write a readable marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        revision = commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "why_it_matters": "Use the notebook as the readable analysis evidence.",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Declare current notebook work.",
        ).revision
        set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id="data_understanding",
            summary="Writing a readable analysis notebook.",
            expected_outputs=["marimo notebook"],
            revision_id=revision.id,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_type == "notebook_registered",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["notebook_artifact_id"] == notebook_artifact.id
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "notebook_artifact_update"
        assert chat_payload["intent"]["status"] == "quality_needs_attention"
        assert chat_payload["actions"][0]["type"] == "open_artifact"
        assert chat_payload["actions"][0]["target_tab"] == "Notebooks"
        assert chat_payload["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert notebook_artifact.id in chat_payload["actions"][0]["artifact_ids"]
        assert any(action["target_tab"] == "Assets" for action in chat_payload["actions"])
        assert chat_payload["response_brief"]["research_plan_node_id"] == "data_understanding"
        assert chat_payload["visible_surfaces"]["notebooks"]["artifact_id"] == notebook_artifact.id
        assert chat_payload["visible_surfaces"]["assets"]["target_anchor"] == "asset-notebooks"
        assert chat_payload["visible_surfaces"]["research_plan"]["node_id"] == "data_understanding"
        assert chat_payload["visible_surfaces"]["chat"]["artifact_id"] == chat_artifact.id
        assert chat_payload["next_focus"]["target_tab"] == "Notebooks"
        assert chat_payload["next_focus"]["target_anchor"] == "notebook-native-marimo-top"
        assert chat_payload["next_focus"]["artifact_id"] == notebook_artifact.id
        assert chat_payload["next_focus"]["artifact_ids"] == [notebook_artifact.id]
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_id == notebook_artifact.id,
            )
        )
        assert edge is not None
        edge_metadata = loads_json(edge.metadata_json, {})
        assert edge_metadata["node_id"] == "data_understanding"
        assert edge_metadata["role"] == "notebook_source"


def test_existing_notebook_registration_event_backfills_agent_chat_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_backfill", name="Notebook Backfill")
        session = AgentSession(
            id="as_notebook_backfill",
            project_id=project.id,
            goal_text="Keep notebooks visible.",
        )
        db.add_all([project, session])
        db.flush()
        notebook_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="agent_notebook",
            filename="notebook.py",
            text="import marimo\napp = marimo.App()\n",
            metadata={
                "project_id": project.id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
            },
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="notebook_registered",
            role="harness",
            title="Notebook registered",
            content="Registered earlier.",
            payload={
                "notebook_artifact_id": notebook_artifact.id,
            },
            artifact_id=notebook_artifact.id,
        )
        db.commit()

        register_agent_session_notebook_source_output(db, store=store, session=session, artifact=notebook_artifact)
        db.commit()

        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "notebook_artifact_update"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert chat_payload["actions"][0]["target_tab"] == "Notebooks"


def test_codex_authored_marimo_notebook_registration_can_defer_until_final_ingest(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "grandmaster_eda.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_deferred_notebook", name="Deferred Notebook Registration")
        session = AgentSession(
            id="as_deferred_notebook",
            project_id=project.id,
            goal_text="Write a readable marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        deferred_event = db.scalar(
                select(AgentTranscriptEvent).where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_type == "notebook_registered_deferred",
                )
            )
        assert deferred_event is not None

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        success_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "notebook_registered",
            )
        )
        assert success_event is not None


def test_notebook_file_request_registers_source_ack_chat_and_plan_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    notebook = notebooks_dir / "data_understanding.py"
    notebook.write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    (requests_dir / "register_data_understanding.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_data_understanding",
                "operation": "register_notebook",
                "payload": {
                    "workspace_path": "notebooks/data_understanding.py",
                    "research_plan_node_id": "data_understanding",
                    "notebook_kind": "data_understanding",
                    "quality_manifest": ready_notebook_quality_manifest(),
                },
            }
        ),
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_request", name="Notebook Request")
        session = AgentSession(
            id="as_notebook_request",
            project_id=project.id,
            goal_text="Write and register a data understanding notebook.",
            workspace_path=str(workspace),
        )
        expectation = DeliverableExpectation(
            id="deliv_data_notebook",
            project_id=project.id,
            kind="data_understanding_notebook",
            subject_ref=f"project:{project.id}",
            status="open",
            created_from="test",
        )
        db.add_all([project, session, expectation])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                        "why_it_matters": "The notebook is the readable analysis output.",
                    }
                ],
            },
            author_type="codex",
            reason="Prepare node for notebook request.",
        )
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_data_understanding.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["schema_version"] == "tablex_notebook_ack.v1"
        assert ack["status"] == "succeeded"
        assert ack["result"]["notebook_artifact_id"] == notebook_artifact.id
        assert ack["result"]["research_plan_node_id"] == "data_understanding"
        assert ack["result"]["chat_artifact_id"]
        assert ack["result"]["visible_surfaces"]["notebooks"]["target_tab"] == "Notebooks"
        assert ack["result"]["visible_surfaces"]["notebooks"]["target_anchor"] == "notebook-native-marimo-top"
        assert ack["result"]["visible_surfaces"]["notebooks"]["artifact_id"] == notebook_artifact.id
        assert ack["result"]["visible_surfaces"]["assets"]["target_tab"] == "Assets"
        assert ack["result"]["visible_surfaces"]["assets"]["target_anchor"] == "asset-notebooks"
        assert ack["result"]["visible_surfaces"]["assets"]["artifact_id"] == notebook_artifact.id
        assert ack["result"]["visible_surfaces"]["research_plan"]["node_id"] == "data_understanding"
        assert ack["result"]["visible_surfaces"]["chat"]["artifact_id"] == ack["result"]["chat_artifact_id"]
        assert ack["result"]["notebook_quality"]["status"] == "manifest_provided"
        assert ack["result"]["notebook_quality"]["schema_version"] == "tablex_notebook_quality_manifest.v1"
        db.refresh(expectation)
        assert expectation.status == "fulfilled"
        assert expectation.fulfilled_by_artifact_id == notebook_artifact.id
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        assert ack["result"]["chat_artifact_id"] == chat_artifact.id
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "notebook_artifact_update"
        assert chat_payload["intent"]["status"] == "source_saved"
        assert chat_payload["actions"][0]["target_tab"] == "Notebooks"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert chat_payload["next_focus"]["artifact_id"] == notebook_artifact.id
        assert chat_payload["next_focus"]["artifact_ids"] == [notebook_artifact.id]
        assert chat_payload["response_brief"]["research_plan_node_id"] == "data_understanding"
        assert chat_payload["response_brief"]["notebook_quality"]["status"] == "manifest_provided"
        source_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_id == notebook_artifact.id,
            )
        )
        assert source_edge is not None
        edge_metadata = loads_json(source_edge.metadata_json, {})
        assert edge_metadata["node_id"] == "data_understanding"
        assert edge_metadata["role"] == "notebook_source"


def test_notebook_file_request_accepts_explicit_top_level_payload_and_read_order_labels(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "salary_eda_report.py").write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    (requests_dir / "register_salary_eda_report.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_salary_eda_report",
                "operation": "register_notebook",
                "workspace_path": "notebooks/salary_eda_report.py",
                "notebook_kind": "data_understanding",
                "quality_manifest": {
                    "schema_version": "tablex_notebook_quality_manifest.v1",
                    "figure_count": 5,
                    "table_count": 1,
                    "key_findings": ["Visual EDA is available for the uploaded table."],
                    "read_order": ["Dataset summary", "Visual diagnostics", "Next assumptions"],
                    "data_sources_used": [".tablex/data/train.csv"],
                    "limitations": ["The target framing is still provisional."],
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_top_level_request", name="Notebook Top Level Request")
        session = AgentSession(
            id="as_notebook_top_level_request",
            project_id=project.id,
            goal_text="Register a data understanding notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_salary_eda_report.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "succeeded"
        assert ack["result"]["compatibility_warnings"]
        assert any(
            warning["field"] == "quality_manifest.read_order[0]"
            for warning in ack["result"]["compatibility_warnings"]
        )
        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        notebook_metadata = loads_json(notebook_artifact.metadata_json, {})
        manifest = notebook_metadata["notebook_quality_manifest"]
        assert manifest["read_order"][0]["label"] == "Dataset summary"
        assert notebook_metadata["notebook_quality_status"] == "manifest_provided"


def test_notebook_file_request_rejects_zero_figure_manifest(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "data_understanding.py").write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_zero_figure_notebook", name="Zero Figure Notebook")
        session = AgentSession(
            id="as_zero_figure_notebook",
            project_id=project.id,
            goal_text="Register notebook quality.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        (requests_dir / "register_zero_figures.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_notebook_request.v1",
                    "request_id": "register_zero_figures",
                    "operation": "register_notebook",
                    "payload": {
                        "workspace_path": "notebooks/data_understanding.py",
                        "notebook_kind": "data_understanding",
                        "quality_manifest": {
                            "schema_version": "tablex_notebook_quality_manifest.v1",
                            "figure_count": 0,
                            "table_count": 2,
                            "key_findings": ["Salary units are mixed."],
                            "read_order": [{"label": "Overview"}],
                            "data_sources_used": ["train.csv"],
                            "limitations": ["Target framing is provisional."],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_zero_figures.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert "zero figures" in ack["error"]["message"]
        rejection_text = notebook_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "register_zero_figures" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "notebook_request_failed"


def test_notebook_file_request_rejects_runtime_broken_marimo_source(tmp_path: Path, monkeypatch: Any) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "data_understanding.py").write_text(
        RUNTIME_ERROR_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    (requests_dir / "register_runtime_broken.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_runtime_broken",
                "operation": "register_notebook",
                "payload": {
                    "workspace_path": "notebooks/data_understanding.py",
                    "notebook_kind": "data_understanding",
                    "quality_manifest": ready_notebook_quality_manifest(),
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_runtime_preflight(artifact: Artifact, *, timeout_seconds: int = 60) -> dict[str, Any]:
        return {
            "schema_version": "marimo_notebook_runtime_preflight.v1",
            "ok": False,
            "error_type": "RuntimeError",
            "error_summary": "KeyError: 'missing_column'",
            "return_code": 1,
        }

    monkeypatch.setattr(
        agent_notebook_quality_module,
        "marimo_notebook_runtime_preflight_for_artifact",
        fake_runtime_preflight,
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_runtime_broken_notebook", name="Runtime Broken Notebook")
        session = AgentSession(
            id="as_runtime_broken_notebook",
            project_id=project.id,
            goal_text="Register a runtime-valid notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_runtime_broken.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert "native marimo runtime preflight" in ack["error"]["message"]
        assert "missing_column" in ack["error"]["message"]
        rejection_text = notebook_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "register_runtime_broken" in rejection_text
        assert "native marimo runtime preflight" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "notebook_request_failed"


def test_notebook_file_request_rejects_duplicate_public_marimo_variables_before_runtime(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "duplicate_public_vars.py").write_text(
        """
import marimo

app = marimo.App()

@app.cell
def _():
    import plotly.express as _px
    _data = {"segment": ["a", "b"], "value": [1, 2]}
    fig = _px.bar(_data, x="segment", y="value")
    fig
    return

@app.cell
def _():
    import plotly.express as _px
    _data = {"segment": ["a", "b"], "value": [2, 1]}
    fig = _px.line(_data, x="segment", y="value")
    fig
    return
""",
        encoding="utf-8",
    )
    (requests_dir / "register_duplicate_public_vars.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_duplicate_public_vars",
                "operation": "register_notebook",
                "payload": {
                    "workspace_path": "notebooks/duplicate_public_vars.py",
                    "notebook_kind": "data_understanding",
                    "quality_manifest": ready_notebook_quality_manifest(),
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_duplicate_public_vars", name="Duplicate Public Vars")
        session = AgentSession(
            id="as_duplicate_public_vars",
            project_id=project.id,
            goal_text="Register a runtime-valid notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_duplicate_public_vars.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert "not a valid native marimo source" in ack["error"]["message"]
        assert "fig" in ack["error"]["message"]
        assert "multiple cells" in ack["error"]["message"]
        assert "native marimo runtime preflight" not in ack["error"]["message"]
        assert ack["error"]["issues"] == [
            {
                "pointer": "notebook.source.public_variables.fig",
                "message": "marimo public variable `fig` is defined in multiple cells at lines [10, 18]",
                "code": "duplicate_public_marimo_variable",
                "variable": "fig",
                "lines": [10, 18],
                "fix": (
                    "Rename repeated cell-local temporaries named `fig` to `_fig`, or give each public output "
                    "a unique semantic name."
                ),
            }
        ]
        rejection_text = notebook_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "register_duplicate_public_vars" in rejection_text
        assert "Top issues:" in rejection_text
        assert "notebook.source.public_variables.fig" in rejection_text
        assert "duplicate_public_marimo_variable" in rejection_text
        assert "multiple cells" in rejection_text


def test_notebook_file_request_accepts_registered_marimo_notebook_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = notebook_requests_dir(workspace)
    requests_dir.mkdir(parents=True)

    with sessionmaker(engine)() as db:
        project = Project(id="p_marimo_notebook_request", name="marimo Notebook Request")
        session = AgentSession(
            id="as_marimo_notebook_request",
            project_id=project.id,
            goal_text="Register an already materialized marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "notebook_story",
                        "title": "Notebook story",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Prepare node for a registered marimo notebook artifact.",
        )
        notebook_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="marimo_notebook",
            name="registered_marimo_notebook",
            filename="story.py",
            text=VISUAL_MARIMO_NOTEBOOK_SOURCE,
            metadata={
                "project_id": project.id,
                "agent_session_id": session.id,
                "source": "main_agent_session_workspace",
            },
        )
        db.commit()
        (requests_dir / "register_existing_marimo.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_notebook_request.v1",
                    "request_id": "register_existing_marimo",
                    "operation": "register_notebook",
                    "payload": {
                        "artifact_id": notebook_artifact.id,
                        "research_plan_node_id": "notebook_story",
                        "notebook_kind": "data_understanding",
                        "quality_manifest": ready_notebook_quality_manifest(),
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_existing_marimo.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "succeeded"
        assert ack["result"]["notebook_artifact_id"] == notebook_artifact.id
        assert ack["result"]["research_plan_node_id"] == "notebook_story"
        assert ack["result"]["visible_surfaces"]["notebooks"]["artifact_id"] == notebook_artifact.id
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        source_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_id == notebook_artifact.id,
            )
        )
        assert source_edge is not None


def test_notebook_file_request_links_run_model_and_dataset_context(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    notebook = notebooks_dir / "model_diagnostics.py"
    notebook.write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_context", name="Notebook Context")
        session = AgentSession(
            id="as_notebook_context",
            project_id=project.id,
            goal_text="Register model diagnostics notebook context.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="context_dataset_artifact",
            filename="dataset.csv",
            text="x,y\n1,2\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_context",
            project_id=project.id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=1,
            column_count=2,
            schema_hash="schema_hash",
        )
        model_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="model_package",
            name="context_model_artifact",
            filename="model.json",
            text="{}",
            metadata={"project_id": project.id},
        )
        run = ExperimentRun(
            id="run_context",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        model_version = ModelVersion(
            id="mv_context",
            project_id=project.id,
            experiment_run_id=run.id,
            dataset_snapshot_id=dataset.id,
            artifact_id=model_artifact.id,
            name="context_model",
            version=1,
            model_family="tree",
            model_type="regressor",
            task_type="regression",
            status="created",
        )
        run.model_version_id = model_version.id
        db.add_all([dataset, run, model_version])
        db.commit()
        (requests_dir / "register_model_context.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_notebook_request.v1",
                    "request_id": "register_model_context",
                    "operation": "register_notebook",
                    "payload": {
                        "workspace_path": "notebooks/model_diagnostics.py",
                        "title": "モデル診断Notebook",
                        "notebook_kind": "model_diagnostics",
                        "run_id": run.id,
                        "quality_manifest": {
                            **ready_model_diagnostics_quality_manifest(),
                            "key_findings": [
                                "Hierarchical median remains competitive under group holdout.",
                                "Text features need leakage review before becoming a primary model.",
                            ],
                            "read_order": [
                                {"label": "Model comparison", "anchor": "model-comparison"},
                                {"label": "Error slices", "anchor": "error-slices"},
                            ],
                            "data_sources_used": [dataset.id],
                            "limitations": ["Business target definition remains provisional."],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        notebook_metadata = loads_json(notebook_artifact.metadata_json, {})
        assert notebook_metadata["title"] == "モデル診断Notebook"
        assert notebook_metadata["notebook_kind"] == "model_diagnostics"
        assert notebook_metadata["run_id"] == run.id
        assert notebook_metadata["model_version_id"] == model_version.id
        assert notebook_metadata["dataset_snapshot_id"] == dataset.id
        assert notebook_metadata["notebook_quality_status"] == "manifest_provided"
        assert notebook_metadata["notebook_quality_manifest"]["figure_count"] == 5
        assert notebook_metadata["notebook_quality_manifest"]["model_diagnostics"]["checks"][0]["name"] == "permutation_importance"
        assert notebook_metadata["key_finding_count"] == 2
        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_model_context.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "succeeded"
        assert ack["result"]["notebook_quality"]["status"] == "manifest_provided"
        assert ack["result"]["notebook_quality"]["figure_count"] == 5
        assert ack["result"]["notebook_quality"]["model_diagnostics_check_count"] == 4
        assert ack["result"]["run_id"] == run.id
        assert ack["result"]["model_version_id"] == model_version.id
        assert ack["result"]["dataset_snapshot_id"] == dataset.id
        assert ack["result"]["visible_surfaces"]["notebooks"]["artifact_id"] == notebook_artifact.id
        assert ack["result"]["visible_surfaces"]["assets"]["target_anchor"] == "asset-notebooks"
        assert ack["result"]["visible_surfaces"]["data"]["target_tab"] == "Data"
        assert ack["result"]["visible_surfaces"]["data"]["target_anchor"] == "data-focus"
        assert ack["result"]["visible_surfaces"]["data"]["dataset_snapshot_id"] == dataset.id
        assert ack["result"]["visible_surfaces"]["leaderboard"]["target_tab"] == "Leaderboard"
        assert ack["result"]["visible_surfaces"]["leaderboard"]["target_anchor"] == "result-readout"
        assert ack["result"]["visible_surfaces"]["leaderboard"]["run_id"] == run.id
        assert ack["result"]["visible_surfaces"]["leaderboard"]["model_version_id"] == model_version.id

        notebook_index = build_project_notebook_index(db, project)
        assert notebook_index["counts"]["total"] == 1
        item = notebook_index["items"][0]
        assert item["title"] == "モデル診断Notebook"
        assert item["notebook_kind"] == "model_diagnostics"
        assert item["run_id"] == run.id
        assert item["model_version_id"] == model_version.id
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["coverage"]["has_quality_manifest"] is True
        assert item["coverage"]["declared_figure_count"] == 5
        assert item["coverage"]["declared_finding_count"] == 2
        assert item["quality_manifest"]["read_order"][0]["label"] == "Model comparison"
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["response_brief"]["run_id"] == run.id
        assert chat_payload["response_brief"]["model_version_id"] == model_version.id
        assert chat_payload["response_brief"]["dataset_snapshot_id"] == dataset.id
        assert chat_payload["response_brief"]["notebook_quality"]["status"] == "manifest_provided"
        assert chat_payload["visible_surfaces"]["data"]["dataset_snapshot_id"] == dataset.id
        assert chat_payload["visible_surfaces"]["leaderboard"]["run_id"] == run.id
        assert any(action["target_tab"] == "Leaderboard" for action in chat_payload["actions"])


def test_model_diagnostics_notebook_request_links_related_runs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "model_diagnostics.py").write_text(VISUAL_MARIMO_NOTEBOOK_SOURCE, encoding="utf-8")

    with sessionmaker(engine)() as db:
        project = Project(id="p_related_model_diagnostics", name="Related Model Diagnostics")
        session = AgentSession(
            id="as_related_model_diagnostics",
            project_id=project.id,
            goal_text="Register one diagnostics notebook for multiple leaderboard runs.",
            workspace_path=str(workspace),
        )
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="related_dataset_artifact",
            filename="dataset.csv",
            text="x,y\n1,2\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_related",
            project_id=project.id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=1,
            column_count=2,
            schema_hash="schema_hash",
        )
        first_run = ExperimentRun(
            id="run_related_a",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        second_run = ExperimentRun(
            id="run_related_b",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        db.add_all([project, session, dataset, first_run, second_run])
        db.commit()
        diagnostics_manifest = ready_model_diagnostics_quality_manifest()
        for check in diagnostics_manifest["model_diagnostics"]["checks"]:
            evidence = check.get("evidence")
            if isinstance(evidence, list) and evidence:
                check["evidence"] = [{"workspace_path": evidence[0]}]
        (requests_dir / "register_related_model_diagnostics.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_notebook_request.v1",
                    "request_id": "register_related_model_diagnostics",
                    "operation": "register_notebook",
                    "payload": {
                        "workspace_path": "notebooks/model_diagnostics.py",
                        "title": "モデル比較診断Notebook",
                        "notebook_kind": "model_diagnostics",
                        "related_run_ids": [first_run.id, second_run.id],
                        "quality_manifest": {
                            **diagnostics_manifest,
                            "key_findings": [
                                "The same diagnostics notebook compares both leaderboard runs.",
                            ],
                            "read_order": [
                                {"label": "Model comparison", "anchor": "model-comparison"},
                            ],
                            "data_sources_used": [dataset.id],
                            "limitations": ["This is a compact multi-run diagnostics notebook."],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        metadata = loads_json(notebook_artifact.metadata_json, {})
        assert metadata["notebook_kind"] == "model_diagnostics"
        assert metadata["related_run_ids"] == [first_run.id, second_run.id]
        checks = metadata["notebook_quality_manifest"]["model_diagnostics"]["checks"]
        assert checks[0]["evidence"] == ["notebooks/model_diagnostics.py"]
        assert latest_model_diagnostics_notebook_for_run(db, project.id, first_run.id) == notebook_artifact
        assert latest_model_diagnostics_notebook_for_run(db, project.id, second_run.id) == notebook_artifact

        ack = loads_json(
            (notebook_acks_dir(workspace) / "register_related_model_diagnostics.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert ack["status"] == "succeeded"
        assert ack["result"]["related_run_ids"] == [first_run.id, second_run.id]
        assert ack["result"]["visible_surfaces"]["leaderboard"]["run_ids"] == [first_run.id, second_run.id]

        notebook_index = build_project_notebook_index(db, project)
        item = notebook_index["items"][0]
        assert item["run_id"] is None
        assert item["related_run_ids"] == [first_run.id, second_run.id]


def test_repeated_single_run_notebook_registration_promotes_to_related_runs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "model_diagnostics.py").write_text(VISUAL_MARIMO_NOTEBOOK_SOURCE, encoding="utf-8")

    with sessionmaker(engine)() as db:
        project = Project(id="p_promote_model_diagnostics_links", name="Promote Model Diagnostics Links")
        session = AgentSession(
            id="as_promote_model_diagnostics_links",
            project_id=project.id,
            goal_text="Register the same diagnostics notebook for multiple runs.",
            workspace_path=str(workspace),
        )
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="promote_dataset_artifact",
            filename="dataset.csv",
            text="x,y\n1,2\n",
            metadata={"project_id": project.id},
        )
        dataset = DatasetSnapshot(
            id="ds_promote_related",
            project_id=project.id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=1,
            column_count=2,
            schema_hash="schema_hash",
        )
        first_run = ExperimentRun(
            id="run_promote_a",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        second_run = ExperimentRun(
            id="run_promote_b",
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        db.add_all([project, session, dataset, first_run, second_run])
        db.commit()

        for request_id, run in (
            ("register_model_diagnostics_a", first_run),
            ("register_model_diagnostics_b", second_run),
        ):
            (requests_dir / f"{request_id}.json").write_text(
                dumps_json(
                    {
                        "schema_version": "tablex_notebook_request.v1",
                        "request_id": request_id,
                        "operation": "register_notebook",
                        "payload": {
                            "workspace_path": "notebooks/model_diagnostics.py",
                            "title": "モデル診断Notebook",
                            "notebook_kind": "model_diagnostics",
                            "run_id": run.id,
                            "quality_manifest": {
                                **ready_model_diagnostics_quality_manifest(),
                                "key_findings": ["The same diagnostics notebook is linked by repeated run registrations."],
                                "read_order": [{"label": "Model comparison", "anchor": "model-comparison"}],
                                "data_sources_used": [dataset.id],
                                "limitations": ["Compact fixture notebook."],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        metadata = loads_json(notebook_artifact.metadata_json, {})
        assert metadata.get("run_id") is None
        assert metadata["related_run_ids"] == [first_run.id, second_run.id]
        assert latest_model_diagnostics_notebook_for_run(db, project.id, first_run.id) == notebook_artifact
        assert latest_model_diagnostics_notebook_for_run(db, project.id, second_run.id) == notebook_artifact
        notebook_index = build_project_notebook_index(db, project)
        item = notebook_index["items"][0]
        assert item["run_id"] is None
        assert item["related_run_ids"] == [first_run.id, second_run.id]


def test_model_diagnostics_artifact_request_registers_standard_outputs(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    (workspace / "artifacts").mkdir(parents=True)
    requests_dir = model_diagnostics_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (workspace / "artifacts" / "permutation_importance.csv").write_text(
        "run_id,feature,mean_delta_mae\nrun_diag_a,price,1.2\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "native_feature_importance.csv").write_text(
        "run_id,feature_encoded,importance\nrun_diag_a,price,0.7\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "partial_dependence.csv").write_text(
        "run_id,feature,feature_value,mean_prediction\nrun_diag_a,price,10,42\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "model_diagnostics.json").write_text(
        dumps_json({"schema_version": "codex_model_diagnostics.v1", "runs": ["run_diag_a", "run_diag_b"]}),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_model_diagnostics_artifacts", name="Model Diagnostics Artifacts")
        session = AgentSession(
            id="as_model_diagnostics_artifacts",
            project_id=project.id,
            goal_text="Register model diagnostics artifacts.",
            workspace_path=str(workspace),
        )
        first_run = ExperimentRun(
            id="run_diag_a",
            project_id=project.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        second_run = ExperimentRun(
            id="run_diag_b",
            project_id=project.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        db.add_all([project, session, first_run, second_run])
        db.commit()
        (requests_dir / "register_model_diagnostics_artifacts.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_model_diagnostics_request.v1",
                    "request_id": "register_model_diagnostics_artifacts",
                    "operation": "register_model_diagnostics_artifacts",
                    "payload": {
                        "related_run_ids": [first_run.id, second_run.id],
                        "checks": [
                            {
                                "name": "permutation_importance",
                                "status": "included",
                                "artifact_keys": ["permutation_importance"],
                            },
                            {
                                "name": "native_feature_importance",
                                "status": "included",
                                "artifact_keys": ["native_feature_importance"],
                            },
                            {
                                "name": "partial_dependence",
                                "status": "included",
                                "artifact_keys": ["partial_dependence"],
                            },
                            {
                                "name": "shap",
                                "status": "needs_dependency",
                                "reason": "SHAP dependency is not available in this run.",
                            },
                        ],
                        "artifacts": {
                            "permutation_importance": "artifacts/permutation_importance.csv",
                            "native_feature_importance": "artifacts/native_feature_importance.csv",
                            "partial_dependence": "artifacts/partial_dependence.csv",
                            "model_diagnostics_artifact_pack": "artifacts/model_diagnostics.json",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (model_diagnostics_acks_dir(workspace) / "register_model_diagnostics_artifacts.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert ack["status"] == "succeeded"
        result = ack["result"]
        assert result["run_ids"] == [first_run.id, second_run.id]
        assert result["permutation_importance_artifact_ids"]
        assert result["feature_importance_artifact_ids"]
        assert result["partial_dependence_artifact_ids"]
        assert result["model_diagnostics_artifact_pack_id"]
        pack = db.get(Artifact, result["model_diagnostics_artifact_pack_id"])
        assert pack is not None
        assert pack.asset_type == "model_diagnostics_artifact_pack"
        pack_metadata = loads_json(pack.metadata_json, {})
        assert pack_metadata["related_run_ids"] == [first_run.id, second_run.id]
        assert latest_run_artifact(db, first_run, "model_diagnostics_artifact_pack") == pack
        assert latest_run_artifact(db, second_run, "model_diagnostics_artifact_pack") == pack
        assert latest_run_artifact(db, second_run, "permutation_importance") is not None
        diagnostics_status = experiment_model_diagnostics_artifact_status(
            db,
            project=project,
            runs=[first_run, second_run],
        )
        assert diagnostics_status["status"] == "registered"
        first_run_status = next(item for item in diagnostics_status["runs"] if item["run_id"] == first_run.id)
        assert first_run_status["checks"]["permutation_importance"]["artifact_status"] == "file_available"
        lineage_count = db.scalar(
            select(func.count(LineageEdge.id)).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "diagnoses",
                LineageEdge.to_asset_id == pack.id,
            )
        )
        assert lineage_count == 2
        evidence = db.scalar(
            select(Evidence).where(
                Evidence.project_id == project.id,
                Evidence.evidence_type == "model_diagnostics_artifact_pack",
            )
        )
        assert evidence is not None
        assert evidence.source_artifact_id == pack.id


def test_model_diagnostics_artifact_request_reprocesses_stale_success_ack(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    (workspace / "artifacts").mkdir(parents=True)
    requests_dir = model_diagnostics_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (workspace / "artifacts" / "permutation_importance.csv").write_text(
        "run_id,feature,mean_delta_mae\nrun_diag_a,price,1.2\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "native_feature_importance.csv").write_text(
        "run_id,feature_encoded,importance\nrun_diag_a,price,0.7\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "partial_dependence.csv").write_text(
        "run_id,feature,feature_value,mean_prediction\nrun_diag_a,price,10,42\n",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "model_diagnostics.json").write_text(
        dumps_json({"schema_version": "codex_model_diagnostics.v1", "runs": ["run_diag_a"]}),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_model_diagnostics_stale_ack", name="Model Diagnostics Stale ACK")
        session = AgentSession(
            id="as_model_diagnostics_stale_ack",
            project_id=project.id,
            goal_text="Reprocess stale model diagnostics ACK.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(id="run_diag_a", project_id=project.id, runner_type="codex_cli", status="succeeded")
        db.add_all([project, session, run])
        db.commit()
        (requests_dir / "register_model_diagnostics_artifacts.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_model_diagnostics_request.v1",
                    "request_id": "register_model_diagnostics_artifacts",
                    "operation": "register_model_diagnostics_artifacts",
                    "payload": {
                        "run_id": run.id,
                        "checks": [
                            {
                                "name": "permutation_importance",
                                "status": "included",
                                "artifact_keys": ["permutation_importance"],
                            },
                            {
                                "name": "native_feature_importance",
                                "status": "included",
                                "artifact_keys": ["native_feature_importance"],
                            },
                            {
                                "name": "partial_dependence",
                                "status": "included",
                                "artifact_keys": ["partial_dependence"],
                            },
                            {"name": "shap", "status": "needs_dependency", "reason": "SHAP unavailable."},
                        ],
                        "artifacts": {
                            "permutation_importance": "artifacts/permutation_importance.csv",
                            "native_feature_importance": "artifacts/native_feature_importance.csv",
                            "partial_dependence": "artifacts/partial_dependence.csv",
                            "model_diagnostics_artifact_pack": "artifacts/model_diagnostics.json",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        ack_dir = model_diagnostics_acks_dir(workspace)
        ack_dir.mkdir(parents=True)
        (ack_dir / "register_model_diagnostics_artifacts.ack.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_model_diagnostics_ack.v1",
                    "request_id": "register_model_diagnostics_artifacts",
                    "operation": "register_model_diagnostics_artifacts",
                    "status": "succeeded",
                    "result": {
                        "artifact_ids": ["art_missing"],
                        "model_diagnostics_artifact_pack_id": "art_missing",
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json((ack_dir / "register_model_diagnostics_artifacts.ack.json").read_text(encoding="utf-8"), {})
        assert ack["status"] == "succeeded"
        assert ack["result"]["model_diagnostics_artifact_pack_id"] != "art_missing"
        assert latest_run_artifact(db, run, "model_diagnostics_artifact_pack") is not None
        assert latest_run_artifact(db, run, "permutation_importance") is not None


def test_model_diagnostics_artifact_request_rejects_missing_included_output(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = model_diagnostics_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (workspace / "artifacts").mkdir(parents=True)
    (workspace / "artifacts" / "permutation_importance.csv").write_text(
        "run_id,feature,mean_delta_mae\nrun_diag_a,price,1.2\n",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_model_diagnostics_reject", name="Model Diagnostics Reject")
        session = AgentSession(
            id="as_model_diagnostics_reject",
            project_id=project.id,
            goal_text="Reject incomplete model diagnostics artifacts.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(id="run_diag_a", project_id=project.id, runner_type="codex_cli", status="succeeded")
        db.add_all([project, session, run])
        db.commit()
        (requests_dir / "register_incomplete_model_diagnostics.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_model_diagnostics_request.v1",
                    "request_id": "register_incomplete_model_diagnostics",
                    "operation": "register_model_diagnostics_artifacts",
                    "payload": {
                        "run_id": run.id,
                        "checks": [
                            {"name": "permutation_importance", "status": "included"},
                            {"name": "native_feature_importance", "status": "included"},
                            {"name": "partial_dependence", "status": "deferred", "reason": "Not run yet."},
                            {"name": "shap", "status": "needs_dependency", "reason": "SHAP unavailable."},
                        ],
                        "artifacts": {
                            "permutation_importance": "artifacts/permutation_importance.csv",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json(
            (model_diagnostics_acks_dir(workspace) / "register_incomplete_model_diagnostics.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert ack["status"] == "failed"
        assert "native_feature_importance" in ack["error"]["message"]
        assert model_diagnostics_request_rejection_path(workspace).exists()
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "model_diagnostics_request_failed"


def test_notebook_file_request_failure_writes_ack_and_chat_attention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = notebook_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (requests_dir / "register_missing.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_missing",
                "operation": "register_notebook",
                "payload": {"workspace_path": "notebooks/missing.py", "research_plan_node_id": "data_understanding"},
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "register_missing_retry.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_missing_retry",
                "operation": "register_notebook",
                "payload": {"workspace_path": "notebooks/missing.py", "research_plan_node_id": "data_understanding"},
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_request_failed", name="Notebook Request Failed")
        session = AgentSession(
            id="as_notebook_request_failed",
            project_id=project.id,
            goal_text="Register a notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json((notebook_acks_dir(workspace) / "register_missing.ack.json").read_text(encoding="utf-8"), {})
        retry_ack = loads_json(
            (notebook_acks_dir(workspace) / "register_missing_retry.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["schema_version"] == "tablex_notebook_ack.v1"
        assert ack["status"] == "failed"
        assert retry_ack["status"] == "failed"
        assert "not registered yet" in ack["error"]["message"]
        rejection = notebook_request_rejection_path(workspace)
        assert rejection.exists()
        rejection_text = rejection.read_text(encoding="utf-8")
        assert "tablex_notebook_request_rejection.v1" in rejection_text
        assert "register_missing" in rejection_text
        assert "register_missing_retry" in rejection_text
        assert ".tablex/acks/notebooks/register_missing_retry.ack.json" in rejection_text
        assert "did not update Chat links" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "notebook_request_failed"
        assert chat_payload["response_brief"]["source_transcript_event"]["event_type"] == "attention_chat_turn_registered"
        chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_count == 1


def test_notebook_file_request_rejects_static_html_registered_as_notebook(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = notebook_requests_dir(workspace)
    requests_dir.mkdir(parents=True)

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_static_request_failed", name="Static Notebook Request Failed")
        session = AgentSession(
            id="as_notebook_static_request_failed",
            project_id=project.id,
            goal_text="Reject static notebook snapshots.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.flush()
        static_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="static_html_notebook_snapshot",
            filename="grandmaster_eda_static.html",
            text="<html><body>static snapshot</body></html>",
            metadata={"project_id": project.id, "notebook_kind": "data_understanding"},
        )
        (requests_dir / "register_static_html.json").write_text(
            dumps_json(
                {
                    "schema_version": "tablex_notebook_request.v1",
                    "request_id": "register_static_html",
                    "operation": "register_notebook",
                    "payload": {"artifact_id": static_artifact.id, "research_plan_node_id": "data_understanding"},
                }
            ),
            encoding="utf-8",
        )
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_registration=False,
        )
        db.commit()

        ack = loads_json((notebook_acks_dir(workspace) / "register_static_html.ack.json").read_text(encoding="utf-8"), {})
        assert ack["schema_version"] == "tablex_notebook_ack.v1"
        assert ack["status"] == "failed"
        assert "native marimo Python source" in ack["error"]["message"]
        rejection_text = notebook_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "register_static_html" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "notebook_request_failed"


def test_auto_registered_notebook_attaches_to_single_active_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "deep_data_understanding.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_auto_notebook_plan_link", name="Auto Notebook Plan Link")
        session = AgentSession(
            id="as_auto_notebook_plan_link",
            project_id=project.id,
            goal_text="Write a readable data understanding notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                ],
            },
            author_type="codex",
            reason="Codex committed the active chapter before notebook authoring.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        source_edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
                LineageEdge.to_asset_id == notebook_artifact.id,
            )
        )
        assert source_edge is not None
        assert loads_json(source_edge.metadata_json, {})["node_id"] == "data_understanding"
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["actions"][0]["target_tab"] == "Notebooks"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert chat_payload["response_brief"]["research_plan_node_id"] == "data_understanding"
        assert chat_payload["response_brief"]["source_transcript_event"]["event_type"] == "notebook_chat_turn_registered"

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        data_block = next(block for block in timeline["blocks"] if block["id"] == "data_understanding")
        assert any(link["artifact_id"] == notebook_artifact.id for link in data_block["attached_artifacts"])


def test_auto_registered_notebook_without_request_asks_codex_for_context_registration(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    (notebooks_dir / "deep_data_understanding.py").write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_context_needed", name="Notebook Context Needed")
        session = AgentSession(
            id="as_notebook_context_needed",
            project_id=project.id,
            goal_text="Write a notebook and register its context.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None

        inbox = notebook_context_request_path(workspace)
        assert inbox.exists()
        inbox_text = inbox.read_text(encoding="utf-8")
        assert "tablex_notebook_context_request.v1" in inbox_text
        assert notebook_artifact.id in inbox_text
        assert ".tablex/requests/notebooks/" in inbox_text

        quality_inbox = notebook_quality_repair_path(workspace)
        assert quality_inbox.exists()
        quality_inbox_text = quality_inbox.read_text(encoding="utf-8")
        assert "tablex_notebook_quality_repair.v1" in quality_inbox_text
        assert notebook_artifact.id in quality_inbox_text

        attention_chats = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.desc())
            ).all()
        )
        assert attention_chats
        attention_payloads = [
            loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
            for artifact in attention_chats
        ]
        attention_by_kind = {
            payload.get("intent", {}).get("message_kind"): payload
            for payload in attention_payloads
            if payload.get("intent", {}).get("type") == "agent_attention_event"
        }
        attention_payload = attention_by_kind["notebook_context_registration_needed"]
        quality_payload = attention_by_kind["notebook_quality_repair_needed"]
        assert quality_payload["actions"][0]["target_tab"] == "Notebooks"
        assert notebook_artifact.id in quality_payload["response_brief"]["details"]["notebook_artifact_ids"]
        assert attention_payload["intent"]["type"] == "agent_attention_event"
        assert attention_payload["intent"]["message_kind"] == "notebook_context_registration_needed"
        assert attention_payload["actions"][0]["target_tab"] == "Notebooks"
        assert attention_payload["actions"][0]["target_anchor"] == "notebook-native-marimo-top"
        assert notebook_artifact.id in attention_payload["response_brief"]["details"]["notebook_artifact_ids"]

        initial_inbox_entries = list_inbox_entries(workspace)
        assert len([entry for entry in initial_inbox_entries if entry["type"] == "notebook_context_request"]) == 1
        assert len([entry for entry in initial_inbox_entries if entry["type"] == "notebook_quality_repair"]) == 1

        request_context_for_auto_registered_notebooks(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
        )
        request_quality_repair_for_session_notebooks(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()

        repeated_inbox_entries = list_inbox_entries(workspace)
        assert len([entry for entry in repeated_inbox_entries if entry["type"] == "notebook_context_request"]) == 1
        assert len([entry for entry in repeated_inbox_entries if entry["type"] == "notebook_quality_repair"]) == 1

        repeated_attention_payloads = [
            loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
            for artifact in db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.desc())
            ).all()
        ]
        assert (
            len(
                [
                    payload
                    for payload in repeated_attention_payloads
                    if payload.get("intent", {}).get("message_kind") == "notebook_context_registration_needed"
                ]
            )
            == 1
        )
        assert (
            len(
                [
                    payload
                    for payload in repeated_attention_payloads
                    if payload.get("intent", {}).get("message_kind") == "notebook_quality_repair_needed"
                ]
            )
            == 1
        )


def test_notebook_request_context_registration_does_not_emit_missing_context_attention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    requests_dir = notebook_requests_dir(workspace)
    notebooks_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (notebooks_dir / "data_understanding.py").write_text(
        VISUAL_MARIMO_NOTEBOOK_SOURCE,
        encoding="utf-8",
    )
    (requests_dir / "register_data_understanding.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_notebook_request.v1",
                "request_id": "register_data_understanding",
                "operation": "register_notebook",
                "payload": {
                    "workspace_path": "notebooks/data_understanding.py",
                    "notebook_kind": "data_understanding",
                    "research_plan_node_id": "data_understanding",
                    "quality_manifest": ready_notebook_quality_manifest(),
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_notebook_context_registered", name="Notebook Context Registered")
        session = AgentSession(
            id="as_notebook_context_registered",
            project_id=project.id,
            goal_text="Write and register a notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Prepare the notebook context node.",
            strict_validation=True,
        )
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        assert not notebook_context_request_path(workspace).exists()
        chat_payloads = [
            loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
            for artifact in db.scalars(
                select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            ).all()
        ]
        assert not any(payload.get("intent", {}).get("message_kind") == "notebook_context_registration_needed" for payload in chat_payloads)


def test_existing_notebook_registration_restores_chat_and_plan_link(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    source_path = tmp_path / "existing_notebook.py"
    source_path.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id="p_existing_registration", name="Existing Registration")
        session = AgentSession(
            id="as_existing_registration",
            project_id=project.id,
            goal_text="Expose an already registered notebook.",
        )
        notebook_artifact = Artifact(
            id="art_existing_notebook",
            project_id=project.id,
            asset_type="analysis_notebook",
            name="existing_notebook",
            version=1,
            uri=str(source_path.parent),
            content_hash="hash_nb",
            size_bytes=120,
            metadata_json=dumps_json(
                {
                    "source": "main_agent_session_workspace",
                    "agent_session_id": session.id,
                    "notebook_kind": "data_understanding",
                    "primary_path": str(source_path),
                }
            ),
        )
        db.add_all([project, session, notebook_artifact])
        db.commit()
        commit_research_plan_revision(
            db,
            project_id=project.id,
            document={
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "active",
                    }
                ],
            },
            author_type="codex",
            reason="Codex is working on the data understanding chapter.",
            strict_validation=True,
        )
        db.commit()

        register_agent_session_notebook_source_output(db, store=store, session=session, artifact=notebook_artifact)
        db.commit()

        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "notebook_artifact_update"
        assert chat_payload["intent"]["status"] == "quality_needs_attention"
        assert chat_payload["actions"][0]["artifact_id"] == notebook_artifact.id
        assert chat_payload["actions"][0]["artifact_ids"] == [notebook_artifact.id]
        assert chat_payload["response_brief"]["research_plan_node_id"] == "data_understanding"
        assert chat_payload["response_brief"]["source_transcript_event"]["event_type"] == "notebook_chat_turn_registered"
        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="en-US")
        data_block = timeline["blocks"][0]
        attached_ids = {link["artifact_id"] for link in data_block["attached_artifacts"] if link["link_type"] == "artifact"}
        assert {
            notebook_artifact.id,
        }.issubset(attached_ids)


def test_research_plan_ingest_commits_contract_valid_workspace_plan(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "research_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "modeling_review",
                        "title": "Modeling review",
                        "granularity": "chapter",
                        "why_it_matters": "Compare candidate models after EDA.",
                        "status": "active",
                        "localizations": {
                            "ja-JP": {
                                "title": "モデリングレビュー",
                                "why_it_matters": "EDA後に候補モデルを比較します。",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        user = User(id="u_plan_display", email="plan-display@example.com", locale="ja-JP")
        project = Project(
            id="p_plan_display",
            name="Plan Display",
            created_by=user.id,
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_display",
            project_id=project.id,
            goal_text="Keep the plan readable.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([user, project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "research_plan")
        )
        assert artifact is not None
        plan_payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        assert plan_payload["timeline_blocks"][0]["title"] == "Modeling review"
        assert plan_payload["timeline_blocks"][0]["why_it_matters"] == "Compare candidate models after EDA."
        revision = db.scalar(select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id))
        assert revision is not None
        assert revision.source_artifact_id == artifact.id
        assert revision.author_type == "codex"
        assert loads_json(revision.document_json, {})["timeline_blocks"][0]["title"] == "Modeling review"

        events = list(db.scalars(select(AgentTranscriptEvent).where(AgentTranscriptEvent.session_id == session.id)))
        assert [event.event_type for event in events] == ["artifact_registered"]
        assert not research_plan_contract_request_path(workspace).exists()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        repeated_events = list(db.scalars(select(AgentTranscriptEvent).where(AgentTranscriptEvent.session_id == session.id)))
        assert [event.event_type for event in repeated_events] == ["artifact_registered"]
        revision_count = db.scalar(
            select(func.count())
            .select_from(ResearchPlanRevision)
            .where(ResearchPlanRevision.project_id == project.id)
        )
        assert revision_count == 1


def test_research_plan_ingest_rejects_invalid_workspace_plan_without_canonical_revision(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "research_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "status": "pending",
                    },
                    {
                        "id": "modeling",
                        "title": "Modeling",
                        "granularity": "chapter",
                        "status": "done",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_invalid_artifact",
            name="Invalid Plan Artifact",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_invalid_artifact",
            project_id=project.id,
            goal_text="Reject invalid plan artifacts.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "research_plan")
        )
        assert artifact is not None
        assert db.scalar(
            select(func.count())
            .select_from(ResearchPlanRevision)
            .where(ResearchPlanRevision.project_id == project.id)
        ) == 0
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == session.id)
                .order_by(AgentTranscriptEvent.event_index.asc())
            )
        )
        assert [event.event_type for event in events] == [
            "artifact_registered",
            "research_plan_artifact_rejected",
            "attention_chat_turn_registered",
        ]
        rejection_payload = loads_json(events[1].payload_json, {})
        issue_codes = {issue["code"] for issue in rejection_payload["issues"]}
        assert "completed_after_open_predecessor" in issue_codes
        rejection_path = research_plan_artifact_rejection_path(workspace)
        assert rejection_path.exists()
        rejection_text = rejection_path.read_text(encoding="utf-8")
        assert "tablex_research_plan_artifact_rejection.v1" in rejection_text
        assert "completed_after_open_predecessor" in rejection_text
        assert ".tablex/requests/research_plan/<new_request_id>.json" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "research_plan_request_failed"
        assert (
            "作業計画の表示はまだ更新していません" in chat_payload["assistant_message"]
            or "visible work plan has not been updated yet" in chat_payload["assistant_message"]
        )
        assert "分析は続いています" in chat_payload["assistant_message"] or "analysis is still running" in chat_payload["assistant_message"]
        assert "構造化エラー" not in chat_payload["assistant_message"]
        assert "structured error" not in chat_payload["assistant_message"]
        assert "ACK" not in chat_payload["assistant_message"]
        assert chat_payload["actions"][0]["target_tab"] == "Home"


def test_same_research_plan_failure_from_artifact_and_request_creates_one_chat_attention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    request_dir = research_plan_requests_dir(workspace)
    outputs_dir.mkdir(parents=True)
    request_dir.mkdir(parents=True)
    invalid_document = {
        "schema_version": "research_plan.v2",
        "project_id": "p_plan_duplicate_attention",
        "timeline_blocks": [
            {
                "id": "data_understanding",
                "title": "Data understanding",
                "granularity": "chapter",
                "status": "active",
            },
            {
                "id": "modeling",
                "title": "Modeling",
                "granularity": "chapter",
                "status": "active",
            },
        ],
    }
    (outputs_dir / "research_plan.json").write_text(dumps_json(invalid_document), encoding="utf-8")
    (request_dir / "commit_same_invalid_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "operation": "commit_revision",
                "request_id": "commit_same_invalid_plan",
                "payload": {"document": invalid_document},
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_duplicate_attention",
            name="Duplicate Plan Attention",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_duplicate_attention",
            project_id=project.id,
            goal_text="Reject duplicate invalid plan paths.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        failed_plan_event_count = db.scalar(
            select(func.count())
            .select_from(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type.in_(["research_plan_artifact_rejected", "research_plan_request_failed"]),
            )
        )
        assert failed_plan_event_count == 2
        chat_artifacts = list(
            db.scalars(
                select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            )
        )
        assert len(chat_artifacts) == 1
        chat_payload = loads_json(artifact_primary_path(chat_artifacts[0]).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "research_plan_request_failed"


def test_research_plan_file_requests_commit_presence_links_and_attention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    requests_dir = workspace / ".tablex" / "requests" / "research_plan"
    outputs_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (outputs_dir / "deep_eda.md").write_text("# Deep EDA\n", encoding="utf-8")
    (requests_dir / "01_commit.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "rp_req_commit",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "deep_data_understanding",
                                "title": "Deep data understanding",
                                "granularity": "chapter",
                                "why_it_matters": "Inspect the actual data story before modeling.",
                                "status": "active",
                            }
                        ],
                    },
                    "reason": "Codex declared the current plan.",
                },
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "02_current.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "rp_req_current",
                "operation": "set_current_work",
                "payload": {
                    "node_id": "deep_data_understanding",
                    "summary": "Writing the EDA narrative and checking leakage-sensitive fields.",
                    "expected_outputs": ["EDA report"],
                },
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "03_attach.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "rp_req_attach",
                "operation": "attach_artifact",
                "payload": {
                    "node_id": "deep_data_understanding",
                    "workspace_path": "outputs/deep_eda.md",
                    "role": "report",
                },
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "04_attention.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "rp_req_attention",
                "operation": "request_human_attention",
                "payload": {
                    "node_id": "deep_data_understanding",
                    "question": "Is this target definition the production objective?",
                    "why_it_matters": "It changes the evaluation boundary.",
                    "provisional_assumption": "Continue with the uploaded objective for local analysis.",
                    "urgency": "high",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_request",
            name="Plan Request",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_request",
            project_id=project.id,
            goal_text="Keep the plan moving.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack_dir = workspace / ".tablex" / "acks" / "research_plan"
        for name in ("01_commit", "02_current", "03_attach", "04_attention"):
            ack = loads_json((ack_dir / f"{name}.ack.json").read_text(encoding="utf-8"), {})
            assert ack["status"] == "succeeded"

        revision = db.scalar(select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id))
        assert revision is not None
        assert loads_json(revision.document_json, {})["timeline_blocks"][0]["id"] == "deep_data_understanding"
        current = db.scalar(select(ResearchPlanCurrentWork).where(ResearchPlanCurrentWork.project_id == project.id))
        assert current is not None
        assert current.node_id == "deep_data_understanding"
        linked_artifact = next(
            (
                artifact
                for artifact in db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
                if loads_json(artifact.metadata_json, {}).get("workspace_relative_path") == "outputs/deep_eda.md"
            ),
            None,
        )
        assert linked_artifact is not None
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
        )
        assert edge is not None
        assert edge.to_asset_id == linked_artifact.id
        question = db.scalar(select(Question).where(Question.project_id == project.id, Question.topic == "research_plan"))
        assert question is not None
        assert question.can_proceed_without_answer is True
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "research_plan_human_attention_requested"
        assert chat_payload["response_brief"]["details"]["question_id"] == question.id
        assert chat_payload["actions"][0]["target_tab"] == "Assumptions"
        assert chat_payload["actions"][0]["target_anchor"] == "assumption-review"


def test_research_plan_file_requests_accept_explicit_legacy_path_and_node_alias(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    requests_dir = workspace / ".tablex" / "requests" / "research_plan"
    outputs_dir.mkdir(parents=True)
    requests_dir.mkdir(parents=True)
    (outputs_dir / "research_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "research_plan.v2",
                "timeline_blocks": [
                    {
                        "id": "data_understanding",
                        "title": "Data understanding",
                        "granularity": "chapter",
                        "why_it_matters": "Inspect the data before modeling.",
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "01_commit_legacy_path.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "legacy_commit_path",
                "operation": "commit_revision",
                "research_plan_path": "outputs/research_plan.json",
                "reason": "Codex pointed Tablex at the explicit plan JSON file.",
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "02_current_alias.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "legacy_current_alias",
                "operation": "set_current_work",
                "research_plan_node_id": "data_understanding",
                "summary": "Reading the uploaded table and preparing EDA evidence.",
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_request_legacy_alias",
            name="Plan Request Legacy Alias",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_request_legacy_alias",
            project_id=project.id,
            goal_text="Keep the plan moving.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        commit_ack = loads_json(
            (workspace / ".tablex" / "acks" / "research_plan" / "01_commit_legacy_path.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        current_ack = loads_json(
            (workspace / ".tablex" / "acks" / "research_plan" / "02_current_alias.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert commit_ack["status"] == "succeeded"
        assert current_ack["status"] == "succeeded"
        assert commit_ack["result"]["compatibility_warnings"]
        assert current_ack["result"]["compatibility_warnings"]
        current = db.scalar(select(ResearchPlanCurrentWork).where(ResearchPlanCurrentWork.project_id == project.id))
        assert current is not None
        assert current.node_id == "data_understanding"
        assert (
            db.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            )
            == 0
        )


def test_failed_research_plan_file_request_is_announced_in_agent_chat(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = workspace / ".tablex" / "requests" / "research_plan"
    requests_dir.mkdir(parents=True)
    (requests_dir / "bad_current.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "bad_current",
                "operation": "set_current_work",
                "payload": {"node_id": "", "summary": "Missing node id should fail."},
            }
        ),
        encoding="utf-8",
    )
    (requests_dir / "bad_current_retry.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "bad_current_retry",
                "operation": "set_current_work",
                "payload": {"node_id": "", "summary": "The same structural error should not spam chat."},
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_request_failed",
            name="Plan Request Failed",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_request_failed",
            project_id=project.id,
            goal_text="Keep the plan moving.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json(
            (workspace / ".tablex" / "acks" / "research_plan" / "bad_current.ack.json").read_text(encoding="utf-8"),
            {},
        )
        retry_ack = loads_json(
            (workspace / ".tablex" / "acks" / "research_plan" / "bad_current_retry.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert ack["status"] == "failed"
        assert retry_ack["status"] == "failed"
        rejection_path = research_plan_request_rejection_path(workspace)
        assert rejection_path.exists()
        rejection_text = rejection_path.read_text(encoding="utf-8")
        assert "tablex_research_plan_request_rejection.v1" in rejection_text
        assert "bad_current" in rejection_text
        assert ".tablex/acks/research_plan/bad_current_retry.ack.json" in rejection_text
        assert "did not change the canonical plan" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "research_plan_request_failed"
        assert chat_payload["actions"][0]["target_tab"] == "Home"
        assert (
            "作業計画の表示はまだ更新していません" in chat_payload["assistant_message"]
            or "visible work plan has not been updated yet" in chat_payload["assistant_message"]
        )
        assert "分析は続いています" in chat_payload["assistant_message"] or "analysis is still running" in chat_payload["assistant_message"]
        assert "set_current_work" not in chat_payload["assistant_message"]
        assert "bad_current" not in chat_payload["assistant_message"]
        assert "ack" not in chat_payload["assistant_message"].lower()
        assert "request" not in chat_payload["assistant_message"].lower()
        chat_count_after_two_failed_requests = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_count_after_two_failed_requests == 1

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        chat_count = db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_count == 1


def test_harness_objective_anchor_advances_after_uploaded_data_and_target(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with sessionmaker(engine)() as db:
        project = Project(id="p_objective_anchor", name="Objective Anchor", target_column="salary")
        db.add(project)
        db.commit()
        dataset_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
            filename="train.csv",
            text="salary,feature\n10,a\n",
            metadata={"project_id": project.id},
        )
        db.commit()

        upload_revision = record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=[dataset_artifact.id],
            primary_artifact_id=dataset_artifact.id,
        )
        assert upload_revision is not None
        objective_revision = record_harness_objective_in_research_plan(
            db,
            project_id=project.id,
            objective_label=project.target_column,
        )
        assert objective_revision is not None

        timeline = build_research_plan_timeline_response(db, project_id=project.id, locale="ja-JP")
        blocks = timeline["blocks"]
        assert [block["status"] for block in blocks[:3]] == ["done", "done", "active"]
        assert blocks[1]["id"] == "objective_framing"
        assert blocks[1]["subtitle"] == "現在の目的: salary"
        assert timeline["current_work"]["node_id"] == "data_understanding"


def test_research_plan_file_request_rejects_open_plan_without_current_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = research_plan_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (requests_dir / "missing_current.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_research_plan_request.v1",
                "request_id": "missing_current",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "pending",
                            }
                        ],
                    },
                    "reason": "Codex forgot to declare the current position.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_missing_current",
            name="Plan Missing Current",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_missing_current",
            project_id=project.id,
            goal_text="Keep the plan unambiguous.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json(
            (workspace / ".tablex" / "acks" / "research_plan" / "missing_current.ack.json").read_text(
                encoding="utf-8"
            ),
            {},
        )
        assert ack["status"] == "failed"
        assert "missing_current_node" in {issue["code"] for issue in ack["error"]["issues"]}
        assert (
            db.scalar(
                select(func.count())
                .select_from(ResearchPlanRevision)
                .where(ResearchPlanRevision.project_id == project.id)
            )
            == 0
        )
        rejection_text = research_plan_request_rejection_path(workspace).read_text(encoding="utf-8")
        assert "missing_current_node" in rejection_text
        assert "active, waiting, or blocked" in rejection_text
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["type"] == "agent_attention_event"
        assert chat_payload["intent"]["message_kind"] == "research_plan_request_failed"
        assert chat_payload["actions"][0]["target_tab"] == "Home"


def test_research_plan_file_request_rejects_missing_schema_version_before_state_change(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    requests_dir = research_plan_requests_dir(workspace)
    requests_dir.mkdir(parents=True)
    (requests_dir / "missing_schema.json").write_text(
        dumps_json(
            {
                "request_id": "missing_schema",
                "operation": "commit_revision",
                "payload": {
                    "document": {
                        "schema_version": "research_plan.v2",
                        "timeline_blocks": [
                            {
                                "id": "data_understanding",
                                "title": "Data understanding",
                                "granularity": "chapter",
                                "status": "active",
                            }
                        ],
                    },
                    "reason": "This should not be processed without the fixed request schema.",
                },
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_plan_request_missing_schema",
            name="Plan Request Missing Schema",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_request_missing_schema",
            project_id=project.id,
            goal_text="Reject malformed plan tool payloads.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        ack = loads_json(
            (research_plan_acks_dir(workspace) / "missing_schema.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert "tablex_research_plan_request.v1" in ack["error"]["message"]
        assert db.scalar(select(func.count()).select_from(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project.id)) == 0
        chat_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        )
        assert chat_artifact is not None
        chat_payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        assert chat_payload["intent"]["message_kind"] == "research_plan_request_failed"
        assert (
            "作業計画の表示はまだ更新していません" in chat_payload["assistant_message"]
            or "visible work plan has not been updated yet" in chat_payload["assistant_message"]
        )
        assert "分析は続いています" in chat_payload["assistant_message"] or "analysis is still running" in chat_payload["assistant_message"]


def test_published_raw_codex_transcript_is_ingested_as_session_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    append_runner_stream_to_workspace(
        workspace,
        stream_name="stdout",
        line='{"type":"turn.started","turn_id":"turn_1"}\n',
    )
    publish_raw_codex_transcript_snapshot(workspace)

    with sessionmaker(engine)() as db:
        project = Project(id="p_raw", name="Raw Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_raw",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifact = db.scalar(select(Artifact).where(Artifact.project_id == project.id))
        assert artifact is not None
        assert artifact.asset_type == "agent_session_transcript"
        metadata = loads_json(artifact.metadata_json, {})
        assert metadata["transcript_kind"] == "codex_cli_stdout_jsonl"
        assert artifact_primary_path(artifact).read_text(encoding="utf-8").startswith('{"type":"turn.started"')
