from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.agent.runners import safe_env
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    Asset,
    AssetReference,
    AssetVersion,
    DatasetSnapshot,
    Job,
    Project,
    User,
    utc_now,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    next_artifact_version,
    register_artifact,
)

MAIN_AUTONOMOUS_SESSION_TYPE = "main_autonomous"
ACTIVE_SESSION_STATUSES = {"starting", "running", "between_turns", "waiting_for_runner"}
TERMINAL_SESSION_STATUSES = {"stopped", "failed", "gave_up", "completed"}
RETRY_BACKOFF_SECONDS = (5, 30, 120, 600)
STALE_PROCESS_TERM_GRACE_SECONDS = 5
SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS = 30
MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60
SESSION_INTERNAL_DIR = ".tablex"
SESSION_INBOX_DIR = "inbox"
USER_INSTRUCTIONS_INBOX_FILENAME = "user_instructions.jsonl"
USER_INSTRUCTIONS_LATEST_FILENAME = "latest_user_instruction.md"
CODEX_RAW_TRANSCRIPT_FILENAME = "codex_raw_transcript.jsonl"
CODEX_STDERR_LOG_FILENAME = "codex_stderr.log"
_SUPERVISOR_LOCK = threading.Lock()
_ACTIVE_SUPERVISORS: set[str] = set()


@dataclass(frozen=True)
class TurnPrompt:
    text: str
    delivered_user_event_indexes: tuple[int, ...]


def active_main_session(db: Session, project_id: str) -> AgentSession | None:
    return db.scalar(
        select(AgentSession)
        .where(
            AgentSession.project_id == project_id,
            AgentSession.session_type == MAIN_AUTONOMOUS_SESSION_TYPE,
            AgentSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
    )


def latest_main_session(db: Session, project_id: str) -> AgentSession | None:
    return db.scalar(
        select(AgentSession)
        .where(
            AgentSession.project_id == project_id,
            AgentSession.session_type == MAIN_AUTONOMOUS_SESSION_TYPE,
        )
        .order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
    )


def start_or_resume_main_session(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    goal_text: str | None,
    autonomy_mode: str,
    runner_kind: str = "codex_cli",
    created_by: str | None = None,
) -> AgentSession:
    existing = active_main_session(db, project.id)
    if existing is not None:
        append_session_event(
            db,
            existing,
            source="tablex_sidecar",
            event_type="session_resume_requested",
            role="harness",
            title="Full Auto resume requested",
            content="Tablex observed an active main AgentSession and will continue supervising it instead of creating a fragmented runner job.",
            payload={"project_id": project.id, "autonomy_mode": autonomy_mode},
        )
        existing.status = "running"
        existing.updated_at = utc_now()
        return existing

    goal = goal_text or build_default_goal_text(db, project)
    session = AgentSession(
        id=new_id("ags"),
        project_id=project.id,
        org_id=project.org_id,
        session_type=MAIN_AUTONOMOUS_SESSION_TYPE,
        status="starting",
        autonomy_mode=autonomy_mode,
        runner_kind=runner_kind,
        goal_text=goal,
        workspace_path=str(session_workspace_path(store, project.id, new_id("session_workspace"))),
        created_by=created_by or "local-user",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.workspace_path = str(session_workspace_path(store, project.id, session.id))
    db.add(session)
    db.flush()
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="session_created",
        role="harness",
        title="Full Auto started",
        content="The analysis has started and will continue from the current project state.",
        payload={"project_id": project.id, "runner_kind": runner_kind, "autonomy_mode": autonomy_mode},
    )
    return session


def session_workspace_path(store: LocalArtifactStore, project_id: str, session_id: str) -> Path:
    return store.root / "agent_sessions" / project_id / session_id


def raw_codex_transcript_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / CODEX_RAW_TRANSCRIPT_FILENAME


def raw_codex_stderr_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / CODEX_STDERR_LOG_FILENAME


def user_instructions_inbox_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / USER_INSTRUCTIONS_INBOX_FILENAME


def latest_user_instruction_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / USER_INSTRUCTIONS_LATEST_FILENAME


def build_default_goal_text(db: Session, project: Project) -> str:
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc()).limit(8)
        ).all()
    )
    target_text = project.target_column or "not fixed; infer or construct the prediction objective from evidence"
    dataset_lines = [
        f"- {dataset.id}: rows={dataset.row_count}, columns={dataset.column_count}, source={dataset.source_ref or dataset.artifact_id}"
        for dataset in datasets
    ]
    return "\n".join(
        [
            f"Run the main Tablex autonomous data-science session for project `{project.name}` ({project.id}).",
            "",
            "You are Codex acting as the execution engine inside Tablex. Tablex must not constrain you to fixed recipes.",
            "Use the provided assets, Skills, and data-science workflow as context and guardrails, then decide the project-specific approach yourself.",
            "",
            "Primary objective:",
            f"- Current target/objective hint: {target_text}",
            "- Understand the data deeply, including relational structure when present.",
            "- Define or refine the prediction/analysis objective. It may be supervised, derived, aggregate, time-dependent, distributional, unsupervised, or optimization-coupled if the evidence supports it.",
            "- Design reliable evaluation before trusting modeling results.",
            "- Build strong evidence-backed baselines and improve them without forcing a predefined recipe.",
            "- Produce useful marimo notebooks and reports for humans, not placeholder summaries.",
            "- Save every important output under `outputs/`, `reports/`, `notebooks/`, or `artifacts/` so Tablex can register it.",
            "- Keep moving in Full Auto. Ask questions when useful, but if no answer is available, record assumptions and continue. Use Give Up only as a last resort.",
            "",
            "Current datasets:",
            *(dataset_lines or ["- No dataset snapshot is registered yet; wait for data or explain the missing input."]),
        ]
    )


