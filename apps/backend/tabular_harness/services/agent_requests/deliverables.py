from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, Project, utc_now
from tabular_harness.services.deliverable_expectations import (
    expectation_to_dict,
    waive_deliverable_expectation,
)

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
DELIVERABLE_REQUESTS_DIR = "deliverables"
DELIVERABLE_REQUEST_SCHEMA_VERSION = "tablex_deliverable_request.v1"
DELIVERABLE_ACK_SCHEMA_VERSION = "tablex_deliverable_ack.v1"

AppendSessionEvent = Callable[..., Any]


def deliverable_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / DELIVERABLE_REQUESTS_DIR


def deliverable_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / DELIVERABLE_REQUESTS_DIR


def process_deliverable_tool_requests(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
) -> None:
    request_dir = deliverable_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = deliverable_acks_dir(workspace)
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
                raise ValueError("Deliverable request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != DELIVERABLE_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported deliverable request schema_version: {schema_version or '<missing>'}; "
                    f"expected {DELIVERABLE_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation != "waive_deliverable":
                raise ValueError(f"Unsupported deliverable request operation: {operation or '<missing>'}")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            expectation = waive_deliverable_expectation(
                db,
                project=project,
                expectation_id=optional_text(payload.get("expectation_id")),
                kind=optional_text(payload.get("kind")),
                subject_ref=optional_text(payload.get("subject_ref")),
                rationale=optional_text(payload.get("rationale")),
            )
            ack = {
                "schema_version": DELIVERABLE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": {"expectation": expectation_to_dict(expectation)},
            }
            write_deliverable_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="deliverable_request_succeeded",
                    role="harness",
                    title="Deliverable request processed",
                    content=f"Processed deliverable request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": DELIVERABLE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_deliverable_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="deliverable_request_failed",
                    role="harness",
                    title="Deliverable request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )


def write_deliverable_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("deliverable request string fields must be strings when provided")
    stripped = value.strip()
    return stripped or None
