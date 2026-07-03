from __future__ import annotations

import threading
import time
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import tabular_harness.services.agent_sessions as agent_sessions_module
import tabular_harness.services.analysis_notebooks as analysis_notebooks_module
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.db.session import ensure_sqlite_mvp_columns
from tabular_harness.models.entities import (
    AgentSession,
    AgentSupervisorLease,
    AgentTranscriptEvent,
    Artifact,
    Base,
    Job,
    Project,
    User,
    utc_now,
)
from tabular_harness.services.agent_sessions import (
    CODEX_RAW_TRANSCRIPT_FILENAME,
    CODEX_STDERR_LOG_FILENAME,
    StreamFileTailer,
    acquire_supervisor_lease,
    append_codex_stream_lines,
    append_runner_stream_to_workspace,
    append_session_event,
    asset_type_for_session_output,
    build_turn_prompt,
    chat_update_message_from_text,
    ingest_session_workspace_outputs,
    latest_codex_transcript_output_at,
    latest_project_response_locale,
    mark_user_instructions_delivered,
    maybe_register_chat_update_from_workspace_output,
    maybe_request_codex_progress_update,
    maybe_request_codex_progress_update_safely,
    metadata_for_session_output,
    progress_request_path,
    publish_raw_codex_transcript_snapshot,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    release_supervisor_lease,
    renew_supervisor_lease,
    research_plan_locale_request_path,
    reserve_transcript_event_indexes,
    run_codex_cli_turn_streaming,
    session_output_artifact_name,
    should_register_session_output,
    start_active_main_session_supervisors,
    start_main_agent_session_supervisor_thread,
    start_supervisor_lease_heartbeat,
    supervisor_slot_active,
)
from tabular_harness.services.approach import store_text_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path
from tabular_harness.services.jobs import create_job


def test_agent_session_marimo_notebook_outputs_are_analysis_notebooks() -> None:
    path = Path("notebooks/grandmaster_eda.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "data_understanding"


def test_agent_session_model_notebook_outputs_are_diagnostics_notebooks() -> None:
    path = Path("notebooks/salary_model_diagnostics.py")

    assert asset_type_for_session_output(path) == "analysis_notebook"
    assert metadata_for_session_output(path)["notebook_kind"] == "model_diagnostics"


def test_agent_session_research_plan_json_outputs_are_research_plans() -> None:
    assert asset_type_for_session_output(Path("outputs/research_plan.json")) == "research_plan"
    assert asset_type_for_session_output(Path("artifacts/research_plan_timeline.json")) == "research_plan"


def test_agent_session_raw_codex_transcript_outputs_are_transcript_artifacts() -> None:
    path = Path(f"artifacts/{CODEX_RAW_TRANSCRIPT_FILENAME}")

    assert asset_type_for_session_output(path) == "agent_session_transcript"
    assert metadata_for_session_output(path) == {"transcript_kind": "codex_cli_stdout_jsonl", "raw_codex_cli": True}


def test_agent_session_codex_stderr_outputs_are_log_artifacts() -> None:
    path = Path(f"artifacts/{CODEX_STDERR_LOG_FILENAME}")

    assert asset_type_for_session_output(path) == "agent_session_log"
    assert metadata_for_session_output(path) == {"transcript_kind": "codex_cli_stderr", "raw_codex_cli": True}


def test_codex_stream_lines_are_persisted_and_published_without_rewriting_stdout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    stdout_line = '{"type":"thread.started","thread_id":"abc"}\n'
    stderr_line = "2026-07-03T00:00:00Z ERROR example\n"

    append_runner_stream_to_workspace(workspace, stream_name="stdout", line=stdout_line)
    append_runner_stream_to_workspace(workspace, stream_name="stderr", line=stderr_line)

    assert raw_codex_transcript_path(workspace).read_text(encoding="utf-8") == stdout_line
    assert raw_codex_stderr_path(workspace).read_text(encoding="utf-8") == stderr_line

    published = publish_raw_codex_transcript_snapshot(workspace)

    assert workspace / "artifacts" / CODEX_RAW_TRANSCRIPT_FILENAME in published
    assert workspace / "artifacts" / CODEX_STDERR_LOG_FILENAME in published
    assert (workspace / "artifacts" / CODEX_RAW_TRANSCRIPT_FILENAME).read_text(encoding="utf-8") == stdout_line
    assert (workspace / "artifacts" / CODEX_STDERR_LOG_FILENAME).read_text(encoding="utf-8") == stderr_line


def test_stream_file_tailer_reads_new_complete_lines_without_replaying_prefix(tmp_path: Path) -> None:
    path = tmp_path / "codex_raw_transcript.jsonl"
    path.write_text('{"type":"thread.started"}\n', encoding="utf-8")
    tailer = StreamFileTailer(path, offset=path.stat().st_size)

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"turn.started"}\n{"type"')

    assert tailer.read_completed_lines() == ['{"type":"turn.started"}\n']

    with path.open("a", encoding="utf-8") as handle:
        handle.write(':"item.completed"}\n')

    assert tailer.read_completed_lines() == ['{"type":"item.completed"}\n']
    assert tailer.read_completed_lines() == []


def test_codex_cli_turn_streaming_uses_workspace_file_transcript(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"thread.started","thread_id":"thread_file_tail"}'
printf '%s\n' '{"type":"turn.started"}'
printf '%s\n' 'fake stderr line' >&2
printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}'
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        user = User(id="u_file_tail", email="file-tail@example.com", locale="ja-JP")
        project = Project(id="p_file_tail", name="File Tail", created_by=user.id)
        session = AgentSession(
            id="as_file_tail",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([user, project, session])
        db.commit()

    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_file_tail",
        session_id="as_file_tail",
        workspace=workspace,
        prompt="hello",
        delivered_user_event_indexes=(),
        agent_model=None,
        timeout_seconds=30,
    )

    assert return_code == 0
    assert '"thread_id":"thread_file_tail"' in raw_codex_transcript_path(workspace).read_text(encoding="utf-8")
    assert raw_codex_stderr_path(workspace).read_text(encoding="utf-8") == "fake stderr line\n"
    assert progress_request_path(workspace).exists()
    assert "locale: ja-JP" in progress_request_path(workspace).read_text(encoding="utf-8")

    with session_factory() as db:
        session = db.get(AgentSession, "as_file_tail")
        assert session is not None
        assert session.codex_thread_id == "thread_file_tail"
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_file_tail")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert [event.event_type for event in events if event.source == "codex_cli"] == [
        "thread.started",
        "turn.started",
        "item.completed",
        "process_exited",
    ]
    process_started = next(event for event in events if event.event_type == "process_started")
    assert loads_json(process_started.payload_json, {})["stdout_mode"] == "workspace_file_tail"


