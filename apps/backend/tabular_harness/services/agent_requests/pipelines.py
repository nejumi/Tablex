from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.config import get_settings
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, ExperimentRun, Project, utc_now
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.jobs import create_job
from tabular_harness.services.research_plans import attach_research_plan_artifact

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
PIPELINE_REQUESTS_DIR = "pipelines"
PIPELINE_REQUEST_SCHEMA_VERSION = "tablex_pipeline_request.v1"
PIPELINE_ACK_SCHEMA_VERSION = "tablex_pipeline_ack.v1"

AppendSessionEvent = Callable[..., Any]


class PipelineToolValidationError(ValueError):
    def __init__(self, message: str, *, issues: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.issues = issues


def pipeline_tool_issue(pointer: str, message: str, **extra: Any) -> dict[str, Any]:
    issue = {"pointer": pointer, "message": message}
    issue.update({key: value for key, value in extra.items() if value is not None})
    return issue


def pipeline_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / PIPELINE_REQUESTS_DIR


def pipeline_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / PIPELINE_REQUESTS_DIR


def process_pipeline_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
) -> None:
    request_dir = pipeline_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = pipeline_acks_dir(workspace)
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
                raise ValueError("Pipeline request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != PIPELINE_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported pipeline request schema_version: {schema_version or '<missing>'}; "
                    f"expected {PIPELINE_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation != "register_prediction_pipeline":
                raise ValueError(f"Unsupported pipeline request operation: {operation or '<missing>'}")
            payload, compatibility_warnings = normalize_pipeline_request_payload(request)
            request_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            job = create_job(
                db,
                job_type="register_prediction_pipeline",
                project_id=project.id,
                input_payload={
                    "schema_version": "prediction_pipeline_registration_job.v1",
                    "agent_session_id": session.id,
                    "request_id": request_id,
                    "operation": operation,
                    "request_hash": request_hash,
                    "request_workspace_relative_path": str(path.relative_to(workspace)),
                    "ack_workspace_relative_path": str(ack_path.relative_to(workspace)),
                    "payload": payload,
                    "compatibility_warnings": compatibility_warnings,
                },
                context={
                    "source": "codex_main_session",
                    "agent_session_id": session.id,
                    "workspace_path": str(workspace),
                },
                policy={
                    "execution": "local_worker",
                    "reason": "prediction pipeline smoke validation can install requirements and execute code",
                },
                priority=35,
                max_attempts=1,
                created_by="codex_main_session",
            )
            ack = {
                "schema_version": PIPELINE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "queued",
                "job_id": job.id,
                "request_hash": request_hash,
                "accepted_at": utc_now().isoformat(),
                "message": "Prediction pipeline registration was accepted and queued for worker validation.",
            }
            if compatibility_warnings:
                ack["compatibility_warnings"] = compatibility_warnings
            write_pipeline_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="pipeline_request_queued",
                    role="harness",
                    title="Prediction pipeline registration queued",
                    content=f"Queued pipeline request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": PIPELINE_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": pipeline_tool_error_payload(exc),
            }
            write_pipeline_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="pipeline_request_failed",
                    role="harness",
                    title="Prediction pipeline request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )


