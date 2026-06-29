from __future__ import annotations

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
    activity = [event for job in recent_jobs for event in worker_events_from_job(job)][:12]
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
        "save_guided_journey_snapshot": "Guidance snapshot saved",
        "compare_guided_journey_snapshots": "Guidance snapshots compared",
        "run_eda_review": "Data review completed",
        "profile_dataset": "Dataset profile updated",
        "run_agent_task": "Agent task recorded",
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
        "guided_journey_report": "Guidance report saved",
        "guided_journey_snapshot": "Guidance snapshot saved",
    }
    return labels.get(asset_type, f"{humanize_identifier(asset_type)} saved")


def humanize_identifier(value: str) -> str:
    words = [word for word in value.replace("-", "_").split("_") if word]
    if not words:
        return "Workbench update"
    return " ".join(word.capitalize() for word in words)


def worker_events_from_job(job: Job) -> list[dict[str, Any]]:
    output = loads_json(job.output_json, {})
    events = output.get("worker_events")
    if isinstance(events, list):
        return [normalize_worker_event(event, job) for event in events if isinstance(event, dict)]
    if not is_agentish_job(job.job_type):
        return []
    return [
        {
            "worker_id": f"job-{job.job_type}",
            "display_name": worker_display_name(job.job_type),
            "status": job.status,
            "headline": str(output.get("assistant_message") or f"{job.job_type.replace('_', ' ')} is {job.status}"),
            "detail": job.error_message or f"Job {job.id}",
            "job_id": job.id,
            "project_id": job.project_id,
            "target_tab": target_tab_for_job(job.job_type),
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "active": job.status in {"queued", "running", "approval_required"},
            "token_usage": output.get("token_usage") if isinstance(output.get("token_usage"), dict) else estimated_tokens(job),
        }
    ]


def normalize_worker_event(event: dict[str, Any], job: Job) -> dict[str, Any]:
    token_usage = event.get("token_usage")
    return {
        "worker_id": str(event.get("worker_id") or f"job-{job.job_type}"),
        "display_name": str(event.get("display_name") or worker_display_name(job.job_type)),
        "status": str(event.get("status") or job.status),
        "headline": str(event.get("headline") or job.job_type.replace("_", " ")),
        "detail": str(event.get("detail") or job.error_message or f"Job {job.id}"),
        "job_id": str(event.get("job_id") or job.id),
        "project_id": job.project_id,
        "target_tab": event.get("target_tab") if isinstance(event.get("target_tab"), str) else target_tab_for_job(job.job_type),
        "created_at": str(event.get("created_at") or job.created_at.isoformat()),
        "updated_at": job.updated_at.isoformat(),
        "active": job.status in {"queued", "running", "approval_required"},
        "token_usage": token_usage if isinstance(token_usage, dict) else estimated_tokens(job),
    }


def estimated_tokens(job: Job) -> dict[str, Any]:
    base = max(24, len(job.job_type) * 3)
    return {
        "source": "estimated_until_runner_telemetry",
        "is_estimate": True,
        "series": [
            {"step": "queued", "tokens": base},
            {"step": "context", "tokens": base * 3},
            {"step": job.status, "tokens": base * (4 if job.status == "running" else 3)},
        ],
    }


def is_agentish_job(job_type: str) -> bool:
    return "agent" in job_type or "notebook" in job_type or "research" in job_type


def worker_display_name(job_type: str) -> str:
    if "notebook" in job_type:
        return "Notebook Worker"
    if "research" in job_type:
        return "Research Worker"
    if "agent" in job_type:
        return "Agent Runner"
    return "Harness Worker"


def target_tab_for_job(job_type: str) -> str | None:
    if "notebook" in job_type:
        return "Notebooks"
    if "agent" in job_type or "research" in job_type:
        return "Approach"
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
