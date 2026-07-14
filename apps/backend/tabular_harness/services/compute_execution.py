from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.core.runtime_resources import detect_compute_resources, select_compute_device
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    ExperimentRun,
    Job,
    Project,
    utc_now,
)
from tabular_harness.services.agent_requests.compute import (
    COMPUTE_ACK_SCHEMA_VERSION,
    write_compute_ack,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)


def execute_agent_compute_job(
    db: Session,
    *,
    store: LocalArtifactStore,
    job: Job,
) -> dict[str, Any]:
    project = require_project(db, job)
    job_input = loads_json(job.input_json, {})
    payload = job_input.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Agent compute job payload is missing")
    session_id = str(job_input.get("agent_session_id") or "").strip()
    session = db.get(AgentSession, session_id)
    if session is None or session.project_id != project.id or not session.workspace_path:
        raise ValueError("Agent compute job session was not found")
    workspace = resolve_runtime_data_path(session.workspace_path).resolve()
    script_path = resolve_workspace_path(workspace, payload.get("script_path"), must_exist=True)
    result_manifest_path = resolve_workspace_path(
        workspace,
        payload.get("result_manifest_path"),
        must_exist=False,
    )
    requested_device = str(payload.get("device_preference") or "auto")
    fallback_policy = str(payload.get("fallback_policy") or "cpu_on_unavailable")
    execution = run_compute_script(
        store=store,
        execution_id=job.id,
        workspace=workspace,
        script_path=script_path,
        arguments=list(payload.get("arguments") or []),
        requested_device=requested_device,
        fallback_policy=fallback_policy,
        timeout_seconds=int(payload.get("timeout_seconds") or 3600),
    )
    resources = execution["resource_snapshot"]
    selected_device = execution["selected_device"]
    fallback_reason = execution["fallback_reason"]
    started_at = datetime.fromisoformat(execution["started_at"])
    ended_at = datetime.fromisoformat(execution["ended_at"])
    timed_out = execution["timed_out"]
    exit_code = execution["exit_code"]
    stdout = execution["stdout"]
    stderr = execution["stderr"]
    selection_error = None
    if selected_device is None:
        selection_error = f"GPU was requested but is unavailable: {fallback_reason}"
    log_metadata = {
        "schema_version": "compute_log.v1",
        "job_id": job.id,
        "agent_session_id": session.id,
        "requested_device": requested_device,
        "selected_device": selected_device,
    }
    stdout_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="compute_stdout",
        name=f"compute_stdout_{job.id}",
        filename="stdout.log",
        text=stdout,
        metadata={**log_metadata, "stream": "stdout"},
    )
    stderr_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="compute_stderr",
        name=f"compute_stderr_{job.id}",
        filename="stderr.log",
        text=stderr,
        metadata={**log_metadata, "stream": "stderr"},
    )
    result_manifest, result_manifest_error = read_compute_result_manifest(result_manifest_path)
    if selection_error is not None:
        result_manifest_error = selection_error
    registered_outputs: list[Artifact] = []
    if exit_code == 0 and result_manifest_error is None:
        try:
            registered_outputs = register_declared_outputs(
                db,
                store=store,
                project=project,
                workspace=workspace,
                job=job,
                declarations=payload.get("outputs"),
            )
        except (OSError, ValueError) as exc:
            result_manifest_error = f"Declared compute outputs could not be registered: {exc}"
    actual_device = result_manifest.get("actual_device") if result_manifest else None
    actual_device_status = "agent_reported" if actual_device in {"cpu", "gpu"} else "missing"
    if selected_device == "cpu" and actual_device == "gpu":
        result_manifest_error = "Compute result reported GPU use after the worker selected CPU."
    evidence_payload = {
        "schema_version": "compute_resource_evidence.v1",
        "job_id": job.id,
        "agent_session_id": session.id,
        "experiment_run_id": payload.get("experiment_run_id"),
        "decision_context": payload.get("decision_context"),
        "requested_device": requested_device,
        "selected_device": selected_device,
        "fallback_policy": fallback_policy,
        "fallback_reason": fallback_reason,
        "actual_device": actual_device,
        "actual_device_status": actual_device_status,
        "resource_snapshot": resources,
        "execution": {
            "script_path": str(script_path.relative_to(workspace)),
            "arguments": list(payload.get("arguments") or []),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": (ended_at - started_at).total_seconds(),
            "exit_code": exit_code,
            "timed_out": timed_out,
            **execution["isolation"],
            "stdout_truncated": execution.get("stdout_truncated", False),
            "stderr_truncated": execution.get("stderr_truncated", False),
        },
        "result_manifest": result_manifest,
        "result_manifest_error": result_manifest_error,
        "stdout_artifact_id": stdout_artifact.id,
        "stderr_artifact_id": stderr_artifact.id,
        "output_artifact_ids": [artifact.id for artifact in registered_outputs],
    }
    evidence = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="compute_resource_evidence",
        name=f"compute_resource_evidence_{job.id}",
        filename="compute_resource_evidence.json",
        payload=evidence_payload,
        metadata={
            "schema_version": "compute_resource_evidence.v1",
            "job_id": job.id,
            "agent_session_id": session.id,
            "experiment_run_id": payload.get("experiment_run_id"),
            "requested_device": requested_device,
            "selected_device": selected_device,
            "actual_device": actual_device,
            "fallback_reason": fallback_reason,
            "exit_code": exit_code,
        },
        created_by=job.created_by,
    )
    for artifact in [stdout_artifact, stderr_artifact, *registered_outputs]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=evidence.id,
            relation_type="supports_compute_resource_evidence",
            org_id=project.org_id,
        )
    attach_evidence_to_run(
        db,
        project=project,
        run_id=payload.get("experiment_run_id"),
        evidence=evidence,
        selected_device=selected_device,
        actual_device=actual_device,
        fallback_reason=fallback_reason,
    )
    succeeded = exit_code == 0 and result_manifest_error is None
    ack = {
        "schema_version": COMPUTE_ACK_SCHEMA_VERSION,
        "request_id": job_input.get("request_id"),
        "operation": "execute",
        "status": "completed" if succeeded else "failed",
        "job_id": job.id,
        "processed_at": utc_now().isoformat(),
        "selected_device": selected_device,
        "actual_device": actual_device,
        "fallback_reason": fallback_reason,
        "compute_resource_evidence_artifact_id": evidence.id,
        "output_artifact_ids": [artifact.id for artifact in registered_outputs],
    }
    ack_path = resolve_workspace_path(
        workspace,
        job_input.get("ack_workspace_relative_path"),
        must_exist=False,
    )
    write_compute_ack(ack_path, ack)
    from tabular_harness.services.agent_sessions import append_session_event

    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="compute_request_completed" if succeeded else "compute_request_failed",
        role="harness",
        title="Compute run completed" if succeeded else "Compute run failed",
        content=(
            "The requested child compute completed and its result artifacts are available."
            if succeeded
            else str(result_manifest_error or f"Compute script exited with code {exit_code}")
        ),
        payload={**ack, "workspace_relative_path": str(ack_path.relative_to(workspace))},
        artifact_id=evidence.id,
        update_heartbeat=False,
    )
    result = {
        "schema_version": "agent_compute_job_result.v1",
        "job_status": "succeeded" if succeeded else "failed",
        "error_message": None
        if succeeded
        else result_manifest_error or f"Compute script exited with code {exit_code}",
        "selected_device": selected_device,
        "actual_device": actual_device,
        "fallback_reason": fallback_reason,
        "compute_resource_evidence_artifact_id": evidence.id,
        "stdout_artifact_id": stdout_artifact.id,
        "stderr_artifact_id": stderr_artifact.id,
        "artifact_id": evidence.id,
        "artifact_ids": [
            evidence.id,
            stdout_artifact.id,
            stderr_artifact.id,
            *[artifact.id for artifact in registered_outputs],
        ],
    }
    return result


