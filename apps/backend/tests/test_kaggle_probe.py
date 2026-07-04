from __future__ import annotations

import json
import urllib.error
import urllib.request
import zipfile
from email.message import Message
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import Job
from tabular_harness.services.kaggle_probe import (
    build_kaggle_auth_candidates,
    download_kaggle_selected_files,
    fetch_kaggle_competition_inventory,
    probe_kaggle_benchmark_access,
)
from tabular_harness.worker.jobs import create_default_worker


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, max_bytes: int = -1) -> bytes:
        if max_bytes < 0:
            return self.body
        return self.body[:max_bytes]

    def close(self) -> None:
        return None


class StreamingResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.offset = 0

    def read(self, max_bytes: int = -1) -> bytes:
        if self.offset >= len(self.body):
            return b""
        if max_bytes < 0:
            max_bytes = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + max_bytes]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


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


def home_credit_benchmark() -> dict[str, Any]:
    return {
        "id": "kaggle_home_credit_default_risk",
        "name": "Home Credit Default Risk",
        "source_kind": "kaggle_competition",
        "source_url": "https://www.kaggle.com/competitions/home-credit-default-risk",
        "competition_slug": "home-credit-default-risk",
    }


def test_kaggle_auth_candidates_do_not_expose_values() -> None:
    candidates, state = build_kaggle_auth_candidates(
        env={"KAGGLE_USERNAME": "test-user", "KAGGLE_API_TOKEN": "secret-token"},
        env_files=(),
    )

    assert candidates
    assert candidates[0].credential_source == "kaggle_username_with_api_token"
    assert candidates[0].auth_scheme == "basic"
    assert state["available"] is True
    assert state["username_available"] is True
    serialized = json.dumps({"state": state, "candidate": candidates[0].safe_summary()})
    assert "secret-token" not in serialized
    assert "Authorization" not in serialized


def test_kaggle_probe_payload_is_secret_free_on_success() -> None:
    seen_headers: list[str] = []

    def fake_opener(request: urllib.request.Request, timeout_seconds: float) -> FakeResponse:
        assert timeout_seconds == 15.0
        seen_headers.append(str(request.headers.get("Authorization")))
        return FakeResponse(b'[{"name":"application_train.csv"},{"name":"bureau.csv"}]')

    payload = probe_kaggle_benchmark_access(
        home_credit_benchmark(),
        env={"KAGGLE_USERNAME": "test-user", "KAGGLE_API_TOKEN": "secret-token"},
        env_files=(),
        opener=fake_opener,
    )

    assert payload["probe"]["status"] == "ok"
    assert payload["probe"]["file_count"] == 2
    assert payload["credential_status"]["credential_sources"] == ["kaggle_username_with_api_token", "kaggle_api_token_bearer"]
    assert seen_headers and seen_headers[0].startswith("Basic ")
    serialized = json.dumps(payload)
    assert "secret-token" not in serialized
    assert seen_headers[0] not in serialized
    assert payload["safety"]["agent_runner_access"] is False


def test_kaggle_probe_tries_next_candidate_after_unauthorized() -> None:
    calls = 0

    def fake_opener(request: urllib.request.Request, timeout_seconds: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=401,
                msg="Unauthorized",
                hdrs=Message(),
                fp=None,
            )
        return FakeResponse(b"[]")

    payload = probe_kaggle_benchmark_access(
        home_credit_benchmark(),
        env={"KAGGLE_USERNAME": "test-user", "KAGGLE_API_TOKEN": "secret-token"},
        env_files=(),
        opener=fake_opener,
    )

    assert payload["probe"]["status"] == "ok"
    assert payload["probe"]["attempt_count"] == 2
    assert payload["probe"]["attempts"][0]["status"] == "unauthorized"


def test_kaggle_inventory_maps_catalog_roles_without_secrets() -> None:
    def fake_opener(request: urllib.request.Request, timeout_seconds: float) -> FakeResponse:
        return FakeResponse(
            json.dumps(
                [
                    {"name": "application_train.csv", "totalBytes": 123},
                    {"name": "bureau.csv", "totalBytes": 456},
                    {"name": "application_test.csv", "totalBytes": 789},
                    {"name": "unconfigured.csv", "totalBytes": 10},
                ]
            ).encode()
        )

    benchmark = {
        **home_credit_benchmark(),
        "required_files": [{"path": "application_train.csv", "role": "primary_table"}],
        "recommended_files": [
            {"path": "bureau.csv", "role": "supporting_table"},
            {"path": "application_test.csv", "role": "holdout_table"},
        ],
    }
    payload = fetch_kaggle_competition_inventory(
        benchmark,
        env={"KAGGLE_USERNAME": "test-user", "KAGGLE_API_TOKEN": "secret-token"},
        env_files=(),
        opener=fake_opener,
    )

    inventory = payload["inventory"]
    assert inventory["status"] == "ok"
    assert inventory["file_count"] == 4
    assert inventory["required_missing_count"] == 0
    assert inventory["recommended_present_count"] == 1
    assert inventory["holdout_file_count"] == 1
    roles = {item["name"]: item["role"] for item in inventory["files"]}
    assert roles["application_train.csv"] == "primary_table"
    assert roles["bureau.csv"] == "supporting_table"
    assert roles["application_test.csv"] == "holdout_table"
    assert roles["unconfigured.csv"] == "extra"
    serialized = json.dumps(payload)
    assert "secret-token" not in serialized
    assert "Authorization" not in serialized


