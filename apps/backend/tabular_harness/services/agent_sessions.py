from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import re
import shutil
import signal
import subprocess
import sys
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

from tabular_harness.agent.runners import CODEX_HARNESS_CONFIG_ARGS, safe_env
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
    ExperimentRun,
    Job,
    LineageEdge,
    ModelVersion,
    Project,
    User,
    utc_now,
)
from tabular_harness.services.agent_session_results import (
    experiment_acks_dir,
    experiment_requests_dir,
    ingest_registered_session_experiment_artifacts,
    process_experiment_result_requests,
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
from tabular_harness.services.research_plan_timeline import (
    research_plan_contract_validation_summary,
    research_plan_evidence_links,
    research_plan_localization_summary,
)
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    attach_research_plan_artifact,
    commit_research_plan_artifact_revision,
    commit_research_plan_revision,
    latest_research_plan_current_work,
    latest_research_plan_revision,
    request_research_plan_human_attention,
    research_plan_current_work_payload,
    research_plan_revision_document,
    set_research_plan_current_work,
)

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
SESSION_BIN_DIR = "bin"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
RESEARCH_PLAN_REQUESTS_DIR = "research_plan"
RESEARCH_PLAN_REQUEST_SCHEMA_VERSION = "tablex_research_plan_request.v1"
RESEARCH_PLAN_ACK_SCHEMA_VERSION = "tablex_research_plan_ack.v1"
NOTEBOOK_REQUESTS_DIR = "notebooks"
NOTEBOOK_REQUEST_SCHEMA_VERSION = "tablex_notebook_request.v1"
NOTEBOOK_ACK_SCHEMA_VERSION = "tablex_notebook_ack.v1"
USER_INSTRUCTIONS_INBOX_FILENAME = "user_instructions.jsonl"
USER_INSTRUCTIONS_LATEST_FILENAME = "latest_user_instruction.md"
PROGRESS_REQUEST_FILENAME = "progress_request.md"
RESEARCH_PLAN_CONTRACT_REQUEST_FILENAME = "research_plan_contract_request.md"
RESEARCH_PLAN_ARTIFACT_REJECTION_FILENAME = "research_plan_artifact_rejection.md"
RESEARCH_PLAN_REQUEST_REJECTION_FILENAME = "research_plan_request_rejection.md"
NOTEBOOK_REQUEST_REJECTION_FILENAME = "notebook_request_rejection.md"
NOTEBOOK_CAPTURE_FAILURE_FILENAME = "notebook_capture_failure.md"
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


def research_plan_contract_request_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / RESEARCH_PLAN_CONTRACT_REQUEST_FILENAME


def research_plan_artifact_rejection_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / RESEARCH_PLAN_ARTIFACT_REJECTION_FILENAME


def research_plan_request_rejection_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / RESEARCH_PLAN_REQUEST_REJECTION_FILENAME


def notebook_request_rejection_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / NOTEBOOK_REQUEST_REJECTION_FILENAME


def notebook_capture_failure_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR / NOTEBOOK_CAPTURE_FAILURE_FILENAME


def research_plan_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / RESEARCH_PLAN_REQUESTS_DIR


def research_plan_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / RESEARCH_PLAN_REQUESTS_DIR


def notebook_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / NOTEBOOK_REQUESTS_DIR


def notebook_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / NOTEBOOK_REQUESTS_DIR


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


def research_plan_contract_issue_hash(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    stable_issues = [
        {
            "code": str(issue.get("code") or ""),
            "path": str(issue.get("path") or ""),
            "message": str(issue.get("message") or ""),
            "severity": str(issue.get("severity") or "error"),
        }
        for issue in issues
        if isinstance(issue, dict)
    ]
    return hashlib.sha1(dumps_json(stable_issues).encode("utf-8")).hexdigest()


def latest_research_plan_contract_request_event(
    db: Session,
    *,
    session_id: str,
    issue_hash: str,
) -> AgentTranscriptEvent | None:
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "research_plan_contract_revision_requested",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(50)
        ).all()
    )
    for event in events:
        payload = loads_json(event.payload_json, {})
        if payload.get("issue_hash") == issue_hash:
            return event
    return None


