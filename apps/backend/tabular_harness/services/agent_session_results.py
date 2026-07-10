from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Job,
    LineageEdge,
    Project,
    ResearchPlan,
    ResearchPlanRevision,
    SplitManifest,
    User,
    utc_now,
)
from tabular_harness.services.agent_inbox import (
    latest_inbox_entry_path,
    list_inbox_entries,
    write_inbox_entry,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.deliverable_expectations import (
    create_run_model_diagnostics_notebook_expectations,
)
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.metric_preferences import (
    leaderboard_sort_key_for_metric,
    normalize_metric_name,
)
from tabular_harness.services.research_plans import (
    PLAN_CURRENT_STATUSES,
    attach_research_plan_artifact,
    latest_research_plan_current_work,
    latest_research_plan_revision,
    research_plan_block_id,
    research_plan_block_status,
    research_plan_blocks_from_revision,
    research_plan_revision_document,
    validate_research_plan_node_exists,
)

EXPERIMENT_REQUESTS_DIR = "experiments"
EXPERIMENT_ACK_SCHEMA_VERSION = "tablex_experiment_result_ack.v1"
EXPERIMENT_REQUEST_SCHEMA_VERSION = "tablex_experiment_result_request.v1"
MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION = "tablex_model_diagnostics_request.v1"
MODEL_DIAGNOSTIC_CHECK_NAMES = (
    "permutation_importance",
    "native_feature_importance",
    "partial_dependence",
    "shap",
)
MODEL_DIAGNOSTIC_CHECK_ASSET_TYPES = {
    "permutation_importance": "permutation_importance",
    "native_feature_importance": "feature_importance",
    "partial_dependence": "partial_dependence",
    "shap": "shap_summary",
}
SUPPORTED_RESULT_SCHEMAS = {
    "model_results.v1",
    "text_ablation_model_comparison.v1",
    "structured_target_encoding_model.v1",
}
DEFAULT_PRIMARY_METRIC_ORDER = ("mae", "rmse", "log_mae", "roc_auc", "pr_auc", "accuracy", "r2")


def write_workspace_inbox_text(
    workspace: Path,
    *,
    kind: str,
    entry_type: str,
    lines: list[str],
    payload: dict[str, Any] | None = None,
    title: str | None = None,
) -> Path | None:
    try:
        return write_inbox_entry(
            workspace,
            kind=kind,
            entry_type=entry_type,
            payload=payload or {},
            content="\n".join(lines).strip() + "\n",
            title=title,
        )
    except (OSError, ValueError):
        return None


def workspace_inbox_has_payload(
    workspace: Path,
    *,
    kind: str,
    entry_type: str,
    payload: dict[str, Any],
) -> bool:
    for entry in list_inbox_entries(workspace):
        if entry.get("kind") != kind or entry.get("type") != entry_type:
            continue
        existing_payload = entry.get("payload")
        if isinstance(existing_payload, dict) and existing_payload == payload:
            return True
    return False


@dataclass(frozen=True)
class RunSpec:
    source_key: str
    model_id: str
    summary: str
    metrics: dict[str, Any]
    params: dict[str, Any]
    primary_metric_name: str
    primary_metric_value: float
    source_artifact_id: str | None = None
    source_workspace_path: str | None = None
    research_plan_node_id: str | None = None
    dataset_snapshot_id: str | None = None
    evaluation_spec_id: str | None = None
    split_manifest_id: str | None = None


@dataclass(frozen=True)
class RunSpecContext:
    source_artifact_id: str | None
    dataset_snapshot_id: str | None
    evaluation_spec_id: str | None
    split_manifest_id: str | None
    warnings: list[dict[str, Any]]


def experiment_requests_dir(workspace: Path) -> Path:
    return workspace / ".tablex" / "requests" / EXPERIMENT_REQUESTS_DIR


def experiment_acks_dir(workspace: Path) -> Path:
    return workspace / ".tablex" / "acks" / EXPERIMENT_REQUESTS_DIR


def experiment_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="experiment_result_request_rejection", kind="rejection")


def experiment_artifact_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="experiment_result_artifact_rejection", kind="rejection")


def pipeline_registration_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="pipeline_registration_request", kind="request")


def model_diagnostics_artifact_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="model_diagnostics_artifact_request", kind="request")


def model_diagnostics_notebook_request_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="model_diagnostics_notebook_request", kind="request")


def process_experiment_result_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_event: Any | None = None,
) -> list[ExperimentRun]:
    request_dir = experiment_requests_dir(workspace)
    if not request_dir.exists():
        return []
    ack_dir = experiment_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    created_runs: list[ExperimentRun] = []
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = loads_json(raw_text, {})
            if not isinstance(payload, dict):
                raise ValueError("Experiment result request must be a JSON object")
            schema_version = str(payload.get("schema_version") or "").strip()
            if schema_version != EXPERIMENT_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Experiment result request schema_version must be {EXPERIMENT_REQUEST_SCHEMA_VERSION}"
                )
            request_id = str(payload.get("request_id") or path.stem)
            operation = str(payload.get("operation") or "register_runs").strip()
            if operation != "register_runs":
                raise ValueError(f"Unsupported experiment result operation: {operation}")
            body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            specs = run_specs_from_experiment_request(body, request_id=request_id)
            runs = register_experiment_run_specs(
                db,
                store=store,
                project=project,
                session=session,
                specs=specs,
                source_artifact=None,
                source_request_id=request_id,
            )
            created_runs.extend(runs)
            chat_artifact = register_experiment_registration_chat_turn(
                db,
                store=store,
                project=project,
                session=session,
                runs=runs,
                source_artifact=None,
                source_request_id=request_id,
            )
            pipeline_registration = experiment_pipeline_registration_status(runs)
            if pipeline_registration["status"] != "ready":
                write_pipeline_registration_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=request_id,
                    pipeline_registration=pipeline_registration,
                )
            model_diagnostics_artifacts = experiment_model_diagnostics_artifact_status(
                db,
                project=project,
                runs=runs,
            )
            if model_diagnostics_artifacts["status"] not in {"ready", "registered"}:
                write_model_diagnostics_artifact_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=request_id,
                    diagnostics_status=model_diagnostics_artifacts,
                )
            model_diagnostics_notebook = experiment_model_diagnostics_notebook_status(db, project=project, runs=runs)
            if model_diagnostics_notebook["status"] != "ready":
                create_run_model_diagnostics_notebook_expectations(
                    db,
                    project=project,
                    runs=runs,
                    created_from=f"register_runs:{request_id}",
                )
                write_model_diagnostics_notebook_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=request_id,
                    diagnostics_status=model_diagnostics_notebook,
                )
            skipped_duplicates = skipped_duplicate_run_specs_for_ack(
                db,
                project_id=project.id,
                specs=specs,
                created_runs=runs,
            )
            ack = {
                "schema_version": EXPERIMENT_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": {
                    "registered_run_ids": [run.id for run in runs],
                    "registered_runs": [experiment_run_ack_item(run) for run in runs],
                    "registered_count": len(runs),
                    "duplicate_count": len(skipped_duplicates),
                    "skipped_duplicates": skipped_duplicates,
                    "plan_link_warnings": experiment_plan_link_warnings(runs),
                    "context_warnings": experiment_context_warnings(runs),
                    "pipeline_registration": pipeline_registration,
                    "model_diagnostics_artifacts": model_diagnostics_artifacts,
                    "model_diagnostics_notebook": model_diagnostics_notebook,
                    "chat_artifact_id": chat_artifact.id if chat_artifact is not None else None,
                    "visible_surfaces": experiment_result_visible_surfaces(
                        runs,
                        chat_artifact_id=chat_artifact.id if chat_artifact is not None else None,
                    ),
                },
            }
            write_experiment_result_ack(ack_path, ack)
            if append_event is not None:
                append_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="experiment_result_request_succeeded",
                    role="harness",
                    title="Experiment result request processed",
                    content=f"Registered {len(runs)} leaderboard run(s) from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    update_heartbeat=False,
                )
                if pipeline_registration["status"] != "ready":
                    append_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="pipeline_registration_requested",
                        role="harness",
                        title="Prediction pipeline registration requested",
                        content="Registered leaderboard runs do not yet have prediction pipeline bundles.",
                        payload={
                            "schema_version": "pipeline_registration_request_notice.v1",
                            "source_request_id": request_id,
                            "pipeline_registration": pipeline_registration,
                        },
                        update_heartbeat=False,
                    )
                if model_diagnostics_artifacts["status"] not in {"ready", "registered"}:
                    append_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="model_diagnostics_artifacts_requested",
                        role="harness",
                        title="Model diagnostics artifacts requested",
                        content="Registered leaderboard runs do not yet have standard model-diagnostics artifacts.",
                        payload={
                            "schema_version": "model_diagnostics_artifact_request_notice.v1",
                            "source_request_id": request_id,
                            "model_diagnostics_artifacts": model_diagnostics_artifacts,
                        },
                        update_heartbeat=False,
                    )
                if model_diagnostics_notebook["status"] != "ready":
                    append_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="model_diagnostics_notebook_requested",
                        role="harness",
                        title="Model diagnostics notebook requested",
                        content="Registered leaderboard runs do not yet have linked model-diagnostics notebooks.",
                        payload={
                            "schema_version": "model_diagnostics_notebook_request_notice.v1",
                            "source_request_id": request_id,
                            "model_diagnostics_notebook": model_diagnostics_notebook,
                        },
                        update_heartbeat=False,
                    )
        except Exception as exc:
            ack = {
                "schema_version": EXPERIMENT_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_experiment_result_ack(ack_path, ack)
            write_experiment_result_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            register_experiment_result_failure_chat_turn(
                db,
                store=store,
                project=project,
                session=session,
                request_id=request_id,
                operation=operation,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if append_event is not None:
                append_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="experiment_result_request_failed",
                    role="harness",
                    title="Experiment result request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )
    return created_runs


def ingest_registered_session_experiment_artifacts(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> list[ExperimentRun]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_session_artifact",
            )
            .order_by(Artifact.created_at.asc(), Artifact.version.asc())
        ).all()
    )
    created_runs: list[ExperimentRun] = []
    created_by_artifact: dict[str, list[ExperimentRun]] = {}
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except OSError:
            continue
        if not isinstance(payload, dict):
            continue
        schema_version = str(payload.get("schema_version") or "")
        if schema_version not in SUPPORTED_RESULT_SCHEMAS:
            continue
        try:
            specs = run_specs_from_structured_result_payload(payload, source_artifact=artifact)
            if not specs:
                raise ValueError(
                    f"`{schema_version}` did not contain any registerable model result rows with a numeric primary metric"
                )
            runs = register_experiment_run_specs(
                db,
                store=store,
                project=project,
                session=session,
                specs=specs,
                source_artifact=artifact,
                source_request_id=None,
            )
        except Exception as exc:
            register_structured_experiment_result_failure(
                db,
                store=store,
                project=project,
                session=session,
                artifact=artifact,
                schema_version=schema_version,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            continue
        if runs:
            created_runs.extend(runs)
            created_by_artifact[artifact.id] = runs
            workspace = Path(session.workspace_path) if session.workspace_path else None
            pipeline_registration = experiment_pipeline_registration_status(runs)
            if workspace is not None and pipeline_registration["status"] != "ready":
                write_pipeline_registration_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=f"artifact:{artifact.id}",
                    pipeline_registration=pipeline_registration,
                )
            diagnostics_artifact_status = experiment_model_diagnostics_artifact_status(
                db,
                project=project,
                runs=runs,
            )
            if workspace is not None and diagnostics_artifact_status["status"] not in {"ready", "registered"}:
                write_model_diagnostics_artifact_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=f"artifact:{artifact.id}",
                    diagnostics_status=diagnostics_artifact_status,
                )
            diagnostics_notebook_status = experiment_model_diagnostics_notebook_status(db, project=project, runs=runs)
            if workspace is not None and diagnostics_notebook_status["status"] != "ready":
                create_run_model_diagnostics_notebook_expectations(
                    db,
                    project=project,
                    runs=runs,
                    created_from=f"artifact:{artifact.id}",
                )
                write_model_diagnostics_notebook_request_to_workspace_inbox(
                    workspace,
                    runs=runs,
                    source_request_id=f"artifact:{artifact.id}",
                    diagnostics_status=diagnostics_notebook_status,
                )
    for artifact_id, runs in created_by_artifact.items():
        source_artifact = db.get(Artifact, artifact_id)
        register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=runs,
            source_artifact=source_artifact,
            source_request_id=None,
        )
    restore_registered_session_experiment_visibility(db, store=store, project=project, session=session)
    return created_runs


