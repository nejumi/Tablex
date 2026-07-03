from __future__ import annotations

import json
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from tabular_harness.api.routes import (
    compact_agent_chat_history_turns,
    format_elapsed_seconds,
    heartbeat_phrase_for_locale,
    matching_main_session_update_for_chat_job,
    seconds_since_timestamp,
    visible_activity_workers,
)
from tabular_harness.core.config import Settings
from tabular_harness.core.json import loads_json
from tabular_harness.main import create_app
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    Job,
    Project,
    Question,
    utc_now,
)
from tabular_harness.schemas import AgentResult
from tabular_harness.services.agent_sessions import (
    append_runner_stream_to_workspace,
    append_session_event,
    latest_user_instruction_path,
    maybe_register_chat_update_from_workspace_output,
    progress_request_path,
    research_plan_locale_request_path,
    user_instructions_inbox_path,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import acquire_next_job, create_job, reap_stale_running_jobs
from tabular_harness.worker.jobs import agent_chat_turn_handler, continue_autonomous_session_handler
from tabular_harness.worker.runner import SyncWorker


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


def run_queued_agent_chat_turn(client: TestClient, job_id: str) -> dict[str, Any]:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        worker = SyncWorker(handlers={"agent_chat_turn": agent_chat_turn_handler}, store=app.state.artifact_store)
        completed = worker.run_job(db, job)
        assert completed.status == "succeeded", completed.error_message
        return loads_json(completed.output_json, {})


def test_sqlite_engine_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
    )
    app = create_app(settings)

    with app.state.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000


def test_visible_activity_workers_hide_old_terminal_cards() -> None:
    now = utc_now()
    old_time = (now - timedelta(seconds=60)).isoformat()
    recent_time = (now - timedelta(seconds=4)).isoformat()

    workers = visible_activity_workers(
        [
            {"worker_id": "old", "status": "succeeded", "updated_at": old_time, "active": False},
            {"worker_id": "recent", "status": "failed", "updated_at": recent_time, "active": False},
            {"worker_id": "old-queued", "status": "queued", "updated_at": old_time, "active": False},
            {"worker_id": "queued", "status": "queued", "updated_at": recent_time, "active": True},
            {"worker_id": "session", "status": "running", "updated_at": old_time, "active": True},
        ],
        now=now,
    )

    assert [worker["worker_id"] for worker in workers] == ["recent", "queued", "session"]


def test_agent_activity_elapsed_output_helpers() -> None:
    now = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)

    assert seconds_since_timestamp(now - timedelta(seconds=42), now=now) == 42
    assert seconds_since_timestamp(None, now=now) is None
    assert format_elapsed_seconds(42) == "42s"
    assert format_elapsed_seconds(125) == "2m"
    assert format_elapsed_seconds(3660) == "1h 1m"
    assert heartbeat_phrase_for_locale(75, locale="ja-JP") == " 最終出力は1分前です。"
    assert heartbeat_phrase_for_locale(75, locale="Japanese") == " 最終出力は1分前です。"
    assert heartbeat_phrase_for_locale(75, locale="en-US") == " Last observed output was 1m ago."


def test_agent_chat_history_compaction_preserves_user_turns() -> None:
    turns: list[dict[str, Any]] = []
    for index in range(40):
        turns.append(
            {
                "created_at": f"2026-07-03T00:{index:02d}:00",
                "user_message": "",
                "assistant_message": f"progress {index}",
                "intent": {"type": "autonomous_agent_progress_report"},
            }
        )
    turns.append(
        {
            "created_at": "2026-07-03T00:10:30",
            "user_message": "状況を説明してください",
            "assistant_message": "説明します。",
            "intent": {"type": "agent_conversation"},
        }
    )

    compacted = compact_agent_chat_history_turns(turns, max_turns=20, max_autonomous_progress_turns=5)

    progress_turns = [turn for turn in compacted if turn["intent"]["type"] == "autonomous_agent_progress_report"]
    assert len(progress_turns) == 5
    assert any(turn["user_message"] == "状況を説明してください" for turn in compacted)
    assert compacted[-1]["assistant_message"] == "progress 39"


def test_project_autonomy_mode_persists(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Mission Control"})
    assert project_response.status_code == 200
    project = project_response.json()
    assert project["autonomy_mode"] == "approval_based"

    update_response = client.patch(f"/api/projects/{project['id']}", json={"autonomy_mode": "full_auto"})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["autonomy_mode"] == "full_auto"

    read_response = client.get(f"/api/projects/{project['id']}")
    assert read_response.status_code == 200
    assert read_response.json()["autonomy_mode"] == "full_auto"


def test_project_artifacts_support_limit_and_asset_type_filters(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Artifact filters"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)

    with app.state.session_factory() as db:
        for index in range(5):
            store_json_artifact(
                db,
                app.state.artifact_store,
                project_id=project_id,
                asset_type="agent_session_report" if index % 2 else "analysis_notebook",
                name=f"artifact_filter_{index}",
                filename="artifact.json",
                payload={"index": index},
                metadata={"index": index},
            )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="versioned_report",
            filename="artifact.json",
            payload={"version": 1},
            metadata={"version": 1},
        )
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="versioned_report",
            filename="artifact.json",
            payload={"version": 2},
            metadata={"version": 2},
        )
        db.commit()

    limited_response = client.get(f"/api/projects/{project_id}/artifacts?limit=2")
    assert limited_response.status_code == 200
    assert len(limited_response.json()) == 2

    filtered_response = client.get(f"/api/projects/{project_id}/artifacts?asset_type=analysis_notebook")
    assert filtered_response.status_code == 200
    assert {item["asset_type"] for item in filtered_response.json()} == {"analysis_notebook"}

    latest_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert latest_response.status_code == 200
    latest_versioned = [item for item in latest_response.json() if item["name"] == "versioned_report"]
    assert len(latest_versioned) == 1
    assert latest_versioned[0]["version"] == 2

    all_versions_response = client.get(f"/api/projects/{project_id}/artifacts?latest_only=false")
    assert all_versions_response.status_code == 200
    all_versioned = [item for item in all_versions_response.json() if item["name"] == "versioned_report"]
    assert [item["version"] for item in all_versioned] == [2, 1]

    overview_response = client.get(f"/api/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview_counts = overview_response.json()["counts"]
    assert overview_counts["artifacts"] == 6
    assert overview_counts["artifact_versions"] == 7


def test_autonomy_mode_change_is_persisted_in_agent_chat_history(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Mode history"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    update_response = client.patch(
        f"/api/projects/{project_id}",
        json={"autonomy_mode": "full_auto", "locale": "Japanese"},
    )
    assert update_response.status_code == 200, update_response.text

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[-1]["intent"]["type"] == "autonomy_mode_change"
    assert history[-1]["user_message"] == "フルオート"
    assert "フルオートに切り替えました" in history[-1]["assistant_message"]

    update_response = client.patch(
        f"/api/projects/{project_id}",
        json={"autonomy_mode": "approval_based", "locale": "日本語"},
    )
    assert update_response.status_code == 200, update_response.text

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history[-1]["intent"]["type"] == "autonomy_mode_change"
    assert history[-1]["user_message"] == "承認ベース"
    assert "承認ベースに切り替えました" in history[-1]["assistant_message"]


def test_health_aliases_are_public_when_auth_is_enabled(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        auth_enabled=True,
    )
    client = TestClient(create_app(settings))

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/projects").status_code == 401


def test_password_auth_protects_api_and_persists_user_settings(tmp_path: Path) -> None:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
        auth_enabled=True,
    )
    client = TestClient(create_app(settings))

    status_response = client.get("/api/auth/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["auth_enabled"] is True
    assert status["authenticated"] is False
    assert status["bootstrap_required"] is True

    protected_response = client.get("/api/projects")
    assert protected_response.status_code == 401

    weak_password_response = client.post(
        "/api/auth/bootstrap",
        json={"email": "weak@example.com", "password": "lowercaseonly", "display_name": "Weak"},
    )
    assert weak_password_response.status_code == 400
    assert "uppercase" in weak_password_response.json()["detail"]

    bootstrap_response = client.post(
        "/api/auth/bootstrap",
        json={
            "email": "owner@example.com",
            "password": "CorrectHorse1!",
            "display_name": "Owner",
        },
    )
    assert bootstrap_response.status_code == 200, bootstrap_response.text
    assert bootstrap_response.json()["authenticated"] is True
    assert bootstrap_response.json()["user"]["is_admin"] is True
    owner_user_id = bootstrap_response.json()["user"]["id"]

    project_response = client.post("/api/projects", json={"name": "Authed project"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]
    assert project_response.json()["created_by"] == owner_user_id

    project_refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert project_refs_response.status_code == 200
    equipped_skill_names = {
        reference["asset"]["name"]
        for reference in project_refs_response.json()
        if reference["asset"] and reference["relation_type"] == "equipped_for_agent_context"
    }
    assert "tablex_grandmaster_eda" in equipped_skill_names

    settings_response = client.patch(
        "/api/auth/me/settings",
        json={
            "settings": {
                "locale": "ja-JP",
                "displayTheme": "dark",
                "userAvatarDataUrl": "data:image/svg+xml;base64,PHN2Zy8+",
                "agentModel": "gpt-5.5-xhigh",
                "utilityModel": "gpt-5-mini",
            }
        },
    )
    assert settings_response.status_code == 200, settings_response.text
    saved_settings = settings_response.json()["settings"]
    assert saved_settings["locale"] == "ja-JP"
    assert saved_settings["displayTheme"] == "dark"
    assert saved_settings["userAvatarDataUrl"].startswith("data:image/")

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert client.get("/api/projects").status_code == 401

    bad_login_response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "wrong password"},
    )
    assert bad_login_response.status_code == 401

    login_response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "CorrectHorse1!"},
    )
    assert login_response.status_code == 200, login_response.text
    assert login_response.json()["user"]["settings"]["locale"] == "ja-JP"
    assert client.get("/api/projects").status_code == 200


def test_full_auto_start_creates_main_agent_session_without_dataset_even_with_legacy_runner_mode(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Autonomous no data"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    start_response = client.post(f"/api/projects/{project_id}/autonomy/start", json={"runner_mode": "harness_only"})
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["job_type"] == "start_autonomous_loop"
    assert queued_job["status"] == "succeeded"
    assert queued_job["input"]["runner_mode"] == "codex_cli_if_available"
    assert queued_job["input"]["requested_runner_mode"] == "harness_only"
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    assert queued_job["output"]["agent_session_id"]

    job_response = client.get(f"/api/jobs/{queued_job['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "succeeded"
    assert job["output"]["schema_version"] == "agent_session_start.v1"
    assert "Full Auto" in job["output"]["assistant_message"]
    assert job["output"]["worker_events"]

    session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["id"] == queued_job["output"]["agent_session_id"]
    assert session["session_type"] == "main_autonomous"

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    assert project_read_response.json()["autonomy_mode"] == "full_auto"
    assert project_read_response.json()["current_phase"] == "AUTONOMOUS_LOOP"

    stop_response = client.post(f"/api/projects/{project_id}/autonomy/stop")
    assert stop_response.status_code == 200, stop_response.text
    stop_job = stop_response.json()
    assert stop_job["job_type"] == "stop_autonomous_loop"
    assert stop_job["status"] == "succeeded"
    assert stop_job["output"]["schema_version"] == "autonomous_loop_stop.v1"
    assert stop_job["output"]["worker_events"][0]["status"] == "cancelled"

    stopped_project_response = client.get(f"/api/projects/{project_id}")
    assert stopped_project_response.status_code == 200
    assert stopped_project_response.json()["autonomy_mode"] == "full_auto"
    assert stopped_project_response.json()["current_phase"] == "IDLE"

    restart_response = client.post(f"/api/projects/{project_id}/autonomy/start", json={"runner_mode": "harness_only"})
    assert restart_response.status_code == 200, restart_response.text
    restart_job = restart_response.json()
    assert restart_job["output"]["schema_version"] == "agent_session_start.v1"
    assert restart_job["output"]["agent_session_id"] == queued_job["output"]["agent_session_id"]
    assert restart_job["output"]["status"] == "resumed"
    assert "resumed" in restart_job["output"]["assistant_message"]

    restarted_session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert restarted_session_response.status_code == 200
    restarted_session = restarted_session_response.json()
    assert restarted_session["id"] == queued_job["output"]["agent_session_id"]
    assert restarted_session["status"] in {"between_turns", "running", "starting"}

    transcript_response = client.get(f"/api/projects/{project_id}/agent-session/transcript")
    assert transcript_response.status_code == 200
    transcript_event_types = [event["event_type"] for event in transcript_response.json()]
    assert "session_resumed_after_power_on" in transcript_event_types


def test_agent_activity_does_not_show_future_autonomous_heartbeat_as_active(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Future heartbeat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Continue the main Full Auto session",
                    "summary": "Reserved heartbeat for the autonomous session.",
                }
            },
            run_after=utc_now() + timedelta(minutes=5),
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 0
    assert activity["workers"]
    assert activity["workers"][0]["job_type"] == "continue_autonomous_session"
    assert activity["workers"][0]["active"] is False
    assert activity["workers"][0]["run_after"]


def test_agent_activity_turn_state_waits_for_user_when_no_agent_work_is_observed(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Idle turn state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    turn_state = activity_response.json()["turn_state"]
    assert turn_state["state"] == "waiting_for_user"
    assert turn_state["owner"] == "user"
    assert turn_state["input_attention"] is True
    assert "local_process_table.codex_exec" in turn_state["sources"]


def test_agent_activity_watchdog_starts_main_session_when_full_auto_has_no_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Watchdog restart"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["state"] in {"agent_running", "agent_scheduled"}
    session_id = activity["turn_state"]["agent_session_id"]

    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"


def test_agent_activity_last_output_uses_codex_transcript_not_sidecar_heartbeat(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Codex output clock"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_codex_output_clock",
            project_id=project_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_heartbeat_at=utc_now(),
        )
        db.add(session)
        db.flush()
        codex_event = append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="A real Codex update.",
            payload={},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="sidecar_status",
            role="harness",
            title="Sidecar status",
            content="Harness sidecar update.",
            payload={},
        )
        expected_output_at = codex_event.created_at.replace(tzinfo=None).isoformat()
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["last_output_at"] == expected_output_at
    assert activity["workers"][0]["last_output_at"] == expected_output_at
    assert activity["workers"][0]["human_description"]["summary"] == "A real Codex update."


def test_agent_activity_surfaces_runner_retry_state(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Runner retry state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_retry_state",
            project_id=project_id,
            session_type="main_autonomous",
            status="waiting_for_runner",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working.",
            last_error="Codex CLI is not available.",
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_retry_scheduled",
            role="harness",
            title="Codex runner retry scheduled",
            content="Codex CLI is unavailable. Tablex will retry.",
            payload={"retry_delay_seconds": 120, "failure_kind": "runner_unavailable"},
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["turn_state"]["state"] == "agent_scheduled"
    assert activity["turn_state"]["label"] == "Codex runner retry scheduled"
    assert "120s" in activity["turn_state"]["detail"]
    assert activity["turn_state"]["retry_state"]["event_type"] == "runner_retry_scheduled"
    assert activity["turn_state"]["retry_state"]["event_index"] == 0
    assert activity["turn_state"]["retry_state"]["created_at"]
    assert activity["turn_state"]["retry_state"]["retry_delay_seconds"] == 120
    assert activity["turn_state"]["retry_state"]["failure_kind"] == "runner_unavailable"
    assert activity["workers"][0]["status"] == "waiting_for_runner"
    assert activity["workers"][0]["headline"] == "Codex runner retry scheduled"
    assert activity["workers"][0]["retry_state"]["retry_delay_seconds"] == 120
    assert activity["workers"][0]["retry_state"]["failure_kind"] == "runner_unavailable"


def test_project_update_starts_main_session_after_target_change(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Update restart"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        db.commit()

    update_response = client.patch(f"/api/projects/{project_id}", json={"target_column": "salary"})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["target_column"] == "salary"

    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["session_type"] == "main_autonomous"
    assert "salary" in session["goal_text"]


def test_agent_activity_turn_state_flags_stale_codex_runner_without_local_process(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Stale runner turn state"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Run Codex",
                    "summary": "This should be backed by a local codex exec process.",
                }
            },
        )
        old_timestamp = utc_now() - timedelta(minutes=2)
        job.status = "running"
        job.locked_by = "test-worker"
        job.started_at = old_timestamp
        job.updated_at = old_timestamp
        job_id = job.id
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    turn_state = activity_response.json()["turn_state"]
    assert turn_state["state"] == "stale_runner"
    assert turn_state["owner"] == "system"
    assert turn_state["input_attention"] is False
    assert turn_state["active_job_id"] == job_id


def test_agent_activity_does_not_count_heartbeat_waiting_on_active_codex_runner(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Heartbeat with active runner"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        runner_job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            context={
                "human_description": {
                    "title": "Run Codex on the main objective",
                    "summary": "Codex is doing the autonomous data-science work.",
                }
            },
        )
        runner_job.status = "running"
        runner_job.locked_by = "test-worker"
        runner_job.started_at = utc_now()
        create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"active_child_job_ids_at_schedule_time": [runner_job.id]},
            context={
                "human_description": {
                    "title": "Continue the main Full Auto session",
                    "summary": "Heartbeat waiting for Codex to return control.",
                }
            },
            run_after=utc_now() - timedelta(seconds=1),
        )
        db.commit()

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["active_count"] == 1
    workers_by_type = {worker["job_type"]: worker for worker in activity["workers"]}
    assert workers_by_type["run_planned_agent_task_codex"]["active"] is True
    assert workers_by_type["continue_autonomous_session"]["active"] is False


def test_autonomous_continuation_does_not_backoff_after_recent_codex_failure(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Runner failure no backoff"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.autonomy_mode = "full_auto"
        project.current_phase = "AUTONOMOUS_LOOP"
        failed_job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project_id,
            input_payload={"agent_task_contract_artifact_id": "art_failed_contract"},
        )
        failed_job.status = "failed"
        failed_job.error_message = "Codex CLI failed."
        failed_job.started_at = utc_now()
        failed_job.ended_at = utc_now()
        failed_job.updated_at = utc_now()
        continuation_job = create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"runner_mode": "codex_cli_if_available", "locale": "ja-JP"},
        )
        db.flush()

        output = continue_autonomous_session_handler(db, continuation_job, app.state.artifact_store)
        assert output["status"] in {"advanced", "waiting_for_data"}
        assert output.get("recent_failed_codex_job_id") is None
        assert output.get("status") != "runner_backoff"
        assert output["session_continuation_job_id"]
        assert failed_job.status == "failed"