def test_codex_cli_turn_streaming_cancels_when_supervisor_lease_is_lost(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/bin/sh
while IFS= read -r _line; do
  :
done
printf '%s\n' '{"type":"thread.started","thread_id":"thread_cancel"}'
/bin/sleep 30
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    with session_factory() as db:
        project = Project(id="p_cancel_tail", name="Cancel Tail")
        session = AgentSession(
            id="as_cancel_tail",
            project_id=project.id,
            goal_text="Continue.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

    cancel_event = threading.Event()
    cancel_event.set()
    return_code = run_codex_cli_turn_streaming(
        session_factory,
        store=store,
        project_id="p_cancel_tail",
        session_id="as_cancel_tail",
        workspace=workspace,
        prompt="hello",
        delivered_user_event_indexes=(),
        agent_model=None,
        timeout_seconds=30,
        cancel_event=cancel_event,
    )

    assert return_code not in {0, None}
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_cancel_tail")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
    event_types = [event.event_type for event in events]
    assert "process_cancelled" in event_types
    assert "process_exited" in event_types
    assert raw_codex_transcript_path(workspace).read_text(encoding="utf-8").strip()


def test_codex_stream_lines_are_indexed_in_one_batch(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_stream_batch", name="Stream Batch")
        session = AgentSession(id="as_stream_batch", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    append_codex_stream_lines(
        session_factory,
        project_id="p_stream_batch",
        session_id="as_stream_batch",
        lines=[
            ("stdout", '{"type":"thread.started","thread_id":"thread_1"}\n'),
            ("stdout", '{"type":"turn.started"}\n'),
            ("stderr", "warning line\n"),
        ],
    )

    with session_factory() as db:
        session = db.get(AgentSession, "as_stream_batch")
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_stream_batch")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert session is not None
    assert session.codex_thread_id == "thread_1"
    assert [event.event_index for event in events] == [0, 1, 2]
    assert [event.event_type for event in events] == ["thread.started", "turn.started", "codex_stderr"]
    assert events[-1].source == "codex_cli_stderr"


def test_supervisor_thread_releases_slot_when_global_runner_is_replaced(tmp_path: Path, monkeypatch: Any) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(id="p_slot_release", name="Slot Release")
        session = AgentSession(id="as_slot_release", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    calls: list[str] = []

    def fake_runner(*args: object, **kwargs: object) -> None:
        del args, kwargs
        calls.append("ran")

    monkeypatch.setattr(agent_sessions_module, "run_main_agent_session_supervisor", fake_runner)

    thread = start_main_agent_session_supervisor_thread(
        session_factory,
        store,
        project_id="p_slot_release",
        session_id="as_slot_release",
    )

    assert thread is not None
    thread.join(timeout=2)
    assert calls == ["ran"]
    assert supervisor_slot_active("as_slot_release") is False


def test_startup_supervisor_recovers_full_auto_project_without_browser_polling(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_startup_recover",
            name="Startup Recover",
            autonomy_mode="full_auto",
            current_phase="AUTONOMOUS_LOOP",
        )
        db.add(project)
        db.commit()

    launched: list[tuple[str, str]] = []

    def fake_runner(
        session_factory_arg: object,
        store_arg: object,
        *,
        project_id: str,
        session_id: str,
        **kwargs: object,
    ) -> None:
        del session_factory_arg, store_arg, kwargs
        launched.append((project_id, session_id))

    threads = start_active_main_session_supervisors(
        session_factory,
        store,
        supervisor_runner=fake_runner,
    )

    assert threads == []
    assert len(launched) == 1
    assert launched[0][0] == "p_startup_recover"

    with session_factory() as db:
        session = db.get(AgentSession, launched[0][1])
        assert session is not None
        assert session.session_type == "main_autonomous"
        assert session.status == "starting"
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == session.id)
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert [event.event_type for event in events] == ["session_created"]


def test_agent_supervisor_lease_prevents_duplicate_cross_process_owners(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_lease", name="Lease Project")
        session = AgentSession(id="as_lease", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    assert acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)
    assert not acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b", ttl_seconds=60)
    assert renew_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)

    with session_factory() as db:
        lease = db.get(AgentSupervisorLease, "as_lease")
        assert lease is not None
        lease.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    assert acquire_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b", ttl_seconds=60)
    assert not renew_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a", ttl_seconds=60)

    release_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-a")
    with session_factory() as db:
        assert db.get(AgentSupervisorLease, "as_lease") is not None

    release_supervisor_lease(session_factory, session_id="as_lease", owner_id="owner-b")
    with session_factory() as db:
        assert db.get(AgentSupervisorLease, "as_lease") is None


def test_supervisor_lease_heartbeat_signals_lost_lease(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_lease_heartbeat", name="Lease Heartbeat")
        session = AgentSession(id="as_lease_heartbeat", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    assert acquire_supervisor_lease(
        session_factory,
        session_id="as_lease_heartbeat",
        owner_id="owner-a",
        ttl_seconds=30,
    )
    stop_event, lease_lost_event, thread = start_supervisor_lease_heartbeat(
        session_factory,
        session_id="as_lease_heartbeat",
        owner_id="owner-a",
        ttl_seconds=3,
    )
    try:
        with session_factory() as db:
            lease = db.get(AgentSupervisorLease, "as_lease_heartbeat")
            assert lease is not None
            lease.owner_id = "owner-b"
            db.commit()

        deadline = time.monotonic() + 5
        while not lease_lost_event.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)

        assert lease_lost_event.is_set()
        with session_factory() as db:
            lease = db.get(AgentSupervisorLease, "as_lease_heartbeat")
            assert lease is not None
            assert lease.owner_id == "owner-b"
    finally:
        stop_event.set()
        thread.join(timeout=2)


def test_main_supervisor_stops_before_runner_when_lease_is_lost(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_lease_lost_supervisor",
            name="Lease Lost Supervisor",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_lease_lost_supervisor",
            project_id=project.id,
            goal_text="Continue.",
            status="between_turns",
        )
        db.add_all([project, session])
        db.commit()

    lost_event = threading.Event()
    lost_event.set()
    stop_event = threading.Event()
    dummy_thread = threading.Thread(target=lambda: None)
    dummy_thread.start()
    dummy_thread.join(timeout=1)

    monkeypatch.setattr(
        agent_sessions_module,
        "start_supervisor_lease_heartbeat",
        lambda *args, **kwargs: (stop_event, lost_event, dummy_thread),
    )
    runner_calls: list[str] = []

    def fail_if_runner_starts(*args: object, **kwargs: object) -> int:
        del args, kwargs
        runner_calls.append("started")
        return 0

    monkeypatch.setattr(agent_sessions_module, "run_codex_cli_turn_streaming", fail_if_runner_starts)

    agent_sessions_module.run_main_agent_session_supervisor(
        session_factory,
        store,
        project_id="p_lease_lost_supervisor",
        session_id="as_lease_lost_supervisor",
        max_turns=1,
        slot_acquired=True,
        lease_owner_id="owner-a",
    )

    assert runner_calls == []
    assert stop_event.is_set()
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_lease_lost_supervisor")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert [event.event_type for event in events] == ["supervisor_lease_lost"]
        assert db.get(AgentSupervisorLease, "as_lease_lost_supervisor") is None


def test_transcript_index_reservation_survives_uncommitted_sidecar_event(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_index_reservation", name="Index Reservation")
        session = AgentSession(id="as_index_reservation", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.commit()

    with session_factory() as db:
        session = db.get(AgentSession, "as_index_reservation")
        assert session is not None
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="progress_update_requested",
            role="harness",
            title="Progress update requested",
            content="Progress update requested.",
            payload={},
        )

        append_codex_stream_lines(
            session_factory,
            project_id="p_index_reservation",
            session_id="as_index_reservation",
            lines=[
                ("stdout", '{"type":"thread.started","thread_id":"thread_2"}\n'),
                ("stdout", '{"type":"turn.started"}\n'),
            ],
        )
        db.commit()

    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(AgentTranscriptEvent.session_id == "as_index_reservation")
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )

    assert [event.event_index for event in events] == [0, 1, 2]
    assert [event.event_type for event in events] == [
        "progress_update_requested",
        "thread.started",
        "turn.started",
    ]


def test_transcript_index_reservation_uses_cached_next_index_without_db_max_query() -> None:
    session_id = "as_cached_index"
    agent_sessions_module._TRANSCRIPT_EVENT_NEXT_INDEX.pop(session_id, None)

    class CountingDB:
        calls = 0

        def scalar(self, statement: Any) -> int:
            del statement
            self.calls += 1
            return 41

    first_db = CountingDB()
    assert reserve_transcript_event_indexes(first_db, session_id=session_id, count=2) == 42
    assert first_db.calls == 1

    class RaisingDB:
        def scalar(self, statement: Any) -> int:
            del statement
            raise AssertionError("cached transcript index reservation should not query DB max")

    try:
        assert reserve_transcript_event_indexes(RaisingDB(), session_id=session_id, count=3) == 44
        assert agent_sessions_module._TRANSCRIPT_EVENT_NEXT_INDEX[session_id] == 47
    finally:
        agent_sessions_module._TRANSCRIPT_EVENT_NEXT_INDEX.pop(session_id, None)


def test_sqlite_schema_sync_repairs_duplicate_transcript_indexes(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_index_repair", name="Index Repair")
        session = AgentSession(id="as_index_repair", project_id=project.id, goal_text="Continue.")
        db.add_all([project, session])
        db.add_all(
            [
                AgentTranscriptEvent(
                    id="agte_dup_1",
                    project_id=project.id,
                    session_id=session.id,
                    event_index=0,
                    source="tablex_sidecar",
                    event_type="first",
                    payload_json="{}",
                ),
                AgentTranscriptEvent(
                    id="agte_dup_2",
                    project_id=project.id,
                    session_id=session.id,
                    event_index=0,
                    source="codex_cli",
                    event_type="second",
                    payload_json="{}",
                ),
            ]
        )
        db.commit()

    ensure_sqlite_mvp_columns(engine)

    with engine.connect() as connection:
        duplicates = list(
            connection.execute(
                select(AgentTranscriptEvent.session_id, AgentTranscriptEvent.event_index)
                .group_by(AgentTranscriptEvent.session_id, AgentTranscriptEvent.event_index)
                .having(func.count() > 1)
            )
        )
        indexes = [row[1] for row in connection.exec_driver_sql("PRAGMA index_list(agent_transcript_events)")]
        artifact_indexes = [row[1] for row in connection.exec_driver_sql("PRAGMA index_list(artifacts)")]

    assert duplicates == []
    assert "ux_agent_transcript_events_session_index" in indexes
    assert "ix_artifacts_project_created" in artifact_indexes
    assert "ix_artifacts_project_type_created" in artifact_indexes


def test_session_output_artifact_name_uses_relative_path_to_avoid_stem_collisions() -> None:
    report_name = session_output_artifact_name("as_path", Path("reports/summary.md"))
    output_name = session_output_artifact_name("as_path", Path("outputs/summary.md"))
    markdown_report_name = session_output_artifact_name("as_path", Path("reports/salary_band_report.md"))
    html_report_name = session_output_artifact_name("as_path", Path("reports/salary_band_report.html"))

    assert report_name != output_name
    assert markdown_report_name != html_report_name
    assert "reports_summary_md" in report_name
    assert "outputs_summary_md" in output_name
    assert "reports_salary_band_report_md" in markdown_report_name
    assert "reports_salary_band_report_html" in html_report_name


def test_session_output_registration_throttles_fast_intermediate_versions(tmp_path: Path) -> None:
    existing_path = tmp_path / "stored" / "report.md"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("old", encoding="utf-8")
    workspace_path = tmp_path / "workspace" / "reports" / "report.md"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("new", encoding="utf-8")
    existing = Artifact(
        id="art_recent",
        project_id="p_recent",
        asset_type="agent_session_report",
        name="agent_session_report",
        version=1,
        uri=str(existing_path.parent),
        content_hash="old",
        metadata_json=dumps_json({"primary_path": str(existing_path)}),
        created_at=utc_now(),
    )

    assert should_register_session_output(workspace_path, existing) is False

    existing.created_at = utc_now() - timedelta(seconds=45)
    assert should_register_session_output(workspace_path, existing) is True


def test_turn_prompt_delivers_all_undelivered_user_instructions_beyond_recent_raw_window(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_prompt", name="Prompt Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_prompt",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content="評価指標はROC-AUCにしてください。",
            payload={},
        )
        for index in range(120):
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="item.completed",
                role="runner",
                title="Codex event",
                content=f"raw event {index}",
                payload={"type": "item.completed"},
            )
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)
        assert "評価指標はROC-AUCにしてください。" in prompt.text
        assert prompt.delivered_user_event_indexes

        mark_user_instructions_delivered(
            session_factory,
            session_id=session.id,
            delivered_user_event_indexes=prompt.delivered_user_event_indexes,
        )
        prompt_after_delivery = build_turn_prompt(db, project=project, session=session)
        assert "評価指標はROC-AUCにしてください。" not in prompt_after_delivery.text


def test_chat_update_marks_delivered_agent_chat_job_succeeded(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    report_path = workspace / "reports" / "chat_update.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        "給与データの粒度を確認しています。\n\n次に会社テーブルとのjoin coverageを見ます。",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(
            id="p_chat_complete",
            name="Chat Complete",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_chat_complete",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Keep the user informed.",
            workspace_path=str(workspace),
        )
        other_session = AgentSession(
            id="as_other_chat",
            project_id=project.id,
            session_type="main_autonomous",
            status="running",
            goal_text="Other session.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session, other_session])
        db.flush()
        chat_job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "状況を説明してください",
                "locale": "ja-JP",
                "delivered_agent_session_id": session.id,
            },
            priority=90,
        )
        unrelated_job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project.id,
            input_payload={
                "message": "別セッションです",
                "locale": "ja-JP",
                "delivered_agent_session_id": other_session.id,
            },
            priority=90,
        )
        source_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_session_report",
            name="agent_session_reports_chat_update_md",
            filename="chat_update.md",
            text=report_path.read_text(encoding="utf-8"),
            metadata={"project_id": project.id, "agent_session_id": session.id},
        )

        maybe_register_chat_update_from_workspace_output(
            db,
            store=store,
            project=project,
            session=session,
            path=report_path,
            artifact=source_artifact,
        )
        db.commit()

        db.refresh(chat_job)
        db.refresh(unrelated_job)
        assert chat_job.status == "succeeded"
        assert unrelated_job.status == "queued"
        output = loads_json(chat_job.output_json, {})
        assert output["status"] == "answered_by_main_codex_session"
        assert output["agent_session_id"] == session.id
        assert output["response_locale"] == "ja-JP"
        assert isinstance(output.get("progress_artifact_id"), str)
        chat_artifacts = list(
            db.scalars(select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn"))
        )
        assert len(chat_artifacts) == 1
        metadata = loads_json(chat_artifacts[0].metadata_json, {})
        assert metadata["source"] == "main_codex_session_chat_update"


def test_turn_prompt_includes_living_research_plan_contract(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)

    with session_factory() as db:
        project = Project(id="p_plan", name="Plan Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_plan",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)

        assert "outputs/research_plan.json" in prompt.text
        assert "timeline_blocks" in prompt.text
        assert "freely add, remove, reorder, branch, or revise" in prompt.text


def test_runner_failure_backoff_counts_attempts_not_sidecar_events(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_retry_count", name="Retry Count", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_retry_count",
            project_id=project.id,
            goal_text="Keep the main session alive.",
        )
        db.add_all([project, session])
        db.flush()
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_unavailable",
            role="harness",
            title="Codex CLI is not available",
            content="Codex binary is missing.",
            payload={},
        )
        db.commit()

        assert agent_sessions_module.consecutive_runner_failure_count(db, session.id) == 1
        assert agent_sessions_module.retry_delay_seconds(1) == 5

        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_retry_scheduled",
            role="harness",
            title="Codex runner retry scheduled",
            content="Retry scheduled.",
            payload={"retry_delay_seconds": 5},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="runner_unavailable",
            role="harness",
            title="Codex CLI is still not available",
            content="Codex binary is missing.",
            payload={},
        )
        db.commit()

        assert agent_sessions_module.consecutive_runner_failure_count(db, session.id) == 2
        assert agent_sessions_module.retry_delay_seconds(2) == 30