def append_session_event(
    db: Session,
    session: AgentSession,
    *,
    source: str,
    event_type: str,
    role: str | None = None,
    title: str | None = None,
    content: str | None = None,
    payload: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    job_id: str | None = None,
) -> AgentTranscriptEvent:
    db.flush()
    current_max = db.scalar(
        select(func.max(AgentTranscriptEvent.event_index)).where(AgentTranscriptEvent.session_id == session.id)
    )
    event = AgentTranscriptEvent(
        id=new_id("agte"),
        project_id=session.project_id,
        session_id=session.id,
        event_index=int(current_max if current_max is not None else -1) + 1,
        source=source,
        event_type=event_type,
        role=role,
        title=title,
        content=content,
        payload_json=dumps_json(payload or {}),
        artifact_id=artifact_id,
        job_id=job_id,
        created_at=utc_now(),
    )
    db.add(event)
    session.updated_at = utc_now()
    session.last_heartbeat_at = utc_now()
    return event


def session_to_dict(session: AgentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "project_id": session.project_id,
        "session_type": session.session_type,
        "status": session.status,
        "autonomy_mode": session.autonomy_mode,
        "runner_kind": session.runner_kind,
        "goal_text": session.goal_text,
        "workspace_path": session.workspace_path,
        "codex_thread_id": session.codex_thread_id,
        "pid": session.pid,
        "turn_index": session.turn_index,
        "last_heartbeat_at": session.last_heartbeat_at.isoformat() if session.last_heartbeat_at else None,
        "last_error": session.last_error,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
    }


def transcript_event_to_dict(event: AgentTranscriptEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "session_id": event.session_id,
        "event_index": event.event_index,
        "source": event.source,
        "event_type": event.event_type,
        "role": event.role,
        "title": event.title,
        "content": event.content,
        "payload": loads_json(event.payload_json, {}),
        "artifact_id": event.artifact_id,
        "job_id": event.job_id,
        "created_at": event.created_at.isoformat(),
    }


def append_runner_stream_to_workspace(workspace: Path, *, stream_name: str, line: str) -> None:
    target = raw_codex_transcript_path(workspace) if stream_name == "stdout" else raw_codex_stderr_path(workspace)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line if line.endswith("\n") else f"{line}\n")
    except OSError:
        return


