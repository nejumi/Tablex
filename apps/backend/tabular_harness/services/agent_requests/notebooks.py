from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, Project, utc_now
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import create_job

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
NOTEBOOK_REQUESTS_DIR = "notebooks"
NOTEBOOK_REQUEST_SCHEMA_VERSION = "tablex_notebook_request.v1"
NOTEBOOK_ACK_SCHEMA_VERSION = "tablex_notebook_ack.v1"
NOTEBOOK_REQUEST_PAYLOAD_KEYS = {
    "artifact_id",
    "dataset_snapshot_id",
    "model_version_id",
    "notebook_kind",
    "quality_manifest",
    "related_run_ids",
    "research_plan_node_id",
    "run_id",
    "title",
    "workspace_path",
}

AppendSessionEvent = Callable[..., Any]
RegisterAttention = Callable[..., Any]
ExecuteNotebookRegistration = Callable[..., dict[str, Any]]
WriteNotebookRejection = Callable[..., Any]


def notebook_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / NOTEBOOK_REQUESTS_DIR


def notebook_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / NOTEBOOK_REQUESTS_DIR


def process_notebook_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    execute_registration_fn: ExecuteNotebookRegistration,
    write_rejection_fn: WriteNotebookRejection,
    append_session_event_fn: AppendSessionEvent | None = None,
    register_attention_fn: RegisterAttention | None = None,
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
            if operation != "register_notebook":
                raise ValueError(f"Unsupported notebook request operation: {operation or '<missing>'}")
            body, compatibility_warnings = notebook_request_payload_and_compatibility_warnings(payload)
            compatibility_warnings.extend(
                notebook_quality_manifest_compatibility_warnings(body.get("quality_manifest"))
            )
            result = execute_registration_fn(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                payload=body,
            )
            if compatibility_warnings:
                result["compatibility_warnings"] = compatibility_warnings
            notebook_artifact_id = result.get("notebook_artifact_id")
            if isinstance(notebook_artifact_id, str) and notebook_artifact_id.strip():
                create_job(
                    db,
                    job_type="prewarm_native_marimo_session",
                    project_id=project.id,
                    input_payload={"analysis_notebook_artifact_id": notebook_artifact_id.strip()},
                    priority=20,
                    max_attempts=1,
                    created_by="tablex",
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
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="notebook_request_succeeded",
                    role="harness",
                    title="Notebook request processed",
                    content=f"Processed notebook request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    artifact_id=result.get("notebook_artifact_id"),
                    update_heartbeat=False,
                )
        except Exception as exc:
            issues = getattr(exc, "issues", None)
            normalized_issues = issues if isinstance(issues, list) else None
            error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
            if normalized_issues is not None:
                error["issues"] = normalized_issues
            ack = {
                "schema_version": NOTEBOOK_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": error,
            }
            write_notebook_tool_ack(ack_path, ack)
            write_rejection_fn(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc),
                issues=normalized_issues,
            )
            if append_session_event_fn is not None:
                append_session_event_fn(
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
            if register_attention_fn is not None:
                details: dict[str, Any] = {
                    "request_id": request_id,
                    "operation": operation,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1200],
                    "workspace_relative_path": str(path.relative_to(workspace)),
                }
                if normalized_issues is not None:
                    details["issues"] = normalized_issues[:8]
                register_attention_fn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=notebook_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    ),
                    status="needs_attention",
                    message_kind="notebook_request_failed",
                    details=details,
                )


def notebook_request_payload_and_compatibility_warnings(
    request: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    raw_payload = request.get("payload")
    compatibility_warnings: list[dict[str, str]] = []
    if raw_payload is None:
        body = {key: request[key] for key in NOTEBOOK_REQUEST_PAYLOAD_KEYS if key in request}
        if not body:
            raise ValueError("payload must be an object")
        compatibility_warnings.append(
            {
                "field": "payload",
                "message": (
                    "Accepted explicit notebook registration fields at the request top level as the payload object."
                ),
            }
        )
    elif not isinstance(raw_payload, dict):
        raise ValueError("payload must be an object")
    else:
        body = dict(raw_payload)

    for key in sorted(NOTEBOOK_REQUEST_PAYLOAD_KEYS):
        if key in request and key not in body:
            body[key] = request[key]
            compatibility_warnings.append(
                {
                    "field": key,
                    "message": f"Accepted top-level `{key}` as payload.{key}.",
                }
            )
    return body, compatibility_warnings


def notebook_quality_manifest_compatibility_warnings(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    read_order = value.get("read_order")
    if not isinstance(read_order, list):
        return []
    warnings: list[dict[str, str]] = []
    for index, item in enumerate(read_order[:20]):
        if isinstance(item, str):
            warnings.append(
                {
                    "field": f"quality_manifest.read_order[{index}]",
                    "message": "Accepted a string read_order item as an object with a label field.",
                }
            )
    return warnings


def notebook_request_failure_attention_key(*, operation: str, error_type: str, error_message: str) -> str:
    normalized = {
        "operation": operation or "unknown",
        "error_type": error_type,
        "error_message": error_message[:800],
    }
    signature = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"notebook_request_failed:{signature}"


def write_notebook_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
