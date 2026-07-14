from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Job,
    Project,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.agent_inbox import latest_inbox_entry_path, write_inbox_entry
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.evaluation import (
    approve_spec,
    create_evaluation_approval_review,
    load_profile_for_dataset,
    promote_candidate_to_spec,
    write_spec_artifact,
)
from tabular_harness.services.jobs import create_job
from tabular_harness.services.metric_preferences import normalize_metric_name

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
EVALUATION_REQUESTS_DIR = "evaluation"
EVALUATION_REQUEST_SCHEMA_VERSION = "tablex_evaluation_request.v1"
EVALUATION_ACK_SCHEMA_VERSION = "tablex_evaluation_ack.v1"

SUPPORTED_EVALUATION_OPERATIONS = {"propose_evaluation", "generate_split"}
SUPPORTED_SPLIT_KINDS = {
    "random",
    "stratified",
    "group",
    "time",
    "fixed_file",
    "fold_column",
    "rolling_forward",
}
GENERATABLE_SPLIT_KINDS = {"random", "stratified", "group", "time"}

AppendSessionEvent = Callable[..., Any]


def evaluation_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / EVALUATION_REQUESTS_DIR


def evaluation_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / EVALUATION_REQUESTS_DIR


def evaluation_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="evaluation_request_rejection", kind="rejection")


def process_evaluation_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
) -> None:
    request_dir = evaluation_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = evaluation_acks_dir(workspace)
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
                raise ValueError("Evaluation request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != EVALUATION_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported evaluation request schema_version: {schema_version or '<missing>'}; "
                    f"expected {EVALUATION_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation not in SUPPORTED_EVALUATION_OPERATIONS:
                raise ValueError(f"Unsupported evaluation request operation: {operation or '<missing>'}")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = execute_evaluation_tool_request(
                db,
                store=store,
                project=project,
                session=session,
                request_id=request_id,
                operation=operation,
                payload=payload,
            )
            ack = {
                "schema_version": EVALUATION_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_evaluation_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="evaluation_request_succeeded",
                    role="harness",
                    title="Evaluation request processed",
                    content=f"Processed evaluation request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    artifact_id=result.get("artifact_id"),
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": EVALUATION_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_evaluation_tool_ack(ack_path, ack)
            write_evaluation_request_rejection_to_workspace_inbox(
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
                    event_type="evaluation_request_failed",
                    role="harness",
                    title="Evaluation request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )


def execute_evaluation_tool_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if operation == "propose_evaluation":
        return execute_propose_evaluation_request(
            db,
            store=store,
            project=project,
            session=session,
            request_id=request_id,
            payload=payload,
        )
    if operation == "generate_split":
        return execute_generate_split_request(db, project=project, payload=payload)
    raise ValueError(f"Unsupported evaluation request operation: {operation or '<missing>'}")


def execute_propose_evaluation_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    dataset = evaluation_request_dataset(db, project=project, payload=payload)
    profile = load_profile_for_dataset(db, dataset)
    available_columns = profile_column_names(profile)
    objective_metric = required_object(payload, "objective_metric")
    primary_metric = normalize_metric_name(required_string(objective_metric, "name", "payload.objective_metric.name"))
    direction = optional_string(objective_metric, "direction")
    split_policy = required_object(payload, "split_policy")
    split_kind = required_string(split_policy, "kind", "payload.split_policy.kind")
    if split_kind not in SUPPORTED_SPLIT_KINDS:
        raise ValueError(f"payload.split_policy.kind must be one of {sorted(SUPPORTED_SPLIT_KINDS)}")
    params = split_policy.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("payload.split_policy.params must be an object when provided")
    validate_split_policy_columns(split_kind, params, available_columns)
    secondary_metrics = normalize_metric_list(payload.get("secondary_metrics"))
    excluded_columns = normalize_existing_columns(payload.get("excluded_columns"), available_columns, "payload.excluded_columns")
    name = optional_string(payload, "name") or f"Codex proposed {split_kind} evaluation"
    rationale = required_string(payload, "rationale", "payload.rationale")
    provisional_assumption = optional_string(payload, "provisional_assumption")
    candidate = EvaluationCandidate(
        id=new_id("ec"),
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        name=name,
        scenario_id=optional_string(payload, "scenario_id") or f"codex_{request_id}",
        split_type=split_kind,
        primary_metric=primary_metric,
        secondary_metrics_json=dumps_json(secondary_metrics),
        time_column=optional_column(params, "time_column", available_columns),
        group_column=optional_column(params, "group_column", available_columns),
        stratify_column=optional_column(params, "stratify_column", available_columns),
        excluded_columns_json=dumps_json(excluded_columns),
        assumption_ids_json=dumps_json(normalize_string_list(payload.get("assumption_ids"), "payload.assumption_ids")),
        rationale_md=evaluation_candidate_rationale(
            rationale=rationale,
            provisional_assumption=provisional_assumption,
            split_policy={"kind": split_kind, "params": params},
            direction=direction,
        ),
        confidence=float(payload.get("confidence") or 0.6),
        risk_level=optional_string(payload, "risk_level") or "medium",
        status="proposed_by_codex",
        created_by=f"agent_session:{session.id}",
    )
    db.add(candidate)
    db.flush()
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="evaluation_candidate_proposal",
        name=f"agent_session_{session.id}_evaluation_{request_id}",
        filename="evaluation_candidate_proposal.json",
        payload={
            "schema_version": "evaluation_candidate_proposal.v1",
            "request_id": request_id,
            "agent_session_id": session.id,
            "candidate_id": candidate.id,
            "dataset_snapshot_id": dataset.id,
            "objective_metric": {"name": primary_metric, "direction": direction},
            "secondary_metrics": secondary_metrics,
            "split_policy": {"kind": split_kind, "params": params},
            "rationale": rationale,
            "provisional_assumption": provisional_assumption,
            "excluded_columns": excluded_columns,
            "raw_payload": payload,
        },
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "evaluation_candidate_id": candidate.id,
            "dataset_snapshot_id": dataset.id,
            "split_type": split_kind,
            "primary_metric": primary_metric,
        },
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="evaluation_candidate",
        from_asset_id=candidate.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="records_proposal",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="evaluation_candidate",
        to_asset_id=candidate.id,
        relation_type="evaluated_by",
    )
    result = {
        "candidate_id": candidate.id,
        "artifact_id": artifact.id,
        "dataset_snapshot_id": dataset.id,
        "split_type": split_kind,
        "primary_metric": primary_metric,
        "status": candidate.status,
        "requires_approval": True,
        "split_generation_supported": split_kind in GENERATABLE_SPLIT_KINDS,
    }
    if project.autonomy_mode != "full_auto":
        return result

    spec = promote_candidate_to_spec(db, store=store, candidate=candidate)
    review = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=True)
    result.update(
        {
            "evaluation_spec_id": spec.id,
            "approval_review_artifact_id": review.artifact.id,
            "approval_blocked": review.blocked,
        }
    )
    if review.blocked:
        return result

    approve_spec(spec)
    approved_artifact = write_spec_artifact(db, store, spec)
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=review.artifact.id,
        to_asset_type="evaluation_spec",
        to_asset_id=spec.id,
        relation_type="supports_approval",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="evaluation_spec",
        from_asset_id=spec.id,
        to_asset_type="artifact",
        to_asset_id=approved_artifact.id,
        relation_type="produces",
    )
    split_job = None
    if split_kind in GENERATABLE_SPLIT_KINDS:
        split_job = create_job(
            db,
            job_type="build_split_manifest",
            project_id=project.id,
            input_payload={"evaluation_spec_id": spec.id},
            policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
            priority=70,
        )
    result.update(
        {
            "status": spec.status,
            "requires_approval": False,
            "evaluation_spec_artifact_id": approved_artifact.id,
            "split_job_id": split_job.id if split_job is not None else None,
        }
    )
    return result