def restore_registered_session_experiment_visibility(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> list[ExperimentRun]:
    runs = session_registered_experiment_runs(db, project=project, session=session)
    grouped: dict[tuple[str, str], list[ExperimentRun]] = {}
    source_artifacts: dict[tuple[str, str], Artifact | None] = {}
    source_request_ids: dict[tuple[str, str], str | None] = {}
    for run in runs:
        params = loads_json(run.params_json, {})
        node_id = ensure_experiment_run_plan_visibility(db, project=project, run=run)
        if node_id and params.get("research_plan_node_id") != node_id:
            params["research_plan_node_id"] = node_id
            run.params_json = dumps_json(params)
        source_artifact_id = str(params.get("source_artifact_id") or "").strip()
        source_artifact = db.get(Artifact, source_artifact_id) if source_artifact_id else None
        if source_artifact is not None and source_artifact.project_id == project.id:
            group_key = ("artifact", source_artifact.id)
            source_artifacts[group_key] = source_artifact
            source_request_ids[group_key] = None
        else:
            source_request_id = str(params.get("source_request_id") or "").strip() or None
            group_key = ("request", source_request_id or "restored_session_runs")
            source_artifacts[group_key] = None
            source_request_ids[group_key] = source_request_id or "restored_session_runs"
        grouped.setdefault(group_key, []).append(run)
    for group_key, group_runs in grouped.items():
        source_artifact = source_artifacts.get(group_key)
        source_request_id = source_request_ids.get(group_key)
        source_reference = (
            source_request_id
            or (f"artifact:{source_artifact.id}" if source_artifact is not None else None)
            or "restored_session_runs"
        )
        register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=group_runs,
            source_artifact=source_artifact,
            source_request_id=source_request_id,
        )
        workspace = Path(session.workspace_path) if session.workspace_path else None
        if workspace is not None:
            pipeline_registration = experiment_pipeline_registration_status(group_runs)
            if pipeline_registration["status"] != "ready":
                write_pipeline_registration_request_to_workspace_inbox(
                    workspace,
                    runs=group_runs,
                    source_request_id=source_reference,
                    pipeline_registration=pipeline_registration,
                )
            diagnostics_artifact_status = experiment_model_diagnostics_artifact_status(
                db,
                project=project,
                runs=group_runs,
            )
            if diagnostics_artifact_status["status"] not in {"ready", "registered"}:
                write_model_diagnostics_artifact_request_to_workspace_inbox(
                    workspace,
                    runs=group_runs,
                    source_request_id=source_reference,
                    diagnostics_status=diagnostics_artifact_status,
                )
            diagnostics_notebook_status = experiment_model_diagnostics_notebook_status(
                db,
                project=project,
                runs=group_runs,
            )
            if diagnostics_notebook_status["status"] != "ready":
                write_model_diagnostics_notebook_request_to_workspace_inbox(
                    workspace,
                    runs=group_runs,
                    source_request_id=source_reference,
                    diagnostics_status=diagnostics_notebook_status,
                )
    db.flush()
    return runs


def reconcile_project_experiment_chat_links(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    limit: int = 20,
) -> int:
    sessions = list(
        db.scalars(
            select(AgentSession)
            .where(AgentSession.project_id == project.id)
            .order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
            .limit(limit)
        ).all()
    )
    before_count = project_experiment_registration_chat_turn_count(db, project=project)
    for session in reversed(sessions):
        restore_registered_session_experiment_visibility(db, store=store, project=project, session=session)
    after_count = project_experiment_registration_chat_turn_count(db, project=project)
    return max(0, after_count - before_count)


def project_experiment_registration_chat_turn_count(db: Session, *, project: Project) -> int:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(500)
        ).all()
    )
    count = 0
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") == "main_agent_session_experiment_registration":
            count += 1
    return count


def session_registered_experiment_runs(db: Session, *, project: Project, session: AgentSession) -> list[ExperimentRun]:
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project.id)
            .order_by(ExperimentRun.started_at.asc(), ExperimentRun.id.asc())
        ).all()
    )
    session_runs: list[ExperimentRun] = []
    for run in runs:
        params = loads_json(run.params_json, {})
        if params.get("agent_session_id") == session.id:
            session_runs.append(run)
    return session_runs


def ensure_experiment_run_plan_visibility(db: Session, *, project: Project, run: ExperimentRun) -> str | None:
    params = loads_json(run.params_json, {})
    if params.get("plan_link_status") == "declared_node_missing":
        return None
    explicit_node_id = str(params.get("research_plan_node_id") or "").strip() or None
    if explicit_node_id is None:
        return None
    node_id = resolve_research_plan_node_for_run(
        db,
        project=project,
        explicit_node_id=explicit_node_id,
    )
    source_artifact_id = str(params.get("source_artifact_id") or "").strip() or None
    attach_experiment_artifact_to_current_plan_node(
        db,
        project=project,
        source_artifact_id=source_artifact_id,
        run=run,
        node_id=node_id,
        allow_current_fallback=False,
    )
    return node_id


def experiment_run_ack_item(run: ExperimentRun) -> dict[str, Any]:
    params = loads_json(run.params_json, {})
    return {
        "run_id": run.id,
        "model_id": params.get("model_id"),
        "source_artifact_id": params.get("source_artifact_id"),
        "dataset_snapshot_id": run.dataset_snapshot_id,
        "evaluation_spec_id": run.evaluation_spec_id,
        "split_manifest_id": run.split_manifest_id,
        "research_plan_node_id": params.get("research_plan_node_id"),
    }