def test_turn_prompt_keeps_chat_update_human_facing_not_internal_changelog(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_chat_prompt", name="Chat Prompt", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_chat_prompt",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
        )
        db.add_all([project, session])
        db.commit()

        prompt = build_turn_prompt(db, project=project, session=session)

        assert "reports/chat_update.md" in prompt.text
        assert ".tablex/inbox/progress_request.md" in prompt.text
        assert "user-facing explanation, not an internal changelog" in prompt.text
        assert "Avoid raw artifact IDs" in prompt.text
        assert "do not make approval-waiting the dominant status" in prompt.text
        assert "make that active work the headline" in prompt.text
        assert "Do not present Full Auto as stopped on approval" in prompt.text
        assert "which reversible analysis, modeling, diagnostics, notebook/report work, or research" in prompt.text


def test_project_response_locale_uses_latest_explicit_user_or_chat_locale(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    now = utc_now()

    with sessionmaker(engine)() as db:
        user = User(id="u_locale", email="locale@example.com", locale="en-US", updated_at=now)
        project = Project(id="p_locale", name="Locale Project", created_by=user.id)
        start_job = Job(
            id="job_start_locale",
            project_id=project.id,
            job_type="start_autonomous_loop",
            input_json=dumps_json({"locale": "ja-JP"}),
            created_at=now + timedelta(seconds=10),
        )
        db.add_all([user, project, start_job])
        db.commit()

        assert latest_project_response_locale(db, project) == "ja-JP"

        user.locale = "fr-FR"
        user.updated_at = now + timedelta(seconds=20)
        db.commit()

        assert latest_project_response_locale(db, project) == "fr-FR"

        chat_job = Job(
            id="job_chat_locale",
            project_id=project.id,
            job_type="agent_chat_turn",
            input_json=dumps_json({"message": "状況を説明して", "locale": "ja-JP"}),
            created_at=now + timedelta(seconds=30),
        )
        db.add(chat_job)
        db.commit()

        assert latest_project_response_locale(db, project) == "ja-JP"


def test_latest_codex_output_ignores_sidecar_events(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_codex_time", name="Codex Time", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_codex_time",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            last_heartbeat_at=utc_now() - timedelta(minutes=10),
        )
        db.add_all([project, session])
        db.flush()
        codex_event = append_session_event(
            db,
            session,
            source="codex_cli",
            event_type="item.completed",
            role="runner",
            title="Codex message",
            content="Working on analysis.",
            payload={},
        )
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="progress_update_requested",
            role="harness",
            title="Progress update requested",
            content="Sidecar nudge.",
            payload={},
            update_heartbeat=False,
        )
        db.commit()

        assert latest_codex_transcript_output_at(db, session_id=session.id) == codex_event.created_at


