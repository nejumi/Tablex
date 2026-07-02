from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
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
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    next_artifact_version,
    register_artifact,
)

MAIN_AUTONOMOUS_SESSION_TYPE = "main_autonomous"
ACTIVE_SESSION_STATUSES = {"starting", "running", "between_turns", "waiting_for_runner"}
TERMINAL_SESSION_STATUSES = {"stopped", "failed", "gave_up", "completed"}


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
        title="Main AgentSession created",
        content="Full Auto now runs through a long-lived AgentSession. Jobs are sidecars, not the main Codex thread.",
        payload={"project_id": project.id, "runner_kind": runner_kind, "autonomy_mode": autonomy_mode},
    )
    return session


def session_workspace_path(store: LocalArtifactStore, project_id: str, session_id: str) -> Path:
    return store.root / "agent_sessions" / project_id / session_id


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


def run_main_agent_session_supervisor(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    session_id: str,
    agent_model: str | None = None,
    max_turns: int = 100_000,
    turn_timeout_seconds: int = 1800,
) -> None:
    for _ in range(max_turns):
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
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
                    title="Main AgentSession stopped",
                    content="The project is no longer in Full Auto, so Tablex stopped supervising the main Codex session.",
                    payload={"project_phase": project.current_phase if project else None},
                )
                db.commit()
                return
            workspace = prepare_session_workspace(db, store=store, project=project, session=session)
            prompt = build_turn_prompt(db, project=project, session=session)
            session.status = "running"
            session.started_at = session.started_at or utc_now()
            session.updated_at = utc_now()
            session.last_heartbeat_at = utc_now()
            db.commit()

        exit_code = run_codex_cli_turn_streaming(
            session_factory,
            project_id=project_id,
            session_id=session_id,
            workspace=workspace,
            prompt=prompt,
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
                db.commit()
                time.sleep(10)
                continue
            if exit_code != 0:
                session.status = "between_turns"
                session.pid = None
                session.last_error = f"Codex turn exited with code {exit_code}; supervisor will continue the same AgentSession."
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="turn_recovery_scheduled",
                    role="harness",
                    title="Codex turn returned non-zero; continuing session",
                    content="Full Auto remains on, so Tablex will resume the same AgentSession instead of leaving the project stopped.",
                    payload={"exit_code": exit_code},
                )
                db.commit()
                time.sleep(5)
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
            "progress": "Explain progress naturally in Codex messages. Tablex stores the raw transcript and Chat explains it to humans.",
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


def build_turn_prompt(db: Session, *, project: Project, session: AgentSession) -> str:
    recent_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(AgentTranscriptEvent.session_id == session.id)
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(40)
        ).all()
    )
    user_instructions = [
        event.content
        for event in reversed(recent_events)
        if event.source == "user" and event.content
    ]
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
        "- Prefer marimo notebooks for data understanding, modeling diagnostics, and reports.",
        "- Read `.tablex/context.json` for `human_interface.response_locale` and write human-facing notebooks/reports/chat in that language.",
        "- Read equipped Skill paths in `.tablex/context.json` before EDA, prior research, notebook authoring, or modeling strategy work.",
        "- If you need user input in Full Auto, state the question and your provisional assumption, then continue unless impossible.",
        "- Use Give Up only as a last resort; if you give up, explain exactly what is missing and preserve partial work.",
        "",
        "Goal:",
        session.goal_text,
        "",
        "Project context is available at `.tablex/context.json`.",
    ]
    if user_instructions:
        lines.extend(["", "Recent user instructions to incorporate:"])
        lines.extend([f"- {item}" for item in user_instructions[-10:]])
    return "\n".join(lines).strip() + "\n"


def run_codex_cli_turn_streaming(
    session_factory: sessionmaker[Session],
    *,
    project_id: str,
    session_id: str,
    workspace: Path,
    prompt: str,
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
            insert_at = 3 if session.codex_thread_id else 2
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

    line_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    start = time.monotonic()

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
        if time.monotonic() - start > timeout_seconds and process.poll() is None:
            process.terminate()
            append_process_timeout_event(session_factory, session_id=session_id, timeout_seconds=timeout_seconds)
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
        append_codex_stream_line(session_factory, project_id=project_id, session_id=session_id, stream_name=stream_name, line=line)
    return_code = process.wait(timeout=5)
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
            content="The current Codex CLI process exceeded the per-turn timeout. The AgentSession supervisor will continue if Full Auto remains on.",
            payload={"timeout_seconds": timeout_seconds},
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
            if path.name.startswith(".") or path.name == "artifact_manifest.json":
                continue
            metadata = {
                "project_id": project.id,
                "agent_session_id": session.id,
                "workspace_relative_path": str(path.relative_to(workspace)),
                "source": "main_agent_session_workspace",
            }
            name = f"agent_session_{session.id}_{path.stem}".replace(".", "_")[:180]
            asset_type = asset_type_for_session_output(path)
            existing = db.scalar(
                select(Artifact).where(
                    Artifact.project_id == project.id,
                    Artifact.asset_type == asset_type,
                    Artifact.name == name,
                )
            )
            if existing is not None:
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


def asset_type_for_session_output(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        return "marimo_notebook"
    if suffix in {".md", ".html"}:
        return "agent_session_report"
    if suffix == ".json":
        return "agent_session_artifact"
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
        return "agent_session_figure"
    return "agent_session_output"


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