def run_pipeline_artifact_id(run: ExperimentRun) -> str | None:
    params = loads_json(run.params_json, {})
    value = params.get("pipeline_artifact_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def experiment_pipeline_registration_status(runs: list[ExperimentRun]) -> dict[str, Any]:
    registered = [
        {"run_id": run.id, "pipeline_artifact_id": pipeline_artifact_id}
        for run in runs
        for pipeline_artifact_id in [run_pipeline_artifact_id(run)]
        if pipeline_artifact_id
    ]
    missing = [
        {
            "run_id": run.id,
            "model_id": loads_json(run.params_json, {}).get("model_id"),
            "model_description": run.summary_md,
        }
        for run in runs
        if run_pipeline_artifact_id(run) is None
    ]
    if registered and missing:
        status = "partial"
    elif missing:
        status = "missing"
    else:
        status = "ready"
    return {
        "schema_version": "experiment_pipeline_registration_status.v1",
        "status": status,
        "missing_count": len(missing),
        "registered_count": len(registered),
        "missing_runs": missing[:50],
        "registered_pipelines": registered[:50],
        "next_request": (
            "Write a tablex_pipeline_request.v1 register_prediction_pipeline request under "
            ".tablex/requests/pipelines/ for the missing run ids."
            if missing
            else None
        ),
    }


def experiment_model_diagnostics_notebook_status(
    db: Session,
    *,
    project: Project,
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    run_ids = {run.id for run in runs}
    linked_run_ids: set[str] = set()
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(("analysis_notebook", "marimo_notebook")))
            .order_by(Artifact.created_at.desc())
            .limit(500)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("notebook_kind") != "model_diagnostics":
            continue
        value = metadata.get("run_id")
        if isinstance(value, str) and value in run_ids:
            linked_run_ids.add(value)
        related = metadata.get("related_run_ids")
        if isinstance(related, list):
            linked_run_ids.update(item for item in related if isinstance(item, str) and item in run_ids)
    missing = [
        {
            "run_id": run.id,
            "model_id": loads_json(run.params_json, {}).get("model_id"),
            "model_description": run.summary_md,
        }
        for run in runs
        if run.id not in linked_run_ids
    ]
    if linked_run_ids and missing:
        status = "partial"
    elif missing:
        status = "missing"
    else:
        status = "ready"
    return {
        "schema_version": "experiment_model_diagnostics_notebook_status.v1",
        "status": status,
        "missing_count": len(missing),
        "linked_count": len(linked_run_ids),
        "missing_runs": missing[:50],
        "next_request": (
            "Write a tablex_notebook_request.v1 register_notebook request for a model-diagnostics marimo notebook "
            "linked to the missing run ids. The quality_manifest.model_diagnostics checks should declare "
            "permutation_importance, native_feature_importance, partial_dependence, and shap coverage."
            if missing
            else None
        ),
    }


def experiment_model_diagnostics_artifact_status(
    db: Session,
    *,
    project: Project,
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    run_statuses = [model_diagnostics_artifact_status_for_run(db, project=project, run=run) for run in runs]
    missing = [item for item in run_statuses if item["status"] == "missing"]
    partial = [item for item in run_statuses if item["status"] == "partial"]
    registered = [item for item in run_statuses if item["status"] == "registered"]
    ready = [item for item in run_statuses if item["status"] == "ready"]
    if run_statuses and len(ready) == len(run_statuses):
        status = "ready"
    elif run_statuses and len(ready) + len(registered) == len(run_statuses):
        status = "registered"
    elif ready or registered or partial:
        status = "partial"
    else:
        status = "missing"
    missing_runs = [
        {
            "run_id": item["run_id"],
            "model_id": item.get("model_id"),
            "model_description": item.get("model_description"),
            "missing_checks": item.get("missing_checks", []),
        }
        for item in [*missing, *partial]
    ]
    return {
        "schema_version": "experiment_model_diagnostics_artifact_status.v1",
        "status": status,
        "ready_count": len(ready),
        "registered_count": len(registered),
        "partial_count": len(partial),
        "missing_count": len(missing),
        "run_count": len(run_statuses),
        "runs": run_statuses[:50],
        "missing_runs": missing_runs[:50],
        "next_request": (
            "Write a tablex_model_diagnostics_request.v1 register_model_diagnostics_artifacts request under "
            ".tablex/requests/model_diagnostics/ for missing run ids."
            if missing_runs
            else None
        ),
    }


def model_diagnostics_artifact_status_for_run(
    db: Session,
    *,
    project: Project,
    run: ExperimentRun,
) -> dict[str, Any]:
    params = loads_json(run.params_json, {})
    pack = latest_run_linked_artifact(db, project=project, run=run, asset_type="model_diagnostics_artifact_pack")
    pack_payload = load_artifact_payload(pack)
    pack_checks = model_diagnostics_checks_by_name(pack_payload)
    if not pack_checks and pack is not None:
        pack_checks = model_diagnostics_checks_by_name(loads_json(pack.metadata_json, {}))
    checks: dict[str, dict[str, Any]] = {}
    for check_name in MODEL_DIAGNOSTIC_CHECK_NAMES:
        artifact = latest_run_linked_artifact(
            db,
            project=project,
            run=run,
            asset_type=MODEL_DIAGNOSTIC_CHECK_ASSET_TYPES[check_name],
        )
        authored_check = pack_checks.get(check_name, {})
        checks[check_name] = model_diagnostics_check_registration_status(
            authored_check,
            artifact=artifact,
        )
    missing_checks = [name for name, item in checks.items() if item["status"] == "missing"]
    if pack is not None and not missing_checks and all(item["status"] == "included" for item in checks.values()):
        status = "ready"
    elif pack is not None and not missing_checks:
        status = "registered"
    elif any(item["status"] != "missing" for item in checks.values()) or pack is not None:
        status = "partial"
    else:
        status = "missing"
    return {
        "schema_version": "experiment_model_diagnostics_artifact_run_status.v1",
        "run_id": run.id,
        "model_id": params.get("model_id"),
        "model_description": run.summary_md,
        "status": status,
        "artifact_pack_id": pack.id if pack is not None else None,
        "checks": checks,
        "missing_checks": missing_checks,
    }


def model_diagnostics_checks_by_name(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return {}
    by_name: dict[str, dict[str, Any]] = {}
    for raw in checks:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name in MODEL_DIAGNOSTIC_CHECK_NAMES:
            by_name[name] = raw
    return by_name


def model_diagnostics_check_registration_status(
    authored_check: dict[str, Any],
    *,
    artifact: Artifact | None,
) -> dict[str, Any]:
    authored_status = str(authored_check.get("status") or "").strip()
    reason = str(authored_check.get("reason") or "").strip()
    if authored_status == "included":
        if artifact is None:
            return {"status": "missing", "reason": "included_check_missing_artifact"}
        return {
            "status": "included",
            "artifact_id": artifact.id,
            "artifact_status": artifact_payload_status(artifact),
        }
    if authored_status in {"not_applicable", "needs_model_artifact", "needs_dependency", "deferred"}:
        return {
            "status": authored_status,
            **({"reason": reason} if reason else {}),
            **({"artifact_id": artifact.id, "artifact_status": artifact_payload_status(artifact)} if artifact else {}),
        }
    if artifact is not None:
        return {"status": "included", "artifact_id": artifact.id, "artifact_status": artifact_payload_status(artifact)}
    return {"status": "missing"}


def latest_run_linked_artifact(
    db: Session,
    *,
    project: Project,
    run: ExperimentRun,
    asset_type: str,
) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project.id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
        .limit(500)
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("run_id") == run.id:
            return artifact
        related_run_ids = metadata.get("related_run_ids")
        run_ids = metadata.get("run_ids")
        if isinstance(related_run_ids, list) and run.id in related_run_ids:
            return artifact
        if isinstance(run_ids, list) and run.id in run_ids:
            return artifact
    return None


def load_artifact_payload(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def artifact_payload_status(artifact: Artifact) -> str | None:
    payload = load_artifact_payload(artifact)
    if isinstance(payload, dict) and isinstance(payload.get("status"), str):
        return payload["status"]
    metadata = loads_json(artifact.metadata_json, {})
    status = metadata.get("status")
    if isinstance(status, str):
        return status
    try:
        return "file_available" if artifact_primary_path(artifact).is_file() else "file_missing"
    except OSError:
        return None


def experiment_result_visible_surfaces(
    runs: list[ExperimentRun],
    *,
    chat_artifact_id: str | None,
) -> dict[str, Any]:
    research_plan_node_ids: set[str] = set()
    source_artifact_ids: set[str] = set()
    dataset_snapshot_ids: set[str] = set()
    evaluation_spec_ids: set[str] = set()
    split_manifest_ids: set[str] = set()
    for run in runs:
        params = loads_json(run.params_json, {})
        add_text_value(research_plan_node_ids, params.get("research_plan_node_id"))
        add_text_value(source_artifact_ids, params.get("source_artifact_id"))
        add_text_value(dataset_snapshot_ids, run.dataset_snapshot_id)
        add_text_value(evaluation_spec_ids, run.evaluation_spec_id)
        add_text_value(split_manifest_ids, run.split_manifest_id)
    surfaces: dict[str, Any] = {
        "leaderboard": {
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "run_ids": [run.id for run in runs],
        },
        "research_plan": {
            "target_tab": "Home",
            "target_anchor": "research-plan",
            "node_ids": sorted(research_plan_node_ids),
        },
        "chat": {
            "target_tab": "Home",
            "target_anchor": "agent-workspace",
            "artifact_id": chat_artifact_id,
        },
    }
    if source_artifact_ids:
        sorted_artifact_ids = sorted(source_artifact_ids)
        surfaces["assets"] = {
            "target_tab": "Assets",
            "target_anchor": "assets-artifact-preview",
            "artifact_id": sorted_artifact_ids[0],
            "artifact_ids": sorted_artifact_ids,
        }
    if dataset_snapshot_ids:
        sorted_dataset_ids = sorted(dataset_snapshot_ids)
        surfaces["data"] = {
            "target_tab": "Data",
            "target_anchor": "data-focus",
            "dataset_snapshot_id": sorted_dataset_ids[0] if len(sorted_dataset_ids) == 1 else None,
            "dataset_snapshot_ids": sorted_dataset_ids,
        }
    if evaluation_spec_ids or split_manifest_ids:
        surfaces["evaluation"] = {
            "target_tab": "Evaluation",
            "target_anchor": "evaluation-design",
            "evaluation_spec_ids": sorted(evaluation_spec_ids),
            "split_manifest_ids": sorted(split_manifest_ids),
        }
    return surfaces


def add_text_value(values: set[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    stripped = value.strip()
    if stripped:
        values.add(stripped)


def run_specs_from_experiment_request(payload: dict[str, Any], *, request_id: str) -> list[RunSpec]:
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("payload.runs must contain at least one run")
    specs: list[RunSpec] = []
    default_plan_node_id = str(payload.get("research_plan_node_id") or "").strip() or None
    default_source_artifact_id = optional_text_field(payload, "source_artifact_id")
    default_source_workspace_path = optional_text_field(payload, "source_workspace_path")
    default_dataset_snapshot_id = optional_text_field(payload, "dataset_snapshot_id")
    default_evaluation_spec_id = optional_text_field(payload, "evaluation_spec_id")
    default_split_manifest_id = optional_text_field(payload, "split_manifest_id")
    for index, item in enumerate(raw_runs):
        if not isinstance(item, dict):
            raise ValueError(f"payload.runs/{index} must be an object")
        model_id = str(item.get("model_id") or item.get("run_name") or item.get("name") or "").strip()
        if not model_id:
            raise ValueError(f"payload.runs/{index}/model_id is required")
        metrics = normalize_metrics(item.get("metrics") if isinstance(item.get("metrics"), dict) else item)
        primary_metric_name, primary_metric_value = primary_metric_from_payload(item, metrics)
        source_key = str(item.get("source_key") or f"{request_id}:{model_id}:{index}")
        summary_value = item.get("model_description")
        if not isinstance(summary_value, str) or not summary_value.strip():
            raise ValueError(f"payload.runs/{index}/model_description is required")
        features_used = item.get("features_used")
        if not isinstance(features_used, list) or not all(isinstance(feature, str) and feature.strip() for feature in features_used):
            raise ValueError(f"payload.runs/{index}/features_used must be a non-empty string array")
        summary = summary_value.strip()[:4000]
        specs.append(
            RunSpec(
                source_key=source_key,
                model_id=model_id,
                summary=summary,
                metrics={**metrics, "primary_metric_name": primary_metric_name, "primary_metric_value": primary_metric_value},
                params={
                    "source": "experiment_result_request",
                    "request_id": request_id,
                    "source_key": source_key,
                    "model_label": optional_text_field(item, "model_label") or optional_text_field(item, "display_name"),
                    "model_description": summary,
                    "features_used": json_safe_object([feature.strip() for feature in features_used]),
                    "feature_summary": optional_text_field(item, "feature_summary"),
                    "raw": json_safe_object(item),
                },
                primary_metric_name=primary_metric_name,
                primary_metric_value=primary_metric_value,
                source_artifact_id=optional_text_field(item, "source_artifact_id") or default_source_artifact_id,
                source_workspace_path=optional_text_field(item, "source_workspace_path") or default_source_workspace_path,
                research_plan_node_id=str(item.get("research_plan_node_id") or "").strip() or default_plan_node_id,
                dataset_snapshot_id=optional_text_field(item, "dataset_snapshot_id") or default_dataset_snapshot_id,
                evaluation_spec_id=optional_text_field(item, "evaluation_spec_id") or default_evaluation_spec_id,
                split_manifest_id=optional_text_field(item, "split_manifest_id") or default_split_manifest_id,
            )
        )
    primary_metric_names = {spec.primary_metric_name for spec in specs}
    if len(primary_metric_names) > 1:
        raise ValueError(
            "All runs in one experiment result request must use the same primary_metric_name; "
            f"received: {', '.join(sorted(primary_metric_names))}"
        )
    return specs


def run_specs_from_structured_result_payload(payload: dict[str, Any], *, source_artifact: Artifact) -> list[RunSpec]:
    schema_version = str(payload.get("schema_version") or "")
    if schema_version not in SUPPORTED_RESULT_SCHEMAS:
        return []
    raw_items = payload.get("comparisons") if schema_version == "text_ablation_model_comparison.v1" else payload.get("models")
    if not isinstance(raw_items, list):
        raw_items = payload.get("runs")
    if not isinstance(raw_items, list):
        return []
    specs: list[RunSpec] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        model_id = str(
            item.get("model_id")
            or item.get("model_name")
            or item.get("source_model_id")
            or item.get("condition")
            or f"model_{index + 1}"
        ).strip()
        metrics = normalize_metrics(item)
        try:
            primary_metric_name, primary_metric_value = primary_metric_from_payload(item, metrics)
        except ValueError:
            continue
        source_key = f"{source_artifact.id}:{schema_version}:{model_id}:{index}"
        summary = str(
            item.get("model_description")
            or item.get("description")
            or item.get("interpretation")
            or item.get("summary")
            or model_id
        ).strip()[:4000]
        plan_node_id = (
            str(item.get("research_plan_node_id") or payload.get("research_plan_node_id") or "").strip()
            or None
        )
        features_used = item.get("features_used") or item.get("feature_set")
        specs.append(
            RunSpec(
                source_key=source_key,
                model_id=model_id[:240],
                summary=summary,
                metrics={**metrics, "primary_metric_name": primary_metric_name, "primary_metric_value": primary_metric_value},
                params={
                    "source": "main_agent_session_structured_result",
                    "schema_version": schema_version,
                    "source_artifact_id": source_artifact.id,
                    "source_key": source_key,
                    "model_label": optional_text_field(item, "model_label") or optional_text_field(item, "display_name"),
                    "model_description": summary,
                    "features_used": json_safe_object(features_used) if isinstance(features_used, list) else [],
                    "feature_summary": optional_text_field(item, "feature_summary"),
                    "evaluation": json_safe_object(payload.get("evaluation")) if isinstance(payload.get("evaluation"), dict) else {},
                    "target": json_safe_object(payload.get("target")) if isinstance(payload.get("target"), dict) else {},
                    "raw": json_safe_object(item),
                },
                primary_metric_name=primary_metric_name,
                primary_metric_value=primary_metric_value,
                source_artifact_id=source_artifact.id,
                source_workspace_path=str(loads_json(source_artifact.metadata_json, {}).get("workspace_relative_path") or ""),
                research_plan_node_id=plan_node_id,
                dataset_snapshot_id=optional_text_field(payload, "dataset_snapshot_id"),
                evaluation_spec_id=optional_text_field(payload, "evaluation_spec_id"),
                split_manifest_id=optional_text_field(payload, "split_manifest_id"),
            )
        )
    return specs


def optional_text_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def normalize_metrics(source: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    nested_metrics = source.get("metrics")
    if isinstance(nested_metrics, dict):
        metrics.update(normalize_metric_mapping(nested_metrics))
    metrics.update(normalize_metric_mapping(source))
    return metrics


def normalize_metric_mapping(source: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            normalized = normalize_metric_name(str(key))
            metrics[normalized] = float(value)
        elif isinstance(value, dict):
            mean_value = value.get("mean")
            if isinstance(mean_value, bool):
                continue
            if isinstance(mean_value, int | float):
                normalized = normalize_metric_name(str(key))
                metrics[normalized] = float(mean_value)
    return metrics


def primary_metric_from_payload(item: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, float]:
    raw_name = item.get("primary_metric_name") or item.get("primary_metric")
    if isinstance(raw_name, str) and raw_name.strip():
        metric_name = normalize_metric_name(raw_name)
        value = metrics.get(metric_name)
        raw_value = item.get("primary_metric_value")
        if value is None and isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            value = float(raw_value)
        if value is None:
            raise ValueError(f"primary metric `{metric_name}` is missing or non-numeric")
        return metric_name, float(value)
    for metric_name in DEFAULT_PRIMARY_METRIC_ORDER:
        value = metrics.get(metric_name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return metric_name, float(value)
    raise ValueError("No numeric primary metric is available")


def register_experiment_run_specs(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    specs: list[RunSpec],
    source_artifact: Artifact | None,
    source_request_id: str | None,
) -> list[ExperimentRun]:
    del store
    validate_run_specs_have_single_primary_metric(specs)
    validate_run_spec_plan_node_refs(db, project=project, specs=specs)
    contexts = [
        resolve_run_spec_context(db, project=project, session=session, spec=spec, source_artifact=source_artifact)
        for spec in specs
    ]
    created: list[ExperimentRun] = []
    for spec, context in zip(specs, contexts, strict=True):
        validate_declared_research_plan_node_accepts_experiment_results(
            db,
            project=project,
            node_id=spec.research_plan_node_id,
        )
        if experiment_run_exists(db, project_id=project.id, source_key=spec.source_key):
            continue
        result_signature = experiment_result_signature(
            spec.metrics,
            model_id=spec.model_id,
            model_description=spec.summary,
            features_used=spec.params.get("features_used"),
            feature_summary=spec.params.get("feature_summary"),
        )
        if experiment_run_with_signature_exists(db, project_id=project.id, result_signature=result_signature):
            continue
        declared_research_plan_node_id = spec.research_plan_node_id
        research_plan_node_id = resolve_research_plan_node_for_run(
            db,
            project=project,
            explicit_node_id=declared_research_plan_node_id,
        )
        plan_link_status = "not_requested"
        plan_link_warning = None
        if declared_research_plan_node_id:
            plan_link_status = "linked"
        now = utc_now()
        run = ExperimentRun(
            id=new_id("run"),
            project_id=project.id,
            dataset_snapshot_id=context.dataset_snapshot_id,
            evaluation_spec_id=context.evaluation_spec_id,
            split_manifest_id=context.split_manifest_id,
            runner_type="codex_main_session",
            status="succeeded",
            started_at=now,
            ended_at=now,
            params_json=dumps_json(
                {
                    **spec.params,
                    "agent_session_id": session.id,
                    "source_request_id": source_request_id,
                    "source_artifact_id": context.source_artifact_id,
                    "source_workspace_path": spec.source_workspace_path,
                    "source_key": spec.source_key,
                    "result_signature": result_signature,
                    "model_id": spec.model_id,
                    "research_plan_node_id": research_plan_node_id,
                    "declared_research_plan_node_id": declared_research_plan_node_id,
                    "plan_link_status": plan_link_status,
                    "plan_link_warning": plan_link_warning,
                    "dataset_snapshot_id": context.dataset_snapshot_id,
                    "evaluation_spec_id": context.evaluation_spec_id,
                    "split_manifest_id": context.split_manifest_id,
                    "declared_dataset_snapshot_id": spec.dataset_snapshot_id,
                    "declared_evaluation_spec_id": spec.evaluation_spec_id,
                    "declared_split_manifest_id": spec.split_manifest_id,
                    "context_warnings": context.warnings,
                }
            ),
            metrics_json=dumps_json(spec.metrics),
            summary_md=spec.summary,
            created_by=session.created_by or project.created_by,
        )
        db.add(run)
        db.flush()
        created.append(run)
        source_artifact_id = context.source_artifact_id
        if source_artifact_id:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=source_artifact_id,
                to_asset_type="experiment_run",
                to_asset_id=run.id,
                relation_type="materializes_metrics_for",
                metadata={"agent_session_id": session.id, "source_key": spec.source_key, "model_id": spec.model_id},
                org_id=project.org_id,
            )
        attach_experiment_artifact_to_current_plan_node(
            db,
            project=project,
            source_artifact_id=source_artifact_id,
            run=run,
            node_id=research_plan_node_id,
            allow_current_fallback=False,
        )
    db.flush()
    return created


def validate_declared_research_plan_node_accepts_experiment_results(
    db: Session,
    *,
    project: Project,
    node_id: str | None,
) -> None:
    cleaned_node_id = node_id.strip() if isinstance(node_id, str) and node_id.strip() else None
    if cleaned_node_id is None:
        return
    revision = latest_research_plan_revision(db, project_id=project.id)
    if revision is None:
        return
    blocks = research_plan_blocks_from_revision(revision)
    matching_block: dict[str, Any] | None = None
    for index, block in enumerate(blocks):
        if research_plan_block_id(block, index) == cleaned_node_id:
            matching_block = block
            break
    if matching_block is None:
        return
    current = latest_research_plan_current_work(db, project_id=project.id)
    if (
        current is not None
        and current.node_id == cleaned_node_id
        and current.status in PLAN_CURRENT_STATUSES
    ):
        return
    status = research_plan_block_status(matching_block)
    if status == "pending":
        raise ValueError(
            f"ResearchPlan node `{cleaned_node_id}` is still pending. "
            "Before registering experiment results for that node, commit a ResearchPlan revision that makes it active/done "
            "or submit a research_plan.set_current_work request for the node."
        )


def validate_run_specs_have_single_primary_metric(specs: list[RunSpec]) -> None:
    primary_metric_names = {spec.primary_metric_name for spec in specs}
    if len(primary_metric_names) > 1:
        raise ValueError(
            "All runs in one experiment result payload must use the same primary_metric_name; "
            f"received: {', '.join(sorted(primary_metric_names))}"
        )


def resolve_research_plan_node_for_run(
    db: Session,
    *,
    project: Project,
    explicit_node_id: str | None,
) -> str | None:
    node_id = explicit_node_id.strip() if isinstance(explicit_node_id, str) and explicit_node_id.strip() else None
    if node_id:
        revision = latest_research_plan_revision(db, project_id=project.id)
        if research_plan_node_exists(revision, node_id=node_id):
            return node_id
        return None
    return None


def research_plan_node_exists(revision: ResearchPlanRevision | None, *, node_id: str) -> bool:
    if revision is None:
        return False
    try:
        validate_research_plan_node_exists(revision, node_id=node_id)
    except ValueError:
        return False
    return True


def experiment_plan_link_warnings(runs: list[ExperimentRun]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for run in runs:
        params = loads_json(run.params_json, {})
        warning = params.get("plan_link_warning")
        if not isinstance(warning, str) or not warning.strip():
            continue
        warnings.append(
            {
                "run_id": run.id,
                "model_id": params.get("model_id"),
                "declared_research_plan_node_id": params.get("declared_research_plan_node_id"),
                "message": warning,
            }
        )
    return warnings


def experiment_context_warnings(runs: list[ExperimentRun]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for run in runs:
        params = loads_json(run.params_json, {})
        raw_warnings = params.get("context_warnings")
        if not isinstance(raw_warnings, list):
            continue
        for warning in raw_warnings:
            if not isinstance(warning, dict):
                continue
            warnings.append(
                {
                    "run_id": run.id,
                    "model_id": params.get("model_id"),
                    "field": warning.get("field"),
                    "declared_value": warning.get("declared_value"),
                    "message": warning.get("message"),
                }
            )
    return warnings


def resolve_run_spec_context(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    spec: RunSpec,
    source_artifact: Artifact | None,
) -> RunSpecContext:
    source_artifact_id = resolve_run_spec_source_artifact_id(
        db,
        project=project,
        session=session,
        spec=spec,
        source_artifact=source_artifact,
    )
    dataset_snapshot_id = spec.dataset_snapshot_id
    evaluation_spec_id = spec.evaluation_spec_id
    split_manifest_id = spec.split_manifest_id
    warnings: list[dict[str, Any]] = []
    if split_manifest_id:
        split_manifest = db.get(SplitManifest, split_manifest_id)
        if split_manifest is None or split_manifest.project_id != project.id:
            warnings.append(
                {
                    "field": "split_manifest_id",
                    "declared_value": split_manifest_id,
                    "message": "Declared split_manifest_id is not registered for this project; the run is registered without a SplitManifest link.",
                }
            )
            split_manifest_id = None
        elif evaluation_spec_id and split_manifest.evaluation_spec_id != evaluation_spec_id:
            warnings.append(
                {
                    "field": "split_manifest_id",
                    "declared_value": split_manifest_id,
                    "message": "Declared split_manifest_id and evaluation_spec_id refer to different evaluation designs; the run keeps neither link.",
                }
            )
            split_manifest_id = None
            evaluation_spec_id = None
        else:
            evaluation_spec_id = split_manifest.evaluation_spec_id
    if evaluation_spec_id:
        evaluation_spec = db.get(EvaluationSpec, evaluation_spec_id)
        if evaluation_spec is None or evaluation_spec.project_id != project.id:
            warnings.append(
                {
                    "field": "evaluation_spec_id",
                    "declared_value": evaluation_spec_id,
                    "message": "Declared evaluation_spec_id is not registered for this project; the run is registered without an EvaluationSpec link.",
                }
            )
            evaluation_spec_id = None
        elif dataset_snapshot_id and evaluation_spec.dataset_snapshot_id != dataset_snapshot_id:
            warnings.append(
                {
                    "field": "evaluation_spec_id",
                    "declared_value": evaluation_spec_id,
                    "message": "Declared evaluation_spec_id and dataset_snapshot_id refer to different datasets; the run keeps neither link.",
                }
            )
            evaluation_spec_id = None
            dataset_snapshot_id = None
        else:
            dataset_snapshot_id = evaluation_spec.dataset_snapshot_id
    if dataset_snapshot_id:
        dataset_snapshot = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset_snapshot is None or dataset_snapshot.project_id != project.id:
            warnings.append(
                {
                    "field": "dataset_snapshot_id",
                    "declared_value": dataset_snapshot_id,
                    "message": "Declared dataset_snapshot_id is not registered for this project; the run is registered without a DatasetSnapshot link.",
                }
            )
            dataset_snapshot_id = None
    return RunSpecContext(
        source_artifact_id=source_artifact_id,
        dataset_snapshot_id=dataset_snapshot_id,
        evaluation_spec_id=evaluation_spec_id,
        split_manifest_id=split_manifest_id,
        warnings=warnings,
    )


def resolve_run_spec_source_artifact_id(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    spec: RunSpec,
    source_artifact: Artifact | None,
) -> str | None:
    explicit_artifact_id = spec.source_artifact_id or (source_artifact.id if source_artifact is not None else None)
    if explicit_artifact_id:
        artifact = db.get(Artifact, explicit_artifact_id)
        if artifact is None or artifact.project_id != project.id:
            raise ValueError(f"source_artifact_id `{explicit_artifact_id}` does not belong to this project")
        return artifact.id
    if not spec.source_workspace_path:
        return None
    artifact = latest_session_artifact_for_workspace_path(
        db,
        project=project,
        session=session,
        workspace_path=spec.source_workspace_path,
    )
    if artifact is None:
        raise ValueError(f"source_workspace_path `{spec.source_workspace_path}` is not registered as a Tablex artifact")
    return artifact.id


def latest_session_artifact_for_workspace_path(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    workspace_path: str,
) -> Artifact | None:
    normalized = workspace_path.strip().lstrip("./")
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.created_at.desc(), Artifact.version.desc())
            .limit(300)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        if str(metadata.get("workspace_relative_path") or "").strip().lstrip("./") == normalized:
            return artifact
    return None


def validate_run_spec_plan_node_refs(db: Session, *, project: Project, specs: list[RunSpec]) -> None:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project.id))
    if plan is None or not plan.active_revision_id:
        if any(spec.research_plan_node_id for spec in specs):
            raise ValueError("payload.research_plan_node_id was provided, but no active ResearchPlan revision exists")
        return
    revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    if revision is None:
        raise ValueError("payload.research_plan_node_id was provided, but no active ResearchPlan revision exists")
    missing = [spec.model_id for spec in specs if not spec.research_plan_node_id]
    if missing:
        raise ValueError(
            "Experiment result payloads must include a visible ResearchPlan node when a ResearchPlan exists. "
            "For `.tablex/requests/experiments/` use `payload.research_plan_node_id`; for `artifacts/model_results.json` "
            "use top-level `research_plan_node_id`; per-run `research_plan_node_id` is also accepted. "
            "Commit or update the ResearchPlan so the modeling/evaluation node is visible, then resubmit the model results for that node."
        )
    node_ids = sorted({spec.research_plan_node_id for spec in specs if spec.research_plan_node_id})
    for node_id in node_ids:
        validate_research_plan_node_exists(revision, node_id=node_id)


def experiment_run_exists(db: Session, *, project_id: str, source_key: str) -> bool:
    return experiment_run_for_source_key(db, project_id=project_id, source_key=source_key) is not None


def experiment_run_for_source_key(db: Session, *, project_id: str, source_key: str) -> ExperimentRun | None:
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id)).all()
    for run in runs:
        params = loads_json(run.params_json, {})
        if params.get("source_key") == source_key:
            return run
    return None


def experiment_run_with_signature_exists(db: Session, *, project_id: str, result_signature: str) -> bool:
    return experiment_run_for_signature(db, project_id=project_id, result_signature=result_signature) is not None


def experiment_run_for_signature(db: Session, *, project_id: str, result_signature: str) -> ExperimentRun | None:
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id)).all()
    for run in runs:
        params = loads_json(run.params_json, {})
        if params.get("result_signature") == result_signature:
            return run
        metrics = loads_json(run.metrics_json, {})
        if (
            experiment_result_signature(
                metrics,
                model_id=experiment_model_id_from_params(params),
                **experiment_signature_context_from_params(params),
            )
            == result_signature
        ):
            return run
    return None


def skipped_duplicate_run_specs_for_ack(
    db: Session,
    *,
    project_id: str,
    specs: list[RunSpec],
    created_runs: list[ExperimentRun],
) -> list[dict[str, Any]]:
    created_source_keys = {
        str(loads_json(run.params_json, {}).get("source_key") or "")
        for run in created_runs
        if str(loads_json(run.params_json, {}).get("source_key") or "").strip()
    }
    skipped: list[dict[str, Any]] = []
    for spec in specs:
        if spec.source_key in created_source_keys:
            continue
        result_signature = experiment_result_signature(
            spec.metrics,
            model_id=spec.model_id,
            model_description=spec.summary,
            features_used=spec.params.get("features_used"),
            feature_summary=spec.params.get("feature_summary"),
        )
        source_key_run = experiment_run_for_source_key(db, project_id=project_id, source_key=spec.source_key)
        signature_run = experiment_run_for_signature(db, project_id=project_id, result_signature=result_signature)
        existing_run = source_key_run or signature_run
        if existing_run is None:
            continue
        reason = "source_key_already_registered" if source_key_run is not None else "result_signature_already_registered"
        skipped.append(
            {
                "model_id": spec.model_id,
                "source_key": spec.source_key,
                "result_signature": result_signature,
                "existing_run_id": existing_run.id,
                "reason": reason,
            }
        )
    return skipped


def experiment_result_signature(
    metrics: dict[str, Any],
    *,
    model_id: str | None = None,
    model_description: Any = None,
    features_used: Any = None,
    feature_summary: Any = None,
) -> str:
    del model_id, feature_summary
    primary_metric_name = str(metrics.get("primary_metric_name") or "").strip().casefold()
    numeric_metrics = {
        key: round(float(value), 12)
        for key, value in metrics.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    normalized_features = (
        sorted(str(feature).strip().casefold() for feature in features_used if isinstance(feature, str) and feature.strip())
        if isinstance(features_used, list)
        else []
    )
    payload = {
        "primary_metric_name": primary_metric_name,
        "numeric_metrics": numeric_metrics,
        "model_description": str(model_description or "").strip().casefold(),
        "features_used": normalized_features,
    }
    return "metrics:" + hashlib.sha256(dumps_json(payload).encode("utf-8")).hexdigest()


def experiment_signature_context_from_params(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("raw") if isinstance(params.get("raw"), dict) else {}
    features_used = params.get("features_used")
    if not isinstance(features_used, list):
        features_used = raw.get("features_used") if isinstance(raw.get("features_used"), list) else []
    model_description = params.get("model_description")
    if not isinstance(model_description, str):
        model_description = raw.get("model_description") if isinstance(raw.get("model_description"), str) else ""
    feature_summary = params.get("feature_summary")
    if not isinstance(feature_summary, str):
        feature_summary = raw.get("feature_summary") if isinstance(raw.get("feature_summary"), str) else ""
    return {
        "model_description": model_description,
        "features_used": features_used,
        "feature_summary": feature_summary,
    }


def experiment_model_id_from_params(params: dict[str, Any]) -> str:
    for key in ("model_id", "run_name", "name"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = params.get("raw")
    if isinstance(raw, dict):
        for key in ("model_id", "source_model_id", "run_name", "name", "condition"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def attach_experiment_artifact_to_current_plan_node(
    db: Session,
    *,
    project: Project,
    source_artifact_id: str | None,
    run: ExperimentRun,
    node_id: str | None = None,
    allow_current_fallback: bool = True,
) -> None:
    current = latest_research_plan_current_work(db, project_id=project.id)
    target_node_id = node_id.strip() if isinstance(node_id, str) and node_id.strip() else None
    if target_node_id is None and allow_current_fallback:
        target_node_id = current.node_id if current is not None and current.node_id else None
    if target_node_id is None:
        return
    revision_id = None
    active_revision = latest_research_plan_revision(db, project_id=project.id)
    if active_revision is not None:
        try:
            validate_research_plan_node_exists(active_revision, node_id=target_node_id)
            revision_id = active_revision.id
        except ValueError:
            revision_id = None
    if revision_id is None and current is not None and current.node_id == target_node_id:
        revision_id = current.revision_id
    source_artifact = db.get(Artifact, source_artifact_id) if source_artifact_id else None
    if source_artifact is not None and source_artifact.project_id == project.id:
        try:
            attach_research_plan_artifact(
                db,
                project_id=project.id,
                node_id=target_node_id,
                artifact_id=source_artifact.id,
                role="experiment_evidence",
                revision_id=revision_id,
                metadata={"experiment_run_id": run.id},
            )
        except ValueError:
            pass
    attach_experiment_run_to_plan_node(
        db,
        project=project,
        node_id=target_node_id,
        run=run,
        revision_id=revision_id,
    )


def attach_experiment_run_to_plan_node(
    db: Session,
    *,
    project: Project,
    node_id: str,
    run: ExperimentRun,
    revision_id: str | None,
) -> None:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project.id))
    if plan is None:
        return
    revision = db.get(ResearchPlanRevision, revision_id) if revision_id else None
    if revision is None and plan.active_revision_id:
        revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    if revision is None:
        return
    existing = db.scalar(
        select(LineageEdge).where(
            LineageEdge.project_id == project.id,
            LineageEdge.from_asset_type == "research_plan_revision",
            LineageEdge.from_asset_id == revision.id,
            LineageEdge.to_asset_type == "experiment_run",
            LineageEdge.to_asset_id == run.id,
            LineageEdge.relation_type == "supports_plan_node",
        )
    )
    if existing is not None:
        return
    try:
        create_lineage_edge(
            db=db,
            project_id=project.id,
            from_asset_type="research_plan_revision",
            from_asset_id=revision.id,
            to_asset_type="experiment_run",
            to_asset_id=run.id,
            relation_type="supports_plan_node",
            metadata={
                "research_plan_id": plan.id,
                "revision_id": revision.id,
                "node_id": node_id[:160],
                "role": "experiment_run",
                "experiment_run_id": run.id,
            },
            org_id=project.org_id,
        )
    except ValueError:
        return


def register_experiment_result_failure_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    request_id: str,
    operation: str,
    error_type: str,
    error_message: str,
) -> Artifact | None:
    failure_fingerprint = experiment_result_failure_fingerprint(
        operation=operation,
        error_type=error_type,
        error_message=error_message,
    )
    if latest_experiment_result_failure_chat_turn(
        db,
        project=project,
        operation=operation,
        error_type=error_type,
        error_message=error_message,
    ):
        return None
    source_key = f"{request_id}:{operation}:{error_type}:{hashlib.sha1(error_message.encode('utf-8')).hexdigest()[:12]}"
    if experiment_registration_chat_turn_exists(db, project=project, session=session, source_key=source_key):
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    if japanese:
        assistant_message = (
            "モデル評価結果はまだLeaderboardに反映していません。"
            "表示中の順位表はそのまま保持し、分析は続いています。"
        )
        action_label = "状況を見る"
        action_detail = "現在の作業状況を確認できます。"
        next_label = "Agent workspace"
    else:
        assistant_message = (
            "The model evaluation results have not been added to the Leaderboard yet. "
            "The visible ranking is unchanged, and the analysis is continuing."
        )
        action_label = "Review status"
        action_detail = "Review the repair request and current agent state."
        next_label = "Agent workspace"
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "experiment_results_registration_failed",
            "source": "main_agent_session_workspace",
            "status": "needs_attention",
        },
        "actions": [
            {
                "type": "open_surface",
                "status": "needs_attention",
                "label": action_label,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "detail": action_detail,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "experiment_results_registration_failed.v1",
            "agent_session_id": session.id,
            "request_id": request_id,
            "operation": operation,
            "error_type": error_type,
            "error_message": error_message[:1200],
            "failure_fingerprint": failure_fingerprint,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": next_label},
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_experiment_result_failure_{session.id}_{hashlib.sha1(source_key.encode('utf-8')).hexdigest()[:12]}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source": "main_agent_session_experiment_registration",
            "source_key": source_key,
            "request_id": request_id,
            "operation": operation,
            "status": "failed",
            "failure_fingerprint": failure_fingerprint,
        },
    )


def register_structured_experiment_result_failure(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    artifact: Artifact,
    schema_version: str,
    error_type: str,
    error_message: str,
) -> None:
    metadata = loads_json(artifact.metadata_json, {})
    workspace_relative_path = str(metadata.get("workspace_relative_path") or "").strip()
    workspace = Path(session.workspace_path) if session.workspace_path else None
    if workspace is not None:
        write_experiment_result_artifact_rejection_to_workspace_inbox(
            workspace,
            source_artifact_id=artifact.id,
            workspace_relative_path=workspace_relative_path or artifact.name,
            schema_version=schema_version,
            error_type=error_type,
            error_message=error_message,
        )
    register_experiment_result_failure_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        request_id=artifact.id,
        operation=f"auto_register_{schema_version or 'structured_result'}",
        error_type=error_type,
        error_message=error_message,
    )


def register_experiment_registration_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    runs: list[ExperimentRun],
    source_artifact: Artifact | None,
    source_request_id: str | None,
) -> Artifact | None:
    if not runs:
        return None
    key = source_artifact.id if source_artifact is not None else source_request_id or hashlib.sha1(
        ",".join(run.id for run in runs).encode("utf-8")
    ).hexdigest()[:12]
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    best_run = sorted(runs, key=lambda run: leaderboard_sort_key_for_metric(run, None))[0]
    best_metrics = loads_json(best_run.metrics_json, {})
    metric_name = str(best_metrics.get("primary_metric_name") or "")
    metric_value = best_metrics.get("primary_metric_value")
    pipeline_registration = experiment_pipeline_registration_status(runs)
    pipeline_missing = pipeline_registration["status"] != "ready"
    model_diagnostics_artifacts = experiment_model_diagnostics_artifact_status(db, project=project, runs=runs)
    diagnostic_artifacts_missing = model_diagnostics_artifacts["status"] not in {"ready", "registered"}
    model_diagnostics_notebook = experiment_model_diagnostics_notebook_status(db, project=project, runs=runs)
    diagnostics_notebook_missing = model_diagnostics_notebook["status"] != "ready"
    visible_surfaces = experiment_result_visible_surfaces(runs, chat_artifact_id=None)
    visible_state_fingerprint = experiment_registration_visible_state_fingerprint(
        runs=runs,
        visible_surfaces=visible_surfaces,
        pipeline_registration=pipeline_registration,
        model_diagnostics_artifacts=model_diagnostics_artifacts,
        model_diagnostics_notebook=model_diagnostics_notebook,
    )
    result_set_fingerprint = experiment_registration_result_set_fingerprint(runs)
    notification_fingerprint = experiment_registration_notification_fingerprint(
        runs=runs,
        pipeline_registration=pipeline_registration,
        model_diagnostics_artifacts=model_diagnostics_artifacts,
        model_diagnostics_notebook=model_diagnostics_notebook,
    )
    run_ids = [run.id for run in runs]
    if japanese:
        assistant_message = (
            f"{len(runs)}件のモデル評価をLeaderboardに登録しました。"
            f"この結果セットの先頭候補は {best_run.summary_md or best_run.id} で、"
            f"{metric_name}={metric_value:.4g} です。"
            if isinstance(metric_value, int | float)
            else f"{len(runs)}件のモデル評価をLeaderboardに登録しました。"
        )
        missing_outputs: list[str] = []
        if pipeline_missing:
            missing_outputs.append("再現用の学習・予測スクリプト")
        if diagnostic_artifacts_missing:
            missing_outputs.append("permutation importance、feature importance、PDP、SHAPなどのモデル診断データ")
        if diagnostics_notebook_missing:
            missing_outputs.append("モデル診断Notebook")
        if missing_outputs:
            assistant_message += " 次に必要な登録: " + "、".join(missing_outputs) + "。"
        action_label = "リーダーボードを開く"
        action_detail = "同じ評価結果セットとして登録されたモデルを順位表で確認できます。"
        next_label = "リーダーボード"
    else:
        assistant_message = (
            f"Registered {len(runs)} model evaluation(s) on the leaderboard. "
            f"The leading candidate in this result set is {best_run.summary_md or best_run.id} "
            f"with {metric_name}={metric_value:.4g}."
            if isinstance(metric_value, int | float)
            else f"Registered {len(runs)} model evaluation(s) on the leaderboard."
        )
        missing_outputs = []
        if pipeline_missing:
            missing_outputs.append("reproducible train/predict scripts")
        if diagnostic_artifacts_missing:
            missing_outputs.append("model diagnostics data for permutation importance, feature importance, PDP, and SHAP")
        if diagnostics_notebook_missing:
            missing_outputs.append("model-diagnostics notebooks")
        if missing_outputs:
            assistant_message += " Still needed: " + ", ".join(missing_outputs) + "."
        action_label = "Open leaderboard"
        action_detail = "Compare the registered model runs as a ranked table."
        next_label = "Leaderboard"
    actions = experiment_registration_chat_actions(
        visible_surfaces=visible_surfaces,
        leaderboard_label=action_label,
        leaderboard_detail=action_detail,
        japanese=japanese,
    )
    existing_chat_artifact_for_source = latest_experiment_registration_chat_turn(
        db,
        project=project,
        session=session,
        source_key=key,
        run_ids=run_ids,
    )
    if existing_chat_artifact_for_source is not None:
        update_experiment_registration_chat_payload(
            db,
            existing_chat_artifact_for_source,
            session=session,
            runs=runs,
            source_artifact=source_artifact,
            source_request_id=source_request_id,
            visible_surfaces=visible_surfaces,
            actions=actions,
            assistant_message=assistant_message,
            visible_state_fingerprint=visible_state_fingerprint,
            result_set_fingerprint=result_set_fingerprint,
            notification_fingerprint=notification_fingerprint,
            japanese=japanese,
        )
        return None
    existing_chat_artifact_for_state = latest_experiment_registration_chat_turn(
        db,
        project=project,
        session=session,
        visible_state_fingerprint=visible_state_fingerprint,
        result_set_fingerprint=result_set_fingerprint,
        notification_fingerprint=notification_fingerprint,
        run_ids=run_ids,
    )
    if existing_chat_artifact_for_state is not None:
        update_experiment_registration_chat_payload(
            db,
            existing_chat_artifact_for_state,
            session=session,
            runs=runs,
            source_artifact=source_artifact,
            source_request_id=source_request_id,
            visible_surfaces=visible_surfaces,
            actions=actions,
            assistant_message=assistant_message,
            visible_state_fingerprint=visible_state_fingerprint,
            result_set_fingerprint=result_set_fingerprint,
            notification_fingerprint=notification_fingerprint,
            japanese=japanese,
        )
        return None
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "experiment_results_registered",
            "source": "main_agent_session_workspace",
            "status": "ready",
        },
        "actions": actions,
        "action_summary": {},
        "response_brief": {
            "schema_version": "experiment_results_registered.v1",
            "agent_session_id": session.id,
            "run_ids": run_ids,
            "source_artifact_id": source_artifact.id if source_artifact is not None else None,
            "source_request_id": source_request_id,
            "research_plan_node_ids": sorted(
                {
                    str(loads_json(run.params_json, {}).get("research_plan_node_id"))
                    for run in runs
                    if loads_json(run.params_json, {}).get("research_plan_node_id")
                }
            ),
            "visible_surfaces": visible_surfaces,
            "pipeline_registration": pipeline_registration,
            "model_diagnostics_artifacts": model_diagnostics_artifacts,
            "model_diagnostics_notebook": model_diagnostics_notebook,
            "result_set_fingerprint": result_set_fingerprint,
            "notification_fingerprint": notification_fingerprint,
        },
        "visible_surfaces": visible_surfaces,
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": "Leaderboard", "target_anchor": "result-readout", "label": next_label},
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_experiment_results_{session.id}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source": "main_agent_session_experiment_registration",
            "source_key": key,
            "source_artifact_id": source_artifact.id if source_artifact is not None else None,
            "source_request_id": source_request_id,
            "visible_state_fingerprint": visible_state_fingerprint,
            "result_set_fingerprint": result_set_fingerprint,
            "notification_fingerprint": notification_fingerprint,
        },
    )
    update_experiment_registration_chat_payload(
        db,
        chat_artifact,
        session=session,
        runs=runs,
        source_artifact=source_artifact,
        source_request_id=source_request_id,
        visible_surfaces=visible_surfaces,
        actions=actions,
        assistant_message=assistant_message,
        visible_state_fingerprint=visible_state_fingerprint,
        result_set_fingerprint=result_set_fingerprint,
        notification_fingerprint=notification_fingerprint,
        japanese=japanese,
    )
    return chat_artifact