def test_kaggle_selective_download_required_file(tmp_path: Path) -> None:
    file_bytes = b"id,target\n1,0\n2,1\n"
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("application_train.csv", file_bytes)
    archive_bytes = archive_buffer.getvalue()

    def fake_opener(request: urllib.request.Request, timeout_seconds: float) -> FakeResponse | StreamingResponse:
        if "/competitions/data/list/" in request.full_url:
            return FakeResponse(
                json.dumps(
                    [
                        {"name": "application_train.csv", "totalBytes": len(archive_bytes)},
                        {"name": "bureau.csv", "totalBytes": 456},
                    ]
                ).encode()
            )
        assert "/competitions/data/download/" in request.full_url
        return StreamingResponse(archive_bytes)

    benchmark = {
        **home_credit_benchmark(),
        "required_files": [{"path": "application_train.csv", "role": "primary_table"}],
        "recommended_files": [{"path": "bureau.csv", "role": "supporting_table"}],
    }
    payload = download_kaggle_selected_files(
        benchmark,
        root=tmp_path / "benchmarks" / "home_credit",
        env={"KAGGLE_USERNAME": "test-user", "KAGGLE_API_TOKEN": "secret-token"},
        env_files=(),
        opener=fake_opener,
    )

    download = payload["download"]
    assert download["status"] == "completed"
    assert download["downloaded_count"] == 1
    assert download["skipped_count"] == 0
    downloaded = download["downloaded_files"][0]
    assert downloaded["name"] == "application_train.csv"
    assert downloaded["sha256"] == sha256(file_bytes).hexdigest()
    assert downloaded["extracted_from_archive"] is True
    assert downloaded["archive_size_bytes"] == len(archive_bytes)
    assert (tmp_path / "benchmarks" / "home_credit" / "application_train.csv").read_bytes() == file_bytes
    serialized = json.dumps(payload)
    assert "secret-token" not in serialized
    assert "Authorization" not in serialized


