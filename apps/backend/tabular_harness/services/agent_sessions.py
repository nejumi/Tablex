from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.agent.runners import safe_env
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    AgentSupervisorLease,
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
from tabular_harness.services.jobs import TERMINAL_STATUSES as TERMINAL_JOB_STATUSES
from tabular_harness.services.jobs import mark_job_succeeded
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.research_plan_timeline import research_plan_localization_summary

MAIN_AUTONOMOUS_SESSION_TYPE = "main_autonomous"
ACTIVE_SESSION_STATUSES = {"starting", "running", "between_turns", "waiting_for_runner"}
TERMINAL_SESSION_STATUSES = {"stopped", "failed", "gave_up", "completed"}
RETRY_BACKOFF_SECONDS = (5, 30, 120, 600)
STALE_PROCESS_TERM_GRACE_SECONDS = 5
SUPERVISOR_LEASE_TTL_SECONDS = 45
SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS = 30
MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60
STREAM_EVENT_FLUSH_INTERVAL_SECONDS = 0.5
STREAM_EVENT_FLUSH_MAX_LINES = 24
SESSION_INTERNAL_DIR = ".tablex"
SESSION_INBOX_DIR = "inbox"
USER_INSTRUCTIONS_INBOX_FILENAME = "user_instructions.jsonl"
USER_INSTRUCTIONS_LATEST_FILENAME = "latest_user_instruction.md"
PROGRESS_REQUEST_FILENAME = "progress_request.md"
RESEARCH_PLAN_LOCALE_REQUEST_FILENAME = "research_plan_locale_request.md"
CODEX_RAW_TRANSCRIPT_FILENAME = "codex_raw_transcript.jsonl"
CODEX_STDERR_LOG_FILENAME = "codex_stderr.log"
PROGRESS_UPDATE_NUDGE_AFTER_SECONDS = 180
PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS = 300
NOTEBOOK_CAPTURE_RETRY_AFTER_SECONDS = 5 * 60
_SUPERVISOR_LOCK = threading.Lock()
_ACTIVE_SUPERVISORS: set[str] = set()
_TRANSCRIPT_EVENT_LOCK = threading.Lock()
_TRANSCRIPT_EVENT_NEXT_INDEX: dict[str, int] = {}


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
            title="Resume requested",
            content="An active Codex session is already running for this project, so supervision will continue from the current state.",
            payload={"project_id": project.id, "autonomy_mode": autonomy_mode},
        )
        existing.status = "running"
        existing.updated_at = utc_now()
        return existing

    stopped = latest_main_session(db, project.id)
    if stopped is not None and stopped.status == "stopped":
        append_session_event(
            db,
            stopped,
            source="tablex_sidecar",
            event_type="session_resumed_after_power_on",
            role="harness",
            title="Full Auto resumed",
            content="The existing main Codex session was resumed so Raw transcript and workspace history stay continuous.",
            payload={"project_id": project.id, "autonomy_mode": autonomy_mode},
        )
        stopped.status = "between_turns"
        stopped.autonomy_mode = autonomy_mode
        stopped.runner_kind = runner_kind
        stopped.pid = None
        stopped.ended_at = None
        stopped.started_at = stopped.started_at or utc_now()
        stopped.updated_at = utc_now()
        return stopped

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
        content="The analysis has started from the current project state.",
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


def progress_request_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / PROGRESS_REQUEST_FILENAME