def write_research_plan_contract_request_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    locale: str | None,
    validation: dict[str, Any],
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    path = research_plan_contract_request_path(workspace)
    japanese = locale_is_japanese(locale)
    issues = [issue for issue in validation.get("issues", []) if isinstance(issue, dict)]
    if japanese:
        headline = (
            "現在のResearchPlanは表示できますが、構造化された実行台帳としては再申告が必要です。"
            "作業を止めず、`.tablex/requests/research_plan/` の `commit_revision` で章粒度のplanを再commitしてください。"
        )
        action = (
            "トップレベルは最大7件のchapter/phase/milestoneにまとめ、個別分析、モデル試行、診断、"
            "Notebookやレポート断片はsubtasks、completion_evidence、ExperimentRun、artifact linkへ移してください。"
        )
    else:
        headline = (
            "The current ResearchPlan is visible, but it needs a validated re-commit as the structured execution ledger. "
            "Do not stop the project; submit a chapter-level plan with `.tablex/requests/research_plan/` `commit_revision`."
        )
        action = (
            "Keep at most 7 top-level chapter/phase/milestone nodes. Move individual analyses, model attempts, diagnostics, "
            "notebook/report sections, and detailed comparisons into subtasks, completion_evidence, ExperimentRuns, or artifact links."
        )
    lines = [
        "schema_version: tablex_research_plan_contract_request.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"locale: {locale or 'unspecified'}",
        f"issue_count: {validation.get('issue_count', 0)}",
        f"error_count: {validation.get('error_count', 0)}",
        f"warning_count: {validation.get('warning_count', 0)}",
        "",
        headline,
        "",
        action,
        "",
        "Tool request path:",
        ".tablex/requests/research_plan/<new_request_id>.json",
        "",
        "Expected operation:",
        "commit_revision",
        "",
        "After writing the request, read the matching ack under `.tablex/acks/research_plan/`. "
        "If the ack fails, revise the JSON and resubmit with a new request_id.",
        "",
        "Top issues:",
    ]
    for issue in issues[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        return


def write_research_plan_artifact_rejection_to_workspace_inbox(
    session: AgentSession,
    *,
    event: AgentTranscriptEvent,
    artifact: Artifact,
    workspace_relative_path: str,
    issues: list[dict[str, Any]],
) -> None:
    if not session.workspace_path:
        return
    workspace = Path(session.workspace_path)
    path = research_plan_artifact_rejection_path(workspace)
    lines = [
        "schema_version: tablex_research_plan_artifact_rejection.v1",
        f"event_index: {event.event_index}",
        f"created_at: {event.created_at.isoformat()}",
        f"artifact_id: {artifact.id}",
        f"workspace_relative_path: {workspace_relative_path}",
        "",
        "The ResearchPlan artifact was registered, but it was not accepted as the canonical ResearchPlan revision.",
        "Revise the plan through the validated request channel instead of assuming this file is the visible plan.",
        "",
        "Tool request path:",
        ".tablex/requests/research_plan/<new_request_id>.json",
        "",
        "Expected operation:",
        "commit_revision",
        "",
        "After writing the request, read the matching ack under `.tablex/acks/research_plan/`. "
        "If the ack fails, revise the JSON and resubmit with a new request_id.",
        "",
        "Top issues:",
    ]
    for issue in issues[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        return


def write_research_plan_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
    issues: list[dict[str, Any]] | None = None,
) -> None:
    path = research_plan_request_rejection_path(workspace)
    lines = [
        "schema_version: tablex_research_plan_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The ResearchPlan request was rejected by Tablex validation and did not change the canonical plan.",
        "Read the ack JSON, repair the fixed request payload, and resubmit with a new request_id.",
        "",
        "Important:",
        "- Do not continue as if the rejected ResearchPlan was accepted.",
        "- If a done node claims notebook/report/artifact outputs, first register or capture the asset and reference its artifact_id or ingested workspace_path.",
        "- If a done node claims experiment_run or leaderboard_entry outputs, first register runs through `.tablex/requests/experiments/` and reference a registered experiment_run_id.",
        "",
        "Error:",
        error_message,
        "",
        "Top issues:",
    ]
    for issue in (issues or [])[:8]:
        lines.extend(
            [
                f"- code: {issue.get('code')}",
                f"  path: {issue.get('path')}",
                f"  message: {issue.get('message')}",
                f"  fix: {issue.get('fix')}",
            ]
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        return


def write_notebook_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
) -> None:
    path = notebook_request_rejection_path(workspace)
    lines = [
        "schema_version: tablex_notebook_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The Notebook request was rejected by Tablex validation or rendering and did not update Notebook previews, Chat links, ResearchPlan evidence, or contextual Data/Leaderboard/Assets links.",
        "Read the ack JSON, repair the fixed request payload or the notebook source, and resubmit under `.tablex/requests/notebooks/` with a new request_id.",
        "",
        "Use this request channel after saving a marimo notebook so Tablex can register it as an asset, render the preview, attach lineage, and make it visible from the related Chat, ResearchPlan node, Dataset, Run, Model, and Assets views.",
        "",
        "Error:",
        error_message,
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        return


def write_notebook_capture_failure_to_workspace_inbox(
    workspace: Path,
    *,
    notebook_artifact: Artifact,
    error_message: str,
) -> None:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    workspace_path = metadata.get("workspace_relative_path")
    if not isinstance(workspace_path, str) or not workspace_path.strip():
        workspace_path = metadata.get("source_path") if isinstance(metadata.get("source_path"), str) else ""
    path = notebook_capture_failure_path(workspace)
    lines = [
        "schema_version: tablex_notebook_capture_failure.v1",
        f"notebook_artifact_id: {notebook_artifact.id}",
        f"notebook_name: {notebook_artifact.name}",
        f"workspace_path: {workspace_path or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        "",
        "Tablex registered the Codex-authored marimo notebook source, but preview capture failed. The source remains an artifact, but the readable in-product preview may be unavailable until the notebook is repaired or recaptured.",
        "Repair the notebook source or write a fixed request under `.tablex/requests/notebooks/` with `schema_version: \"tablex_notebook_request.v1\"` and operation `capture_notebook`.",
        "",
        "Error:",
        error_message,
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except OSError:
        return


def maybe_request_research_plan_contract_revision(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    locale: str | None = None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES:
        return None
    payload, source = research_plan_context_payload(db, artifact=None, project_id=project.id)
    validation = research_plan_contract_validation_summary(db, project_id=project.id, payload=payload)
    if validation.get("status") != "needs_revision":
        return None
    issue_hash = research_plan_contract_issue_hash(validation)
    existing_event = latest_research_plan_contract_request_event(db, session_id=session.id, issue_hash=issue_hash)
    if existing_event is not None:
        return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="research_plan_contract_revision_requested",
        role="harness",
        title="ResearchPlan revision requested",
        content="Tablex asked Codex to re-commit the ResearchPlan through the validated request channel.",
        payload={
            "locale": locale,
            "issue_hash": issue_hash,
            "source": source,
            "validation": validation,
        },
        update_heartbeat=False,
    )
    write_research_plan_contract_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        validation=validation,
    )
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=f"research_plan_contract_needs_revision:{issue_hash}",
        status="needs_attention",
        message_kind="research_plan_contract_needs_revision",
        details={
            "issue_hash": issue_hash,
            "error_count": validation.get("error_count", 0),
            "warning_count": validation.get("warning_count", 0),
            "issue_count": validation.get("issue_count", 0),
            "top_issue_codes": [issue.get("code") for issue in validation.get("issues", [])[:6] if isinstance(issue, dict)],
        },
    )
    return event


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
                maybe_request_research_plan_contract_revision(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    locale=latest_project_response_locale(db, project),
                )
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
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key="runner_unavailable",
                        status="waiting",
                        message_kind="runner_unavailable",
                        details={"retry_delay_seconds": retry_delay, "failure_kind": "runner_unavailable"},
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
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key=f"turn_recovery:{exit_code}",
                        status="waiting",
                        message_kind="turn_recovery",
                        details={"exit_code": exit_code, "retry_delay_seconds": retry_delay},
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
    ensure_session_python_shims(workspace)
    research_plan_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    research_plan_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    notebook_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    notebook_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    experiment_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    experiment_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    write_session_context_file(db, project=project, session=session)
    (workspace / ".tablex" / "GOAL.md").write_text(session.goal_text, encoding="utf-8")
    return workspace


def ensure_session_python_shims(workspace: Path) -> None:
    bin_dir = workspace / SESSION_INTERNAL_DIR / SESSION_BIN_DIR
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for name in ("python", "python3"):
        target = bin_dir / name
        try:
            if target.exists() or target.is_symlink():
                if target.resolve() == Path(sys.executable).resolve():
                    continue
                target.unlink()
            target.symlink_to(sys.executable)
        except OSError:
            script = f"#!/usr/bin/env sh\nexec {json.dumps(sys.executable)} \"$@\"\n"
            try:
                target.write_text(script, encoding="utf-8")
                target.chmod(0o755)
            except OSError:
                continue


def python_runtime_context(workspace: Path) -> dict[str, Any]:
    workspace_python = workspace / SESSION_INTERNAL_DIR / SESSION_BIN_DIR / "python"
    packages = {
        "marimo": package_version_or_none("marimo"),
        "pandas": package_version_or_none("pandas"),
        "numpy": package_version_or_none("numpy"),
        "scikit_learn": package_version_or_none("scikit-learn"),
        "matplotlib": package_version_or_none("matplotlib"),
        "plotly": package_version_or_none("plotly"),
        "duckdb": package_version_or_none("duckdb"),
        "polars": package_version_or_none("polars"),
        "xgboost": package_version_or_none("xgboost"),
        "lightgbm": package_version_or_none("lightgbm"),
    }
    return {
        "tablex_backend": {
            "executable": sys.executable,
            "workspace_python": str(workspace_python),
            "workspace_python_exists": workspace_python.exists(),
            "packages": packages,
        },
        "notebook_execution": {
            "marimo_available": packages["marimo"] is not None,
            "rendering_owner": "tablex_harness",
            "source_dirs": ["notebooks", "outputs/notebooks"],
        },
    }


def package_version_or_none(package_name: str) -> str | None:
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return None


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
            db,
            latest_research_plan_artifact,
            project_id=project.id,
            response_locale=response_locale,
        ),
        "python_runtimes": python_runtime_context(Path(session.workspace_path or "")),
        "output_contract": {
            "registerable_dirs": ["outputs", "reports", "notebooks", "artifacts"],
            "marimo_notebooks": "Place .py marimo notebooks under notebooks/ or outputs/notebooks/.",
            "notebook_runtime": (
                "For local notebook checks inside this workspace, prefer python_runtimes.tablex_backend.workspace_python. "
                "Tablex renders registered marimo notebooks after they are saved as artifacts."
            ),
            "living_research_plan": (
                "When the project plan changes, write outputs/research_plan.json with optional timeline_blocks. "
                "Tablex renders those blocks directly; after the initial anchors, Codex may append, refine, supersede, or branch them. "
                "Keep top-level timeline_blocks coarse and capped at 7 nodes: use granularity chapter, phase, or milestone. Put individual analyses, "
                "model attempts, diagnostics, notebook sections, and reports in subtasks, ExperimentRuns, artifacts, or completion evidence. "
                "Completed nodes are append-only: keep them visible and add follow-up nodes when more work is needed. "
                "For validated tool commits, exactly one open top-level node should be active/waiting/blocked, and a done node needs "
                "structured completion_evidence, supporting_artifacts, or a no_output_required rationale. "
                "Write human-visible timeline fields such as title, subtitle, why_it_matters, next_action, done_criteria, blockers, "
                "and subtask title/detail in human_interface.response_locale. If you keep canonical English, also include "
                "localizations like {\"ja-JP\": {\"title\": \"...\", \"subtitle\": \"...\"}}."
            ),
            "research_plan_tool_requests": {
                "request_dir": ".tablex/requests/research_plan",
                "ack_dir": ".tablex/acks/research_plan",
                "schema_version": "tablex_research_plan_request.v1",
                "operations": [
                    "commit_revision",
                    "set_current_work",
                    "attach_artifact",
                    "request_human_attention",
                ],
                "description": (
                    "Use this fixed JSON request/ack channel when you need Tablex to commit a plan revision, update the "
                    "current plan node, link an output artifact to a node, or create a human-attention question. "
                    "Use a new request_id and file for each operation, then read the matching ack JSON."
                ),
                "commit_revision_contract": {
                    "top_level_granularity": ["chapter", "phase", "milestone"],
                    "max_top_level_nodes": 7,
                    "current_rule": "If any top-level work remains open, exactly one top-level node should be active, waiting, or blocked.",
                    "done_rule": (
                        "A done node must include completion_evidence/supporting_artifacts or no_output_required with rationale. "
                        "If it produced output, include deliverable_contract.expected_outputs and matching evidence output_type values."
                    ),
                    "known_output_types": [
                        "notebook",
                        "report",
                        "experiment_run",
                        "leaderboard_entry",
                        "artifact",
                        "question",
                    ],
                    "example_done_node": {
                        "id": "data_understanding",
                        "title": "Data understanding and relational map",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook", "report"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "workspace_path": "notebooks/data_understanding.py"},
                            {"output_type": "report", "workspace_path": "reports/data_understanding.md"},
                        ],
                    },
                },
            },
            "experiment_result_tool_requests": {
                "request_dir": ".tablex/requests/experiments",
                "ack_dir": ".tablex/acks/experiments",
                "schema_version": "tablex_experiment_result_request.v1",
                "operations": ["register_runs"],
                "description": (
                    "Use this fixed JSON request/ack channel when model or evaluation results should become "
                    "Tablex ExperimentRun records and appear in the Leaderboard. Each run must include a stable "
                    "model_id and numeric metrics. Prefer one comparable primary metric across runs in the same result set."
                ),
                "register_runs_contract": {
                    "optional_project_link": "Set payload.research_plan_node_id or per-run research_plan_node_id to link the run to a ResearchPlan node.",
                    "optional_context_links": (
                        "Set payload.dataset_snapshot_id, payload.evaluation_spec_id, payload.split_manifest_id, "
                        "and payload.source_workspace_path when available. Tablex validates these fixed ids, derives "
                        "dataset/evaluation context from split manifests, resolves workspace paths to registered artifacts, "
                        "and links the resulting ExperimentRuns back to the evidence artifact and visible ResearchPlan node."
                    ),
                    "required_run_fields": ["model_id", "metrics"],
                    "recommended_run_fields": [
                        "summary",
                        "primary_metric_name",
                        "source_workspace_path",
                        "dataset_snapshot_id",
                        "evaluation_spec_id",
                        "split_manifest_id",
                    ],
                    "example_request": {
                        "schema_version": "tablex_experiment_result_request.v1",
                        "request_id": "register_model_runs_001",
                        "operation": "register_runs",
                        "payload": {
                            "research_plan_node_id": "modeling_and_diagnostics",
                            "source_workspace_path": "reports/model_results_summary.md",
                            "split_manifest_id": "split_primary",
                            "runs": [
                                {
                                    "model_id": "xgboost_structured_text_v1",
                                    "summary": "Fold-safe boosted baseline with structured and text features.",
                                    "primary_metric_name": "mae",
                                    "metrics": {"mae": 123.4, "rmse": 180.0},
                                    "source_workspace_path": "artifacts/model_results.json",
                                }
                            ],
                        },
                    },
                },
            },
            "notebook_tool_requests": {
                "request_dir": ".tablex/requests/notebooks",
                "ack_dir": ".tablex/acks/notebooks",
                "schema_version": NOTEBOOK_REQUEST_SCHEMA_VERSION,
                "operations": ["capture_notebook"],
                "description": (
                    "Use this fixed JSON request/ack channel after saving a marimo notebook when you need Tablex "
                    "to render an in-product preview, link it to a ResearchPlan node, and post a human-facing Chat link. "
                    "Read the matching ack before marking the plan node done."
                ),
                "capture_notebook_contract": {
                    "required_reference": "payload.artifact_id or payload.workspace_path",
                    "optional_project_link": "Set payload.research_plan_node_id to link the source and preview to a visible plan node.",
                    "optional_context_links": (
                        "Set payload.dataset_snapshot_id for data notebooks, payload.run_id for run/model diagnostics, "
                        "and payload.model_version_id when the notebook explains a model package. Tablex validates these "
                        "ids and stores them on the notebook artifact so Data, Leaderboard, Assets, and ResearchPlan can "
                        "all open the same notebook viewer."
                    ),
                    "example_request": {
                        "schema_version": NOTEBOOK_REQUEST_SCHEMA_VERSION,
                        "request_id": "capture_data_understanding_notebook_001",
                        "operation": "capture_notebook",
                        "payload": {
                            "workspace_path": "notebooks/data_understanding.py",
                            "research_plan_node_id": "data_understanding",
                            "notebook_kind": "data_understanding",
                            "dataset_snapshot_id": "ds_current",
                        },
                    },
                },
            },
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


