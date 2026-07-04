from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    ExperimentRun,
    Project,
    User,
    utc_now,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.metric_preferences import (
    leaderboard_sort_key_for_metric,
    normalize_metric_name,
)
from tabular_harness.services.research_plans import (
    attach_research_plan_artifact,
    latest_research_plan_current_work,
)

EXPERIMENT_REQUESTS_DIR = "experiments"
EXPERIMENT_ACK_SCHEMA_VERSION = "tablex_experiment_result_ack.v1"
EXPERIMENT_REQUEST_SCHEMA_VERSION = "tablex_experiment_result_request.v1"
SUPPORTED_RESULT_SCHEMAS = {
    "model_results.v1",
    "text_ablation_model_comparison.v1",
    "structured_target_encoding_model.v1",
}
DEFAULT_PRIMARY_METRIC_ORDER = ("mae", "rmse", "log_mae", "roc_auc", "pr_auc", "accuracy", "r2")


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


def experiment_requests_dir(workspace: Path) -> Path:
    return workspace / ".tablex" / "requests" / EXPERIMENT_REQUESTS_DIR


def experiment_acks_dir(workspace: Path) -> Path:
    return workspace / ".tablex" / "acks" / EXPERIMENT_REQUESTS_DIR


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
            ack = {
                "schema_version": EXPERIMENT_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": {
                    "registered_run_ids": [run.id for run in runs],
                    "registered_count": len(runs),
                    "duplicate_count": max(0, len(specs) - len(runs)),
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
    if created_runs:
        register_experiment_registration_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            runs=created_runs,
            source_artifact=None,
            source_request_id=",".join(sorted({run_spec_source_request_id(run) for run in created_runs})),
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
        specs = run_specs_from_structured_result_payload(payload, source_artifact=artifact)
        runs = register_experiment_run_specs(
            db,
            store=store,
            project=project,
            session=session,
            specs=specs,
            source_artifact=artifact,
            source_request_id=None,
        )
        if runs:
            created_runs.extend(runs)
            created_by_artifact[artifact.id] = runs
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
    return created_runs


def run_specs_from_experiment_request(payload: dict[str, Any], *, request_id: str) -> list[RunSpec]:
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("payload.runs must contain at least one run")
    specs: list[RunSpec] = []
    for index, item in enumerate(raw_runs):
        if not isinstance(item, dict):
            raise ValueError(f"payload.runs/{index} must be an object")
        model_id = str(item.get("model_id") or item.get("run_name") or item.get("name") or "").strip()
        if not model_id:
            raise ValueError(f"payload.runs/{index}/model_id is required")
        metrics = normalize_metrics(item.get("metrics") if isinstance(item.get("metrics"), dict) else item)
        primary_metric_name, primary_metric_value = primary_metric_from_payload(item, metrics)
        source_key = str(item.get("source_key") or f"{request_id}:{model_id}:{index}")
        specs.append(
            RunSpec(
                source_key=source_key,
                model_id=model_id,
                summary=str(item.get("summary") or item.get("interpretation") or model_id)[:4000],
                metrics={**metrics, "primary_metric_name": primary_metric_name, "primary_metric_value": primary_metric_value},
                params={
                    "source": "experiment_result_request",
                    "request_id": request_id,
                    "source_key": source_key,
                    "raw": json_safe_object(item),
                },
                primary_metric_name=primary_metric_name,
                primary_metric_value=primary_metric_value,
                source_artifact_id=str(item.get("source_artifact_id")) if item.get("source_artifact_id") else None,
                source_workspace_path=str(item.get("source_workspace_path")) if item.get("source_workspace_path") else None,
            )
        )
    return specs


def run_specs_from_structured_result_payload(payload: dict[str, Any], *, source_artifact: Artifact) -> list[RunSpec]:
    schema_version = str(payload.get("schema_version") or "")
    if schema_version not in SUPPORTED_RESULT_SCHEMAS:
        return []
    raw_items = payload.get("comparisons") if schema_version == "text_ablation_model_comparison.v1" else payload.get("models")
    if not isinstance(raw_items, list):
        return []
    specs: list[RunSpec] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id") or item.get("source_model_id") or item.get("condition") or f"model_{index + 1}").strip()
        metrics = normalize_metrics(item)
        try:
            primary_metric_name, primary_metric_value = primary_metric_from_payload(item, metrics)
        except ValueError:
            continue
        source_key = f"{source_artifact.id}:{schema_version}:{model_id}:{index}"
        summary = str(item.get("interpretation") or item.get("summary") or model_id).strip()[:4000]
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
                    "evaluation": json_safe_object(payload.get("evaluation")) if isinstance(payload.get("evaluation"), dict) else {},
                    "target": json_safe_object(payload.get("target")) if isinstance(payload.get("target"), dict) else {},
                    "raw": json_safe_object(item),
                },
                primary_metric_name=primary_metric_name,
                primary_metric_value=primary_metric_value,
                source_artifact_id=source_artifact.id,
                source_workspace_path=str(loads_json(source_artifact.metadata_json, {}).get("workspace_relative_path") or ""),
            )
        )
    return specs


