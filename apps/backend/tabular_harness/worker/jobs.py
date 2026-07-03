from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.config import get_settings
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    EvaluationSpec,
    Job,
    Project,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.agent_chat import handle_agent_chat_turn
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.autonomy import (
    RUNNER_MODE_CODEX_IF_AVAILABLE,
    AutonomousLoopState,
    active_autonomous_child_job_ids,
    ingest_codex_target_definition_proposal,
    queue_autonomous_session_continuation,
    run_autonomous_loop_tick,
)
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    normalize_model_candidate_name,
    run_baseline,
    run_model_candidate,
)
from tabular_harness.services.evaluation import generate_split_manifest
from tabular_harness.services.jobs import JOB_TYPES, create_job
from tabular_harness.services.planned_agent_execution import run_planned_agent_task_codex_cli
from tabular_harness.services.planned_agent_workspace import load_contract_payload
from tabular_harness.worker.runner import JobHandler, SyncWorker

INITIAL_JOB_TYPES = tuple(sorted(JOB_TYPES))


def stub_job_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    del db
    del store
    return {
        "message": "Queued job processed by SyncWorker stub handler.",
        "job_type": job.job_type,
        "input": loads_json(job.input_json, {}),
        "context": loads_json(job.context_json, {}),
        "policy": loads_json(job.policy_json, {}),
        "attempt_count": job.attempt_count,
    }