def append_user_instruction_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    message: str,
    locale: str | None,
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    inbox_path = user_instructions_inbox_path(workspace)
    latest_path = latest_user_instruction_path(workspace)
    payload = {
        "schema_version": "tablex_user_instruction.v1",
        "session_id": session.id,
        "project_id": session.project_id,
        "event_id": event.id,
        "event_index": event.event_index,
        "created_at": event.created_at.isoformat(),
        "locale": locale,
        "message": message,
    }
    try:
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        latest_path.write_text(
            "\n".join(
                [
                    f"event_index: {event.event_index}",
                    f"created_at: {event.created_at.isoformat()}",
                    f"locale: {locale or 'unspecified'}",
                    "",
                    message.strip(),
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def publish_raw_codex_transcript_snapshot(workspace: Path) -> list[Path]:
    artifacts_dir = workspace / "artifacts"
    published: list[Path] = []
    for source, filename in (
        (raw_codex_transcript_path(workspace), CODEX_RAW_TRANSCRIPT_FILENAME),
        (raw_codex_stderr_path(workspace), CODEX_STDERR_LOG_FILENAME),
    ):
        if not source.exists():
            continue
        try:
            payload = source.read_bytes()
        except OSError:
            continue
        if not payload:
            continue
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            target = artifacts_dir / filename
            if not target.exists() or target.read_bytes() != payload:
                target.write_bytes(payload)
            published.append(target)
        except OSError:
            continue
    return published


SupervisorRunner = Callable[..., None]


def start_main_agent_session_supervisor_thread(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    session_id: str,
    agent_model: str | None = None,
    supervisor_runner: SupervisorRunner | None = None,
) -> threading.Thread | None:
    if not acquire_supervisor_slot(session_id):
        return None
    runner = supervisor_runner or run_main_agent_session_supervisor
    if supervisor_runner is not None and supervisor_runner is not run_main_agent_session_supervisor:
        try:
            runner(
                session_factory,
                store,
                project_id=project_id,
                session_id=session_id,
                agent_model=agent_model,
                slot_acquired=True,
            )
        finally:
            release_supervisor_slot(session_id)
        return None

    def target() -> None:
        try:
            runner(
                session_factory,
                store,
                project_id=project_id,
                session_id=session_id,
                agent_model=agent_model,
                slot_acquired=True,
            )
        finally:
            if runner is not run_main_agent_session_supervisor:
                release_supervisor_slot(session_id)

    thread = threading.Thread(
        target=target,
        name=f"tablex-agent-session-{session_id}",
        daemon=True,
    )
    thread.start()
    return thread


def start_active_main_session_supervisors(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    agent_model: str | None = None,
) -> list[threading.Thread]:
    launch_specs: list[tuple[str, str]] = []
    with session_factory() as db:
        projects = list(
            db.scalars(
                select(Project).where(
                    Project.current_phase == "AUTONOMOUS_LOOP",
                    Project.autonomy_mode == "full_auto",
                )
            ).all()
        )
        for project in projects:
            session = active_main_session(db, project.id)
            if session is None:
                session = start_or_resume_main_session(
                    db,
                    store=store,
                    project=project,
                    goal_text=None,
                    autonomy_mode="full_auto",
                    runner_kind="codex_cli",
                    created_by="tablex-startup-supervisor",
                )
            elif session.pid is not None:
                session.status = "between_turns"
                session.last_error = "Server restarted while Codex was active; Tablex will resume the same session."
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="startup_stale_runner_detected",
                    role="harness",
                    title="Startup will recover Full Auto",
                    content="Tablex restarted and will recover the active autonomous session.",
                    payload={"previous_pid": session.pid},
                )
            launch_specs.append((project.id, session.id))
        db.commit()
    threads: list[threading.Thread] = []
    for project_id, session_id in launch_specs:
        thread = start_main_agent_session_supervisor_thread(
            session_factory,
            store,
            project_id=project_id,
            session_id=session_id,
            agent_model=agent_model,
        )
        if thread is not None:
            threads.append(thread)
    return threads


def run_main_agent_session_supervisor(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    session_id: str,
    agent_model: str | None = None,
    max_turns: int = 100_000,
    turn_timeout_seconds: int = MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    slot_acquired: bool = False,
) -> None:
    if not slot_acquired and not acquire_supervisor_slot(session_id):
        return
    try:
        for _ in range(max_turns):
            with session_factory() as db:
                project = db.get(Project, project_id)
                session = db.get(AgentSession, session_id)
                if project is None or session is None:
                    return
                if session.pid and pid_is_alive(session.pid):
                    previous_pid = session.pid
                    workspace_hint = Path(session.workspace_path) if session.workspace_path else None
                    terminated = False
                    if pid_matches_agent_codex_process(previous_pid, workspace_hint, session.id):
                        terminate_stale_codex_process(previous_pid)
                        terminated = True
                    session.pid = None
                    session.status = "between_turns"
                    session.last_error = "Recovered an unobserved Codex process from an earlier supervisor."
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="stale_runner_process_recovered",
                        role="harness",
                        title="Recovered unobserved Codex process",
                        content="A stored Codex PID could not be monitored by this supervisor; Tablex cleared it and will resume the same session.",
                        payload={"previous_pid": previous_pid, "terminated_process": terminated},
                    )
                    db.commit()
                    time.sleep(1)
                    continue
                if project.current_phase != "AUTONOMOUS_LOOP" or session.status in TERMINAL_SESSION_STATUSES:
                    session.status = "stopped"
                    session.pid = None
                    session.ended_at = utc_now()
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="session_stopped",
                        role="harness",
                        title="Full Auto stopped",
                        content="Full Auto is off. The analysis will not continue until the project is started again.",
                        payload={"project_phase": project.current_phase if project else None},
                    )
                    db.commit()
                    return
                workspace = prepare_session_workspace(db, store=store, project=project, session=session)
                turn_prompt = build_turn_prompt(db, project=project, session=session)
                session.status = "running"
                session.started_at = session.started_at or utc_now()
                session.updated_at = utc_now()
                session.last_heartbeat_at = utc_now()
                session.last_error = None
                db.commit()

            exit_code = run_codex_cli_turn_streaming(
                session_factory,
                store=store,
                project_id=project_id,
                session_id=session_id,
                workspace=workspace,
                prompt=turn_prompt.text,
                delivered_user_event_indexes=turn_prompt.delivered_user_event_indexes,
                agent_model=agent_model,
                timeout_seconds=turn_timeout_seconds,
            )
            with session_factory() as db:
                project = db.get(Project, project_id)
                session = db.get(AgentSession, session_id)
                if project is None or session is None:
                    return
                ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=Path(session.workspace_path or workspace))
                if project.current_phase != "AUTONOMOUS_LOOP":
                    session.status = "stopped"
                    session.pid = None
                    session.ended_at = utc_now()
                    db.commit()
                    return
                if exit_code is None:
                    session.status = "waiting_for_runner"
                    session.pid = None
                    session.last_error = "Codex CLI is not available."
                    retry_delay = retry_delay_seconds(consecutive_runner_failure_count(db, session.id))
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="runner_retry_scheduled",
                        role="harness",
                        title="Codex runner retry scheduled",
                        content="Codex CLI is unavailable. Tablex will keep the same session and retry after a cooldown.",
                        payload={"retry_delay_seconds": retry_delay, "failure_kind": "runner_unavailable"},
                    )
                    db.commit()
                    time.sleep(retry_delay)
                    continue
                if exit_code != 0:
                    session.status = "between_turns"
                    session.pid = None
                    retry_delay = retry_delay_seconds(consecutive_runner_failure_count(db, session.id))
                    session.last_error = (
                        f"Codex turn exited with code {exit_code}; supervisor will retry in {retry_delay}s."
                    )
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="turn_recovery_scheduled",
                        role="harness",
                        title="Codex turn returned non-zero; continuing session",
                        content="Full Auto remains on. Tablex will resume the same session after a cooldown instead of leaving the project stopped.",
                        payload={"exit_code": exit_code, "retry_delay_seconds": retry_delay},
                    )
                    db.commit()
                    time.sleep(retry_delay)
                    continue
                session.status = "between_turns"
                session.pid = None
                session.turn_index += 1
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="turn_completed_supervisor_continue",
                    role="harness",
                    title="Codex turn completed; supervisor will continue",
                    content="Full Auto is still on. Tablex keeps the same AgentSession alive and asks Codex to continue from the transcript and project state.",
                    payload={"turn_index": session.turn_index},
                )
                db.commit()
            time.sleep(2)
    finally:
        release_supervisor_slot(session_id)