def experiment_registration_visible_state_fingerprint(
    *,
    runs: list[ExperimentRun],
    visible_surfaces: dict[str, Any],
    pipeline_registration: dict[str, Any],
    model_diagnostics_artifacts: dict[str, Any],
    model_diagnostics_notebook: dict[str, Any],
) -> str:
    payload = {
        "schema_version": "experiment_registration_visible_state.v1",
        "run_ids": sorted(run.id for run in runs),
        "research_plan_node_ids": sorted(
            {
                str(loads_json(run.params_json, {}).get("research_plan_node_id"))
                for run in runs
                if loads_json(run.params_json, {}).get("research_plan_node_id")
            }
        ),
        "visible_surfaces": visible_surfaces,
        "pipeline_registration": pipeline_registration,
        "model_diagnostics_artifacts": model_diagnostics_artifacts,
        "model_diagnostics_notebook": model_diagnostics_notebook,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def experiment_registration_notification_fingerprint(
    *,
    runs: list[ExperimentRun],
    pipeline_registration: dict[str, Any],
    model_diagnostics_artifacts: dict[str, Any],
    model_diagnostics_notebook: dict[str, Any],
) -> str:
    run_keys: list[str] = []
    for run in runs:
        params = loads_json(run.params_json, {})
        metrics = loads_json(run.metrics_json, {})
        result_signature = str(params.get("result_signature") or "").strip()
        if not result_signature:
            result_signature = experiment_result_signature(
                metrics,
                model_id=experiment_model_id_from_params(params),
                **experiment_signature_context_from_params(params),
            )
        run_keys.append(result_signature or run.id)
    payload = {
        "schema_version": "experiment_registration_notification.v1",
        "run_keys": sorted(run_keys),
        "pipeline_status": pipeline_registration.get("status"),
        "pipeline_missing_count": pipeline_registration.get("missing_count"),
        "diagnostics_status": model_diagnostics_artifacts.get("status"),
        "diagnostics_missing_count": model_diagnostics_artifacts.get("missing_count"),
        "notebook_status": model_diagnostics_notebook.get("status"),
        "notebook_missing_count": model_diagnostics_notebook.get("missing_count"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def experiment_registration_result_set_fingerprint(runs: list[ExperimentRun]) -> str:
    run_keys: list[str] = []
    for run in runs:
        params = loads_json(run.params_json, {})
        metrics = loads_json(run.metrics_json, {})
        result_signature = str(params.get("result_signature") or "").strip()
        if not result_signature:
            result_signature = experiment_result_signature(
                metrics,
                model_id=experiment_model_id_from_params(params),
                **experiment_signature_context_from_params(params),
            )
        run_keys.append(result_signature or run.id)
    payload = {
        "schema_version": "experiment_registration_result_set.v1",
        "run_keys": sorted(run_keys),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def update_experiment_registration_chat_payload(
    db: Session,
    chat_artifact: Artifact,
    *,
    session: AgentSession,
    runs: list[ExperimentRun],
    source_artifact: Artifact | None,
    source_request_id: str | None,
    visible_surfaces: dict[str, Any],
    actions: list[dict[str, Any]],
    assistant_message: str,
    visible_state_fingerprint: str,
    result_set_fingerprint: str,
    notification_fingerprint: str,
    japanese: bool,
) -> None:
    visible_surfaces_with_chat = {
        **visible_surfaces,
        "chat": {
            **visible_surfaces.get("chat", {}),
            "target_tab": "Home",
            "target_anchor": "agent-workspace",
            "artifact_id": chat_artifact.id,
        },
    }
    try:
        path = artifact_primary_path(chat_artifact)
        payload = loads_json(path.read_text(encoding="utf-8"), {})
        if isinstance(payload, dict):
            payload.setdefault("schema_version", "agent_chat_turn.v1")
            payload.setdefault("project_id", chat_artifact.project_id)
            payload.setdefault("user_message", "")
            payload["assistant_message"] = assistant_message or experiment_registration_minimal_message(runs, japanese=japanese)
            if not isinstance(payload.get("intent"), dict):
                payload["intent"] = {
                    "type": "experiment_results_registered",
                    "source": "main_agent_session_workspace",
                    "status": "ready",
                }
            payload.setdefault("action_summary", {})
            payload.setdefault(
                "response_composer",
                {
                    "schema_version": "agent_response_composer.v1",
                    "mode": "main_agent_session",
                    "status": "harness_fact",
                },
            )
            payload.setdefault("worker_events", [])
            payload.setdefault("token_usage", {"source": "not_applicable", "is_estimate": False, "series": []})
            payload.setdefault(
                "next_focus",
                {
                    "target_tab": "Leaderboard",
                    "target_anchor": "result-readout",
                    "label": "リーダーボード" if japanese else "Leaderboard",
                },
            )
            payload["actions"] = actions
            payload["visible_surfaces"] = visible_surfaces_with_chat
            response_brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
            project = db.get(Project, chat_artifact.project_id)
            payload["response_brief"] = {
                "schema_version": "experiment_results_registered.v1",
                **response_brief,
                "run_ids": [run.id for run in runs],
                "source_artifact_id": source_artifact.id if source_artifact is not None else None,
                "source_request_id": source_request_id,
                "research_plan_node_ids": sorted(
                    {
                        str(loads_json(run.params_json, {}).get("research_plan_node_id"))
                        for run in runs
                        if loads_json(run.params_json, {}).get("research_plan_node_id")
                    }
                ),
                "visible_surfaces": visible_surfaces_with_chat,
                "pipeline_registration": experiment_pipeline_registration_status(runs),
                "model_diagnostics_artifacts": experiment_model_diagnostics_artifact_status(
                    db,
                    project=project,
                    runs=runs,
                )
                if project is not None
                else response_brief.get("model_diagnostics_artifacts"),
                "model_diagnostics_notebook": experiment_model_diagnostics_notebook_status(
                    db,
                    project=project,
                    runs=runs,
                )
                if project is not None
                else response_brief.get("model_diagnostics_notebook"),
                "result_set_fingerprint": result_set_fingerprint,
                "notification_fingerprint": notification_fingerprint,
            }
            encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            path.write_bytes(encoded)
            chat_artifact.content_hash = hashlib.sha256(encoded).hexdigest()
            chat_artifact.size_bytes = len(encoded)
            # Keep the original chat chronology stable. Rescans may enrich links
            # on the existing notice, but they must not make an old leaderboard
            # result appear as a fresh chat message.
            metadata = loads_json(chat_artifact.metadata_json, {})
            metadata["agent_session_id"] = session.id
            metadata["visible_state_fingerprint"] = visible_state_fingerprint
            metadata["result_set_fingerprint"] = result_set_fingerprint
            metadata["notification_fingerprint"] = notification_fingerprint
            chat_artifact.metadata_json = dumps_json(metadata)
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass


def experiment_registration_minimal_message(runs: list[ExperimentRun], *, japanese: bool) -> str:
    count = len(runs)
    if japanese:
        return f"{count}件のモデル評価をLeaderboardに登録しました。"
    return f"Registered {count} model evaluation(s) on the leaderboard."


def experiment_registration_chat_actions(
    *,
    visible_surfaces: dict[str, Any],
    leaderboard_label: str,
    leaderboard_detail: str,
    japanese: bool,
) -> list[dict[str, Any]]:
    leaderboard_surface = visible_surfaces["leaderboard"]
    actions: list[dict[str, Any]] = [
        {
            "type": "open_surface",
            "status": "ready",
            "label": leaderboard_label,
            "target_tab": leaderboard_surface["target_tab"],
            "target_anchor": leaderboard_surface["target_anchor"],
            "detail": leaderboard_detail,
            "entity_ids": leaderboard_surface["run_ids"],
        }
    ]
    assets_surface = visible_surfaces.get("assets")
    if isinstance(assets_surface, dict):
        actions.append(
            {
                "type": "open_artifact",
                "status": "ready",
                "label": "根拠アセットを見る" if japanese else "Open evidence asset",
                "target_tab": assets_surface["target_tab"],
                "target_anchor": assets_surface["target_anchor"],
                "detail": "登録されたモデル評価のsource artifactへ移動します。"
                if japanese
                else "Open the source artifact behind the registered model results.",
                "artifact_id": assets_surface["artifact_id"],
                "artifact_ids": assets_surface["artifact_ids"],
            }
        )
    data_surface = visible_surfaces.get("data")
    if isinstance(data_surface, dict):
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "関連データを見る" if japanese else "Open related data",
                "target_tab": data_surface["target_tab"],
                "target_anchor": data_surface["target_anchor"],
                "detail": "このRun群が評価されたDataset文脈へ移動します。"
                if japanese
                else "Open the Dataset context used by these runs.",
                "entity_ids": data_surface["dataset_snapshot_ids"],
            }
        )
    evaluation_surface = visible_surfaces.get("evaluation")
    if isinstance(evaluation_surface, dict):
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "評価設計を見る" if japanese else "Open evaluation design",
                "target_tab": evaluation_surface["target_tab"],
                "target_anchor": evaluation_surface["target_anchor"],
                "detail": "このRun群が従うEvaluationSpec / SplitManifest文脈へ移動します。"
                if japanese
                else "Open the EvaluationSpec / SplitManifest context for these runs.",
                "entity_ids": evaluation_surface["evaluation_spec_ids"] + evaluation_surface["split_manifest_ids"],
            }
        )
    return actions