def research_plan_locale_request_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / RESEARCH_PLAN_LOCALE_REQUEST_FILENAME


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
            "- Keep moving in Full Auto. Ask questions when useful, but if no answer is available, record reversible assumptions and continue. Do not wait for formal approval before doing non-destructive analysis, evaluation design, modeling experiments, diagnostics, notebooks, research, or reports. Defer only destructive, production-write, deployment-grade, secret-exposing, or evaluation-integrity-breaking actions. Use Give Up only as a last resort.",
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
    update_heartbeat: bool = True,
) -> AgentTranscriptEvent:
    with _TRANSCRIPT_EVENT_LOCK:
        db.flush()
        next_index = reserve_transcript_event_indexes(db, session_id=session.id, count=1)
        event = AgentTranscriptEvent(
            id=new_id("agte"),
            project_id=session.project_id,
            session_id=session.id,
            event_index=next_index,
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
        if update_heartbeat:
            session.last_heartbeat_at = utc_now()
        return event


def reserve_transcript_event_indexes(db: Session, *, session_id: str, count: int) -> int:
    if count <= 0:
        raise ValueError("count must be positive")
    cached_next = _TRANSCRIPT_EVENT_NEXT_INDEX.get(session_id)
    if cached_next is None:
        current_max = db.scalar(
            select(func.max(AgentTranscriptEvent.event_index)).where(AgentTranscriptEvent.session_id == session_id)
        )
        next_index = int(current_max if current_max is not None else -1) + 1
    else:
        next_index = int(cached_next)
    _TRANSCRIPT_EVENT_NEXT_INDEX[session_id] = next_index + count
    return next_index


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


class StreamFileTailer:
    """Tail complete text lines from a file that another process is appending to."""

    def __init__(self, path: Path, *, offset: int = 0) -> None:
        self.path = path
        self.offset = offset
        self._partial = ""

    def read_completed_lines(self) -> list[str]:
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []
        if not chunk:
            return []
        self._partial += chunk
        parts = self._partial.splitlines(keepends=True)
        if parts and not parts[-1].endswith(("\n", "\r")):
            self._partial = parts.pop()
        else:
            self._partial = ""
        return [line if line.endswith("\n") else f"{line}\n" for line in parts]

    def drain_remaining_lines(self) -> list[str]:
        lines = self.read_completed_lines()
        if self._partial:
            lines.append(f"{self._partial}\n")
            self._partial = ""
        return lines


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


def write_progress_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    trigger: str = "stale_progress_update",
    user_message: str | None = None,
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    path = progress_request_path(workspace)
    japanese = locale_is_japanese(locale)
    user_message_excerpt = user_message.strip()[:1200] if isinstance(user_message, str) and user_message.strip() else None
    if trigger == "user_chat_message":
        if japanese:
            message = (
                "ユーザーがAgent Chatで返答を待っています。"
                "`reports/chat_update.md` をユーザーの言語で可能なタイミングですぐ更新してください。"
                "Raw logの要約ではなく、今の状況、実際に進めていること、未確定事項、次に見るべき場所を人間にわかる言葉で説明してください。"
            )
        else:
            message = (
                "The user is waiting in Agent Chat. "
                "Update `reports/chat_update.md` in the user's locale as soon as practical. "
                "Do not summarize Raw logs; explain the current situation, what is actually moving, remaining uncertainty, and where to look next."
            )
    elif japanese:
        message = (
            "人間向けの進捗説明がしばらく更新されていません。"
            "次に意味のある節目、現在の作業、詰まり、計画変更、または確認すべき成果物があるタイミングで、"
            "`reports/chat_update.md` をユーザーの言語で短く更新してください。"
            "Raw logの要約ではなく、今何をしていて、なぜそれが重要で、次にどこを見るべきかを説明してください。"
        )
    else:
        message = (
            "The human-facing progress update has been quiet for a while. "
            "At the next meaningful checkpoint, current work, issue, plan change, or artifact worth reviewing, "
            "update `reports/chat_update.md` concisely in the user's locale. "
            "Do not summarize Raw logs; explain what you are doing now, why it matters, and where the user should look next."
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "schema_version: tablex_progress_request.v1",
                    f"event_index: {event.event_index}",
                    f"created_at: {event.created_at.isoformat()}",
                    f"locale: {locale or 'unspecified'}",
                    f"trigger: {trigger}",
                    "",
                    message,
                    "",
                    *(
                        [
                            "latest_user_message:",
                            user_message_excerpt,
                            "",
                        ]
                        if user_message_excerpt
                        else []
                    ),
                ]
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def write_research_plan_locale_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    artifact: Artifact,
    locale: str,
    summary: dict[str, Any],
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    path = research_plan_locale_request_path(workspace)
    missing_blocks = [
        item
        for item in summary.get("blocks", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("missing_fields")
    ][:20]
    missing_block_lines = [
        f"- id: {item['id']} | missing_fields: {', '.join(str(field) for field in item.get('missing_fields', []))}"
        for item in missing_blocks
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "schema_version: tablex_research_plan_locale_request.v1",
                    f"event_index: {event.event_index}",
                    f"created_at: {event.created_at.isoformat()}",
                    f"locale: {locale}",
                    f"artifact_id: {artifact.id}",
                    f"artifact_path: {artifact_primary_path(artifact)}",
                    f"issue_signature: {research_plan_locale_issue_signature(summary)}",
                    f"missing_block_count: {summary.get('missing_block_count', 0)}",
                    f"missing_subtask_count: {summary.get('missing_subtask_count', 0)}",
                    "",
                    "missing_blocks:",
                    *(missing_block_lines or ["- none"]),
                    "",
                    "Update `outputs/research_plan.json` so every human-visible `timeline_blocks` string is in the requested locale.",
                    "Preserve the project-specific plan structure and Codex-authored intent; do not replace it with a fixed template.",
                    "If a canonical English copy is useful, keep it under `localizations` while making the requested locale complete.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def latest_codex_transcript_output_at(db: Session, *, session_id: str) -> datetime | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.source.in_(["codex_cli", "codex_cli_stderr"]),
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    return event.created_at if event is not None else None


def latest_codex_chat_update_at(db: Session, *, project_id: str, session_id: str) -> datetime | None:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") == "main_codex_session_chat_update" and metadata.get("agent_session_id") == session_id:
            return artifact.created_at
    return None


def latest_progress_update_nudge_at(db: Session, *, session_id: str) -> datetime | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.source == "tablex_sidecar",
            AgentTranscriptEvent.event_type == "progress_update_requested",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    return event.created_at if event is not None else None


def maybe_request_codex_progress_update(
    db: Session,
    *,
    session: AgentSession,
    locale: str | None,
    now: datetime | None = None,
    stale_after_seconds: int = PROGRESS_UPDATE_NUDGE_AFTER_SECONDS,
    min_interval_seconds: int = PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS,
    trigger: str = "stale_progress_update",
    user_message: str | None = None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES:
        return None
    observed_at = now or utc_now()
    reference = latest_codex_chat_update_at(db, project_id=session.project_id, session_id=session.id)
    if reference is None:
        reference = session.started_at or session.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if (observed_at.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds() < stale_after_seconds:
        return None
    latest_nudge = latest_progress_update_nudge_at(db, session_id=session.id)
    if latest_nudge is not None:
        if latest_nudge.tzinfo is None:
            latest_nudge = latest_nudge.replace(tzinfo=timezone.utc)
        if (observed_at.astimezone(timezone.utc) - latest_nudge.astimezone(timezone.utc)).total_seconds() < min_interval_seconds:
            return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="progress_update_requested",
        role="harness",
        title="Progress update requested",
        content="Tablex asked Codex to refresh the progress update without interrupting the current work.",
        payload={
            "locale": locale,
            "trigger": trigger,
            "stale_after_seconds": stale_after_seconds,
            "min_interval_seconds": min_interval_seconds,
            "latest_chat_update_at": reference.isoformat(),
            "user_message_excerpt": user_message.strip()[:1200]
            if isinstance(user_message, str) and user_message.strip()
            else None,
        },
        update_heartbeat=False,
    )
    write_progress_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        trigger=trigger,
        user_message=user_message,
    )
    return event


def maybe_request_codex_progress_update_safely(
    session_factory: sessionmaker[Session],
    *,
    project_id: str,
    session_id: str,
) -> None:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
            maybe_request_codex_progress_update(
                db,
                session=session,
                locale=latest_project_response_locale(db, project),
                stale_after_seconds=PROGRESS_UPDATE_NUDGE_AFTER_SECONDS,
                min_interval_seconds=PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS,
            )
            db.commit()
    except Exception:
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
    lease_owner_id: str | None = None,
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
                lease_owner_id=lease_owner_id,
                slot_acquired=True,
            )
        finally:
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
    lease_owner_id: str | None = None,
    supervisor_runner: SupervisorRunner | None = None,
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
                previous_pid = session.pid
                if pid_is_alive(previous_pid):
                    if supervisor_slot_active(session.id) or supervisor_lease_active(db, session.id):
                        continue
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
                        payload={"previous_pid": previous_pid, "process_alive": True},
                    )
                else:
                    session.pid = None
                    session.status = "between_turns"
                    session.last_error = "Cleared a stale Codex PID from before startup; Tablex will resume the same session."
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="startup_dead_runner_pid_cleared",
                        role="harness",
                        title="Startup cleared stale Codex PID",
                        content="Tablex found a stored Codex PID that is no longer alive and will resume the same AgentSession.",
                        payload={"previous_pid": previous_pid, "process_alive": False},
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
            lease_owner_id=lease_owner_id,
            supervisor_runner=supervisor_runner,
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
    lease_owner_id: str | None = None,
    max_turns: int = 100_000,
    turn_timeout_seconds: int = MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    slot_acquired: bool = False,
) -> None:
    if not slot_acquired and not acquire_supervisor_slot(session_id):
        return
    owner_id = lease_owner_id or default_supervisor_lease_owner_id(session_id)
    if not acquire_supervisor_lease(session_factory, session_id=session_id, owner_id=owner_id):
        release_supervisor_slot(session_id)
        return
    lease_stop_event, lease_lost_event, lease_thread = start_supervisor_lease_heartbeat(
        session_factory,
        session_id=session_id,
        owner_id=owner_id,
    )
    try:
        for _ in range(max_turns):
            if supervisor_lease_lost_event_is_set(session_factory, session_id=session_id, event=lease_lost_event):
                return
            with session_factory() as db:
                project = db.get(Project, project_id)
                session = db.get(AgentSession, session_id)
                if project is None or session is None:
                    return
                if lease_lost_event.is_set():
                    append_supervisor_lease_lost_event(db, session=session, owner_id=owner_id)
                    db.commit()
                    return
                if clear_stale_stored_runner_pid(db, session=session):
                    db.commit()
                    if lease_lost_event.wait(1):
                        continue
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
                if lease_lost_event.is_set():
                    append_supervisor_lease_lost_event(db, session=session, owner_id=owner_id)
                    db.commit()
                    return
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
                cancel_event=lease_lost_event,
            )
            if supervisor_lease_lost_event_is_set(session_factory, session_id=session_id, event=lease_lost_event):
                return
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
                    if lease_lost_event.wait(retry_delay):
                        continue
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
                    if lease_lost_event.wait(retry_delay):
                        continue
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
            if lease_lost_event.wait(2):
                continue
    finally:
        lease_stop_event.set()
        lease_thread.join(timeout=2)
        release_supervisor_lease(session_factory, session_id=session_id, owner_id=owner_id)
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


