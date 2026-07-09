from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.models.entities import Artifact, Project
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


def summarize_prediction_pipeline_runtime_failure(error_message: str) -> str:
    stripped = " ".join(error_message.strip().split())
    if "pandas dtypes must be int, float or bool" in error_message and "Fields with bad pandas dtypes:" in error_message:
        fields = error_message.rsplit("Fields with bad pandas dtypes:", 1)[1].strip().splitlines()[0].strip()
        return (
            "Prediction pipeline failed because predict.py passed non-numeric columns to the model. "
            f"Columns needing pipeline-side preprocessing: {fields}"
        )
    if "No such file or directory" in error_message:
        return "Prediction pipeline failed because predict.py could not find a required bundled file or input path."
    if stripped:
        return f"Prediction pipeline failed during predict.py execution: {stripped[:700]}"
    return "Prediction pipeline failed during predict.py execution."


def maybe_send_prediction_pipeline_runtime_failure_to_codex(
    db: Session,
    *,
    project: Project,
    pipeline_artifact: Artifact,
    job_id: str,
    error_message: str,
    error_summary: str,
    input_artifact_id: str | None = None,
    dataset_snapshot_id: str | None = None,
    input_artifact_ids_by_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is None or not session.workspace_path:
        return {"delivered": False, "reason": "no_main_session"}
    payload = {
        "schema_version": "prediction_pipeline_runtime_failure.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "job_id": job_id,
        "pipeline_artifact_id": pipeline_artifact.id,
        "pipeline_name": pipeline_artifact.name,
        "input_artifact_id": input_artifact_id if isinstance(input_artifact_id, str) else None,
        "dataset_snapshot_id": dataset_snapshot_id if isinstance(dataset_snapshot_id, str) else None,
        "input_artifact_ids_by_table": input_artifact_ids_by_table if isinstance(input_artifact_ids_by_table, dict) else None,
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
        f"pipeline_artifact_id: {pipeline_artifact.id}",
        f"pipeline_name: {pipeline_artifact.name}",
        f"input_artifact_id: {input_artifact_id or '<none>'}",
        f"dataset_snapshot_id: {dataset_snapshot_id or '<none>'}",
        "",
        "A user ran a registered prediction pipeline, but predict.py failed on the prediction input.",
        "Repair the Codex-authored pipeline source and register a new prediction_pipeline artifact version. Do not mutate the existing artifact.",
        "The repaired predict.py must apply the same preprocessing used at training time and must accept target-free prediction input.",
        "",
        "Error summary:",
        error_summary,
        "",
        "stderr_tail:",
        error_message[-4000:],
    ]
    try:
        inbox_path = write_inbox_entry(
            Path(session.workspace_path),
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
    }
