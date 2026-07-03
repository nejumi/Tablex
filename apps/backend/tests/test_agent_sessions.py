from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, AgentTranscriptEvent, Artifact, Base, Project, utc_now
from tabular_harness.services.agent_sessions import (
    CODEX_RAW_TRANSCRIPT_FILENAME,
    CODEX_STDERR_LOG_FILENAME,
    append_codex_stream_lines,
    append_runner_stream_to_workspace,
    append_session_event,
    asset_type_for_session_output,
    build_turn_prompt,
    chat_update_message_from_text,
    ingest_session_workspace_outputs,
    mark_user_instructions_delivered,
    metadata_for_session_output,
    publish_raw_codex_transcript_snapshot,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    session_output_artifact_name,
    should_register_session_output,
)
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path


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


def test_session_output_artifact_name_uses_relative_path_to_avoid_stem_collisions() -> None:
    report_name = session_output_artifact_name("as_path", Path("reports/summary.md"))
    output_name = session_output_artifact_name("as_path", Path("outputs/summary.md"))

    assert report_name != output_name
    assert "reports_summary_md" in report_name
    assert "outputs_summary_md" in output_name


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
        assert "user-facing explanation, not an internal changelog" in prompt.text
        assert "Avoid raw artifact IDs" in prompt.text


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