def default_supervisor_lease_owner_id(session_id: str) -> str:
    return f"pid:{os.getpid()}:session:{session_id}"


def _lease_expired(expires_at: datetime, now: datetime) -> bool:
    comparable = expires_at
    if comparable.tzinfo is None:
        comparable = comparable.replace(tzinfo=timezone.utc)
    return comparable <= now


def supervisor_lease_active(db: Session, session_id: str, *, now: datetime | None = None) -> bool:
    lease = db.get(AgentSupervisorLease, session_id)
    return bool(lease is not None and not _lease_expired(lease.expires_at, now or utc_now()))


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


def clear_stale_stored_runner_pid(db: Session, *, session: AgentSession) -> bool:
    if session.pid is None:
        return False
    previous_pid = session.pid
    process_alive = pid_is_alive(previous_pid)
    workspace_hint = Path(session.workspace_path) if session.workspace_path else None
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
            content="A stored Codex PID could not be monitored by this supervisor; Tablex cleared it and will resume the same session.",
            payload={
                "previous_pid": previous_pid,
                "process_alive": True,
                "matched_codex_process": matched_codex_process,
                "terminated_process": terminated,
            },
        )
    else:
        session.last_error = "Cleared a stale Codex PID; Tablex will resume the same session."
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="stale_runner_pid_cleared",
            role="harness",
            title="Cleared stale Codex PID",
            content="A stored Codex PID was no longer alive; Tablex cleared it and will resume the same AgentSession.",
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
    write_session_context_file(db, project=project, session=session)
    (workspace / ".tablex" / "GOAL.md").write_text(session.goal_text, encoding="utf-8")
    return workspace


