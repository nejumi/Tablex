from __future__ import annotations

import subprocess
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, Job, Project, utc_now
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    artifact_to_dict,
)


def build_portal_overview(db: Session) -> dict[str, Any]:
    projects = list(db.scalars(select(Project).order_by(Project.updated_at.desc())).all())
    recent_jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc()).limit(12)).all())
    recent_artifacts = list(db.scalars(select(Artifact).order_by(Artifact.created_at.desc()).limit(12)).all())
    recent_ideas = list_portal_ideas(db, limit=8)
    active_jobs = [job for job in recent_jobs if job.status in {"queued", "running", "approval_required"}]
    project_names = {project.id: project.name for project in projects}
    activity = [
        event
        for job in recent_jobs
        for event in worker_events_from_job(job, project_name=project_names.get(job.project_id or ""))
    ][:12]
    project_rows = [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "current_phase": project.current_phase,
            "updated_at": project.updated_at.isoformat(),
        }
        for project in projects[:12]
    ]
    return {
        "schema_version": "portal_overview.v1",
        "generated_at": utc_now().isoformat(),
        "summary": {
            "project_count": len(projects),
            "active_project_count": len([project for project in projects if project.status != "archived"]),
            "job_count": int(db.scalar(select(func.count()).select_from(Job)) or 0),
            "artifact_count": int(db.scalar(select(func.count()).select_from(Artifact)) or 0),
            "active_worker_count": len(active_jobs),
            "idea_count": len(recent_ideas),
        },
        "projects": project_rows,
        "recent_updates": build_recent_updates(projects, recent_jobs, recent_artifacts),
        "agent_activity": activity,
        "ideas": recent_ideas,
    }


def create_portal_idea(db: Session, *, store: LocalArtifactStore, text: str) -> dict[str, Any]:
    payload = {
        "schema_version": "portal_idea.v1",
        "text": text.strip(),
        "status": "open",
        "source": "portal_inbox",
        "created_at": utc_now().isoformat(),
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="portal_idea",
        name="portal_idea",
        filename="portal_idea.json",
        payload=payload,
        metadata={
            "scope": "cross_project",
            "status": payload["status"],
            "source": payload["source"],
        },
    )
    return portal_idea_from_artifact(artifact)


def list_portal_ideas(db: Session, *, limit: int = 40) -> list[dict[str, Any]]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id.is_(None), Artifact.asset_type == "portal_idea")
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    return [portal_idea_from_artifact(artifact) for artifact in artifacts]


def portal_idea_from_artifact(artifact: Artifact) -> dict[str, Any]:
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    return {
        "id": artifact.id,
        "artifact_id": artifact.id,
        "text": str(payload.get("text") or ""),
        "status": str(payload.get("status") or "open"),
        "source": str(payload.get("source") or "portal_inbox"),
        "created_at": str(payload.get("created_at") or artifact.created_at.isoformat()),
    }


NOISY_PORTAL_ARTIFACT_TYPES = {
    "agent_chat_turn",
}


