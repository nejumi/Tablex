from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import Base, Job
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import create_job
from tabular_harness.worker.daemon import LocalWorkerDaemon


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
                    artifact_id = output["agent_chat_turn_artifact_id"]
                    assert artifact_id
                    break
            time.sleep(0.05)
        else:
            raise AssertionError(f"local worker daemon did not finish queued chat job; last status={status}")

        history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 1
        answered = history[0]
        assert answered["job_id"] == job_id
        assert answered["artifact_id"] == artifact_id
        assert not answered["artifact_id"].startswith("job_pending_")
        assert answered["assistant_message"] != "応答を準備しています。"
        assert answered["response_composer"]["status"] not in {"queued", "running"}


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
                job_type="generate_data_understanding_notebook",
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


def test_local_worker_daemon_periodically_retries_agent_session_supervisor_recovery(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    calls: list[str] = []

    def fake_supervisor_recovery(*args: object, **kwargs: object) -> list[threading.Thread]:
        del args
        calls.append(str(kwargs.get("lease_owner_id")))
        return []

    daemon = LocalWorkerDaemon(
        session_factory,
        store,
        worker_id="recovery-daemon",
        interval_seconds=0.02,
        max_jobs_per_wake=1,
        agent_session_supervisor_interval_seconds=0.05,
        agent_session_supervisor_runner=fake_supervisor_recovery,
    )
    daemon.start()
    try:
        deadline = time.monotonic() + 1.0
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(calls) >= 2
        assert all(call.startswith("worker-daemon:recovery-daemon:thread:") for call in calls)
    finally:
        daemon.stop()


def test_api_lifespan_can_disable_agent_session_supervisor(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_supervisor_recovery(*args: object, **kwargs: object) -> list[threading.Thread]:
        del args, kwargs
        calls.append("called")
        return []

    monkeypatch.setattr(
        "tabular_harness.main.start_active_main_session_supervisors",
        fake_supervisor_recovery,
    )
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        api_agent_session_supervisor_enabled=False,
        local_worker_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        config = client.get("/api/config").json()
        assert config["api_agent_session_supervisor_enabled"] is False
        assert config["local_worker_enabled"] is False

    assert calls == []
