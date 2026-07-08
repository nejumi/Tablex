from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import select

from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import AgentSession, AgentTranscriptEvent, Job, Project
from tabular_harness.services.agent_inbox import list_inbox_entries


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        api_agent_session_supervisor_enabled=False,
    )
    return TestClient(create_app(settings))


def create_project(client: TestClient) -> str:
    response = client.post("/api/projects", json={"name": "Console demo"})
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def test_console_message_delivers_to_completed_main_session_and_wakes(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "IDLE"
        session = AgentSession(
            id="ags_console_completed",
            project_id=project_id,
            session_type="main_autonomous",
            status="completed",
            autonomy_mode="full_auto",
            goal_text="Continue when the user provides input.",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.commit()

    response = client.post(
        f"/api/projects/{project_id}/agent-session/console-message",
        json={"message": "確認して結果を返してください", "locale": "ja-JP"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "agent_console_message.v1"
    assert body["delivered"] is True
    assert body["woke_session"] is True
    assert body["status"] == "between_turns"
    with app.state.session_factory() as db:
        session = db.get(AgentSession, "ags_console_completed")
        assert session is not None
        assert session.status == "between_turns"
        project = db.get(Project, project_id)
        assert project is not None
        assert project.current_phase == "AUTONOMOUS_LOOP"
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.source == "user",
                AgentTranscriptEvent.event_type == "user_instruction",
            )
        )
        assert event is not None
        payload = loads_json(event.payload_json, {})
        assert payload["channel"] == "console"
        assert payload["delivery"] == "direct_console_to_main_agent_session"
    inbox_entries = list_inbox_entries(workspace)
    user_entries = [entry for entry in inbox_entries if entry.get("kind") == "user_instruction"]
    assert user_entries
    assert user_entries[0]["payload"]["channel"] == "console"


def test_console_message_does_not_wake_stopped_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        session = AgentSession(
            id="ags_console_stopped",
            project_id=project_id,
            session_type="main_autonomous",
            status="stopped",
            autonomy_mode="full_auto",
            goal_text="Stopped by user.",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.commit()

    response = client.post(
        f"/api/projects/{project_id}/agent-session/console-message",
        json={"message": "再開して", "locale": "ja-JP"},
    )
    assert response.status_code == 409
    with app.state.session_factory() as db:
        session = db.get(AgentSession, "ags_console_stopped")
        assert session is not None
        assert session.status == "stopped"
        events = list(db.scalars(select(AgentTranscriptEvent).where(AgentTranscriptEvent.session_id == session.id)))
        assert events == []
    assert list_inbox_entries(workspace) == []


def test_agent_chat_wakes_completed_main_session_instead_of_composing_locally(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "IDLE"
        session = AgentSession(
            id="ags_chat_completed",
            project_id=project_id,
            session_type="main_autonomous",
            status="completed",
            autonomy_mode="full_auto",
            goal_text="Continue when the user provides input.",
            workspace_path=str(workspace),
        )
        db.add(session)
        db.commit()

    response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "暫定評価の分割方法を確認して報告してください", "locale": "ja-JP"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_composer"]["mode"] == "main_codex_session"
    assert body["response_composer"]["status"] == "waiting_for_agent"
    assert body["response_brief"]["delivery"] == "workspace_inbox_and_transcript"
    with app.state.session_factory() as db:
        session = db.get(AgentSession, "ags_chat_completed")
        assert session is not None
        assert session.status == "between_turns"
        project = db.get(Project, project_id)
        assert project is not None
        assert project.current_phase == "AUTONOMOUS_LOOP"
        job = db.get(Job, body["job"]["id"])
        assert job is not None
        assert job.status == "waiting_for_agent"
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.source == "user",
                AgentTranscriptEvent.event_type == "user_instruction",
            )
        )
        assert event is not None
    inbox_entries = list_inbox_entries(workspace)
    assert [entry for entry in inbox_entries if entry.get("kind") == "user_instruction"]


def test_agent_chat_starts_missing_full_auto_main_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_id = create_project(client)
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        db.commit()

    response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "評価設定を提案してください", "locale": "ja-JP"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_composer"]["mode"] == "main_codex_session"
    assert body["response_composer"]["status"] == "waiting_for_agent"
    with app.state.session_factory() as db:
        session = db.scalar(select(AgentSession).where(AgentSession.project_id == project_id))
        assert session is not None
        assert session.status in {"starting", "between_turns"}
        event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.source == "user",
                AgentTranscriptEvent.event_type == "user_instruction",
            )
        )
        assert event is not None
        assert Path(session.workspace_path or "").exists()