def agent_chat_turn_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("agent_chat_turn requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("agent_chat_turn requires a non-empty message")
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    agent_model = payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None
    utility_model = payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None
    result = handle_agent_chat_turn(
        db,
        store=store,
        project=project,
        job=job,
        message=message,
        locale=locale,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    return {
        "schema_version": result.response["schema_version"],
        "agent_chat_turn_artifact_id": result.artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "intent_type": result.response["intent"]["type"],
        "action_count": len(result.response["actions"]),
        "assistant_message": result.response["assistant_message"],
        "response_composer": result.response["response_composer"],
        "worker_events": result.response["worker_events"],
        "token_usage": result.response["token_usage"],
        "agent_task_contract_artifact_id": result.planned_agent_task.artifact.id
        if result.planned_agent_task
        else None,
    }


def run_baseline_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("run_baseline requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    spec_id = payload.get("evaluation_spec_id")
    split_id = payload.get("split_manifest_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    split = db.get(SplitManifest, split_id) if isinstance(split_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    if split is None:
        raise ValueError("SplitManifest not found")
    result = run_baseline(db, store=store, project=project, evaluation_spec=spec, split_manifest=split)
    output = {
        "schema_version": "baseline_training.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "experiment_run_id": result.run.id,
        "model_version_id": result.model_version_id,
        "artifact_ids": result.artifact_ids,
        "metrics": result.metrics,
        "primary_metric_name": result.metrics.get("primary_metric_name"),
        "primary_metric_value": result.metrics.get("primary_metric_value"),
        "worker_events": [
            {
                "worker_id": "adaptive-baseline",
                "display_name": "Training Worker",
                "status": "succeeded",
                "headline": f"Adaptive baseline trained: {result.run.id}",
                "detail": "Registered the baseline run, model package, metrics, and supporting artifacts.",
                "job_id": job.id,
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "training_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load split", "tokens": 80},
                        {"step": "fit baseline", "tokens": 180},
                        {"step": "score", "tokens": 120},
                        {"step": "register artifacts", "tokens": 140},
                    ],
                },
            }
        ],
    }
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="baseline_training_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def build_split_manifest_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    spec_id = payload.get("evaluation_spec_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    split = generate_split_manifest(db, store=store, spec=spec)
    queued_training_ids: list[str] = []
    if job.project_id:
        common_policy = {
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
            "queued_by": "split_manifest_worker",
        }
        baseline_job = create_job(
            db,
            job_type="run_baseline",
            project_id=job.project_id,
            input_payload={"evaluation_spec_id": spec.id, "split_manifest_id": split.id},
            context={
                "human_description": {
                    "source": "split_manifest_worker",
                    "title": "Train the adaptive baseline",
                    "summary": "Train the adaptive baseline after the queued SplitManifest has been materialized.",
                }
            },
            policy=common_policy,
            priority=70,
        )
        candidate_job = create_job(
            db,
            job_type="train_model_candidates",
            project_id=job.project_id,
            input_payload={
                "requested_models": ["xgboost", "logistic_regression", "lightgbm"],
                "normalized_models": ["xgboost", "logistic_regression", "lightgbm"],
                "unsupported_models": [],
                "evaluation_spec_id": spec.id,
                "split_manifest_id": split.id,
            },
            context={
                "human_description": {
                    "source": "split_manifest_worker",
                    "title": "Train candidate models",
                    "summary": "Train XGBoost, LogisticRegression, and LightGBM after the queued SplitManifest has been materialized.",
                }
            },
            policy=common_policy,
            priority=65,
        )
        queued_training_ids = [baseline_job.id, candidate_job.id]
    output = {
        "schema_version": "split_manifest_generation.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "artifact_ids": [split.artifact_id],
        "created_job_ids": queued_training_ids,
        "worker_events": [
            {
                "worker_id": "split-manifest-builder",
                "display_name": "Evaluation Worker",
                "status": "succeeded",
                "headline": "SplitManifest generated",
                "detail": "Created the stable train/validation split for downstream model runs.",
                "job_id": job.id,
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-spec",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "split_generation_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load spec", "tokens": 40},
                        {"step": "split rows", "tokens": 140},
                        {"step": "write manifest", "tokens": 80},
                    ],
                },
            }
        ],
    }
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project_id=job.project_id,
        job=job,
        reason="split_manifest_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def train_model_candidates_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("train_model_candidates requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    spec_id = payload.get("evaluation_spec_id")
    split_id = payload.get("split_manifest_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    split = db.get(SplitManifest, split_id) if isinstance(split_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    if split is None:
        raise ValueError("SplitManifest not found")
    raw_requested_models = payload.get("requested_models") or payload.get("normalized_models") or []
    if not isinstance(raw_requested_models, list):
        raise ValueError("requested model list is invalid")
    requested_models = payload.get("normalized_models") or raw_requested_models
    if not isinstance(requested_models, list):
        raise ValueError("normalized model list is invalid")
    unsupported_models = payload.get("unsupported_models") or []
    if not isinstance(unsupported_models, list):
        unsupported_models = []
    normalized_models: list[str] = []
    failures: list[dict[str, Any]] = [
        {
            "model": str(model),
            "status": "unsupported",
            "reason": "Model candidate is not recognized by Tablex yet.",
        }
        for model in unsupported_models
    ]
    for model in requested_models:
        normalized = normalize_model_candidate_name(str(model))
        if normalized is None:
            failures.append(
                {
                    "model": str(model),
                    "status": "unsupported",
                    "reason": "Model candidate is not recognized by Tablex yet.",
                }
            )
            continue
        if normalized not in normalized_models:
            normalized_models.append(normalized)
    successes: list[dict[str, Any]] = []
    for model in normalized_models:
        try:
            result = run_model_candidate(
                db,
                store=store,
                project=project,
                evaluation_spec=spec,
                split_manifest=split,
                model_candidate=model,
            )
        except ModelDependencyRequiredError as exc:
            failures.append(
                {
                    "model": model,
                    "status": "dependency_required",
                    "package": exc.package_name,
                    "install_spec": exc.install_spec,
                    "reason": str(exc),
                    "approval_required": True,
                }
            )
            continue
        except ValueError as exc:
            failures.append({"model": model, "status": "failed", "reason": str(exc)})
            continue
        successes.append(
            {
                "model": model,
                "status": "succeeded",
                "experiment_run_id": result.run.id,
                "model_version_id": result.model_version_id,
                "artifact_ids": result.artifact_ids,
                "metrics": result.metrics,
                "primary_metric_name": result.metrics.get("primary_metric_name"),
                "primary_metric_value": result.metrics.get("primary_metric_value"),
                "roc_auc": result.metrics.get("roc_auc"),
                "pr_auc": result.metrics.get("pr_auc"),
            }
        )
    status = "succeeded" if successes else "failed"
    output: dict[str, Any] = {
        "schema_version": "model_candidate_training.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "requested_models": raw_requested_models,
        "normalized_models": normalized_models,
        "trained_models": [item["model"] for item in successes],
        "failed_models": failures,
        "success_count": len(successes),
        "failure_count": len(failures),
        "experiment_run_ids": [item["experiment_run_id"] for item in successes],
        "model_version_ids": [item["model_version_id"] for item in successes if item.get("model_version_id")],
        "results": successes,
        "worker_events": [
            {
                "worker_id": "training-candidates",
                "display_name": "Training Worker",
                "status": status,
                "headline": (
                    f"Trained {len(successes)} model candidate(s)"
                    if successes
                    else "Model candidate training needs attention"
                ),
                "detail": "; ".join(
                    [
                        *(f"{item['model']} -> {item['experiment_run_id']}" for item in successes),
                        *(f"{item['model']}: {item['status']}" for item in failures),
                    ]
                ),
                "job_id": job.id,
                "target_tab": "Leaderboard" if successes else "Experiments",
                "target_anchor": "result-readout" if successes else None,
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "training_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load split", "tokens": 80},
                        {"step": "fit models", "tokens": 120 * max(len(normalized_models), 1)},
                        {"step": "score", "tokens": 90 * max(len(successes), 1)},
                        {"step": "register artifacts", "tokens": 110 * max(len(successes), 1)},
                    ],
                },
            }
        ],
    }
    if not successes:
        output["job_status"] = "failed"
        output["error_message"] = "; ".join(
            f"{item['model']}: {item['status']}" for item in failures
        ) or "No model candidates completed training"
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="model_candidate_training_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def run_planned_agent_task_codex_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    artifact_id = payload.get("agent_task_contract_artifact_id")
    if not isinstance(artifact_id, str):
        raise ValueError("run_planned_agent_task_codex requires agent_task_contract_artifact_id")
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise ValueError("AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise ValueError("Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise ValueError("AgentTaskContract artifact is not project-scoped")
    project = db.get(Project, contract_artifact.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = run_planned_agent_task_codex_cli(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    contract_payload = load_contract_payload(contract_artifact)
    target_state = AutonomousLoopState(project=project, job=job)
    if contract_payload.get("task_type") == "target_definition_review":
        ingest_codex_target_definition_proposal(
            db,
            project=project,
            state=target_state,
            agent_result=result.agent_result,
            source_artifact_id=result.artifact_ids[0] if result.artifact_ids else None,
        )
    status = "failed" if result.agent_result.status == "failed" else "succeeded"
    output: dict[str, Any] = {
        "schema_version": "planned_agent_task_codex_execution.v1",
        "agent_task_contract_artifact_id": contract_artifact.id,
        "task_id": result.agent_result.task_id,
        "agent_status": result.agent_result.status,
        "agent_final_message": result.agent_result.final_message,
        "agent_failure_reason": result.agent_result.failure_reason,
        "agent_give_up_reason": result.agent_result.give_up_reason,
        "required_next_inputs": result.agent_result.required_next_inputs,
        "codex_cli": result.agent_result.outputs.get("codex_cli") if isinstance(result.agent_result.outputs, dict) else None,
        "agent_workspace_manifest_artifact_id": result.workspace_artifact_id,
        "agent_task_readiness_review_artifact_id": result.readiness_artifact_id,
        "readiness_status": result.readiness_status,
        "artifact_ids": result.artifact_ids,
        "ingested_artifact_ids": result.ingested_artifact_ids,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "experiment_run_id": result.experiment_ingestion.experiment_run_id,
        "agent_metrics_artifact_id": result.experiment_ingestion.metrics_artifact_id,
        "agent_feature_recipe_artifact_id": result.experiment_ingestion.feature_recipe_artifact_id,
        "approach_decision_trace_artifact_id": result.approach_decision_trace_artifact_id,
        "visualization_ids": result.experiment_ingestion.visualization_ids,
        "autonomous_state_steps": [step.to_dict() for step in target_state.steps],
        "project_target_column": project.target_column,
        "worker_events": [
            {
                "worker_id": "codex-runner",
                "display_name": "Codex Runner",
                "status": status,
                "headline": (
                    "Codex completed the planned agent task"
                    if status == "succeeded"
                    else "Codex runner needs attention"
                ),
                "detail": result.agent_result.final_message,
                "job_id": job.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "codex_runner_result",
                    "is_estimate": True,
                    "series": [
                        {"step": "load workspace", "tokens": 160},
                        {"step": "reason", "tokens": 900},
                        {"step": "write artifacts", "tokens": 240},
                    ],
                },
            }
        ],
    }
    if status == "failed":
        output["job_status"] = "failed"
        output["error_message"] = result.agent_result.failure_reason or result.agent_result.final_message
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="codex_session_returned",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def continue_autonomous_session_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("continue_autonomous_session requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    runner_mode = str(payload.get("runner_mode") or RUNNER_MODE_CODEX_IF_AVAILABLE)
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    if project.current_phase != "AUTONOMOUS_LOOP" or project.autonomy_mode != "full_auto":
        return {
            "schema_version": "autonomous_session_continuation.v1",
            "status": "stopped",
            "reason": "Full Auto is no longer active for this project.",
            "worker_events": [autonomous_session_worker_event(job, project, status="succeeded", headline="Autonomous session is off")],
        }
    active_child_ids = active_autonomous_child_job_ids(db, project.id, exclude_job_id=job.id)
    if active_child_ids:
        next_job = queue_autonomous_session_continuation(
            db,
            project=project,
            reason="waiting_for_child_workers",
            parent_job_id=job.id,
            exclude_job_id=job.id,
            runner_mode=runner_mode,
            locale=locale,
            run_after_seconds=15,
        )
        return {
            "schema_version": "autonomous_session_continuation.v1",
            "status": "waiting_for_child_workers",
            "active_child_job_ids": active_child_ids,
            "session_continuation_job_id": next_job.id if next_job is not None else None,
            "worker_events": [
                autonomous_session_worker_event(
                    job,
                    project,
                    status="succeeded",
                    headline="Main session is waiting for child workers",
                    detail=f"Waiting for {len(active_child_ids)} worker(s) before resuming Codex context.",
                )
            ],
        }
    output = run_autonomous_loop_tick(
        db,
        store=store,
        project=project,
        job=job,
        runner_mode=runner_mode,
        autonomy_mode="full_auto",
        locale=locale,
        agent_model=payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None,
        utility_model=payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None,
    )
    created_job_ids = output.get("created_job_ids") if isinstance(output.get("created_job_ids"), list) else []
    next_delay_seconds = 15 if created_job_ids else 60
    next_job = queue_autonomous_session_continuation(
        db,
        project=project,
        reason="continuation_tick_completed",
        parent_job_id=job.id,
        exclude_job_id=job.id,
        runner_mode=runner_mode,
        locale=locale,
        run_after_seconds=next_delay_seconds,
    )
    if next_job is not None:
        output["session_continuation_job_id"] = next_job.id
    output["schema_version"] = "autonomous_session_continuation.v1"
    return output
def maybe_queue_autonomous_session_continuation(
    db: Session,
    *,
    job: Job,
    reason: str,
    project: Project | None = None,
    project_id: str | None = None,
) -> Job | None:
    resolved_project = project
    if resolved_project is None and project_id is not None:
        resolved_project = db.get(Project, project_id)
    if resolved_project is None or resolved_project.current_phase != "AUTONOMOUS_LOOP":
        return None
    return queue_autonomous_session_continuation(
        db,
        project=resolved_project,
        reason=reason,
        parent_job_id=job.id,
        runner_mode=RUNNER_MODE_CODEX_IF_AVAILABLE,
        run_after_seconds=10,
    )


def autonomous_session_worker_event(
    job: Job,
    project: Project,
    *,
    status: str,
    headline: str,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "worker_id": "autonomous-session",
        "display_name": "Autonomous Session",
        "status": status,
        "headline": headline,
        "detail": detail or "The harness is keeping the main Full Auto thread warm and ready to resume.",
        "job_id": job.id,
        "project_id": project.id,
        "target_tab": "Home",
        "target_anchor": "agent-workspace",
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "autonomous_session_heartbeat",
            "is_estimate": True,
            "series": [
                {"step": "observe", "tokens": 40},
                {"step": "resume", "tokens": 80},
                {"step": "handoff", "tokens": 120},
            ],
        },
    }


def default_handlers() -> dict[str, JobHandler]:
    handlers = {job_type: stub_job_handler for job_type in JOB_TYPES}
    handlers.update(concrete_handlers())
    return handlers


def concrete_handlers() -> dict[str, JobHandler]:
    handlers: dict[str, JobHandler] = {}
    handlers["run_baseline"] = run_baseline_handler
    handlers["build_split_manifest"] = build_split_manifest_handler
    handlers["train_model_candidates"] = train_model_candidates_handler
    handlers["run_planned_agent_task_codex"] = run_planned_agent_task_codex_handler
    handlers["continue_autonomous_session"] = continue_autonomous_session_handler
    handlers["agent_chat_turn"] = agent_chat_turn_handler
    return handlers


def create_default_worker(
    worker_id: str = "local-worker", store: LocalArtifactStore | None = None, include_stub_handlers: bool = False
) -> SyncWorker:
    artifact_store = store or LocalArtifactStore(get_settings().artifact_root)
    handlers = default_handlers() if include_stub_handlers else concrete_handlers()
    return SyncWorker(handlers=handlers, store=artifact_store, worker_id=worker_id)