def test_progress_update_nudge_writes_inbox_without_faking_heartbeat(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    workspace = tmp_path / "workspace"
    old_heartbeat = utc_now() - timedelta(minutes=20)

    with sessionmaker(engine)() as db:
        project = Project(id="p_nudge", name="Nudge Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_nudge",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
            last_heartbeat_at=old_heartbeat,
        )
        db.add_all([project, session])
        db.commit()

        event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        db.commit()

        assert event is not None
        db.refresh(session)
        assert session.last_heartbeat_at is not None
        assert session.last_heartbeat_at.replace(tzinfo=timezone.utc) == old_heartbeat
        request_path = progress_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "reports/chat_update.md" in request_text
        assert "Raw logの要約ではなく" in request_text

        second_event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale="ja-JP",
            now=utc_now(),
            stale_after_seconds=60,
            min_interval_seconds=300,
        )
        assert second_event is None


def test_supervisor_safe_progress_update_uses_project_locale_without_browser_polling(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    workspace = tmp_path / "workspace"

    with session_factory() as db:
        user = User(id="u_progress_locale", email="progress@example.com", locale="ja-JP")
        project = Project(
            id="p_safe_nudge",
            name="Safe Nudge Project",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
            created_by=user.id,
        )
        session = AgentSession(
            id="as_safe_nudge",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            status="running",
            workspace_path=str(workspace),
            created_at=utc_now() - timedelta(minutes=20),
            started_at=utc_now() - timedelta(minutes=20),
        )
        db.add_all([user, project, session])
        db.commit()

    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id="p_safe_nudge",
        session_id="as_safe_nudge",
    )

    request_path = progress_request_path(workspace)
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "locale: ja-JP" in request_text
    assert "Raw logの要約ではなく" in request_text
    with session_factory() as db:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == "as_safe_nudge",
                    AgentTranscriptEvent.event_type == "progress_update_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["locale"] == "ja-JP"