def research_plan_display_context(
    db: Session,
    artifact: Artifact | None,
    *,
    project_id: str,
    response_locale: str,
) -> dict[str, Any]:
    payload, source = research_plan_context_payload(db, artifact=artifact, project_id=project_id)
    raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
    localization = research_plan_localization_summary(raw_blocks, locale=response_locale)
    return {
        **source,
        "response_locale": response_locale,
        "localization": localization,
        "contract_validation": research_plan_contract_validation_summary(
            db,
            project_id=project_id,
            payload=payload if isinstance(payload, dict) else {},
        ),
    }


def research_plan_context_payload(
    db: Session,
    *,
    artifact: Artifact | None,
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    revision = latest_research_plan_revision(db, project_id=project_id)
    if revision is not None:
        payload = research_plan_revision_document(revision)
        return (
            payload if isinstance(payload, dict) else {},
            {
                "source": "research_plan_revision",
                "source_revision_id": revision.id,
                "research_plan_id": revision.research_plan_id,
                "revision_index": revision.revision_index,
                "revision_author_type": revision.author_type,
                "source_artifact_id": revision.source_artifact_id,
                "artifact_id": revision.source_artifact_id,
                "path": None,
            },
        )
    if artifact is None:
        return (
            {"timeline_blocks": []},
            {
                "source": "none",
                "source_revision_id": None,
                "research_plan_id": None,
                "revision_index": None,
                "revision_author_type": None,
                "source_artifact_id": None,
                "artifact_id": None,
                "path": None,
            },
        )
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
    return (
        payload if isinstance(payload, dict) else {},
        {
            "source": "research_plan_artifact",
            "source_revision_id": None,
            "research_plan_id": None,
            "revision_index": None,
            "revision_author_type": None,
            "source_artifact_id": artifact.id,
            "artifact_id": artifact.id,
            "path": str(artifact_primary_path(artifact)),
        },
    )


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
        "- Keep a living plan when it helps the user follow the work: write `outputs/research_plan.json` with `schema_version: \"research_plan.v1\"` and optional `timeline_blocks`. Use `timeline_blocks` as an execution ledger: after data upload, objective/task framing, data understanding, and prior-knowledge research anchors, add, refine, supersede, or branch project-specific blocks. Top-level timeline blocks should be coarse chapters/phases/milestones with `granularity: \"chapter\"`, `\"phase\"`, or `\"milestone\"`; put individual analyses, model attempts, diagnostics, notebook sections, and reports in `subtasks`, ExperimentRuns, artifacts, or completion evidence rather than as top-level blocks. Do not remove or reopen completed nodes; add follow-up nodes instead. Mark a block done only when completion_evidence/supporting_artifacts exist or you explicitly record that no useful output is needed.",
        "- For acknowledged ResearchPlan operations, write fixed JSON requests under `.tablex/requests/research_plan/` using `schema_version: \"tablex_research_plan_request.v1\"`; Tablex writes matching acks under `.tablex/acks/research_plan/`. Use this for `commit_revision`, `set_current_work`, `attach_artifact`, and `request_human_attention` when you need a validated harness-side state update. Valid commits keep the visible plan left-to-right, keep at most 7 top-level chapter/phase/milestone nodes, keep exactly one open top-level node active/waiting/blocked, keep detailed work below chapter-level nodes, and give done nodes a deliverable_contract plus matching completion evidence unless no output is intentionally required. If a done node claims notebook/report/artifact outputs, completion_evidence must reference a registered Tablex artifact_id or a workspace_path that Tablex already ingested; if it claims experiment_run or leaderboard_entry outputs, completion_evidence must reference a registered experiment_run_id. Invalid plan transitions are returned as actionable ack errors; revise and resubmit instead of continuing with an inconsistent visible plan.",
        "- For model comparison or evaluation results that should appear in Leaderboard, write fixed JSON requests under `.tablex/requests/experiments/` using `schema_version: \"tablex_experiment_result_request.v1\"` and operation `register_runs`, or save structured result JSON such as `model_results.v1` under artifacts/. Include `research_plan_node_id` when the runs belong to a visible plan node. Include `source_workspace_path`, `dataset_snapshot_id`, `evaluation_spec_id`, and `split_manifest_id` when available so Tablex can validate the result context, link evidence artifacts, and make the run inspectable from Leaderboard and ResearchPlan.",
        "- For marimo notebooks that should be visible in Tablex, write fixed JSON requests under `.tablex/requests/notebooks/` using `schema_version: \"tablex_notebook_request.v1\"` and operation `capture_notebook` after saving the notebook. Include `workspace_path` or `artifact_id`, and include `research_plan_node_id` when the notebook belongs to a visible plan node. Tablex writes acks under `.tablex/acks/notebooks/` with preview artifact ids or actionable render errors.",
        "- For `outputs/research_plan.json` timeline_blocks, write human-facing strings in `.tablex/context.json` `human_interface.response_locale` when practical. Keep identifiers and source column names exact.",
        "- Keep human-facing accountability continuous: when you make meaningful progress, hit uncertainty, start or finish a long-running step, recover from an error, change the plan, or need the user to know what changed, overwrite `reports/chat_update.md` with only the latest concise update in the user's locale. Keep it under 1200 characters. Use separate report files for long history. Do not wait for Tablex to infer this from logs.",
        "- Treat `reports/chat_update.md` as a user-facing explanation, not an internal changelog: say what you are doing now, why it matters, what changed, what uncertainty remains, and where the user should look next. Avoid raw artifact IDs, hashes, filenames, internal schema names, and implementation vocabulary unless they are necessary for a user decision.",
        "- In Full Auto progress reports, do not make approval-waiting the dominant status. If an unconfirmed decision exists, pair it with the concrete reversible work that is continuing now, and make that active work the headline.",
        "- Prefer marimo notebooks for data understanding, modeling diagnostics, and reports.",
        "- Read `.tablex/context.json` for `human_interface.response_locale` and write human-facing notebooks/reports/chat in that language.",
        "- Read equipped Skill paths in `.tablex/context.json` before EDA, prior research, notebook authoring, or modeling strategy work.",
        "- During long turns, check `.tablex/inbox/user_instructions.jsonl`, `.tablex/inbox/latest_user_instruction.md`, `.tablex/inbox/progress_request.md`, `.tablex/inbox/research_plan_contract_request.md`, `.tablex/inbox/research_plan_artifact_rejection.md`, `.tablex/inbox/research_plan_request_rejection.md`, `.tablex/inbox/notebook_request_rejection.md`, `.tablex/inbox/notebook_capture_failure.md`, and `.tablex/inbox/experiment_result_request_rejection.md`; incorporate user messages, publish progress updates, and repair rejected ResearchPlan, Notebook, or Leaderboard result request state without waiting for a new Codex turn when practical.",
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
                *CODEX_HARNESS_CONFIG_ARGS,
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
                *CODEX_HARNESS_CONFIG_ARGS,
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
            cmd[2:2] = ["--model", agent_model]
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


def process_research_plan_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    request_dir = research_plan_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = research_plan_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = loads_json(raw_text, {})
            if not isinstance(payload, dict):
                raise ValueError("ResearchPlan request must be a JSON object")
            request_id = str(payload.get("request_id") or path.stem)
            schema_version = str(payload.get("schema_version") or "")
            if schema_version != RESEARCH_PLAN_REQUEST_SCHEMA_VERSION:
                expected = RESEARCH_PLAN_REQUEST_SCHEMA_VERSION
                raise ValueError(f"Unsupported ResearchPlan request schema_version: {schema_version or '<missing>'}; expected {expected}")
            operation = str(payload.get("operation") or payload.get("tool") or "").strip()
            body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            result = execute_research_plan_tool_request(
                db,
                project=project,
                workspace=workspace,
                operation=operation,
                payload=body,
            )
            ack = {
                "schema_version": RESEARCH_PLAN_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_research_plan_tool_ack(ack_path, ack)
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="research_plan_request_succeeded",
                role="harness",
                title="ResearchPlan request processed",
                content=f"Processed ResearchPlan request `{operation}` from `{path.relative_to(workspace)}`.",
                payload=ack,
                update_heartbeat=False,
            )
            if operation == "request_human_attention":
                result_payload = result if isinstance(result, dict) else {}
                register_agent_session_attention_chat_turn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=f"research_plan_human_attention:{result_payload.get('question_id') or request_id}",
                    status="needs_attention",
                    message_kind="research_plan_human_attention_requested",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "question_id": result_payload.get("question_id"),
                        "question": body.get("question") if isinstance(body.get("question"), str) else "",
                        "why_it_matters": body.get("why_it_matters") if isinstance(body.get("why_it_matters"), str) else "",
                        "node_id": body.get("node_id") if isinstance(body.get("node_id"), str) else "",
                        "can_proceed_without_answer": result_payload.get("can_proceed_without_answer"),
                    },
                )
        except ResearchPlanValidationError as exc:
            ack = {
                "schema_version": RESEARCH_PLAN_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "issues": exc.issues,
                },
            }
            write_research_plan_tool_ack(ack_path, ack)
            write_research_plan_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc)[:1200],
                issues=exc.issues,
            )
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="research_plan_request_failed",
                role="harness",
                title="ResearchPlan request failed",
                content=str(exc),
                payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                update_heartbeat=False,
            )
            register_agent_session_attention_chat_turn(
                db,
                store=store,
                project=project,
                session=session,
                attention_key=f"research_plan_request_failed:{request_id}",
                status="needs_attention",
                message_kind="research_plan_request_failed",
                details={
                    "request_id": request_id,
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1200],
                    "issues": exc.issues[:8],
                    "workspace_relative_path": str(path.relative_to(workspace)),
                },
            )
        except Exception as exc:
            ack = {
                "schema_version": RESEARCH_PLAN_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_research_plan_tool_ack(ack_path, ack)
            write_research_plan_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc)[:1200],
                issues=None,
            )
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="research_plan_request_failed",
                role="harness",
                title="ResearchPlan request failed",
                content=str(exc),
                payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                update_heartbeat=False,
            )
            register_agent_session_attention_chat_turn(
                db,
                store=store,
                project=project,
                session=session,
                attention_key=f"research_plan_request_failed:{request_id}",
                status="needs_attention",
                message_kind="research_plan_request_failed",
                details={
                    "request_id": request_id,
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1200],
                    "workspace_relative_path": str(path.relative_to(workspace)),
                },
            )


