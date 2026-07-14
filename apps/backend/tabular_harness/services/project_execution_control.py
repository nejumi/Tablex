from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tabular_harness.core.ids import new_id

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
STOP_REQUEST_SCHEMA_VERSION = "project_execution_stop_request.v1"
STOP_ACK_SCHEMA_VERSION = "project_execution_stop_ack.v1"


def request_project_execution_stop(data_dir: Path, *, project_id: str) -> dict[str, Any]:
    request = {
        "schema_version": STOP_REQUEST_SCHEMA_VERSION,
        "request_id": new_id("stop"),
        "project_id": validate_project_id(project_id),
        "requested_at": now_iso(),
    }
    write_json(stop_request_path(data_dir, project_id), request)
    stop_ack_path(data_dir, project_id).unlink(missing_ok=True)
    return request


def project_execution_stop_requested(data_dir: Path, *, project_id: str) -> bool:
    request = read_json(stop_request_path(data_dir, project_id))
    return (
        request.get("schema_version") == STOP_REQUEST_SCHEMA_VERSION
        and request.get("project_id") == project_id
    )


def list_project_execution_stop_requests(data_dir: Path) -> list[dict[str, Any]]:
    root = execution_control_root(data_dir)
    if not root.exists():
        return []
    requests: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.stop.json")):
        request = read_json(path)
        project_id = request.get("project_id")
        if (
            request.get("schema_version") == STOP_REQUEST_SCHEMA_VERSION
            and isinstance(project_id, str)
            and PROJECT_ID_PATTERN.fullmatch(project_id)
        ):
            ack = read_json(stop_ack_path(data_dir, project_id))
            if ack.get("request_id") == request.get("request_id") and ack.get("verified") is True:
                continue
            requests.append(request)
    return requests


def record_project_execution_stop_ack(
    data_dir: Path,
    *,
    request: dict[str, Any],
    observed_count: int,
    terminated_count: int,
    remaining_count: int,
    processes: list[dict[str, Any]],
) -> dict[str, Any]:
    project_id = validate_project_id(str(request.get("project_id") or ""))
    previous = read_json(stop_ack_path(data_dir, project_id))
    same_request = previous.get("request_id") == request.get("request_id")
    previous_zero_observations = (
        int(previous.get("consecutive_zero_observations") or 0) if same_request else 0
    )
    consecutive_zero_observations = (
        previous_zero_observations + 1 if remaining_count == 0 else 0
    )
    ack = {
        "schema_version": STOP_ACK_SCHEMA_VERSION,
        "request_id": request.get("request_id"),
        "project_id": project_id,
        "observed_at": now_iso(),
        "observed_count": observed_count,
        "terminated_count": terminated_count,
        "remaining_count": remaining_count,
        "consecutive_zero_observations": consecutive_zero_observations,
        "verified": remaining_count == 0 and consecutive_zero_observations >= 2,
        "processes": processes,
    }
    write_json(stop_ack_path(data_dir, project_id), ack)
    return ack


def wait_for_project_execution_stop_ack(
    data_dir: Path,
    *,
    request: dict[str, Any],
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    project_id = validate_project_id(str(request.get("project_id") or ""))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ack = read_json(stop_ack_path(data_dir, project_id))
        if ack.get("request_id") == request.get("request_id") and ack.get("verified") is True:
            return ack
        time.sleep(0.1)
    ack = read_json(stop_ack_path(data_dir, project_id))
    return {
        "schema_version": STOP_ACK_SCHEMA_VERSION,
        "request_id": request.get("request_id"),
        "project_id": project_id,
        "verified": False,
        "remaining_count": ack.get("remaining_count"),
        "consecutive_zero_observations": ack.get("consecutive_zero_observations", 0),
        "status": "ack_timeout",
    }


def clear_project_execution_stop(data_dir: Path, *, project_id: str) -> None:
    stop_request_path(data_dir, project_id).unlink(missing_ok=True)
    stop_ack_path(data_dir, project_id).unlink(missing_ok=True)


def stop_request_path(data_dir: Path, project_id: str) -> Path:
    return execution_control_root(data_dir) / f"{validate_project_id(project_id)}.stop.json"


def stop_ack_path(data_dir: Path, project_id: str) -> Path:
    return execution_control_root(data_dir) / f"{validate_project_id(project_id)}.stop.ack.json"


def execution_control_root(data_dir: Path) -> Path:
    return data_dir.resolve() / "runtime" / "project-execution-control"


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError("Invalid project id for execution control")
    return project_id


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
