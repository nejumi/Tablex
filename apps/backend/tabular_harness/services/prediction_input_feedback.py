from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import AgentTranscriptEvent, Artifact, Project
from tabular_harness.services.agent_inbox import write_inbox_entry
from tabular_harness.services.agent_supervisor import active_main_session, latest_main_session
from tabular_harness.services.agent_transcript import append_session_event


def maybe_send_prediction_input_validation_failure_to_codex(
    db: Session,
    *,
    project: Project,
    artifact: Artifact,
    pipeline_artifact_id: str | None,
    table_name: str,
    batch_kind: str,
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    if validation_report.get("status") != "failed":
        return {"delivered": False, "reason": "validation_passed"}
    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is None or not session.workspace_path:
        return {"delivered": False, "reason": "no_main_session"}
    if session.status == "stopped":
        return {"delivered": False, "reason": "agent_power_off", "agent_session_id": session.id}
    if session.status not in {"starting", "running", "between_turns", "waiting_for_runner", "completed"}:
        return {"delivered": False, "reason": f"main_session_{session.status}", "agent_session_id": session.id}
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="prediction_input_validation_failed",
        role="harness",
        title="Prediction input validation failed",
        content="A prediction input did not match the selected model input contract.",
        payload={
            "schema_version": "prediction_input_validation_observation.v1",
            "project_id": project.id,
            "artifact_id": artifact.id,
            "pipeline_artifact_id": pipeline_artifact_id if isinstance(pipeline_artifact_id, str) else None,
            "table_name": table_name,
            "batch_kind": batch_kind,
            "validation_report": validation_report,
        },
        update_heartbeat=False,
    )
    payload = {
        "schema_version": "prediction_input_validation_observation.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "transcript_event_id": event.id,
        "transcript_event_index": event.event_index,
        "artifact_id": artifact.id,
        "pipeline_artifact_id": pipeline_artifact_id if isinstance(pipeline_artifact_id, str) else None,
        "table_name": table_name,
        "batch_kind": batch_kind,
        "validation_report": validation_report,
    }
    missing_columns = validation_report.get("missing_columns")
    unexpected_columns = validation_report.get("unexpected_columns")
    lines = [
        "schema_version: prediction_input_validation_observation.v1",
        f"project_id: {project.id}",
        f"artifact_id: {artifact.id}",
        f"pipeline_artifact_id: {pipeline_artifact_id or '<none>'}",
        f"table_name: {table_name}",
        f"batch_kind: {batch_kind}",
        "",
        "A user uploaded prediction input for a registered model pipeline, but the input did not match the fixed input contract.",
        "Review the validation report and either repair the pipeline/input contract or explain the required input table clearly in the next human-facing update.",
        "",
        f"missing_columns: {missing_columns if isinstance(missing_columns, list) else []}",
        f"unexpected_columns: {unexpected_columns if isinstance(unexpected_columns, list) else []}",
    ]
    try:
        inbox_path = write_inbox_entry(
            resolve_runtime_data_path(session.workspace_path),
            kind="observation",
            entry_type="prediction_input_validation_failed",
            payload=payload,
            content="\n".join(lines).strip() + "\n",
            title="Prediction input validation failed",
        )
    except OSError:
        return {"delivered": False, "reason": "inbox_write_failed", "agent_session_id": session.id}
    return {
        "delivered": True,
        "agent_session_id": session.id,
        "transcript_event_id": event.id,
        "transcript_event_index": event.event_index,
        "inbox_path": str(inbox_path),
    }


def prediction_pipeline_runtime_failure_message(*, exit_code: int | None) -> str:
    if isinstance(exit_code, int):
        return f"Prediction pipeline failed while running predict.py (exit code {exit_code})."
    return "Prediction pipeline failed while running predict.py."


