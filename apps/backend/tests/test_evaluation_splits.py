from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import Job
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


def run_queued_job(client: TestClient, job_id: str) -> dict[str, Any]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        worker = create_default_worker(store=app.state.artifact_store)
        completed = worker.run_job(db, job)
        assert completed.status == "succeeded", completed.error_message
        return loads_json(completed.output_json, {})


def create_project_with_candidates(client: TestClient) -> tuple[str, list[dict[str, Any]]]:
    project_response = client.post(
        "/api/projects",
        json={"name": "Temporal Demo", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    csv_bytes = (
        b"customer_id,created_at,feature,target\n"
        b"c1,2026-01-01,10,0\n"
        b"c1,2026-01-02,11,1\n"
        b"c2,2026-01-03,13,0\n"
        b"c2,2026-01-04,9,1\n"
        b"c3,2026-01-05,8,0\n"
        b"c3,2026-01-06,7,1\n"
        b"c4,2026-01-07,12,0\n"
        b"c4,2026-01-08,6,1\n"
    )
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("temporal.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200
    assert design_response.json()["status"] == "queued"
    run_queued_job(client, design_response.json()["id"])

    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    return project_id, cast(list[dict[str, Any]], candidates_response.json())


def promote_approve_and_split(client: TestClient, candidate_id: str) -> dict[str, Any]:
    promote_response = client.post(f"/api/evaluation-candidates/{candidate_id}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200, approve_response.text

    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    split_job = split_response.json()
    assert split_job["status"] == "queued"
    split_output = run_queued_job(client, split_job["id"])
    split_manifest_response = client.get(f"/api/split-manifests/{split_output['split_manifest_id']}")
    assert split_manifest_response.status_code == 200, split_manifest_response.text
    return cast(dict[str, Any], split_manifest_response.json())


def test_time_split_manifest_generation_respects_time_order(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _, candidates = create_project_with_candidates(client)
    time_candidate = next(item for item in candidates if item["split_type"] == "time")

    split = promote_approve_and_split(client, str(time_candidate["id"]))
    summary = split["summary"]

    assert split["train_count"] > 0
    assert split["valid_count"] > 0
    assert summary["split_type"] == "time"
    assert summary["time_column"] == "created_at"
    assert summary["time_order_respected"] is True
    assert summary["time_ranges"]["train"]["max_time"] <= summary["time_ranges"]["valid"]["min_time"]


def test_group_split_manifest_generation_prevents_group_overlap(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _, candidates = create_project_with_candidates(client)
    group_candidate = next(item for item in candidates if item["split_type"] == "group")

    split = promote_approve_and_split(client, str(group_candidate["id"]))
    summary = split["summary"]

    assert split["train_count"] > 0
    assert split["valid_count"] > 0
    assert summary["split_type"] == "group"
    assert summary["group_column"] == "customer_id"
    assert summary["group_overlap_count"] == 0
    assert summary["group_leakage_check_passed"] is True