def execute_research_plan_tool_request(
    db: Session,
    *,
    project: Project,
    workspace: Path,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if operation == "commit_revision":
        document = payload.get("document")
        if not isinstance(document, dict):
            raise ValueError("payload.document is required for commit_revision")
        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document=document,
            author_type=str(payload.get("author_type") or "codex"),
            author_id=str(payload.get("author_id")) if payload.get("author_id") is not None else None,
            reason=str(payload.get("reason") or ""),
            source_artifact_id=str(payload.get("source_artifact_id"))
            if payload.get("source_artifact_id") is not None
            else None,
            parent_revision_id=str(payload.get("parent_revision_id"))
            if payload.get("parent_revision_id") is not None
            else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            strict_validation=True,
        )
        return {
            "research_plan_id": result.plan.id,
            "revision_id": result.revision.id,
            "revision_index": result.revision.revision_index,
            "created": result.created,
        }
    if operation == "set_current_work":
        current = set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id=str(payload.get("node_id") or ""),
            summary=str(payload.get("summary") or ""),
            status=str(payload.get("status") or "active"),
            expected_outputs=[str(item) for item in payload.get("expected_outputs", [])]
            if isinstance(payload.get("expected_outputs"), list)
            else [],
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
            updated_by_type=str(payload.get("updated_by_type") or "codex"),
            updated_by=str(payload.get("updated_by")) if payload.get("updated_by") is not None else None,
        )
        return {"current_work": research_plan_current_work_payload(current)}
    if operation == "attach_artifact":
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            workspace_path = payload.get("workspace_path")
            if not isinstance(workspace_path, str) or not workspace_path.strip():
                raise ValueError("payload.artifact_id or payload.workspace_path is required for attach_artifact")
            artifact = latest_session_artifact_for_workspace_path(
                db,
                project_id=project.id,
                workspace=workspace,
                workspace_path=workspace_path,
            )
            if artifact is None:
                raise ValueError(f"No registered artifact found for workspace_path {workspace_path}")
            artifact_id = artifact.id
        edge = attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=str(payload.get("node_id") or ""),
            artifact_id=artifact_id,
            role=str(payload.get("role") or "evidence"),
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
        return {
            "link_id": edge.id,
            "artifact_id": edge.to_asset_id,
            "node_id": str(loads_json(edge.metadata_json, {}).get("node_id") or ""),
        }
    if operation == "request_human_attention":
        question = request_research_plan_human_attention(
            db,
            project_id=project.id,
            question=str(payload.get("question") or ""),
            why_it_matters=str(payload.get("why_it_matters") or ""),
            node_id=str(payload.get("node_id")) if payload.get("node_id") is not None else None,
            provisional_assumption=str(payload.get("provisional_assumption"))
            if payload.get("provisional_assumption") is not None
            else None,
            impact_if_wrong=str(payload.get("impact_if_wrong")) if payload.get("impact_if_wrong") is not None else None,
            urgency=str(payload.get("urgency") or "medium"),
            fallback_policy=str(payload.get("fallback_policy") or "infer_and_continue"),
            blocks_next_phase=bool(payload.get("blocks_next_phase") or False),
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
        )
        return {"question_id": question.id, "can_proceed_without_answer": question.can_proceed_without_answer}
    raise ValueError(f"Unsupported ResearchPlan request operation: {operation}")