def test_approval_based_start_creates_real_planning_evidence_with_dataset(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Autonomous with data"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,value"] + [f"{index},{'a' if index % 2 else 'b'},{index * 3}" for index in range(1, 31)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("autonomous.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "harness_only", "autonomy_mode": "approval_based"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["status"] == "queued"
    assert queued_job["output"]["schema_version"] == "autonomous_loop_start_queued.v1"
    job_response = client.get(f"/api/jobs/{queued_job['id']}")
    assert job_response.status_code == 200
    output = job_response.json()["output"]
    assert output["status"] == "advanced"
    labels = {step["label"] for step in output["steps"]}
    assert {
        "data_quality",
        "eda_review",
        "research_brief",
        "approach_ideas",
        "agent_task_contract",
        "agent_workspace",
        "evaluation_spec",
        "reflection",
    }.issubset(labels)
    assert output["artifact_ids"]
    assert output["next_human_boundary"]
    assert output["interventions"]
    assert output["interventions"][0]["kind"] == "target_definition"
    target_step = next(step for step in output["steps"] if step["label"] == "target_definition")
    assert target_step["status"] == "needs_approval"
    evaluation_step = next(step for step in output["steps"] if step["label"] == "evaluation_spec")
    assert evaluation_step["status"] == "deferred"

    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    asset_types = {artifact["asset_type"] for artifact in artifacts}
    assert "data_quality_gate" in asset_types
    assert "eda_review_bundle" in asset_types
    assert "agent_task_contract" in asset_types
    assert "agent_workspace_manifest" in asset_types

    contract_steps = [step for step in output["steps"] if step["label"] == "agent_task_contract"]
    assert contract_steps[-1]["entity_ids"]["task_type"] == "target_definition_review"


def test_full_auto_codex_start_creates_main_agent_session_transcript(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fake_supervisor(
        session_factory: Any,
        store: LocalArtifactStore,
        *,
        project_id: str,
        session_id: str,
        agent_model: str | None = None,
        **_: Any,
    ) -> None:
        del project_id, agent_model
        with session_factory() as db:
            from tabular_harness.models.entities import AgentSession

            session = db.get(AgentSession, session_id)
            assert session is not None
            session.status = "running"
            workspace_path = Path(session.workspace_path or "")
            append_runner_stream_to_workspace(
                workspace_path,
                stream_name="stdout",
                line='{"type":"thread.started","thread_id":"thread_test"}\n',
            )
            append_runner_stream_to_workspace(
                workspace_path,
                stream_name="stdout",
                line='{"type":"item.completed","item":{"type":"agent_message","text":"I am continuing."}}\n',
            )
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="thread.started",
                role="runner",
                title="Thread started",
                content=None,
                payload={"type": "thread.started", "thread_id": "thread_test"},
            )
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="item.completed",
                role="runner",
                title="Codex message",
                content="I am continuing the main autonomous session.",
                payload={"type": "item.completed", "item": {"type": "agent_message", "text": "I am continuing."}},
            )
            store_json_artifact(
                db,
                store,
                project_id=session.project_id,
                asset_type="agent_chat_turn",
                name=f"agent_session_chat_update_{session.id}",
                filename="agent_chat_turn.json",
                payload={
                    "schema_version": "agent_chat_turn.v1",
                    "project_id": session.project_id,
                    "user_message": "",
                    "assistant_message": "データ理解の根拠を確認し、次に評価設計へ進む準備をしています。",
                    "intent": {"type": "autonomous_agent_progress_report"},
                    "actions": [],
                    "action_summary": {},
                },
                metadata={
                    "project_id": session.project_id,
                    "agent_session_id": session.id,
                    "source": "main_codex_session_chat_update",
                },
            )
            db.commit()

    monkeypatch.setattr("tabular_harness.api.routes.run_main_agent_session_supervisor", fake_supervisor)
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Session Full Auto"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("session.csv", b"x,y\n1,0\n2,1\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    start_job = start_response.json()
    assert start_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = start_job["output"]["agent_session_id"]

    session_response = client.get(f"/api/projects/{project_id}/agent-session/current")
    assert session_response.status_code == 200
    session = session_response.json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"
    assert session["observed_codex_process_count"] == 0
    assert session["pid_is_observed_codex_process"] is False
    assert session["observed_runner_state"] == "supervisor_should_continue"

    transcript_response = client.get(f"/api/projects/{project_id}/agent-session/transcript")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert [event["event_type"] for event in transcript][-2:] == ["thread.started", "item.completed"]
    assert transcript[-1]["source"] == "codex_cli"
    assert transcript[-1]["content"] == "I am continuing the main autonomous session."

    delta_response = client.get(
        f"/api/projects/{project_id}/agent-session/transcript?since_index={transcript[-2]['event_index']}"
    )
    assert delta_response.status_code == 200
    delta = delta_response.json()
    assert [event["event_index"] for event in delta] == [transcript[-1]["event_index"]]

    empty_delta_response = client.get(
        f"/api/projects/{project_id}/agent-session/transcript?since_index={transcript[-1]['event_index']}"
    )
    assert empty_delta_response.status_code == 200
    assert empty_delta_response.json() == []

    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript")
    assert raw_transcript_response.status_code == 200
    raw_transcript = raw_transcript_response.json()
    assert raw_transcript["session_id"] == session_id
    assert raw_transcript["stdout_line_count"] == 2
    assert raw_transcript["stderr_line_count"] == 0
    assert raw_transcript["stdout_download_url"].endswith("/agent-session/raw-transcript/stdout/download")
    assert raw_transcript["stderr_download_url"].endswith("/agent-session/raw-transcript/stderr/download")
    assert raw_transcript["stdout_tail"][-1].startswith('{"type":"item.completed"')
    assert raw_transcript["stdout_tail_lines"][-1]["line_number"] == 2
    assert raw_transcript["stdout_tail_lines"][-1]["parsed"]["type"] == "item.completed"
    assert raw_transcript["stdout_tail_lines"][-1]["truncated"] is False
    assert raw_transcript["stderr_tail_lines"] == []
    raw_stdout_download = client.get(raw_transcript["stdout_download_url"])
    assert raw_stdout_download.status_code == 200
    assert raw_stdout_download.headers["content-type"].startswith("text/plain")
    assert raw_stdout_download.text.startswith('{"type":"thread.started"')
    invalid_raw_download = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript/stdin/download")
    assert invalid_raw_download.status_code == 404

    raw_path = Path(session["workspace_path"]) / ".tablex" / "codex_raw_transcript.jsonl"
    raw_path.write_text(
        '{"type":"item.completed","item":{"type":"command_execution","aggregated_output":"'
        + ("x" * 20_000)
        + '"}}\n',
        encoding="utf-8",
    )
    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript")
    assert raw_transcript_response.status_code == 200
    large_tail = raw_transcript_response.json()["stdout_tail_lines"][-1]
    assert large_tail["truncated"] is True
    assert large_tail["original_length"] > 20_000
    assert len(large_tail["text"]) < large_tail["original_length"]
    assert large_tail["parsed"]["type"] == "item.completed"
    assert "[truncated" in large_tail["parsed"]["item"]["aggregated_output"]

    raw_path.write_text(
        "\n".join(f'{{"type":"item.completed","index":{index}}}' for index in range(1, 1501)) + "\n",
        encoding="utf-8",
    )
    raw_transcript_response = client.get(f"/api/projects/{project_id}/agent-session/raw-transcript?limit=3")
    assert raw_transcript_response.status_code == 200
    long_raw = raw_transcript_response.json()
    assert long_raw["stdout_line_count"] == 1500
    assert [line["line_number"] for line in long_raw["stdout_tail_lines"]] == [1498, 1499, 1500]
    assert [line["parsed"]["index"] for line in long_raw["stdout_tail_lines"]] == [1498, 1499, 1500]

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    main_worker = next(worker for worker in activity["workers"] if worker.get("agent_session_id") == session_id)
    assert activity["turn_state"]["raw_transcript"]["session_id"] == session_id
    assert activity["turn_state"]["raw_transcript"]["stdout_line_count"] >= 1
    assert activity["turn_state"]["raw_transcript"]["stderr_line_count"] == 0
    assert activity["turn_state"]["raw_transcript"]["updated_at"]
    assert main_worker["raw_transcript"]["stdout_line_count"] == activity["turn_state"]["raw_transcript"]["stdout_line_count"]
    assert "データ理解の根拠" in main_worker["detail"]
    assert "データ理解の根拠" in main_worker["human_description"]["summary"]


def test_agent_chat_appends_user_instruction_to_active_main_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Session chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "評価指標はROC-AUCで考えてください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text

    transcript = client.get(f"/api/projects/{project_id}/agent-session/transcript").json()
    user_events = [event for event in transcript if event["source"] == "user" and event["event_type"] == "user_instruction"]
    assert user_events
    assert user_events[-1]["content"] == "評価指標はROC-AUCで考えてください"


def test_worker_acquire_handles_sqlite_naive_run_after(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Run-after worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        created = create_job(
            db,
            job_type="continue_autonomous_session",
            project_id=project_id,
            input_payload={"reason": "timezone-regression"},
            run_after=utc_now() - timedelta(seconds=1),
        )
        created_id = created.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="timezone-test-worker", job_types={"continue_autonomous_session"})
        assert acquired is not None
        assert acquired.id == created_id


def test_worker_acquire_skips_currently_locked_queued_job(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Locked worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        locked = create_job(db, job_type="profile_dataset", project_id=project_id, priority=100)
        locked.locked_by = "active-worker"
        locked.locked_at = utc_now()
        available = create_job(db, job_type="profile_dataset", project_id=project_id, priority=10)
        available_id = available.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="second-worker", job_types={"profile_dataset"})
        assert acquired is not None
        assert acquired.id == available_id
        assert acquired.locked_by == "second-worker"


def test_worker_acquire_recovers_stale_queued_lock(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Stale lock worker check"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        stale = create_job(db, job_type="profile_dataset", project_id=project_id, priority=100)
        stale.locked_by = "dead-worker"
        stale.locked_at = utc_now() - timedelta(minutes=11)
        stale_id = stale.id
        db.commit()

    with session_factory() as db:
        acquired = acquire_next_job(db, worker_id="recovery-worker", job_types={"profile_dataset"})
        assert acquired is not None
        assert acquired.id == stale_id
        assert acquired.locked_by == "recovery-worker"


def test_reap_stale_running_jobs_only_times_out_short_control_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Stale running cleanup"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    now = utc_now()
    with session_factory() as db:
        stale_chat = create_job(db, job_type="agent_chat_turn", project_id=project_id, priority=90)
        stale_chat.status = "running"
        stale_chat.locked_by = "dead-worker"
        stale_chat.locked_at = now - timedelta(minutes=6)
        stale_continuation = create_job(db, job_type="continue_autonomous_session", project_id=project_id, priority=45)
        stale_continuation.status = "running"
        stale_continuation.locked_by = "dead-worker"
        stale_continuation.locked_at = now - timedelta(minutes=11)
        old_training = create_job(db, job_type="train_model_candidates", project_id=project_id, priority=60)
        old_training.status = "running"
        old_training.locked_by = "busy-worker"
        old_training.locked_at = now - timedelta(hours=2)
        fresh_chat = create_job(db, job_type="agent_chat_turn", project_id=project_id, priority=90)
        fresh_chat.status = "running"
        fresh_chat.locked_by = "active-worker"
        fresh_chat.locked_at = now - timedelta(minutes=1)
        ids = {
            "stale_chat": stale_chat.id,
            "stale_continuation": stale_continuation.id,
            "old_training": old_training.id,
            "fresh_chat": fresh_chat.id,
        }
        db.commit()

    with session_factory() as db:
        assert reap_stale_running_jobs(db, now=now) == 2
        db.commit()

    with session_factory() as db:
        assert db.get(Job, ids["stale_chat"]).status == "timed_out"
        assert db.get(Job, ids["stale_continuation"]).status == "timed_out"
        assert db.get(Job, ids["old_training"]).status == "running"
        assert db.get(Job, ids["fresh_chat"]).status == "running"


def test_sync_worker_marks_failed_after_handler_transaction_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Worker rollback"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    session_factory = app.state.session_factory
    with session_factory() as db:
        job = create_job(db, job_type="profile_dataset", project_id=project_id)
        job_id = job.id
        db.commit()

    def broken_handler(db: Any, job: Job, store: LocalArtifactStore) -> dict[str, object]:
        del store
        duplicate_a = Artifact(
            id="art_duplicate_a",
            project_id=job.project_id,
            asset_type="duplicate_test",
            name="same",
            version=1,
            uri="local://a",
            content_hash="a",
        )
        duplicate_b = Artifact(
            id="art_duplicate_b",
            project_id=job.project_id,
            asset_type="duplicate_test",
            name="same",
            version=1,
            uri="local://b",
            content_hash="b",
        )
        db.add_all([duplicate_a, duplicate_b])
        try:
            db.flush()
        except IntegrityError as exc:
            raise RuntimeError("simulated handler transaction failure") from exc
        return {"unexpected": True}

    worker = SyncWorker(
        handlers={"profile_dataset": broken_handler},
        store=cast(Any, app).state.artifact_store,
        worker_id="rollback-test-worker",
    )
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        result = worker.run_job(db, job)
        assert result.status == "failed"
        assert "simulated handler transaction failure" in (result.error_message or "")

    with session_factory() as db:
        recovered = db.get(Job, job_id)
        assert recovered is not None
        assert recovered.status == "failed"


def test_full_auto_start_queues_training_for_large_dataset_boundary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TABLEX_AUTONOMY_SYNC_TRAINING_ROW_LIMIT", "10")
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Autonomous queued training", "target_column": "label", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("queued_training.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert session["session_type"] == "main_autonomous"
    assert "fixed recipes" in session["goal_text"].lower()

    activity = client.get(f"/api/projects/{project_id}/agent-activity").json()
    assert activity["turn_state"]["agent_session_id"] == session_id
    assert any(worker.get("agent_session_id") == session_id for worker in activity["workers"])

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history
    assert history[-1]["intent"]["type"] == "agent_loop_control"
    assert "Full Auto" in history[-1]["assistant_message"]


def test_full_auto_passes_readiness_constraints_to_main_codex_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Constrained autonomous session", "target_column": "label", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("constrained.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        db.add(
            Question(
                id="q_block_autonomous",
                project_id=project_id,
                question_set_id="qs_block_autonomous",
                topic="evaluation_boundary",
                question="Should the current validation boundary be confirmed before interpreting model results?",
                why_it_matters="This affects whether model comparison evidence can be trusted.",
                default_assumption="Continue with the current split as a provisional boundary.",
                impact_if_wrong="The leaderboard may overstate generalization.",
                choices_json="[]",
                status="open",
                priority=95,
                risk_level="high",
                value_of_answer="high",
                can_proceed_without_answer=False,
                fallback_policy="block_until_answered",
                blocks_next_phase=True,
            )
        )
        db.commit()

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert "Design reliable evaluation" in session["goal_text"]
    transcript = client.get(f"/api/projects/{project_id}/agent-session/transcript").json()
    assert any(event["event_type"] == "session_created" for event in transcript)


def test_full_auto_delegates_target_definition_to_codex_without_harness_target_heuristics(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TABLEX_AUTONOMY_SYNC_TRAINING_ROW_LIMIT", "10")
    monkeypatch.setattr("tabular_harness.services.autonomy.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Home Credit style upload"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    train_rows = ["SK_ID_CURR,feature,TARGET"] + [f"{100000 + index},{index % 7},{1 if index % 5 == 0 else 0}" for index in range(1, 80)]
    train_upload = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("application_train.csv", "\n".join(train_rows).encode("utf-8"), "text/csv")},
    )
    assert train_upload.status_code == 200, train_upload.text

    submission_rows = ["SK_ID_CURR,TARGET"] + [f"{200000 + index},0.0" for index in range(1, 80)]
    submission_upload = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("sample_submission.csv", "\n".join(submission_rows).encode("utf-8"), "text/csv")},
    )
    assert submission_upload.status_code == 200, submission_upload.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli_if_available", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    assert train_upload.json()["dataset_snapshot"]["id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert "infer or construct the prediction objective from evidence" in session["goal_text"]

    project = client.get(f"/api/projects/{project_id}").json()
    assert project["target_column"] is None
    assert project["task_type"] is None


def test_full_auto_codex_target_proposal_drives_evaluation_and_runs(tmp_path: Path, monkeypatch: Any) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Codex target proposal"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,label"] + [
        f"{index},{'a' if index % 2 else 'b'},{1 if index % 3 == 0 else 0}" for index in range(1, 80)
    ]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("codex_target.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    def fake_codex_runner(*args: Any, **kwargs: Any) -> Any:
        agent_result = AgentResult(
            task_id="agt_fake",
            status="succeeded",
            final_message="Codex reviewed the data context and proposed a target.",
            outputs={
                "target_definition_proposal": {
                    "recommended_target": {
                        "kind": "existing_column",
                        "column_name": "label",
                        "task_type": "binary_classification",
                        "confidence": 0.82,
                        "risk_level": "medium",
                        "rationale": "The proposal is based on the profiled project context supplied to Codex.",
                    },
                    "alternatives": [],
                    "risks": ["Confirm prediction-time availability before deployment."],
                },
                "report_md": "Target definition review complete.",
            },
            artifacts=[],
            warnings=[],
        )
        return SimpleNamespace(
            agent_result=agent_result,
            artifact_ids=[],
            report_id="rpt_fake",
            evidence_id="ev_fake",
            workspace_artifact_id="art_workspace_fake",
            readiness_artifact_id="art_readiness_fake",
            readiness_status="ready_with_warnings",
            ingested_artifact_ids=[],
            auto_prepared_workspace=False,
            experiment_ingestion=SimpleNamespace(run=None),
            relational_context_summary={},
            relational_context_summary_artifact_id=None,
            approach_decision_trace_artifact_id=None,
        )

    del fake_codex_runner
    monkeypatch.setattr(
        "tabular_harness.api.routes.run_main_agent_session_supervisor",
        lambda *args, **kwargs: None,
    )

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "codex_cli", "autonomy_mode": "full_auto", "locale": "ja-JP"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "agent_session_start.v1"
    session_id = queued_job["output"]["agent_session_id"]
    session = client.get(f"/api/projects/{project_id}/agent-session/current").json()
    assert session["id"] == session_id
    assert "Current target/objective hint" in session["goal_text"]

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    project = project_read_response.json()
    assert project["target_column"] is None
    assert project["task_type"] is None


def test_approval_based_start_runs_but_does_not_auto_adopt_evaluation(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Approval based with data", "target_column": "value", "task_type": "regression"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    rows = ["feature,segment,value"] + [f"{index},{'a' if index % 2 else 'b'},{index * 3}" for index in range(1, 31)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("approval.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    start_response = client.post(
        f"/api/projects/{project_id}/autonomy/start",
        json={"runner_mode": "harness_only", "autonomy_mode": "approval_based"},
    )
    assert start_response.status_code == 200, start_response.text
    queued_job = start_response.json()
    assert queued_job["output"]["schema_version"] == "autonomous_loop_start_queued.v1"
    job_response = client.get(f"/api/jobs/{queued_job['id']}")
    assert job_response.status_code == 200
    output = job_response.json()["output"]
    assert output["mode"] == "approval_based"
    assert any(step["label"] == "evaluation_review" for step in output["steps"])
    evaluation_step = next(step for step in output["steps"] if step["label"] == "evaluation_spec")
    assert evaluation_step["status"] == "blocked"
    assert "Human approval" in evaluation_step["boundary"]

    project_read_response = client.get(f"/api/projects/{project_id}")
    assert project_read_response.status_code == 200
    assert project_read_response.json()["autonomy_mode"] == "approval_based"
    assert project_read_response.json()["current_phase"] == "AUTONOMOUS_LOOP"

    specs = client.get(f"/api/projects/{project_id}/evaluation/specs").json()
    assert all(spec["status"] != "approved" for spec in specs)


def test_project_guidance_recommends_next_focus(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Guided UX"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    empty_guidance_response = client.get(f"/api/projects/{project_id}/guidance")
    assert empty_guidance_response.status_code == 200, empty_guidance_response.text
    empty_guidance = empty_guidance_response.json()
    assert empty_guidance["schema_version"] == "project_guidance.v1"
    assert empty_guidance["attention_budget"] == 1
    assert empty_guidance["recommended_focus"]["focus_key"] == "upload_data"
    assert empty_guidance["recommended_focus"]["target_tab"] == "Data"
    assert empty_guidance["recommended_focus"]["primary_action"]["action_type"] == "navigate"
    assert empty_guidance["supporting_counts"]["datasets"] == 0
    empty_navigation = empty_guidance["autonomous_navigation"]
    assert empty_navigation["schema_version"] == "autonomous_navigation.v1"
    assert empty_navigation["mode"] == "one_decision_at_a_time"
    assert empty_navigation["attention_budget"] == 1
    assert empty_navigation["headline"] == empty_guidance["recommended_focus"]["title"]
    assert empty_navigation["primary_action"]["id"] == empty_guidance["recommended_focus"]["primary_action"]["id"]
    assert empty_navigation["codex_navigation"]["runner_may_choose_approach"] is True
    assert empty_navigation["decision_brief"]["schema_version"] == "autonomous_decision_brief.v1"
    assert empty_navigation["decision_brief"]["attention_budget"] == 1
    assert empty_navigation["decision_brief"]["decision_question"]
    empty_journey = {stage["id"]: stage for stage in empty_guidance["journey_stages"]}
    assert empty_guidance["current_stage_id"] == "data_intake"
    assert empty_journey["data_intake"]["status"] == "current"
    assert empty_journey["understanding"]["status"] == "waiting"
    assert empty_journey["notebooks"]["target_tab"] == "Notebooks"
    assert empty_journey["notebooks"]["status"] == "waiting"
    assert empty_journey["approach"]["summary"].startswith("Prepare an open-ended Codex")

    csv_bytes = b"feature,target\n1,0\n2,1\n3,0\n4,1\n"
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("guided.csv", csv_bytes, "text/csv")},
        data={"target_column": "target"},
    )
    assert upload_response.status_code == 200, upload_response.text

    next_guidance_response = client.get(f"/api/projects/{project_id}/guidance")
    assert next_guidance_response.status_code == 200, next_guidance_response.text
    next_guidance = next_guidance_response.json()
    assert next_guidance["supporting_counts"]["datasets"] == 1
    next_journey = {stage["id"]: stage for stage in next_guidance["journey_stages"]}
    assert next_journey["data_intake"]["status"] == "done"
    assert next_guidance["current_stage_id"] in {
        "understanding",
        "assumptions",
        "evaluation",
        "approach",
    }
    assert next_guidance["recommended_focus"]["focus_key"] in {
        "assumptions",
        "evaluation",
        "understand_data",
    }
    assert next_guidance["recommended_focus"]["primary_action"]["target_tab"]
    assert next_guidance["agent_guidance"]
    next_navigation = next_guidance["autonomous_navigation"]
    assert next_navigation["attention_budget"] == 1
    assert next_navigation["journey_progress"]["total_count"] == len(next_guidance["journey_stages"])
    assert "show_the_next_decision" in next_navigation["aesthetic_principle"]
    assert next_navigation["decision_brief"]["target_tab"] == next_guidance["recommended_focus"]["target_tab"]

    snapshot_response = client.post(f"/api/projects/{project_id}/guidance/snapshot")
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot_job = snapshot_response.json()
    assert snapshot_job["status"] == "succeeded"
    assert snapshot_job["job_type"] == "save_guided_journey_snapshot"
    assert snapshot_job["output"]["schema_version"] == "guided_journey_snapshot.v1"
    assert snapshot_job["output"]["guided_journey_snapshot_artifact_id"]
    assert snapshot_job["output"]["guided_journey_report_id"]
    assert snapshot_job["output"]["visualization_artifact_id"]

    report_preview_response = client.get(f"/api/reports/{snapshot_job['output']['guided_journey_report_id']}/preview")
    assert report_preview_response.status_code == 200, report_preview_response.text
    assert "Guided Journey" in report_preview_response.json()["preview"]

    decision_brief_response = client.post(f"/api/projects/{project_id}/guidance/decision-brief")
    assert decision_brief_response.status_code == 200, decision_brief_response.text
    decision_brief_job = decision_brief_response.json()
    assert decision_brief_job["status"] == "succeeded"
    assert decision_brief_job["job_type"] == "save_autonomous_decision_brief"
    assert decision_brief_job["output"]["schema_version"] == "autonomous_decision_brief.v1"
    assert decision_brief_job["output"]["autonomous_decision_brief_artifact_id"]
    assert decision_brief_job["output"]["autonomous_decision_brief_report_id"]

    decision_brief_preview_response = client.get(
        f"/api/reports/{decision_brief_job['output']['autonomous_decision_brief_report_id']}/preview"
    )
    assert decision_brief_preview_response.status_code == 200, decision_brief_preview_response.text
    assert "Autonomous Decision Brief" in decision_brief_preview_response.json()["preview"]

    second_snapshot_response = client.post(f"/api/projects/{project_id}/guidance/snapshot")
    assert second_snapshot_response.status_code == 200, second_snapshot_response.text

    comparison_response = client.post(f"/api/projects/{project_id}/guidance/snapshots/compare")
    assert comparison_response.status_code == 200, comparison_response.text
    comparison_job = comparison_response.json()
    assert comparison_job["status"] == "succeeded"
    assert comparison_job["job_type"] == "compare_guided_journey_snapshots"
    assert comparison_job["output"]["schema_version"] == "guided_journey_comparison.v1"
    assert comparison_job["output"]["guided_journey_comparison_artifact_id"]
    assert comparison_job["output"]["guided_journey_comparison_report_id"]

    comparison_preview_response = client.get(
        f"/api/reports/{comparison_job['output']['guided_journey_comparison_report_id']}/preview"
    )
    assert comparison_preview_response.status_code == 200, comparison_preview_response.text
    assert "Guided Journey Comparison" in comparison_preview_response.json()["preview"]



def test_agent_chat_records_conversation_without_mutating_project_state(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Metric chat", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,target"] + [f"{index},0" for index in range(1, 10)] + ["10,1"]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("metric.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    candidates_before = client.get(f"/api/projects/{project_id}/evaluation/candidates").json()
    assert any(candidate["primary_metric"] == "pr_auc" for candidate in candidates_before)

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "metricはROCーAUCにして", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["schema_version"] == "agent_chat_turn.v1"
    assert chat["intent"]["type"] == "agent_conversation"
    assert chat["actions"] == []
    assert chat["job"]["status"] == "queued"
    assert chat["response_composer"]["status"] == "queued"
    assert chat["artifact_id"].startswith("pending_")
    assert "返答を準備しています" in chat["assistant_message"]
    assert chat["response_brief"]["wait_state"]["worker_state"] == "waiting_for_local_worker"

    pending_history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert pending_history_response.status_code == 200
    pending_history = pending_history_response.json()
    assert len(pending_history) == 1
    assert pending_history[0]["job_id"] == chat["job"]["id"]
    assert pending_history[0]["artifact_id"] == f"job_pending_{chat['job']['id']}"
    assert pending_history[0]["response_composer"]["status"] == "queued"
    assert "返答を準備しています" in pending_history[0]["assistant_message"]
    assert pending_history[0]["response_brief"]["wait_state"]["worker_state"] == "waiting_for_local_worker"
    assert pending_history[0]["response_brief"]["wait_state"]["job_age_seconds"] >= 0

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        old_job = db.get(Job, chat["job"]["id"])
        assert old_job is not None
        old_time = utc_now() - timedelta(seconds=75)
        old_job.created_at = old_time
        old_job.updated_at = old_time
        db.commit()
    stale_history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert stale_history[0]["response_brief"]["wait_state"]["possibly_stale"] is True
    assert "まだ返答が戻っていません" in stale_history[0]["assistant_message"]

    output = run_queued_agent_chat_turn(client, chat["job"]["id"])
    assert output["schema_version"] == "agent_chat_turn.v1"

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    answered = history[0]
    assert answered["user_message"] == "metricはROCーAUCにして"
    assert answered["actions"] == []
    assert answered["intent"]["type"] == "agent_conversation"
    assert answered["artifact_id"] == output["artifact_id"]
    assert answered["action_summary"]["outcome"] == "answered"
    assert "schema-validated agent proposals" in answered["action_summary"]["boundaries"][0]
    assert answered["response_brief"]["response_locale"] == "ja-JP"
    assert answered["response_brief"]["conversation_context"]["schema_version"] == "agent_conversation_context.v1"
    explicit_actions = {
        item["action"] for item in answered["response_brief"]["conversation_context"]["available_explicit_actions"]
    }
    assert {"create_skill", "equip_existing_skill"} <= explicit_actions
    assert answered["response_brief"]["conversation_context"]["skill_context"]["purpose"].startswith("Skills are reusable")
    assert answered["token_usage"]["is_estimate"] is True

    candidates_after = client.get(f"/api/projects/{project_id}/evaluation/candidates").json()
    assert candidates_after == candidates_before
    leaderboard = client.get(f"/api/projects/{project_id}/leaderboard").json()
    assert leaderboard == []
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    assert any(item["asset_type"] == "agent_chat_turn" for item in artifacts)
    assert not any(item["asset_type"] == "evaluation_metric_preference" for item in artifacts)

    metric_response = client.post(f"/api/projects/{project_id}/leaderboard/metric", json={"metric": "ROCーAUC"})
    assert metric_response.status_code == 200, metric_response.text
    assert metric_response.json()["metric"] == "roc_auc"


def test_agent_chat_brief_includes_recent_conversation_turns(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Conversation Memory"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    first_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "この会話でsalaryの扱いを後で確認したいです。", "locale": "ja-JP"},
    )
    assert first_response.status_code == 200, first_response.text
    first_output = run_queued_agent_chat_turn(client, first_response.json()["job"]["id"])
    assert first_output["schema_version"] == "agent_chat_turn.v1"

    second_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "さっきの話を踏まえて状況を説明してください。", "locale": "ja-JP"},
    )
    assert second_response.status_code == 200, second_response.text
    run_queued_agent_chat_turn(client, second_response.json()["job"]["id"])

    history_response = client.get(f"/api/projects/{project_id}/agent-chat/history")
    assert history_response.status_code == 200
    second_turn = history_response.json()[-1]
    recent_turns = second_turn["response_brief"]["conversation_context"]["recent_conversation_turns"]
    assert any("salaryの扱い" in turn["user_message"] for turn in recent_turns)
    assert any(turn["artifact_id"] == first_output["artifact_id"] for turn in recent_turns)


