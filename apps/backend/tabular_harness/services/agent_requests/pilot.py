from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, Artifact, Evidence, PilotDeployment, Project, utc_now
from tabular_harness.services.agent_inbox import latest_inbox_entry_path, write_inbox_entry
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.research_plans import attach_research_plan_artifact

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
PILOT_REQUESTS_DIR = "pilot"
PILOT_REQUEST_SCHEMA_VERSION = "tablex_pilot_request.v1"
PILOT_ACK_SCHEMA_VERSION = "tablex_pilot_ack.v1"

AppendSessionEvent = Callable[..., Any]
RegisterAttention = Callable[..., Any]


def pilot_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="pilot_request_rejection", kind="rejection")


def pilot_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / PILOT_REQUESTS_DIR


def pilot_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / PILOT_REQUESTS_DIR


def process_pilot_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
    register_attention_fn: RegisterAttention | None = None,
) -> None:
    request_dir = pilot_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = pilot_acks_dir(workspace)
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
                raise ValueError("Pilot request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            if str(request.get("schema_version") or "") != PILOT_REQUEST_SCHEMA_VERSION:
                raise ValueError(f"Unsupported pilot request schema_version; expected {PILOT_REQUEST_SCHEMA_VERSION}")
            operation = str(request.get("operation") or "").strip()
            if operation != "register_validation_audit":
                raise ValueError(f"Unsupported pilot request operation: {operation or '<missing>'}")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = execute_validation_audit_registration_request(
                db,
                store=store,
                project=project,
                session=session,
                request_id=request_id,
                payload=payload,
            )
            ack = {
                "schema_version": PILOT_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_pilot_tool_ack(ack_path, ack)
        except Exception as exc:
            ack = {
                "schema_version": PILOT_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_pilot_tool_ack(ack_path, ack)
            write_pilot_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="pilot_request_failed",
                    role="harness",
                    title="Pilot request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )
            if register_attention_fn is not None:
                register_attention_fn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=pilot_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    ),
                    status="needs_attention",
                    message_kind="pilot_request_failed",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1200],
                        "workspace_relative_path": str(path.relative_to(workspace)),
                    },
                )


def execute_validation_audit_registration_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    deployment_id = require_nonempty_string(payload, "deployment_id")
    deployment = db.get(PilotDeployment, deployment_id)
    if deployment is None or deployment.project_id != project.id:
        raise ValueError("payload.deployment_id does not belong to this project")
    scoring_report_artifact_ids = require_string_list(
        payload.get("scoring_report_artifact_ids", []),
        "payload.scoring_report_artifact_ids",
    )
    for artifact_id in scoring_report_artifact_ids:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project.id:
            raise ValueError(f"Unknown scoring report artifact id {artifact_id}")
    verdict = require_nonempty_string(payload, "scheme_verdict")
    if verdict not in {"confirmed", "partially_confirmed", "refuted"}:
        raise ValueError("payload.scheme_verdict must be confirmed, partially_confirmed, or refuted")
    gap_decomposition = payload.get("gap_decomposition")
    if not isinstance(gap_decomposition, list):
        raise ValueError("payload.gap_decomposition must be an array")
    valid_components = {"temporal_drift", "covariate_shift", "target_shift", "leakage", "sample_noise", "data_quality", "other"}
    for index, item in enumerate(gap_decomposition):
        if not isinstance(item, dict):
            raise ValueError(f"payload.gap_decomposition/{index} must be an object")
        component = item.get("component")
        if component not in valid_components:
            raise ValueError(f"payload.gap_decomposition/{index}/component is invalid")
    hypotheses = payload.get("hypotheses")
    if hypotheses is not None and not isinstance(hypotheses, list):
        raise ValueError("payload.hypotheses must be an array when provided")
    next_iteration_focus = require_nonempty_string(payload, "next_iteration_focus")
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="validation_scheme_audit",
        name=f"agent_session_{session.id}_validation_audit_{request_id}",
        filename="validation_audit.json",
        payload={"schema_version": "validation_scheme_audit.v1", "request_id": request_id, **payload},
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "deployment_id": deployment.id,
            "scheme_verdict": verdict,
            "scoring_report_artifact_ids": scoring_report_artifact_ids,
        },
    )
    evidence = Evidence(
        id=new_id("evd"),
        project_id=project.id,
        evidence_type="validation_scheme_audit",
        summary=next_iteration_focus,
        strength="reported",
        source_artifact_id=artifact.id,
        metadata_json=dumps_json({"request_id": request_id, "scheme_verdict": verdict}),
    )
    db.add(evidence)
    node_id = optional_nonempty_string(payload, "research_plan_node_id")
    if node_id:
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=node_id,
            artifact_id=artifact.id,
            role="validation_audit",
            metadata={"request_id": request_id, "evidence_id": evidence.id},
        )
    return {"artifact_id": artifact.id, "evidence_id": evidence.id, "deployment_id": deployment.id}


def write_pilot_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_pilot_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
) -> None:
    lines = [
        "schema_version: tablex_pilot_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The pilot request did not register a validation audit, evidence, or ResearchPlan link.",
        "Read the ack JSON, repair the fixed request payload, and resubmit under `.tablex/requests/pilot/` with a new request_id.",
        "",
        "Expected operation: register_validation_audit.",
        "Required fields include deployment_id, scoring_report_artifact_ids, scheme_verdict, gap_decomposition, and next_iteration_focus.",
        "",
        "Error:",
        error_message,
    ]
    write_inbox_entry(
        workspace,
        kind="rejection",
        entry_type="pilot_request_rejection",
        title="Pilot request rejected",
        content="\n".join(lines).rstrip() + "\n",
        payload={
            "schema_version": "tablex_pilot_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
        },
    )


def pilot_request_failure_attention_key(*, operation: str, error_type: str, error_message: str) -> str:
    normalized = {
        "operation": operation or "unknown",
        "error_type": error_type,
        "error_message": error_message[:800],
    }
    signature = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"pilot_request_failed:{signature}"


def require_nonempty_string(payload: dict[str, Any], key: str, *, prefix: str = "payload") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}.{key} must be a non-empty string")
    return value.strip()


def optional_nonempty_string(payload: dict[str, Any], key: str, *, prefix: str = "payload") -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def require_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    output: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        output.append(item.strip())
    return output
