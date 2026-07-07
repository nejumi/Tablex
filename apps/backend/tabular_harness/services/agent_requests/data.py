from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, Artifact, DatasetSnapshot, Project, utc_now
from tabular_harness.services.agent_inbox import write_inbox_entry
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.dataset_profile import profile_dataset_artifact
from tabular_harness.services.research_plans import attach_research_plan_artifact

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
DATA_REQUESTS_DIR = "data"
DATA_REQUEST_SCHEMA_VERSION = "tablex_data_request.v1"
DATA_ACK_SCHEMA_VERSION = "tablex_data_ack.v1"
TASK_SPEC_SCHEMA_VERSION = "task_spec.v1"

AppendSessionEvent = Callable[..., Any]


def data_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / DATA_REQUESTS_DIR


def data_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / DATA_REQUESTS_DIR


def process_data_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
) -> None:
    request_dir = data_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = data_acks_dir(workspace)
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
                raise ValueError("Data request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != DATA_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported data request schema_version: {schema_version or '<missing>'}; "
                    f"expected {DATA_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = execute_data_tool_request(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                operation=operation,
                payload=payload,
            )
            ack = {
                "schema_version": DATA_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_data_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="data_request_succeeded",
                    role="harness",
                    title="Data request processed",
                    content=f"Processed data request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    artifact_id=result.get("artifact_id"),
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": DATA_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_data_tool_ack(ack_path, ack)
            write_data_request_rejection_to_workspace_inbox(
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
                    event_type="data_request_failed",
                    role="harness",
                    title="Data request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )


def execute_data_tool_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if operation == "set_primary_table":
        dataset = data_request_dataset_reference(db, store=store, project=project, payload=payload)
        project.primary_dataset_snapshot_id = dataset.id
        project.updated_at = utc_now()
        artifact = db.get(Artifact, dataset.artifact_id)
        if artifact is not None:
            metadata = loads_json(artifact.metadata_json, {})
            artifact.metadata_json = dumps_json(
                {
                    **metadata,
                    "selected_as_primary_dataset_snapshot_id": dataset.id,
                    "selected_as_project_primary_at": utc_now().isoformat(),
                    "selected_by": "codex_data_request",
                }
            )
        return {"dataset_snapshot_id": dataset.id, "artifact_id": dataset.artifact_id}
    if operation == "register_derived_table":
        return execute_register_derived_table_request(
            db,
            store=store,
            project=project,
            workspace=workspace,
            payload=payload,
        )
    if operation == "commit_task_spec":
        task_spec = payload.get("task_spec")
        if not isinstance(task_spec, dict):
            raise ValueError("payload.task_spec is required for commit_task_spec")
        return execute_commit_task_spec_request(
            db,
            store=store,
            project=project,
            session=session,
            task_spec=task_spec,
            research_plan_node_id=optional_nonempty_string(payload, "research_plan_node_id"),
        )
    raise ValueError(f"Unsupported data request operation: {operation or '<missing>'}")


DATA_REQUEST_TABLE_SUFFIXES = {".csv", ".parquet"}


def data_request_dataset_reference(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    payload: dict[str, Any],
) -> DatasetSnapshot:
    dataset_snapshot_id = optional_nonempty_string(payload, "dataset_snapshot_id")
    artifact_id = optional_nonempty_string(payload, "artifact_id")
    if bool(dataset_snapshot_id) == bool(artifact_id):
        raise ValueError("Provide exactly one of payload.dataset_snapshot_id or payload.artifact_id")
    if dataset_snapshot_id:
        dataset = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset is None or dataset.project_id != project.id:
            raise ValueError("dataset_snapshot_id does not belong to this project")
        return dataset
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise ValueError("artifact_id does not belong to this project")
    dataset = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id, DatasetSnapshot.artifact_id == artifact.id)
        .order_by(DatasetSnapshot.created_at.desc())
        .limit(1)
    )
    if dataset is None:
        if artifact.asset_type not in {"dataset_snapshot", "uploaded_supporting_table"}:
            raise ValueError("artifact_id must reference an uploaded table artifact")
        source_path = artifact_primary_path(artifact)
        if source_path.suffix.lower() not in DATA_REQUEST_TABLE_SUFFIXES:
            raise ValueError("artifact_id must reference a CSV or Parquet table artifact")
        metadata = loads_json(artifact.metadata_json, {})
        dataset = profile_dataset_artifact(
            db,
            store,
            project,
            artifact,
            project.target_column,
            source_type="codex_selected_primary_table",
            source_ref=str(metadata.get("source_filename") or metadata.get("table_name") or artifact.name),
        )
    return dataset