def pipeline_tool_error_payload(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    issues = getattr(exc, "issues", None)
    if isinstance(issues, list):
        payload["issues"] = issues
    return payload


def normalize_pipeline_request_payload(request: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    payload = request.get("payload")
    warnings: list[str] = []
    if isinstance(payload, dict):
        normalized = dict(payload)
    elif payload is None:
        reserved = {"schema_version", "operation", "request_id", "payload"}
        candidate = {key: value for key, value in request.items() if key not in reserved}
        if not candidate:
            raise ValueError("payload must be an object")
        normalized = candidate
        warnings.append("top_level_pipeline_payload_fields")
    else:
        raise ValueError("payload must be an object")

    if "run_ids" in normalized:
        run_ids = require_string_list(normalized.get("run_ids"), "payload.run_ids")
        if "experiment_run_ids" in normalized:
            experiment_run_ids = require_string_list(
                normalized.get("experiment_run_ids"),
                "payload.experiment_run_ids",
            )
            if experiment_run_ids != run_ids:
                raise ValueError("payload.run_ids and payload.experiment_run_ids must match when both are provided")
        else:
            normalized["experiment_run_ids"] = run_ids
            warnings.append("payload.run_ids_alias_for_experiment_run_ids")
    if "experiment_run_ids" not in normalized and isinstance(normalized.get("run_id"), str):
        run_id = str(normalized.get("run_id") or "").strip()
        if run_id:
            normalized["experiment_run_ids"] = [run_id]
            warnings.append("payload.run_id_alias_for_experiment_run_ids")
    if "workspace_dir" not in normalized and isinstance(normalized.get("workspace_path"), str):
        workspace_path = str(normalized.get("workspace_path") or "").strip()
        if workspace_path:
            normalized["workspace_dir"] = workspace_path
            warnings.append("payload.workspace_path_alias_for_workspace_dir")
    if "manifest_workspace_path" not in normalized and isinstance(normalized.get("pipeline_manifest_path"), str):
        manifest_workspace_path = str(normalized.get("pipeline_manifest_path") or "").strip()
        if manifest_workspace_path:
            normalized["manifest_workspace_path"] = manifest_workspace_path
            warnings.append("payload.pipeline_manifest_path_alias_for_manifest_workspace_path")
    if "pipeline_name" not in normalized:
        pipeline_name = str(normalized.get("model_id") or "").strip()
        if not pipeline_name and isinstance(normalized.get("workspace_dir"), str):
            pipeline_name = Path(str(normalized["workspace_dir"])).name.strip()
        if pipeline_name:
            normalized["pipeline_name"] = pipeline_name
            warnings.append("payload.pipeline_name_derived_from_fixed_id")
    return normalized, warnings


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


def write_pipeline_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def execute_pipeline_registration_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    request_id: str,
    payload: dict[str, Any],
    compatibility_warnings: list[str] | None = None,
) -> dict[str, Any]:
    compatibility_warnings = list(compatibility_warnings or [])
    pipeline_name = require_nonempty_string(payload, "pipeline_name")
    workspace_dir_value = require_nonempty_string(payload, "workspace_dir")
    workspace_dir = resolve_workspace_relative_path(workspace, workspace_dir_value)
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        raise ValueError(f"payload.workspace_dir does not exist or is not a directory: {workspace_dir_value}")
    required_files = ["pipeline_manifest.json", "train.py", "predict.py", "requirements.txt", "README.md"]
    missing_files = [name for name in required_files if not (workspace_dir / name).is_file()]
    if missing_files:
        raise ValueError(f"Pipeline directory is missing required files: {', '.join(missing_files)}")
    validate_pipeline_requirements_file(workspace_dir / "requirements.txt")
    submitted_manifest = payload.get("manifest")
    if submitted_manifest is None:
        manifest_path_value = optional_nonempty_string(payload, "manifest_workspace_path")
        if manifest_path_value:
            manifest_path = resolve_workspace_relative_path(workspace, manifest_path_value)
            if manifest_path != workspace_dir / "pipeline_manifest.json":
                compatibility_warnings.append("payload.manifest_workspace_path_used")
        else:
            manifest_path = workspace_dir / "pipeline_manifest.json"
        submitted_manifest = loads_json(manifest_path.read_text(encoding="utf-8"), {})
    if not isinstance(submitted_manifest, dict):
        raise ValueError("payload.manifest or pipeline_manifest.json must be an object")
    manifest, manifest_warnings = normalize_pipeline_manifest(submitted_manifest)
    compatibility_warnings.extend(manifest_warnings)
    run_ids = require_string_list(payload.get("experiment_run_ids", []), "payload.experiment_run_ids")
    if not run_ids:
        raise ValueError("payload.experiment_run_ids must contain at least one run id")
    runs = []
    for run_id in run_ids:
        run = db.get(ExperimentRun, run_id)
        if run is None or run.project_id != project.id:
            raise ValueError(f"payload.experiment_run_ids contains unknown run id {run_id}")
        runs.append(run)
    smoke_validation = smoke_validate_prediction_pipeline(
        workspace_dir,
        workspace=workspace,
        manifest=manifest,
        request_id=request_id,
    )
    metric_reproduction = pipeline_metric_reproduction_summary(manifest=manifest, runs=runs)
    bundle_dir = workspace / "artifacts" / "pipeline_bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", pipeline_name).strip("._") or "prediction_pipeline"
    bundle_path = bundle_dir / f"{safe_name}.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(
            path
            for path in workspace_dir.rglob("*")
            if path.is_file() and should_package_pipeline_file(path, workspace_dir)
        ):
            archive.write(item, item.relative_to(workspace_dir))
    version = next_artifact_version(db, project.id, "prediction_pipeline", safe_name)
    target_dir, stored, content_hash = store.store_existing_file(
        org_id=project.org_id,
        project_id=project.id,
        asset_type="prediction_pipeline",
        name=safe_name,
        version=version,
        source_path=bundle_path,
        filename=bundle_path.name,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "pipeline_name": pipeline_name,
            "workspace_dir": workspace_dir_value,
            "workspace_relative_path": str(bundle_path.relative_to(workspace)),
            "experiment_run_ids": run_ids,
            "research_plan_node_id": optional_nonempty_string(payload, "research_plan_node_id"),
            "pipeline_manifest": manifest,
            "submitted_pipeline_manifest": submitted_manifest if submitted_manifest != manifest else None,
            "compatibility_warnings": compatibility_warnings,
            "smoke_validation": smoke_validation,
            "metric_reproduction": metric_reproduction,
            "primary_path": str(bundle_path),
        },
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="prediction_pipeline",
        name=safe_name,
        uri=str(target_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "pipeline_name": pipeline_name,
            "workspace_dir": workspace_dir_value,
            "workspace_relative_path": str(bundle_path.relative_to(workspace)),
            "experiment_run_ids": run_ids,
            "research_plan_node_id": optional_nonempty_string(payload, "research_plan_node_id"),
            "pipeline_manifest": manifest,
            "submitted_pipeline_manifest": submitted_manifest if submitted_manifest != manifest else None,
            "compatibility_warnings": compatibility_warnings,
            "smoke_validation": smoke_validation,
            "metric_reproduction": metric_reproduction,
            "primary_path": str(target_dir / bundle_path.name),
        },
        version=version,
        org_id=project.org_id,
    )
    for run in runs:
        params = loads_json(run.params_json, {})
        params["pipeline_artifact_id"] = artifact.id
        run.params_json = dumps_json(params)
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="materializes_prediction_pipeline",
            metadata={"request_id": request_id, "pipeline_name": pipeline_name},
        )
        if run.model_version_id:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="model_version",
                from_asset_id=run.model_version_id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="materializes_prediction_pipeline",
                metadata={"request_id": request_id, "pipeline_name": pipeline_name, "experiment_run_id": run.id},
            )
    node_id = optional_nonempty_string(payload, "research_plan_node_id")
    if node_id:
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=node_id,
            artifact_id=artifact.id,
            role="prediction_pipeline",
            metadata={"request_id": request_id, "experiment_run_ids": run_ids},
        )
    return {
        "pipeline_artifact_id": artifact.id,
        "experiment_run_ids": run_ids,
        "bundle_workspace_path": str(bundle_path.relative_to(workspace)),
        "compatibility_warnings": compatibility_warnings,
        "smoke_validation": smoke_validation,
        "metric_reproduction": metric_reproduction,
    }


