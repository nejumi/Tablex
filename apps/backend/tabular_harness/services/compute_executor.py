from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from tabular_harness.core.runtime_resources import detect_compute_resources, select_compute_device

EXECUTION_SCHEMA_VERSION = "isolated_compute_execution.v1"
STATUS_SCHEMA_VERSION = "isolated_compute_status.v1"
MAX_CAPTURED_CHARS = 4 * 1024 * 1024
MAX_EXECUTION_ATTEMPTS = max(1, int(os.getenv("TABLEX_COMPUTE_MAX_ATTEMPTS", "3")))
EXECUTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_execution_lock = threading.Lock()
_execution_futures: dict[str, Future[None]] = {}
_execution_processes: dict[str, subprocess.Popen[str]] = {}
_execution_pool = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("TABLEX_COMPUTE_MAX_WORKERS", "1"))),
    thread_name_prefix="tablex-compute",
)

def recover_interrupted_executions() -> None:
    root = compute_execution_root()
    if not root.exists():
        return
    for status_path in root.glob("*/status.json"):
        status = read_json_file(status_path)
        if (
            status.get("schema_version") != STATUS_SCHEMA_VERSION
            or status.get("status") != "running"
        ):
            continue
        write_status(
            status_path.parent.name,
            {
                **status,
                "status": "interrupted",
                "updated_at": now_iso(),
                "error": {
                    "type": "ExecutorRestarted",
                    "message": "The compute executor restarted before this execution reached a terminal state.",
                },
            },
        )


@asynccontextmanager
async def compute_executor_lifespan(_app: FastAPI):
    recover_interrupted_executions()
    yield


app = FastAPI(
    title="Tablex isolated compute executor",
    docs_url=None,
    redoc_url=None,
    lifespan=compute_executor_lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/executions/{execution_id}")
def submit_execution(execution_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    validate_execution_id(execution_id)
    validate_payload(payload)
    with _execution_lock:
        existing = read_execution_status(execution_id)
        if existing.get("status") in {"completed", "failed", "cancelled"}:
            return existing
        future = _execution_futures.get(execution_id)
        if existing.get("status") == "running" and future is not None and not future.done():
            return existing
        request_path = execution_dir(execution_id) / "request.json"
        if request_path.exists():
            stored_request = read_json_file(request_path)
            if stored_request != payload:
                raise HTTPException(
                    status_code=409, detail="Execution id is already bound to a different request"
                )
        else:
            write_json_file(request_path, payload)
        attempt = int(existing.get("attempt") or 0) + 1
        if attempt > MAX_EXECUTION_ATTEMPTS:
            status = {
                **existing,
                "schema_version": STATUS_SCHEMA_VERSION,
                "execution_id": execution_id,
                "status": "failed",
                "attempt": attempt - 1,
                "updated_at": now_iso(),
                "ended_at": now_iso(),
                "result": None,
                "error": {
                    "type": "RetryLimitExceeded",
                    "message": (
                        "The compute executor could not finish this execution after "
                        f"{MAX_EXECUTION_ATTEMPTS} attempts."
                    ),
                },
            }
            write_status(execution_id, status)
            return status
        status = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "execution_id": execution_id,
            "status": "running",
            "attempt": attempt,
            "created_at": existing.get("created_at") or now_iso(),
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "result": None,
            "error": None,
        }
        write_status(execution_id, status)
        _execution_futures[execution_id] = _execution_pool.submit(
            run_durable_execution, execution_id, payload
        )
        return status


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str) -> dict[str, Any]:
    validate_execution_id(execution_id)
    status = read_execution_status(execution_id)
    if not status:
        raise HTTPException(status_code=404, detail="Compute execution not found")
    return status


@app.delete("/executions/{execution_id}")
def cancel_execution(execution_id: str) -> dict[str, Any]:
    validate_execution_id(execution_id)
    with _execution_lock:
        status = read_execution_status(execution_id)
        if not status:
            raise HTTPException(status_code=404, detail="Compute execution not found")
        if status.get("status") in {"completed", "failed", "cancelled"}:
            return status
        cancelled = {
            **status,
            "status": "cancelled",
            "updated_at": now_iso(),
            "ended_at": now_iso(),
            "result": None,
            "error": {
                "type": "ExecutionCancelled",
                "message": "The project power control cancelled this compute execution.",
            },
        }
        write_status(execution_id, cancelled)
        process = _execution_processes.get(execution_id)
    if process is not None:
        terminate_process_tree(process)
        with _execution_lock:
            _execution_processes.pop(execution_id, None)
    return read_execution_status(execution_id)


@app.delete("/executions/{execution_id}/record")
def delete_execution_record(execution_id: str) -> dict[str, Any]:
    validate_execution_id(execution_id)
    with _execution_lock:
        status = read_execution_status(execution_id)
        if not status:
            return {"execution_id": execution_id, "status": "not_found", "deleted": True}
        if status.get("status") not in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Active compute execution cannot be deleted")
        if execution_id in _execution_processes:
            raise HTTPException(status_code=409, detail="Compute process is still terminating")
        _execution_futures.pop(execution_id, None)
        shutil.rmtree(execution_dir(execution_id))
    return {"execution_id": execution_id, "status": "deleted", "deleted": True}