def test_kaggle_probe_endpoint_stores_safe_artifact(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    def fake_probe(benchmark: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "kaggle_credential_probe.v1",
            "benchmark_id": benchmark["id"],
            "benchmark_name": benchmark["name"],
            "source_kind": benchmark["source_kind"],
            "competition_slug": benchmark["competition_slug"],
            "checked_at": "2026-06-29T00:00:00+00:00",
            "credential_status": {
                "available": True,
                "candidate_count": 1,
                "credential_sources": ["kaggle_username_with_api_token"],
                "auth_schemes": ["basic"],
                "username_available": True,
                "missing": [],
                "warnings": [],
                "values_exposed": False,
            },
            "request": {
                "endpoint_kind": "competition_data_list",
                "url_host": "www.kaggle.com",
                "network_accessed": True,
            },
            "probe": {
                "status": "ok",
                "http_status": 200,
                "can_access_competition_files": True,
                "file_count": 8,
                "attempt_count": 1,
                "attempts": [
                    {
                        "credential_source": "kaggle_username_with_api_token",
                        "auth_scheme": "basic",
                        "username_available": True,
                        "status": "ok",
                        "http_status": 200,
                        "file_count": 8,
                    }
                ],
            },
            "safety": {
                "secret_value_logged": False,
                "secret_value_artifacted": False,
                "connector_credentials_materialized": False,
                "agent_runner_access": False,
                "agent_task_contract_access": False,
            },
            "next_actions": ["Competition file access is available to the harness process."],
        }

    monkeypatch.setattr("tabular_harness.worker.jobs.probe_kaggle_benchmark_access", fake_probe)
    response = client.post("/api/benchmarks/kaggle_home_credit_default_risk/kaggle/probe")
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["policy"]["secret_access"] == "harness_process_only"
    assert job["policy"]["agent_runner_access"] is False
    assert job["policy"]["execution"] == "queued_worker"
    output = run_queued_job(client, job["id"])
    assert output["probe_status"] == "ok"
    assert output["kaggle_probe_artifact_id"]

    preview_response = client.get(f"/api/artifacts/{output['kaggle_probe_artifact_id']}/preview")
    assert preview_response.status_code == 200
    preview = preview_response.json()["preview"]
    assert "kaggle_credential_probe.v1" in preview
    assert "Authorization" not in preview


def test_kaggle_inventory_endpoint_stores_safe_artifact(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    def fake_inventory(benchmark: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "kaggle_competition_file_inventory.v1",
            "benchmark_id": benchmark["id"],
            "benchmark_name": benchmark["name"],
            "source_kind": benchmark["source_kind"],
            "competition_slug": benchmark["competition_slug"],
            "checked_at": "2026-06-29T00:00:00+00:00",
            "credential_status": {
                "available": True,
                "candidate_count": 1,
                "credential_sources": ["kaggle_api_token_bearer"],
                "auth_schemes": ["bearer"],
                "username_available": True,
                "missing": [],
                "warnings": [],
                "values_exposed": False,
            },
            "request": {
                "endpoint_kind": "competition_data_list",
                "url_host": "www.kaggle.com",
                "network_accessed": True,
            },
            "inventory": {
                "status": "ok",
                "http_status": 200,
                "file_count": 3,
                "total_size_bytes": 1368,
                "files": [
                    {
                        "name": "application_train.csv",
                        "size_bytes": 123,
                        "requirement": "required",
                        "role": "primary_table",
                        "configured_expected": True,
                    }
                ],
                "required_present_count": 1,
                "required_missing_count": 0,
                "recommended_present_count": 1,
                "holdout_file_count": 1,
                "missing_required": [],
                "attempt_count": 1,
                "attempts": [],
            },
            "safety": {
                "secret_value_logged": False,
                "secret_value_artifacted": False,
                "connector_credentials_materialized": False,
                "agent_runner_access": False,
                "agent_task_contract_access": False,
            },
            "next_actions": ["Use the inventory artifact to choose files before download."],
        }

    monkeypatch.setattr("tabular_harness.worker.jobs.fetch_kaggle_competition_inventory", fake_inventory)
    response = client.post("/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory")
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["policy"]["secret_access"] == "harness_process_only"
    assert job["policy"]["execution"] == "queued_worker"
    output = run_queued_job(client, job["id"])
    assert output["inventory_status"] == "ok"
    assert output["file_count"] == 3
    assert output["required_missing_count"] == 0
    assert output["kaggle_inventory_artifact_id"]

    latest_response = client.get("/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == output["kaggle_inventory_artifact_id"]


def test_kaggle_download_endpoint_stores_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    def fake_download(benchmark: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        root = kwargs["root"]
        target = root / "application_train.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("id,target\n1,0\n", encoding="utf-8")
        return {
            "schema_version": "kaggle_selective_download_manifest.v1",
            "benchmark_id": benchmark["id"],
            "benchmark_name": benchmark["name"],
            "source_kind": benchmark["source_kind"],
            "competition_slug": benchmark["competition_slug"],
            "checked_at": "2026-06-29T00:00:00+00:00",
            "root_path": str(root),
            "request_policy": {
                "selected_files": [],
                "include_required": True,
                "include_recommended": False,
                "include_holdout": False,
                "overwrite": False,
                "max_total_bytes": 500 * 1024 * 1024,
            },
            "credential_status": {
                "available": True,
                "candidate_count": 1,
                "credential_sources": ["kaggle_username_with_api_token"],
                "auth_schemes": ["basic"],
                "username_available": True,
                "missing": [],
                "warnings": [],
                "values_exposed": False,
            },
            "request": {
                "endpoint_kind": "competition_data_download",
                "url_host": "www.kaggle.com",
                "network_accessed": True,
            },
            "download": {
                "status": "completed",
                "planned_file_count": 1,
                "downloaded_count": 1,
                "skipped_count": 0,
                "downloaded_bytes": target.stat().st_size,
                "downloaded_files": [
                    {
                        "name": "application_train.csv",
                        "relative_path": "application_train.csv",
                        "size_bytes": target.stat().st_size,
                        "sha256": "fake",
                        "requirement": "required",
                        "role": "primary_table",
                    }
                ],
                "skipped_files": [],
                "attempts": [],
            },
            "safety": {
                "secret_value_logged": False,
                "secret_value_artifacted": False,
                "connector_credentials_materialized": False,
                "agent_runner_access": False,
                "agent_task_contract_access": False,
            },
            "next_actions": ["Run benchmark local-status or import from the resolved benchmark root."],
        }

    monkeypatch.setattr("tabular_harness.worker.jobs.download_kaggle_selected_files", fake_download)
    response = client.post(
        "/api/benchmarks/kaggle_home_credit_default_risk/kaggle/download",
        json={"include_required": True, "overwrite": False},
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["policy"]["secret_access"] == "harness_process_only"
    assert job["policy"]["execution"] == "queued_worker"
    output = run_queued_job(client, job["id"])
    assert output["download_status"] == "completed"
    assert output["downloaded_count"] == 1
    assert output["local_ready"] is True
    assert output["can_import_now"] is True
    assert output["kaggle_download_manifest_artifact_id"]
