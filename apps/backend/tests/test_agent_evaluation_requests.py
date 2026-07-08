from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import AgentSession, DatasetSnapshot, EvaluationCandidate, ExperimentRun, Job, Project
from tabular_harness.services.agent_requests.evaluation import (
    EVALUATION_ACK_SCHEMA_VERSION,
    process_evaluation_tool_requests,
)
from tabular_harness.services.evaluation import approve_spec, promote_candidate_to_spec
from tabular_harness.worker.jobs import create_default_worker


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
    )
    return TestClient(create_app(settings))


def upload_project_dataset(client: TestClient) -> tuple[str, str]:
    project_response = client.post(
        "/api/projects",
        json={"name": "Evaluation request demo", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    csv_bytes = (
        b"customer_id,created_at,feature,fold,target\n"
        b"c1,2026-01-01,10,0,0\n"
        b"c1,2026-01-02,11,1,1\n"
        b"c2,2026-01-03,13,0,0\n"
        b"c2,2026-01-04,9,1,1\n"
        b"c3,2026-01-05,8,0,0\n"
        b"c3,2026-01-06,7,1,1\n"
        b"c4,2026-01-07,12,0,0\n"
        b"c4,2026-01-08,6,1,1\n"
    )
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("demo.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        dataset = db.scalar(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.desc())
        )
        assert dataset is not None
        dataset_id = dataset.id
    return project_id, dataset_id


def run_worker_job(client: TestClient, job_id: str) -> dict[str, Any]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        completed = create_default_worker(store=app.state.artifact_store).run_job(db, job)
        assert completed.status == "succeeded", completed.error_message
        return loads_json(completed.output_json, {})


def test_agent_evaluation_request_creates_candidate_and_ack(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id, dataset_id = upload_project_dataset(client)
    workspace = tmp_path / "workspace"
    request_dir = workspace / ".tablex" / "requests" / "evaluation"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "propose_auc_group.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": "tablex_evaluation_request.v1",
                "request_id": "propose_auc_group",
                "operation": "propose_evaluation",
                "payload": {
                    "dataset_snapshot_id": dataset_id,
                    "objective_metric": {"name": "ROC-AUC", "direction": "higher_is_better"},
                    "secondary_metrics": ["pr_auc"],
                    "split_policy": {"kind": "group", "params": {"group_column": "customer_id", "seed": 42}},
                    "rationale": "Keep repeated customer rows on one side of validation.",
                    "provisional_assumption": "No external holdout file is available.",
                },
            }
        ),
        encoding="utf-8",
    )
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        session = AgentSession(
            id="ags_eval_request",
            project_id=project_id,
            goal_text="Evaluate",
            status="running",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.flush()
        process_evaluation_tool_requests(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
        )
        candidate = db.scalar(select(EvaluationCandidate).where(EvaluationCandidate.project_id == project_id))
        assert candidate is not None
        assert candidate.primary_metric == "roc_auc"
        assert candidate.split_type == "group"
        assert candidate.group_column == "customer_id"
        db.commit()
    ack = loads_json((workspace / ".tablex" / "acks" / "evaluation" / "propose_auc_group.ack.json").read_text(), {})
    assert ack["schema_version"] == EVALUATION_ACK_SCHEMA_VERSION
    assert ack["status"] == "succeeded"
    assert ack["result"]["candidate_id"]
    assert ack["result"]["split_generation_supported"] is True


@pytest.mark.parametrize(
    ("split_kind", "params", "expected_column_attr", "expected_column", "split_generation_supported"),
    [
        ("time", {"time_column": "created_at", "test_fraction": 0.25}, "time_column", "created_at", True),
        ("fold_column", {"fold_column": "fold"}, None, None, False),
        ("fixed_file", {"validation_file_ref": "validation_holdout.csv"}, None, None, False),
    ],
)
def test_agent_evaluation_request_accepts_non_group_policy_shapes(
    tmp_path: Path,
    split_kind: str,
    params: dict[str, Any],
    expected_column_attr: str | None,
    expected_column: str | None,
    split_generation_supported: bool,
) -> None:
    client = make_client(tmp_path)
    project_id, dataset_id = upload_project_dataset(client)
    workspace = tmp_path / f"workspace_{split_kind}"
    request_dir = workspace / ".tablex" / "requests" / "evaluation"
    request_dir.mkdir(parents=True)
    request_id = f"propose_{split_kind}"
    (request_dir / f"{request_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "tablex_evaluation_request.v1",
                "request_id": request_id,
                "operation": "propose_evaluation",
                "payload": {
                    "dataset_snapshot_id": dataset_id,
                    "objective_metric": {"name": "roc_auc", "direction": "higher_is_better"},
                    "secondary_metrics": ["log_loss"],
                    "split_policy": {"kind": split_kind, "params": params},
                    "rationale": f"Exercise the {split_kind} fixed-format proposal path.",
                },
            }
        ),
        encoding="utf-8",
    )
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        session = AgentSession(
            id=f"ags_eval_{split_kind}",
            project_id=project_id,
            goal_text="Evaluate",
            status="running",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.flush()
        process_evaluation_tool_requests(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
        )
        candidate = db.scalar(
            select(EvaluationCandidate).where(
                EvaluationCandidate.project_id == project_id,
                EvaluationCandidate.scenario_id == f"codex_{request_id}",
            )
        )
        assert candidate is not None
        assert candidate.primary_metric == "roc_auc"
        assert candidate.split_type == split_kind
        if expected_column_attr:
            assert getattr(candidate, expected_column_attr) == expected_column
        for key, value in params.items():
            assert f'"{key}":' in candidate.rationale_md
            assert str(value) in candidate.rationale_md
        db.commit()
    ack = loads_json((workspace / ".tablex" / "acks" / "evaluation" / f"{request_id}.ack.json").read_text(), {})
    assert ack["schema_version"] == EVALUATION_ACK_SCHEMA_VERSION
    assert ack["status"] == "succeeded"
    assert ack["result"]["split_type"] == split_kind
    assert ack["result"]["split_generation_supported"] is split_generation_supported


def test_agent_evaluation_generate_split_request_queues_job(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id, _dataset_id = upload_project_dataset(client)
    app = cast(Any, client.app)
    workspace = tmp_path / "workspace"
    request_dir = workspace / ".tablex" / "requests" / "evaluation"
    request_dir.mkdir(parents=True)
    with app.state.session_factory() as db:
        from tabular_harness.services.evaluation import create_default_evaluation_candidates

        project = db.get(Project, project_id)
        assert project is not None
        latest_dataset = db.scalar(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.desc())
        )
        assert latest_dataset is not None
        candidates = create_default_evaluation_candidates(
            db,
            store=app.state.artifact_store,
            project=project,
            dataset=latest_dataset,
        )
        candidate = next(item for item in candidates if item.split_type == "group")
        spec = promote_candidate_to_spec(db, store=app.state.artifact_store, candidate=candidate)
        approve_spec(spec)
        session = AgentSession(
            id="ags_eval_split",
            project_id=project_id,
            goal_text="Evaluate",
            status="running",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.flush()
        request_path = request_dir / "generate_split.json"
        request_path.write_text(
            json.dumps(
                {
                    "schema_version": "tablex_evaluation_request.v1",
                    "request_id": "generate_split",
                    "operation": "generate_split",
                    "payload": {"evaluation_spec_id": spec.id},
                }
            ),
            encoding="utf-8",
        )
        process_evaluation_tool_requests(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            workspace=workspace,
        )
        db.commit()
    ack = loads_json((workspace / ".tablex" / "acks" / "evaluation" / "generate_split.ack.json").read_text(), {})
    assert ack["status"] == "succeeded"
    job_id = ack["result"]["job_id"]
    output = run_worker_job(client, job_id)
    assert output["split_manifest_id"]


def test_leaderboard_marks_runs_formal_or_provisional(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id, _dataset_id = upload_project_dataset(client)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        from tabular_harness.services.evaluation import create_default_evaluation_candidates, generate_split_manifest

        project = db.get(Project, project_id)
        assert project is not None
        dataset = db.scalar(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.desc())
        )
        assert dataset is not None
        candidate = next(
            item
            for item in create_default_evaluation_candidates(
                db,
                store=app.state.artifact_store,
                project=project,
                dataset=dataset,
            )
            if item.split_type == "group"
        )
        spec = promote_candidate_to_spec(db, store=app.state.artifact_store, candidate=candidate)
        approve_spec(spec)
        split = generate_split_manifest(db, store=app.state.artifact_store, spec=spec)
        formal = ExperimentRun(
            id="run_formal",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            evaluation_spec_id=spec.id,
            split_manifest_id=split.id,
            runner_type="test",
            status="succeeded",
            params_json=json.dumps({"model_id": "formal_model", "model_description": "Formal model"}),
            metrics_json=json.dumps({"primary_metric_name": "roc_auc", "primary_metric_value": 0.7, "roc_auc": 0.7}),
        )
        provisional = ExperimentRun(
            id="run_provisional",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="test",
            status="succeeded",
            params_json=json.dumps({"model_id": "provisional_model", "model_description": "Provisional model"}),
            metrics_json=json.dumps({"primary_metric_name": "roc_auc", "primary_metric_value": 0.8, "roc_auc": 0.8}),
        )
        db.add_all([formal, provisional])
        db.commit()
    response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert response.status_code == 200, response.text
    grades = {item["run_id"]: item["evaluation_grade"] for item in response.json()}
    assert grades["run_formal"] == "formal"
    assert grades["run_provisional"] == "provisional"
