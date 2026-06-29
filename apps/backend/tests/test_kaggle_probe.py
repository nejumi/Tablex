from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.main import create_app
from tabular_harness.services.kaggle_probe import (
    build_kaggle_auth_candidates,
    probe_kaggle_benchmark_access,
)


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
                hdrs=None,
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

    monkeypatch.setattr("tabular_harness.api.routes.probe_kaggle_benchmark_access", fake_probe)
    response = client.post("/api/benchmarks/kaggle_home_credit_default_risk/kaggle/probe")
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "succeeded"
    assert job["policy"]["secret_access"] == "harness_process_only"
    assert job["policy"]["agent_runner_access"] is False
    assert job["output"]["probe_status"] == "ok"
    assert job["output"]["kaggle_probe_artifact_id"]

    preview_response = client.get(f"/api/artifacts/{job['output']['kaggle_probe_artifact_id']}/preview")
    assert preview_response.status_code == 200
    preview = preview_response.json()["preview"]
    assert "kaggle_credential_probe.v1" in preview
    assert "Authorization" not in preview