def should_package_pipeline_file(path: Path, workspace_dir: Path) -> bool:
    relative = path.relative_to(workspace_dir)
    if any(part in {".tablex_smoke", "__pycache__"} for part in relative.parts):
        return False
    if path.suffix in {".pyc", ".pyo"}:
        return False
    return True


def normalize_pipeline_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = loads_json(dumps_json(manifest), {})
    if not isinstance(normalized, dict):
        raise PipelineToolValidationError(
            "pipeline_manifest is invalid",
            issues=[{"pointer": "pipeline_manifest", "message": "must be an object"}],
        )
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    if normalized.get("schema_version") != "pipeline_manifest.v1":
        issues.append(
            {
                "pointer": "pipeline_manifest.schema_version",
                "message": "must be pipeline_manifest.v1",
            }
        )

    input_contract = normalized.get("input_contract")
    if not isinstance(input_contract, dict):
        issues.append({"pointer": "pipeline_manifest.input_contract", "message": "must be an object"})
    else:
        input_warnings, input_issues = normalize_pipeline_input_contract(normalized, input_contract)
        warnings.extend(input_warnings)
        issues.extend(input_issues)

    output_contract = normalized.get("output_contract")
    if not isinstance(output_contract, dict):
        issues.append({"pointer": "pipeline_manifest.output_contract", "message": "must be an object"})
    else:
        output_warnings, output_issues = normalize_pipeline_output_contract(output_contract)
        warnings.extend(output_warnings)
        issues.extend(output_issues)

    for key in ("training", "runtime"):
        if not isinstance(normalized.get(key), dict):
            issues.append({"pointer": f"pipeline_manifest.{key}", "message": "must be an object"})
    expected_metrics = normalized.get("expected_metrics")
    if expected_metrics is not None and not isinstance(expected_metrics, list):
        issues.append({"pointer": "pipeline_manifest.expected_metrics", "message": "must be an array when provided"})
    elif isinstance(expected_metrics, list):
        metric_warnings, metric_issues = normalize_pipeline_expected_metrics(expected_metrics)
        warnings.extend(metric_warnings)
        issues.extend(metric_issues)

    if issues:
        raise PipelineToolValidationError("pipeline_manifest is invalid", issues=issues)
    return normalized, warnings