def execute_register_derived_table_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    workspace: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workspace_path = optional_nonempty_string(payload, "workspace_path")
    if not workspace_path:
        raise ValueError("payload.workspace_path is required for register_derived_table")
    source_path = resolve_workspace_relative_path(workspace, workspace_path)
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"workspace_path does not exist under the workspace: {workspace_path}")
    if source_path.suffix.lower() not in {".csv", ".parquet"}:
        raise ValueError("register_derived_table workspace_path must be a CSV or Parquet file")
    derivation = payload.get("derivation")
    if not isinstance(derivation, dict):
        raise ValueError("payload.derivation must be an object")
    source_ids = derivation.get("source_dataset_snapshot_ids")
    if not isinstance(source_ids, list):
        source_ids = []
    verified_source_ids: list[str] = []
    for item in source_ids:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("derivation.source_dataset_snapshot_ids must contain dataset snapshot ids")
        dataset = db.get(DatasetSnapshot, item.strip())
        if dataset is None or dataset.project_id != project.id:
            raise ValueError(f"source_dataset_snapshot_id does not belong to this project: {item}")
        verified_source_ids.append(dataset.id)
    table_name = optional_nonempty_string(payload, "name") or source_path.stem
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", table_name).strip("._") or "derived_table"
    artifact_name = f"derived_table_{safe_name}_{new_id('dt')}"
    metadata = {
        "project_id": project.id,
        "source": "codex_data_request",
        "workspace_relative_path": workspace_path,
        "table_name": table_name,
        "derivation": derivation,
        "row_granularity": payload.get("row_granularity"),
    }
    version = next_artifact_version(db, project.id, "dataset_snapshot", artifact_name)
    artifact_dir, stored, content_hash = store.store_existing_file(
        org_id="local-org",
        project_id=project.id,
        asset_type="dataset_snapshot",
        name=artifact_name,
        version=version,
        source_path=source_path,
        filename=source_path.name,
        metadata=metadata,
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="dataset_snapshot",
        name=artifact_name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
        created_by="codex_main_session",
    )
    dataset = profile_dataset_artifact(
        db,
        store,
        project,
        artifact,
        project.target_column,
        source_type="codex_derived_table",
        source_ref=table_name,
    )
    for source_id in verified_source_ids:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=source_id,
            to_asset_type="dataset_snapshot",
            to_asset_id=dataset.id,
            relation_type="derived_table_input",
        )
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_id": artifact.id,
        "workspace_path": workspace_path,
        "source_dataset_snapshot_ids": verified_source_ids,
    }


def execute_commit_task_spec_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession | None,
    task_spec: dict[str, Any],
    research_plan_node_id: str | None,
    source: str = "data_tool_request",
) -> dict[str, Any]:
    return commit_task_spec_artifact(
        db,
        store=store,
        project=project,
        session=session,
        task_spec=task_spec,
        research_plan_node_id=research_plan_node_id,
        source=source,
        update_project_task_type=True,
        update_project_target_column=True,
    )


def commit_task_spec_artifact(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession | None,
    task_spec: dict[str, Any],
    research_plan_node_id: str | None,
    source: str,
    update_project_task_type: bool,
    update_project_target_column: bool,
) -> dict[str, Any]:
    normalized = validate_task_spec_payload(db, project=project, task_spec=task_spec)
    metadata: dict[str, Any] = {
        "project_id": project.id,
        "source": source,
        "status": normalized["status"],
        "task_shape": normalized["task_shape"],
        "research_plan_node_id": research_plan_node_id,
    }
    if session is not None:
        metadata["agent_session_id"] = session.id
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="task_spec",
        name=f"task_spec_{new_id('tspec')}",
        filename="task_spec.json",
        payload=normalized,
        metadata=metadata,
    )
    for dataset_id in task_spec_dataset_ids(normalized):
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset_id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="referenced_by_task_spec",
        )
    if research_plan_node_id:
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=research_plan_node_id,
            artifact_id=artifact.id,
            role="task_spec",
            metadata={"source": source},
        )
    if update_project_task_type:
        project.task_type = normalized["task_shape"]
    if update_project_target_column:
        project.target_column = denormalized_target_column_from_task_spec(normalized)
    project.updated_at = utc_now()
    return {
        "task_spec_artifact_id": artifact.id,
        "artifact_id": artifact.id,
        "task_shape": normalized["task_shape"],
        "status": normalized["status"],
        "target_column": project.target_column,
    }


def record_user_confirmed_task_spec_for_project_edit(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    target_column: str | None,
    table_ref: str | None = None,
) -> dict[str, Any] | None:
    target = target_column.strip() if isinstance(target_column, str) else ""
    if not target:
        return None
    task_shape = project.task_type if project.task_type in TASK_SPEC_SHAPES else "other"
    target_payload: dict[str, Any] = {"column": target, "derivation": None}
    granularity: dict[str, Any] = {}
    if table_ref:
        target_payload["table_ref"] = table_ref
        granularity["table_ref"] = table_ref
    return commit_task_spec_artifact(
        db,
        store=store,
        project=project,
        session=None,
        task_spec={
            "schema_version": TASK_SPEC_SCHEMA_VERSION,
            "objective_text": target,
            "task_shape": task_shape,
            "targets": [target_payload],
            "granularity": granularity,
            "assumptions": [],
            "status": "user_confirmed",
        },
        research_plan_node_id=None,
        source="user_project_update",
        update_project_task_type=False,
        update_project_target_column=True,
    )