def experiment_registration_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    source_key: str,
) -> bool:
    return latest_experiment_registration_chat_turn(db, project=project, session=session, source_key=source_key) is not None


def latest_experiment_registration_chat_turn(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    source_key: str | None = None,
    visible_state_fingerprint: str | None = None,
    result_set_fingerprint: str | None = None,
    notification_fingerprint: str | None = None,
    run_ids: list[str] | None = None,
) -> Artifact | None:
    normalized_run_ids = normalize_experiment_registration_run_ids(run_ids)
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
                Artifact.metadata_json.contains("main_agent_session_experiment_registration"),
            )
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_experiment_registration"
            and (
                (source_key is not None and metadata.get("source_key") == source_key)
                or (
                    visible_state_fingerprint is not None
                    and metadata.get("visible_state_fingerprint") == visible_state_fingerprint
                )
                or (
                    result_set_fingerprint is not None
                    and metadata.get("result_set_fingerprint") == result_set_fingerprint
                )
                or (
                    notification_fingerprint is not None
                    and metadata.get("notification_fingerprint") == notification_fingerprint
                )
                or (
                    normalized_run_ids
                    and experiment_registration_artifact_run_ids(artifact) == normalized_run_ids
                )
            )
        ):
            return artifact
    return None


def normalize_experiment_registration_run_ids(run_ids: list[str] | None) -> list[str]:
    if not isinstance(run_ids, list):
        return []
    return sorted({item.strip() for item in run_ids if isinstance(item, str) and item.strip()})