def normalize_pipeline_input_contract(
    manifest: dict[str, Any],
    input_contract: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    inference_format = input_contract.get("inference_format")
    if not isinstance(inference_format, dict):
        required_columns = string_items(input_contract.get("required_columns"))
        optional_columns = string_items(input_contract.get("optional_columns"))
        if required_columns:
            input_contract["inference_format"] = {
                "columns": [{"name": column, "dtype": "string", "required": True} for column in required_columns]
                + [
                    {"name": column, "dtype": "string", "required": False}
                    for column in optional_columns
                    if column not in set(required_columns)
                ],
                "description": input_contract.get("description") or "normalized from required_columns",
            }
            warnings.append("pipeline_manifest.input_contract.required_columns_normalized")
        else:
            issues.append(
                {
                    "pointer": "pipeline_manifest.input_contract.inference_format",
                    "message": "must be an object or input_contract.required_columns must be a non-empty string array",
                }
            )
    else:
        columns = inference_format.get("columns")
        if isinstance(columns, list):
            normalized_columns, column_warning, column_issues = normalize_pipeline_column_specs(
                columns,
                pointer="pipeline_manifest.input_contract.inference_format.columns",
                default_required=True,
            )
            inference_format["columns"] = normalized_columns
            if column_warning:
                warnings.append("pipeline_manifest.input_contract.inference_format.string_columns_normalized")
            issues.extend(column_issues)
        else:
            issues.append(
                {
                    "pointer": "pipeline_manifest.input_contract.inference_format.columns",
                    "message": "must be a non-empty array",
                }
            )
    history_requirements = input_contract.get("history_requirements")
    if history_requirements is None and "history_requirements" in manifest:
        top_level_history = manifest.get("history_requirements")
        if isinstance(top_level_history, dict):
            input_contract["history_requirements"] = top_level_history
            warnings.append("pipeline_manifest.history_requirements_moved_to_input_contract")
        elif isinstance(top_level_history, list):
            input_contract["history_requirements"] = {
                "required": bool(top_level_history),
                "as_of_column": None,
                "history_window": None,
                "history_format": {"entries": top_level_history} if top_level_history else None,
                "notes": "normalized from top-level history_requirements",
            }
            warnings.append("pipeline_manifest.history_requirements_array_normalized")
    required_tables = input_contract.get("required_tables")
    if required_tables is not None:
        normalized_tables, table_issues = normalize_pipeline_required_tables(required_tables)
        input_contract["required_tables"] = normalized_tables
        issues.extend(table_issues)
    return warnings, issues


def normalize_pipeline_required_tables(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"pointer": "pipeline_manifest.input_contract.required_tables", "message": "must be an array when provided"}]
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    valid_roles = {"primary", "supporting", "history"}
    for index, item in enumerate(value):
        pointer = f"pipeline_manifest.input_contract.required_tables/{index}"
        if not isinstance(item, dict):
            issues.append({"pointer": pointer, "message": "must be an object"})
            continue
        table = dict(item)
        name = table.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append({"pointer": f"{pointer}.name", "message": "is required"})
        else:
            table["name"] = name.strip()
        role = table.get("role")
        if not isinstance(role, str) or role.strip() not in valid_roles:
            issues.append({"pointer": f"{pointer}.role", "message": f"must be one of {sorted(valid_roles)}"})
        else:
            table["role"] = role.strip()
        columns = table.get("columns")
        if not isinstance(columns, list):
            issues.append({"pointer": f"{pointer}.columns", "message": "must be an array"})
        else:
            normalized_columns, _column_warning, column_issues = normalize_pipeline_column_specs(
                columns,
                pointer=f"{pointer}.columns",
                default_required=True,
            )
            table["columns"] = normalized_columns
            issues.extend(column_issues)
        table["join_keys"] = string_items(table.get("join_keys"))
        for optional_key in ("as_of_column", "history_window"):
            optional_value = table.get(optional_key)
            table[optional_key] = optional_value.strip() if isinstance(optional_value, str) and optional_value.strip() else None
        table["optional"] = bool(table.get("optional"))
        normalized.append(table)
    return normalized, issues