TASK_SPEC_SHAPES = {
    "supervised_regression",
    "supervised_classification",
    "multilabel",
    "multi_target",
    "clustering",
    "anomaly_detection",
    "forecasting",
    "distribution_prediction",
    "aggregate_prediction",
    "inverse_optimization",
    "exploratory",
    "other",
}
TASK_SPEC_STATUSES = {"provisional", "user_confirmed", "superseded", "rejected"}


def validate_task_spec_payload(db: Session, *, project: Project, task_spec: dict[str, Any]) -> dict[str, Any]:
    if task_spec.get("schema_version") != TASK_SPEC_SCHEMA_VERSION:
        raise ValueError(f"task_spec.schema_version must be {TASK_SPEC_SCHEMA_VERSION}")
    objective_text = task_spec.get("objective_text")
    if not isinstance(objective_text, str) or not objective_text.strip():
        raise ValueError("task_spec.objective_text must be a non-empty string")
    task_shape = task_spec.get("task_shape")
    if task_shape not in TASK_SPEC_SHAPES:
        raise ValueError(f"task_spec.task_shape must be one of {sorted(TASK_SPEC_SHAPES)}")
    status = task_spec.get("status")
    if status not in TASK_SPEC_STATUSES:
        raise ValueError(f"task_spec.status must be one of {sorted(TASK_SPEC_STATUSES)}")
    targets = task_spec.get("targets")
    if not isinstance(targets, list):
        raise ValueError("task_spec.targets must be a list; use [] for unsupervised or exploratory tasks")
    granularity = task_spec.get("granularity")
    if not isinstance(granularity, dict):
        raise ValueError("task_spec.granularity must be an object")
    assumptions = task_spec.get("assumptions")
    if not isinstance(assumptions, list):
        raise ValueError("task_spec.assumptions must be a list")
    normalized = dict(task_spec)
    normalized["objective_text"] = objective_text.strip()
    normalized["task_shape"] = str(task_shape)
    normalized["status"] = str(status)
    normalized["targets"] = targets
    normalized["granularity"] = granularity
    normalized["assumptions"] = assumptions
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ValueError(f"task_spec.targets[{index}] must be an object")
        column = target.get("column")
        if column is not None and (not isinstance(column, str) or not column.strip()):
            raise ValueError(f"task_spec.targets[{index}].column must be a non-empty string when provided")
        table_ref = target.get("table_ref")
        if table_ref is not None and (not isinstance(table_ref, str) or not table_ref.strip()):
            raise ValueError(f"task_spec.targets[{index}].table_ref must be a non-empty string when provided")
        derivation = target.get("derivation")
        if derivation is not None and not isinstance(derivation, dict):
            raise ValueError(f"task_spec.targets[{index}].derivation must be an object or null")
    for dataset_id in task_spec_dataset_ids(normalized):
        dataset = db.get(DatasetSnapshot, dataset_id)
        if dataset is None or dataset.project_id != project.id:
            raise ValueError(f"TaskSpec references a dataset_snapshot_id outside this project: {dataset_id}")
    return normalized


def task_spec_dataset_ids(task_spec: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in task_spec.get("targets", []):
        if isinstance(item, dict) and isinstance(item.get("dataset_snapshot_id"), str) and item["dataset_snapshot_id"].strip():
            ids.append(item["dataset_snapshot_id"].strip())
        if isinstance(item, dict) and isinstance(item.get("table_ref"), str) and item["table_ref"].strip():
            ids.append(item["table_ref"].strip())
    granularity = task_spec.get("granularity")
    if isinstance(granularity, dict) and isinstance(granularity.get("dataset_snapshot_id"), str) and granularity["dataset_snapshot_id"].strip():
        ids.append(granularity["dataset_snapshot_id"].strip())
    if isinstance(granularity, dict) and isinstance(granularity.get("table_ref"), str) and granularity["table_ref"].strip():
        ids.append(granularity["table_ref"].strip())
    return list(dict.fromkeys(ids))


def denormalized_target_column_from_task_spec(task_spec: dict[str, Any]) -> str | None:
    targets = task_spec.get("targets")
    if not isinstance(targets, list):
        return None
    column_targets = [
        item.get("column")
        for item in targets
        if isinstance(item, dict)
        and isinstance(item.get("column"), str)
        and item["column"].strip()
    ]
    if len(column_targets) == 1:
        return str(column_targets[0]).strip()
    return None


def write_data_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_data_request_rejection_to_workspace_inbox(
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
        "schema_version: tablex_data_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The data request was rejected by fixed-format validation and did not change project data state.",
        "Read the ack JSON, repair the request under `.tablex/requests/data/`, and resubmit with a new request_id.",
        "",
        "Error:",
        error_message,
    ]
    write_inbox_entry(
        workspace,
        kind="rejection",
        entry_type="data_request_rejection",
        content="\n".join(lines),
        payload={
            "schema_version": "tablex_data_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
        },
        title="Data request rejected",
    )


def optional_nonempty_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_workspace_relative_path(workspace: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"path must be workspace-relative: {value}")
    resolved = (workspace / relative).resolve()
    workspace_resolved = workspace.resolve()
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {value}") from exc
    return resolved