def acquire_supervisor_slot(session_id: str) -> bool:
    with _SUPERVISOR_LOCK:
        if session_id in _ACTIVE_SUPERVISORS:
            return False
        _ACTIVE_SUPERVISORS.add(session_id)
        return True


def release_supervisor_slot(session_id: str) -> None:
    with _SUPERVISOR_LOCK:
        _ACTIVE_SUPERVISORS.discard(session_id)


def supervisor_slot_active(session_id: str) -> bool:
    with _SUPERVISOR_LOCK:
        return session_id in _ACTIVE_SUPERVISORS


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_stale_codex_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + STALE_PROCESS_TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def pid_matches_agent_codex_process(pid: int, workspace: Path | None, session_id: str) -> bool:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
    except OSError:
        return False
    if "codex" not in cmdline or "exec" not in cmdline:
        return False
    if session_id in cmdline:
        return True
    if workspace is not None and str(workspace) in cmdline:
        return True
    return False


def retry_delay_seconds(consecutive_failures: int) -> int:
    if consecutive_failures <= 0:
        return RETRY_BACKOFF_SECONDS[0]
    index = min(consecutive_failures - 1, len(RETRY_BACKOFF_SECONDS) - 1)
    return RETRY_BACKOFF_SECONDS[index]


def consecutive_runner_failure_count(db: Session, session_id: str) -> int:
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(AgentTranscriptEvent.session_id == session_id)
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(80)
        ).all()
    )
    count = 0
    failure_events = {
        "runner_unavailable",
        "runner_retry_scheduled",
        "turn_recovery_scheduled",
        "process_timeout",
        "process_killed_after_timeout",
    }
    for event in events:
        if event.event_type in {"turn_completed_supervisor_continue"}:
            break
        if event.event_type == "process_exited":
            payload = loads_json(event.payload_json, {})
            if payload.get("exit_code") == 0:
                break
        if event.event_type in failure_events:
            count += 1
    return max(1, count)


def prepare_session_workspace(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> Path:
    workspace = Path(session.workspace_path or session_workspace_path(store, project.id, session.id))
    session.workspace_path = str(workspace)
    (workspace / ".tablex").mkdir(parents=True, exist_ok=True)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    (workspace / "notebooks").mkdir(parents=True, exist_ok=True)
    (workspace / "artifacts").mkdir(parents=True, exist_ok=True)
    (workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR).mkdir(parents=True, exist_ok=True)
    context = build_session_context(db, project=project, session=session)
    (workspace / ".tablex" / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    (workspace / ".tablex" / "GOAL.md").write_text(session.goal_text, encoding="utf-8")
    return workspace


def build_session_context(db: Session, *, project: Project, session: AgentSession) -> dict[str, Any]:
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc()).limit(12)
        ).all()
    )
    artifacts = list(
        db.scalars(
            select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.created_at.desc()).limit(80)
        ).all()
    )
    skill_references = list(
        db.scalars(
            select(AssetReference)
            .where(AssetReference.source_type == "project", AssetReference.source_id == project.id)
            .order_by(AssetReference.created_at.desc())
            .limit(30)
        ).all()
    )
    response_locale = latest_project_response_locale(db, project)
    equipped_skills = equipped_skill_context(db, skill_references)
    return {
        "schema_version": "tablex_agent_session_context.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
            "autonomy_mode": project.autonomy_mode,
        },
        "human_interface": {
            "response_locale": response_locale,
            "notebook_language": response_locale,
            "instruction": (
                "Write human-facing chat responses, marimo notebook narratives, research summaries, and reports "
                "in this locale unless the user explicitly asks otherwise."
            ),
        },
        "session": {"id": session.id, "turn_index": session.turn_index, "codex_thread_id": session.codex_thread_id},
        "datasets": [
            {
                "id": item.id,
                "artifact_id": item.artifact_id,
                "source_ref": item.source_ref,
                "row_count": item.row_count,
                "column_count": item.column_count,
            }
            for item in datasets
        ],
        "recent_artifacts": [
            {
                "id": item.id,
                "asset_type": item.asset_type,
                "name": item.name,
                "uri": item.uri,
                "path": str(artifact_primary_path(item)),
                "metadata": loads_json(item.metadata_json, {}),
            }
            for item in artifacts
        ],
        "equipped_skill_references": equipped_skills,
        "output_contract": {
            "registerable_dirs": ["outputs", "reports", "notebooks", "artifacts"],
            "marimo_notebooks": "Place .py marimo notebooks under notebooks/ or outputs/notebooks/.",
            "living_research_plan": (
                "When the project plan changes, write outputs/research_plan.json with optional timeline_blocks. "
                "Tablex renders those blocks directly; after the initial anchors, Codex may add, remove, reorder, or branch them."
            ),
            "progress": "Explain progress naturally in Codex messages. Tablex stores the raw transcript and Chat explains it to humans.",
            "chat_update": (
                "reports/chat_update.md is the human-facing Chat update, not an internal changelog. "
                "Explain the current work, why it matters, what changed, open uncertainty, and the next useful place to look. "
                "Avoid raw artifact IDs, hashes, internal schema names, and implementation vocabulary unless they are needed for a user decision."
            ),
            "notebook_quality": (
                "Data understanding and research notebooks are human deliverables, not only model context. "
                "Use equipped Skills such as tablex-grandmaster-eda and tablex-notebook-quality when present."
            ),
        },
    }