def latest_session_artifact_for_workspace_path(
    db: Session,
    *,
    project_id: str,
    workspace: Path,
    workspace_path: str,
) -> Artifact | None:
    candidate = Path(workspace_path)
    if candidate.is_absolute():
        try:
            relative_path = str(candidate.relative_to(workspace))
        except ValueError:
            relative_path = str(candidate)
    else:
        relative_path = str(candidate)
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
            .limit(300)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("workspace_relative_path") == relative_path:
            return artifact
    return None


def write_research_plan_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def process_notebook_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    request_dir = notebook_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = notebook_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = loads_json(raw_text, {})
            if not isinstance(payload, dict):
                raise ValueError("Notebook request must be a JSON object")
            schema_version = str(payload.get("schema_version") or "")
            if schema_version != NOTEBOOK_REQUEST_SCHEMA_VERSION:
                raise ValueError(f"Unsupported notebook request schema_version: {schema_version or '<missing>'}")
            request_id = str(payload.get("request_id") or path.stem)
            operation = str(payload.get("operation") or "").strip()
            if operation != "capture_notebook":
                raise ValueError(f"Unsupported notebook request operation: {operation or '<missing>'}")
            body = payload.get("payload")
            if not isinstance(body, dict):
                raise ValueError("payload must be an object")
            result = execute_notebook_capture_request(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                payload=body,
            )
            ack = {
                "schema_version": NOTEBOOK_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_notebook_tool_ack(ack_path, ack)
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="notebook_request_succeeded",
                role="harness",
                title="Notebook request processed",
                content=f"Processed notebook request `{operation}` from `{path.relative_to(workspace)}`.",
                payload=ack,
                artifact_id=result.get("preview_artifact_id") or result.get("notebook_artifact_id"),
                update_heartbeat=False,
            )
        except Exception as exc:
            ack = {
                "schema_version": NOTEBOOK_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_notebook_tool_ack(ack_path, ack)
            write_notebook_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="notebook_request_failed",
                role="harness",
                title="Notebook request failed",
                content=str(exc),
                payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                update_heartbeat=False,
            )
            register_agent_session_attention_chat_turn(
                db,
                store=store,
                project=project,
                session=session,
                attention_key=f"notebook_request_failed:{request_id}",
                status="needs_attention",
                message_kind="notebook_request_failed",
                details={
                    "request_id": request_id,
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1200],
                    "workspace_relative_path": str(path.relative_to(workspace)),
                },
            )


def execute_notebook_capture_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    notebook_artifact = notebook_artifact_from_request(db, project=project, workspace=workspace, payload=payload)
    context_links = apply_notebook_request_metadata(
        db,
        project=project,
        notebook_artifact=notebook_artifact,
        payload=payload,
    )
    node_id = str(payload.get("research_plan_node_id") or "").strip() or None
    revision_id = str(payload.get("revision_id") or "").strip() or None
    if node_id:
        attach_notebook_artifacts_to_current_research_plan(
            db,
            session=session,
            notebook_artifact=notebook_artifact,
            node_id=node_id,
            revision_id=revision_id,
            strict=True,
        )
    from tabular_harness.services.analysis_notebooks import create_notebook_execution_capture

    try:
        capture = create_notebook_execution_capture(db, store=store, notebook_artifact=notebook_artifact)
    except Exception as exc:
        linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
            db,
            session=session,
            notebook_artifact=notebook_artifact,
            node_id=node_id,
            revision_id=revision_id,
            strict=False,
        )
        register_agent_session_notebook_chat_turn(
            db,
            store=store,
            session=session,
            notebook_artifact=notebook_artifact,
            status="preview_failed",
            linked_plan_node_id=linked_plan_node_id,
            error=str(exc)[:1200],
        )
        raise ValueError(f"Notebook preview capture failed: {str(exc)[:1200]}") from exc
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=notebook_artifact,
        related_artifacts=[
            (capture.evidence_html_artifact, "notebook_preview"),
            (capture.html_artifact, "notebook_html"),
            (capture.manifest_artifact, "notebook_manifest"),
        ],
        node_id=node_id,
        revision_id=revision_id,
        strict=bool(node_id),
    )
    register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=notebook_artifact,
        status="ready",
        preview_artifact=capture.evidence_html_artifact or capture.html_artifact,
        html_artifact=capture.html_artifact,
        manifest_artifact=capture.manifest_artifact,
        linked_plan_node_id=linked_plan_node_id,
    )
    return {
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_execution_html_artifact_id": getattr(capture.html_artifact, "id", None),
        "notebook_execution_manifest_artifact_id": getattr(capture.manifest_artifact, "id", None),
        "notebook_evidence_html_artifact_id": getattr(capture.evidence_html_artifact, "id", None),
        "preview_artifact_id": getattr(capture.evidence_html_artifact or capture.html_artifact, "id", None),
        "research_plan_node_id": linked_plan_node_id,
        **context_links,
    }


def notebook_artifact_from_request(
    db: Session,
    *,
    project: Project,
    workspace: Path,
    payload: dict[str, Any],
) -> Artifact:
    artifact_id = payload.get("artifact_id")
    artifact: Artifact | None = None
    if isinstance(artifact_id, str) and artifact_id.strip():
        artifact = db.get(Artifact, artifact_id.strip())
    else:
        workspace_path = payload.get("workspace_path")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise ValueError("payload.artifact_id or payload.workspace_path is required")
        artifact = latest_session_artifact_for_workspace_path(
            db,
            project_id=project.id,
            workspace=workspace,
            workspace_path=workspace_path,
        )
    if artifact is None or artifact.project_id != project.id:
        raise ValueError("Notebook artifact does not belong to this project or is not registered yet")
    if artifact.asset_type != "analysis_notebook":
        raise ValueError(f"Referenced artifact must be analysis_notebook, not {artifact.asset_type}")
    return artifact


def apply_notebook_request_metadata(
    db: Session,
    *,
    project: Project,
    notebook_artifact: Artifact,
    payload: dict[str, Any],
) -> dict[str, str | None]:
    notebook_kind = optional_text_field(payload, "notebook_kind")
    dataset_snapshot_id = optional_text_field(payload, "dataset_snapshot_id")
    run_id = optional_text_field(payload, "run_id")
    model_version_id = optional_text_field(payload, "model_version_id")
    research_plan_node_id = optional_text_field(payload, "research_plan_node_id")
    run: ExperimentRun | None = None
    model_version: ModelVersion | None = None
    dataset_snapshot: DatasetSnapshot | None = None

    if run_id:
        run = db.get(ExperimentRun, run_id)
        if run is None or run.project_id != project.id:
            raise ValueError(f"payload.run_id `{run_id}` does not belong to this project")
        if model_version_id and run.model_version_id and run.model_version_id != model_version_id:
            raise ValueError("payload.run_id and payload.model_version_id refer to different model results")
        if dataset_snapshot_id and run.dataset_snapshot_id and run.dataset_snapshot_id != dataset_snapshot_id:
            raise ValueError("payload.run_id and payload.dataset_snapshot_id refer to different datasets")
        model_version_id = model_version_id or run.model_version_id
        dataset_snapshot_id = dataset_snapshot_id or run.dataset_snapshot_id

    if model_version_id:
        model_version = db.get(ModelVersion, model_version_id)
        if model_version is None or model_version.project_id != project.id:
            raise ValueError(f"payload.model_version_id `{model_version_id}` does not belong to this project")
        if run_id and model_version.experiment_run_id != run_id:
            raise ValueError("payload.model_version_id and payload.run_id refer to different experiment runs")
        run_id = run_id or model_version.experiment_run_id
        dataset_snapshot_id = dataset_snapshot_id or model_version.dataset_snapshot_id

    if dataset_snapshot_id:
        dataset_snapshot = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset_snapshot is None or dataset_snapshot.project_id != project.id:
            raise ValueError(f"payload.dataset_snapshot_id `{dataset_snapshot_id}` does not belong to this project")
        if model_version and model_version.dataset_snapshot_id and model_version.dataset_snapshot_id != dataset_snapshot.id:
            raise ValueError("payload.model_version_id and payload.dataset_snapshot_id refer to different datasets")
        if run and run.dataset_snapshot_id and run.dataset_snapshot_id != dataset_snapshot.id:
            raise ValueError("payload.run_id and payload.dataset_snapshot_id refer to different datasets")

    updates = {
        "notebook_kind": notebook_kind,
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
        "research_plan_node_id": research_plan_node_id,
        "notebook_context_source": "tablex_notebook_request",
    }
    metadata = loads_json(notebook_artifact.metadata_json, {})
    for key, value in updates.items():
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    notebook_artifact.metadata_json = dumps_json(metadata)
    return {
        "notebook_kind": str(metadata.get("notebook_kind") or "") or None,
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
    }