def cancel_agent_compute_executions(
    execution_ids: list[str],
    *,
    purge_records: bool = False,
) -> dict[str, Any]:
    """Cancel durable child compute and verify that no requested execution remains active."""
    unique_ids = list(dict.fromkeys(execution_ids))
    executor_url = os.getenv("TABLEX_COMPUTE_EXECUTOR_URL", "").strip()
    if not unique_ids:
        return {
            "schema_version": "agent_compute_cancellation.v1",
            "requested_count": 0,
            "cancelled_count": 0,
            "deleted_count": 0,
            "remaining_count": 0,
            "executions": [],
        }
    if not executor_url:
        return {
            "schema_version": "agent_compute_cancellation.v1",
            "requested_count": len(unique_ids),
            "cancelled_count": 0,
            "deleted_count": 0,
            "remaining_count": len(unique_ids),
            "executions": [
                {"execution_id": execution_id, "status": "executor_not_configured"}
                for execution_id in unique_ids
            ],
        }

    executions: list[dict[str, Any]] = []
    for execution_id in unique_ids:
        url = f"{executor_url.rstrip('/')}/executions/{execution_id}"
        try:
            response = httpx.delete(url, timeout=15)
            if response.status_code == 404:
                executions.append({"execution_id": execution_id, "status": "not_started"})
                continue
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status") if isinstance(payload, dict) else None
            if purge_records and status in {"cancelled", "completed", "failed"}:
                purge_response = httpx.delete(f"{url}/record", timeout=15)
                purge_response.raise_for_status()
                status = "deleted"
            executions.append(
                {"execution_id": execution_id, "status": status or "invalid_response"}
            )
        except (httpx.HTTPError, ValueError) as exc:
            executions.append(
                {
                    "execution_id": execution_id,
                    "status": "cancellation_failed",
                    "error_type": type(exc).__name__,
                }
            )
    terminal_statuses = {"cancelled", "completed", "failed", "not_started", "deleted"}
    remaining_count = sum(1 for item in executions if item["status"] not in terminal_statuses)
    return {
        "schema_version": "agent_compute_cancellation.v1",
        "requested_count": len(unique_ids),
        "cancelled_count": sum(1 for item in executions if item["status"] == "cancelled"),
        "deleted_count": sum(1 for item in executions if item["status"] == "deleted"),
        "remaining_count": remaining_count,
        "executions": executions,
    }