def latest_project_response_locale(db: Session, project: Project) -> str:
    job = db.scalar(
        select(Job)
        .where(Job.project_id == project.id, Job.job_type == "start_autonomous_loop")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is not None:
        payload = loads_json(job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    user = db.get(User, project.created_by)
    if user is not None and user.locale:
        return user.locale
    return "en-US"


def equipped_skill_context(db: Session, references: list[AssetReference]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for reference in references:
        asset = db.get(Asset, reference.target_asset_id)
        if asset is None or asset.asset_type != "skill":
            continue
        version = db.get(AssetVersion, reference.target_asset_version_id or asset.latest_version_id or "")
        artifact = db.get(Artifact, version.artifact_id) if version is not None else None
        content = read_skill_asset_content(artifact) if artifact is not None else {}
        items.append(
            {
                "reference_id": reference.id,
                "asset_id": asset.id,
                "asset_version_id": version.id if version is not None else None,
                "name": asset.name,
                "description": asset.description,
                "relation_type": reference.relation_type,
                "artifact_id": artifact.id if artifact is not None else None,
                "artifact_path": str(artifact_primary_path(artifact)) if artifact is not None else None,
                "skill_path": content.get("skill_path") if isinstance(content.get("skill_path"), str) else None,
                "reference_paths": content.get("reference_paths") if isinstance(content.get("reference_paths"), list) else [],
                "runner_guidance": content.get("runner_guidance") if isinstance(content.get("runner_guidance"), list) else [],
                "content": content,
            }
        )
    return items


def read_skill_asset_content(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    path = artifact_primary_path(artifact)
    try:
        if path.suffix.lower() == ".json":
            payload = loads_json(path.read_text(encoding="utf-8"), {})
            return payload if isinstance(payload, dict) else {}
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {"text": text[:12000]}


def build_turn_prompt(db: Session, *, project: Project, session: AgentSession) -> TurnPrompt:
    user_instruction_events = undelivered_user_instruction_events(db, session.id)
    user_instructions = [event.content for event in user_instruction_events if event.content]
    if session.turn_index == 0 or not session.codex_thread_id:
        intro = [
            "Treat this as the main Tablex /goal for a long-running autonomous data-science session.",
            "You are not a small job runner. Continue until the project has genuinely useful data understanding, evaluation, modeling, insights, and marimo reports, or until Tablex explicitly stops you.",
        ]
    else:
        intro = [
            "Resume the same Tablex autonomous data-science session.",
            "Do not restart from scratch. Read .tablex/context.json, .tablex/GOAL.md, recent outputs, and continue the project-specific plan.",
        ]
    lines = [
        *intro,
        "",
        "Hard constraints:",
        "- Do not read secrets or connector credentials.",
        "- Do not use validation/test targets in feature generation prompts.",
        "- Do not destructively modify EvaluationSpec or SplitManifest.",
        "- Register important outputs by writing files under outputs/, reports/, notebooks/, or artifacts/.",
        "- Keep a living plan when it helps the user follow the work: write `outputs/research_plan.json` with `schema_version: \"research_plan.v1\"` and optional `timeline_blocks`. Use `timeline_blocks` only as a display contract: after data upload, objective/task framing, data understanding, and prior-knowledge research anchors, freely add, remove, reorder, branch, or revise project-specific blocks. Mark a block done only when the supporting artifact exists or you explicitly record that no useful output is needed.",
        "- Keep human-facing accountability continuous: when you make meaningful progress, hit uncertainty, start or finish a long-running step, recover from an error, change the plan, or need the user to know what changed, overwrite `reports/chat_update.md` with only the latest concise update in the user's locale. Keep it under 1200 characters. Use separate report files for long history. Do not wait for Tablex to infer this from logs.",
        "- Treat `reports/chat_update.md` as a user-facing explanation, not an internal changelog: say what you are doing now, why it matters, what changed, what uncertainty remains, and where the user should look next. Avoid raw artifact IDs, hashes, filenames, internal schema names, and implementation vocabulary unless they are necessary for a user decision.",
        "- Prefer marimo notebooks for data understanding, modeling diagnostics, and reports.",
        "- Read `.tablex/context.json` for `human_interface.response_locale` and write human-facing notebooks/reports/chat in that language.",
        "- Read equipped Skill paths in `.tablex/context.json` before EDA, prior research, notebook authoring, or modeling strategy work.",
        "- During long turns, check `.tablex/inbox/user_instructions.jsonl` and `.tablex/inbox/latest_user_instruction.md` for new user messages; incorporate them without waiting for a new Codex turn when practical.",
        "- If you need user input in Full Auto, state the question and your provisional assumption, then continue unless impossible.",
        "- Use Give Up only as a last resort; if you give up, explain exactly what is missing and preserve partial work.",
        "",
        "Goal:",
        session.goal_text,
        "",
        "Project context is available at `.tablex/context.json`.",
    ]
    if user_instructions:
        lines.extend(["", "User instructions not yet delivered to Codex:"])
        lines.extend([f"- {item}" for item in user_instructions])
    return TurnPrompt(
        text="\n".join(lines).strip() + "\n",
        delivered_user_event_indexes=tuple(event.event_index for event in user_instruction_events),
    )


def latest_delivered_user_event_index(db: Session, session_id: str) -> int:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.event_type == "user_instructions_delivered_to_codex",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    if event is None:
        return -1
    payload = loads_json(event.payload_json, {})
    value = payload.get("last_user_event_index")
    return int(value) if isinstance(value, int) else -1


def undelivered_user_instruction_events(db: Session, session_id: str) -> list[AgentTranscriptEvent]:
    delivered_index = latest_delivered_user_event_index(db, session_id)
    return list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "user",
                AgentTranscriptEvent.event_type == "user_instruction",
                AgentTranscriptEvent.event_index > delivered_index,
            )
            .order_by(AgentTranscriptEvent.event_index.asc())
        ).all()
    )


def mark_user_instructions_delivered(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    delivered_user_event_indexes: tuple[int, ...],
) -> None:
    if not delivered_user_event_indexes:
        return
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="user_instructions_delivered_to_codex",
            role="harness",
            title="User instructions delivered to Codex",
            content=f"Delivered {len(delivered_user_event_indexes)} pending user instruction(s) to the main Codex session.",
            payload={
                "delivered_user_event_indexes": list(delivered_user_event_indexes),
                "last_user_event_index": max(delivered_user_event_indexes),
            },
        )
        db.commit()


