from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from tabular_harness.core.runtime_resources import detect_compute_resources, select_compute_device

EXECUTION_SCHEMA_VERSION = "isolated_compute_execution.v1"
MAX_CAPTURED_CHARS = 4 * 1024 * 1024

app = FastAPI(title="Tablex isolated compute executor", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/execute")
def execute(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return execute_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def execute_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "isolated_compute_request.v1":
        raise ValueError("Unsupported isolated compute request schema")
    artifact_root = Path(os.getenv("HARNESS_ARTIFACT_ROOT", "/data/artifacts")).resolve()
    workspace = resolve_beneath(artifact_root, payload.get("workspace_relative_path"), must_exist=True)
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
            completed = subprocess.run(
                [sys.executable, str(script_path), *arguments],
                cwd=workspace,
                env=compute_environment(selected_device),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = text_from_timeout_stream(exc.stdout)
            stderr = (
                text_from_timeout_stream(exc.stderr)
                + "\nCompute execution exceeded its declared timeout."
            )
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