def experiment_registration_artifact_run_ids(artifact: Artifact) -> list[str]:
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "experiment_results_registered":
        return []
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    run_ids = brief.get("run_ids")
    if not isinstance(run_ids, list):
        visible_surfaces = payload.get("visible_surfaces") if isinstance(payload.get("visible_surfaces"), dict) else {}
        leaderboard = (
            visible_surfaces.get("leaderboard") if isinstance(visible_surfaces.get("leaderboard"), dict) else {}
        )
        run_ids = leaderboard.get("run_ids")
    return normalize_experiment_registration_run_ids(run_ids if isinstance(run_ids, list) else None)


def experiment_result_failure_fingerprint(*, operation: str, error_type: str, error_message: str) -> str:
    payload = {
        "operation": operation,
        "error_type": error_type,
        "error_hash": hashlib.sha1(error_message.encode("utf-8")).hexdigest()[:12],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def latest_experiment_result_failure_chat_turn(
    db: Session,
    *,
    project: Project,
    operation: str,
    error_type: str,
    error_message: str,
) -> Artifact | None:
    fingerprint = experiment_result_failure_fingerprint(
        operation=operation,
        error_type=error_type,
        error_message=error_message,
    )
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project.id,
                Artifact.asset_type == "agent_chat_turn",
                Artifact.metadata_json.contains("main_agent_session_experiment_registration"),
            )
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_experiment_registration":
            continue
        if metadata.get("failure_fingerprint") == fingerprint:
            return artifact
        if experiment_result_failure_artifact_fingerprint(artifact) == fingerprint:
            return artifact
    return None


