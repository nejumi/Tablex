from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, AgentTranscriptEvent, Artifact, DatasetSnapshot, Project
from tabular_harness.services.agent_session_inbox import (
    write_data_framing_request_to_workspace_inbox,
    write_task_spec_request_to_workspace_inbox,
)
from tabular_harness.services.agent_transcript import append_session_event

ACTIVE_SESSION_STATUSES_FOR_TASK_SPEC_NUDGE = {"starting", "running", "between_turns", "waiting_for_runner"}


def project_has_task_spec_artifact(db: Session, *, project_id: str) -> bool:
    artifact = db.scalar(
        select(Artifact.id)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "task_spec")
        .limit(1)
    )
    return artifact is not None


def latest_task_spec_request_event(
    db: Session,
    *,
    session_id: str,
    primary_dataset_snapshot_id: str,
) -> AgentTranscriptEvent | None:
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "task_spec_requested",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(50)
        ).all()
    )
    for event in events:
        payload = loads_json(event.payload_json, {})
        if payload.get("primary_dataset_snapshot_id") == primary_dataset_snapshot_id:
            return event
    return None


def project_dataset_snapshot_ids(db: Session, *, project_id: str) -> list[str]:
    return list(
        db.scalars(
            select(DatasetSnapshot.id)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.asc(), DatasetSnapshot.id.asc())
        ).all()
    )


def latest_data_framing_request_event(
    db: Session,
    *,
    session_id: str,
    dataset_snapshot_ids: list[str],
) -> AgentTranscriptEvent | None:
    dataset_key = sorted(dataset_snapshot_ids)
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "data_framing_requested",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(50)
        ).all()
    )
    for event in events:
        payload = loads_json(event.payload_json, {})
        recorded = payload.get("dataset_snapshot_ids")
        if isinstance(recorded, list) and sorted(str(item) for item in recorded) == dataset_key:
            return event
    return None


def maybe_request_data_framing_update(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    locale: str | None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES_FOR_TASK_SPEC_NUDGE:
        return None
    if isinstance(project.primary_dataset_snapshot_id, str) and project.primary_dataset_snapshot_id.strip():
        return None
    if project_has_task_spec_artifact(db, project_id=project.id):
        return None
    dataset_snapshot_ids = project_dataset_snapshot_ids(db, project_id=project.id)
    if not dataset_snapshot_ids:
        return None
    if latest_data_framing_request_event(
        db,
        session_id=session.id,
        dataset_snapshot_ids=dataset_snapshot_ids,
    ) is not None:
        return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="data_framing_requested",
        role="harness",
        title="Data framing request delivered",
        content=(
            "DatasetSnapshot records are available while primary DatasetSnapshot and TaskSpec are still missing; "
            "Tablex asked Codex to submit data-framing requests without stopping reversible work."
        ),
        payload={
            "schema_version": "tablex_data_framing_request_notice.v1",
            "locale": locale,
            "project_id": project.id,
            "dataset_snapshot_ids": dataset_snapshot_ids,
            "requested_operations": ["set_primary_table", "register_derived_table", "commit_task_spec"],
            "targets_empty_allowed": True,
        },
        update_heartbeat=False,
    )
    write_data_framing_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        project_id=project.id,
        dataset_snapshot_ids=dataset_snapshot_ids,
    )
    return event


def maybe_request_task_spec_update(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    locale: str | None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES_FOR_TASK_SPEC_NUDGE:
        return None
    primary_dataset_snapshot_id = project.primary_dataset_snapshot_id
    if not isinstance(primary_dataset_snapshot_id, str) or not primary_dataset_snapshot_id.strip():
        return None
    primary_dataset_snapshot_id = primary_dataset_snapshot_id.strip()
    if project_has_task_spec_artifact(db, project_id=project.id):
        return None
    if latest_task_spec_request_event(
        db,
        session_id=session.id,
        primary_dataset_snapshot_id=primary_dataset_snapshot_id,
    ) is not None:
        return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="task_spec_requested",
        role="harness",
        title="TaskSpec request delivered",
        content=(
            "A primary DatasetSnapshot is registered and TaskSpec is still missing; "
            "Tablex asked Codex to submit commit_task_spec without stopping reversible work."
        ),
        payload={
            "schema_version": "tablex_task_spec_request_notice.v1",
            "locale": locale,
            "project_id": project.id,
            "primary_dataset_snapshot_id": primary_dataset_snapshot_id,
            "requested_operation": "commit_task_spec",
            "targets_empty_allowed": True,
        },
        update_heartbeat=False,
    )
    write_task_spec_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        project_id=project.id,
        primary_dataset_snapshot_id=primary_dataset_snapshot_id,
    )
    return event