def write_session_context_file(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    response_locale: str | None = None,
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    path = workspace / ".tablex" / "context.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        context = build_session_context(db, project=project, session=session, response_locale=response_locale)
        path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def build_session_context(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    response_locale: str | None = None,
) -> dict[str, Any]:
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
    response_locale = response_locale.strip() if isinstance(response_locale, str) and response_locale.strip() else latest_project_response_locale(db, project)
    equipped_skills = equipped_skill_context(db, skill_references)
    latest_research_plan_artifact = next((item for item in artifacts if item.asset_type == "research_plan"), None)
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
        "research_plan_display": research_plan_display_context(
            latest_research_plan_artifact,
            response_locale=response_locale,
        ),
        "output_contract": {
            "registerable_dirs": ["outputs", "reports", "notebooks", "artifacts"],
            "marimo_notebooks": "Place .py marimo notebooks under notebooks/ or outputs/notebooks/.",
            "living_research_plan": (
                "When the project plan changes, write outputs/research_plan.json with optional timeline_blocks. "
                "Tablex renders those blocks directly; after the initial anchors, Codex may add, remove, reorder, or branch them. "
                "Write human-visible timeline fields such as title, subtitle, why_it_matters, next_action, done_criteria, blockers, "
                "and subtask title/detail in human_interface.response_locale. If you keep canonical English, also include "
                "localizations like {\"ja-JP\": {\"title\": \"...\", \"subtitle\": \"...\"}}."
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
    candidates: list[tuple[datetime, str]] = []
    user = db.get(User, project.created_by)
    if user is not None and user.locale and user.locale.strip():
        candidates.append((_utc_comparable(user.updated_at), user.locale.strip()))
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project.id, Job.job_type.in_(["start_autonomous_loop", "agent_chat_turn"]))
            .order_by(Job.created_at.desc())
            .limit(20)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            candidates.append((_utc_comparable(job.created_at), locale.strip()))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    legacy_job = db.scalar(
        select(Job)
        .where(Job.project_id == project.id, Job.job_type == "start_autonomous_loop")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if legacy_job is not None:
        payload = loads_json(legacy_job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return "en-US"


def _utc_comparable(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def research_plan_display_context(artifact: Artifact | None, *, response_locale: str) -> dict[str, Any]:
    if artifact is None:
        return {
            "artifact_id": None,
            "response_locale": response_locale,
            "localization": research_plan_localization_summary([], locale=response_locale),
        }
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
    raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
    localization = research_plan_localization_summary(raw_blocks, locale=response_locale)
    return {
        "artifact_id": artifact.id,
        "path": str(artifact_primary_path(artifact)),
        "response_locale": response_locale,
        "localization": localization,
        "instruction": (
            "If missing_block_count or missing_subtask_count is nonzero, update outputs/research_plan.json "
            "so every human-visible timeline string is in response_locale or has an explicit localization entry."
        ),
    }


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
        "- For `outputs/research_plan.json` timeline_blocks, write every human-visible string in `.tablex/context.json` `human_interface.response_locale`. If you need a canonical English copy, put localized display fields under `localizations` and keep the active locale complete.",
        "- Do not write bilingual ResearchPlan display strings such as Japanese headings followed by `/ project context` or English phrase titles. Use the active locale for the sentence, and keep English only for identifiers that are genuinely identifiers.",
        "- If `.tablex/context.json` `research_plan_display.localization` reports missing locale fields, repair the ResearchPlan display fields or add `localizations` for the active locale before extending the plan. Do not leave mixed-language plan titles, subtitles, next actions, blockers, or done criteria in the user-facing timeline.",
        "- Keep human-facing accountability continuous: when you make meaningful progress, hit uncertainty, start or finish a long-running step, recover from an error, change the plan, or need the user to know what changed, overwrite `reports/chat_update.md` with only the latest concise update in the user's locale. Keep it under 1200 characters. Use separate report files for long history. Do not wait for Tablex to infer this from logs.",
        "- Treat `reports/chat_update.md` as a user-facing explanation, not an internal changelog: say what you are doing now, why it matters, what changed, what uncertainty remains, and where the user should look next. Avoid raw artifact IDs, hashes, filenames, internal schema names, and implementation vocabulary unless they are necessary for a user decision.",
        "- In Full Auto progress reports, do not make approval-waiting the dominant status. If an unconfirmed decision exists, pair it with the concrete reversible work that is continuing now, and make that active work the headline.",
        "- Prefer marimo notebooks for data understanding, modeling diagnostics, and reports.",
        "- Read `.tablex/context.json` for `human_interface.response_locale` and write human-facing notebooks/reports/chat in that language.",
        "- Read equipped Skill paths in `.tablex/context.json` before EDA, prior research, notebook authoring, or modeling strategy work.",
        "- During long turns, check `.tablex/inbox/user_instructions.jsonl`, `.tablex/inbox/latest_user_instruction.md`, `.tablex/inbox/progress_request.md`, and `.tablex/inbox/research_plan_locale_request.md`; incorporate user messages and publish progress updates without waiting for a new Codex turn when practical.",
        "- If you need user input in Full Auto, state the question and your provisional assumption, then continue unless a true hard safety boundary makes all useful work impossible.",
        "- Treat formal approval, data-owner confirmation, deployment permission, or production-write clearance as future evidence unless the current action would write to production, expose secrets, or violate evaluation integrity. Keep doing reversible local analysis and artifact generation while waiting.",
        "- Do not present Full Auto as stopped on approval unless no useful reversible work remains. If a destructive or deployment-grade action is deferred, say which reversible analysis, modeling, diagnostics, notebook/report work, or research you are continuing now.",
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
            content=f"Delivered {len(delivered_user_event_indexes)} pending user instruction(s) to Codex.",
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
    cancel_event: threading.Event | None = None,
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
                    content="Tablex cannot start Codex because the codex binary is not on PATH.",
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
            title="Starting Codex",
            content="Codex is starting from the current project workspace.",
            payload={"command": " ".join(cmd[:-1] + ["-"]), "workspace": str(workspace)},
        )
        db.commit()

    raw_stdout_path = raw_codex_transcript_path(workspace)
    raw_stderr_path = raw_codex_stderr_path(workspace)
    raw_stdout_path.parent.mkdir(parents=True, exist_ok=True)
    raw_stdout_path.touch(exist_ok=True)
    raw_stderr_path.touch(exist_ok=True)
    stdout_offset = raw_stdout_path.stat().st_size
    stderr_offset = raw_stderr_path.stat().st_size
    stdout_writer = raw_stdout_path.open("a", encoding="utf-8", buffering=1)
    stderr_writer = raw_stderr_path.open("a", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(workspace),
            stdin=subprocess.PIPE,
            stdout=stdout_writer,
            stderr=stderr_writer,
            text=True,
            bufsize=1,
            env=safe_env(workspace),
            start_new_session=True,
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
                    title="Codex started",
                    content=f"Codex process pid={process.pid} is running.",
                    payload={
                        "pid": process.pid,
                        "stdout_path": str(raw_stdout_path),
                        "stderr_path": str(raw_stderr_path),
                        "stdout_mode": "workspace_file_tail",
                    },
                )
                db.commit()
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()
        maybe_request_codex_progress_update_safely(
            session_factory,
            project_id=project_id,
            session_id=session_id,
        )

        stream_tailers = {
            "stdout": StreamFileTailer(raw_stdout_path, offset=stdout_offset),
            "stderr": StreamFileTailer(raw_stderr_path, offset=stderr_offset),
        }
    except Exception:
        stdout_writer.close()
        stderr_writer.close()
        raise

    start = time.monotonic()
    last_output_at = start
    last_workspace_ingest = 0.0
    last_stream_event_flush = start
    pending_stream_events: list[tuple[str, str]] = []
    timeout_sent = False
    cancel_sent = False
    terminated_at: float | None = None

    try:
        while True:
            now = time.monotonic()
            if now - last_workspace_ingest >= 10:
                ingest_session_workspace_outputs_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                    workspace=workspace,
                    allow_notebook_auto_capture=False,
                )
                maybe_request_codex_progress_update_safely(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                )
                last_workspace_ingest = now
            if cancel_event is not None and cancel_event.is_set() and process.poll() is None and not cancel_sent:
                process.terminate()
                append_process_cancelled_event(
                    session_factory,
                    session_id=session_id,
                    reason="supervisor_lease_lost",
                )
                cancel_sent = True
                terminated_at = now
            if now - last_output_at > timeout_seconds and process.poll() is None and not timeout_sent:
                process.terminate()
                append_process_timeout_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
                timeout_sent = True
                terminated_at = now
            if terminated_at is not None and now - terminated_at > 15 and process.poll() is None:
                process.kill()
                append_process_killed_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
                terminated_at = None

            new_lines: list[tuple[str, str]] = []
            for stream_name, tailer in stream_tailers.items():
                new_lines.extend((stream_name, line) for line in tailer.read_completed_lines())
            if new_lines:
                last_output_at = time.monotonic()
                pending_stream_events.extend(new_lines)
            now = time.monotonic()
            if pending_stream_events and (
                len(pending_stream_events) >= STREAM_EVENT_FLUSH_MAX_LINES
                or now - last_stream_event_flush >= STREAM_EVENT_FLUSH_INTERVAL_SECONDS
            ):
                append_codex_stream_lines(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                    lines=pending_stream_events,
                )
                pending_stream_events = []
                last_stream_event_flush = now
            if now - last_workspace_ingest >= 10:
                ingest_session_workspace_outputs_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                    workspace=workspace,
                    allow_notebook_auto_capture=False,
                )
                maybe_request_codex_progress_update_safely(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                )
                last_workspace_ingest = now
            if process.poll() is not None:
                for stream_name, tailer in stream_tailers.items():
                    pending_stream_events.extend((stream_name, line) for line in tailer.drain_remaining_lines())
                break
            time.sleep(0.5)
    finally:
        stdout_writer.close()
        stderr_writer.close()
    if pending_stream_events:
        append_codex_stream_lines(
            session_factory,
            project_id=project_id,
            session_id=session_id,
            lines=pending_stream_events,
        )
    try:
        return_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        append_process_killed_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
        return_code = process.wait(timeout=5)
    if return_code == 0:
        mark_user_instructions_delivered(
            session_factory,
            session_id=session_id,
            delivered_user_event_indexes=delivered_user_event_indexes,
        )
    publish_raw_codex_transcript_snapshot(workspace)
    ingest_session_workspace_outputs_safely(
        session_factory,
        store=store,
        project_id=project_id,
        session_id=session_id,
        workspace=workspace,
        allow_notebook_auto_capture=True,
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
    allow_notebook_auto_capture: bool = True,
) -> None:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
            ingest_session_workspace_outputs(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                allow_notebook_auto_capture=allow_notebook_auto_capture,
            )
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


def append_process_cancelled_event(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    reason: str,
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_cancelled",
            role="harness",
            title="Codex process cancelled",
            content="The current Codex CLI process was cancelled because this supervisor should no longer drive the session.",
            payload={"reason": reason},
            update_heartbeat=False,
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
    append_codex_stream_lines(
        session_factory,
        project_id=project_id,
        session_id=session_id,
        lines=[(stream_name, line)],
    )


def append_codex_stream_lines(
    session_factory: sessionmaker[Session],
    *,
    project_id: str,
    session_id: str,
    lines: list[tuple[str, str]],
) -> None:
    if not lines:
        return
    with _TRANSCRIPT_EVENT_LOCK:
        with session_factory() as db:
            session = db.get(AgentSession, session_id)
            if session is None:
                return
            next_index = reserve_transcript_event_indexes(db, session_id=session.id, count=len(lines))
            now = utc_now()
            for stream_name, line in lines:
                source, event_type, title, content, payload = codex_stream_event_fields(stream_name, line)
                if event_type == "thread.started" and isinstance(payload.get("thread_id"), str):
                    session.codex_thread_id = str(payload["thread_id"])
                db.add(
                    AgentTranscriptEvent(
                        id=new_id("agte"),
                        project_id=project_id,
                        session_id=session.id,
                        event_index=next_index,
                        source=source,
                        event_type=event_type,
                        role="runner",
                        title=title,
                        content=content,
                        payload_json=dumps_json(payload),
                        created_at=now,
                    )
                )
                next_index += 1
            session.updated_at = utc_now()
            session.last_heartbeat_at = utc_now()
            db.commit()


def codex_stream_event_fields(stream_name: str, line: str) -> tuple[str, str, str, str | None, dict[str, Any]]:
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
    source = "codex_cli" if stream_name == "stdout" else "codex_cli_stderr"
    return source, event_type, title, content, payload


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
    allow_notebook_auto_capture: bool = True,
) -> None:
    output_roots = [workspace / "outputs", workspace / "reports", workspace / "notebooks", workspace / "artifacts"]
    response_locale: str | None = None
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
            if asset_type == "research_plan":
                response_locale = response_locale or latest_project_response_locale(db, project)
                maybe_request_research_plan_locale_refresh(db, session=session, artifact=artifact, locale=response_locale)
            if allow_notebook_auto_capture:
                maybe_capture_agent_session_notebook_output(
                    db,
                    store=store,
                    session=session,
                    artifact=artifact,
                )
            else:
                maybe_defer_agent_session_notebook_capture(db, session=session, artifact=artifact)
    if allow_notebook_auto_capture:
        capture_pending_agent_session_notebooks(db, store=store, project=project, session=session)


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


def maybe_capture_agent_session_notebook_output(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    artifact: Artifact,
) -> None:
    if artifact.asset_type != "analysis_notebook" or artifact.project_id is None:
        return
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("source") != "main_agent_session_workspace":
        return
    if agent_session_notebook_capture_event_exists(
        db,
        session=session,
        artifact=artifact,
        event_types=("notebook_auto_capture_succeeded",),
    ):
        return
    latest_failure = latest_agent_session_notebook_capture_event(
        db,
        session=session,
        artifact=artifact,
        event_types=("notebook_auto_capture_failed",),
    )
    if latest_failure is not None and not notebook_capture_failure_retry_due(latest_failure):
        return
    existing_captures = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == artifact.project_id,
                Artifact.asset_type == "notebook_execution_manifest",
            )
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    if any(loads_json(item.metadata_json, {}).get("notebook_artifact_id") == artifact.id for item in existing_captures):
        return
    try:
        from tabular_harness.services.analysis_notebooks import create_notebook_execution_capture

        capture = create_notebook_execution_capture(db, store=store, notebook_artifact=artifact)
    except Exception as exc:
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="notebook_auto_capture_failed",
            role="harness",
            title="Notebook preview capture failed",
            content="A Codex-authored marimo notebook was saved, but Tablex could not render the preview automatically.",
            payload={"notebook_artifact_id": artifact.id, "error": str(exc)[:1200]},
            artifact_id=artifact.id,
        )
        return
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_auto_capture_succeeded",
        role="harness",
        title="Notebook preview captured",
        content="A Codex-authored marimo notebook was rendered into in-product notebook evidence.",
        payload={
            "notebook_artifact_id": artifact.id,
            "notebook_execution_html_artifact_id": capture.html_artifact.id,
            "notebook_execution_manifest_artifact_id": capture.manifest_artifact.id,
            "notebook_evidence_html_artifact_id": capture.evidence_html_artifact.id
            if capture.evidence_html_artifact
            else None,
        },
        artifact_id=capture.html_artifact.id,
    )


