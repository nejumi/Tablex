from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, AgentTranscriptEvent, utc_now
from tabular_harness.services.agent_workspace import (
    CODEX_RAW_TRANSCRIPT_FILENAME,
    CODEX_STDERR_LOG_FILENAME,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
)

_TRANSCRIPT_EVENT_LOCK = threading.Lock()
_TRANSCRIPT_EVENT_NEXT_INDEX: dict[str, int] = {}


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


def codex_jsonl_event_type(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""
    value = payload.get("type") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else ""


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

