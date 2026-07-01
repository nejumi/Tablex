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
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    normalize_model_candidate_name,
    run_baseline,
    run_model_candidate,
)
from tabular_harness.services.evaluation import generate_split_manifest
from tabular_harness.services.jobs import JOB_TYPES, create_job
from tabular_harness.services.planned_agent_execution import run_planned_agent_task_codex_cli
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
    return {
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
    return {
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
    status = "failed" if result.agent_result.status == "failed" else "succeeded"
    output: dict[str, Any] = {
        "schema_version": "planned_agent_task_codex_execution.v1",
        "agent_task_contract_artifact_id": contract_artifact.id,
        "task_id": result.agent_result.task_id,
        "agent_status": result.agent_result.status,
        "agent_final_message": result.agent_result.final_message,
        "agent_failure_reason": result.agent_result.failure_reason,
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
    return output


def default_handlers() -> dict[str, JobHandler]:
    handlers = {job_type: stub_job_handler for job_type in JOB_TYPES}
    handlers["run_baseline"] = run_baseline_handler
    handlers["build_split_manifest"] = build_split_manifest_handler
    handlers["train_model_candidates"] = train_model_candidates_handler
    handlers["run_planned_agent_task_codex"] = run_planned_agent_task_codex_handler
    return handlers


def create_default_worker(
    worker_id: str = "local-worker", store: LocalArtifactStore | None = None
) -> SyncWorker:
    artifact_store = store or LocalArtifactStore(get_settings().artifact_root)
    return SyncWorker(handlers=default_handlers(), store=artifact_store, worker_id=worker_id)
