from __future__ import annotations

import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.json import loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    AgentSupervisorLease,
    AgentTranscriptEvent,
    Project,
    utc_now,
)
from tabular_harness.services.agent_presence import supervisor_lease_active
from tabular_harness.services.agent_transcript import append_session_event

MAIN_AUTONOMOUS_SESSION_TYPE = "main_autonomous"
ACTIVE_SESSION_STATUSES = {"starting", "running", "between_turns", "waiting_for_runner"}
TERMINAL_SESSION_STATUSES = {"stopped", "failed", "gave_up", "completed"}
RETRY_BACKOFF_SECONDS = (5, 30, 120, 600)
STALE_PROCESS_TERM_GRACE_SECONDS = 5
SUPERVISOR_LEASE_TTL_SECONDS = 45
MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 15 * 60
MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS = 5 * 60

_SUPERVISOR_LOCK = threading.Lock()
_ACTIVE_SUPERVISORS: set[str] = set()


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


def project_session_still_registered(db: Session, *, project_id: str, session_id: str) -> bool:
    project_exists = db.scalar(select(Project.id).where(Project.id == project_id)) is not None
    if not project_exists:
        return False
    return db.scalar(select(AgentSession.id).where(AgentSession.id == session_id, AgentSession.project_id == project_id)) is not None


def default_supervisor_lease_owner_id(session_id: str) -> str:
    return f"pid:{os.getpid()}:session:{session_id}"


def _lease_expired(expires_at: datetime, now: datetime) -> bool:
    comparable = expires_at
    if comparable.tzinfo is None:
        comparable = comparable.replace(tzinfo=timezone.utc)
    return comparable <= now


def acquire_supervisor_lease(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    owner_id: str,
    ttl_seconds: int = SUPERVISOR_LEASE_TTL_SECONDS,
) -> bool:
    now = utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    with session_factory() as db:
        lease = db.get(AgentSupervisorLease, session_id)
        if lease is None:
            db.add(
                AgentSupervisorLease(
                    session_id=session_id,
                    owner_id=owner_id,
                    acquired_at=now,
                    heartbeat_at=now,
                    expires_at=expires_at,
                )
            )
            try:
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                lease = db.get(AgentSupervisorLease, session_id)
        if lease is None:
            return False
        if lease.owner_id == owner_id or _lease_expired(lease.expires_at, now):
            lease.owner_id = owner_id
            lease.acquired_at = now
            lease.heartbeat_at = now
            lease.expires_at = expires_at
            db.commit()
            return True
        return False


def renew_supervisor_lease(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    owner_id: str,
    ttl_seconds: int = SUPERVISOR_LEASE_TTL_SECONDS,
) -> bool:
    now = utc_now()
    with session_factory() as db:
        lease = db.get(AgentSupervisorLease, session_id)
        if lease is None or lease.owner_id != owner_id:
            return False
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        db.commit()
        return True


def release_supervisor_lease(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    owner_id: str,
) -> None:
    with session_factory() as db:
        lease = db.get(AgentSupervisorLease, session_id)
        if lease is not None and lease.owner_id == owner_id:
            db.delete(lease)
            db.commit()


def start_supervisor_lease_heartbeat(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    owner_id: str,
    ttl_seconds: int = SUPERVISOR_LEASE_TTL_SECONDS,
) -> tuple[threading.Event, threading.Event, threading.Thread]:
    stop_event = threading.Event()
    lease_lost_event = threading.Event()

    def heartbeat() -> None:
        interval = max(1.0, ttl_seconds / 3)
        while not stop_event.wait(interval):
            if not renew_supervisor_lease(
                session_factory,
                session_id=session_id,
                owner_id=owner_id,
                ttl_seconds=ttl_seconds,
            ):
                lease_lost_event.set()
                return

    thread = threading.Thread(
        target=heartbeat,
        name=f"tablex-agent-lease-{session_id}",
        daemon=True,
    )
    thread.start()
    return stop_event, lease_lost_event, thread


def append_supervisor_lease_lost_event(
    db: Session,
    *,
    session: AgentSession,
    owner_id: str | None = None,
) -> None:
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="supervisor_lease_lost",
        role="harness",
        title="Supervisor lease lost",
        content="This supervisor stopped because it no longer owns the AgentSession lease.",
        payload={"owner_id": owner_id} if owner_id else {},
        update_heartbeat=False,
    )


def supervisor_lease_lost_event_is_set(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    event: threading.Event,
) -> bool:
    if not event.is_set():
        return False
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            append_supervisor_lease_lost_event(db, session=session)
            db.commit()
    return True


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


def stop_main_session(db: Session, project: Project, *, record_event: bool = True) -> AgentSession | None:
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
    if not record_event:
        return session
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="session_stop_requested",
        role="harness",
        title="User stopped Full Auto",
        content="Full Auto was stopped by the project power control.",
        payload={"project_id": project.id},
    )
    return session


def clear_stale_stored_runner_pid(db: Session, *, session: AgentSession) -> bool:
    if session.pid is None:
        return False
    previous_pid = session.pid
    process_alive = pid_is_alive(previous_pid)
    workspace_hint = resolve_runtime_data_path(session.workspace_path) if session.workspace_path else None
    matched_codex_process = process_alive and pid_matches_agent_codex_process(previous_pid, workspace_hint, session.id)
    terminated = False
    if matched_codex_process:
        terminate_stale_codex_process(previous_pid)
        terminated = True
    session.pid = None
    session.status = "between_turns"
    if process_alive:
        session.last_error = "Recovered an unobserved Codex process from an earlier supervisor."
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="stale_runner_process_recovered",
            role="harness",
            title="Recovered unobserved Codex process",
            content="A stored Codex PID could not be monitored by this supervisor; Tablex cleared it and will continue the work.",
            payload={
                "previous_pid": previous_pid,
                "process_alive": True,
                "matched_codex_process": matched_codex_process,
                "terminated_process": terminated,
            },
        )
    else:
        session.last_error = "Cleared a stale Codex PID; Tablex will continue the work."
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="stale_runner_pid_cleared",
            role="harness",
            title="Cleared stale Codex PID",
            content="A stored Codex PID was no longer alive; Tablex cleared it and will continue the work.",
            payload={"previous_pid": previous_pid, "process_alive": False},
        )
    return True


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
    current_attempt_counted = False
    scheduled_failure_events = {"runner_retry_scheduled", "turn_recovery_scheduled"}
    raw_failure_events = {"runner_unavailable", "process_timeout", "process_killed_after_timeout"}
    for event in events:
        if event.event_type in {"turn_completed_supervisor_continue"}:
            break
        if event.event_type == "process_exited":
            payload = loads_json(event.payload_json, {})
            if payload.get("exit_code") == 0:
                break
            if not current_attempt_counted:
                count += 1
                current_attempt_counted = True
            continue
        if event.event_type in scheduled_failure_events:
            count += 1
            current_attempt_counted = True
            continue
        if event.event_type in raw_failure_events and not current_attempt_counted:
            count += 1
            current_attempt_counted = True
    return max(1, count)


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
            content=f"Delivered {len(delivered_user_event_indexes)} pending user instruction(s) to Codex.",
            payload={
                "delivered_user_event_indexes": list(delivered_user_event_indexes),
                "last_user_event_index": max(delivered_user_event_indexes),
            },
        )
        db.commit()
