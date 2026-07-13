from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    Base,
    ExperimentRun,
    Job,
    LineageEdge,
    Project,
)
from tabular_harness.services.agent_requests.compute import process_compute_tool_requests
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path
from tabular_harness.services.compute_execution import execute_agent_compute_job
from tabular_harness.services.compute_executor import execute_payload


def test_compute_request_runs_with_cpu_fallback_and_links_resource_evidence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifact-store")
    workspace = tmp_path / "workspace"
    request_dir = workspace / ".tablex" / "requests" / "compute"
    request_dir.mkdir(parents=True)
    script = workspace / "train.py"
    script.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/model.txt').write_text('fitted', encoding='utf-8')\n"
        "Path('outputs/result.json').write_text(json.dumps({"
        "'schema_version':'compute_result.v1','actual_device':os.environ['TABLEX_SELECTED_DEVICE'],"
        "'summary':'Completed the controlled training probe.'}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    request = {
        "schema_version": "tablex_compute_request.v1",
        "operation": "execute",
        "request_id": "gpu_probe",
        "payload": {
            "script_path": "train.py",
            "arguments": [],
            "device_preference": "gpu",
            "fallback_policy": "cpu_on_unavailable",
            "timeout_seconds": 60,
            "decision_context": "Compare the candidate under the available compute runtime.",
            "result_manifest_path": "outputs/result.json",
            "experiment_run_id": "run_compute",
            "outputs": [
                {"path": "outputs/model.txt", "asset_type": "model_package", "name": "compute_model"}
            ],
        },
    }
    (request_dir / "gpu_probe.json").write_text(dumps_json(request), encoding="utf-8")
    with sessionmaker(engine)() as db:
        project = Project(id="p_compute", name="Compute Test")
        session = AgentSession(
            id="ags_compute",
            project_id=project.id,
            goal_text="Test compute routing.",
            workspace_path=str(workspace),
        )
        run = ExperimentRun(
            id="run_compute",
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json="{}",
            metrics_json="{}",
        )
        db.add_all([project, session, run])
        db.commit()
        process_compute_tool_requests(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()
        job = db.scalar(select(Job).where(Job.job_type == "run_agent_compute"))
        assert job is not None
        monkeypatch.setattr(
            "tabular_harness.services.compute_execution.detect_compute_resources",
            lambda **kwargs: {
                "schema_version": "compute_resource_snapshot.v1",
                "gpu": {
                    "status": "unavailable",
                    "usable_for_compute": False,
                    "reason": "No GPU is visible in the isolated executor.",
                },
            },
        )

        result = execute_agent_compute_job(db, store=store, job=job)
        db.commit()

        assert result["job_status"] == "succeeded"
        assert result["selected_device"] == "cpu"
        assert result["actual_device"] == "cpu"
        assert result["fallback_reason"] == "No GPU is visible in the isolated executor."
        evidence = db.get(Artifact, result["compute_resource_evidence_artifact_id"])
        assert evidence is not None
        evidence_payload = loads_json(artifact_primary_path(evidence).read_text(encoding="utf-8"), {})
        assert evidence_payload["requested_device"] == "gpu"
        assert evidence_payload["selected_device"] == "cpu"
        assert evidence_payload["actual_device"] == "cpu"
        assert evidence_payload["execution"]["execution_mode"] == "local_subprocess"
        assert evidence_payload["execution"]["credentials_mounted"] is None
        saved_run = db.get(ExperimentRun, run.id)
        assert saved_run is not None
        run_params = loads_json(saved_run.params_json, {})
        assert run_params["actual_compute_device"] == "cpu"
        assert run_params["compute_resource_evidence_artifact_ids"] == [evidence.id]
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.from_asset_id == run.id,
                LineageEdge.to_asset_id == evidence.id,
                LineageEdge.relation_type == "executed_with_compute_resources",
            )
        )
        assert edge is not None
        ack = loads_json(
            (workspace / ".tablex" / "acks" / "compute" / "gpu_probe.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "completed"
        assert ack["actual_device"] == "cpu"


def test_compute_request_rejects_workspace_escape(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifact-store")
    workspace = tmp_path / "workspace"
    request_dir = workspace / ".tablex" / "requests" / "compute"
    request_dir.mkdir(parents=True)
    (request_dir / "escape.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_compute_request.v1",
                "operation": "execute",
                "request_id": "escape",
                "payload": {
                    "script_path": "../secret.py",
                    "result_manifest_path": "outputs/result.json",
                    "decision_context": "Invalid escape probe.",
                },
            }
        ),
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_escape", name="Escape Test")
        session = AgentSession(
            id="ags_escape",
            project_id=project.id,
            goal_text="Reject escape.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        process_compute_tool_requests(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()

        assert db.scalar(select(Job).where(Job.job_type == "run_agent_compute")) is None
        ack = loads_json(
            (workspace / ".tablex" / "acks" / "compute" / "escape.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert "escapes" in ack["error"]["message"]


def test_unavailable_required_gpu_still_records_failure_evidence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifact-store")
    workspace = tmp_path / "workspace"
    request_dir = workspace / ".tablex" / "requests" / "compute"
    request_dir.mkdir(parents=True)
    (workspace / "train.py").write_text("raise RuntimeError('must not run')\n", encoding="utf-8")
    (request_dir / "gpu_required.json").write_text(
        dumps_json(
            {
                "schema_version": "tablex_compute_request.v1",
                "operation": "execute",
                "request_id": "gpu_required",
                "payload": {
                    "script_path": "train.py",
                    "device_preference": "gpu",
                    "fallback_policy": "fail",
                    "timeout_seconds": 60,
                    "decision_context": "This candidate specifically requires its GPU implementation.",
                    "result_manifest_path": "outputs/result.json",
                },
            }
        ),
        encoding="utf-8",
    )
    with sessionmaker(engine)() as db:
        project = Project(id="p_gpu_required", name="GPU Required")
        session = AgentSession(
            id="ags_gpu_required",
            project_id=project.id,
            goal_text="Record unavailable GPU evidence.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()
        process_compute_tool_requests(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()
        job = db.scalar(select(Job).where(Job.job_type == "run_agent_compute"))
        assert job is not None
        monkeypatch.setattr(
            "tabular_harness.services.compute_execution.detect_compute_resources",
            lambda **kwargs: {
                "schema_version": "compute_resource_snapshot.v1",
                "gpu": {"status": "unavailable", "usable_for_compute": False, "reason": "No GPU is visible."},
            },
        )

        result = execute_agent_compute_job(db, store=store, job=job)
        db.commit()

        assert result["job_status"] == "failed"
        assert result["selected_device"] is None
        assert "GPU was requested but is unavailable" in result["error_message"]
        evidence = db.get(Artifact, result["compute_resource_evidence_artifact_id"])
        assert evidence is not None
        evidence_payload = loads_json(artifact_primary_path(evidence).read_text(encoding="utf-8"), {})
        assert evidence_payload["execution"]["exit_code"] == 78
        assert evidence_payload["result_manifest_error"].startswith("GPU was requested but is unavailable")
        ack = loads_json(
            (workspace / ".tablex" / "acks" / "compute" / "gpu_required.ack.json").read_text(encoding="utf-8"),
            {},
        )
        assert ack["status"] == "failed"
        assert ack["compute_resource_evidence_artifact_id"] == evidence.id


def test_isolated_executor_filters_credentials_and_reports_boundary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    artifact_root = tmp_path / "artifacts"
    workspace = artifact_root / "agent_sessions" / "project" / "session"
    workspace.mkdir(parents=True)
    (workspace / "probe.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path('environment.json').write_text(json.dumps(dict(os.environ)), encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-the-boundary")
    monkeypatch.setattr(
        "tabular_harness.services.compute_executor.detect_compute_resources",
        lambda **kwargs: {
            "schema_version": "compute_resource_snapshot.v1",
            "gpu": {"status": "unavailable", "usable_for_compute": False, "reason": "CPU test"},
        },
    )

    result = execute_payload(
        {
            "schema_version": "isolated_compute_request.v1",
            "workspace_relative_path": "agent_sessions/project/session",
            "script_path": "probe.py",
            "arguments": [],
            "requested_device": "cpu",
            "fallback_policy": "cpu_on_unavailable",
            "timeout_seconds": 30,
        }
    )

    environment = loads_json((workspace / "environment.json").read_text(encoding="utf-8"), {})
    assert result["exit_code"] == 0
    assert result["isolation"] == {
        "execution_mode": "isolated_executor",
        "external_network": False,
        "credentials_mounted": False,
        "metadata_database_mounted": False,
    }
    assert "OPENAI_API_KEY" not in environment
    assert environment["TABLEX_SELECTED_DEVICE"] == "cpu"