def optional_text_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"payload.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def write_notebook_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


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
                try:
                    commit_research_plan_artifact_revision(
                        db,
                        artifact=artifact,
                        reason=f"Committed Codex-authored workspace ResearchPlan from {path.relative_to(workspace)}.",
                        strict_validation=True,
                    )
                except ResearchPlanValidationError as exc:
                    rejection_event = append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="research_plan_artifact_rejected",
                        role="harness",
                        title="ResearchPlan artifact rejected",
                        content=str(exc),
                        payload={
                            "artifact_id": artifact.id,
                            "workspace_relative_path": str(path.relative_to(workspace)),
                            "issues": exc.issues[:12],
                        },
                        artifact_id=artifact.id,
                        update_heartbeat=False,
                    )
                    write_research_plan_artifact_rejection_to_workspace_inbox(
                        session,
                        event=rejection_event,
                        artifact=artifact,
                        workspace_relative_path=str(path.relative_to(workspace)),
                        issues=exc.issues,
                    )
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key=f"research_plan_artifact_rejected:{artifact.id}",
                        status="needs_attention",
                        message_kind="research_plan_request_failed",
                        details={
                            "request_id": artifact.name,
                            "operation": "commit_revision",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:1200],
                            "issues": exc.issues[:8],
                            "workspace_relative_path": str(path.relative_to(workspace)),
                        },
                    )
            if allow_notebook_auto_capture:
                maybe_capture_agent_session_notebook_output(
                    db,
                    store=store,
                    session=session,
                    artifact=artifact,
                )
            else:
                maybe_defer_agent_session_notebook_capture(db, session=session, artifact=artifact)
    process_research_plan_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
    maybe_request_research_plan_contract_revision(
        db,
        store=store,
        project=project,
        session=session,
        locale=latest_project_response_locale(db, project),
    )
    process_notebook_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
    process_experiment_result_requests(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_event=append_session_event,
    )
    ingest_registered_session_experiment_artifacts(db, store=store, project=project, session=session)
    attach_registered_session_notebooks_to_current_research_plan(db, project=project, session=session)
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
    existing_success = latest_agent_session_notebook_capture_event(
        db,
        session=session,
        artifact=artifact,
        event_types=("notebook_auto_capture_succeeded",),
    )
    if existing_success is not None:
        register_agent_session_notebook_chat_turn_from_capture_event(
            db,
            store=store,
            session=session,
            notebook_artifact=artifact,
            event=existing_success,
        )
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
        if session.workspace_path:
            write_notebook_capture_failure_to_workspace_inbox(
                Path(session.workspace_path),
                notebook_artifact=artifact,
                error_message=str(exc),
            )
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
        linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
            db,
            session=session,
            notebook_artifact=artifact,
        )
        register_agent_session_notebook_chat_turn(
            db,
            store=store,
            session=session,
            notebook_artifact=artifact,
            status="preview_failed",
            linked_plan_node_id=linked_plan_node_id,
            error=str(exc)[:1200],
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
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=artifact,
        related_artifacts=[
            (capture.evidence_html_artifact, "notebook_preview"),
            (capture.html_artifact, "notebook_html"),
            (capture.manifest_artifact, "notebook_manifest"),
        ],
    )
    register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=artifact,
        status="ready",
        preview_artifact=capture.evidence_html_artifact or capture.html_artifact,
        html_artifact=capture.html_artifact,
        manifest_artifact=capture.manifest_artifact,
        linked_plan_node_id=linked_plan_node_id,
    )


def register_agent_session_notebook_chat_turn_from_capture_event(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    notebook_artifact: Artifact,
    event: AgentTranscriptEvent,
) -> Artifact | None:
    payload = loads_json(event.payload_json, {})
    preview_artifact = (
        db.get(Artifact, payload.get("notebook_evidence_html_artifact_id"))
        if isinstance(payload.get("notebook_evidence_html_artifact_id"), str)
        else None
    )
    html_artifact = (
        db.get(Artifact, payload.get("notebook_execution_html_artifact_id"))
        if isinstance(payload.get("notebook_execution_html_artifact_id"), str)
        else None
    )
    manifest_artifact = (
        db.get(Artifact, payload.get("notebook_execution_manifest_artifact_id"))
        if isinstance(payload.get("notebook_execution_manifest_artifact_id"), str)
        else None
    )
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=notebook_artifact,
        related_artifacts=[
            (preview_artifact, "notebook_preview"),
            (html_artifact, "notebook_html"),
            (manifest_artifact, "notebook_manifest"),
        ],
    )
    return register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=notebook_artifact,
        status="ready",
        preview_artifact=preview_artifact,
        html_artifact=html_artifact,
        manifest_artifact=manifest_artifact,
        linked_plan_node_id=linked_plan_node_id,
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


def attach_registered_session_notebooks_to_current_research_plan(
    db: Session,
    *,
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
        success_event = latest_agent_session_notebook_capture_event(
            db,
            session=session,
            artifact=artifact,
            event_types=("notebook_auto_capture_succeeded",),
        )
        related_artifacts: list[tuple[Artifact | None, str]] = []
        if success_event is not None:
            payload = loads_json(success_event.payload_json, {})
            related_artifacts = [
                (db.get(Artifact, payload.get("notebook_evidence_html_artifact_id")), "notebook_preview")
                if isinstance(payload.get("notebook_evidence_html_artifact_id"), str)
                else (None, "notebook_preview"),
                (db.get(Artifact, payload.get("notebook_execution_html_artifact_id")), "notebook_html")
                if isinstance(payload.get("notebook_execution_html_artifact_id"), str)
                else (None, "notebook_html"),
                (db.get(Artifact, payload.get("notebook_execution_manifest_artifact_id")), "notebook_manifest")
                if isinstance(payload.get("notebook_execution_manifest_artifact_id"), str)
                else (None, "notebook_manifest"),
            ]
        attach_notebook_artifacts_to_current_research_plan(
            db,
            session=session,
            notebook_artifact=artifact,
            related_artifacts=related_artifacts,
        )


def attach_notebook_artifacts_to_current_research_plan(
    db: Session,
    *,
    session: AgentSession,
    notebook_artifact: Artifact,
    related_artifacts: list[tuple[Any | None, str]] | None = None,
    node_id: str | None = None,
    revision_id: str | None = None,
    strict: bool = False,
) -> str | None:
    if notebook_artifact.project_id is None:
        return None
    current = latest_research_plan_current_work(db, project_id=notebook_artifact.project_id)
    target_node_id = node_id.strip() if isinstance(node_id, str) and node_id.strip() else None
    target_revision_id = revision_id.strip() if isinstance(revision_id, str) and revision_id.strip() else None
    if target_node_id is None:
        if current is None or not current.node_id.strip():
            return None
        target_node_id = current.node_id
        target_revision_id = current.revision_id
    if target_revision_id is None and current is not None and current.revision_id:
        target_revision_id = current.revision_id
    if target_revision_id is None:
        revision = latest_research_plan_revision(db, project_id=notebook_artifact.project_id)
        target_revision_id = revision.id if revision is not None else None
    artifact_roles: list[tuple[str, str]] = [(notebook_artifact.id, "notebook_source")]
    for artifact_like, role in related_artifacts or []:
        artifact_id = getattr(artifact_like, "id", None)
        if isinstance(artifact_id, str) and artifact_id.strip():
            artifact_roles.append((artifact_id, role))
    attached_any = False
    for artifact_id, role in artifact_roles:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != notebook_artifact.project_id:
            continue
        if research_plan_artifact_link_exists(
            db,
            project_id=notebook_artifact.project_id,
            node_id=target_node_id,
            artifact_id=artifact.id,
        ):
            continue
        try:
            attach_research_plan_artifact(
                db,
                project_id=notebook_artifact.project_id,
                node_id=target_node_id,
                artifact_id=artifact.id,
                role=role,
                revision_id=target_revision_id,
                metadata={
                    "agent_session_id": session.id,
                    "notebook_artifact_id": notebook_artifact.id,
                    "source": "main_agent_session_notebook_link",
                },
            )
        except ValueError:
            if strict:
                raise
            continue
        attached_any = True
    return target_node_id if attached_any or strict else None


def research_plan_artifact_link_exists(
    db: Session,
    *,
    project_id: str,
    node_id: str,
    artifact_id: str,
) -> bool:
    edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == project_id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == artifact_id,
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.desc())
            .limit(20)
        ).all()
    )
    for edge in edges:
        metadata = loads_json(edge.metadata_json, {})
        if metadata.get("node_id") == node_id:
            return True
    return False


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