def test_chat_update_message_uses_latest_concise_tail_for_cumulative_files() -> None:
    text = "\n\n".join(
        [
            "2026-07-03 進捗: 古い進捗です。" + "詳細。" * 500,
            "2026-07-03 進捗: 最新の短い報告です。モデル候補を比較し、次にNotebookを更新します。",
        ]
    )

    message = chat_update_message_from_text(text, limit=200)

    assert "最新の短い報告" in message
    assert "古い進捗" not in message


def test_codex_authored_chat_update_is_registered_as_persistent_chat_turn(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True)
    chat_update = reports_dir / "chat_update.md"
    chat_update.write_text("データ理解を進めています。次に欠損と重複を確認します。", encoding="utf-8")

    with session_factory() as db:
        project = Project(id="p_chat", name="Chat Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_chat",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(chat_artifacts) == 1
        payload = loads_json(artifact_primary_path(chat_artifacts[0]).read_text(encoding="utf-8"), {})
        assert payload["user_message"] == ""
        assert payload["assistant_message"] == "データ理解を進めています。次に欠損と重複を確認します。"
        assert payload["intent"]["type"] == "autonomous_agent_progress_report"

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        unchanged_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(unchanged_chat_artifacts) == 1

        chat_update.write_text("データ理解を進めています。重複候補を発見したので深掘りします。", encoding="utf-8")
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        updated_chat_artifacts = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
                .order_by(Artifact.created_at.asc())
            )
        )
        assert len(updated_chat_artifacts) == 2