def maybe_send_prediction_pipeline_runtime_failure_to_codex(
    db: Session,
    *,
    project: Project,
    pipeline_artifact: Artifact,
    job_id: str,
    error_message: str,
    error_summary: str,
    exit_code: int | None = None,
    input_artifact_id: str | None = None,
    dataset_snapshot_id: str | None = None,
    input_artifact_ids_by_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is None or not session.workspace_path:
        return {"delivered": False, "reason": "no_main_session"}
    attention_key = prediction_pipeline_runtime_failure_attention_key(
        pipeline_artifact_id=pipeline_artifact.id,
        exit_code=exit_code,
        stderr_tail=error_message[-4000:],
    )
    existing_event = prediction_pipeline_runtime_failure_event_for_attention_key(
        db,
        project_id=project.id,
        attention_key=attention_key,
    )
    if existing_event is not None:
        return {
            "delivered": True,
            "deduplicated": True,
            "reason": "duplicate_runtime_failure_observation",
            "agent_session_id": existing_event.session_id,
            "transcript_event_id": existing_event.id,
            "transcript_event_index": existing_event.event_index,
            "attention_key": attention_key,
        }
    payload = {
        "schema_version": "prediction_pipeline_runtime_failure.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "job_id": job_id,
        "attention_key": attention_key,
        "pipeline_artifact_id": pipeline_artifact.id,
        "pipeline_name": pipeline_artifact.name,
        "input_artifact_id": input_artifact_id if isinstance(input_artifact_id, str) else None,
        "dataset_snapshot_id": dataset_snapshot_id if isinstance(dataset_snapshot_id, str) else None,
        "input_artifact_ids_by_table": input_artifact_ids_by_table if isinstance(input_artifact_ids_by_table, dict) else None,
        "exit_code": exit_code if isinstance(exit_code, int) else None,
        "error_summary": error_summary,
        "stderr_tail": error_message[-4000:],
    }
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="prediction_pipeline_runtime_failed",
        role="harness",
        title="Prediction pipeline failed",
        content=error_summary,
        payload=payload,
        update_heartbeat=False,
    )
    payload["transcript_event_id"] = event.id
    payload["transcript_event_index"] = event.event_index
    lines = [
        "schema_version: prediction_pipeline_runtime_failure.v1",
        f"project_id: {project.id}",
        f"job_id: {job_id}",
        f"attention_key: {attention_key}",
        f"pipeline_artifact_id: {pipeline_artifact.id}",
        f"pipeline_name: {pipeline_artifact.name}",
        f"exit_code: {exit_code if isinstance(exit_code, int) else '<unknown>'}",
        f"input_artifact_id: {input_artifact_id or '<none>'}",
        f"dataset_snapshot_id: {dataset_snapshot_id or '<none>'}",
        "",
        "A user ran a registered prediction pipeline, but predict.py failed on the prediction input.",
        "Repair the Codex-authored pipeline source and register a new prediction_pipeline artifact version. Do not mutate the existing artifact.",
        "The repaired predict.py must apply the same preprocessing used at training time and must accept target-free prediction input.",
        "Use the stderr tail below as factual evidence; Tablex has not inferred the root cause.",
        "",
        "Error summary:",
        error_summary,
        "",
        "stderr_tail:",
        error_message[-4000:],
    ]
    try:
        inbox_path = write_inbox_entry(
            resolve_runtime_data_path(session.workspace_path),
            kind="observation",
            entry_type="prediction_pipeline_runtime_failed",
            payload=payload,
            content="\n".join(lines).strip() + "\n",
            title="Prediction pipeline failed",
        )
    except OSError:
        return {"delivered": False, "reason": "inbox_write_failed", "agent_session_id": session.id}
    return {
        "delivered": True,
        "agent_session_id": session.id,
        "transcript_event_id": event.id,
        "transcript_event_index": event.event_index,
        "inbox_path": str(inbox_path),
        "attention_key": attention_key,
    }


def prediction_pipeline_runtime_failure_attention_key(
    *,
    pipeline_artifact_id: str,
    exit_code: int | None,
    stderr_tail: str,
) -> str:
    digest = hashlib.sha256(stderr_tail.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"prediction_pipeline_runtime_failed:{pipeline_artifact_id}:{exit_code if isinstance(exit_code, int) else 'unknown'}:{digest}"


def prediction_pipeline_runtime_failure_event_for_attention_key(
    db: Session,
    *,
    project_id: str,
    attention_key: str,
) -> AgentTranscriptEvent | None:
    events = db.scalars(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.project_id == project_id,
            AgentTranscriptEvent.event_type == "prediction_pipeline_runtime_failed",
        )
        .order_by(AgentTranscriptEvent.created_at.desc())
        .limit(100)
    ).all()
    for event in events:
        payload = loads_json(event.payload_json, {})
        if payload.get("attention_key") == attention_key:
            return event
    return None