def execute_generate_split_request(db: Session, *, project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    spec_id = required_string(payload, "evaluation_spec_id", "payload.evaluation_spec_id")
    spec = db.get(EvaluationSpec, spec_id)
    if spec is None or spec.project_id != project.id:
        raise ValueError("payload.evaluation_spec_id does not belong to this project")
    if spec.status != "approved":
        raise ValueError("EvaluationSpec must be approved before generating a SplitManifest")
    if spec.split_type not in GENERATABLE_SPLIT_KINDS:
        raise ValueError(
            f"SplitManifest generation is not implemented for split_type={spec.split_type!r}; "
            "Codex can still propose it as an EvaluationCandidate."
        )
    existing_split = db.scalar(
        select(SplitManifest)
        .where(
            SplitManifest.project_id == project.id,
            SplitManifest.evaluation_spec_id == spec.id,
        )
        .order_by(SplitManifest.created_at.desc())
        .limit(1)
    )
    if existing_split is not None:
        return {
            "job_id": None,
            "evaluation_spec_id": spec.id,
            "split_manifest_id": existing_split.id,
            "status": "succeeded",
            "reused": True,
        }
    active_split_jobs = db.scalars(
        select(Job)
        .where(
            Job.project_id == project.id,
            Job.job_type == "build_split_manifest",
            Job.status.in_(("queued", "running", "waiting_for_approval")),
        )
        .order_by(Job.created_at.desc())
    )
    for active_job in active_split_jobs:
        job_input = loads_json(active_job.input_json, {})
        if job_input.get("evaluation_spec_id") == spec.id:
            return {
                "job_id": active_job.id,
                "evaluation_spec_id": spec.id,
                "status": active_job.status,
                "reused": True,
            }
    job = create_job(
        db,
        job_type="build_split_manifest",
        project_id=project.id,
        input_payload={"evaluation_spec_id": spec.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
        priority=70,
    )
    return {"job_id": job.id, "evaluation_spec_id": spec.id, "status": job.status, "reused": False}


def evaluation_request_dataset(db: Session, *, project: Project, payload: dict[str, Any]) -> DatasetSnapshot:
    dataset_snapshot_id = optional_string(payload, "dataset_snapshot_id") or project.primary_dataset_snapshot_id
    if dataset_snapshot_id:
        dataset = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset is None or dataset.project_id != project.id:
            raise ValueError("payload.dataset_snapshot_id does not belong to this project")
        return dataset
    dataset = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id)
        .order_by(DatasetSnapshot.created_at.desc())
        .limit(1)
    )
    if dataset is None:
        raise ValueError("A DatasetSnapshot is required before proposing an evaluation")
    return dataset