def build_recent_updates(projects: list[Project], jobs: list[Job], artifacts: list[Artifact]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    project_names = {project.id: project.name for project in projects}
    for project in projects[:8]:
        updates.append(
            {
                "type": "project",
                "project_id": project.id,
                "title": project.name,
                "summary": f"Project is in {project.current_phase.replace('_', ' ').lower()}",
                "created_at": project.updated_at.isoformat(),
                "target_tab": "Overview",
            }
        )
    for job in jobs[:6]:
        project_name = project_names.get(job.project_id or "", "Project")
        updates.append(
            {
                "type": "job",
                "project_id": job.project_id,
                "title": portal_job_title(job.job_type),
                "summary": f"{job.status.replace('_', ' ')} · {project_name}",
                "created_at": job.created_at.isoformat(),
                "target_tab": target_tab_for_job(job.job_type),
                "lineage_ref": job.id,
            }
        )
    for artifact in artifacts[:6]:
        if artifact.asset_type in NOISY_PORTAL_ARTIFACT_TYPES:
            continue
        project_name = project_names.get(artifact.project_id or "", "Cross-project library")
        updates.append(
            {
                "type": "artifact",
                "project_id": artifact.project_id,
                "title": portal_artifact_title(artifact.asset_type),
                "summary": project_name,
                "created_at": artifact.created_at.isoformat(),
                "target_tab": target_tab_for_artifact(artifact.asset_type),
                "artifact": artifact_to_dict(artifact),
                "lineage_ref": artifact.id,
            }
        )
    return sorted(updates, key=lambda item: str(item["created_at"]), reverse=True)[:12]


def portal_job_title(job_type: str) -> str:
    labels = {
        "agent_chat_turn": "Agent chat handled a request",
        "generate_decision_report": "Decision report generated",
        "save_autonomous_decision_brief": "Decision brief saved",
        "save_guided_journey_snapshot": "Guidance snapshot saved",
        "compare_guided_journey_snapshots": "Guidance snapshots compared",
        "run_eda_review": "Data review completed",
        "profile_dataset": "Dataset profile updated",
        "run_agent_task": "Agent task recorded",
        "train_model_candidates": "Model candidates trained",
    }
    return labels.get(job_type, humanize_identifier(job_type))


def portal_artifact_title(asset_type: str) -> str:
    labels = {
        "decision_report": "Decision report saved",
        "decision_report_bundle": "Decision report bundle saved",
        "eda_review_html": "Data review report saved",
        "eda_review_bundle": "Data review evidence saved",
        "analysis_notebook": "Analysis notebook saved",
        "notebook_html": "Notebook preview saved",
        "agent_task_contract": "Agent task handoff saved",
        "autonomous_decision_brief": "Decision brief saved",
        "autonomous_decision_brief_report": "Decision brief report saved",
        "guided_journey_report": "Guidance report saved",
        "guided_journey_snapshot": "Guidance snapshot saved",
    }
    return labels.get(asset_type, f"{humanize_identifier(asset_type)} saved")


def humanize_identifier(value: str) -> str:
    words = [word for word in value.replace("-", "_").split("_") if word]
    if not words:
        return "Workbench update"
    return " ".join(word.capitalize() for word in words)


def worker_events_from_job(
    job: Job,
    *,
    project_name: str | None = None,
    active_job_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    output = loads_json(job.output_json, {})
    context = loads_json(job.context_json, {})
    events = output.get("worker_events")
    if isinstance(events, list):
        return [
            normalize_worker_event(event, job, project_name=project_name, active_job_ids=active_job_ids)
            for event in events
            if isinstance(event, dict)
        ]
    if not is_agentish_job(job.job_type):
        return []
    description = human_description_for_job(job, output=output, context=context, project_name=project_name)
    return [
        {
            "worker_id": f"job-{job.job_type}",
            "display_name": worker_display_name(job.job_type),
            "status": job.status,
            "headline": description["title"],
            "detail": job.error_message or description["summary"],
            "job_id": job.id,
            "job_type": job.job_type,
            "project_id": job.project_id,
            "project_name": project_name,
            "target_tab": target_tab_for_job(job.job_type),
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "run_after": job.run_after.isoformat() if job.run_after else None,
            "active": job_active_for_activity(job, active_job_ids=active_job_ids),
            "human_description": description,
            "token_usage": output.get("token_usage") if isinstance(output.get("token_usage"), dict) else estimated_tokens(job),
        }
    ]


def normalize_worker_event(
    event: dict[str, Any],
    job: Job,
    *,
    project_name: str | None = None,
    active_job_ids: set[str] | None = None,
) -> dict[str, Any]:
    token_usage = event.get("token_usage")
    output = loads_json(job.output_json, {})
    context = loads_json(job.context_json, {})
    description = human_description_for_job(job, output=output, context=context, project_name=project_name)
    event_status = str(event.get("status") or job.status)
    status = job.status if job.status in {"running", "succeeded", "failed", "cancelled", "approval_required"} else event_status
    event_started_at = event.get("started_at")
    started_at = str(event_started_at) if isinstance(event_started_at, str) else job.started_at.isoformat() if job.started_at else None
    return {
        "worker_id": str(event.get("worker_id") or f"job-{job.job_type}"),
        "display_name": str(event.get("display_name") or worker_display_name(job.job_type)),
        "status": status,
        "headline": str(event.get("headline") or description["title"]),
        "detail": str(event.get("detail") or job.error_message or description["summary"]),
        "job_id": str(event.get("job_id") or job.id),
        "job_type": job.job_type,
        "project_id": job.project_id,
        "project_name": project_name,
        "target_tab": event.get("target_tab") if isinstance(event.get("target_tab"), str) else target_tab_for_job(job.job_type),
        "created_at": str(event.get("created_at") or job.created_at.isoformat()),
        "updated_at": job.updated_at.isoformat(),
        "started_at": started_at,
        "run_after": job.run_after.isoformat() if job.run_after else None,
        "active": job_active_for_activity(job, active_job_ids=active_job_ids),
        "human_description": event.get("human_description") if isinstance(event.get("human_description"), dict) else description,
        "token_usage": token_usage if isinstance(token_usage, dict) else estimated_tokens(job),
    }


def estimated_tokens(job: Job) -> dict[str, Any]:
    base = max(24, len(job.job_type) * 3)
    return {
        "source": "estimated_waiting_for_worker" if job.status == "queued" else "estimated_until_runner_telemetry",
        "is_estimate": True,
        "series": [
            {"step": "queued", "tokens": base},
            {"step": "context", "tokens": base * 3},
            {"step": job.status, "tokens": base * (4 if job.status == "running" else 3)},
        ],
    }


def active_job_ids_for_activity(jobs: list[Job]) -> set[str]:
    return {job.id for job in jobs if job_active_for_activity(job)}


def build_project_turn_state(
    project: Project,
    jobs: list[Job],
    workers: list[dict[str, Any]],
    *,
    active_job_ids: set[str],
) -> dict[str, Any]:
    observed_at = utc_now()
    active_workers = [worker for worker in workers if worker.get("active")]
    approval_workers = [worker for worker in workers if worker.get("status") == "approval_required"]
    running_jobs = [job for job in jobs if job.status == "running"]
    queued_jobs = [job for job in jobs if job.status == "queued"]
    active_jobs = [job for job in jobs if job.id in active_job_ids]
    codex_processes = running_codex_processes_for_project(project.id)
    running_codex_jobs = [job for job in running_jobs if job.job_type == "run_planned_agent_task_codex"]
    stale_codex_jobs = [
        job
        for job in running_codex_jobs
        if not codex_processes and seconds_since(job.updated_at, observed_at) >= 45
    ]
    future_jobs = [job for job in queued_jobs if job.run_after and normalize_dt(job.run_after) > observed_at]
    due_queued_jobs = [job for job in queued_jobs if job.run_after is None or normalize_dt(job.run_after) <= observed_at]

    base = {
        "schema_version": "turn_state.v1",
        "project_id": project.id,
        "observed_at": observed_at.isoformat(),
        "sources": ["metadata_db.jobs", "agent_activity.workers", "local_process_table.codex_exec"],
        "active_count": len(active_workers),
        "active_job_ids": [str(worker.get("job_id")) for worker in active_workers if worker.get("job_id")],
        "active_codex_process_count": len(codex_processes),
        "codex_processes": codex_processes[:3],
    }

    if approval_workers:
        worker = approval_workers[0]
        return {
            **base,
            "state": "waiting_for_user",
            "owner": "user",
            "label": "Waiting for your approval",
            "detail": str(worker.get("detail") or worker.get("headline") or "Codex is paused at an approval boundary."),
            "input_attention": True,
            "confidence": "observed",
            "active_job_id": worker.get("job_id"),
            "active_job_type": worker.get("job_type"),
        }
    if stale_codex_jobs:
        job = stale_codex_jobs[0]
        return {
            **base,
            "state": "stale_runner",
            "owner": "system",
            "label": "Runner state needs attention",
            "detail": "A Codex job is marked running, but no local codex exec process is observed for this project.",
            "input_attention": False,
            "confidence": "observed",
            "active_job_id": job.id,
            "active_job_type": job.job_type,
            "last_job_update_at": job.updated_at.isoformat(),
        }
    if codex_processes or active_workers or any(job.status == "running" for job in active_jobs):
        worker = active_workers[0] if active_workers else None
        job = active_jobs[0] if active_jobs else (running_jobs[0] if running_jobs else None)
        return {
            **base,
            "state": "agent_running",
            "owner": "agent",
            "label": "Codex is working",
            "detail": str(worker.get("detail") if worker else "A Tablex worker or Codex process is active."),
            "input_attention": False,
            "confidence": "observed",
            "active_job_id": worker.get("job_id") if worker else job.id if job else None,
            "active_job_type": worker.get("job_type") if worker else job.job_type if job else None,
        }
    if due_queued_jobs:
        job = due_queued_jobs[0]
        return {
            **base,
            "state": "worker_pending",
            "owner": "system",
            "label": "Waiting for a local worker",
            "detail": "A job is queued and due, but no worker has locked it yet.",
            "input_attention": False,
            "confidence": "observed",
            "active_job_id": job.id,
            "active_job_type": job.job_type,
        }
    if project.current_phase == "AUTONOMOUS_LOOP" and future_jobs:
        job = future_jobs[0]
        return {
            **base,
            "state": "agent_scheduled",
            "owner": "agent",
            "label": "Codex will resume automatically",
            "detail": "Full Auto is between turns; the next heartbeat is scheduled.",
            "input_attention": False,
            "confidence": "observed",
            "active_job_id": job.id,
            "active_job_type": job.job_type,
            "next_run_after": job.run_after.isoformat() if job.run_after else None,
        }
    if project.current_phase == "AUTONOMOUS_LOOP":
        return {
            **base,
            "state": "needs_attention",
            "owner": "system",
            "label": "No live agent turn observed",
            "detail": "Full Auto is on, but no active Codex process, worker, approval, or scheduled heartbeat is currently observed.",
            "input_attention": False,
            "confidence": "observed",
        }
    return {
        **base,
        "state": "waiting_for_user",
        "owner": "user",
        "label": "Waiting for you",
        "detail": "Codex is not running for this project. Send a message or press Start when ready.",
        "input_attention": True,
        "confidence": "observed",
    }


def job_active_for_activity(job: Job, *, active_job_ids: set[str] | None = None) -> bool:
    waiting_child_ids = heartbeat_waiting_child_ids(job)
    if waiting_child_ids and (active_job_ids is None or any(child_id in active_job_ids for child_id in waiting_child_ids)):
        return False
    if job.status in {"running", "approval_required"}:
        return True
    if job.status == "queued":
        run_after = job.run_after
        if run_after is not None:
            if run_after.tzinfo is None:
                run_after = run_after.replace(tzinfo=timezone.utc)
            if run_after > utc_now():
                return False
        created_at = job.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return utc_now() - created_at < timedelta(minutes=30)
    return False


def running_codex_processes_for_project(project_id: str) -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            text=True,
            capture_output=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    marker = f"/{project_id}/"
    processes: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if "codex exec" not in stripped or marker not in stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        processes.append({"pid": pid, "command": compact_command(command)})
    return processes


def compact_command(command: str, limit: int = 240) -> str:
    return command if len(command) <= limit else command[: limit - 14] + " ...[truncated]"


def normalize_dt(value: Any) -> Any:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def seconds_since(value: Any, now: Any) -> float:
    return max(0.0, (now - normalize_dt(value)).total_seconds())


def heartbeat_waiting_child_ids(job: Job) -> list[str]:
    if job.job_type != "continue_autonomous_session":
        return []
    payload = loads_json(job.input_json, {})
    child_ids = payload.get("active_child_job_ids_at_schedule_time")
    if not isinstance(child_ids, list):
        child_ids = payload.get("active_child_job_ids")
    if not isinstance(child_ids, list):
        return []
    return [str(child_id) for child_id in child_ids if isinstance(child_id, str) and child_id]


def human_description_for_job(
    job: Job,
    *,
    output: dict[str, Any],
    context: dict[str, Any],
    project_name: str | None,
) -> dict[str, str]:
    description = output.get("human_description")
    if not isinstance(description, dict):
        description = context.get("human_description")
    if isinstance(description, dict):
        title = str(description.get("title") or humanize_identifier(job.job_type))
        summary = str(description.get("summary") or description.get("detail") or title)
        source = str(description.get("source") or "job_context")
        return {"title": title, "summary": summary, "source": source}

    project_label = project_name or "this project"
    default_description = default_human_description_for_job(job, project_label=project_label)
    if default_description:
        return default_description

    title = str(output.get("assistant_message") or f"{humanize_identifier(job.job_type)} is {job.status}")
    if job.status == "queued":
        summary = (
            f"Waiting for a local worker to pick up {job.id} for {project_label}. "
            "No live token telemetry is available until the worker starts running."
        )
    elif job.status == "running":
        summary = f"Running {job.id} for {project_label}."
    elif job.status == "approval_required":
        summary = f"Waiting for approval before {job.id} can run for {project_label}."
    else:
        summary = job.error_message or f"{job.id} is {job.status} for {project_label}."
    return {"title": title, "summary": summary, "source": "job_status_fallback"}


def default_human_description_for_job(job: Job, *, project_label: str) -> dict[str, str] | None:
    waiting = "Waiting for a local worker to pick it up. " if job.status == "queued" else ""
    if job.job_type == "run_baseline":
        return {
            "title": "Train the adaptive baseline",
            "summary": (
                f"{waiting}Use the approved evaluation design for {project_label}, train the current adaptive "
                "tabular baseline, and publish comparable run evidence for the Leaderboard."
            ),
            "source": "job_type_default",
        }
    if job.job_type == "train_model_candidates":
        return {
            "title": "Train candidate models",
            "summary": (
                f"{waiting}Train the candidate model set for {project_label} on the same split and metric surface "
                "so the Leaderboard can compare runs fairly."
            ),
            "source": "job_type_default",
        }
    if job.job_type == "run_planned_agent_task_codex":
        return {
            "title": "Run Codex on the prepared agent task",
            "summary": (
                f"{waiting}Execute the prepared AgentTaskContract for {project_label}, then return artifacts, "
                "findings, and next recommendations to the harness."
            ),
            "source": "job_type_default",
        }
    if job.job_type == "build_split_manifest":
        return {
            "title": "Build the SplitManifest",
            "summary": (
                f"{waiting}Generate the approved train/validation split for {project_label} outside the Start request "
                "so model training can use a stable evaluation manifest."
            ),
            "source": "job_type_default",
        }
    return None


def is_agentish_job(job_type: str) -> bool:
    return (
        "agent" in job_type
        or "autonomous" in job_type
        or "notebook" in job_type
        or "research" in job_type
        or "split" in job_type
        or "train" in job_type
        or "baseline" in job_type
        or "experiment" in job_type
    )


def worker_display_name(job_type: str) -> str:
    if job_type == "continue_autonomous_session":
        return "Autonomous Session"
    if "train" in job_type or "baseline" in job_type:
        return "Training Worker"
    if "notebook" in job_type:
        return "Notebook Worker"
    if "research" in job_type:
        return "Research Worker"
    if "agent" in job_type:
        return "Agent Runner"
    if "split" in job_type:
        return "Evaluation Worker"
    return "Harness Worker"


def target_tab_for_job(job_type: str) -> str | None:
    if "train" in job_type:
        return "Leaderboard"
    if "notebook" in job_type:
        return "Notebooks"
    if "agent" in job_type or "research" in job_type:
        return "Approach"
    if "split" in job_type:
        return "Evaluation"
    if "baseline" in job_type or "experiment" in job_type:
        return "Experiments"
    return None


def target_tab_for_artifact(asset_type: str) -> str | None:
    if "notebook" in asset_type:
        return "Notebooks"
    if "report" in asset_type or "dashboard" in asset_type:
        return "Reports"
    if "evaluation" in asset_type or "split" in asset_type:
        return "Evaluation"
    if "agent" in asset_type or "research" in asset_type:
        return "Approach"
    return "Assets"