def test_codex_authored_marimo_notebook_is_auto_captured_on_workspace_ingest(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "grandmaster_eda.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )
    captured_notebooks: list[str] = []

    def fake_capture(db: Any, *, store: LocalArtifactStore, notebook_artifact: Artifact) -> Any:
        del db, store
        captured_notebooks.append(notebook_artifact.id)
        return SimpleNamespace(
            html_artifact=SimpleNamespace(id="art_auto_html"),
            manifest_artifact=SimpleNamespace(id="art_auto_manifest"),
            evidence_html_artifact=SimpleNamespace(id="art_auto_evidence"),
        )

    monkeypatch.setattr(analysis_notebooks_module, "create_notebook_execution_capture", fake_capture)

    with session_factory() as db:
        project = Project(id="p_notebook_capture", name="Notebook Capture")
        session = AgentSession(
            id="as_notebook_capture",
            project_id=project.id,
            goal_text="Write a readable marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        assert captured_notebooks == [notebook_artifact.id]
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_type == "notebook_auto_capture_succeeded",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            ).all()
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["notebook_artifact_id"] == notebook_artifact.id
        assert payload["notebook_execution_html_artifact_id"] == "art_auto_html"


def test_codex_authored_marimo_notebook_capture_can_defer_until_final_ingest(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "grandmaster_eda.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )
    captured_notebooks: list[str] = []

    def fake_capture(db: Any, *, store: LocalArtifactStore, notebook_artifact: Artifact) -> Any:
        del db, store
        captured_notebooks.append(notebook_artifact.id)
        return SimpleNamespace(
            html_artifact=SimpleNamespace(id="art_deferred_html"),
            manifest_artifact=SimpleNamespace(id="art_deferred_manifest"),
            evidence_html_artifact=None,
        )

    monkeypatch.setattr(analysis_notebooks_module, "create_notebook_execution_capture", fake_capture)

    with sessionmaker(engine)() as db:
        project = Project(id="p_deferred_notebook", name="Deferred Notebook Capture")
        session = AgentSession(
            id="as_deferred_notebook",
            project_id=project.id,
            goal_text="Write a readable marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            allow_notebook_auto_capture=False,
        )
        db.commit()

        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        assert captured_notebooks == []
        deferred_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "notebook_auto_capture_deferred",
            )
        )
        assert deferred_event is not None

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        assert captured_notebooks == [notebook_artifact.id]
        success_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "notebook_auto_capture_succeeded",
            )
        )
        assert success_event is not None


