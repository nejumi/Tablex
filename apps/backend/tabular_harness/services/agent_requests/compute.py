from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, ExperimentRun, Project, utc_now
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import create_job

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
COMPUTE_REQUESTS_DIR = "compute"
COMPUTE_REQUEST_SCHEMA_VERSION = "tablex_compute_request.v1"
COMPUTE_ACK_SCHEMA_VERSION = "tablex_compute_ack.v1"
COMPUTE_DEVICE_PREFERENCES = {"cpu", "gpu", "auto"}
COMPUTE_FALLBACK_POLICIES = {"cpu_on_unavailable", "fail"}

AppendSessionEvent = Callable[..., Any]


def compute_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / COMPUTE_REQUESTS_DIR


def compute_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / COMPUTE_REQUESTS_DIR


def process_compute_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
) -> None:
    del store
    request_dir = compute_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = compute_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            request = loads_json(raw_text, {})
            if not isinstance(request, dict):
                raise ValueError("Compute request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem).strip()
            if request.get("schema_version") != COMPUTE_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Compute request schema_version must be {COMPUTE_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation != "execute":
                raise ValueError(f"Unsupported compute operation: {operation or '<missing>'}")
            payload = normalize_compute_payload(
                db,
                project=project,
                workspace=workspace,
                value=request.get("payload"),
            )
            request_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            job = create_job(
                db,
                job_type="run_agent_compute",
                project_id=project.id,
                input_payload={
                    "schema_version": "agent_compute_job.v1",
                    "agent_session_id": session.id,
                    "request_id": request_id,
                    "request_hash": request_hash,
                    "request_workspace_relative_path": str(path.relative_to(workspace)),
                    "ack_workspace_relative_path": str(ack_path.relative_to(workspace)),
                    "payload": payload,
                },
                context={
                    "source": "codex_main_session",
                    "agent_session_id": session.id,
                    "workspace_path": str(workspace),
                },
                policy={
                    "execution": "isolated_compute_executor",
                    "external_network": False,
                    "credentials_mounted": False,
                    "reason": "Codex-authored project compute runs without auth or connector credentials.",
                },
                priority=30,
                max_attempts=1,
                created_by="codex_main_session",
            )
            ack = {
                "schema_version": COMPUTE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "queued",
                "job_id": job.id,
                "request_hash": request_hash,
                "accepted_at": utc_now().isoformat(),
                "message": "The compute run was queued for the isolated executor.",
            }
            write_compute_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="compute_request_queued",
                    role="harness",
                    title="Compute run queued",
                    content="The requested project compute run was accepted for isolated execution.",
                    payload=ack,
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": COMPUTE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_compute_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="compute_request_failed",
                    role="harness",
                    title="Compute request rejected",
                    content=str(exc),
                    payload=ack,
                    update_heartbeat=False,
                )


def normalize_compute_payload(
    db: Session,
    *,
    project: Project,
    workspace: Path,
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    script_path = require_workspace_file(workspace, value.get("script_path"), field="payload.script_path")
    if script_path.suffix.lower() != ".py":
        raise ValueError("payload.script_path must reference a Python source file")
    arguments = value.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 100 or not all(
        isinstance(item, str) and len(item) <= 4096 for item in arguments
    ):
        raise ValueError("payload.arguments must be an array of at most 100 strings")
    device_preference = str(value.get("device_preference") or "auto").strip().lower()
    if device_preference not in COMPUTE_DEVICE_PREFERENCES:
        raise ValueError("payload.device_preference must be cpu, gpu, or auto")
    fallback_policy = str(value.get("fallback_policy") or "cpu_on_unavailable").strip().lower()
    if fallback_policy not in COMPUTE_FALLBACK_POLICIES:
        raise ValueError("payload.fallback_policy must be cpu_on_unavailable or fail")
    timeout_seconds = value.get("timeout_seconds", 3600)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 10 <= timeout_seconds <= 86400:
        raise ValueError("payload.timeout_seconds must be an integer from 10 through 86400")
    result_manifest_path = require_workspace_relative_path(
        workspace,
        value.get("result_manifest_path"),
        field="payload.result_manifest_path",
        require_exists=False,
    )
    run_id = value.get("experiment_run_id")
    if run_id is not None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("payload.experiment_run_id must be a non-empty string")
        run = db.get(ExperimentRun, run_id.strip())
        if run is None or run.project_id != project.id:
            raise ValueError("payload.experiment_run_id must reference a run in this project")
        run_id = run.id
    outputs = value.get("outputs", [])
    if not isinstance(outputs, list) or len(outputs) > 50:
        raise ValueError("payload.outputs must be an array of at most 50 artifact declarations")
    normalized_outputs = [normalize_output(workspace, item, index=index) for index, item in enumerate(outputs)]
    return {
        "script_path": str(script_path.relative_to(workspace.resolve())),
        "arguments": arguments,
        "device_preference": device_preference,
        "fallback_policy": fallback_policy,
        "timeout_seconds": timeout_seconds,
        "result_manifest_path": str(result_manifest_path.relative_to(workspace.resolve())),
        "experiment_run_id": run_id,
        "outputs": normalized_outputs,
        "decision_context": require_text(value.get("decision_context"), "payload.decision_context"),
    }


def normalize_output(workspace: Path, value: Any, *, index: int) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"payload.outputs[{index}] must be an object")
    path = require_workspace_relative_path(
        workspace,
        value.get("path"),
        field=f"payload.outputs[{index}].path",
        require_exists=False,
    )
    asset_type = require_text(value.get("asset_type"), f"payload.outputs[{index}].asset_type")
    name = require_text(value.get("name"), f"payload.outputs[{index}].name")
    return {"path": str(path.relative_to(workspace.resolve())), "asset_type": asset_type, "name": name}


def require_workspace_file(workspace: Path, value: Any, *, field: str) -> Path:
    path = require_workspace_relative_path(workspace, value, field=field, require_exists=True)
    if not path.is_file():
        raise ValueError(f"{field} must reference a file")
    return path


def require_workspace_relative_path(
    workspace: Path,
    value: Any,
    *,
    field: str,
    require_exists: bool,
) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    relative = Path(value.strip())
    if relative.is_absolute():
        raise ValueError(f"{field} must be relative to the AgentSession workspace")
    root = workspace.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{field} escapes the AgentSession workspace")
    if require_exists and not path.exists():
        raise ValueError(f"{field} does not exist")
    return path


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def write_compute_ack(path: Path, payload: dict[str, Any]) -> None:
    from tabular_harness.core.json import dumps_json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_json(payload), encoding="utf-8")
