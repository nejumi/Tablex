from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import tabular_harness.services.marimo_sessions as marimo_sessions
from tabular_harness.core.config import Settings
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Artifact
from tabular_harness.services.jobs import JOB_TYPES
from tabular_harness.worker.jobs import concrete_handlers


class FakeMarimoProcess:
    instances: list[FakeMarimoProcess] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        FakeMarimoProcess.instances.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        del timeout
        return self.returncode


@pytest.fixture(autouse=True)
def clear_native_marimo_sessions() -> None:
    with marimo_sessions._lock:
        marimo_sessions._sessions_by_id.clear()
        marimo_sessions._session_id_by_artifact_id.clear()
    FakeMarimoProcess.instances.clear()


def test_native_marimo_session_restarts_when_notebook_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(marimo_sessions, "marimo_available", lambda: True)
    monkeypatch.setattr(marimo_sessions.subprocess, "Popen", FakeMarimoProcess)
    artifact, source_path = notebook_artifact(tmp_path, artifact_id="art_one", source="print('one')\n")
    settings = marimo_settings(tmp_path)

    first = marimo_sessions.start_or_get_native_marimo_session(artifact=artifact, settings=settings)
    source_path.write_text("print('two')\n", encoding="utf-8")
    second = marimo_sessions.start_or_get_native_marimo_session(artifact=artifact, settings=settings)

    assert second.id != first.id
    assert first.process.terminated is True
    assert second.process.poll() is None
    assert second.source_hash != first.source_hash
    assert marimo_sessions._session_id_by_artifact_id[artifact.id] == second.id


def test_native_marimo_session_limit_terminates_least_recently_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(marimo_sessions, "marimo_available", lambda: True)
    monkeypatch.setattr(marimo_sessions.subprocess, "Popen", FakeMarimoProcess)
    settings = marimo_settings(tmp_path, max_sessions=2)
    now = datetime.now(timezone.utc)
    first_artifact, _ = notebook_artifact(tmp_path, artifact_id="art_one", source="print('one')\n")
    second_artifact, _ = notebook_artifact(tmp_path, artifact_id="art_two", source="print('two')\n")
    third_artifact, _ = notebook_artifact(tmp_path, artifact_id="art_three", source="print('three')\n")

    first = marimo_sessions.start_or_get_native_marimo_session(artifact=first_artifact, settings=settings)
    first.last_accessed_at = now - timedelta(minutes=10)
    second = marimo_sessions.start_or_get_native_marimo_session(artifact=second_artifact, settings=settings)
    second.last_accessed_at = now
    third = marimo_sessions.start_or_get_native_marimo_session(artifact=third_artifact, settings=settings)

    assert first.process.terminated is True
    assert second.id in marimo_sessions._sessions_by_id
    assert third.id in marimo_sessions._sessions_by_id
    assert len(marimo_sessions._sessions_by_id) == 2


def test_prewarm_native_marimo_session_job_is_registered() -> None:
    handlers = concrete_handlers()

    assert "prewarm_native_marimo_session" in JOB_TYPES
    assert "prewarm_native_marimo_session" in handlers


def notebook_artifact(tmp_path: Path, *, artifact_id: str, source: str) -> tuple[Artifact, Path]:
    source_path = tmp_path / f"{artifact_id}.py"
    source_path.write_text(source, encoding="utf-8")
    artifact = Artifact(
        id=artifact_id,
        project_id="p_test",
        asset_type="analysis_notebook",
        name=artifact_id,
        version=1,
        uri=str(tmp_path),
        content_hash=f"hash_{artifact_id}",
        metadata_json=dumps_json({"primary_path": str(source_path)}),
    )
    return artifact, source_path


def marimo_settings(tmp_path: Path, *, max_sessions: int = 4) -> Settings:
    return Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url="sqlite://",
        artifact_root=tmp_path / "artifacts",
        max_upload_bytes=1024,
        cors_origins=(),
        marimo_max_sessions=max_sessions,
    )