def test_agent_chat_writes_active_session_instruction_to_workspace_inbox(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Inbox delivery"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_inbox_delivery"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_inbox_delivery",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working and read the workspace inbox.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.flush()
        append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="現在のデータを確認しています。",
            payload={"type": "item.completed", "item": {"type": "agent_message"}},
        )
        db.commit()
    append_runner_stream_to_workspace(workspace, stream_name="stdout", line='{"type":"turn.started"}')

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "この条件で特徴量を見直してください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["job"]["job_type"] == "agent_chat_turn"
    assert chat["job"]["status"] == "waiting_for_agent"
    assert chat["job"]["priority"] == 90
    assert chat["job"]["run_after"] is None
    assert chat["response_composer"]["mode"] == "main_codex_session"
    assert chat["response_composer"]["status"] == "waiting_for_agent"
    assert "入力は進行中の分析エージェントに届いています" in chat["assistant_message"]
    assert "worker待ち" not in chat["assistant_message"]
    assert chat["response_brief"]["wait_state"]["worker_state"] == "waiting_for_main_agent_reply"
    assert chat["response_brief"]["progress_update_requested_event_id"]
    observation = chat["response_brief"]["agent_session_observation"]
    assert observation["schema_version"] == "agent_session_chat_wait_observation.v1"
    assert observation["agent_session_id"] == "ags_inbox_delivery"
    assert observation["status"] == "running"
    assert observation["last_codex_output_seconds_ago"] is not None
    assert observation["raw_transcript"]["stdout_line_count"] == 1

    inbox = user_instructions_inbox_path(workspace)
    latest = latest_user_instruction_path(workspace)
    progress_request = progress_request_path(workspace)
    assert inbox.exists()
    assert latest.exists()
    assert progress_request.exists()
    inbox_lines = inbox.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(inbox_lines[-1])
    assert payload["schema_version"] == "tablex_user_instruction.v1"
    assert payload["session_id"] == "ags_inbox_delivery"
    assert payload["locale"] == "ja-JP"
    assert payload["message"] == "この条件で特徴量を見直してください"
    progress_request_text = progress_request.read_text(encoding="utf-8")
    assert "trigger: user_chat_message" in progress_request_text
    assert "latest_user_message:" in progress_request_text
    assert "この条件で特徴量を見直してください" in progress_request_text
    assert "ユーザーがAgent Chatで返答を待っています" in progress_request_text
    assert "この条件で特徴量を見直してください" in latest.read_text(encoding="utf-8")
    jobs = client.get(f"/api/projects/{project_id}/jobs").json()
    assert any(job["job_type"] == "agent_chat_turn" and job["status"] == "waiting_for_agent" for job in jobs)
    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history[-1]["job_id"] == chat["job"]["id"]
    assert history[-1]["user_message"] == "この条件で特徴量を見直してください"
    assert history[-1]["response_composer"]["mode"] == "main_codex_session"
    assert history[-1]["response_composer"]["status"] == "waiting_for_agent"
    assert "Codexの返答が届き次第" in history[-1]["assistant_message"]
    assert history[-1]["response_brief"]["delivered_agent_session_id"] == "ags_inbox_delivery"
    assert history[-1]["response_brief"]["wait_state"]["worker_state"] == "waiting_for_main_agent_reply"
    history_observation = history[-1]["response_brief"]["agent_session_observation"]
    assert history_observation["agent_session_id"] == "ags_inbox_delivery"
    assert history_observation["raw_transcript"]["stdout_line_count"] == 1

    worker = SyncWorker(handlers={"agent_chat_turn": agent_chat_turn_handler}, store=app.state.artifact_store)
    with app.state.session_factory() as db:
        assert worker.run_next_job(db, project_id=project_id, job_types={"agent_chat_turn"}) is None
        waiting_job = db.get(Job, chat["job"]["id"])
        assert waiting_job is not None
        assert waiting_job.status == "waiting_for_agent"

    report_path = workspace / "reports" / "chat_update.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("特徴量の見直し依頼を受け取りました。次に利用可能な列と漏洩リスクを確認します。", encoding="utf-8")
    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        session = db.get(AgentSession, "ags_inbox_delivery")
        assert project is not None
        assert session is not None
        source_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_session_report",
            name="agent_session_reports_chat_update_md",
            filename="chat_update.md",
            payload={"message": report_path.read_text(encoding="utf-8")},
            metadata={"project_id": project_id, "agent_session_id": session.id},
        )
        maybe_register_chat_update_from_workspace_output(
            db,
            store=app.state.artifact_store,
            project=project,
            session=session,
            path=report_path,
            artifact=source_artifact,
        )
        db.commit()

    completed_history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    completed_turn = completed_history[-1]
    assert completed_turn["job_id"] == chat["job"]["id"]
    assert "特徴量の見直し依頼" in completed_turn["assistant_message"]
    assert completed_turn["response_composer"]["mode"] == "main_codex_session"
    assert completed_turn["response_brief"]["progress_artifact_id"]


def test_agent_chat_history_pairs_main_session_update_to_delivered_instruction(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Main session chat update pairing"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_update_pairing"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_update_pairing",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep working and publish chat updates.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        db.commit()

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "いま何を見ていますか？", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert "入力は進行中の分析エージェントに届いています" in chat["assistant_message"]

    with app.state.session_factory() as db:
        progress_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_chat_update_ags_update_pairing_manual",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "project_id": project_id,
                "user_message": "",
                "assistant_message": "データの粒度と欠損の偏りを確認しています。次に候補特徴量の漏洩リスクを見ます。",
                "intent": {
                    "type": "autonomous_agent_progress_report",
                    "source": "main_codex_session",
                    "routing_policy": "codex_authored_human_update",
                },
                "actions": [],
                "action_summary": {},
                "response_brief": {
                    "schema_version": "agent_progress_report_brief.v1",
                    "agent_session_id": "ags_update_pairing",
                    "source_artifact_id": "art_manual_chat_update",
                    "workspace_relative_path": "reports/chat_update.md",
                },
                "response_composer": {
                    "schema_version": "agent_response_composer.v1",
                    "mode": "main_codex_session",
                    "status": "codex_authored",
                },
                "worker_events": [],
                "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
                "next_focus": {"target_tab": "Data", "target_anchor": "notebook-preview-top", "label": "Data"},
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": "ags_update_pairing",
                "source_artifact_id": "art_manual_chat_update",
                "source": "main_codex_session_chat_update",
            },
        )
        db.commit()

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert len(history) == 1
    turn = history[0]
    assert turn["user_message"] == "いま何を見ていますか？"
    assert "データの粒度" in turn["assistant_message"]
    assert "worker待ち" not in turn["assistant_message"]
    assert turn["intent"]["source"] == "main_codex_session_chat_update"
    assert turn["response_composer"]["mode"] == "main_codex_session"
    assert turn["response_composer"]["status"] == "codex_authored"
    assert turn["response_brief"]["progress_artifact_id"] == progress_artifact.id
    assert turn["response_brief"]["agent_session_observation"]["agent_session_id"] == "ags_update_pairing"
    assert turn["response_brief"]["agent_session_observation"]["schema_version"] == "agent_session_chat_wait_observation.v1"
    assert turn["job_id"] == chat["job"]["id"]


def test_agent_chat_history_pairs_each_main_session_update_once(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "One progress update per chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_one_update"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        db.add(
            AgentSession(
                id="ags_one_update",
                project_id=project_id,
                org_id=project.org_id,
                session_type="main_autonomous",
                status="running",
                autonomy_mode="full_auto",
                runner_kind="codex_cli",
                goal_text="Keep working and publish chat updates.",
                workspace_path=str(workspace),
                created_by="test",
            )
        )
        db.commit()

    first_chat = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "最初の質問です。", "locale": "ja-JP"},
    ).json()
    second_chat = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "二つ目の質問です。", "locale": "ja-JP"},
    ).json()

    with app.state.session_factory() as db:
        progress_artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="agent_session_chat_update_ags_one_update_manual",
            filename="agent_chat_turn.json",
            payload={
                "schema_version": "agent_chat_turn.v1",
                "project_id": project_id,
                "user_message": "",
                "assistant_message": "最初の質問に対応する進捗です。次は評価設計を見ます。",
                "intent": {
                    "type": "autonomous_agent_progress_report",
                    "source": "main_codex_session",
                    "routing_policy": "codex_authored_human_update",
                },
                "actions": [],
                "action_summary": {},
                "response_brief": {
                    "schema_version": "agent_progress_report_brief.v1",
                    "agent_session_id": "ags_one_update",
                    "source_artifact_id": "art_one_update",
                    "workspace_relative_path": "reports/chat_update.md",
                },
                "response_composer": {
                    "schema_version": "agent_response_composer.v1",
                    "mode": "main_codex_session",
                    "status": "codex_authored",
                },
                "worker_events": [],
                "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
                "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"},
            },
            metadata={
                "project_id": project_id,
                "agent_session_id": "ags_one_update",
                "source_artifact_id": "art_one_update",
                "source": "main_codex_session_chat_update",
            },
        )
        db.commit()

    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    first_turn = next(turn for turn in history if turn.get("job_id") == first_chat["job"]["id"])
    second_turn = next(turn for turn in history if turn.get("job_id") == second_chat["job"]["id"])

    assert first_turn["user_message"] == "最初の質問です。"
    assert first_turn["response_brief"]["progress_artifact_id"] == progress_artifact.id
    assert "最初の質問に対応する進捗" in first_turn["assistant_message"]
    assert second_turn["user_message"] == "二つ目の質問です。"
    assert second_turn["response_composer"]["mode"] == "main_codex_session"
    assert second_turn["response_composer"]["status"] == "waiting_for_agent"
    assert "Codexの返答が届き次第" in second_turn["assistant_message"]
    assert second_turn["artifact_id"].startswith("job_pending_")


def test_main_session_update_pairing_uses_datetime_order_not_string_order() -> None:
    job = Job(
        id="job_chat_pair",
        job_type="agent_chat_turn",
        project_id="p_pair",
        input_json="{}",
        output_json="{}",
        created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    payload = {"delivered_agent_session_id": "ags_pair"}
    old_update_with_later_looking_local_time = {
        "agent_session_id": "ags_pair",
        "artifact_id": "art_old",
        "created_at": "2026-01-01T08:59:59+09:00",
    }
    new_update = {
        "agent_session_id": "ags_pair",
        "artifact_id": "art_new",
        "created_at": "2026-01-01T00:00:01Z",
    }

    paired = matching_main_session_update_for_chat_job(
        job,
        payload,
        [old_update_with_later_looking_local_time, new_update],
    )

    assert paired == new_update


def test_research_plan_timeline_reads_artifact_authored_blocks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Timeline Plan"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        artifact = store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_research_plan",
            filename="research_plan.json",
            metadata={"project_id": project_id, "source": "test"},
            payload={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "deep_eda",
                        "title": "Deep EDA",
                        "why_it_matters": "Inspect salary tail and relational coverage.",
                        "next_action": "Open the EDA notebook and validate the tail story.",
                        "done_criteria": "Tail risk is documented with a readable artifact.",
                        "evidence": "1 evidence",
                        "blockers": ["Owner review is pending."],
                        "supporting_artifacts": [{"path": "notebooks/deep_eda.py", "exists": True}],
                        "status": "active",
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-preview-top",
                        "localizations": {
                            "ja-JP": {
                                "title": "深いEDA",
                                "why_it_matters": "salaryの裾とリレーショナルなカバレッジを確認します。",
                                "next_action": "EDAノートブックを開き、裾の見立てを確認します。",
                                "done_criteria": "裾のリスクが読めるartifactで記録されていること。",
                                "blockers": ["データオーナー確認が未完了です。"],
                            }
                        },
                        "subtasks": [
                            {
                                "id": "tail_review",
                                "title": "High salary tail review",
                                "detail": "Check whether tail labels need a separate decision path.",
                                "status": "pending",
                                "target_tab": "Insight",
                                "localizations": {
                                    "ja-JP": {
                                        "title": "高salary裾の確認",
                                        "detail": "裾ラベルに別の判断経路が必要か確認します。",
                                    }
                                },
                            }
                        ],
                    },
                    {
                        "id": "approval_response_contract_v19",
                        "title": "approval response contract v19",
                        "why_it_matters": "Prepare the data owner reply shape.",
                        "blockers": ["Owner review is pending.", "Metric choice is pending."],
                        "status": "blocked",
                    },
                    {
                        "id": "done_missing_notebook",
                        "title": "Done missing notebook",
                        "why_it_matters": "A readable notebook must exist before this can be treated as done.",
                        "supporting_artifacts": [{"path": "notebooks/missing_eda.py", "exists": False}],
                        "status": "done",
                        "localizations": {
                            "ja-JP": {
                                "title": "未生成Notebook待ち",
                                "why_it_matters": "読めるNotebookが存在するまでは完了扱いできません。",
                            }
                        },
                    },
                    {"id": "broken", "status": "done"},
                    {
                        "id": "invalid_status",
                        "title": "Invalid status becomes pending",
                        "phase": "modeling",
                        "status": "surprise",
                    },
                    {
                        "id": "mixed_language",
                        "title": "Codexが update model diagnostics and feature importance",
                        "why_it_matters": "Notebookで inspect error slices, PDP, and residual segments.",
                        "status": "active",
                    },
                    {
                        "id": "thin_japanese_mixed_title",
                        "title": "approved target rebuild と evaluation",
                        "why_it_matters": "承認後はresolved target candidate、evaluation rerun、case queue reviewが必要。",
                        "status": "active",
                    },
                    {
                        "id": "japanese_heading_english_phrase",
                        "title": "データアップロード / project context",
                        "why_it_matters": "Dataset identity、target hint、locale、output contractが確定している。",
                        "status": "done",
                    },
                ],
            },
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["source_artifact_id"] == artifact.id
    assert [block["id"] for block in timeline["blocks"]] == [
        "deep_eda",
        "approval_response_contract_v19",
        "done_missing_notebook",
        "invalid_status",
        "mixed_language",
        "thin_japanese_mixed_title",
        "japanese_heading_english_phrase",
    ]
    assert timeline["blocks"][0]["status"] == "active"
    assert timeline["blocks"][0]["subtitle"] == "Inspect salary tail and relational coverage."
    assert timeline["blocks"][0]["next_action"] == "Open the EDA notebook and validate the tail story."
    assert timeline["blocks"][0]["done_criteria"] == "Tail risk is documented with a readable artifact."
    assert timeline["blocks"][0]["evidence"] == "1 evidence"
    assert timeline["blocks"][0]["supporting_artifacts"][0]["path"] == "notebooks/deep_eda.py"
    assert timeline["blocks"][0]["subtasks"][0]["target_tab"] == "Insight"
    assert timeline["blocks"][1]["status"] == "blocked"
    assert timeline["blocks"][2]["status"] == "pending"
    assert timeline["blocks"][2]["status_adjustment_reason"] == "missing_supporting_artifacts"
    assert timeline["blocks"][2]["missing_supporting_artifact_count"] == 1
    assert timeline["blocks"][2]["supporting_artifacts"][0]["exists"] is False
    assert timeline["blocks"][3]["status"] == "pending"
    assert timeline["blocks"][3]["evidence"] == "modeling"

    localized_response = client.get(f"/api/projects/{project_id}/research-plan/timeline?locale=ja-JP")
    assert localized_response.status_code == 200
    localized = localized_response.json()
    assert localized["response_locale"] == "ja-JP"
    assert localized["localization"]["requires_explicit_locale"] is True
    assert localized["localization"]["missing_block_count"] == 5
    assert localized["localization"]["missing_subtask_count"] == 0
    assert localized["blocks"][0]["title"] == "深いEDA"
    assert localized["blocks"][0]["subtitle"] == "salaryの裾とリレーショナルなカバレッジを確認します。"
    assert localized["blocks"][0]["next_action"] == "EDAノートブックを開き、裾の見立てを確認します。"
    assert localized["blocks"][0]["done_criteria"] == "裾のリスクが読めるartifactで記録されていること。"
    assert localized["blocks"][0]["blockers"] == ["データオーナー確認が未完了です。"]
    assert localized["blocks"][0]["evidence"] == "ブロッカー 1件"
    assert localized["blocks"][0]["localization_status"] == "localized"
    assert localized["blocks"][0]["subtasks"][0]["title"] == "高salary裾の確認"
    assert localized["blocks"][0]["subtasks"][0]["detail"] == "裾ラベルに別の判断経路が必要か確認します。"
    assert localized["blocks"][1]["title"] == "計画ブロック"
    assert localized["blocks"][1]["subtitle"] == ""
    assert localized["blocks"][1]["localization_status"] == "needs_locale_refresh"
    assert localized["blocks"][1]["missing_localization_fields"] == ["title", "why_it_matters", "blockers"]
    assert localized["blocks"][1]["evidence"] is None
    assert localized["blocks"][1]["blockers"] == []
    assert localized["blocks"][2]["title"] == "未生成Notebook待ち"
    assert localized["blocks"][2]["status"] == "pending"
    assert localized["blocks"][2]["status_adjustment_reason"] == "missing_supporting_artifacts"
    assert localized["blocks"][2]["missing_supporting_artifact_count"] == 1
    assert localized["blocks"][2]["localization_status"] == "localized"
    assert localized["blocks"][3]["status"] == "pending"
    assert localized["blocks"][3]["localization_status"] == "needs_locale_refresh"
    assert localized["blocks"][3]["evidence"] is None
    assert localized["blocks"][3]["title"] == "計画ブロック"
    assert localized["blocks"][3]["subtitle"] == ""
    assert localized["blocks"][4]["localization_status"] == "needs_locale_refresh"
    assert localized["blocks"][4]["title"] == "計画ブロック"
    assert localized["blocks"][4]["subtitle"] == ""
    assert localized["blocks"][5]["localization_status"] == "needs_locale_refresh"
    assert localized["blocks"][5]["title"] == "計画ブロック"
    assert localized["blocks"][5]["subtitle"] == ""
    assert localized["blocks"][6]["localization_status"] == "needs_locale_refresh"
    assert localized["blocks"][6]["title"] == "計画ブロック"
    assert localized["blocks"][6]["subtitle"] == ""

    japanese_alias_response = client.get(
        f"/api/projects/{project_id}/research-plan/timeline",
        params={"locale": "Japanese"},
    )
    assert japanese_alias_response.status_code == 200
    japanese_alias = japanese_alias_response.json()
    assert japanese_alias["response_locale"] == "Japanese"
    assert japanese_alias["blocks"][0]["title"] == "深いEDA"
    assert japanese_alias["blocks"][1]["title"] == "計画ブロック"
    assert japanese_alias["blocks"][1]["subtitle"] == ""
    assert japanese_alias["blocks"][1]["localization_status"] == "needs_locale_refresh"


def test_research_plan_timeline_requests_locale_refresh_for_active_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan locale refresh"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_plan_locale_refresh"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        session = AgentSession(
            id="ags_plan_locale_refresh",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep the plan display aligned with the user locale.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_plan",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "codex_added_plan",
                        "title": "approved target rebuild and evaluation",
                        "why_it_matters": "Resolve target policy, rerun evaluation, and update model diagnostics.",
                        "status": "active",
                    }
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline?locale=ja-JP")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["localization"]["missing_block_count"] == 1
    assert timeline["blocks"][0]["title"] == "計画ブロック"
    assert timeline["blocks"][0]["subtitle"] == ""

    request_path = research_plan_locale_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "schema_version: tablex_research_plan_locale_request.v1" in request_text
    assert "locale: ja-JP" in request_text
    assert "missing_block_count: 1" in request_text

    with app.state.session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "ags_plan_locale_refresh",
                    AgentTranscriptEvent.event_type == "research_plan_locale_refresh_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["locale"] == "ja-JP"
        assert payload["missing_block_count"] == 1

    repeated = client.get(f"/api/projects/{project_id}/research-plan/timeline?locale=ja-JP")
    assert repeated.status_code == 200
    with app.state.session_factory() as db:
        event_count = db.scalar(
            select(func.count())
            .select_from(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == "ags_plan_locale_refresh",
                AgentTranscriptEvent.event_type == "research_plan_locale_refresh_requested",
            )
        )
        assert event_count == 1