def run_codex_cli_turn_streaming(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
    workspace: Path,
    prompt: str,
    delivered_user_event_indexes: tuple[int, ...],
    agent_model: str | None,
    timeout_seconds: int,
) -> int | None:
    if shutil.which("codex") is None:
        with session_factory() as db:
            session = db.get(AgentSession, session_id)
            if session is not None:
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="runner_unavailable",
                    role="harness",
                    title="Codex CLI is not available",
                    content="Tablex cannot start the main Codex session because the codex binary is not on PATH.",
                    payload={},
                )
                db.commit()
        return None

    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return 1
        turn_index = session.turn_index
        last_message_path = workspace / ".tablex" / f"codex_last_message_turn_{turn_index}.md"
        if session.codex_thread_id:
            cmd = [
                "codex",
                "exec",
                "--cd",
                str(workspace),
                "--sandbox",
                "workspace-write",
                "resume",
                session.codex_thread_id,
                "--json",
                "--output-last-message",
                str(last_message_path),
                "--skip-git-repo-check",
                "-",
            ]
        else:
            cmd = [
                "codex",
                "exec",
                "--cd",
                str(workspace),
                "--sandbox",
                "workspace-write",
                "--json",
                "--output-last-message",
                str(last_message_path),
                "--skip-git-repo-check",
                "-",
            ]
        if agent_model and agent_model not in {"codex-default", "default"}:
            insert_at = 7 if session.codex_thread_id else 2
            cmd[insert_at:insert_at] = ["--model", agent_model]
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="codex_command",
            role="harness",
            title="Launching Codex CLI",
            content="Starting or resuming the main Codex session. Raw will store Codex JSONL events directly.",
            payload={"command": " ".join(cmd[:-1] + ["-"]), "workspace": str(workspace)},
        )
        db.commit()

    process = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=safe_env(workspace),
    )
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            session.pid = process.pid
            session.status = "running"
            session.last_heartbeat_at = utc_now()
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="process_started",
                role="harness",
                title="Codex process started",
                content=f"Codex CLI process pid={process.pid} is running for the main AgentSession.",
                payload={"pid": process.pid},
            )
            db.commit()
    if process.stdin is not None:
        process.stdin.write(prompt)
        process.stdin.close()
    mark_user_instructions_delivered(
        session_factory,
        session_id=session_id,
        delivered_user_event_indexes=delivered_user_event_indexes,
    )

    line_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    start = time.monotonic()
    last_output_at = start
    last_workspace_ingest = 0.0
    timeout_sent = False
    terminated_at: float | None = None

    def read_stream(name: str, stream: Any) -> None:
        try:
            for line in stream:
                line_queue.put((name, line))
        finally:
            line_queue.put((name, None))

    stdout_thread = threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True)
    stderr_thread = threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    finished_streams: set[str] = set()
    while True:
        now = time.monotonic()
        if now - last_workspace_ingest >= 10:
            ingest_session_workspace_outputs_safely(
                session_factory,
                store=store,
                project_id=project_id,
                session_id=session_id,
                workspace=workspace,
            )
            last_workspace_ingest = now
        if now - last_output_at > timeout_seconds and process.poll() is None and not timeout_sent:
            process.terminate()
            append_process_timeout_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
            timeout_sent = True
            terminated_at = now
        if terminated_at is not None and now - terminated_at > 15 and process.poll() is None:
            process.kill()
            append_process_killed_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
            terminated_at = None
        try:
            stream_name, line = line_queue.get(timeout=0.5)
        except queue.Empty:
            if process.poll() is not None and len(finished_streams) >= 2:
                break
            continue
        if line is None:
            finished_streams.add(stream_name)
            if process.poll() is not None and len(finished_streams) >= 2:
                break
            continue
        last_output_at = time.monotonic()
        append_runner_stream_to_workspace(workspace, stream_name=stream_name, line=line)
        append_codex_stream_line(session_factory, project_id=project_id, session_id=session_id, stream_name=stream_name, line=line)
        now = time.monotonic()
        if now - last_workspace_ingest >= 10:
            ingest_session_workspace_outputs_safely(
                session_factory,
                store=store,
                project_id=project_id,
                session_id=session_id,
                workspace=workspace,
            )
            last_workspace_ingest = now
    try:
        return_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        append_process_killed_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
        return_code = process.wait(timeout=5)
    publish_raw_codex_transcript_snapshot(workspace)
    ingest_session_workspace_outputs_safely(
        session_factory,
        store=store,
        project_id=project_id,
        session_id=session_id,
        workspace=workspace,
    )
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            session.pid = None
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="process_exited",
                role="runner",
                title="Codex process exited",
                content=f"Codex CLI exited with code {return_code}.",
                payload={"exit_code": return_code},
            )
            db.commit()
    return return_code