def test_failed_notebook_auto_capture_retries_after_cooldown(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    notebooks_dir = workspace / "notebooks"
    notebooks_dir.mkdir(parents=True)
    notebook = notebooks_dir / "grandmaster_eda.py"
    notebook.write_text(
        "import marimo\n\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n",
        encoding="utf-8",
    )
    attempts: list[str] = []

    def flaky_capture(db: Any, *, store: LocalArtifactStore, notebook_artifact: Artifact) -> Any:
        del db, store
        attempts.append(notebook_artifact.id)
        if len(attempts) == 1:
            raise RuntimeError("temporary marimo export failure")
        return SimpleNamespace(
            html_artifact=SimpleNamespace(id="art_retry_html"),
            manifest_artifact=SimpleNamespace(id="art_retry_manifest"),
            evidence_html_artifact=None,
        )

    monkeypatch.setattr(analysis_notebooks_module, "create_notebook_execution_capture", flaky_capture)

    with sessionmaker(engine)() as db:
        project = Project(id="p_retry_notebook", name="Retry Notebook Capture")
        session = AgentSession(
            id="as_retry_notebook",
            project_id=project.id,
            goal_text="Write a readable marimo notebook.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        notebook_artifact = db.scalar(
            select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
        )
        assert notebook_artifact is not None
        assert attempts == [notebook_artifact.id]
        failed_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "notebook_auto_capture_failed",
            )
        )
        assert failed_event is not None

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        assert attempts == [notebook_artifact.id]

        failed_event.created_at = utc_now() - timedelta(minutes=10)
        db.commit()
        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        assert attempts == [notebook_artifact.id, notebook_artifact.id]
        success_event = db.scalar(
            select(AgentTranscriptEvent).where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type == "notebook_auto_capture_succeeded",
            )
        )
        assert success_event is not None
        success_payload = loads_json(success_event.payload_json, {})
        assert success_payload["notebook_artifact_id"] == notebook_artifact.id
        assert success_payload["notebook_execution_html_artifact_id"] == "art_retry_html"