def normalize_metrics(source: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            normalized = normalize_metric_name(str(key))
            metrics[normalized] = float(value)
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
    created: list[ExperimentRun] = []
    for spec in specs:
        if experiment_run_exists(db, project_id=project.id, source_key=spec.source_key):
            continue
        result_signature = experiment_result_signature(spec.metrics, model_id=spec.model_id)
        if experiment_run_with_signature_exists(db, project_id=project.id, result_signature=result_signature):
            continue
        now = utc_now()
        run = ExperimentRun(
            id=new_id("run"),
            project_id=project.id,
            runner_type="codex_main_session",
            status="succeeded",
            started_at=now,
            ended_at=now,
            params_json=dumps_json(
                {
                    **spec.params,
                    "agent_session_id": session.id,
                    "source_request_id": source_request_id,
                    "source_artifact_id": spec.source_artifact_id or (source_artifact.id if source_artifact is not None else None),
                    "source_workspace_path": spec.source_workspace_path,
                    "source_key": spec.source_key,
                    "result_signature": result_signature,
                    "model_id": spec.model_id,
                }
            ),
            metrics_json=dumps_json(spec.metrics),
            summary_md=spec.summary,
            created_by=session.created_by or project.created_by,
        )
        db.add(run)
        db.flush()
        created.append(run)
        source_artifact_id = spec.source_artifact_id or (source_artifact.id if source_artifact is not None else None)
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
        )
    db.flush()
    return created


def experiment_run_exists(db: Session, *, project_id: str, source_key: str) -> bool:
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id)).all()
    for run in runs:
        params = loads_json(run.params_json, {})
        if params.get("source_key") == source_key:
            return True
    return False


def experiment_run_with_signature_exists(db: Session, *, project_id: str, result_signature: str) -> bool:
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id)).all()
    for run in runs:
        params = loads_json(run.params_json, {})
        if params.get("result_signature") == result_signature:
            return True
    return False


def experiment_result_signature(metrics: dict[str, Any], *, model_id: str | None = None) -> str:
    cleaned_model_id = model_id.strip().casefold() if isinstance(model_id, str) and model_id.strip() else ""
    if cleaned_model_id:
        primary_metric_name = str(metrics.get("primary_metric_name") or "").strip().casefold()
        primary_metric_value = metrics.get("primary_metric_value")
        if not isinstance(primary_metric_value, int | float) or isinstance(primary_metric_value, bool):
            primary_metric_value = metrics.get(primary_metric_name)
        if isinstance(primary_metric_value, int | float) and not isinstance(primary_metric_value, bool):
            payload = {
                "model_id": cleaned_model_id,
                "primary_metric_name": primary_metric_name,
                "primary_metric_value": round(float(primary_metric_value), 8),
            }
            return "candidate:" + hashlib.sha256(dumps_json(payload).encode("utf-8")).hexdigest()
    numeric_metrics = {
        key: round(float(value), 12)
        for key, value in metrics.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    return "metrics:" + hashlib.sha256(dumps_json(numeric_metrics).encode("utf-8")).hexdigest()


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
) -> None:
    if not source_artifact_id:
        return
    current = latest_research_plan_current_work(db, project_id=project.id)
    if current is None or not current.node_id:
        return
    try:
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=current.node_id,
            artifact_id=source_artifact_id,
            role="experiment_evidence",
            revision_id=current.revision_id,
            metadata={"experiment_run_id": run.id},
        )
    except ValueError:
        return


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
    if experiment_registration_chat_turn_exists(db, project=project, session=session, source_key=key):
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    best_run = sorted(runs, key=lambda run: leaderboard_sort_key_for_metric(run, None))[0]
    best_metrics = loads_json(best_run.metrics_json, {})
    metric_name = str(best_metrics.get("primary_metric_name") or "")
    metric_value = best_metrics.get("primary_metric_value")
    if japanese:
        assistant_message = (
            f"{len(runs)}件のモデル評価をLeaderboardに登録しました。"
            f"この結果セットの先頭候補は {best_run.summary_md or best_run.id} で、"
            f"{metric_name}={metric_value:.4g} です。"
            if isinstance(metric_value, int | float)
            else f"{len(runs)}件のモデル評価をLeaderboardに登録しました。"
        )
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
        action_label = "Open leaderboard"
        action_detail = "Compare the registered model runs as a ranked table."
        next_label = "Leaderboard"
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
        "actions": [
            {
                "type": "open_surface",
                "status": "ready",
                "label": action_label,
                "target_tab": "Leaderboard",
                "target_anchor": "leaderboard",
                "detail": action_detail,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "experiment_results_registered.v1",
            "agent_session_id": session.id,
            "run_ids": [run.id for run in runs],
            "source_artifact_id": source_artifact.id if source_artifact is not None else None,
            "source_request_id": source_request_id,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": "Leaderboard", "target_anchor": "leaderboard", "label": next_label},
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
        },
    )
    return chat_artifact


def experiment_registration_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    source_key: str,
) -> bool:
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(200)
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_experiment_registration"
            and metadata.get("agent_session_id") == session.id
            and metadata.get("source_key") == source_key
        ):
            return True
    return False


def run_spec_source_request_id(run: ExperimentRun) -> str:
    params = loads_json(run.params_json, {})
    value = params.get("source_request_id")
    return str(value) if value else run.id


def latest_project_response_locale(db: Session, project: Project) -> str:
    user = db.get(User, project.created_by) if project.created_by else None
    if user is not None and user.locale:
        return user.locale
    return "en-US"


def write_experiment_result_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def json_safe_object(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
    return value