def ingest_session_workspace_outputs_safely(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
    workspace: Path,
) -> None:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
            ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=workspace)
            db.commit()
    except Exception:
        return


def append_process_timeout_event(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    timeout_seconds: int,
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_timeout",
            role="harness",
            title="Codex turn timed out",
            content="The current Codex CLI process produced no output for the idle timeout. The supervisor will continue if Full Auto remains on.",
            payload={"idle_timeout_seconds": timeout_seconds},
        )
        db.commit()


def append_process_killed_event(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    timeout_seconds: int,
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_killed_after_timeout",
            role="harness",
            title="Codex process killed after idle timeout",
            content="The Codex process did not exit after the idle timeout termination request, so Tablex killed it and will continue the same session if Full Auto remains on.",
            payload={"idle_timeout_seconds": timeout_seconds},
        )
        db.commit()


def append_codex_stream_line(
    session_factory: sessionmaker[Session],
    *,
    project_id: str,
    session_id: str,
    stream_name: str,
    line: str,
) -> None:
    stripped = line.strip()
    payload: dict[str, Any] = {"stream": stream_name, "line": stripped}
    event_type = f"codex_{stream_name}"
    title = "Codex stdout"
    content = stripped
    if stream_name == "stdout" and stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
            event_type = str(parsed.get("type") or "codex_event")
            title = codex_event_title(parsed)
            content = codex_event_content(parsed)
    elif stream_name == "stderr":
        title = "Codex stderr"
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        if event_type == "thread.started" and isinstance(payload.get("thread_id"), str):
            session.codex_thread_id = str(payload["thread_id"])
        append_session_event(
            db,
            session,
            source="codex_cli" if stream_name == "stdout" else "codex_cli_stderr",
            event_type=event_type,
            role="runner",
            title=title,
            content=content,
            payload=payload,
        )
        db.commit()


def codex_event_title(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "Codex event")
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    item_type = str(item.get("type") or "") if isinstance(item, dict) else ""
    if event_type == "thread.started":
        return "Thread started"
    if event_type == "turn.started":
        return "Turn started"
    if event_type == "turn.completed":
        return "Turn completed"
    if event_type == "item.completed" and item_type == "agent_message":
        return "Codex message"
    if event_type == "item.completed" and "tool" in item_type:
        return "Tool use"
    if event_type == "item.completed" and ("exec" in item_type or "command" in item_type):
        return "Command execution"
    return event_type.replace("_", " ").replace(".", " ").title()