def notebook_capture_failure_retry_due(
    event: AgentTranscriptEvent,
    *,
    retry_after_seconds: int = NOTEBOOK_CAPTURE_RETRY_AFTER_SECONDS,
) -> bool:
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (utc_now() - created_at).total_seconds() >= retry_after_seconds


def maybe_defer_agent_session_notebook_capture(db: Session, *, session: AgentSession, artifact: Artifact) -> None:
    if artifact.asset_type != "analysis_notebook" or artifact.project_id is None:
        return
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("source") != "main_agent_session_workspace":
        return
    if agent_session_notebook_capture_event_exists(
        db,
        session=session,
        artifact=artifact,
        event_types=(
            "notebook_auto_capture_deferred",
            "notebook_auto_capture_succeeded",
            "notebook_auto_capture_failed",
        ),
    ):
        return
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_auto_capture_deferred",
        role="harness",
        title="Notebook preview capture deferred",
        content="A Codex-authored marimo notebook was registered; preview rendering will run after the active Codex turn yields.",
        payload={"notebook_artifact_id": artifact.id},
        artifact_id=artifact.id,
        update_heartbeat=False,
    )


def capture_pending_agent_session_notebooks(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> None:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in reversed(notebook_artifacts):
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        maybe_capture_agent_session_notebook_output(db, store=store, session=session, artifact=artifact)


def agent_session_notebook_capture_event_exists(
    db: Session,
    *,
    session: AgentSession,
    artifact: Artifact,
    event_types: tuple[str, ...],
) -> bool:
    return latest_agent_session_notebook_capture_event(
        db,
        session=session,
        artifact=artifact,
        event_types=event_types,
    ) is not None


def latest_agent_session_notebook_capture_event(
    db: Session,
    *,
    session: AgentSession,
    artifact: Artifact,
    event_types: tuple[str, ...],
) -> AgentTranscriptEvent | None:
    recent_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type.in_(event_types),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(100)
        ).all()
    )
    for event in recent_events:
        payload = loads_json(event.payload_json, {})
        if payload.get("notebook_artifact_id") == artifact.id:
            return event
    return None