def profile_column_names(profile: dict[str, Any]) -> set[str]:
    raw_columns = profile.get("columns")
    if not isinstance(raw_columns, list):
        return set()
    names: set[str] = set()
    for item in raw_columns:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def validate_split_policy_columns(split_kind: str, params: dict[str, Any], available_columns: set[str]) -> None:
    if split_kind == "group":
        require_existing_column(params, "group_column", available_columns)
    elif split_kind in {"time", "rolling_forward"}:
        require_existing_column(params, "time_column", available_columns)
    elif split_kind == "stratified":
        if optional_string(params, "stratify_column"):
            require_existing_column(params, "stratify_column", available_columns)
    elif split_kind == "fold_column":
        require_existing_column(params, "fold_column", available_columns)
    elif split_kind == "fixed_file":
        required_string(params, "validation_file_ref", "payload.split_policy.params.validation_file_ref")


def require_existing_column(params: dict[str, Any], key: str, available_columns: set[str]) -> str:
    value = required_string(params, key, f"payload.split_policy.params.{key}")
    if available_columns and value not in available_columns:
        raise ValueError(f"payload.split_policy.params.{key} is not a column in the selected dataset")
    return value


def optional_column(params: dict[str, Any], key: str, available_columns: set[str]) -> str | None:
    value = optional_string(params, key)
    if value is None:
        return None
    if available_columns and value not in available_columns:
        raise ValueError(f"payload.split_policy.params.{key} is not a column in the selected dataset")
    return value


def required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"payload.{key} must be an object")
    return value


def required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def normalize_metric_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("payload.secondary_metrics must be a list when provided")
    return [normalize_metric_name(item) for item in value if isinstance(item, str) and item.strip()]


def normalize_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list when provided")
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_existing_columns(value: Any, available_columns: set[str], label: str) -> list[str]:
    columns = normalize_string_list(value, label)
    if available_columns:
        missing = [column for column in columns if column not in available_columns]
        if missing:
            raise ValueError(f"{label} contains columns not in the selected dataset: {', '.join(missing[:5])}")
    return columns


def evaluation_candidate_rationale(
    *,
    rationale: str,
    provisional_assumption: str | None,
    split_policy: dict[str, Any],
    direction: str | None,
) -> str:
    payload = {"split_policy": split_policy}
    if direction:
        payload["metric_direction"] = direction
    parts = [rationale.strip(), "", "```json", dumps_json(payload), "```"]
    if provisional_assumption:
        parts.extend(["", f"Provisional assumption: {provisional_assumption.strip()}"])
    return "\n".join(parts).strip()


def write_evaluation_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(dumps_json(payload) + "\n", encoding="utf-8")


def write_evaluation_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
) -> Path | None:
    return write_inbox_entry(
        workspace,
        kind="rejection",
        entry_type="evaluation_request_rejection",
        title="Evaluation request needs revision",
        payload={
            "schema_version": "tablex_evaluation_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_relative_path": request_relative_path,
            "ack_relative_path": ack_relative_path,
            "error": {"type": error_type, "message": error_message},
        },
        content="\n".join(
            [
                "The evaluation request was not accepted.",
                f"Request: `{request_relative_path}`",
                f"Ack: `{ack_relative_path}`",
                f"Error: {error_type}: {error_message}",
                "Revise the JSON request and resubmit it with the same schema.",
            ]
        ),
    )