def test_research_plan_timeline_uses_artifact_locale_and_codex_display_fields(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan display locale"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_plan_with_display_locale",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "project": {"locale": "ja-JP"},
                "timeline_blocks": [
                    {
                        "id": "approval_contract",
                        "title": "approval response contract",
                        "why_it_matters": "Keep the owner decision reversible and auditable.",
                        "next_action": "Review the response choices.",
                        "done_criteria": "The owner can answer without ambiguity.",
                        "blockers": ["Owner answer is missing."],
                        "display_title": "承認応答の設計",
                        "display_why_it_matters": "オーナー判断を可逆的かつ監査可能に保ちます。",
                        "display_next_action": "回答選択肢を確認します。",
                        "display_done_criteria": "オーナーが迷わず回答できること。",
                        "display_blockers": ["オーナー回答が未提出です。"],
                        "status": "active",
                        "subtasks": [
                            {
                                "id": "response_options",
                                "title": "response options",
                                "detail": "Check choices before publication.",
                                "status": "pending",
                                "human_display": {
                                    "title": "回答選択肢",
                                    "detail": "公開前に選択肢を確認します。",
                                },
                            }
                        ],
                    },
                    {
                        "id": "translation_map",
                        "title": "model review",
                        "why_it_matters": "Keep diagnostics readable.",
                        "status": "pending",
                        "translations": {
                            "ja": {
                                "title": "モデル確認",
                                "why_it_matters": "診断結果を読みやすく保ちます。",
                            }
                        },
                    },
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["requested_locale"] is None
    assert timeline["authored_locale"] == "ja-JP"
    assert timeline["response_locale"] == "ja-JP"
    assert timeline["localization"]["missing_block_count"] == 0
    assert timeline["blocks"][0]["title"] == "承認応答の設計"
    assert timeline["blocks"][0]["subtitle"] == "オーナー判断を可逆的かつ監査可能に保ちます。"
    assert timeline["blocks"][0]["next_action"] == "回答選択肢を確認します。"
    assert timeline["blocks"][0]["done_criteria"] == "オーナーが迷わず回答できること。"
    assert timeline["blocks"][0]["blockers"] == ["オーナー回答が未提出です。"]
    assert timeline["blocks"][0]["localization_status"] == "localized"
    assert timeline["blocks"][0]["subtasks"][0]["title"] == "回答選択肢"
    assert timeline["blocks"][0]["subtasks"][0]["detail"] == "公開前に選択肢を確認します。"
    assert timeline["blocks"][1]["title"] == "モデル確認"
    assert timeline["blocks"][1]["subtitle"] == "診断結果を読みやすく保ちます。"


def test_research_plan_timeline_refresh_uses_artifact_locale_when_query_locale_absent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Plan artifact locale refresh"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    app = cast(Any, client.app)
    workspace = app.state.artifact_store.root / "agent_sessions" / project_id / "ags_artifact_locale_refresh"

    with app.state.session_factory() as db:
        project = db.get(Project, project_id)
        assert project is not None
        project.current_phase = "AUTONOMOUS_LOOP"
        session = AgentSession(
            id="ags_artifact_locale_refresh",
            project_id=project_id,
            org_id=project.org_id,
            session_type="main_autonomous",
            status="running",
            autonomy_mode="full_auto",
            runner_kind="codex_cli",
            goal_text="Keep locale-specific plan display current.",
            workspace_path=str(workspace),
            created_by="test",
        )
        db.add(session)
        store_json_artifact(
            db,
            app.state.artifact_store,
            project_id=project_id,
            asset_type="research_plan",
            name="codex_plan_artifact_locale",
            filename="research_plan.json",
            payload={
                "schema_version": "research_plan.v1",
                "project": {"locale": "ja-JP"},
                "timeline_blocks": [
                    {
                        "id": "codex_added_plan",
                        "title": "model review and deployment readiness",
                        "why_it_matters": "Explain the next validation work.",
                        "status": "active",
                    }
                ],
            },
            metadata={"source": "test"},
        )
        db.commit()

    response = client.get(f"/api/projects/{project_id}/research-plan/timeline")
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["requested_locale"] is None
    assert timeline["response_locale"] == "ja-JP"
    assert timeline["blocks"][0]["title"] == "計画ブロック"
    assert timeline["blocks"][0]["subtitle"] == ""
    assert timeline["blocks"][0]["localization_status"] == "needs_locale_refresh"
    assert "title" in timeline["blocks"][0]["missing_localization_fields"]
    request_path = research_plan_locale_request_path(workspace)
    assert request_path.exists()
    assert "locale: ja-JP" in request_path.read_text(encoding="utf-8")


def test_model_candidates_endpoint_queues_requested_models_into_leaderboard(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Candidate training", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,segment,target"]
    for index in range(1, 61):
        target = 1 if index % 3 == 0 else 0
        segment = "high" if index % 5 in {0, 1} else "low"
        rows.append(f"{index},{segment},{target}")
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("candidate_training.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    primary = next(item for item in candidates_response.json() if item["status"] == "primary_candidate")
    promote_response = client.post(f"/api/evaluation-candidates/{primary['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]
    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200, approve_response.text
    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text

    queue_response = client.post(
        f"/api/projects/{project_id}/model-candidates/run",
        json={"models": ["LightGBM", "LogisticRegression"]},
    )
    assert queue_response.status_code == 200, queue_response.text
    queued_training_job = queue_response.json()
    assert queued_training_job["job_type"] == "train_model_candidates"
    assert queued_training_job["status"] == "queued"
    assert set(queued_training_job["input"]["normalized_models"]) == {"lightgbm", "logistic_regression"}

    run_job_response = client.post(f"/api/jobs/{queued_training_job['id']}/run")
    assert run_job_response.status_code == 200, run_job_response.text
    nudged_job = run_job_response.json()
    assert nudged_job["status"] == "queued"
    assert nudged_job["priority"] >= 90

    interactive_worker_response = client.post("/api/worker/run-once")
    assert interactive_worker_response.status_code == 200, interactive_worker_response.text
    assert interactive_worker_response.json() is None
    queued_after_interactive_response = client.get(f"/api/projects/{project_id}/jobs")
    assert queued_after_interactive_response.status_code == 200
    queued_after_interactive = next(
        item for item in queued_after_interactive_response.json() if item["id"] == queued_training_job["id"]
    )
    assert queued_after_interactive["status"] == "queued"

    worker_response = client.post("/api/worker/run-once?include_long_running=true")
    assert worker_response.status_code == 200, worker_response.text
    training_job = worker_response.json()
    assert training_job["id"] == queued_training_job["id"]
    assert training_job["status"] == "succeeded"
    assert training_job["output"]["success_count"] == 2
    assert training_job["output"]["worker_events"][0]["display_name"] == "Training Worker"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard = leaderboard_response.json()
    assert len(leaderboard) == 2
    baseline_types = {row["metrics"]["baseline_type"] for row in leaderboard}
    assert baseline_types == {"lightgbm_classifier", "logistic_regression"}
    assert all(row["display_metric_name"] for row in leaderboard)


def test_core_harness_actions_use_explicit_endpoints(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Explicit action loop", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    rows = ["feature,segment,target"] + [f"{index},{'A' if index % 2 else 'B'},{index % 2}" for index in range(1, 14)]
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("explicit_actions.csv", "\n".join(rows).encode("utf-8"), "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "succeeded"
    assert quality_job["output"]["artifact_ids"]

    evaluation_response = client.post(f"/api/projects/{project_id}/evaluation/compare")
    assert evaluation_response.status_code == 200, evaluation_response.text
    evaluation_job = evaluation_response.json()
    assert evaluation_job["status"] == "succeeded"
    assert evaluation_job["output"]["artifact_id"]

    report_response = client.post(f"/api/projects/{project_id}/decision-report/generate")
    assert report_response.status_code == 200, report_response.text
    report_job = report_response.json()
    assert report_job["status"] == "succeeded"
    assert report_job["output"]["decision_report_artifact_id"]

    readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert readout_response.status_code == 200, readout_response.text
    readout = readout_response.json()
    assert readout["schema_version"] == "result_readout.v1"

def test_relational_schema_hint_upload_preview_and_agent_route(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "ER evidence"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    er_json = {
        "tables": [
            {"table_name": "customers", "columns": ["customer_id", "segment"]},
            {"table_name": "applications", "columns": ["application_id", "customer_id", "target"]},
        ],
        "relationships": [
            {
                "left_table": "customers",
                "left_column": "customer_id",
                "right_table": "applications",
                "right_column": "customer_id",
                "relation_type": "one_to_many",
                "confidence": 0.85,
            }
        ],
    }
    json_upload_response = client.post(
        f"/api/projects/{project_id}/relational/schema-hints/upload",
        files={"file": ("er_hint.json", json.dumps(er_json).encode("utf-8"), "application/json")},
        data={"note": "Customer to application relationship from source ERD."},
    )
    assert json_upload_response.status_code == 200, json_upload_response.text
    json_job = json_upload_response.json()
    assert json_job["status"] == "succeeded"
    assert json_job["output"]["schema_version"] == "relational_schema_hint.v1"
    assert json_job["output"]["parsed_table_count"] == 2
    assert json_job["output"]["parsed_relationship_count"] == 1

    json_preview_response = client.get(
        f"/api/artifacts/{json_job['output']['relational_schema_hint_artifact_id']}/preview"
    )
    assert json_preview_response.status_code == 200
    json_preview = json_preview_response.json()
    assert json_preview["content_type"] == "json"
    assert "customers" in json_preview["preview"]

    report_preview_response = client.get(
        f"/api/artifacts/{json_job['output']['relational_schema_hint_report_artifact_id']}/preview"
    )
    assert report_preview_response.status_code == 200
    report_preview = report_preview_response.json()["preview"]
    assert "Relational Schema Hint" in report_preview
    assert "customers.customer_id -> applications.customer_id" in report_preview

    png_upload_response = client.post(
        f"/api/projects/{project_id}/relational/schema-hints/upload",
        files={"file": ("er_diagram.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png")},
    )
    assert png_upload_response.status_code == 200, png_upload_response.text
    png_job = png_upload_response.json()
    png_preview_response = client.get(
        f"/api/artifacts/{png_job['output']['relational_schema_hint_artifact_id']}/preview"
    )
    assert png_preview_response.status_code == 200
    png_preview = png_preview_response.json()
    assert png_preview["content_type"] == "image/png"
    assert png_preview["preview_available"] is True
    assert png_preview["preview"].endswith("/download")



def test_upload_data_bundle_profiles_primary_supporting_tables_and_er_hint(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Bundle upload"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    application_csv = "\n".join(
        [
            "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL",
            "100001,0,150000",
            "100002,1,90000",
            "100003,0,120000",
        ]
    )
    bureau_csv = "\n".join(
        [
            "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE",
            "100001,50001,Active",
            "100001,50002,Closed",
            "100002,50003,Active",
        ]
    )
    er_json = {
        "tables": [{"name": "application_train"}, {"name": "bureau"}],
        "relationships": [
            {
                "left_table": "application_train",
                "left_column": "SK_ID_CURR",
                "right_table": "bureau",
                "right_column": "SK_ID_CURR",
                "relation_type": "one_to_many",
            }
        ],
    }

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload-bundle",
        files=[
            ("files", ("application_train.csv", application_csv.encode("utf-8"), "text/csv")),
            ("files", ("bureau.csv", bureau_csv.encode("utf-8"), "text/csv")),
            ("files", ("home_credit_er.json", json.dumps(er_json).encode("utf-8"), "application/json")),
        ],
        data={
            "primary_filename": "application_train.csv",
            "target_column": "TARGET",
            "note": "Home Credit style one-to-many relationship.",
        },
    )
    assert upload_response.status_code == 200, upload_response.text
    job = upload_response.json()
    assert job["status"] == "succeeded"
    assert job["output"]["schema_version"] == "upload_data_bundle.v1"
    assert job["output"]["dataset_snapshot_id"]
    assert len(job["output"]["supporting_table_artifact_ids"]) == 1
    assert len(job["output"]["relational_hint_artifact_ids"]) == 1
    assert job["output"]["relational_catalog_artifact_id"]
    assert job["output"]["relational_table_bundle_manifest_artifact_id"]
    assert job["output"]["analysis_notebook_artifact_id"] is None
    assert job["output"]["notebook_html_artifact_id"] is None
    assert job["output"]["notebook_kind"] is None
    assert job["output"]["notebook_warning"] == "awaiting_agent_authored_notebook"
    assert job["output"]["notebook_authoring_brief_artifact_ids"]
    assert job["output"]["runner_context"]["fixed_recipe_required"] is False

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {artifact["asset_type"] for artifact in artifacts_response.json()}
    assert "dataset_snapshot" in asset_types
    assert "uploaded_supporting_table" in asset_types
    assert "relational_schema_hint" in asset_types
    assert "relational_catalog" in asset_types
    assert "relational_table_bundle_manifest" in asset_types
    assert "analysis_notebook" not in asset_types
    assert "notebook_html" not in asset_types
    assert "notebook_authoring_brief" in asset_types

    catalog_preview_response = client.get(f"/api/artifacts/{job['output']['relational_catalog_artifact_id']}/preview")
    assert catalog_preview_response.status_code == 200
    catalog_preview = catalog_preview_response.json()
    assert catalog_preview["content_type"] == "json"
    assert "application_train" in catalog_preview["preview"]
    assert "runner_defined" in catalog_preview["preview"]



def test_portal_overview_ideas_and_agent_activity(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Portal Ops", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    idea_response = client.post("/api/portal/ideas", json={"text": "Make worker boxes transient and lively."})
    assert idea_response.status_code == 200, idea_response.text
    idea = idea_response.json()
    assert idea["artifact_id"]
    assert idea["text"].startswith("Make worker")

    ideas_response = client.get("/api/portal/ideas")
    assert ideas_response.status_code == 200
    assert any(item["id"] == idea["id"] for item in ideas_response.json())

    csv_bytes = b"feature,target\n1,0\n2,1\n3,0\n4,1\n"
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("portal.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    notebook_response = client.post(f"/api/projects/{project_id}/analysis-notebooks/data-understanding")
    assert notebook_response.status_code == 200, notebook_response.text
    notebook_job = notebook_response.json()
    assert notebook_job["status"] == "succeeded"
    assert notebook_job["job_type"] == "prepare_data_understanding_notebook_authoring"
    assert notebook_job["output"]["analysis_notebook_artifact_id"] is None
    assert notebook_job["output"]["notebook_authoring_brief_artifact_id"]

    eda_response = client.post(f"/api/datasets/{dataset_id}/eda-review")
    assert eda_response.status_code == 200, eda_response.text
    eda_job = eda_response.json()
    assert eda_job["status"] == "succeeded"
    assert eda_job["output"]["eda_review_html_artifact_id"]

    author_response = client.post(f"/api/projects/{project_id}/notebook-authoring/brief")
    assert author_response.status_code == 200, author_response.text
    author_job = author_response.json()
    assert author_job["status"] == "succeeded"
    assert author_job["output"]["notebook_authoring_brief_artifact_id"]

    chat_response = client.post(
        f"/api/projects/{project_id}/agent-chat",
        json={"message": "状況を説明してください", "locale": "ja-JP"},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat = chat_response.json()
    assert chat["intent"]["type"] == "agent_conversation"
    assert chat["actions"] == []
    assert chat["response_composer"]["status"] == "queued"

    run_queued_agent_chat_turn(client, chat["job"]["id"])
    history = client.get(f"/api/projects/{project_id}/agent-chat/history").json()
    assert history[-1]["response_brief"]["conversation_context"]["counts"]["datasets"] == 1

    activity_response = client.get(f"/api/projects/{project_id}/agent-activity")
    assert activity_response.status_code == 200
    activity = activity_response.json()
    assert activity["schema_version"] == "agent_activity.v1"

    overview_response = client.get("/api/portal/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["schema_version"] == "portal_overview.v1"
    assert overview["summary"]["project_count"] >= 1
    assert overview["summary"]["active_project_count"] == 1
    assert overview["summary"]["idea_count"] >= 1
    recent_updates = overview["recent_updates"]
    assert all("agent_chat_turn" not in update["title"] for update in recent_updates)
    assert all("agent_chat_turn" not in update["summary"] for update in recent_updates)

def test_project_upload_profile_evaluation_split_flow(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback")
    client = make_client(tmp_path)

    project_response = client.post(
        "/api/projects",
        json={"name": "Demo", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    csv_bytes = (
        b"customer_id,created_at,feature,target,final_status\n"
        b"c1,2026-01-01,10,1,won\n"
        b"c1,2026-01-02,11,0,lost\n"
        b"c2,2026-01-03,13,1,won\n"
        b"c2,2026-01-04,9,0,lost\n"
        b"c3,2026-01-05,8,1,won\n"
        b"c3,2026-01-06,7,0,lost\n"
    )
    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("demo.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]
    assert upload_response.json()["dataset_snapshot"]["row_count"] == 6

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    quality_job = quality_response.json()
    assert quality_job["status"] == "succeeded"
    assert len(quality_job["output"]["artifact_ids"]) == 3
    quality_gate = quality_job["output"]["gate"]
    assert quality_gate["schema_version"] == "data_quality_gate.v1"
    assert quality_gate["summary"]["severity"] in {"warning", "pass"}
    assert "final_status" in quality_gate["evaluation_guidance"]["excluded_columns"]
    assert quality_job["output"]["insight_id"]

    latest_quality_response = client.get(f"/api/datasets/{dataset_id}/quality/latest")
    assert latest_quality_response.status_code == 200
    quality_artifact_id = latest_quality_response.json()["id"]
    quality_preview_response = client.get(f"/api/artifacts/{quality_artifact_id}/preview")
    assert quality_preview_response.status_code == 200
    assert "data_quality_gate.v1" in quality_preview_response.json()["preview"]

    eda_review_response = client.post(f"/api/datasets/{dataset_id}/eda-review")
    assert eda_review_response.status_code == 200, eda_review_response.text
    eda_review_job = eda_review_response.json()
    assert eda_review_job["status"] == "succeeded"
    assert eda_review_job["job_type"] == "run_eda_review"
    assert eda_review_job["output"]["schema_version"] == "eda_review.v1"
    assert eda_review_job["output"]["eda_review_bundle_artifact_id"]
    assert eda_review_job["output"]["eda_review_html_artifact_id"]
    assert eda_review_job["output"]["eda_review_report_id"]
    assert len(eda_review_job["output"]["eda_review_figure_artifact_ids"]) >= 4
    eda_bundle_response = client.get(
        f"/api/artifacts/{eda_review_job['output']['eda_review_bundle_artifact_id']}/download"
    )
    assert eda_bundle_response.status_code == 200
    eda_bundle = eda_bundle_response.json()
    assert eda_bundle["schema_version"] == "eda_review.v1"
    assert eda_bundle["dataset_snapshot_id"] == dataset_id
    assert eda_bundle["summary"]["target_column"] == "target"
    assert eda_bundle["read_this_first"]
    assert eda_bundle["story_cards"]
    assert eda_bundle["playbook"]
    assert eda_bundle["codex_next_prompts"]
    eda_html_response = client.get(
        f"/api/artifacts/{eda_review_job['output']['eda_review_html_artifact_id']}/preview"
    )
    assert eda_html_response.status_code == 200
    eda_html = eda_html_response.json()
    assert eda_html["content_type"] == "text/html"
    assert "Tablex Data Review" in eda_html["preview"]
    assert "Read this first" in eda_html["preview"]
    assert "Visual story cards" in eda_html["preview"]
    assert "Ask Codex next" in eda_html["preview"]
    eda_inline_response = client.get(
        f"/api/artifacts/{eda_review_job['output']['eda_review_html_artifact_id']}/inline-preview"
    )
    assert eda_inline_response.status_code == 200
    assert eda_inline_response.headers["content-type"].startswith("text/html")
    assert "content-disposition" not in eda_inline_response.headers
    assert "Tablex Data Review" in eda_inline_response.text
    eda_svg_response = client.get(
        f"/api/artifacts/{eda_review_job['output']['eda_review_figure_artifact_ids'][0]}/preview"
    )
    assert eda_svg_response.status_code == 200
    assert eda_svg_response.json()["content_type"] == "image/svg+xml"

    eda_story_response = client.get(f"/api/projects/{project_id}/analysis-story")
    assert eda_story_response.status_code == 200, eda_story_response.text
    eda_story = eda_story_response.json()
    assert eda_story["schema_version"] == "analysis_story_surface.v1"
    assert eda_story["available"] is True
    assert eda_story["story"]["source_type"] == "eda_review"
    assert eda_story["story"]["selected_source"]["preview_artifact_id"] == eda_review_job["output"]["eda_review_html_artifact_id"]
    assert eda_story["story"]["read_order"]
    assert eda_story["story"]["visual_story_cards"]
    assert eda_story["story"]["codex_prompts"]

    assumptions_response = client.get(f"/api/projects/{project_id}/assumptions")
    assert assumptions_response.status_code == 200
    assumptions = assumptions_response.json()
    assert any(item["fallback_policy"] == "exclude_until_confirmed" for item in assumptions)

    review_queue_response = client.get(f"/api/projects/{project_id}/assumptions/review-queue")
    assert review_queue_response.status_code == 200, review_queue_response.text
    review_queue = review_queue_response.json()
    assert review_queue["schema_version"] == "assumption_review_queue.v1"
    assert review_queue["counts"]["total_assumptions"] >= 1
    assert review_queue["next_item"]["item_type"] in {"assumption", "question"}
    assert review_queue["next_item"]["primary_actions"]
    if review_queue["next_item"]["item_type"] == "assumption":
        assert review_queue["next_item"]["evidence"]
        confirm_review_response = client.post(f"/api/assumptions/{review_queue['next_item']['id']}/confirm")
        assert confirm_review_response.status_code == 200, confirm_review_response.text
        next_review_queue_response = client.get(f"/api/projects/{project_id}/assumptions/review-queue")
        assert next_review_queue_response.status_code == 200
        assert next_review_queue_response.json()["next_item"]["id"] != review_queue["next_item"]["id"]

    understanding_response = client.get(f"/api/projects/{project_id}/understanding/latest")
    assert understanding_response.status_code == 200
    assert "Data Understanding" in understanding_response.json()["markdown"]

    notebook_response = client.post(f"/api/projects/{project_id}/analysis-notebooks/data-understanding")
    assert notebook_response.status_code == 200, notebook_response.text
    notebook_job = notebook_response.json()
    assert notebook_job["status"] == "succeeded"
    assert notebook_job["job_type"] == "prepare_data_understanding_notebook_authoring"
    assert notebook_job["output"]["schema_version"] == "notebook_authoring_preparation.v1"
    assert notebook_job["output"]["execution_status"] == "awaiting_agent_authored_notebook"
    assert notebook_job["output"]["analysis_notebook_artifact_id"] is None
    assert notebook_job["output"]["notebook_html_artifact_id"] is None
    assert notebook_job["output"]["notebook_run_manifest_artifact_id"] is None
    assert notebook_job["output"]["notebook_report_id"] is None
    assert notebook_job["output"]["notebook_authoring_brief_artifact_id"]

    authoring_preview_response = client.get(
        f"/api/artifacts/{notebook_job['output']['notebook_authoring_brief_artifact_id']}/preview"
    )
    assert authoring_preview_response.status_code == 200
    authoring_preview = authoring_preview_response.json()
    assert authoring_preview["preview_available"] is True
    assert authoring_preview["content_type"] == "json"
    assert "notebook_authoring_brief.v1" in authoring_preview["preview"]

    notebook_index_response = client.get(f"/api/projects/{project_id}/analysis-notebooks")
    assert notebook_index_response.status_code == 200
    notebook_index = notebook_index_response.json()
    assert notebook_index["counts"]["total"] == 0

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    first_question = questions_response.json()[0]
    answer_response = client.post(
        f"/api/questions/{first_question['id']}/answer",
        json={"answer_value": first_question["choices"][0], "answer_text": "integration test"},
    )
    assert answer_response.status_code == 200
    assert answer_response.json()["question_id"] == first_question["id"]

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200
    assert design_response.json()["status"] == "succeeded"

    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    primary = next(item for item in candidates if item["status"] == "primary_candidate")
    assert primary["split_type"] == "stratified"
    assert primary["stratify_column"] == "target"

    scenario_compare_response = client.post(f"/api/projects/{project_id}/evaluation/compare")
    assert scenario_compare_response.status_code == 200, scenario_compare_response.text
    scenario_compare_job = scenario_compare_response.json()
    assert scenario_compare_job["status"] == "succeeded"
    assert scenario_compare_job["output"]["artifact_id"]
    assert scenario_compare_job["output"]["candidate_count"] >= 2
    scenario_compare_preview_response = client.get(
        f"/api/artifacts/{scenario_compare_job['output']['artifact_id']}/preview"
    )
    assert scenario_compare_preview_response.status_code == 200
    scenario_compare_preview = scenario_compare_preview_response.json()["preview"]
    assert "evaluation_scenario_comparison.v1" in scenario_compare_preview
    assert "decision_support" in scenario_compare_preview

    promote_response = client.post(f"/api/evaluation-candidates/{primary['id']}/promote")
    assert promote_response.status_code == 200
    spec_id = promote_response.json()["id"]

    approval_review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert approval_review_response.status_code == 200, approval_review_response.text
    approval_review_job = approval_review_response.json()
    assert approval_review_job["status"] == "succeeded"
    assert approval_review_job["output"]["artifact_id"]
    assert approval_review_job["output"]["review_status"] in {"ready", "ready_with_assumptions"}
    approval_review_preview_response = client.get(
        f"/api/artifacts/{approval_review_job['output']['artifact_id']}/preview"
    )
    assert approval_review_preview_response.status_code == 200
    approval_review_preview = approval_review_preview_response.json()["preview"]
    assert "evaluation_approval_review.v1" in approval_review_preview
    assert "assumption_backed_proceed" in approval_review_preview

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text
    split = split_response.json()
    assert split["train_count"] > 0
    assert split["valid_count"] > 0
    assert split["project_id"] == project_id

    strategy_plan_response = client.post(f"/api/projects/{project_id}/baseline/strategy-plan")
    assert strategy_plan_response.status_code == 200, strategy_plan_response.text
    strategy_plan_job = strategy_plan_response.json()
    assert strategy_plan_job["status"] == "succeeded"
    assert strategy_plan_job["output"]["baseline_strategy_plan_artifact_id"]
    strategy_preview_response = client.get(
        f"/api/artifacts/{strategy_plan_job['output']['baseline_strategy_plan_artifact_id']}/preview"
    )
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "baseline_strategy_plan.v1" in strategy_preview
    assert "adaptive_baseline_planning" in strategy_preview
    assert "reporting_plan" in strategy_preview


    strategy_brief_response = client.get(f"/api/projects/{project_id}/approach/strategy-brief")
    assert strategy_brief_response.status_code == 200, strategy_brief_response.text
    strategy_brief = strategy_brief_response.json()
    assert strategy_brief["schema_version"] == "adaptive_strategy_brief.v1"
    assert strategy_brief["summary"]["fixed_recipe_policy"] == "advisory_candidates_only"
    assert strategy_brief["codex_handoff"]["autonomy_policy"]["can_propose_new_approach_classes"] is True
    assert strategy_brief["codex_handoff"]["autonomy_policy"]["must_emit_approach_decision_trace"] is True
    assert any(lane["lane_id"] == "adaptive_baseline" for lane in strategy_brief["candidate_lanes"])

    strategy_brief_job_response = client.post(f"/api/projects/{project_id}/approach/strategy-brief")
    assert strategy_brief_job_response.status_code == 200, strategy_brief_job_response.text
    strategy_brief_job = strategy_brief_job_response.json()
    assert strategy_brief_job["status"] == "succeeded"
    assert strategy_brief_job["output"]["adaptive_strategy_brief_artifact_id"]
    assert strategy_brief_job["output"]["adaptive_strategy_report_artifact_id"]
    assert strategy_brief_job["output"]["visualization_artifact_id"]
    strategy_brief_preview_response = client.get(
        f"/api/artifacts/{strategy_brief_job['output']['adaptive_strategy_brief_artifact_id']}/preview"
    )
    assert strategy_brief_preview_response.status_code == 200
    assert "adaptive_strategy_brief.v1" in strategy_brief_preview_response.json()["preview"]

    baseline_response = client.post(f"/api/projects/{project_id}/baseline/run")
    assert baseline_response.status_code == 200, baseline_response.text
    baseline_job = baseline_response.json()
    assert baseline_job["status"] == "succeeded"
    assert baseline_job["output"]["experiment_run_id"]
    assert baseline_job["output"]["model_version_id"]
    baseline_metrics = baseline_job["output"]["metrics"]
    assert baseline_metrics["model_baseline_attempted"] is True
    assert baseline_metrics["baseline_type"] in {"xgboost_classifier", "logistic_regression", "majority_classifier"}
    assert baseline_metrics["primary_metric_value"] >= 0
    assert "roc_auc" in baseline_metrics
    assert len(baseline_job["output"]["artifact_ids"]) >= 7

    leaderboard_metric_response = client.post(
        f"/api/projects/{project_id}/leaderboard/metric",
        json={"metric": "ROCーAUC"},
    )
    assert leaderboard_metric_response.status_code == 200, leaderboard_metric_response.text
    assert leaderboard_metric_response.json()["metric"] == "roc_auc"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200, leaderboard_response.text
    leaderboard = leaderboard_response.json()
    assert leaderboard[0]["run_id"] == baseline_job["output"]["experiment_run_id"]
    assert leaderboard[0]["display_metric_name"] == "roc_auc"
    assert leaderboard[0]["display_metric_source"] == "metric_preference"
    assert leaderboard[0]["display_metric_available"] is True
    assert abs(leaderboard[0]["display_metric_value"] - baseline_metrics["roc_auc"]) <= 1e-12


    initial_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert initial_readout_response.status_code == 200, initial_readout_response.text
    initial_readout = initial_readout_response.json()
    assert initial_readout["schema_version"] == "result_readout.v1"
    assert initial_readout["top_run"]["id"] == baseline_job["output"]["experiment_run_id"]
    assert initial_readout["evaluation_contract"]["status"] == "ready"
    assert initial_readout["next_action"]["target_tab"] == "Leaderboard"

    result_notebook_response = client.post(f"/api/projects/{project_id}/results/notebook-evidence")
    assert result_notebook_response.status_code == 200, result_notebook_response.text
    result_notebook_job = result_notebook_response.json()
    assert result_notebook_job["status"] == "succeeded"
    assert result_notebook_job["job_type"] == "prepare_result_notebook_evidence"
    assert result_notebook_job["output"]["schema_version"] == "result_notebook_evidence.v1"
    assert result_notebook_job["output"]["top_run_id"] == baseline_job["output"]["experiment_run_id"]
    assert result_notebook_job["output"]["analysis_notebook_artifact_id"] is None
    assert result_notebook_job["output"]["notebook_evidence_html_artifact_id"] is None
    assert result_notebook_job["output"]["preview_artifact_id"] is None
    assert result_notebook_job["output"]["capture_mode"] == "not_created_by_harness"
    assert result_notebook_job["output"]["execution_status"] == "awaiting_agent_authored_notebook"
    assert result_notebook_job["output"]["notebook_authoring_brief_artifact_id"]

    notebook_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert notebook_readout_response.status_code == 200, notebook_readout_response.text
    notebook_readout = notebook_readout_response.json()
    assert notebook_readout["notebook"]["status"] in {"missing", "partial", "attention"}
    assert notebook_readout["notebook"]["action_endpoint"].endswith("/results/notebook-evidence")
    assert notebook_readout["read_order"][3]["target_tab"] == "Notebooks"
    assert notebook_readout["read_order"][3]["artifact_id"] is None


    compare_runs_response = client.post(f"/api/projects/{project_id}/experiments/compare")
    assert compare_runs_response.status_code == 200, compare_runs_response.text
    compare_runs_job = compare_runs_response.json()
    assert compare_runs_job["status"] == "succeeded"
    assert compare_runs_job["output"]["artifact_ids"]

    comparison_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert comparison_readout_response.status_code == 200, comparison_readout_response.text
    comparison_readout = comparison_readout_response.json()
    assert comparison_readout["comparison"]["available"] is True
    assert comparison_readout["comparison"]["report_artifact"]["asset_type"] == "experiment_comparison_report"
    assert comparison_readout["read_order"][0]["title"] == "Read the result"

    model_response = client.get(f"/api/model-versions/{baseline_job['output']['model_version_id']}")
    assert model_response.status_code == 200, model_response.text
    model_version = model_response.json()
    assert model_version["model_family"] == "xgboost"
    assert model_version["model_type"] == "xgboost_classifier"
    assert model_version["artifact_id"]

    model_versions_response = client.get(f"/api/projects/{project_id}/model-versions")
    assert model_versions_response.status_code == 200
    assert model_versions_response.json()[0]["id"] == model_version["id"]

    validate_response = client.post(f"/api/model-versions/{model_version['id']}/validate")
    assert validate_response.status_code == 200, validate_response.text
    validate_job = validate_response.json()
    assert validate_job["status"] == "succeeded"
    assert validate_job["output"]["model_version_id"] == model_version["id"]
    assert validate_job["output"]["metrics"]["max_abs_metric_delta"] <= 1e-9
    assert len(validate_job["output"]["artifact_ids"]) == 3

    validation_history_response = client.get(f"/api/model-versions/{model_version['id']}/validations")
    assert validation_history_response.status_code == 200
    validation_history = validation_history_response.json()
    assert validation_history[0]["job"]["id"] == validate_job["id"]
    assert validation_history[0]["validation_status"] == "passed"
    assert validation_history[0]["max_abs_metric_delta"] <= 1e-9
    assert len(validation_history[0]["artifacts"]) == 3

    jobs_response = client.get(f"/api/projects/{project_id}/jobs")
    assert jobs_response.status_code == 200
    job_types = [item["job_type"] for item in jobs_response.json()]
    assert "validate_model_package" in job_types
    assert "run_baseline" in job_types
    assert "compare_evaluation_scenarios" in job_types
    assert "review_evaluation_approval" in job_types

    approval_job_response = client.post(
        "/api/jobs",
        json={
            "job_type": "run_agent_task",
            "project_id": project_id,
            "input": {"purpose": "approval gate integration test"},
            "policy": {"network": "restricted"},
            "max_attempts": 2,
        },
    )
    assert approval_job_response.status_code == 200, approval_job_response.text
    approval_job = approval_job_response.json()
    assert approval_job["status"] == "approval_required"
    assert approval_job["approval_required"] is True

    approve_job_response = client.post(f"/api/jobs/{approval_job['id']}/approve")
    assert approve_job_response.status_code == 200
    assert approve_job_response.json()["status"] == "queued"
    assert approve_job_response.json()["approved_by"] == "local-user"

    worker_response = client.post("/api/worker/run-once")
    assert worker_response.status_code == 200, worker_response.text
    assert worker_response.json() is None
    queued_approval_response = client.get(f"/api/projects/{project_id}/jobs")
    assert queued_approval_response.status_code == 200
    queued_approval = next(item for item in queued_approval_response.json() if item["id"] == approval_job["id"])
    assert queued_approval["status"] == "queued"

    dependency_a_response = client.post(
        "/api/jobs",
        json={
            "job_type": "agent_chat_turn",
            "project_id": project_id,
            "input": {"message": "dependency-a", "locale": "en-US"},
        },
    )
    assert dependency_a_response.status_code == 200
    dependency_a = dependency_a_response.json()
    dependency_b_response = client.post(
        "/api/jobs",
        json={
            "job_type": "agent_chat_turn",
            "project_id": project_id,
            "input": {"message": "dependency-b", "locale": "en-US"},
            "dependency_job_ids": [dependency_a["id"]],
            "priority": 100,
        },
    )
    assert dependency_b_response.status_code == 200
    dependency_b = dependency_b_response.json()
    first_dependency_worker_response = client.post("/api/worker/run-once")
    assert first_dependency_worker_response.status_code == 200
    assert first_dependency_worker_response.json()["id"] == dependency_a["id"]
    second_dependency_worker_response = client.post("/api/worker/run-once")
    assert second_dependency_worker_response.status_code == 200
    assert second_dependency_worker_response.json()["id"] == dependency_b["id"]

    cancel_retry_response = client.post(
        "/api/jobs",
        json={
            "job_type": "infer_assumptions",
            "project_id": project_id,
            "input": {"purpose": "cancel-retry integration test"},
            "max_attempts": 2,
        },
    )
    assert cancel_retry_response.status_code == 200
    cancel_retry_job = cancel_retry_response.json()
    cancel_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    retry_response = client.post(f"/api/jobs/{cancel_retry_job['id']}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "queued"

    seed_assets_response = client.post("/api/assets/seed-defaults")
    assert seed_assets_response.status_code == 200
    seeded_assets = seed_assets_response.json()
    assert len(seeded_assets) >= 15
    seeded_asset_names = {item["name"] for item in seeded_assets}
    assert {
        "tabular_gradient_boosting_strategy",
        "tablex_grandmaster_eda",
        "xgboost_mixed_type_baseline",
        "text_tfidf_train_fold_recipe",
        "causal_time_lag_rolling_features",
        "relational_aggregation_recipe",
        "decision_report_prompt",
    }.issubset(seeded_asset_names)
    skill_asset = next(item for item in seeded_assets if item["asset_type"] == "skill")

    research_plan_response = client.post(f"/api/projects/{project_id}/approach/research-plan")
    assert research_plan_response.status_code == 200, research_plan_response.text
    research_plan_job = research_plan_response.json()
    assert research_plan_job["status"] == "succeeded"
    research_plan_artifact_id = research_plan_job["output"]["artifact_id"]
    assert research_plan_job["output"]["schema_version"] == "research_plan.v1"
    assert research_plan_job["output"]["query_count"] >= 2
    assert research_plan_job["output"]["recommended_asset_count"] >= 4
    assert research_plan_job["output"]["network_default"] == "disabled_until_runner_policy_allows"

    research_plan_preview_response = client.get(f"/api/artifacts/{research_plan_artifact_id}/preview")
    assert research_plan_preview_response.status_code == 200
    research_plan_preview = research_plan_preview_response.json()["preview"]
    assert "research_plan.v1" in research_plan_preview
    research_plan_download_response = client.get(f"/api/artifacts/{research_plan_artifact_id}/download")
    assert research_plan_download_response.status_code == 200
    research_plan_download = research_plan_download_response.text
    assert "controlled_web_search" in research_plan_download
    assert "connector_credentials" in research_plan_download
    assert "xgboost_mixed_type_baseline" in research_plan_download
    assert "causal_time_lag_rolling_features" in research_plan_download

    source_pack_response = client.post(f"/api/projects/{project_id}/approach/research-source-pack")
    assert source_pack_response.status_code == 200, source_pack_response.text
    source_pack_job = source_pack_response.json()
    assert source_pack_job["status"] == "succeeded"
    assert source_pack_job["output"]["schema_version"] == "research_source_pack.v1"
    assert source_pack_job["output"]["research_plan_artifact_id"] == research_plan_artifact_id
    assert source_pack_job["output"]["research_source_pack_artifact_id"]
    assert source_pack_job["output"]["research_source_report_artifact_id"]
    assert source_pack_job["output"]["project_source_count"] >= 1
    assert source_pack_job["output"]["library_source_count"] >= 4
    assert source_pack_job["output"]["network_default"] == "disabled_until_runner_policy_allows"

    source_pack_preview_response = client.get(
        f"/api/artifacts/{source_pack_job['output']['research_source_report_artifact_id']}/preview"
    )
    assert source_pack_preview_response.status_code == 200
    source_pack_preview = source_pack_preview_response.json()["preview"]
    assert "Research Source Pack" in source_pack_preview
    assert "Connector credentials" in source_pack_preview or "connector credentials" in source_pack_preview

    research_stub_response = client.post(
        f"/api/research-source-packs/{source_pack_job['output']['research_source_pack_artifact_id']}/run-local-stub"
    )
    assert research_stub_response.status_code == 200, research_stub_response.text
    research_stub_job = research_stub_response.json()
    assert research_stub_job["status"] == "succeeded"
    assert research_stub_job["output"]["research_run_manifest_artifact_id"]
    assert research_stub_job["output"]["research_findings_report_id"]
    assert research_stub_job["output"]["research_findings_report_artifact_id"]
    assert research_stub_job["output"]["source_citation_manifest_artifact_id"]
    assert research_stub_job["output"]["visualization_id"]
    assert research_stub_job["output"]["evidence_id"]
    assert research_stub_job["output"]["external_network_accessed"] is False
    assert research_stub_job["output"]["connector_credentials_materialized"] is False

    research_stub_report_response = client.get(
        f"/api/artifacts/{research_stub_job['output']['research_findings_report_artifact_id']}/preview"
    )
    assert research_stub_report_response.status_code == 200
    research_stub_report = research_stub_report_response.json()["preview"]
    assert "Controlled Research Runner Stub" in research_stub_report
    assert "External network accessed: false" in research_stub_report

    research_synthesis_response = client.post(f"/api/projects/{project_id}/approach/research-synthesis")
    assert research_synthesis_response.status_code == 200, research_synthesis_response.text
    research_synthesis_job = research_synthesis_response.json()
    assert research_synthesis_job["status"] == "succeeded"
    assert research_synthesis_job["output"]["schema_version"] == "research_finding_synthesis.v1"
    assert research_synthesis_job["output"]["research_finding_synthesis_artifact_id"]
    assert research_synthesis_job["output"]["research_finding_synthesis_report_id"]
    assert research_synthesis_job["output"]["research_finding_synthesis_report_artifact_id"]
    assert research_synthesis_job["output"]["visualization_id"]
    assert research_synthesis_job["output"]["evidence_id"]
    assert research_synthesis_job["output"]["external_network_accessed"] is False
    assert research_synthesis_job["output"]["has_only_stub_findings"] is True

    research_synthesis_report_response = client.get(
        f"/api/artifacts/{research_synthesis_job['output']['research_finding_synthesis_report_artifact_id']}/preview"
    )
    assert research_synthesis_report_response.status_code == 200
    research_synthesis_report = research_synthesis_report_response.json()["preview"]
    assert "Research Finding Synthesis" in research_synthesis_report
    assert "Stub-only findings: true" in research_synthesis_report

    agent_task_plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert agent_task_plan_response.status_code == 200, agent_task_plan_response.text
    agent_task_plan_job = agent_task_plan_response.json()
    assert agent_task_plan_job["status"] == "succeeded"
    assert agent_task_plan_job["output"]["schema_version"] == "agent_task_planning.v1"
    assert agent_task_plan_job["output"]["agent_task_contract_artifact_id"]
    assert agent_task_plan_job["output"]["recommended_approach_count"] >= 2
    assert agent_task_plan_job["output"]["research_query_count"] >= 2
    assert agent_task_plan_job["output"]["recommended_asset_count"] >= 4

    agent_task_plan_preview_response = client.get(
        f"/api/artifacts/{agent_task_plan_job['output']['agent_task_contract_artifact_id']}/preview"
    )
    assert agent_task_plan_preview_response.status_code == 200
    assert agent_task_plan_preview_response.json()["preview_available"] is True
    agent_task_plan_download_response = client.get(
        f"/api/artifacts/{agent_task_plan_job['output']['agent_task_contract_artifact_id']}/download"
    )
    assert agent_task_plan_download_response.status_code == 200
    agent_task_contract = agent_task_plan_download_response.json()
    assert agent_task_contract["inputs"]["schema_version"] == "agent_task_planning.v1"
    assert len(agent_task_contract["inputs"]["recommended_approach_candidates"]) >= 2
    assert "reporting_requirements" in agent_task_contract["inputs"]
    assert agent_task_contract["inputs"]["research_source_pack"]["artifact_id"] == source_pack_job["output"][
        "research_source_pack_artifact_id"
    ]
    assert agent_task_contract["inputs"]["research_finding_synthesis"]["artifact_id"] == research_synthesis_job[
        "output"
    ]["research_finding_synthesis_artifact_id"]
    assert agent_task_contract["inputs"]["research_finding_synthesis"]["citation_audit"][
        "external_network_accessed"
    ] is False
    assert agent_task_contract["inputs"]["research_source_policy"]["network_default"] == (
        "disabled_until_runner_policy_allows"
    )
    assert agent_task_contract["inputs"]["adaptive_strategy_brief"]["artifact_id"] == strategy_brief_job["output"][
        "adaptive_strategy_brief_artifact_id"
    ]
    assert agent_task_contract["inputs"]["open_ended_approach_space"]["strategy_brief_available"] is True
    assert "skills/tablex-grandmaster-eda/SKILL.md" in agent_task_contract["context_files"]
    assert any(
        item["role"] == "adaptive_strategy_brief"
        and item["artifact_id"] == strategy_brief_job["output"]["adaptive_strategy_brief_artifact_id"]
        for item in agent_task_contract["inputs"]["available_context_artifacts"]
    )
    assert any(
        item["name"] == "xgboost_mixed_type_baseline"
        for item in agent_task_contract["inputs"]["library_recommendations"]
    )

    agent_task_job_artifacts_response = client.get(f"/api/jobs/{agent_task_plan_job['id']}/artifacts")
    assert agent_task_job_artifacts_response.status_code == 200
    agent_task_job_artifacts = agent_task_job_artifacts_response.json()
    assert agent_task_job_artifacts["summary"]["task_id"] == agent_task_plan_job["output"]["task_id"]
    assert agent_task_job_artifacts["summary"]["recommended_approach_count"] >= 2
    assert agent_task_job_artifacts["missing_artifact_ids"] == []
    assert agent_task_job_artifacts["artifacts"][0]["asset_type"] == "agent_task_contract"

    planned_workspace_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_job['output']['agent_task_contract_artifact_id']}/prepare-workspace"
    )
    assert planned_workspace_response.status_code == 200, planned_workspace_response.text
    planned_workspace_job = planned_workspace_response.json()
    assert planned_workspace_job["status"] == "succeeded"
    assert planned_workspace_job["output"]["schema_version"] == "agent_workspace_manifest.v1"
    assert planned_workspace_job["output"]["agent_workspace_manifest_artifact_id"]
    assert planned_workspace_job["output"]["agent_task_contract_artifact_id"] == agent_task_plan_job["output"][
        "agent_task_contract_artifact_id"
    ]
    assert planned_workspace_job["output"]["materialized_context_count"] >= 4
    assert planned_workspace_job["output"]["materialized_library_asset_count"] >= 4

    planned_workspace_download_response = client.get(
        f"/api/artifacts/{planned_workspace_job['output']['agent_workspace_manifest_artifact_id']}/download"
    )
    assert planned_workspace_download_response.status_code == 200
    planned_workspace_manifest = planned_workspace_download_response.json()
    assert planned_workspace_manifest["source_contract_artifact_id"] == agent_task_plan_job["output"][
        "agent_task_contract_artifact_id"
    ]
    assert ".harness/task_contract.json" in planned_workspace_manifest["files"]
    assert ".harness/agent_result.schema.json" in planned_workspace_manifest["files"]
    assert ".harness/execution_policy.json" in planned_workspace_manifest["files"]
    assert "README.md" in planned_workspace_manifest["files"]
    assert any(
        item["context_path"].startswith(".harness/context/library_assets/")
        for item in planned_workspace_manifest["materialized_sources"]
    )
    assert any(
        item["artifact_id"] == strategy_brief_job["output"]["adaptive_strategy_brief_artifact_id"]
        and item["source_kind"] == "context_artifact"
        for item in planned_workspace_manifest["materialized_sources"]
    )

    planned_workspace_job_artifacts_response = client.get(f"/api/jobs/{planned_workspace_job['id']}/artifacts")
    assert planned_workspace_job_artifacts_response.status_code == 200
    planned_workspace_job_artifacts = planned_workspace_job_artifacts_response.json()
    assert planned_workspace_job_artifacts["summary"]["agent_workspace_manifest_artifact_id"]
    assert planned_workspace_job_artifacts["summary"]["materialized_library_asset_count"] >= 4
    assert any(
        item["asset_type"] == "agent_workspace_manifest"
        for item in planned_workspace_job_artifacts["artifacts"]
    )

    readiness_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_job['output']['agent_task_contract_artifact_id']}/readiness-review"
    )
    assert readiness_response.status_code == 200, readiness_response.text
    readiness_job = readiness_response.json()
    assert readiness_job["status"] == "succeeded"
    assert readiness_job["output"]["schema_version"] == "agent_task_readiness_review.v1"
    assert readiness_job["output"]["agent_task_readiness_review_artifact_id"]
    assert readiness_job["output"]["agent_task_readiness_report_artifact_id"]
    assert readiness_job["output"]["visualization_artifact_id"]
    assert readiness_job["output"]["readiness_status"] in {"ready", "ready_with_warnings", "blocked"}
    assert readiness_job["output"]["blocker_count"] == 0
    assert readiness_job["output"]["pass_count"] > 0
    assert isinstance(readiness_job["output"]["next_actions"], list)

    readiness_download_response = client.get(
        f"/api/artifacts/{readiness_job['output']['agent_task_readiness_review_artifact_id']}/download"
    )
    assert readiness_download_response.status_code == 200
    readiness_payload = readiness_download_response.json()
    assert readiness_payload["schema_version"] == "agent_task_readiness_review.v1"
    assert readiness_payload["pass_count"] == readiness_job["output"]["pass_count"]
    assert readiness_payload["workspace_artifact_id"] == planned_workspace_job["output"][
        "agent_workspace_manifest_artifact_id"
    ]
    artifacts_after_readiness = client.get(f"/api/projects/{project_id}/artifacts").json()
    readiness_artifact = next(
        item for item in artifacts_after_readiness if item["id"] == readiness_job["output"]["agent_task_readiness_review_artifact_id"]
    )
    assert readiness_artifact["metadata"]["pass_count"] == readiness_job["output"]["pass_count"]
    assert "first_next_action" in readiness_artifact["metadata"]
    assert any(item["check_id"] == "workspace_manifest" for item in readiness_payload["checks"])
    strategy_readiness_check = next(
        item for item in readiness_payload["checks"] if item["check_id"] == "adaptive_strategy_context"
    )
    assert strategy_readiness_check["status"] == "pass"

    readiness_report_preview_response = client.get(
        f"/api/artifacts/{readiness_job['output']['agent_task_readiness_report_artifact_id']}/preview"
    )
    assert readiness_report_preview_response.status_code == 200
    assert "Agent Task Readiness Review" in readiness_report_preview_response.json()["preview"]

    planned_stub_response = client.post(
        f"/api/agent-task-contracts/{agent_task_plan_job['output']['agent_task_contract_artifact_id']}/run-local-stub"
    )
    assert planned_stub_response.status_code == 200, planned_stub_response.text
    planned_stub_job = planned_stub_response.json()
    assert planned_stub_job["status"] == "succeeded"
    assert planned_stub_job["output"]["agent_status"] == "succeeded"
    assert planned_stub_job["output"]["readiness_status"] in {"ready", "ready_with_warnings"}
    assert planned_stub_job["output"]["auto_prepared_workspace"] is False
    assert len(planned_stub_job["output"]["ingested_artifact_ids"]) == 9
    assert planned_stub_job["output"]["report_id"]
    assert planned_stub_job["output"]["evidence_id"]
    assert planned_stub_job["output"]["experiment_run_id"]
    assert planned_stub_job["output"]["agent_metrics_artifact_id"]
    assert planned_stub_job["output"]["agent_feature_recipe_artifact_id"]
    assert planned_stub_job["output"]["approach_decision_trace_artifact_id"]
    assert planned_stub_job["output"]["source_citation_manifest_artifact_id"]
    assert planned_stub_job["output"]["citation_audit_report_id"]
    assert planned_stub_job["output"]["citation_audit_report_artifact_id"]
    assert planned_stub_job["output"]["citation_evidence_id"]
    assert planned_stub_job["output"]["citation_visualization_id"]
    assert planned_stub_job["output"]["citation_visualization_artifact_id"]
    assert len(planned_stub_job["output"]["visualization_ids"]) == 1
    assert planned_stub_job["output"]["requires_human_review"] is True

    planned_trace_download_response = client.get(
        f"/api/artifacts/{planned_stub_job['output']['approach_decision_trace_artifact_id']}/download"
    )
    assert planned_trace_download_response.status_code == 200
    planned_trace = planned_trace_download_response.json()
    assert planned_trace["context_used"]["adaptive_strategy_brief_artifact_id"] == strategy_brief_job["output"][
        "adaptive_strategy_brief_artifact_id"
    ]
    assert planned_trace["adaptive_strategy_guidance"]["fixed_recipe_policy"] == "advisory_candidates_only"
    assert planned_trace["adaptive_strategy_guidance"]["must_emit_approach_decision_trace"] is True

    planned_citation_preview_response = client.get(
        f"/api/artifacts/{planned_stub_job['output']['citation_audit_report_artifact_id']}/preview"
    )
    assert planned_citation_preview_response.status_code == 200
    planned_citation_preview = planned_citation_preview_response.json()["preview"]
    assert "Citation Audit Report" in planned_citation_preview
    assert "External network accessed: false" in planned_citation_preview

    planned_stub_job_artifacts_response = client.get(f"/api/jobs/{planned_stub_job['id']}/artifacts")
    assert planned_stub_job_artifacts_response.status_code == 200
    planned_stub_job_artifacts = planned_stub_job_artifacts_response.json()
    planned_stub_asset_types = {item["asset_type"] for item in planned_stub_job_artifacts["artifacts"]}
    assert {
        "agent_task_report",
        "agent_result",
        "visualization_spec",
        "feature_recipe",
        "experiment_metrics",
        "approach_decision_trace",
        "source_citation_manifest",
        "citation_audit_report",
    }.issubset(planned_stub_asset_types)

    planned_stub_runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert planned_stub_runs_response.status_code == 200
    assert any(
        run["id"] == planned_stub_job["output"]["experiment_run_id"] and run["status"] == "not_executed"
        for run in planned_stub_runs_response.json()
    )

    planned_agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert planned_agent_results_response.status_code == 200
    planned_agent_results = planned_agent_results_response.json()
    planned_result = next(item for item in planned_agent_results if item["job_id"] == planned_stub_job["id"])
    assert planned_result["source"]["type"] == "agent_task_contract"
    assert planned_result["artifacts"]["source_citation_manifest"]["id"] == planned_stub_job["output"][
        "source_citation_manifest_artifact_id"
    ]
    assert planned_result["reports"]["citation_audit_report"]["id"] == planned_stub_job["output"][
        "citation_audit_report_id"
    ]
    assert planned_result["artifacts"]["approach_decision_trace"]["id"] == planned_stub_job["output"][
        "approach_decision_trace_artifact_id"
    ]
    assert planned_result["approach_decision_trace"]["policy"] == "open_ended_with_harness_constraints"
    assert planned_result["citation_audit"]["citation_count"] >= 1
    assert planned_result["citation_audit"]["external_network_accessed"] is False

    research_response = client.post(
        f"/api/projects/{project_id}/approach/research-briefs",
        json={"question": "What flexible approaches should be considered?"},
    )
    assert research_response.status_code == 200, research_response.text
    research_job = research_response.json()
    assert research_job["status"] == "succeeded"
    assert research_job["output"]["research_brief_id"]

    briefs_response = client.get(f"/api/projects/{project_id}/approach/research-briefs")
    assert briefs_response.status_code == 200
    brief = briefs_response.json()[0]
    assert "controlled web" in brief["summary_md"].lower() or "web" in brief["summary_md"].lower()
    assert len(brief["recommended_approaches"]) >= 2
    assert any(source["source_type"] == "research_plan" for source in brief["sources"])
    assert any(source["source_type"] == "research_finding_synthesis" for source in brief["sources"])

    ideas_response = client.post(f"/api/projects/{project_id}/approach/ideas/generate")
    assert ideas_response.status_code == 200, ideas_response.text
    ideas_job = ideas_response.json()
    assert ideas_job["status"] == "succeeded"
    assert len(ideas_job["output"]["idea_ids"]) >= 2

    ideas_list_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert ideas_list_response.status_code == 200
    idea = ideas_list_response.json()[0]
    assert idea["status"] == "proposed"
    contract_inputs = idea["agent_task_contract"]["inputs"]
    assert contract_inputs["must_respect_split_manifest"] is True
    assert contract_inputs["research_plan_artifact_id"] == research_plan_artifact_id
    assert (
        contract_inputs["research_finding_synthesis"]["artifact_id"]
        == research_synthesis_job["output"]["research_finding_synthesis_artifact_id"]
    )
    assert len(contract_inputs["recommended_asset_ids"]) >= 4
    assert len(contract_inputs["recommended_asset_version_ids"]) >= 4
    assert contract_inputs["research_source_policy"]["network_default"] == "disabled_until_runner_policy_allows"
    assert any("secrets" in item for item in idea["agent_task_contract"]["forbidden_actions"])

    assets_response = client.get("/api/assets")
    assert assets_response.status_code == 200
    assert any(item["name"] == skill_asset["name"] for item in assets_response.json())

    versions_response = client.get(f"/api/assets/{skill_asset['id']}/versions")
    assert versions_response.status_code == 200
    skill_version = versions_response.json()[0]
    assert skill_version["asset_id"] == skill_asset["id"]

    custom_skill_response = client.post(
        "/api/assets",
        json={
            "asset_type": "skill",
            "name": "custom_credit_review_skill",
            "description": "Project-specific credit review guidance.",
            "content": {
                "schema_version": "tablex_skill.v1",
                "instructions": ["Review credit-risk evidence without forcing a fixed recipe."],
            },
            "tags": ["credit", "eda"],
            "semantic_tags": ["skill", "credit_risk"],
        },
    )
    assert custom_skill_response.status_code == 200, custom_skill_response.text
    custom_skill = custom_skill_response.json()
    assert "credit_risk" in custom_skill["semantic_tags"]
    custom_skill_versions_response = client.get(f"/api/assets/{custom_skill['id']}/versions")
    assert custom_skill_versions_response.status_code == 200

    project_ref_response = client.post(
        f"/api/projects/{project_id}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_research",
        },
    )
    assert project_ref_response.status_code == 200, project_ref_response.text
    assert project_ref_response.json()["asset"]["asset_type"] == "skill"

    idea_ref_response = client.post(
        f"/api/ideas/{idea['id']}/asset-references",
        json={
            "target_asset_id": skill_asset["id"],
            "target_asset_version_id": skill_version["id"],
            "relation_type": "uses_for_agent_task",
        },
    )
    assert idea_ref_response.status_code == 200, idea_ref_response.text
    assert idea_ref_response.json()["source_type"] == "idea"

    project_refs_response = client.get(f"/api/projects/{project_id}/asset-references")
    assert project_refs_response.status_code == 200
    assert project_refs_response.json()[0]["asset"]["name"] == skill_asset["name"]

    skill_preview_response = client.get(f"/api/artifacts/{skill_version['artifact_id']}/preview")
    assert skill_preview_response.status_code == 200
    assert skill_preview_response.json()["preview_available"] is True

    context_response = client.post(f"/api/ideas/{idea['id']}/prepare-agent-context")
    assert context_response.status_code == 200, context_response.text
    context_job = context_response.json()
    assert context_job["status"] == "succeeded"
    assert context_job["output"]["schema_version"] == "agent_context_pack.v1"
    assert context_job["output"]["artifact_id"]
    assert context_job["output"]["asset_recommendation_count"] >= 4
    assert context_job["output"]["materialized_library_asset_count"] >= 4

    context_packs_response = client.get(f"/api/ideas/{idea['id']}/context-packs")
    assert context_packs_response.status_code == 200
    context_artifact = context_packs_response.json()[0]
    assert context_artifact["id"] == context_job["output"]["artifact_id"]

    context_preview_response = client.get(f"/api/artifacts/{context_artifact['id']}/preview")
    assert context_preview_response.status_code == 200
    context_download_response = client.get(f"/api/artifacts/{context_artifact['id']}/download")
    assert context_download_response.status_code == 200
    context_payload = context_download_response.json()
    assert context_payload["schema_version"] == "agent_context_pack.v1"
    assert "controlled_web_search" in context_payload["research_policy"]["allowed_modes"]
    assert context_payload["safety_controls"]["connector_credentials"] == "never passed to the agent"
    assert context_payload["evaluation_context"]["split_manifest_id"]
    assert context_payload["quality_gate_context"]["status"] == "available"
    assert context_payload["quality_gate_context"]["quality_check_scope"] in {"full", "sample"}
    assert context_payload["research_plan_context"]["artifact_id"] == research_plan_artifact_id
    assert (
        context_payload["research_synthesis_context"]["artifact_id"]
        == research_synthesis_job["output"]["research_finding_synthesis_artifact_id"]
    )
    assert context_payload["research_synthesis_context"]["citation_audit"]["external_network_accessed"] is False
    assert len(context_payload["asset_recommendations"]) >= 4
    assert len(context_payload["materialized_library_assets"]) >= 4
    assert any(
        item["context_path"].startswith(".harness/context/library_assets/")
        for item in context_payload["materialized_library_assets"]
    )
    assert any(item["name"] == "xgboost_mixed_type_baseline" for item in context_payload["asset_recommendations"])

    experiment_plan_response = client.post(f"/api/ideas/{idea['id']}/experiment-plan")
    assert experiment_plan_response.status_code == 200, experiment_plan_response.text
    experiment_plan_job = experiment_plan_response.json()
    assert experiment_plan_job["status"] == "succeeded"
    assert experiment_plan_job["output"]["plan_id"]
    assert experiment_plan_job["output"]["artifact_id"]
    assert experiment_plan_job["output"]["readiness"]["status"] == "ready_for_runner"

    experiment_plans_response = client.get(f"/api/ideas/{idea['id']}/experiment-plans")
    assert experiment_plans_response.status_code == 200
    experiment_plan_artifact = experiment_plans_response.json()[0]
    assert experiment_plan_artifact["id"] == experiment_plan_job["output"]["artifact_id"]

    experiment_plan_preview_response = client.get(f"/api/artifacts/{experiment_plan_artifact['id']}/preview")
    assert experiment_plan_preview_response.status_code == 200
    assert "experiment_plan.v1" in experiment_plan_preview_response.json()["preview"]
    assert "source_policy" in experiment_plan_preview_response.json()["preview"]

    agent_task_response = client.post(f"/api/ideas/{idea['id']}/run-agent-task")
    assert agent_task_response.status_code == 200, agent_task_response.text
    agent_task_job = agent_task_response.json()
    assert agent_task_job["status"] == "succeeded"
    assert agent_task_job["output"]["idea_id"] == idea["id"]
    assert agent_task_job["output"]["agent_status"] == "succeeded"
    assert agent_task_job["output"]["requires_human_review"] is True
    assert len(agent_task_job["output"]["artifact_ids"]) >= 4
    assert agent_task_job["output"]["workspace_artifact_id"]
    assert len(agent_task_job["output"]["ingested_artifact_ids"]) == 9
    assert agent_task_job["output"]["report_id"]
    assert agent_task_job["output"]["evidence_id"]
    assert agent_task_job["output"]["experiment_run_id"]
    assert agent_task_job["output"]["agent_metrics_artifact_id"]
    assert agent_task_job["output"]["agent_feature_recipe_artifact_id"]
    assert agent_task_job["output"]["approach_decision_trace_artifact_id"]
    assert agent_task_job["output"]["source_citation_manifest_artifact_id"]
    assert agent_task_job["output"]["citation_audit_report_id"]
    assert agent_task_job["output"]["citation_audit_report_artifact_id"]
    assert agent_task_job["output"]["citation_evidence_id"]
    assert agent_task_job["output"]["citation_visualization_id"]
    assert len(agent_task_job["output"]["visualization_ids"]) == 1

    citation_manifest_response = client.get(
        f"/api/artifacts/{agent_task_job['output']['source_citation_manifest_artifact_id']}/download"
    )
    assert citation_manifest_response.status_code == 200
    citation_manifest = citation_manifest_response.json()
    assert citation_manifest["schema_version"] == "source_citation_manifest.v1"
    assert citation_manifest["connector_credentials_materialized"] is False

    idea_decision_trace_response = client.get(
        f"/api/artifacts/{agent_task_job['output']['approach_decision_trace_artifact_id']}/download"
    )
    assert idea_decision_trace_response.status_code == 200
    idea_decision_trace = idea_decision_trace_response.json()
    assert idea_decision_trace["schema_version"] == "approach_decision_trace.v1"
    assert any(
        item["approach"] == "fixed_predefined_recipe_execution"
        for item in idea_decision_trace["rejected_or_deferred_approaches"]
    )

    citation_report_response = client.get(
        f"/api/reports/{agent_task_job['output']['citation_audit_report_id']}/preview"
    )
    assert citation_report_response.status_code == 200
    assert "Citation Audit Report" in citation_report_response.json()["preview"]

    agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert agent_results_response.status_code == 200
    agent_results = agent_results_response.json()
    assert len(agent_results) >= 2
    idea_result = next(item for item in agent_results if item["job_id"] == agent_task_job["id"])
    assert idea_result["source"] == {"type": "idea", "id": idea["id"]}
    assert idea_result["experiment_run"]["id"] == agent_task_job["output"]["experiment_run_id"]
    assert idea_result["artifacts"]["agent_task_report"]["asset_type"] == "agent_task_report"
    assert idea_result["artifacts"]["citation_audit_report"]["asset_type"] == "citation_audit_report"
    assert idea_result["artifacts"]["approach_decision_trace"]["id"] == agent_task_job["output"][
        "approach_decision_trace_artifact_id"
    ]
    assert idea_result["approach_decision_trace"]["deferred_or_rejected_count"] >= 1
    assert idea_result["evidence"]["citation_audit"]["id"] == agent_task_job["output"]["citation_evidence_id"]

    updated_ideas_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert updated_ideas_response.status_code == 200
    assert updated_ideas_response.json()[0]["status"] == "agent_stub_completed"

    agent_task_runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert agent_task_runs_response.status_code == 200
    assert any(
        run["id"] == agent_task_job["output"]["experiment_run_id"] and run["runner_type"] == "local_stub"
        for run in agent_task_runs_response.json()
    )

    visualization_response = client.post(f"/api/projects/{project_id}/visualizations/generate")
    assert visualization_response.status_code == 200, visualization_response.text
    visualization_job = visualization_response.json()
    assert visualization_job["status"] == "succeeded"
    assert len(visualization_job["output"]["visualization_ids"]) >= 4

    visualizations_response = client.get(f"/api/projects/{project_id}/visualizations")
    assert visualizations_response.status_code == 200
    visualizations = visualizations_response.json()
    chart_types = {item["chart_type"] for item in visualizations}
    assert {"metric_cards", "category_bars", "stage_status", "leaderboard_bar"}.issubset(chart_types)
    leaderboard_visualization = next(item for item in visualizations if item["chart_type"] == "leaderboard_bar")
    assert leaderboard_visualization["spec"]["schema_version"] == "visualization_spec.v1"

    insights_response = client.post(f"/api/projects/{project_id}/insights/generate")
    assert insights_response.status_code == 200, insights_response.text
    insights_job = insights_response.json()
    assert insights_job["status"] == "succeeded"
    assert len(insights_job["output"]["insight_ids"]) >= 5
    assert len(insights_job["output"]["evidence_ids"]) >= 5

    insights_list_response = client.get(f"/api/projects/{project_id}/insights")
    assert insights_list_response.status_code == 200
    insight = insights_list_response.json()[0]
    assert insight["artifact_id"] == insights_job["output"]["artifact_id"]
    assert insight["evidence_ids"]

    insight_preview_response = client.get(f"/api/artifacts/{insight['artifact_id']}/preview")
    assert insight_preview_response.status_code == 200
    assert "insight_set.v1" in insight_preview_response.json()["preview"]

    report_response = client.post(
        f"/api/projects/{project_id}/reports/draft",
        json={"title": "Integration report", "report_type": "project_summary"},
    )
    assert report_response.status_code == 200, report_response.text
    report_job = report_response.json()
    assert report_job["status"] == "succeeded"

    reports_response = client.get(f"/api/projects/{project_id}/reports")
    assert reports_response.status_code == 200
    report = reports_response.json()[0]
    assert report["artifact_id"] == report_job["output"]["artifact_id"]

    report_preview_response = client.get(f"/api/artifacts/{report['artifact_id']}/preview")
    assert report_preview_response.status_code == 200
    assert "Project Report" in report_preview_response.json()["preview"]
    assert "## Insights" in report_preview_response.json()["preview"]

    report_preview_by_id_response = client.get(f"/api/reports/{report['id']}/preview")
    assert report_preview_by_id_response.status_code == 200
    assert "## Visualizations" in report_preview_by_id_response.json()["preview"]

    artifact_translation_response = client.post(
        f"/api/artifacts/{report['artifact_id']}/translate",
        json={"target_locale": "Japanese", "source_locale": "en-US"},
    )
    assert artifact_translation_response.status_code == 200, artifact_translation_response.text
    artifact_translation = artifact_translation_response.json()
    assert artifact_translation["source_type"] == "artifact"
    assert artifact_translation["target_locale"] == "Japanese"
    assert artifact_translation["artifact"]["asset_type"] == "translated_artifact_preview"
    assert artifact_translation["job"]["output"]["codex_translation_contract_artifact_id"]
    assert "Codex" in artifact_translation["preview"]["preview"]

    report_translation_response = client.post(
        f"/api/reports/{report['id']}/translate",
        json={"target_locale": "ja-JP", "source_locale": "en-US"},
    )
    assert report_translation_response.status_code == 200, report_translation_response.text
    report_translation = report_translation_response.json()
    assert report_translation["source_type"] == "report"
    assert report_translation["report"]["status"] == "draft_translation"
    assert report_translation["artifact"]["asset_type"] == "translated_report"
    assert report_translation["job"]["job_type"] == "translate_tier3_content"
    assert report_translation["job"]["output"]["codex_translation_contract_artifact_id"]

    decision_response = client.post(f"/api/projects/{project_id}/decision-dashboard/generate")
    assert decision_response.status_code == 200, decision_response.text
    decision_job = decision_response.json()
    assert decision_job["status"] == "succeeded"
    assert decision_job["output"]["schema_version"] == "decision_dashboard.v1"
    assert decision_job["output"]["decision_dashboard_artifact_id"]
    assert decision_job["output"]["decision_report_artifact_id"]
    assert decision_job["output"]["report_id"]
    assert len(decision_job["output"]["visualization_ids"]) == 3

    decision_dashboard_preview_response = client.get(
        f"/api/artifacts/{decision_job['output']['decision_dashboard_artifact_id']}/preview"
    )
    assert decision_dashboard_preview_response.status_code == 200
    assert decision_dashboard_preview_response.json()["preview_available"] is True
    decision_dashboard_download_response = client.get(
        f"/api/artifacts/{decision_job['output']['decision_dashboard_artifact_id']}/download"
    )
    assert decision_dashboard_download_response.status_code == 200
    decision_dashboard_payload = decision_dashboard_download_response.json()
    assert decision_dashboard_payload["schema_version"] == "decision_dashboard.v1"
    assert "readiness_stages" in decision_dashboard_payload

    decision_report_preview_response = client.get(f"/api/reports/{decision_job['output']['report_id']}/preview")
    assert decision_report_preview_response.status_code == 200
    decision_report_preview = decision_report_preview_response.json()["preview"]
    assert "Decision Report" in decision_report_preview
    assert "## Readiness Stages" in decision_report_preview

    current_decision_report_empty_response = client.get(f"/api/projects/{project_id}/decision-report/current")
    assert current_decision_report_empty_response.status_code == 200
    assert current_decision_report_empty_response.json()["available"] is False

    decision_report_v1_response = client.post(f"/api/projects/{project_id}/decision-report/generate")
    assert decision_report_v1_response.status_code == 200, decision_report_v1_response.text
    decision_report_v1_job = decision_report_v1_response.json()
    assert decision_report_v1_job["status"] == "succeeded"
    assert decision_report_v1_job["job_type"] == "generate_decision_report"
    assert decision_report_v1_job["output"]["schema_version"] == "decision_report_bundle.v1"
    assert decision_report_v1_job["output"]["decision_report_bundle_artifact_id"]
    assert decision_report_v1_job["output"]["decision_report_artifact_id"]
    assert decision_report_v1_job["output"]["decision_report_evidence_id"]
    assert decision_report_v1_job["output"]["source_asset_count"] > 0

    decision_report_bundle_response = client.get(
        f"/api/artifacts/{decision_report_v1_job['output']['decision_report_bundle_artifact_id']}/download"
    )
    assert decision_report_bundle_response.status_code == 200
    decision_report_bundle = decision_report_bundle_response.json()
    assert decision_report_bundle["schema_version"] == "decision_report_bundle.v1"
    assert decision_report_bundle["safety"]["external_dashboards_required"] is False
    assert decision_report_bundle["safety"]["secret_values_included"] is False
    assert "data_review" in decision_report_bundle["sections"]
    assert "evaluation" in decision_report_bundle["sections"]
    assert "notebooks" in decision_report_bundle["sections"]
    assert "experiments" in decision_report_bundle["sections"]
    assert "runner_results" in decision_report_bundle["sections"]
    assert "citations" in decision_report_bundle["sections"]
    assert any(row["area"] == "Data Review" for row in decision_report_bundle["evidence_map"])
    assert decision_report_bundle["next_actions"]

    decision_report_v1_preview_response = client.get(
        f"/api/reports/{decision_report_v1_job['output']['report_id']}/preview"
    )
    assert decision_report_v1_preview_response.status_code == 200
    decision_report_v1_preview = decision_report_v1_preview_response.json()["preview"]
    assert "## Evidence Map" in decision_report_v1_preview
    assert "## Data Review" in decision_report_v1_preview
    assert "## Evaluation Design" in decision_report_v1_preview
    assert "## Experiments And Model Evidence" in decision_report_v1_preview
    assert "## Notebook Evidence" in decision_report_v1_preview
    assert "## Runner Results And Citations" in decision_report_v1_preview
    assert "## Next Actions" in decision_report_v1_preview

    current_decision_report_response = client.get(f"/api/projects/{project_id}/decision-report/current")
    assert current_decision_report_response.status_code == 200
    current_decision_report = current_decision_report_response.json()
    assert current_decision_report["available"] is True
    assert current_decision_report["report"]["id"] == decision_report_v1_job["output"]["report_id"]
    assert current_decision_report["bundle"]["schema_version"] == "decision_report_bundle.v1"

    post_run_readout_response = client.get(f"/api/projects/{project_id}/results/readout")
    assert post_run_readout_response.status_code == 200, post_run_readout_response.text
    post_run_readout = post_run_readout_response.json()
    assert post_run_readout["decision_report"]["available"] is True
    assert post_run_readout["next_action"]["target_anchor"] == "result-readout"
    assert post_run_readout["safety"]["leaderboard_is_decision"] is False

    runs_response = client.get(f"/api/projects/{project_id}/runs")
    assert runs_response.status_code == 200
    baseline_run = next(run for run in runs_response.json() if run["model_version_id"] == model_version["id"])
    assert baseline_run["runner_type"] == "local_baseline"

    leaderboard_response = client.get(f"/api/projects/{project_id}/leaderboard")
    assert leaderboard_response.status_code == 200
    assert leaderboard_response.json()[0]["primary_metric_value"] is not None

    diagnostics_response = client.post(f"/api/runs/{baseline_run['id']}/diagnostics")
    assert diagnostics_response.status_code == 200, diagnostics_response.text
    diagnostics_job = diagnostics_response.json()
    assert diagnostics_job["status"] == "succeeded"
    assert len(diagnostics_job["output"]["artifact_ids"]) == 3
    diagnostics_payload = diagnostics_job["output"]["diagnostics"]
    assert diagnostics_payload["schema_version"] == "evaluation_diagnostics.v1"
    assert diagnostics_payload["task_kind"] == "classification"
    assert diagnostics_payload["summary"]["count"] > 0
    assert diagnostics_job["output"]["insight_id"]
    assert diagnostics_job["output"]["evidence_id"]

    model_evidence_response = client.post(f"/api/runs/{baseline_run['id']}/model-diagnostics-artifacts")
    assert model_evidence_response.status_code == 200, model_evidence_response.text
    model_evidence_job = model_evidence_response.json()
    assert model_evidence_job["status"] == "succeeded"
    assert model_evidence_job["job_type"] == "materialize_model_diagnostics_artifacts"
    assert model_evidence_job["output"]["feature_importance_artifact_id"]
    assert model_evidence_job["output"]["permutation_importance_artifact_id"]
    assert model_evidence_job["output"]["model_diagnostics_artifact_pack_id"]
    assert model_evidence_job["output"]["model_diagnostics_report_artifact_id"]
    assert model_evidence_job["output"]["availability"]["native_feature_importance"] == "ready"
    assert model_evidence_job["output"]["availability"]["prediction_review"] == "ready"
    model_evidence_report_response = client.get(
        f"/api/artifacts/{model_evidence_job['output']['model_diagnostics_report_artifact_id']}/preview"
    )
    assert model_evidence_report_response.status_code == 200
    model_evidence_report = model_evidence_report_response.json()["preview"]
    assert "Model Diagnostics Artifact Pack" in model_evidence_report
    assert "Top Native Features" in model_evidence_report

    model_notebook_response = client.post(f"/api/runs/{baseline_run['id']}/analysis-notebook")
    assert model_notebook_response.status_code == 200, model_notebook_response.text
    model_notebook_job = model_notebook_response.json()
    assert model_notebook_job["status"] == "succeeded"
    assert model_notebook_job["job_type"] == "prepare_model_diagnostics_notebook_authoring"
    assert model_notebook_job["output"]["notebook_kind"] == "model_diagnostics"
    assert model_notebook_job["output"]["run_id"] == baseline_run["id"]
    assert model_notebook_job["output"]["analysis_notebook_artifact_id"] is None
    assert model_notebook_job["output"]["notebook_html_artifact_id"] is None
    assert model_notebook_job["output"]["notebook_report_id"] is None
    assert model_notebook_job["output"]["visualization_id"] is None
    assert model_notebook_job["output"]["visualization_artifact_id"] is None
    assert model_notebook_job["output"]["execution_status"] == "awaiting_agent_authored_notebook"
    assert model_notebook_job["output"]["notebook_authoring_brief_artifact_id"]

    notebook_index_response = client.get(f"/api/projects/{project_id}/analysis-notebooks")
    assert notebook_index_response.status_code == 200, notebook_index_response.text
    notebook_index = notebook_index_response.json()
    assert notebook_index["schema_version"] == "analysis_notebook_index.v1"
    assert notebook_index["counts"]["total"] == 0
    assert notebook_index["recommended_notebook"] is None

    guidance_after_capture_response = client.get(f"/api/projects/{project_id}/guidance")
    assert guidance_after_capture_response.status_code == 200
    guidance_after_capture = guidance_after_capture_response.json()
    guidance_journey = {stage["id"]: stage for stage in guidance_after_capture["journey_stages"]}
    assert guidance_journey["notebooks"]["status"] in {"todo", "next", "doing"}
    assert guidance_after_capture["supporting_counts"]["analysis_notebooks"] == 0
    assert guidance_after_capture["supporting_counts"]["notebook_execution_captures"] == 0

    run_report_response = client.post(f"/api/runs/{baseline_run['id']}/report")
    assert run_report_response.status_code == 200, run_report_response.text
    run_report_job = run_report_response.json()
    assert run_report_job["status"] == "succeeded"
    assert run_report_job["output"]["report_id"]
    assert run_report_job["output"]["artifact_id"]

    comparison_response = client.post(f"/api/projects/{project_id}/experiments/compare")
    assert comparison_response.status_code == 200, comparison_response.text
    comparison_job = comparison_response.json()
    assert comparison_job["status"] == "succeeded"
    assert comparison_job["output"]["comparison"]["schema_version"] == "experiment_comparison.v1"
    assert comparison_job["output"]["comparison"]["decision"]["best_run_id"] == baseline_run["id"]
    assert len(comparison_job["output"]["artifact_ids"]) >= 2
    assert comparison_job["output"]["report_id"]
    assert comparison_job["output"]["insight_id"]

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "baseline_plan",
        "baseline_strategy_plan",
        "feature_recipe",
        "model_package",
        "model_validation_report",
        "model_validation_metrics",
        "prediction_replay",
        "data_quality_gate",
        "data_quality_report",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "research_plan",
        "agent_task_contract",
        "research_brief",
        "approach_candidate",
        "report",
        "visualization_spec",
        "insight_set",
        "evaluation_diagnostics",
        "evaluation_diagnostics_report",
        "experiment_plan",
        "experiment_comparison",
        "experiment_comparison_report",
        "run_report",
        "decision_dashboard",
        "decision_report",
        "agent_workspace_manifest",
        "agent_task_readiness_review",
        "agent_task_readiness_report",
        "agent_context_pack",
        "agent_task_report",
        "agent_result",
        "notebook_authoring_brief",
        "notebook_authoring_report",
        "eda_review_bundle",
        "eda_review_html",
        "eda_review_svg",
        "eda_review_report",
    }.issubset(asset_types)
    artifacts = artifacts_response.json()
    validation_report = next(item for item in artifacts if item["asset_type"] == "model_validation_report")
    model_package = next(item for item in artifacts if item["asset_type"] == "model_package")
    diagnostics_report = next(item for item in artifacts if item["asset_type"] == "evaluation_diagnostics_report")
    run_report = next(item for item in artifacts if item["asset_type"] == "run_report")
    experiment_comparison = next(item for item in artifacts if item["asset_type"] == "experiment_comparison")
    approval_review = next(item for item in artifacts if item["asset_type"] == "evaluation_approval_review")
    workspace_manifest = next(item for item in artifacts if item["asset_type"] == "agent_workspace_manifest")

    preview_response = client.get(f"/api/artifacts/{validation_report['id']}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["preview_available"] is True
    assert "Model Package Validation Report" in preview_response.json()["preview"]

    diagnostics_preview_response = client.get(f"/api/artifacts/{diagnostics_report['id']}/preview")
    assert diagnostics_preview_response.status_code == 200
    assert "Evaluation Diagnostics" in diagnostics_preview_response.json()["preview"]

    run_report_preview_response = client.get(f"/api/artifacts/{run_report['id']}/preview")
    assert run_report_preview_response.status_code == 200
    assert "Run Report" in run_report_preview_response.json()["preview"]

    comparison_preview_response = client.get(f"/api/artifacts/{experiment_comparison['id']}/preview")
    assert comparison_preview_response.status_code == 200
    assert "experiment_comparison.v1" in comparison_preview_response.json()["preview"]

    approval_review_late_preview_response = client.get(f"/api/artifacts/{approval_review['id']}/preview")
    assert approval_review_late_preview_response.status_code == 200
    assert "evaluation_approval_review.v1" in approval_review_late_preview_response.json()["preview"]

    workspace_preview_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/preview")
    assert workspace_preview_response.status_code == 200
    workspace_download_response = client.get(f"/api/artifacts/{workspace_manifest['id']}/download")
    assert workspace_download_response.status_code == 200
    workspace_payload = workspace_download_response.json()
    assert workspace_payload["schema_version"] == "agent_workspace_manifest.v1"
    assert workspace_payload["safety"]["connector_credentials"] == "not_materialized"
    materialized_paths = [item["context_path"] for item in workspace_payload["materialized_sources"]]
    assert any("research_plan.json" in path for path in materialized_paths)
    assert any("baseline_metrics.json" in path for path in materialized_paths)
    assert any("baseline_report.md" in path for path in materialized_paths)
    assert any(path.startswith(".harness/context/library_assets/") for path in materialized_paths)
    assert any(item.get("asset_name") == "xgboost_mixed_type_baseline" for item in workspace_payload["materialized_sources"])

    package_preview_response = client.get(f"/api/artifacts/{model_package['id']}/preview")
    assert package_preview_response.status_code == 200
    assert package_preview_response.json()["preview_available"] is False

    download_response = client.get(f"/api/artifacts/{validation_report['id']}/download")
    assert download_response.status_code == 200
    assert b"Model Package Validation Report" in download_response.content

    lineage_response = client.get(f"/api/projects/{project_id}/lineage")
    assert lineage_response.status_code == 200
    assert any(item["to_asset_type"] == "model_version" for item in lineage_response.json())

    schema_response = client.get(f"/api/datasets/{dataset_id}/schema")
    assert schema_response.status_code == 200
    assert len(schema_response.json()["columns"]) == 5


def test_bounded_profile_quality_gate_uses_sample_scope(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post("/api/projects", json={"name": "Wide", "target_column": "target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]
    header = ["row_id", "target", *[f"feature_{index}" for index in range(85)]]
    rows = []
    for row_index in range(120):
        rows.append(
            ",".join(
                [
                    f"id_{row_index}",
                    str(row_index % 2),
                    *[str((row_index + column_index) % 7) for column_index in range(85)],
                ]
            )
        )
    csv_bytes = (",".join(header) + "\n" + "\n".join(rows) + "\n").encode("utf-8")

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("wide.csv", csv_bytes, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    dataset_id = upload_response.json()["dataset_snapshot"]["id"]

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    profile_artifact = next(item for item in artifacts_response.json() if item["asset_type"] == "eda_profile")
    assert profile_artifact["metadata"]["profile_mode"] == "bounded_sample"

    quality_response = client.post(f"/api/datasets/{dataset_id}/quality/run")
    assert quality_response.status_code == 200, quality_response.text
    gate = quality_response.json()["output"]["gate"]
    assert gate["profile_boundary"]["quality_check_scope"] == "sample"
    assert any(check["check_id"] == "profile_statistics_sampled" for check in gate["checks"])
    duplicate_check = next(check for check in gate["checks"] if check["check_id"] == "duplicate_rows")
    assert duplicate_check["status"] == "pass"
    assert duplicate_check["evidence"]["duplicate_row_count"] == 0

    latest_quality_response = client.get(f"/api/datasets/{dataset_id}/quality/latest")
    assert latest_quality_response.status_code == 200
    assert latest_quality_response.json()["metadata"]["quality_check_scope"] == "sample"


def test_planned_agent_task_stub_rejects_blocked_readiness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Blocked planned task", "target_column": "target", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert plan_response.status_code == 200, plan_response.text
    contract_artifact_id = plan_response.json()["output"]["agent_task_contract_artifact_id"]

    run_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/run-local-stub")
    assert run_response.status_code == 400
    assert "readiness has blockers" in run_response.json()["detail"]


def test_evaluation_approval_blocks_required_unanswered_question(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    project_response = client.post("/api/projects", json={"name": "Missing target"})
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    upload_response = client.post(
        f"/api/projects/{project_id}/datasets/upload",
        files={"file": ("features.csv", b"feature_a,feature_b\n1,10\n2,20\n3,30\n4,40\n", "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text

    questions_response = client.get(f"/api/projects/{project_id}/questions")
    assert questions_response.status_code == 200
    assert any(item["fallback_policy"] == "block_until_answered" for item in questions_response.json())

    design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert design_response.status_code == 200, design_response.text
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    candidate = candidates_response.json()[0]

    promote_response = client.post(f"/api/evaluation-candidates/{candidate['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]

    review_response = client.post(f"/api/evaluation-specs/{spec_id}/approval-review")
    assert review_response.status_code == 200, review_response.text
    review_job = review_response.json()
    assert review_job["output"]["review_status"] == "blocked"
    assert review_job["output"]["blocker_count"] >= 1

    approve_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approve_response.status_code == 409
    assert "block_until_answered" in approve_response.text

    spec_response = client.get(f"/api/evaluation-specs/{spec_id}")
    assert spec_response.status_code == 200
    assert spec_response.json()["status"] == "draft"


def test_benchmark_catalog_and_local_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    benchmarks_response = client.get("/api/benchmarks")
    assert benchmarks_response.status_code == 200, benchmarks_response.text
    benchmarks = benchmarks_response.json()
    assert any(item["id"] == "kaggle_home_credit_default_risk" for item in benchmarks)
    assert any(item["id"] == "uci_wine_quality" for item in benchmarks)
    assert any(item["id"] == "openml_credit_g" for item in benchmarks)
    home_credit_benchmark = next(item for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk")
    assert home_credit_benchmark["source_card"]["access"]["requires_account"] is True
    assert home_credit_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "user_managed_outside_tablex"
    assert home_credit_benchmark["source_card"]["credential_probe"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_probe"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["credential_inventory"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_inventory"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["credential_download"]["supported"] is True
    assert home_credit_benchmark["source_card"]["credential_download"]["agent_receives_credentials"] is False
    assert home_credit_benchmark["source_card"]["table_bundle"]["supporting_table_count"] >= 1
    assert home_credit_benchmark["source_card"]["source_verification"]["source_count"] >= 1
    uci_benchmark = next(item for item in benchmarks if item["id"] == "uci_bank_marketing")
    assert uci_benchmark["local_status"]["ready"] is False
    assert uci_benchmark["fixture_available"] is True
    assert uci_benchmark["source_card"]["access"]["supports_direct_download"] is True
    assert uci_benchmark["source_card"]["credential_policy"]["dataset_credentials"] == "not_required"
    assert uci_benchmark["source_card"]["credential_probe"]["supported"] is False
    assert uci_benchmark["source_card"]["credential_inventory"]["supported"] is False
    assert uci_benchmark["source_card"]["credential_download"]["supported"] is False
    assert uci_benchmark["scenario"]["kind"] == "single_table_categorical_smoke"
    openml_benchmark = next(item for item in benchmarks if item["id"] == "openml_credit_g")
    assert openml_benchmark["source_card"]["table_bundle"]["kind"] == "single_table_bundle"
    assert openml_benchmark["source_card"]["source_verification"]["access_checked"]["requires_account"] is False
    assert "Do not paste Kaggle credentials" in next(
        item["download_instructions"] for item in benchmarks if item["id"] == "kaggle_home_credit_default_risk"
    )

    source_card_response = client.get("/api/benchmarks/uci_bank_marketing/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["schema_version"] == "benchmark_source_card.v1"
    assert source_card["access"]["kind"] == "public_direct_download"
    assert "bank+marketing.zip" in str(source_card["download"]["download_urls"])

    readiness_response = client.get("/api/benchmarks/uci_bank_marketing/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is False
    assert any("fixture" in item.lower() for item in readiness_response.json()["next_actions"])

    project_response = client.post(
        "/api/projects",
        json={"name": "Benchmark import", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    collection_response = client.post(f"/api/projects/{project_id}/benchmarks/collection-plan")
    assert collection_response.status_code == 200, collection_response.text
    collection_job = collection_response.json()
    assert collection_job["status"] == "succeeded"
    assert collection_job["output"]["schema_version"] == "benchmark_collection_plan.v1"
    assert collection_job["output"]["benchmark_collection_plan_artifact_id"]
    assert collection_job["output"]["benchmark_collection_report_artifact_id"]
    assert collection_job["output"]["credentialed_count"] >= 1
    assert collection_job["output"]["public_direct_count"] >= 1
    assert collection_job["output"]["multitable_count"] >= 1

    collection_plan_response = client.get(
        f"/api/artifacts/{collection_job['output']['benchmark_collection_plan_artifact_id']}/download"
    )
    assert collection_plan_response.status_code == 200
    collection_plan = collection_plan_response.json()
    assert collection_plan["credential_policy"]["secret_access"] == "forbidden"
    home_credit_plan = next(
        item for item in collection_plan["benchmarks"] if item["benchmark_id"] == "kaggle_home_credit_default_risk"
    )
    assert "credentialed_manual_download_required" in home_credit_plan["collection_status"]
    openml_plan = next(item for item in collection_plan["benchmarks"] if item["benchmark_id"] == "openml_credit_g")
    assert "public_workflow_available" in openml_plan["collection_status"]

    collection_report_response = client.get(
        f"/api/artifacts/{collection_job['output']['benchmark_collection_report_artifact_id']}/preview"
    )
    assert collection_report_response.status_code == 200
    collection_report = collection_report_response.json()["preview"]
    assert "Benchmark Collection Plan" in collection_report
    assert "Home Credit Default Risk" in collection_report

    import_missing_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_missing_response.status_code == 400
    assert "Missing required benchmark files" in import_missing_response.text

    fixture_response = client.post("/api/benchmarks/uci_bank_marketing/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["schema_version"] == "benchmark_fixture.v1"
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "bank-full.csv" for item in fixture["generated_files"])

    status_response = client.get("/api/benchmarks/uci_bank_marketing/local-status")
    assert status_response.status_code == 200
    assert status_response.json()["ready"] is True

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/import", json={})
    assert import_response.status_code == 200, import_response.text
    payload = import_response.json()
    assert payload["primary_file"] == "bank-full.csv"
    assert payload["dataset_snapshot"]["source_type"] == "benchmark_catalog"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_bank_marketing:bank-full.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_bank_marketing"
    assert payload["import_manifest_artifact"]["asset_type"] == "benchmark_import_manifest"
    assert payload["relational_catalog_artifact"]["asset_type"] == "relational_catalog"
    assert payload["supporting_table_artifacts"] == []

    project_after_import = client.get(f"/api/projects/{project_id}")
    assert project_after_import.status_code == 200
    assert project_after_import.json()["target_column"] == "y"

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    assert "benchmark_import_manifest.v1" in manifest_preview_response.json()["preview"]
    assert "not_stored_or_passed_to_agent" in manifest_preview_response.json()["preview"]

    relational_preview_response = client.get(f"/api/artifacts/{payload['relational_catalog_artifact']['id']}/preview")
    assert relational_preview_response.status_code == 200
    assert "relational_catalog.v1" in relational_preview_response.json()["preview"]

    scenario_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack")
    assert scenario_response.status_code == 200, scenario_response.text
    scenario_job = scenario_response.json()
    assert scenario_job["status"] == "succeeded"
    assert scenario_job["output"]["scenario_kind"] == "single_table_categorical_smoke"
    assert scenario_job["output"]["benchmark_scenario_pack_artifact_id"]
    scenario_preview_response = client.get(
        f"/api/artifacts/{scenario_job['output']['benchmark_scenario_report_artifact_id']}/preview"
    )
    assert scenario_preview_response.status_code == 200
    assert "Benchmark Scenario Report" in scenario_preview_response.json()["preview"]


def test_public_uci_wine_fixture_source_card_import(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    source_card_response = client.get("/api/benchmarks/uci_wine_quality/source-card")
    assert source_card_response.status_code == 200
    source_card = source_card_response.json()
    assert source_card["access"]["requires_account"] is False
    assert source_card["access"]["supports_direct_download"] is True
    assert "wine+quality.zip" in str(source_card["download"]["download_urls"])
    assert source_card["import_readiness"]["can_import_now"] is False

    fixture_response = client.post("/api/benchmarks/uci_wine_quality/fixtures/generate", json={"overwrite": True})
    assert fixture_response.status_code == 200, fixture_response.text
    fixture = fixture_response.json()
    assert fixture["fixture_matches_expected"] is True
    assert fixture["local_status"]["ready"] is True
    assert any(item["path"] == "winequality-red.csv" for item in fixture["generated_files"])

    readiness_response = client.get("/api/benchmarks/uci_wine_quality/import-readiness")
    assert readiness_response.status_code == 200
    assert readiness_response.json()["can_import_now"] is True

    project_response = client.post(
        "/api/projects",
        json={"name": "Wine quality public smoke", "task_type": "regression"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    import_response = client.post(f"/api/projects/{project_id}/benchmarks/uci_wine_quality/import", json={})
    assert import_response.status_code == 200, import_response.text
    payload = import_response.json()
    assert payload["primary_file"] == "winequality-red.csv"
    assert payload["dataset_snapshot"]["source_ref"] == "uci_wine_quality:winequality-red.csv"
    assert payload["dataset_snapshot"]["row_count"] == 8
    assert payload["artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert payload["relational_catalog_artifact"]["metadata"]["benchmark_id"] == "uci_wine_quality"
    assert len(payload["supporting_table_artifacts"]) == 1

    manifest_preview_response = client.get(f"/api/artifacts/{payload['import_manifest_artifact']['id']}/preview")
    assert manifest_preview_response.status_code == 200
    manifest_preview = manifest_preview_response.json()["preview"]
    assert "benchmark_import_manifest.v1" in manifest_preview
    assert "public_direct_download" in manifest_preview


def test_public_benchmark_download_extracts_expected_files(tmp_path: Path, monkeypatch: Any) -> None:
    archive_dir = tmp_path / "served"
    archive_dir.mkdir()
    archive_path = archive_dir / "public.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/public.csv", "feature,target\n1,0\n2,1\n")
        archive.writestr("../evil.csv", "feature,target\n9,9\n")
        archive.writestr("ignored.txt", "ignore me\n")

    handler = partial(SimpleHTTPRequestHandler, directory=str(archive_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/public.zip"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_zip_smoke",
                            "name": "Public Zip Smoke",
                            "source_kind": "public_test_archive",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "zip",
                                        "expected_files": ["public.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "public.csv", "target_column": "target"},
                            "required_files": [
                                {"path": "public.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_archive",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "zip", "expected_files": ["public.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        readiness_response = client.get("/api/benchmarks/public_zip_smoke/import-readiness")
        assert readiness_response.status_code == 200
        assert readiness_response.json()["can_import_now"] is False

        download_response = client.post("/api/benchmarks/public_zip_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "succeeded"
        assert job["output"]["extracted_file_count"] == 1
        assert job["output"]["local_ready"] is True
        assert job["output"]["artifact_id"]

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_zip_smoke"
        assert (benchmark_root / "public.csv").read_text(encoding="utf-8").startswith("feature,target")
        assert not (benchmark_root / "evil.csv").exists()

        status_response = client.get("/api/benchmarks/public_zip_smoke/local-status")
        assert status_response.status_code == 200
        assert status_response.json()["ready"] is True

        manifest_preview_response = client.get(f"/api/artifacts/{job['output']['artifact_id']}/preview")
        assert manifest_preview_response.status_code == 200
        manifest_preview = manifest_preview_response.json()["preview"]
        assert "benchmark_public_download_manifest.v1" in manifest_preview
        assert "unsafe_path" in manifest_preview
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_download_places_direct_csv(tmp_path: Path, monkeypatch: Any) -> None:
    served_dir = tmp_path / "served_direct"
    served_dir.mkdir()
    (served_dir / "credit.csv").write_text("feature,class\n1,good\n2,bad\n", encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/credit.csv"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_csv_smoke",
                            "name": "Public CSV Smoke",
                            "source_kind": "public_test_file",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "csv",
                                        "expected_files": ["credit.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "primary_table": {"path": "credit.csv", "target_column": "class"},
                            "required_files": [
                                {"path": "credit.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_direct_file",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "csv", "expected_files": ["credit.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)

        download_response = client.post("/api/benchmarks/public_csv_smoke/public-download", json={"overwrite": False})
        assert download_response.status_code == 200, download_response.text
        job = download_response.json()
        assert job["status"] == "succeeded"
        assert job["output"]["extracted_file_count"] == 1
        assert job["output"]["local_ready"] is True

        benchmark_root = tmp_path / "data" / "benchmarks" / "public_csv_smoke"
        assert (benchmark_root / "credit.csv").read_text(encoding="utf-8").startswith("feature,class")
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_workflow_runs_baseline_and_reports(tmp_path: Path, monkeypatch: Any) -> None:
    served_dir = tmp_path / "served_workflow"
    served_dir.mkdir()
    rows = ["feature_num,feature_cat,note,class"]
    for index in range(40):
        label = "good" if index % 2 == 0 else "bad"
        category = "low" if index % 3 == 0 else "high"
        note = "steady payer" if label == "good" else "late payment"
        rows.append(f"{index},{category},{note},{label}")
    (served_dir / "workflow.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/workflow.csv"
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": "benchmark_catalog.v1",
                    "datasets": [
                        {
                            "id": "public_workflow_smoke",
                            "name": "Public Workflow Smoke",
                            "source_kind": "public_test_file",
                            "source_url": url,
                            "access": {
                                "kind": "public_direct_download",
                                "requires_account": False,
                                "requires_secret": False,
                                "supports_direct_download": True,
                                "download_urls": [
                                    {
                                        "url": url,
                                        "archive_type": "csv",
                                        "expected_files": ["workflow.csv"],
                                    }
                                ],
                            },
                            "task_types": ["binary_classification"],
                            "modality_tags": ["single_table", "download_smoke"],
                            "scenario": {
                                "kind": "single_table_public_workflow_smoke",
                                "validation_focus": "stratified_split",
                                "feature_focus": ["numeric_imputation", "categorical_encoding", "text_tfidf"],
                                "report_focus": ["baseline_sanity", "leaderboard"],
                            },
                            "primary_table": {"path": "workflow.csv", "target_column": "class"},
                            "required_files": [
                                {"path": "workflow.csv", "role": "primary_table", "description": "Downloaded table."}
                            ],
                            "download": {
                                "method": "public_direct_file",
                                "requires_account": False,
                                "download_urls": [{"url": url, "archive_type": "csv", "expected_files": ["workflow.csv"]}],
                                "command": "Downloaded by test local HTTP server.",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("TABLEX_BENCHMARK_CATALOG_PATH", str(catalog_path))
        client = make_client(tmp_path)
        project_response = client.post(
            "/api/projects",
            json={"name": "Public benchmark workflow", "task_type": "binary_classification"},
        )
        assert project_response.status_code == 200
        project_id = project_response.json()["id"]

        workflow_response = client.post(
            f"/api/projects/{project_id}/benchmarks/public_workflow_smoke/public-workflow",
            json={"overwrite": False},
        )
        assert workflow_response.status_code == 200, workflow_response.text
        workflow_job = workflow_response.json()
        assert workflow_job["status"] == "succeeded"
        output = workflow_job["output"]
        assert output["download_manifest_artifact_id"]
        assert output["dataset_snapshot_id"]
        assert output["evaluation_spec_id"]
        assert output["split_manifest_id"]
        assert output["baseline_strategy_plan_artifact_id"]
        assert output["experiment_run_id"]
        assert output["metrics"]["model_baseline_attempted"] is True
        assert output["run_report_artifact_id"]
        assert output["decision_dashboard_artifact_id"]
        assert output["decision_report_artifact_id"]
        assert output["benchmark_scenario_pack_artifact_id"]
        assert len(output["visualization_ids"]) >= 4
        assert len(output["artifact_ids"]) >= 20

        job_artifacts_response = client.get(f"/api/jobs/{workflow_job['id']}/artifacts")
        assert job_artifacts_response.status_code == 200
        job_artifacts = job_artifacts_response.json()
        assert job_artifacts["summary"]["benchmark_id"] == "public_workflow_smoke"
        assert job_artifacts["summary"]["experiment_run_id"] == output["experiment_run_id"]
        assert job_artifacts["summary"]["artifact_count"] >= 20
        assert job_artifacts["missing_artifact_ids"] == []
        assert any(item["asset_type"] == "decision_report" for item in job_artifacts["artifacts"])

        runs_response = client.get(f"/api/projects/{project_id}/runs")
        assert runs_response.status_code == 200
        assert runs_response.json()[0]["id"] == output["experiment_run_id"]

        artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
        assert artifacts_response.status_code == 200
        asset_types = {item["asset_type"] for item in artifacts_response.json()}
        assert {
            "benchmark_import_manifest",
            "relational_catalog",
            "baseline_strategy_plan",
            "baseline_report",
            "baseline_metrics",
            "evaluation_diagnostics",
            "evaluation_diagnostics_report",
            "run_report",
            "visualization_spec",
            "insight_set",
            "decision_dashboard",
            "decision_report",
            "benchmark_scenario_pack",
        }.issubset(asset_types)

        decision_preview_response = client.get(f"/api/artifacts/{output['decision_report_artifact_id']}/preview")
        assert decision_preview_response.status_code == 200
        assert "Decision Report" in decision_preview_response.json()["preview"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_public_benchmark_workflow_rejects_credentialed_source(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Credentialed benchmark workflow", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/public-workflow",
        json={"overwrite": False},
    )
    assert response.status_code == 400
    assert "credential-free" in response.text


def test_benchmark_evidence_pack_empty_project(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Empty benchmark evidence", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    evidence_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_response.status_code == 200, evidence_response.text
    evidence_job = evidence_response.json()
    assert evidence_job["status"] == "succeeded"
    assert evidence_job["output"]["benchmark_count"] == 0
    assert evidence_job["output"]["benchmark_evidence_pack_artifact_id"]
    assert evidence_job["output"]["benchmark_evidence_report_artifact_id"]
    assert evidence_job["output"]["visualization_artifact_id"]
    assert evidence_job["output"]["evidence_id"]

    report_preview_response = client.get(
        f"/api/artifacts/{evidence_job['output']['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert report_preview_response.status_code == 200
    assert "No benchmark evidence exists yet" in report_preview_response.json()["preview"]


def test_home_credit_fixture_smoke_harness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit fixture smoke", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    smoke_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke",
        json={"overwrite": True},
    )
    assert smoke_response.status_code == 200, smoke_response.text
    smoke_job = smoke_response.json()
    assert smoke_job["status"] == "succeeded"
    output = smoke_job["output"]
    assert output["fixture"]["local_status"]["ready"] is True
    assert output["fixture"]["fixture_matches_expected"] is True
    assert output["dataset_snapshot_id"]
    assert output["quality_gate"]["schema_version"] == "data_quality_gate.v1"
    assert output["evaluation_scenario_comparison_artifact_id"]
    assert output["approval_review_artifact_id"]
    assert output["split_manifest_id"]
    assert output["baseline_strategy_plan_artifact_id"]
    assert output["research_plan_artifact_id"]
    assert output["benchmark_scenario_pack_artifact_id"]
    assert output["benchmark_scenario_report_artifact_id"]
    assert len(output["artifact_ids"]) >= 16

    strategy_preview_response = client.get(f"/api/artifacts/{output['baseline_strategy_plan_artifact_id']}/preview")
    assert strategy_preview_response.status_code == 200
    strategy_preview = strategy_preview_response.json()["preview"]
    assert "adaptive_baseline_planning" in strategy_preview
    assert "relational_aggregation_features" in strategy_preview
    assert "reporting_plan" in strategy_preview

    artifacts_response = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    asset_types = {item["asset_type"] for item in artifacts_response.json()}
    assert {
        "benchmark_import_manifest",
        "relational_catalog",
        "data_quality_gate",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "split_manifest",
        "baseline_strategy_plan",
        "research_plan",
        "benchmark_supporting_table",
        "benchmark_scenario_pack",
        "benchmark_scenario_report",
    }.issubset(asset_types)

    scenario_report_preview_response = client.get(f"/api/artifacts/{output['benchmark_scenario_report_artifact_id']}/preview")
    assert scenario_report_preview_response.status_code == 200
    scenario_report_preview = scenario_report_preview_response.json()["preview"]
    assert "multi_table_credit_risk" in scenario_report_preview
    assert "Fixture results are product smoke checks" in scenario_report_preview

    evidence_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_response.status_code == 200, evidence_response.text
    evidence_job = evidence_response.json()
    assert evidence_job["status"] == "succeeded"
    evidence_output = evidence_job["output"]
    assert evidence_output["benchmark_count"] == 1
    assert evidence_output["benchmark_ids"] == ["kaggle_home_credit_default_risk"]
    assert evidence_output["benchmark_evidence_pack_artifact_id"]
    assert evidence_output["benchmark_evidence_report_id"]
    assert evidence_output["benchmark_evidence_report_artifact_id"]
    assert evidence_output["visualization_id"]
    assert evidence_output["visualization_artifact_id"]
    assert evidence_output["evidence_id"]
    assert len(evidence_output["artifact_ids"]) == 3

    evidence_job_artifacts_response = client.get(f"/api/jobs/{evidence_job['id']}/artifacts")
    assert evidence_job_artifacts_response.status_code == 200
    evidence_job_artifacts = evidence_job_artifacts_response.json()
    assert evidence_job_artifacts["summary"]["benchmark_count"] == 1
    assert evidence_job_artifacts["summary"]["benchmark_evidence_pack_artifact_id"]
    evidence_asset_types = {item["asset_type"] for item in evidence_job_artifacts["artifacts"]}
    assert {"benchmark_evidence_pack", "benchmark_evidence_report", "visualization_spec"}.issubset(
        evidence_asset_types
    )

    evidence_pack_preview_response = client.get(
        f"/api/artifacts/{evidence_output['benchmark_evidence_pack_artifact_id']}/preview"
    )
    assert evidence_pack_preview_response.status_code == 200
    evidence_pack_preview = evidence_pack_preview_response.json()["preview"]
    assert "benchmark_evidence_pack.v1" in evidence_pack_preview
    assert "benchmark_supporting_table" in evidence_pack_preview

    evidence_report_preview_response = client.get(
        f"/api/artifacts/{evidence_output['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert evidence_report_preview_response.status_code == 200
    evidence_report_preview = evidence_report_preview_response.json()["preview"]
    assert "Benchmark Evidence Pack" in evidence_report_preview
    assert "Home Credit Default Risk" in evidence_report_preview


def test_benchmark_relational_catalog_infers_shared_keys(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    project_response = client.post(
        "/api/projects",
        json={"name": "Home Credit tiny", "task_type": "binary_classification"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["id"]

    benchmark_dir = tmp_path / "data" / "benchmarks" / "kaggle_home_credit_default_risk"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "application_train.csv").write_text(
        "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL\n"
        "100001,1,120000\n"
        "100002,0,90000\n"
        "100003,0,110000\n",
        encoding="utf-8",
    )
    (benchmark_dir / "bureau.csv").write_text(
        "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE\n"
        "100001,200001,Active\n"
        "100001,200002,Closed\n"
        "100002,200003,Closed\n",
        encoding="utf-8",
    )

    import_response = client.post(
        f"/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/import",
        json={},
    )
    assert import_response.status_code == 200, import_response.text
    assert len(import_response.json()["supporting_table_artifacts"]) == 1
    assert import_response.json()["supporting_table_artifacts"][0]["asset_type"] == "benchmark_supporting_table"
    output_job_response = client.get(f"/api/projects/{project_id}/jobs")
    assert output_job_response.status_code == 200
    import_job = next(item for item in output_job_response.json() if item["job_type"] == "import_benchmark_dataset")
    assert import_job["output"]["table_count"] == 2
    assert import_job["output"]["relationship_count"] >= 1

    relational_artifact_id = import_response.json()["relational_catalog_artifact"]["id"]
    relational_preview_response = client.get(f"/api/artifacts/{relational_artifact_id}/preview")
    assert relational_preview_response.status_code == 200
    preview = relational_preview_response.json()["preview"]
    assert "relational_catalog.v1" in preview
    assert "SK_ID_CURR" in preview
    assert "shared_key_name" in preview

    seed_assets_response = client.post("/api/assets/seed-defaults")
    assert seed_assets_response.status_code == 200
    collection_response = client.post(f"/api/projects/{project_id}/benchmarks/collection-plan")
    assert collection_response.status_code == 200, collection_response.text

    relational_plan_response = client.post(f"/api/projects/{project_id}/features/relational-plan")
    assert relational_plan_response.status_code == 200, relational_plan_response.text
    relational_plan_job = relational_plan_response.json()
    assert relational_plan_job["status"] == "succeeded"
    assert relational_plan_job["output"]["schema_version"] == "relational_feature_plan.v1"
    assert relational_plan_job["output"]["relational_feature_plan_artifact_id"]
    assert relational_plan_job["output"]["relational_feature_report_artifact_id"]
    assert relational_plan_job["output"]["visualization_id"]
    assert relational_plan_job["output"]["evidence_id"]
    assert relational_plan_job["output"]["supporting_table_count"] == 1
    assert relational_plan_job["output"]["relationship_count"] >= 1
    assert relational_plan_job["output"]["aggregation_candidate_count"] >= 1

    relational_plan_download_response = client.get(
        f"/api/artifacts/{relational_plan_job['output']['relational_feature_plan_artifact_id']}/download"
    )
    assert relational_plan_download_response.status_code == 200
    relational_plan = relational_plan_download_response.json()
    assert relational_plan["schema_version"] == "relational_feature_plan.v1"
    assert relational_plan["source_summary"]["benchmark_id"] == "kaggle_home_credit_default_risk"
    assert relational_plan["source_summary"]["benchmark_collection_plan_artifact_id"] == collection_response.json()[
        "output"
    ]["benchmark_collection_plan_artifact_id"]
    assert relational_plan["agent_task_handoff"]["fit_aggregations_on_training_folds_only"] is True
    assert any(item["risk_level"] == "high" for item in relational_plan["risk_register"])

    relational_report_response = client.get(
        f"/api/artifacts/{relational_plan_job['output']['relational_feature_report_artifact_id']}/preview"
    )
    assert relational_report_response.status_code == 200
    assert "Relational Feature Plan" in relational_report_response.json()["preview"]

    relational_recipe_response = client.post(f"/api/projects/{project_id}/features/relational-recipe/build")
    assert relational_recipe_response.status_code == 200, relational_recipe_response.text
    relational_recipe_job = relational_recipe_response.json()
    assert relational_recipe_job["status"] == "succeeded"
    assert relational_recipe_job["output"]["schema_version"] == "relational_feature_recipe.v1"
    assert relational_recipe_job["output"]["relational_feature_recipe_artifact_id"]
    assert relational_recipe_job["output"]["relational_feature_preview_artifact_id"]
    assert relational_recipe_job["output"]["relational_feature_preview_profile_artifact_id"]
    assert relational_recipe_job["output"]["relational_feature_recipe_report_artifact_id"]
    assert relational_recipe_job["output"]["generated_feature_count"] >= 1
    assert relational_recipe_job["output"]["executed_step_count"] >= 1
    assert relational_recipe_job["output"]["preview_row_count"] > 0

    relational_recipe_download_response = client.get(
        f"/api/artifacts/{relational_recipe_job['output']['relational_feature_recipe_artifact_id']}/download"
    )
    assert relational_recipe_download_response.status_code == 200
    relational_recipe = relational_recipe_download_response.json()
    assert relational_recipe["schema_version"] == "relational_feature_recipe.v1"
    assert relational_recipe["source_summary"]["benchmark_id"] == "kaggle_home_credit_default_risk"
    assert relational_recipe["source_summary"]["relational_feature_plan_artifact_id"] == relational_plan_job[
        "output"
    ]["relational_feature_plan_artifact_id"]
    assert relational_recipe["execution_scope"]["mode"] == "preview_only"
    assert relational_recipe["safety"]["target_column_excluded"] == "TARGET"
    assert relational_recipe["safety"]["fit_on_training_folds_only"] is True
    assert all("TARGET" not in item.get("columns", []) for item in relational_recipe["steps"])

    relational_recipe_preview_response = client.get(
        f"/api/artifacts/{relational_recipe_job['output']['relational_feature_preview_artifact_id']}/download"
    )
    assert relational_recipe_preview_response.status_code == 200
    assert "bureau_categorical_summaries__row_count" in relational_recipe_preview_response.text

    relational_recipe_report_response = client.get(
        f"/api/artifacts/{relational_recipe_job['output']['relational_feature_recipe_report_artifact_id']}/preview"
    )
    assert relational_recipe_report_response.status_code == 200
    assert "Relational Feature Recipe" in relational_recipe_report_response.json()["preview"]

    relational_diagnostics_response = client.post(
        f"/api/projects/{project_id}/features/relational-scenarios/diagnose"
    )
    assert relational_diagnostics_response.status_code == 200, relational_diagnostics_response.text
    relational_diagnostics_job = relational_diagnostics_response.json()
    assert relational_diagnostics_job["status"] == "succeeded"
    assert relational_diagnostics_job["output"]["schema_version"] == (
        "relational_feature_scenario_diagnostics.v1"
    )
    assert relational_diagnostics_job["output"]["relational_feature_scenario_diagnostics_artifact_id"]
    assert relational_diagnostics_job["output"]["relational_feature_scenario_report_artifact_id"]
    assert relational_diagnostics_job["output"]["generated_feature_count"] >= 1
    assert relational_diagnostics_job["output"]["usable_feature_count"] >= 1
    assert relational_diagnostics_job["output"]["scenario_count"] >= 3

    relational_diagnostics_download_response = client.get(
        "/api/artifacts/"
        f"{relational_diagnostics_job['output']['relational_feature_scenario_diagnostics_artifact_id']}/download"
    )
    assert relational_diagnostics_download_response.status_code == 200
    relational_diagnostics = relational_diagnostics_download_response.json()
    assert relational_diagnostics["schema_version"] == "relational_feature_scenario_diagnostics.v1"
    assert relational_diagnostics["safety"]["model_training_performed"] is False
    assert relational_diagnostics["safety"]["fixed_model_strategy"] is False
    assert relational_diagnostics["split_compatibility"]["status"] == "missing_evaluation_spec"
    assert any(item["scenario"] == "safe_relational_preview" for item in relational_diagnostics["scenario_comparison"])

    relational_diagnostics_report_response = client.get(
        f"/api/artifacts/{relational_diagnostics_job['output']['relational_feature_scenario_report_artifact_id']}/preview"
    )
    assert relational_diagnostics_report_response.status_code == 200
    assert "Relational Feature Scenario Diagnostics" in relational_diagnostics_report_response.json()["preview"]

    evidence_pack_response = client.post(f"/api/projects/{project_id}/benchmarks/evidence-pack")
    assert evidence_pack_response.status_code == 200, evidence_pack_response.text
    evidence_pack_job = evidence_pack_response.json()
    assert evidence_pack_job["status"] == "succeeded"
    evidence_pack_download_response = client.get(
        f"/api/artifacts/{evidence_pack_job['output']['benchmark_evidence_pack_artifact_id']}/download"
    )
    assert evidence_pack_download_response.status_code == 200
    evidence_pack = evidence_pack_download_response.json()
    assert evidence_pack["summary"]["relational_recipe_count"] >= 1
    assert evidence_pack["summary"]["relational_diagnostics_count"] >= 1
    evidence_entry = evidence_pack["benchmarks"][0]
    assert evidence_entry["relational_features"]["diagnostics_artifact_id"] == relational_diagnostics_job[
        "output"
    ]["relational_feature_scenario_diagnostics_artifact_id"]
    assert any(stage["stage"] == "Relational diagnostics" for stage in evidence_entry["stages"])
    evidence_report_response = client.get(
        f"/api/artifacts/{evidence_pack_job['output']['benchmark_evidence_report_artifact_id']}/preview"
    )
    assert evidence_report_response.status_code == 200
    assert "Relational scenarios" in evidence_report_response.json()["preview"]

    decision_response = client.post(f"/api/projects/{project_id}/decision-dashboard/generate")
    assert decision_response.status_code == 200, decision_response.text
    decision_job = decision_response.json()
    assert decision_job["status"] == "succeeded"
    decision_download_response = client.get(
        f"/api/artifacts/{decision_job['output']['decision_dashboard_artifact_id']}/download"
    )
    assert decision_download_response.status_code == 200
    decision_dashboard = decision_download_response.json()
    assert decision_dashboard["relational_context"]["diagnostics_artifact_id"] == relational_diagnostics_job[
        "output"
    ]["relational_feature_scenario_diagnostics_artifact_id"]
    assert any(stage["stage"] == "Relational" for stage in decision_dashboard["readiness_stages"])
    decision_report_response = client.get(f"/api/reports/{decision_job['output']['report_id']}/preview")
    assert decision_report_response.status_code == 200
    assert "Relational Feature Context" in decision_report_response.json()["preview"]

    project_report_response = client.post(f"/api/projects/{project_id}/reports/draft", json={})
    assert project_report_response.status_code == 200, project_report_response.text
    project_report_job = project_report_response.json()
    project_report_preview_response = client.get(f"/api/reports/{project_report_job['output']['report_id']}/preview")
    assert project_report_preview_response.status_code == 200
    assert "Relational Feature Context" in project_report_preview_response.json()["preview"]

    evaluation_design_response = client.post(f"/api/projects/{project_id}/evaluation/design")
    assert evaluation_design_response.status_code == 200, evaluation_design_response.text
    candidates_response = client.get(f"/api/projects/{project_id}/evaluation/candidates")
    assert candidates_response.status_code == 200
    random_candidate = next(item for item in candidates_response.json() if item["split_type"] == "random")
    promote_response = client.post(f"/api/evaluation-candidates/{random_candidate['id']}/promote")
    assert promote_response.status_code == 200, promote_response.text
    spec_id = promote_response.json()["id"]
    approval_response = client.post(f"/api/evaluation-specs/{spec_id}/approve")
    assert approval_response.status_code == 200, approval_response.text
    split_response = client.post(f"/api/evaluation-specs/{spec_id}/generate-split")
    assert split_response.status_code == 200, split_response.text

    agent_task_plan_response = client.post(f"/api/projects/{project_id}/approach/agent-task-plan", json={})
    assert agent_task_plan_response.status_code == 200, agent_task_plan_response.text
    agent_contract_response = client.get(
        f"/api/artifacts/{agent_task_plan_response.json()['output']['agent_task_contract_artifact_id']}/download"
    )
    assert agent_contract_response.status_code == 200
    assert agent_contract_response.json()["inputs"]["relational_feature_plan"]["artifact_id"] == relational_plan_job[
        "output"
    ]["relational_feature_plan_artifact_id"]
    assert agent_contract_response.json()["inputs"]["relational_feature_recipe"]["artifact_id"] == (
        relational_recipe_job["output"]["relational_feature_recipe_artifact_id"]
    )
    assert agent_contract_response.json()["inputs"]["relational_feature_scenario_diagnostics"]["artifact_id"] == (
        relational_diagnostics_job["output"]["relational_feature_scenario_diagnostics_artifact_id"]
    )

    contract_artifact_id = agent_task_plan_response.json()["output"]["agent_task_contract_artifact_id"]
    workspace_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/prepare-workspace")
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_job = workspace_response.json()
    assert workspace_job["status"] == "succeeded"
    assert workspace_job["output"]["materialized_relational_context_count"] >= 6
    workspace_download_response = client.get(
        f"/api/artifacts/{workspace_job['output']['agent_workspace_manifest_artifact_id']}/download"
    )
    assert workspace_download_response.status_code == 200
    workspace_manifest = workspace_download_response.json()
    relational_sources = [
        item
        for item in workspace_manifest["materialized_sources"]
        if item["source_kind"] == "relational_context_artifact"
    ]
    assert len(relational_sources) >= 6
    relational_paths = [item["context_path"] for item in relational_sources]
    assert all(path.startswith(".harness/context/relational/") for path in relational_paths)
    assert any("relational_feature_plan" in path and path.endswith(".json") for path in relational_paths)
    assert any("relational_feature_recipe" in path and path.endswith(".json") for path in relational_paths)
    assert any("relational_feature_preview" in path and path.endswith(".csv") for path in relational_paths)
    assert any(
        "relational_feature_preview_profile" in path and path.endswith(".json") for path in relational_paths
    )
    assert any(
        "relational_feature_scenario_diagnostics" in path and path.endswith(".json")
        for path in relational_paths
    )
    assert any(
        "relational_feature_scenario_report" in path and path.endswith(".md") for path in relational_paths
    )
    assert all(item["artifact_id"] and item["content_hash"] for item in relational_sources)
    assert all(isinstance(item["size_bytes"], int) for item in relational_sources)
    assert any(
        item["artifact_id"]
        == relational_diagnostics_job["output"]["relational_feature_scenario_diagnostics_artifact_id"]
        for item in relational_sources
    )

    readiness_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/readiness-review")
    assert readiness_response.status_code == 200, readiness_response.text
    readiness_job = readiness_response.json()
    assert readiness_job["status"] == "succeeded"
    readiness_download_response = client.get(
        f"/api/artifacts/{readiness_job['output']['agent_task_readiness_review_artifact_id']}/download"
    )
    assert readiness_download_response.status_code == 200
    readiness = readiness_download_response.json()
    relational_check = next(item for item in readiness["checks"] if item["check_id"] == "relational_context")
    assert relational_check["status"] == "pass"
    assert "relational context artifact" in relational_check["summary"]

    stub_response = client.post(f"/api/agent-task-contracts/{contract_artifact_id}/run-local-stub")
    assert stub_response.status_code == 200, stub_response.text
    stub_job = stub_response.json()
    assert stub_job["status"] == "succeeded"
    assert stub_job["output"]["relational_context_source_count"] >= 6
    assert stub_job["output"]["relational_context_summary_artifact_id"]
    assert stub_job["output"]["approach_decision_trace_artifact_id"]
    assert len(stub_job["output"]["visualization_ids"]) >= 2

    stub_report_response = client.get(
        f"/api/artifacts/{stub_job['output']['ingested_artifact_ids'][0]}/download"
    )
    assert stub_report_response.status_code == 200
    assert "Relational Runner Context" in stub_report_response.text

    relational_summary_response = client.get(
        f"/api/artifacts/{stub_job['output']['relational_context_summary_artifact_id']}/download"
    )
    assert relational_summary_response.status_code == 200
    relational_summary = relational_summary_response.json()
    assert relational_summary["schema_version"] == "relational_runner_context_summary.v1"
    assert relational_summary["status"] == "available"
    assert relational_summary["source_count"] >= 6
    assert relational_summary["coverage"]["has_scenario_report"] is True
    assert relational_summary["deferred_safety_checks"]
    assert relational_summary["recommended_agent_task_scenarios"]

    decision_trace_response = client.get(
        f"/api/artifacts/{stub_job['output']['approach_decision_trace_artifact_id']}/download"
    )
    assert decision_trace_response.status_code == 200
    decision_trace = decision_trace_response.json()
    assert decision_trace["schema_version"] == "approach_decision_trace.v1"
    assert decision_trace["autonomy_policy"]["approach_selection"] == "open_ended_with_harness_constraints"
    assert "propose_new_feature_families" in decision_trace["autonomy_policy"]["runner_may"]
    assert any(
        item["approach"] == "fixed_predefined_recipe_execution"
        and item["status"] == "rejected_as_product_default"
        for item in decision_trace["rejected_or_deferred_approaches"]
    )
    assert decision_trace["context_used"]["relational_context_available"] is True

    agent_results_response = client.get(f"/api/projects/{project_id}/agent-task-results")
    assert agent_results_response.status_code == 200
    agent_results = agent_results_response.json()
    relational_result = next(item for item in agent_results if item["job_id"] == stub_job["id"])
    assert relational_result["relational_context"]["source_count"] >= 6
    assert relational_result["relational_context"]["usable_feature_count"] >= 1
    assert relational_result["relational_context"]["summary_artifact_id"] == stub_job["output"][
        "relational_context_summary_artifact_id"
    ]
    assert relational_result["artifacts"]["relational_context_summary"]["id"] == stub_job["output"][
        "relational_context_summary_artifact_id"
    ]
    assert relational_result["artifacts"]["approach_decision_trace"]["id"] == stub_job["output"][
        "approach_decision_trace_artifact_id"
    ]
    assert relational_result["approach_decision_trace"]["policy"] == "open_ended_with_harness_constraints"
    assert relational_result["approach_decision_trace"]["relational_context_available"] is True

    ideas_response = client.post(f"/api/projects/{project_id}/approach/ideas/generate")
    assert ideas_response.status_code == 200, ideas_response.text
    ideas_list_response = client.get(f"/api/projects/{project_id}/approach/ideas")
    assert ideas_list_response.status_code == 200
    idea = ideas_list_response.json()[0]
    context_response = client.post(f"/api/ideas/{idea['id']}/prepare-agent-context")
    assert context_response.status_code == 200, context_response.text
    context_payload_response = client.get(f"/api/artifacts/{context_response.json()['output']['artifact_id']}/download")
    assert context_payload_response.status_code == 200
    assert context_payload_response.json()["relational_feature_plan_context"]["artifact_id"] == relational_plan_job[
        "output"
    ]["relational_feature_plan_artifact_id"]
    assert context_payload_response.json()["relational_feature_recipe_context"]["artifact_id"] == (
        relational_recipe_job["output"]["relational_feature_recipe_artifact_id"]
    )
    assert context_payload_response.json()["relational_feature_scenario_diagnostics_context"]["artifact_id"] == (
        relational_diagnostics_job["output"]["relational_feature_scenario_diagnostics_artifact_id"]
    )