def maybe_request_research_plan_locale_refresh(
    db: Session,
    *,
    session: AgentSession,
    artifact: Artifact,
    locale: str | None,
) -> None:
    if artifact.asset_type != "research_plan" or artifact.project_id is None or not session.workspace_path:
        return
    if not locale or locale.lower().startswith("en"):
        return
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return
    raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
    summary = research_plan_localization_summary(raw_blocks, locale=locale)
    if not summary.get("requires_explicit_locale"):
        return
    if not summary.get("missing_block_count") and not summary.get("missing_subtask_count"):
        return
    issue_signature = research_plan_locale_issue_signature(summary)
    project = db.get(Project, artifact.project_id)
    if project is not None:
        write_session_context_file(db, project=project, session=session, response_locale=locale)
    recent_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "research_plan_locale_refresh_requested",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(50)
        ).all()
    )
    for event in recent_events:
        event_payload = loads_json(event.payload_json, {})
        if (
            event_payload.get("artifact_id") == artifact.id
            and event_payload.get("locale") == locale
            and event_payload.get("issue_signature") == issue_signature
        ):
            return
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="research_plan_locale_refresh_requested",
        role="harness",
        title="ResearchPlan display-language refresh requested",
        content="Tablex asked Codex to refresh the ResearchPlan display fields in the user's selected locale.",
        payload={
            "artifact_id": artifact.id,
            "locale": locale,
            "issue_signature": issue_signature,
            "missing_block_count": summary.get("missing_block_count", 0),
            "missing_subtask_count": summary.get("missing_subtask_count", 0),
            "blocks": summary.get("blocks", []),
        },
        artifact_id=artifact.id,
        update_heartbeat=False,
    )
    write_research_plan_locale_request_to_workspace_inbox(session, event=event, artifact=artifact, locale=locale, summary=summary)