def experiment_result_failure_artifact_fingerprint(artifact: Artifact) -> str | None:
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "experiment_results_registration_failed":
        return None
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    fingerprint = brief.get("failure_fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return fingerprint.strip()
    operation = brief.get("operation")
    error_type = brief.get("error_type")
    error_message = brief.get("error_message")
    if not all(isinstance(value, str) and value.strip() for value in [operation, error_type, error_message]):
        return None
    return experiment_result_failure_fingerprint(
        operation=str(operation),
        error_type=str(error_type),
        error_message=str(error_message),
    )


def run_spec_source_request_id(run: ExperimentRun) -> str:
    params = loads_json(run.params_json, {})
    value = params.get("source_request_id")
    return str(value) if value else run.id


def latest_project_response_locale(db: Session, project: Project) -> str:
    candidates: list[tuple[datetime, str]] = []
    user = db.get(User, project.created_by) if project.created_by else None
    if user is not None and user.locale and user.locale.strip():
        candidates.append((_utc_comparable(user.updated_at), user.locale.strip()))
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project.id, Job.job_type.in_(["start_autonomous_loop", "agent_chat_turn"]))
            .order_by(Job.created_at.desc())
            .limit(20)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            candidates.append((_utc_comparable(job.created_at), locale.strip()))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return "en-US"