def codex_event_content(event: dict[str, Any]) -> str | None:
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    if isinstance(item, dict):
        for key in ("text", "output", "summary", "command"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
    usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
    if usage:
        return (
            f"usage: input={usage.get('input_tokens', '-')}, output={usage.get('output_tokens', '-')}, "
            f"reasoning={usage.get('reasoning_output_tokens', '-')}"
        )
    return None


def ingest_session_workspace_outputs(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    output_roots = [workspace / "outputs", workspace / "reports", workspace / "notebooks", workspace / "artifacts"]
    for root in output_roots:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if should_skip_session_output(path):
                continue
            metadata = {
                "project_id": project.id,
                "agent_session_id": session.id,
                "workspace_relative_path": str(path.relative_to(workspace)),
                "source": "main_agent_session_workspace",
                **metadata_for_session_output(path),
            }
            name = session_output_artifact_name(session.id, path.relative_to(workspace))
            asset_type = asset_type_for_session_output(path)
            existing = db.scalar(
                select(Artifact).where(
                    Artifact.project_id == project.id,
                    Artifact.asset_type == asset_type,
                    Artifact.name == name,
                ).order_by(Artifact.version.desc())
            )
            if existing is not None and not should_register_session_output(path, existing):
                continue
            version = next_artifact_version(db, project.id, asset_type, name)
            target_dir, stored, content_hash = store.store_existing_file(
                org_id=project.org_id,
                project_id=project.id,
                asset_type=asset_type,
                name=name,
                version=version,
                source_path=path,
                filename=path.name,
                metadata={**metadata, "primary_path": str(path)},
            )
            artifact = register_artifact(
                db,
                project_id=project.id,
                asset_type=asset_type,
                name=name,
                uri=str(target_dir),
                content_hash=content_hash,
                size_bytes=stored.size_bytes,
                metadata={**metadata, "primary_path": str(target_dir / path.name)},
                version=version,
                org_id=project.org_id,
            )
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="artifact_registered",
                role="harness",
                title="Workspace output registered",
                content=f"Registered `{path.relative_to(workspace)}` as `{asset_type}`.",
                payload=metadata,
                artifact_id=artifact.id,
            )
            maybe_register_chat_update_from_workspace_output(
                db,
                store=store,
                project=project,
                session=session,
                path=path,
                artifact=artifact,
            )


def asset_type_for_session_output(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name == CODEX_RAW_TRANSCRIPT_FILENAME or (suffix == ".jsonl" and "transcript" in path.stem.lower()):
        return "agent_session_transcript"
    if path.name == CODEX_STDERR_LOG_FILENAME:
        return "agent_session_log"
    if suffix == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        return "analysis_notebook"
    if suffix in {".md", ".html"}:
        return "agent_session_report"
    if suffix == ".json" and path.stem.lower() in {"research_plan", "research_plan_timeline"}:
        return "research_plan"
    if suffix == ".json":
        return "agent_session_artifact"
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
        return "agent_session_figure"
    return "agent_session_output"


def session_output_artifact_name(session_id: str, relative_path: Path) -> str:
    relative_text = relative_path.as_posix()
    digest = hashlib.sha1(relative_text.encode("utf-8")).hexdigest()[:10]
    readable = re.sub(r"[^A-Za-z0-9]+", "_", relative_text).strip("_") or "output"
    return f"agent_session_{session_id}_{readable[:145]}_{digest}"


def should_skip_session_output(path: Path) -> bool:
    return (
        path.name.startswith(".")
        or path.name == "artifact_manifest.json"
        or path.suffix == ".pyc"
        or "__pycache__" in path.parts
    )


def should_register_session_output(path: Path, existing: Artifact | None) -> bool:
    if existing is None:
        return True
    try:
        existing_path = artifact_primary_path(existing)
        changed = hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(existing_path.read_bytes()).hexdigest()
    except OSError:
        return True
    if not changed:
        return False
    if is_chat_update_path(path):
        return True
    created_at = existing.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (utc_now() - created_at).total_seconds() >= SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS


def is_chat_update_path(path: Path) -> bool:
    return path.name == "chat_update.md" and path.parent.name == "reports"


def maybe_register_chat_update_from_workspace_output(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    path: Path,
    artifact: Artifact,
) -> None:
    if not is_chat_update_path(path):
        return
    try:
        message = chat_update_message_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return
    if not message:
        return
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": message[:4000],
        "intent": {
            "type": "autonomous_agent_progress_report",
            "source": "main_codex_session",
            "routing_policy": "codex_authored_human_update",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_progress_report_brief.v1",
            "agent_session_id": session.id,
            "source_artifact_id": artifact.id,
            "workspace_relative_path": str(path.relative_to(Path(session.workspace_path or path.parent))),
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session",
            "status": "codex_authored",
        },
        "worker_events": [],
        "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"},
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_chat_update_{session.id}_{artifact.id}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source_artifact_id": artifact.id,
            "source": "main_codex_session_chat_update",
        },
    )
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="chat_update_registered",
        role="harness",
        title="Codex progress report registered",
        content="Registered Codex-authored human progress report for Agent Chat.",
        payload={"chat_artifact_id": chat_artifact.id, "source_artifact_id": artifact.id},
        artifact_id=chat_artifact.id,
    )


def chat_update_message_from_text(text: str, limit: int = 900) -> str:
    stripped = text.strip()
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", stripped) if item.strip()]
    message = paragraphs[-1] if paragraphs else stripped
    if len(message) <= limit:
        return message
    return message[-limit:].lstrip()


def metadata_for_session_output(path: Path) -> dict[str, Any]:
    if path.name == CODEX_RAW_TRANSCRIPT_FILENAME:
        return {"transcript_kind": "codex_cli_stdout_jsonl", "raw_codex_cli": True}
    if path.name == CODEX_STDERR_LOG_FILENAME:
        return {"transcript_kind": "codex_cli_stderr", "raw_codex_cli": True}
    suffix = path.suffix.lower()
    if suffix == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        return {"notebook_kind": notebook_kind_for_session_output(path)}
    return {}


def notebook_kind_for_session_output(path: Path) -> str:
    name = path.stem.lower().replace("-", "_")
    if any(marker in name for marker in ("data_understanding", "grandmaster_eda", "eda", "exploration", "visual_story")):
        return "data_understanding"
    if any(marker in name for marker in ("model_diagnostics", "diagnostic", "leaderboard", "model", "experiment", "result")):
        return "model_diagnostics"
    return "agent_authored"


def stop_main_session(db: Session, project: Project) -> AgentSession | None:
    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is None:
        return None
    if session.pid:
        try:
            os.kill(session.pid, signal.SIGTERM)
        except OSError:
            pass
    session.status = "stopped"
    session.pid = None
    session.ended_at = utc_now()
    session.updated_at = utc_now()
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="session_stop_requested",
        role="harness",
        title="User stopped Full Auto",
        content="The main AgentSession was stopped by the project power control.",
        payload={"project_id": project.id},
    )
    return session