def research_plan_locale_issue_signature(summary: dict[str, Any]) -> str:
    issue_payload = {
        "locale": summary.get("requested_locale"),
        "missing_block_count": summary.get("missing_block_count", 0),
        "missing_subtask_count": summary.get("missing_subtask_count", 0),
        "blocks": [
            {
                "id": item.get("id"),
                "missing_fields": item.get("missing_fields", []),
            }
            for item in summary.get("blocks", [])
            if isinstance(item, dict)
        ],
    }
    return hashlib.sha256(dumps_json(issue_payload).encode("utf-8")).hexdigest()


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
    complete_pending_chat_job_from_main_session_update(
        db,
        project=project,
        session=session,
        chat_artifact=chat_artifact,
        message=message,
    )


def complete_pending_chat_job_from_main_session_update(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    chat_artifact: Artifact,
    message: str,
) -> Job | None:
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.project_id == project.id,
                Job.job_type == "agent_chat_turn",
                ~Job.status.in_(TERMINAL_JOB_STATUSES),
            )
            .order_by(Job.created_at.asc())
            .limit(100)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        if payload.get("delivered_agent_session_id") != session.id:
            continue
        mark_job_succeeded(
            job,
            {
                "schema_version": "agent_chat_turn_completion.v1",
                "status": "answered_by_main_codex_session",
                "agent_session_id": session.id,
                "progress_artifact_id": chat_artifact.id,
                "response_locale": payload.get("locale") if isinstance(payload.get("locale"), str) else None,
                "message_preview": message[:280],
            },
        )
        return job
    return None


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
        content="Full Auto was stopped by the project power control.",
        payload={"project_id": project.id},
    )
    return session