@app.post("/execute")
def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility endpoint for callers that do not need restart recovery."""
    try:
        return execute_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def execute_payload(payload: dict[str, Any], *, execution_id: str | None = None) -> dict[str, Any]:
    validate_payload(payload)
    artifact_root = Path(os.getenv("HARNESS_ARTIFACT_ROOT", "/data/artifacts")).resolve()
    workspace = resolve_beneath(
        artifact_root, payload.get("workspace_relative_path"), must_exist=True
    )
    script_path = resolve_beneath(workspace, payload.get("script_path"), must_exist=True)
    if not script_path.is_file():
        raise ValueError("Compute script is not a file")
    arguments = payload.get("arguments") or []
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise ValueError("Compute arguments must be a list of strings")
    requested_device = str(payload.get("requested_device") or "auto")
    fallback_policy = str(payload.get("fallback_policy") or "cpu_on_unavailable")
    if requested_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("Unsupported compute device preference")
    if fallback_policy not in {"cpu_on_unavailable", "fail"}:
        raise ValueError("Unsupported compute fallback policy")
    timeout_seconds = int(payload.get("timeout_seconds") or 3600)
    if timeout_seconds < 1 or timeout_seconds > 24 * 60 * 60:
        raise ValueError("Compute timeout must be between 1 second and 24 hours")

    resources = detect_compute_resources(probe_libraries=True)
    selected_device, fallback_reason = select_compute_device(
        resources,
        requested=requested_device,
        fallback_policy=fallback_policy,
    )
    started_at = datetime.now(timezone.utc)
    timed_out = False
    stdout = ""
    stderr = ""
    if selected_device is None:
        exit_code = 78
        stderr = f"GPU was requested but is unavailable: {fallback_reason}"
    else:
        try:
            process = subprocess.Popen(
                [sys.executable, str(script_path), *arguments],
                cwd=workspace,
                env=compute_environment(selected_device),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            if execution_id is not None:
                with _execution_lock:
                    cancelled_before_start = (
                        read_execution_status(execution_id).get("status") == "cancelled"
                    )
                    if not cancelled_before_start:
                        _execution_processes[execution_id] = process
                if cancelled_before_start:
                    terminate_process_tree(process)
                    raise RuntimeError("Compute execution was cancelled before the process started")
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                stdout, stderr = process.communicate()
                timed_out = True
                exit_code = 124
                stderr += "\nCompute execution exceeded its declared timeout."
            finally:
                if execution_id is not None:
                    with _execution_lock:
                        _execution_processes.pop(execution_id, None)
        except OSError as exc:
            exit_code = 127
            stderr = str(exc)
    ended_at = datetime.now(timezone.utc)
    stdout, stdout_truncated = truncate_output(stdout)
    stderr, stderr_truncated = truncate_output(stderr)
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "selected_device": selected_device,
        "fallback_reason": fallback_reason,
        "resource_snapshot": resources,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "timed_out": timed_out,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "isolation": {
            "execution_mode": "isolated_executor",
            "external_network": False,
            "credentials_mounted": False,
            "metadata_database_mounted": False,
        },
    }


def run_durable_execution(execution_id: str, payload: dict[str, Any]) -> None:
    with _execution_lock:
        if read_execution_status(execution_id).get("status") == "cancelled":
            return
    try:
        result = execute_payload(payload, execution_id=execution_id)
        with _execution_lock:
            status = read_execution_status(execution_id)
            if not status or status.get("status") == "cancelled":
                return
            write_status(
                execution_id,
                {
                    **status,
                    "status": "completed",
                    "updated_at": now_iso(),
                    "ended_at": now_iso(),
                    "result": result,
                    "error": None,
                },
            )
    except Exception as exc:
        with _execution_lock:
            status = read_execution_status(execution_id)
            if not status or status.get("status") == "cancelled":
                return
            write_status(
                execution_id,
                {
                    **status,
                    "status": "failed",
                    "updated_at": now_iso(),
                    "ended_at": now_iso(),
                    "result": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def validate_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "isolated_compute_request.v1":
        raise ValueError("Unsupported isolated compute request schema")


def validate_execution_id(execution_id: str) -> None:
    if not EXECUTION_ID_PATTERN.fullmatch(execution_id):
        raise HTTPException(status_code=422, detail="Invalid compute execution id")


def compute_execution_root() -> Path:
    artifact_root = Path(os.getenv("HARNESS_ARTIFACT_ROOT", "/data/artifacts")).resolve()
    return artifact_root / "_compute_executions"


def execution_dir(execution_id: str) -> Path:
    validate_execution_id(execution_id)
    return compute_execution_root() / execution_id


def read_execution_status(execution_id: str) -> dict[str, Any]:
    return read_json_file(execution_dir(execution_id) / "status.json")


def write_status(execution_id: str, payload: dict[str, Any]) -> None:
    write_json_file(execution_dir(execution_id) / "status.json", payload)


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_beneath(root: Path, value: Any, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Compute path must be a non-empty relative path")
    relative = Path(value.strip())
    if relative.is_absolute():
        raise ValueError("Compute path must be relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Compute path escapes its allowed root")
    if must_exist and not path.exists():
        raise ValueError(f"Compute path does not exist: {relative}")
    return path


def compute_environment(selected_device: str) -> dict[str, str]:
    allowed_names = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "TABLEX_RUNTIME_LOCATION",
        "TABLEX_COMPUTE_DEVICE_MODE",
        "NVIDIA_VISIBLE_DEVICES",
        "NVIDIA_DRIVER_CAPABILITIES",
        "CUDA_VISIBLE_DEVICES",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed_names}
    environment["TABLEX_SELECTED_DEVICE"] = selected_device
    if selected_device == "cpu":
        environment["CUDA_VISIBLE_DEVICES"] = ""
    return environment


def truncate_output(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_CAPTURED_CHARS:
        return value, False
    return value[:MAX_CAPTURED_CHARS], True


def text_from_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
