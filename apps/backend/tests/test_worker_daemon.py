from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from tabular_harness.core.config import Settings
from tabular_harness.main import create_app
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Job
from tabular_harness.services.jobs import create_job


def test_local_worker_daemon_processes_concrete_chat_jobs_from_lifespan(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        local_worker_enabled=True,
        local_worker_interval_seconds=0.1,
        local_worker_max_jobs_per_wake=1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        app_any = cast(Any, app)
        project_response = client.post("/api/projects", json={"name": "Daemon chat"})
        assert project_response.status_code == 200
        project_id = project_response.json()["id"]
        chat_response = client.post(
            f"/api/projects/{project_id}/agent-chat",
            json={"message": "状況を説明してください", "locale": "ja-JP"},
        )
        assert chat_response.status_code == 200
        job_id = chat_response.json()["job"]["id"]

        deadline = time.monotonic() + 5
        status = None
        while time.monotonic() < deadline:
            with app_any.state.session_factory() as db:
                current = db.get(Job, job_id)
                status = current.status if current is not None else None
                if status == "succeeded":
                    assert current is not None
                    assert current.locked_by is None
                    output = loads_json(current.output_json, {})
                    assert output["agent_chat_turn_artifact_id"]
                    return
            time.sleep(0.05)

    raise AssertionError(f"local worker daemon did not finish queued chat job; last status={status}")


def test_local_worker_daemon_does_not_succeed_stub_only_jobs(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        local_worker_enabled=True,
        local_worker_interval_seconds=0.1,
        local_worker_max_jobs_per_wake=1,
    )
    app = create_app(settings)

    with TestClient(app):
        app_any = cast(Any, app)
        with app_any.state.session_factory() as db:
            job = create_job(
                db,
                job_type="profile_dataset",
                project_id=None,
                input_payload={"source": "daemon-test"},
            )
            job_id = job.id
            db.commit()

        time.sleep(0.35)
        with app_any.state.session_factory() as db:
            current = db.get(Job, job_id)
            assert current is not None
            assert current.status == "queued"
            assert current.locked_by is None