def register_agent_session_notebook_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    notebook_artifact: Artifact,
    status: str,
    preview_artifact: Any | None = None,
    html_artifact: Any | None = None,
    manifest_artifact: Any | None = None,
    linked_plan_node_id: str | None = None,
    error: str | None = None,
) -> Artifact | None:
    if notebook_artifact.project_id is None:
        return None
    project = db.get(Project, notebook_artifact.project_id)
    if project is None:
        return None
    if agent_session_notebook_chat_turn_exists(
        db,
        project=project,
        session=session,
        notebook_artifact=notebook_artifact,
        status=status,
    ):
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    preview_artifact_id = getattr(preview_artifact, "id", None)
    html_artifact_id = getattr(html_artifact, "id", None)
    manifest_artifact_id = getattr(manifest_artifact, "id", None)
    artifact_ids = [
        item
        for item in [notebook_artifact.id, preview_artifact_id, html_artifact_id, manifest_artifact_id]
        if isinstance(item, str) and item.strip()
    ]
    open_artifact_id = (
        preview_artifact_id
        if isinstance(preview_artifact_id, str) and preview_artifact_id
        else html_artifact_id
        if isinstance(html_artifact_id, str) and html_artifact_id
        else notebook_artifact.id
    )
    if status == "ready":
        assistant_message = (
            "分析ノートブックを保存し、Tablex内で開けるプレビューを用意しました。"
            if japanese
            else "The analysis notebook is saved, and its in-product preview is ready."
        )
        action_status = "ready"
        action_label = "ノートブックを開く" if japanese else "Open notebook"
        action_detail = (
            "保存されたmarimo sourceと生成済みプレビューを確認できます。"
            if japanese
            else "Open the saved marimo source and rendered preview."
        )
        next_focus_label = "ノートブック" if japanese else "Notebook"
    else:
        assistant_message = (
            "分析ノートブックのソースは保存されていますが、プレビュー生成に失敗しました。ソースは確認できます。"
            if japanese
            else "The analysis notebook source is saved, but Tablex could not render the preview yet. The source is available."
        )
        action_status = "needs_attention"
        action_label = "ノートブックソースを開く" if japanese else "Open notebook source"
        action_detail = (
            "プレビュー生成は後で再試行されます。"
            if japanese
            else "Preview rendering will be retried later."
        )
        next_focus_label = "ノートブックソース" if japanese else "Notebook source"
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "notebook_artifact_update",
            "source": "main_agent_session_workspace",
            "status": status,
        },
        "actions": [
            {
                "type": "open_artifact",
                "status": action_status,
                "label": action_label,
                "target_tab": "Notebooks",
                "target_anchor": "notebook-preview-top",
                "detail": action_detail,
                "artifact_id": open_artifact_id,
                "artifact_ids": artifact_ids,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "notebook_artifact_update.v1",
            "agent_session_id": session.id,
            "notebook_artifact_id": notebook_artifact.id,
            "preview_artifact_id": preview_artifact_id,
            "html_artifact_id": html_artifact_id,
            "manifest_artifact_id": manifest_artifact_id,
            "status": status,
            "error": error,
            "research_plan_node_id": linked_plan_node_id,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": "Notebooks", "target_anchor": "notebook-preview-top", "label": next_focus_label},
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_notebook_update_{session.id}_{notebook_artifact.id}_{status}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source_artifact_id": notebook_artifact.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_status": status,
            "source": "main_agent_session_notebook_update",
        },
    )
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_chat_turn_registered",
        role="harness",
        title="Notebook chat turn registered",
        content="Registered notebook availability in Agent Chat.",
        payload={
            "chat_artifact_id": chat_artifact.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_status": status,
            "preview_artifact_id": preview_artifact_id,
        },
        artifact_id=chat_artifact.id,
        update_heartbeat=False,
    )
    return chat_artifact


def agent_session_notebook_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    notebook_artifact: Artifact,
    status: str,
) -> bool:
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(100)
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_notebook_update"
            and metadata.get("agent_session_id") == session.id
            and metadata.get("notebook_artifact_id") == notebook_artifact.id
            and metadata.get("notebook_status") == status
        ):
            return True
    return False


def register_agent_session_attention_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    attention_key: str,
    status: str,
    message_kind: str,
    details: dict[str, Any] | None = None,
) -> Artifact | None:
    cleaned_key = attention_key.strip()[:240]
    if not cleaned_key:
        return None
    if agent_session_attention_chat_turn_exists(db, project=project, session=session, attention_key=cleaned_key):
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    details = details or {}
    assistant_message = attention_chat_message(message_kind, details=details, japanese=japanese)
    target_tab, target_anchor, action_label = attention_chat_action_target(message_kind, japanese=japanese)
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "agent_attention_event",
            "source": "main_agent_session_observation",
            "status": status,
            "message_kind": message_kind,
        },
        "actions": [
            {
                "type": "open_surface",
                "status": status,
                "label": action_label,
                "target_tab": target_tab,
                "target_anchor": target_anchor,
                "detail": assistant_message,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_attention_event.v1",
            "agent_session_id": session.id,
            "attention_key": cleaned_key,
            "status": status,
            "message_kind": message_kind,
            "details": details,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": target_tab, "target_anchor": target_anchor, "label": action_label},
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_attention_{session.id}_{hashlib.sha1(cleaned_key.encode('utf-8')).hexdigest()[:12]}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "attention_key": cleaned_key,
            "message_kind": message_kind,
            "source": "main_agent_session_attention",
        },
    )
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="attention_chat_turn_registered",
        role="harness",
        title="Attention event registered in Chat",
        content="Registered an agent attention event in Agent Chat.",
        payload={"chat_artifact_id": chat_artifact.id, "attention_key": cleaned_key, "message_kind": message_kind},
        artifact_id=chat_artifact.id,
        update_heartbeat=False,
    )
    return chat_artifact


def attention_chat_action_target(message_kind: str, *, japanese: bool) -> tuple[str, str, str]:
    if message_kind in {"runner_unavailable", "turn_recovery"}:
        return "Jobs", "agent-workspace", "状況を見る" if japanese else "Review status"
    if message_kind == "research_plan_human_attention_requested":
        return "Assumptions", "assumption-review", "質問を確認" if japanese else "Review question"
    return "Home", "agent-workspace", "状況を見る" if japanese else "Review status"