def normalize_pipeline_output_contract(output_contract: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    prediction_column = output_contract.get("prediction_column")
    if not isinstance(prediction_column, str) or not prediction_column.strip():
        issues.append(
            {
                "pointer": "pipeline_manifest.output_contract.prediction_column",
                "message": "is required",
            }
        )
    if not isinstance(output_contract.get("columns"), list):
        required_columns = string_items(output_contract.get("required_columns"))
        optional_columns = string_items(output_contract.get("optional_columns"))
        columns: list[dict[str, Any]] = []
        for column in required_columns:
            columns.append(
                {
                    "name": column,
                    "dtype": "float" if isinstance(prediction_column, str) and column == prediction_column else "string",
                }
            )
        required_set = set(required_columns)
        for column in optional_columns:
            if column not in required_set:
                columns.append({"name": column, "dtype": "string"})
        if columns:
            output_contract["columns"] = columns
            warnings.append("pipeline_manifest.output_contract.required_columns_normalized")
        else:
            issues.append(
                {
                    "pointer": "pipeline_manifest.output_contract.columns",
                    "message": "must be an array or output_contract.required_columns must be a non-empty string array",
                }
            )
    else:
        columns = output_contract.get("columns")
        if isinstance(columns, list):
            normalized_columns, column_warning, column_issues = normalize_pipeline_column_specs(
                columns,
                pointer="pipeline_manifest.output_contract.columns",
                default_required=True,
                prediction_column=prediction_column.strip() if isinstance(prediction_column, str) else None,
            )
            output_contract["columns"] = normalized_columns
            if column_warning:
                warnings.append("pipeline_manifest.output_contract.string_columns_normalized")
            issues.extend(column_issues)
    return warnings, issues


def normalize_pipeline_column_specs(
    columns: list[Any],
    *,
    pointer: str,
    default_required: bool,
    prediction_column: str | None = None,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    saw_string = False
    if not columns:
        issues.append({"pointer": pointer, "message": "must be a non-empty array"})
        return normalized, saw_string, issues
    for index, item in enumerate(columns):
        if isinstance(item, str) and item.strip():
            saw_string = True
            name = item.strip()
            normalized.append(
                {
                    "name": name,
                    "dtype": "float" if prediction_column is not None and name == prediction_column else "string",
                    "required": default_required,
                }
            )
            continue
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        issues.append(
            {
                "pointer": f"{pointer}/{index}",
                "message": "must be an object or non-empty string column name",
            }
        )
    return normalized, saw_string, issues


def normalize_pipeline_expected_metrics(metrics: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    warnings: list[str] = []
    issues: list[dict[str, Any]] = []
    for index, item in enumerate(metrics):
        if not isinstance(item, dict):
            issues.append({"pointer": f"pipeline_manifest.expected_metrics/{index}", "message": "must be an object"})
            continue
        metric_name = item.get("metric")
        if "name" not in item and isinstance(metric_name, str) and metric_name.strip():
            item["name"] = metric_name.strip()
            if "pipeline_manifest.expected_metrics.metric_alias_normalized" not in warnings:
                warnings.append("pipeline_manifest.expected_metrics.metric_alias_normalized")
    return warnings, issues


def string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


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


def pipeline_metric_reproduction_summary(
    *,
    manifest: dict[str, Any],
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    expected_metrics = manifest.get("expected_metrics")
    if not isinstance(expected_metrics, list) or not expected_metrics:
        return {
            "schema_version": "prediction_pipeline_metric_reproduction.v1",
            "metric_reproduced": None,
            "reason": "expected_metrics_missing",
            "comparisons": [],
        }
    comparisons: list[dict[str, Any]] = []
    for expected in expected_metrics:
        if not isinstance(expected, dict):
            continue
        metric_name = expected.get("name")
        expected_value = expected.get("value")
        if not isinstance(metric_name, str) or not isinstance(expected_value, (int, float)):
            continue
        observed_values: list[float] = []
        for run in runs:
            metrics = loads_json(run.metrics_json, {})
            value = metrics.get(metric_name)
            if isinstance(value, (int, float)):
                observed_values.append(float(value))
        observed_value = observed_values[0] if observed_values else None
        absolute_delta = abs(float(expected_value) - observed_value) if observed_value is not None else None
        relative_delta = absolute_delta / max(abs(float(expected_value)), 1e-12) if absolute_delta is not None else None
        comparisons.append(
            {
                "metric": metric_name,
                "expected": float(expected_value),
                "observed": observed_value,
                "absolute_delta": absolute_delta,
                "relative_delta": relative_delta,
                "matched": relative_delta is not None and relative_delta <= 0.05,
            }
        )
    matched_values = [item["matched"] for item in comparisons if item.get("observed") is not None]
    return {
        "schema_version": "prediction_pipeline_metric_reproduction.v1",
        "metric_reproduced": all(matched_values) if matched_values else None,
        "reason": None if matched_values else "observed_metric_missing",
        "comparisons": comparisons,
    }


def smoke_validate_prediction_pipeline(
    workspace_dir: Path,
    *,
    workspace: Path | None = None,
    manifest: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    input_contract = manifest.get("input_contract")
    output_contract = manifest.get("output_contract")
    runtime = manifest.get("runtime")
    if not isinstance(input_contract, dict) or not isinstance(output_contract, dict) or not isinstance(runtime, dict):
        raise ValueError("pipeline_manifest input_contract, output_contract, and runtime must be objects")
    inference_format = input_contract.get("inference_format")
    if not isinstance(inference_format, dict):
        raise ValueError("pipeline_manifest.input_contract.inference_format must be an object")
    input_columns = inference_format.get("columns")
    if not isinstance(input_columns, list) or not input_columns:
        raise ValueError("pipeline_manifest.input_contract.inference_format.columns must be a non-empty array")
    column_specs = [item for item in input_columns if isinstance(item, dict)]
    if len(column_specs) != len(input_columns):
        raise ValueError("pipeline_manifest.input_contract.inference_format.columns must contain objects")
    input_column_names = [
        require_manifest_column_name(item, f"input_contract.inference_format.columns/{index}")
        for index, item in enumerate(column_specs)
    ]
    output_column_specs = output_contract.get("columns")
    output_column_names = []
    if isinstance(output_column_specs, list):
        output_column_names = [
            require_manifest_column_name(item, f"output_contract.columns/{index}")
            for index, item in enumerate(output_column_specs)
            if isinstance(item, dict)
        ]
    prediction_column = require_nonempty_string(output_contract, "prediction_column")
    required_output_columns = sorted(set([prediction_column, *output_column_names]))
    smoke_dir = workspace_dir / ".tablex_smoke" / request_id
    smoke_dir.mkdir(parents=True, exist_ok=True)
    input_path = smoke_dir / "input.csv"
    output_path = smoke_dir / "predictions.csv"
    input_row, input_source = smoke_input_row_for_pipeline(
        workspace,
        manifest=manifest,
        input_column_names=input_column_names,
        column_specs=column_specs,
    )
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=input_column_names)
        writer.writeheader()
        writer.writerow(input_row)
    timeout_seconds = runtime.get("timeout_seconds_predict")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        timeout_seconds = 300
    requirements_path = workspace_dir / "requirements.txt"
    smoke_python = ensure_prediction_pipeline_smoke_python(requirements_path)
    try:
        completed = subprocess.run(
            [
                str(smoke_python),
                str(workspace_dir / "predict.py"),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            timeout=min(timeout_seconds, 900),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        seconds = min(timeout_seconds, 900)
        raise PipelineToolValidationError(
            f"Prediction pipeline smoke run timed out after {seconds} second(s)",
            issues=[
                pipeline_tool_issue(
                    "pipeline.predict",
                    "predict.py did not finish within the declared runtime timeout",
                    timeout_seconds=seconds,
                    repair="Make predict.py bounded for one-row validation input or increase runtime.timeout_seconds_predict.",
                )
            ],
        ) from exc
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or completed.stdout or "")[-4000:]
        raise PipelineToolValidationError(
            f"Prediction pipeline smoke run failed with exit code {completed.returncode}: {stderr_tail}",
            issues=[
                pipeline_tool_issue(
                    "pipeline.predict",
                    "predict.py exited with a non-zero status during isolated smoke validation",
                    exit_code=completed.returncode,
                    stderr_tail=stderr_tail,
                    repair=(
                        "Ensure the pipeline directory contains every file predict.py requires, including model "
                        "artifacts under model/ or another path that predict.py resolves inside the pipeline bundle."
                    ),
                )
            ],
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PipelineToolValidationError(
            "Prediction pipeline smoke run did not create a non-empty output file",
            issues=[
                pipeline_tool_issue(
                    "pipeline.output",
                    "predict.py must write a non-empty CSV to the --output path declared by the harness",
                    expected_path=str(output_path),
                    repair="Write predictions.csv to the exact --output argument path.",
                )
            ],
        )
    with output_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        output_columns = list(reader.fieldnames or [])
    if len(rows) != 1:
        raise PipelineToolValidationError(
            f"Prediction pipeline smoke output must contain 1 row; got {len(rows)}",
            issues=[
                pipeline_tool_issue(
                    "pipeline.output.rows",
                    "prediction output row count must match the smoke input row count",
                    expected_rows=1,
                    actual_rows=len(rows),
                )
            ],
        )
    missing_output_columns = [column for column in required_output_columns if column not in output_columns]
    if missing_output_columns:
        raise PipelineToolValidationError(
            f"Prediction pipeline smoke output is missing column(s): {', '.join(missing_output_columns)}",
            issues=[
                pipeline_tool_issue(
                    "pipeline.output.columns",
                    "prediction output must include every column declared in output_contract",
                    missing_columns=missing_output_columns,
                    observed_columns=output_columns,
                )
            ],
        )
    return {
        "schema_version": "prediction_pipeline_smoke_validation.v1",
        "status": "passed",
        "runtime_isolated": True,
        "python_executable": str(smoke_python),
        "requirements_hash": prediction_pipeline_requirements_hash(requirements_path),
        "input_source": input_source,
        "input_rows": 1,
        "output_rows": len(rows),
        "prediction_column": prediction_column,
        "validated_output_columns": required_output_columns,
    }


def smoke_input_row_for_pipeline(
    workspace: Path | None,
    *,
    manifest: dict[str, Any],
    input_column_names: list[str],
    column_specs: list[dict[str, Any]],
) -> tuple[dict[str, str], str]:
    source_path_value = manifest.get("source_data_workspace_path")
    if workspace is not None and isinstance(source_path_value, str) and source_path_value.strip():
        source_path = resolve_workspace_relative_path_allowing_symlink_target(workspace, source_path_value.strip())
        if source_path.is_file():
            with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    if row:
                        return (
                            {
                                column_name: str(row.get(column_name, ""))
                                if row.get(column_name) is not None
                                else ""
                                for column_name in input_column_names
                            },
                            "manifest.source_data_workspace_path",
                        )
    return (
        {
            column_name: smoke_value_for_manifest_dtype(str(spec.get("dtype") or ""))
            for column_name, spec in zip(input_column_names, column_specs, strict=True)
        },
        "synthetic_contract_values",
    )


def ensure_prediction_pipeline_smoke_python(requirements_path: Path) -> Path:
    requirements_hash = prediction_pipeline_requirements_hash(requirements_path)
    python_tag = f"py{sys.version_info.major}.{sys.version_info.minor}"
    env_dir = get_settings().data_dir / "_pipeline_envs" / f"{python_tag}_{requirements_hash[:16]}"
    ready_marker = env_dir / ".tablex_ready"
    python_path = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if ready_marker.exists() and python_path.exists():
        return python_path
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    if not python_path.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(env_dir)],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    if prediction_pipeline_requirements_has_installable_lines(requirements_path):
        completed = subprocess.run(
            [
                str(python_path),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or completed.stdout or "")[-4000:]
            raise PipelineToolValidationError(
                f"Prediction pipeline requirements install failed: {stderr_tail}",
                issues=[
                    pipeline_tool_issue(
                        "pipeline.requirements",
                        "requirements.txt could not be installed in the isolated smoke environment",
                        stderr_tail=stderr_tail,
                        repair="Keep requirements minimal and installable from the configured Python package indexes.",
                    )
                ],
            )
    ready_marker.write_text(
        dumps_json(
            {
                "schema_version": "prediction_pipeline_smoke_env.v1",
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "requirements_hash": requirements_hash,
            }
        ),
        encoding="utf-8",
    )
    return python_path


def prediction_pipeline_requirements_hash(requirements_path: Path) -> str:
    try:
        payload = requirements_path.read_bytes()
    except OSError as exc:
        raise ValueError("Pipeline requirements.txt could not be read") from exc
    digest = hashlib.sha256()
    digest.update(f"python:{sys.version_info.major}.{sys.version_info.minor}\n".encode("utf-8"))
    digest.update(payload)
    return digest.hexdigest()


def prediction_pipeline_requirements_has_installable_lines(requirements_path: Path) -> bool:
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("Pipeline requirements.txt could not be read") from exc
    return any(line.strip() and not line.strip().startswith("#") for line in lines)


def require_manifest_column_name(item: dict[str, Any], pointer: str) -> str:
    value = item.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"pipeline_manifest.{pointer}.name is required")
    return value.strip()


def validate_pipeline_requirements_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("Pipeline requirements.txt could not be read") from exc
    blocked_prefixes = (
        "-r",
        "--requirement",
        "-c",
        "--constraint",
        "--index-url",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--trusted-host",
        "--editable",
        "-e",
    )
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(blocked_prefixes):
            raise ValueError(f"requirements.txt line {index} uses unsupported installer option")
        if "://" in line or line.startswith((".", "/", "~")):
            raise ValueError(f"requirements.txt line {index} must name a package requirement, not a URL or local path")


def smoke_value_for_manifest_dtype(dtype: str) -> str:
    normalized = dtype.lower()
    if any(token in normalized for token in ("int", "float", "double", "decimal", "number", "numeric")):
        return "1"
    if "bool" in normalized:
        return "true"
    if "date" in normalized or "time" in normalized:
        return "2026-01-01T00:00:00Z"
    return "sample"


def resolve_workspace_relative_path(workspace: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("workspace paths must be relative to the AgentSession workspace")
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("workspace path escapes the AgentSession workspace") from exc
    return resolved


def resolve_workspace_relative_path_allowing_symlink_target(workspace: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("workspace paths must be relative to the AgentSession workspace")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("workspace paths must not contain parent-directory segments")
    return workspace / candidate
