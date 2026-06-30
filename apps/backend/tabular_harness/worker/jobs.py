from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.config import get_settings
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import EvaluationSpec, Job, Project, SplitManifest, utc_now
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    normalize_model_candidate_name,
    run_model_candidate,
)
from tabular_harness.services.jobs import JOB_TYPES
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


def default_handlers() -> dict[str, JobHandler]:
    handlers = {job_type: stub_job_handler for job_type in JOB_TYPES}
    handlers["train_model_candidates"] = train_model_candidates_handler
    return handlers


def create_default_worker(
    worker_id: str = "local-worker", store: LocalArtifactStore | None = None
) -> SyncWorker:
    artifact_store = store or LocalArtifactStore(get_settings().artifact_root)
    return SyncWorker(handlers=default_handlers(), store=artifact_store, worker_id=worker_id)