def run_compute_script(
    *,
    store: LocalArtifactStore,
    execution_id: str,
    workspace: Path,
    script_path: Path,
    arguments: list[str],
    requested_device: str,
    fallback_policy: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    executor_url = os.getenv("TABLEX_COMPUTE_EXECUTOR_URL", "").strip()
    if executor_url:
        root = store.root.resolve()
        try:
            workspace_relative_path = str(workspace.relative_to(root))
        except ValueError as exc:
            raise ValueError("Compute workspace is outside the shared artifact root") from exc
        request_payload = {
            "schema_version": "isolated_compute_request.v1",
            "workspace_relative_path": workspace_relative_path,
            "script_path": str(script_path.relative_to(workspace)),
            "arguments": arguments,
            "requested_device": requested_device,
            "fallback_policy": fallback_policy,
            "timeout_seconds": timeout_seconds,
        }
        execution_url = f"{executor_url.rstrip('/')}/executions/{execution_id}"
        deadline = time.monotonic() + timeout_seconds + 90
        submit_required = True
        while True:
            try:
                if submit_required:
                    response = httpx.post(execution_url, json=request_payload, timeout=30)
                    submit_required = False
                else:
                    response = httpx.get(execution_url, timeout=30)
                response.raise_for_status()
            except httpx.RequestError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Compute executor did not become reachable before its declared timeout"
                    ) from exc
                submit_required = True
                time.sleep(2)
                continue
            status_payload = response.json()
            if (
                not isinstance(status_payload, dict)
                or status_payload.get("schema_version") != "isolated_compute_status.v1"
            ):
                raise ValueError("Compute executor returned an invalid execution status")
            status = status_payload.get("status")
            if status == "completed":
                result = status_payload.get("result")
                if (
                    not isinstance(result, dict)
                    or result.get("schema_version") != "isolated_compute_execution.v1"
                ):
                    raise ValueError("Compute executor completed without a valid result")
                return result
            if status == "failed":
                error = status_payload.get("error")
                message = error.get("message") if isinstance(error, dict) else None
                raise ValueError(str(message or "Compute executor failed"))
            if status == "cancelled":
                raise RuntimeError("Compute execution was cancelled by the project power control")
            if status == "interrupted":
                submit_required = True
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Compute executor did not reach a terminal state before its declared timeout"
                )
            time.sleep(2)
    return run_compute_script_locally(
        workspace=workspace,
        script_path=script_path,
        arguments=arguments,
        requested_device=requested_device,
        fallback_policy=fallback_policy,
        timeout_seconds=timeout_seconds,
    )


def run_compute_script_locally(
    *,
    workspace: Path,
    script_path: Path,
    arguments: list[str],
    requested_device: str,
    fallback_policy: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    resources = detect_compute_resources(probe_libraries=True)
    selected_device, fallback_reason = select_compute_device(
        resources,
        requested=requested_device,
        fallback_policy=fallback_policy,
    )
    started_at = datetime.now(timezone.utc)
    timed_out = False
    if selected_device is None:
        exit_code = 78
        stdout = ""
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
    return {
        "schema_version": "isolated_compute_execution.v1",
        "selected_device": selected_device,
        "fallback_reason": fallback_reason,
        "resource_snapshot": resources,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "isolation": {
            "execution_mode": "local_subprocess",
            "external_network": None,
            "credentials_mounted": None,
            "metadata_database_mounted": None,
        },
    }


def compute_environment(selected_device: str) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "PYTHONPATH",
            "HARNESS_DATA_DIR",
            "TABLEX_RUNTIME_LOCATION",
            "TABLEX_COMPUTE_DEVICE_MODE",
            "NVIDIA_VISIBLE_DEVICES",
            "NVIDIA_DRIVER_CAPABILITIES",
            "CUDA_VISIBLE_DEVICES",
        }
    }
    allowed["TABLEX_SELECTED_DEVICE"] = selected_device
    if selected_device == "cpu":
        allowed["CUDA_VISIBLE_DEVICES"] = ""
    return allowed