def test_research_plan_ingest_requests_locale_refresh_for_mixed_language_timeline(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "research_plan.json").write_text(
        dumps_json(
            {
                "schema_version": "research_plan.v1",
                "timeline_blocks": [
                    {
                        "id": "modeling_review",
                        "title": "Modeling review",
                        "why_it_matters": "Compare candidate models after EDA.",
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        user = User(id="u_plan_locale", email="plan-locale@example.com", locale="ja-JP")
        project = Project(
            id="p_plan_locale",
            name="Plan Locale",
            created_by=user.id,
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        session = AgentSession(
            id="as_plan_locale",
            project_id=project.id,
            goal_text="Keep the plan readable.",
            workspace_path=str(workspace),
            status="running",
        )
        db.add_all([user, project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        request_path = research_plan_locale_request_path(workspace)
        assert request_path.exists()
        request_text = request_path.read_text(encoding="utf-8")
        assert "locale: ja-JP" in request_text
        assert "outputs/research_plan.json" in request_text

        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_type == "research_plan_locale_refresh_requested",
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
            )
        )
        assert len(events) == 1
        payload = loads_json(events[0].payload_json, {})
        assert payload["locale"] == "ja-JP"
        assert payload["missing_block_count"] == 1

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()
        repeated_events = list(
            db.scalars(
                select(AgentTranscriptEvent).where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_type == "research_plan_locale_refresh_requested",
                )
            )
        )
        assert len(repeated_events) == 1


def test_published_raw_codex_transcript_is_ingested_as_session_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    append_runner_stream_to_workspace(
        workspace,
        stream_name="stdout",
        line='{"type":"turn.started","turn_id":"turn_1"}\n',
    )
    publish_raw_codex_transcript_snapshot(workspace)

    with sessionmaker(engine)() as db:
        project = Project(id="p_raw", name="Raw Project", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        session = AgentSession(
            id="as_raw",
            project_id=project.id,
            goal_text="Run a useful data science loop.",
            workspace_path=str(workspace),
        )
        db.add_all([project, session])
        db.commit()

        ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
        db.commit()

        artifact = db.scalar(select(Artifact).where(Artifact.project_id == project.id))
        assert artifact is not None
        assert artifact.asset_type == "agent_session_transcript"
        metadata = loads_json(artifact.metadata_json, {})
        assert metadata["transcript_kind"] == "codex_cli_stdout_jsonl"
        assert artifact_primary_path(artifact).read_text(encoding="utf-8").startswith('{"type":"turn.started"')
