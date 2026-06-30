from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, ExperimentRun, Project
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore

BUILTIN_METRIC_OPTIONS = [
    {
        "name": "roc_auc",
        "label": "ROC-AUC",
        "direction": "higher_is_better",
        "task_types": ["binary_classification"],
        "aliases": ["roc auc", "roc-auc", "roc_auc", "auc"],
    },
    {
        "name": "pr_auc",
        "label": "PR-AUC",
        "direction": "higher_is_better",
        "task_types": ["binary_classification"],
        "aliases": ["pr auc", "pr-auc", "pr_auc", "average precision"],
    },
    {
        "name": "accuracy",
        "label": "Accuracy",
        "direction": "higher_is_better",
        "task_types": ["classification"],
        "aliases": ["accuracy"],
    },
    {
        "name": "macro_f1",
        "label": "Macro F1",
        "direction": "higher_is_better",
        "task_types": ["classification"],
        "aliases": ["macro f1", "macro-f1", "macro_f1"],
    },
    {
        "name": "f1",
        "label": "F1",
        "direction": "higher_is_better",
        "task_types": ["binary_classification"],
        "aliases": ["f1", "f1 score"],
    },
    {
        "name": "log_loss",
        "label": "Log loss",
        "direction": "lower_is_better",
        "task_types": ["classification"],
        "aliases": ["log loss", "log-loss", "log_loss"],
    },
    {
        "name": "rmse",
        "label": "RMSE",
        "direction": "lower_is_better",
        "task_types": ["regression"],
        "aliases": ["rmse", "root mean squared error"],
    },
    {
        "name": "mae",
        "label": "MAE",
        "direction": "lower_is_better",
        "task_types": ["regression"],
        "aliases": ["mae", "mean absolute error"],
    },
    {
        "name": "r2",
        "label": "R2",
        "direction": "higher_is_better",
        "task_types": ["regression"],
        "aliases": ["r2", "r squared", "r-squared"],
    },
]

LOSS_METRICS = {
    option["name"]
    for option in BUILTIN_METRIC_OPTIONS
    if option["direction"] == "lower_is_better"
} | {"mape", "mean_absolute_error"}


def normalize_metric_name(metric: str) -> str:
    normalized = metric.strip().casefold().replace("ー", "-")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    aliases = {
        re.sub(r"[^a-z0-9]+", "_", alias.casefold()).strip("_"): str(option["name"])
        for option in BUILTIN_METRIC_OPTIONS
        for alias in [str(option["name"]), *[str(value) for value in option["aliases"]]]
    }
    return aliases.get(normalized, normalized)


def record_metric_preference(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    metric: str,
    source: str,
) -> Artifact:
    metric = normalize_metric_name(metric)
    payload = {
        "schema_version": "evaluation_metric_preference.v1",
        "project_id": project.id,
        "requested_metric": metric,
        "source": source,
        "applies_to": ["leaderboard_view", "future_evaluation_design"],
        "approved_evaluation_spec_modified": False,
        "note": (
            "This preference changes the in-product leaderboard view when existing runs expose the metric. "
            "Approved EvaluationSpecs still require explicit review before destructive replacement."
        ),
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="evaluation_metric_preference",
        name=f"evaluation_metric_preference_{metric}",
        filename="evaluation_metric_preference.json",
        payload=payload,
        metadata={"project_id": project.id, "requested_metric": metric, "source": source},
    )


def latest_metric_preference(db: Session, project_id: str) -> str | None:
    artifact = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "evaluation_metric_preference")
        .order_by(Artifact.created_at.desc())
    )
    if artifact is None:
        return None
    metric = loads_json(artifact.metadata_json, {}).get("requested_metric")
    return normalize_metric_name(str(metric)) if isinstance(metric, str) and metric else None


def metric_value(metrics: dict[str, Any], metric: str | None) -> float | None:
    if metric:
        value = metrics.get(metric)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        if metrics.get("primary_metric_name") == metric:
            primary_value = metrics.get("primary_metric_value")
            if isinstance(primary_value, int | float) and not isinstance(primary_value, bool):
                return float(primary_value)
        return None
    primary_value = metrics.get("primary_metric_value")
    if isinstance(primary_value, int | float) and not isinstance(primary_value, bool):
        return float(primary_value)
    primary_metric = metrics.get("primary_metric_name")
    if isinstance(primary_metric, str):
        value = metrics.get(primary_metric)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def metric_name(metrics: dict[str, Any], metric: str | None) -> str | None:
    if metric:
        return metric
    return str(metrics["primary_metric_name"]) if isinstance(metrics.get("primary_metric_name"), str) else None


def leaderboard_sort_key_for_metric(run: ExperimentRun, metric: str | None) -> tuple[int, float]:
    metrics = loads_json(run.metrics_json, {})
    name = metric_name(metrics, metric)
    value = metric_value(metrics, metric)
    if value is None:
        return (1, 0.0)
    if name in LOSS_METRICS:
        return (0, value)
    return (0, -value)