def read_compute_result_manifest(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, "Compute script did not create the declared result manifest."
    try:
        value = loads_json(path.read_text(encoding="utf-8"), {})
    except OSError as exc:
        return {}, f"Compute result manifest could not be read: {exc}"
    if not isinstance(value, dict):
        return {}, "Compute result manifest must be a JSON object."
    if value.get("schema_version") != "compute_result.v1":
        return value, "Compute result manifest schema_version must be compute_result.v1."
    if value.get("actual_device") not in {"cpu", "gpu"}:
        return value, "Compute result manifest actual_device must be cpu or gpu."
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        return value, "Compute result manifest summary is required."
    return value, None


def register_declared_outputs(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    workspace: Path,
    job: Job,
    declarations: Any,
) -> list[Artifact]:
    if not isinstance(declarations, list):
        return []
    artifacts: list[Artifact] = []
    for item in declarations:
        if not isinstance(item, dict):
            continue
        source_path = resolve_workspace_path(workspace, item.get("path"), must_exist=True)
        if not source_path.is_file():
            raise ValueError(
                f"Declared compute output is not a file: {source_path.relative_to(workspace)}"
            )
        asset_type = str(item.get("asset_type") or "compute_output")
        name = str(item.get("name") or f"compute_output_{new_id('out')}")
        version = next_artifact_version(db, project.id, asset_type, name)
        artifact_dir, stored, content_hash = store.store_existing_file(
            org_id=project.org_id,
            project_id=project.id,
            asset_type=asset_type,
            name=name,
            version=version,
            source_path=source_path,
            filename=source_path.name,
            metadata={
                "job_id": job.id,
                "workspace_relative_path": str(source_path.relative_to(workspace)),
            },
        )
        artifacts.append(
            register_artifact(
                db,
                project_id=project.id,
                asset_type=asset_type,
                name=name,
                uri=str(artifact_dir),
                content_hash=content_hash,
                size_bytes=stored.size_bytes,
                metadata={
                    "job_id": job.id,
                    "workspace_relative_path": str(source_path.relative_to(workspace)),
                    "primary_path": str(stored.path),
                },
                version=version,
                org_id=project.org_id,
                created_by=job.created_by,
            )
        )
    return artifacts


def attach_evidence_to_run(
    db: Session,
    *,
    project: Project,
    run_id: Any,
    evidence: Artifact,
    selected_device: str | None,
    actual_device: Any,
    fallback_reason: str | None,
) -> None:
    if not isinstance(run_id, str) or not run_id:
        return
    run = db.get(ExperimentRun, run_id)
    if run is None or run.project_id != project.id:
        return
    params = loads_json(run.params_json, {})
    artifact_ids = params.get("compute_resource_evidence_artifact_ids")
    if not isinstance(artifact_ids, list):
        artifact_ids = []
    if evidence.id not in artifact_ids:
        artifact_ids.append(evidence.id)
    params["compute_resource_evidence_artifact_ids"] = artifact_ids
    params["selected_compute_device"] = selected_device
    params["actual_compute_device"] = actual_device
    params["compute_fallback_reason"] = fallback_reason
    run.params_json = dumps_json(params)
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="experiment_run",
        from_asset_id=run.id,
        to_asset_type="artifact",
        to_asset_id=evidence.id,
        relation_type="executed_with_compute_resources",
        org_id=project.org_id,
    )


def resolve_workspace_path(workspace: Path, value: Any, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Compute job contains an invalid workspace path")
    relative = Path(value.strip())
    if relative.is_absolute():
        raise ValueError("Compute job workspace paths must be relative")
    path = (workspace / relative).resolve()
    if not path.is_relative_to(workspace):
        raise ValueError("Compute job workspace path escapes the session workspace")
    if must_exist and not path.exists():
        raise ValueError(f"Compute job workspace path does not exist: {relative}")
    return path


def require_project(db: Session, job: Job) -> Project:
    project = db.get(Project, job.project_id) if job.project_id else None
    if project is None:
        raise ValueError("Agent compute job project was not found")
    return project


def text_from_timeout_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