def _utc_comparable(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def write_experiment_result_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_experiment_result_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
) -> None:
    path = experiment_request_rejection_path(workspace)
    lines = [
        "schema_version: tablex_experiment_result_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The Experiment result request was rejected by Tablex validation and did not create ExperimentRun records, Leaderboard rows, ResearchPlan evidence, or model/run contextual links.",
        "Read the ack JSON, repair the fixed request payload, and resubmit under `.tablex/requests/experiments/` with a new request_id.",
        "",
        "Valid result requests should keep rows comparable within the same request, use one primary metric for ranked rows, include available dataset/evaluation/split context, and reference a valid ResearchPlan node when the work belongs to a visible plan node.",
        "",
        "Error:",
        error_message,
    ]
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="experiment_result_request_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_experiment_result_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
        },
        title="Experiment result request rejected",
    )


def write_pipeline_registration_request_to_workspace_inbox(
    workspace: Path,
    *,
    runs: list[ExperimentRun],
    source_request_id: str | None,
    pipeline_registration: dict[str, Any],
) -> None:
    if not runs or pipeline_registration.get("status") == "ready":
        return
    payload = {
        "schema_version": "tablex_pipeline_registration_request.v1",
        "source_request_id": source_request_id,
        "pipeline_registration": pipeline_registration,
        "run_ids": [run.id for run in runs],
    }
    if workspace_inbox_has_payload(
        workspace,
        kind="request",
        entry_type="pipeline_registration_request",
        payload=payload,
    ):
        return
    missing_runs = pipeline_registration.get("missing_runs") if isinstance(pipeline_registration, dict) else []
    missing_items = missing_runs if isinstance(missing_runs, list) else []
    lines = [
        "schema_version: tablex_pipeline_registration_request.v1",
        f"created_at: {utc_now().isoformat()}",
        f"source_request_id: {source_request_id or '<unknown>'}",
        f"missing_count: {pipeline_registration.get('missing_count', len(missing_items))}",
        "",
        "Leaderboard rows were registered, but one or more runs do not yet have reproducible prediction pipeline bundles.",
        "Continue the work and create pipeline directories under `pipelines/<name>/` for the missing runs, then submit fixed JSON requests under `.tablex/requests/pipelines/` with `schema_version: \"tablex_pipeline_request.v1\"` and operation `register_prediction_pipeline`.",
        "",
        "Required pipeline files:",
        "- pipeline_manifest.json",
        "- train.py",
        "- predict.py",
        "- requirements.txt",
        "- README.md",
        "",
        "The pipeline must accept production-style inference input without the target column. If history is required, declare it in pipeline_manifest.json history_requirements and recompute lag/rolling features inside predict.py.",
        "",
        "Missing runs:",
    ]
    for item in missing_items[:50]:
        if not isinstance(item, dict):
            continue
        lines.append(f"- run_id: {item.get('run_id')}")
        lines.append(f"  model_id: {item.get('model_id')}")
        description = str(item.get("model_description") or "").strip()
        if description:
            lines.append(f"  model_description: {description[:500]}")
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="pipeline_registration_request",
        lines=lines,
        payload=payload,
        title="Pipeline registration requested",
    )


def write_model_diagnostics_artifact_request_to_workspace_inbox(
    workspace: Path,
    *,
    runs: list[ExperimentRun],
    source_request_id: str | None,
    diagnostics_status: dict[str, Any],
) -> None:
    if not runs or diagnostics_status.get("status") in {"ready", "registered"}:
        return
    payload = {
        "schema_version": "tablex_model_diagnostics_artifact_request.v1",
        "source_request_id": source_request_id,
        "diagnostics_status": diagnostics_status,
        "run_ids": [run.id for run in runs],
    }
    if workspace_inbox_has_payload(
        workspace,
        kind="request",
        entry_type="model_diagnostics_artifact_request",
        payload=payload,
    ):
        return
    missing_runs = diagnostics_status.get("missing_runs") if isinstance(diagnostics_status, dict) else []
    missing_items = missing_runs if isinstance(missing_runs, list) else []
    lines = [
        "schema_version: tablex_model_diagnostics_artifact_request.v1",
        f"created_at: {utc_now().isoformat()}",
        f"source_request_id: {source_request_id or '<unknown>'}",
        f"missing_count: {len(missing_items)}",
        "",
        "Leaderboard rows were registered, but one or more runs do not yet have standard model-diagnostics artifacts.",
        "Continue the work and submit fixed JSON requests under `.tablex/requests/model_diagnostics/`.",
        "",
        "Request contract:",
        f"- schema_version: \"{MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION}\"",
        "- operation: \"register_model_diagnostics_artifacts\"",
        "- payload.run_id or payload.related_run_ids must reference the registered ExperimentRun ids.",
        "- payload.checks must include permutation_importance, native_feature_importance, partial_dependence, and shap.",
        "- For each check, status must be included, not_applicable, needs_model_artifact, needs_dependency, or deferred.",
        "- Any included check must provide a matching artifact in payload.artifacts.",
        "- Artifact keys: permutation_importance, native_feature_importance, partial_dependence, shap or shap_summary, model_diagnostics_artifact_pack.",
        "",
        "Missing runs:",
    ]
    for item in missing_items[:50]:
        if not isinstance(item, dict):
            continue
        lines.append(f"- run_id: {item.get('run_id')}")
        lines.append(f"  model_id: {item.get('model_id')}")
        missing_checks = item.get("missing_checks")
        if isinstance(missing_checks, list) and missing_checks:
            lines.append("  missing_checks: " + ", ".join(str(check) for check in missing_checks))
        description = str(item.get("model_description") or "").strip()
        if description:
            lines.append(f"  model_description: {description[:500]}")
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="model_diagnostics_artifact_request",
        lines=lines,
        payload=payload,
        title="Model diagnostics artifacts requested",
    )


def write_model_diagnostics_notebook_request_to_workspace_inbox(
    workspace: Path,
    *,
    runs: list[ExperimentRun],
    source_request_id: str | None,
    diagnostics_status: dict[str, Any],
) -> None:
    if not runs or diagnostics_status.get("status") == "ready":
        return
    payload = {
        "schema_version": "tablex_model_diagnostics_notebook_request.v1",
        "source_request_id": source_request_id,
        "diagnostics_status": diagnostics_status,
        "run_ids": [run.id for run in runs],
    }
    if workspace_inbox_has_payload(
        workspace,
        kind="request",
        entry_type="model_diagnostics_notebook_request",
        payload=payload,
    ):
        return
    missing_runs = diagnostics_status.get("missing_runs") if isinstance(diagnostics_status, dict) else []
    missing_items = missing_runs if isinstance(missing_runs, list) else []
    lines = [
        "schema_version: tablex_model_diagnostics_notebook_request.v1",
        f"created_at: {utc_now().isoformat()}",
        f"source_request_id: {source_request_id or '<unknown>'}",
        f"missing_count: {diagnostics_status.get('missing_count', len(missing_items))}",
        "",
        "Leaderboard rows were registered, but one or more runs do not yet have linked model-diagnostics marimo notebooks.",
        "Continue the work and author native marimo notebook source for the missing runs, then submit fixed JSON requests under `.tablex/requests/notebooks/` with `schema_version: \"tablex_notebook_request.v1\"` and operation `register_notebook`.",
        "",
        "Notebook request requirements:",
        "- notebook_kind: model_diagnostics",
        "- run_id: the single ExperimentRun being diagnosed, or related_run_ids: an array of ExperimentRun ids when one notebook compares multiple leaderboard rows",
        "- quality_manifest.figure_count > 0 with meaningful visual diagnostics",
        "- quality_manifest.model_diagnostics.checks entries for permutation_importance, native_feature_importance, partial_dependence, and shap",
        "- each check uses status included, not_applicable, needs_model_artifact, needs_dependency, or deferred with evidence/reason",
        "",
        "Missing runs:",
    ]
    for item in missing_items[:50]:
        if not isinstance(item, dict):
            continue
        lines.append(f"- run_id: {item.get('run_id')}")
        lines.append(f"  model_id: {item.get('model_id')}")
        description = str(item.get("model_description") or "").strip()
        if description:
            lines.append(f"  model_description: {description[:500]}")
    write_workspace_inbox_text(
        workspace,
        kind="request",
        entry_type="model_diagnostics_notebook_request",
        lines=lines,
        payload=payload,
        title="Model diagnostics notebook requested",
    )


def write_experiment_result_artifact_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    source_artifact_id: str,
    workspace_relative_path: str,
    schema_version: str,
    error_type: str,
    error_message: str,
) -> None:
    payload = {
        "schema_version": "tablex_experiment_result_artifact_rejection.v1",
        "source_artifact_id": source_artifact_id,
        "workspace_path": workspace_relative_path,
        "result_schema_version": schema_version,
        "error_type": error_type,
        "error_message": error_message,
    }
    for entry in list_inbox_entries(workspace):
        if entry.get("kind") != "rejection" or entry.get("type") != "experiment_result_artifact_rejection":
            continue
        existing_payload = entry.get("payload")
        if isinstance(existing_payload, dict) and existing_payload == payload:
            return
    lines = [
        "schema_version: tablex_experiment_result_artifact_rejection.v1",
        f"source_artifact_id: {source_artifact_id}",
        f"workspace_path: {workspace_relative_path}",
        f"result_schema_version: {schema_version or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"error_type: {error_type}",
        "",
        "The structured model result artifact was registered as a workspace artifact, but Tablex could not materialize it into ExperimentRun records, Leaderboard rows, ResearchPlan evidence, or model/run contextual links.",
        "Repair the structured result file or submit a fixed request under `.tablex/requests/experiments/` with `schema_version: \"tablex_experiment_result_request.v1\"`.",
        "",
        "Valid model result rows need a stable model_id, one comparable primary metric, and a numeric primary metric value. Include dataset/evaluation/split and ResearchPlan node references when they are known.",
        "",
        "Error:",
        error_message,
    ]
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="experiment_result_artifact_rejection",
        lines=lines,
        payload=payload,
        title="Experiment result artifact rejected",
    )


def json_safe_object(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
    return value
