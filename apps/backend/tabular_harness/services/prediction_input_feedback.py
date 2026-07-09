from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.models.entities import Artifact, Project
from tabular_harness.services.agent_inbox import write_inbox_entry
from tabular_harness.services.agent_sessions import active_main_session, append_session_event


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
    session = active_main_session(db, project.id)
    if session is None or not session.workspace_path:
        return {"delivered": False, "reason": "no_active_main_session"}
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
            Path(session.workspace_path),
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