def attention_chat_message(message_kind: str, *, details: dict[str, Any], japanese: bool) -> str:
    retry_delay = details.get("retry_delay_seconds")
    retry_text = f"{int(retry_delay)}s" if isinstance(retry_delay, (int, float)) else None
    if message_kind == "runner_unavailable":
        if japanese:
            return f"Codex runnerをまだ起動できません。Tablexは同じセッションを保持し、{retry_text or 'しばらく後'}に再試行します。"
        return f"Codex runner is not available yet. Tablex is keeping the same session and will retry in {retry_text or 'a moment'}."
    if message_kind == "turn_recovery":
        exit_code = details.get("exit_code")
        if japanese:
            return f"Codex turnが終了コード{exit_code}で戻りました。Full Autoは維持され、{retry_text or 'しばらく後'}に同じセッションを再開します。"
        return f"Codex returned exit code {exit_code}. Full Auto is still on, and Tablex will resume the same session in {retry_text or 'a moment'}."
    if message_kind == "research_plan_request_failed":
        operation = str(details.get("operation") or "ResearchPlan update")
        if japanese:
            return f"ResearchPlanの更新要求 `{operation}` を保存できませんでした。Codexにはackで理由を返しているため、修正した要求を出し直せます。"
        return f"ResearchPlan update `{operation}` could not be saved. The ack includes the reason so Codex can submit a corrected request."
    if message_kind == "research_plan_human_attention_requested":
        question = str(details.get("question") or "").strip()
        can_proceed = details.get("can_proceed_without_answer")
        if japanese:
            suffix = (
                "回答がなくても仮定を置いて進めます。"
                if can_proceed is True
                else "この確認は次の判断に影響します。"
            )
            return f"Codexから確認したい点があります。{question} {suffix}".strip()
        suffix = (
            "If no answer arrives, Codex can continue with an explicit assumption."
            if can_proceed is True
            else "This answer affects the next decision."
        )
        return f"Codex has a question for you. {question} {suffix}".strip()
    if message_kind == "research_plan_contract_needs_revision":
        if japanese:
            return (
                "Research Planの表示台帳を整理し直しています。現在の計画は細かい作業がトップレベルに出すぎているため、"
                "Codexに章立てへまとめ直し、NotebookやLeaderboardへのリンクを付け直すよう渡しました。"
            )
        return (
            "Tablex is asking Codex to tidy the Research Plan ledger. The current plan is too fine-grained at the top level, "
            "so Codex should re-commit it as chapter-level work with notebook and leaderboard links attached."
        )
    if message_kind == "notebook_request_failed":
        if japanese:
            return "Notebookの登録またはプレビュー生成に失敗しました。Codexにはackで理由を返しているため、Notebookを修正して再提出できます。"
        return "Notebook registration or preview rendering failed. The ack includes the reason so Codex can repair and resubmit the notebook."
    return "Agent attention is needed." if not japanese else "Agentの状態確認が必要です。"


def agent_session_attention_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    attention_key: str,
) -> bool:
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(100)
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_attention"
            and metadata.get("agent_session_id") == session.id
            and metadata.get("attention_key") == attention_key
        ):
            return True
    return False


NOTEBOOK_EVIDENCE_ASSET_TYPES = {
    "analysis_notebook",
    "notebook_evidence_html",
    "notebook_execution_html",
    "notebook_static_html",
}
READABLE_NOTEBOOK_PREVIEW_ASSET_TYPES = (
    "notebook_evidence_html",
    "notebook_execution_html",
    "notebook_static_html",
)
REPORT_EVIDENCE_ASSET_TYPES = {
    "agent_session_report",
    "notebook_execution_report",
    "understanding_report",
    "experiment_report",
    "report",
}


def chat_update_actions_from_research_plan_evidence(
    db: Session,
    *,
    project: Project,
    japanese: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    revision = latest_research_plan_revision(db, project_id=project.id)
    if revision is None:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}
    document = research_plan_revision_document(revision)
    raw_blocks = document.get("timeline_blocks") if isinstance(document, dict) else None
    links = research_plan_evidence_links(db, revision=revision, raw_blocks=raw_blocks)
    if not links:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}

    notebook_link = first_evidence_link(links, link_types={"artifact"}, asset_types=NOTEBOOK_EVIDENCE_ASSET_TYPES)
    run_link = first_evidence_link(links, link_types={"experiment_run"})
    report_link = first_evidence_link(links, link_types={"artifact"}, asset_types=REPORT_EVIDENCE_ASSET_TYPES)

    actions: list[dict[str, Any]] = []
    if notebook_link is not None:
        artifact_id = notebook_link.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            action_artifact_id, action_artifact_ids, action_detail = notebook_action_artifact_targets(
                db,
                project_id=project.id,
                evidence_artifact_id=artifact_id,
                fallback_detail=evidence_link_detail(notebook_link),
            )
            actions.append(
                {
                    "type": "open_artifact",
                    "status": "ready",
                    "label": "ノートブックを開く" if japanese else "Open notebook",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-preview-top",
                    "detail": action_detail,
                    "artifact_id": action_artifact_id,
                    "artifact_ids": action_artifact_ids,
                    "research_plan_node_id": notebook_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if run_link is not None:
        run_id = run_link.get("run_id")
        if isinstance(run_id, str) and run_id:
            actions.append(
                {
                    "type": "open_surface",
                    "status": "ready",
                    "label": "リーダーボードを見る" if japanese else "Open leaderboard",
                    "target_tab": "Leaderboard",
                    "target_anchor": "result-readout",
                    "detail": evidence_link_detail(run_link),
                    "entity_ids": [run_id],
                    "run_id": run_id,
                    "research_plan_node_id": run_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if report_link is not None:
        artifact_id = report_link.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            actions.append(
                {
                    "type": "open_artifact",
                    "status": "ready",
                    "label": "レポートを開く" if japanese else "Open report",
                    "target_tab": "Assets",
                    "target_anchor": "assets-library",
                    "detail": evidence_link_detail(report_link),
                    "artifact_id": artifact_id,
                    "artifact_ids": [artifact_id],
                    "research_plan_node_id": report_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if not actions:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}
    first = actions[0]
    next_focus = {
        "target_tab": first.get("target_tab") or "Home",
        "target_anchor": first.get("target_anchor") or "agent-workspace",
        "label": first.get("label") or ("Agent workspace"),
    }
    return actions, next_focus


def notebook_action_artifact_targets(
    db: Session,
    *,
    project_id: str,
    evidence_artifact_id: str,
    fallback_detail: str,
) -> tuple[str, list[str], str]:
    evidence_artifact = db.get(Artifact, evidence_artifact_id)
    if evidence_artifact is None or evidence_artifact.project_id != project_id:
        return evidence_artifact_id, [evidence_artifact_id], fallback_detail

    evidence_metadata = loads_json(evidence_artifact.metadata_json, {})
    source_notebook_id = evidence_metadata.get("notebook_artifact_id")
    if evidence_artifact.asset_type in READABLE_NOTEBOOK_PREVIEW_ASSET_TYPES:
        artifact_ids = [evidence_artifact.id]
        if isinstance(source_notebook_id, str) and source_notebook_id.strip():
            artifact_ids.insert(0, source_notebook_id.strip())
        return evidence_artifact.id, dedupe_preserve_order(artifact_ids), evidence_artifact.name

    if evidence_artifact.asset_type == "analysis_notebook":
        preview_artifact = latest_readable_notebook_preview_artifact(
            db,
            project_id=project_id,
            notebook_artifact_id=evidence_artifact.id,
        )
        if preview_artifact is not None:
            return (
                preview_artifact.id,
                dedupe_preserve_order([evidence_artifact.id, preview_artifact.id]),
                preview_artifact.name,
            )

    return evidence_artifact.id, [evidence_artifact.id], evidence_artifact.name or fallback_detail


def latest_readable_notebook_preview_artifact(
    db: Session,
    *,
    project_id: str,
    notebook_artifact_id: str,
) -> Artifact | None:
    for asset_type in READABLE_NOTEBOOK_PREVIEW_ASSET_TYPES:
        candidates = list(
            db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
                .order_by(Artifact.created_at.desc())
                .limit(50)
            ).all()
        )
        for artifact in candidates:
            metadata = loads_json(artifact.metadata_json, {})
            if metadata.get("notebook_artifact_id") == notebook_artifact_id:
                return artifact
    return None


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def first_evidence_link(
    links: list[dict[str, Any]],
    *,
    link_types: set[str],
    asset_types: set[str] | None = None,
) -> dict[str, Any] | None:
    for link in reversed(links):
        link_type = link.get("link_type")
        if not isinstance(link_type, str) or link_type not in link_types:
            continue
        if asset_types is not None:
            asset_type = link.get("asset_type")
            if not isinstance(asset_type, str) or asset_type not in asset_types:
                continue
        return link
    return None


def evidence_link_detail(link: dict[str, Any]) -> str:
    for key in ("artifact_name", "role", "run_id", "artifact_id"):
        value = link.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "ResearchPlan evidence"


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
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    actions, next_focus = chat_update_actions_from_research_plan_evidence(db, project=project, japanese=japanese)
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
        "actions": actions,
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_progress_report_brief.v1",
            "agent_session_id": session.id,
            "source_artifact_id": artifact.id,
            "workspace_relative_path": str(path.relative_to(Path(session.workspace_path or path.parent))),
            "linked_action_count": len(actions),
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session",
            "status": "codex_authored",
        },
        "worker_events": [],
        "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
        "next_focus": next_focus,
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
