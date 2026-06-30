from __future__ import annotations

import csv
import io
import math
import re
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
from scipy import sparse
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from xgboost import XGBClassifier, XGBRegressor

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    ModelVersion,
    Project,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.profiler import read_sql

LOSS_METRICS = {"rmse", "mae", "log_loss"}
ROW_INDEX_COLUMN = "__harness_row_index"
TARGET_VALUE_COLUMN = "__harness_target"
SPLIT_VALUE_COLUMN = "__harness_split"
SYSTEM_COLUMNS = {ROW_INDEX_COLUMN, TARGET_VALUE_COLUMN, SPLIT_VALUE_COLUMN}
TEXT_MAX_FEATURES_PER_COLUMN = 128
MAX_LAG_ROLLING_SOURCE_COLUMNS = 8
TEXT_TOKEN_PATTERN = re.compile(r"\w+")
MODEL_CANDIDATE_ALIASES = {
    "xgboost": "xgboost",
    "xgb": "xgboost",
    "xgboost_classifier": "xgboost",
    "xgboost_regressor": "xgboost",
    "lightgbm": "lightgbm",
    "lgbm": "lightgbm",
    "lightgbm_classifier": "lightgbm",
    "lightgbm_regressor": "lightgbm",
    "logisticregression": "logistic_regression",
    "logistic_regression": "logistic_regression",
    "logistic regression": "logistic_regression",
    "logreg": "logistic_regression",
    "ridge": "ridge_regression",
    "ridge_regression": "ridge_regression",
}


class ModelDependencyRequiredError(ValueError):
    def __init__(self, *, model_candidate: str, package_name: str, install_spec: str) -> None:
        super().__init__(
            f"{model_candidate} requires dependency {install_spec}. Create an approved dependency change before running it."
        )
        self.model_candidate = model_candidate
        self.package_name = package_name
        self.install_spec = install_spec


@dataclass(frozen=True)
class BaselineResult:
    run: ExperimentRun
    artifact_ids: list[str]
    metrics: dict[str, Any]
    model_version_id: str | None = None


@dataclass(frozen=True)
class BaselineStrategyPlanResult:
    plan: dict[str, Any]
    artifact: Artifact


@dataclass(frozen=True)
class ModelPackagePayload:
    package: dict[str, Any]
    baseline_type: str
    model_family: str
    task_type: str


def run_baseline(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
) -> BaselineResult:
    return _run_model_candidate(
        db,
        store=store,
        project=project,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        model_candidate=None,
        runner_type="local_baseline",
    )


def run_model_candidate(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
    model_candidate: str,
) -> BaselineResult:
    normalized = normalize_model_candidate_name(model_candidate)
    if normalized is None:
        raise ValueError(f"Unsupported model candidate: {model_candidate}")
    return _run_model_candidate(
        db,
        store=store,
        project=project,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        model_candidate=normalized,
        runner_type="local_training",
    )


def _run_model_candidate(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
    model_candidate: str | None,
    runner_type: str,
) -> BaselineResult:
    if not project.target_column:
        raise ValueError("Project target_column is required before running baseline")
    if evaluation_spec.status != "approved":
        raise ValueError("EvaluationSpec must be approved before baseline execution")
    if split_manifest.evaluation_spec_id != evaluation_spec.id:
        raise ValueError("SplitManifest does not belong to the selected EvaluationSpec")

    dataset = db.get(DatasetSnapshot, evaluation_spec.dataset_snapshot_id)
    if dataset is None:
        raise ValueError("DatasetSnapshot not found")
    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    split_artifact = db.get(Artifact, split_manifest.artifact_id)
    if dataset_artifact is None or split_artifact is None:
        raise ValueError("Required dataset or split artifact not found")

    excluded_columns = parse_string_list(loads_json(evaluation_spec.excluded_columns_json, []))
    rows = load_split_rows(
        dataset_path=artifact_primary_path(dataset_artifact),
        split_path=artifact_primary_path(split_artifact),
        target_column=project.target_column,
    )
    task_type = resolve_task_type(project.task_type, rows)
    baseline_plan = build_baseline_plan(
        rows,
        task_type=task_type,
        target_column=project.target_column,
        primary_metric=evaluation_spec.primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=evaluation_spec,
    )
    if model_candidate is not None:
        apply_model_candidate_to_baseline_plan(baseline_plan, model_candidate, task_type)
    baseline_strategy_plan = build_baseline_strategy_plan(
        db,
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        baseline_plan=baseline_plan,
    )
    if task_type == "regression":
        if model_candidate is None:
            metrics, predictions = run_regression_baseline(
                rows,
                evaluation_spec.primary_metric,
                target_column=project.target_column,
                excluded_columns=excluded_columns,
                baseline_plan=baseline_plan,
            )
        else:
            metrics, predictions = run_regression_model_candidate(
                rows,
                evaluation_spec.primary_metric,
                model_candidate=model_candidate,
                target_column=project.target_column,
                excluded_columns=excluded_columns,
                baseline_plan=baseline_plan,
            )
        baseline_name = str(metrics["baseline_type"])
    else:
        if model_candidate is None:
            metrics, predictions = run_classification_baseline(
                rows,
                evaluation_spec.primary_metric,
                target_column=project.target_column,
                excluded_columns=excluded_columns,
                baseline_plan=baseline_plan,
            )
        else:
            metrics, predictions = run_classification_model_candidate(
                rows,
                evaluation_spec.primary_metric,
                model_candidate=model_candidate,
                target_column=project.target_column,
                excluded_columns=excluded_columns,
                baseline_plan=baseline_plan,
            )
        baseline_name = str(metrics["baseline_type"])
    model_package_payload = metrics.pop("_model_package_payload", None)
    feature_recipe = metrics.pop("feature_recipe", build_fallback_feature_recipe(baseline_name))
    baseline_plan["selected_baseline_type"] = baseline_name
    baseline_plan["execution_status"] = "succeeded"
    baseline_strategy_plan["selected_execution"] = {
        "status": "executed",
        "run_id": None,
        "baseline_type": baseline_name,
        "model_family": metrics.get("model_family", "fallback"),
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
        "reason": "Selected by local strong baseline runner after respecting EvaluationSpec and SplitManifest.",
    }

    report = render_baseline_report(
        project=project,
        spec=evaluation_spec,
        split=split_manifest,
        baseline_name=baseline_name,
        metrics=metrics,
        predictions=predictions,
        baseline_plan=baseline_plan,
        feature_recipe=feature_recipe,
        baseline_strategy_plan=baseline_strategy_plan,
    )
    run = ExperimentRun(
        id=new_id("run"),
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        evaluation_spec_id=evaluation_spec.id,
        split_manifest_id=split_manifest.id,
        runner_type=runner_type,
        status="succeeded",
        started_at=utc_now(),
        ended_at=utc_now(),
        params_json=dumps_json(
            {
                "baseline": baseline_name,
                "model_candidate": model_candidate,
                "target_column": project.target_column,
                "excluded_columns": excluded_columns,
            }
        ),
        metrics_json=dumps_json(metrics),
        summary_md=report,
    )
    db.add(run)
    db.flush()
    baseline_strategy_plan["selected_execution"]["run_id"] = run.id

    model_artifact: Artifact | None = None
    model_version: ModelVersion | None = None
    if isinstance(model_package_payload, ModelPackagePayload):
        model_package_payload.package["baseline_plan"] = baseline_plan
        model_package_payload.package["baseline_strategy_plan"] = baseline_strategy_plan
        model_package_payload.package["feature_recipe"] = feature_recipe
        model_package_payload.package["metrics"] = metrics
        model_package_payload.package["run_metadata"] = {
            "run_id": run.id,
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "evaluation_spec_id": evaluation_spec.id,
            "split_manifest_id": split_manifest.id,
            "target_column": project.target_column,
        }
        model_artifact = store_model_package_artifact(
            db,
            store,
            project_id=project.id,
            run_id=run.id,
            package=model_package_payload.package,
            metadata={
                "run_id": run.id,
                "evaluation_spec_id": evaluation_spec.id,
                "split_manifest_id": split_manifest.id,
                "baseline_type": baseline_name,
                "model_family": model_package_payload.model_family,
            },
        )
        model_version = create_model_version(
            db,
            project=project,
            run=run,
            dataset=dataset,
            evaluation_spec=evaluation_spec,
            split_manifest=split_manifest,
            model_artifact=model_artifact,
            baseline_type=baseline_name,
            model_family=model_package_payload.model_family,
            task_type=model_package_payload.task_type,
            metrics=metrics,
            params={
                "baseline_plan_artifact": "created_after_model_version",
                "feature_recipe_artifact": "created_after_model_version",
            },
        )
        run.model_version_id = model_version.id
        db.flush()

    plan_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="baseline_plan",
        name=f"baseline_plan_{run.id}",
        filename="baseline_plan.json",
        payload=baseline_plan,
        metadata={"run_id": run.id, "evaluation_spec_id": evaluation_spec.id},
    )
    strategy_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="baseline_strategy_plan",
        name=f"baseline_strategy_plan_{run.id}",
        filename="baseline_strategy_plan.json",
        payload=baseline_strategy_plan,
        metadata={
            "run_id": run.id,
            "dataset_snapshot_id": dataset.id,
            "evaluation_spec_id": evaluation_spec.id,
            "split_manifest_id": split_manifest.id,
            "selected_baseline_type": baseline_name,
            "strategy_count": len(baseline_strategy_plan.get("candidate_strategies", [])),
            "strategy_mode": baseline_strategy_plan.get("context", {}).get("strategy_mode"),
            "matched_asset_count": baseline_strategy_plan.get("context", {})
            .get("library_context", {})
            .get("matched_asset_count"),
            "agent_task_count": len(baseline_strategy_plan.get("next_agent_tasks", [])),
        },
    )
    recipe_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="feature_recipe",
        name=f"feature_recipe_{run.id}",
        filename="feature_recipe.json",
        payload=feature_recipe,
        metadata={"run_id": run.id, "evaluation_spec_id": evaluation_spec.id},
    )
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="baseline_report",
        name=f"baseline_report_{run.id}",
        filename="baseline_report.md",
        text=report,
        metadata={"run_id": run.id, "evaluation_spec_id": evaluation_spec.id},
    )
    metrics_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="baseline_metrics",
        name=f"baseline_metrics_{run.id}",
        filename="baseline_metrics.json",
        payload=metrics,
        metadata={"run_id": run.id, "evaluation_spec_id": evaluation_spec.id},
    )
    predictions_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="prediction_output",
        name=f"prediction_valid_{run.id}",
        filename="prediction_valid.csv",
        text=predictions_to_csv(predictions),
        metadata={"run_id": run.id, "split_manifest_id": split_manifest.id},
    )
    if model_version is not None:
        model_version.params_json = dumps_json(
            {
                "baseline_plan_artifact_id": plan_artifact.id,
                "baseline_strategy_plan_artifact_id": strategy_artifact.id,
                "feature_recipe_artifact_id": recipe_artifact.id,
                "model_package_artifact_id": model_artifact.id if model_artifact else None,
            }
        )
        db.flush()

    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="trained_on",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="evaluation_spec",
        from_asset_id=evaluation_spec.id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="evaluates_with",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="split_manifest",
        from_asset_id=split_manifest.id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="uses",
    )
    for artifact in (
        strategy_artifact,
        plan_artifact,
        recipe_artifact,
        report_artifact,
        metrics_artifact,
        predictions_artifact,
    ):
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    if model_version is not None:
        for artifact in (plan_artifact, recipe_artifact):
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact.id,
                to_asset_type="model_version",
                to_asset_id=model_version.id,
                relation_type="documents",
            )
    if model_artifact is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=model_artifact.id,
            relation_type="produces",
        )
    if model_version is not None and model_artifact is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="model_version",
            to_asset_id=model_version.id,
            relation_type="creates",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=model_artifact.id,
            to_asset_type="model_version",
            to_asset_id=model_version.id,
            relation_type="packages",
        )
    return BaselineResult(
        run=run,
        artifact_ids=[
            *([model_artifact.id] if model_artifact is not None else []),
            strategy_artifact.id,
            plan_artifact.id,
            recipe_artifact.id,
            report_artifact.id,
            metrics_artifact.id,
            predictions_artifact.id,
        ],
        metrics=metrics,
        model_version_id=model_version.id if model_version is not None else None,
    )


def load_split_rows(dataset_path: Path, split_path: Path, target_column: str) -> list[dict[str, Any]]:
    con = duckdb.connect(database=":memory:")
    source_columns = [
        str(description[0])
        for description in con.execute(f"SELECT * FROM {read_sql(dataset_path)} LIMIT 0").description
        if str(description[0]) not in SYSTEM_COLUMNS
    ]
    if target_column not in source_columns:
        raise ValueError(f"Target column {target_column!r} was not found in dataset")

    select_expressions = [
        f"data.{quote_ident(ROW_INDEX_COLUMN)} AS {quote_ident(ROW_INDEX_COLUMN)}",
        *[
            f"data.{quote_ident(column)} AS {quote_ident(column)}"
            for column in source_columns
        ],
        f"data.{quote_ident(target_column)} AS {quote_ident(TARGET_VALUE_COLUMN)}",
        f"split.split AS {quote_ident(SPLIT_VALUE_COLUMN)}",
    ]
    query = f"""
    SELECT
      {", ".join(select_expressions)}
    FROM (
      SELECT row_number() OVER () - 1 AS {quote_ident(ROW_INDEX_COLUMN)}, *
      FROM {read_sql(dataset_path)}
    ) AS data
    JOIN read_parquet({sql_literal(str(split_path))}) AS split
      ON data.{quote_ident(ROW_INDEX_COLUMN)} = split.row_index
    ORDER BY data.{quote_ident(ROW_INDEX_COLUMN)}
    """
    cursor = con.execute(query)
    column_names = [description[0] for description in cursor.description]
    return [
        {column_names[index]: value for index, value in enumerate(row)}
        for row in cursor.fetchall()
    ]


def resolve_task_type(task_type: str | None, rows: list[dict[str, Any]]) -> str:
    if task_type in {"regression", "binary_classification", "multiclass_classification"}:
        return task_type
    train_targets = [
        row[TARGET_VALUE_COLUMN]
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    unique = {str(value) for value in train_targets}
    if 0 < len(unique) <= 2:
        return "binary_classification"
    if 2 < len(unique) <= 20:
        return "multiclass_classification"
    return "regression"


def normalize_model_candidate_name(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")
    return MODEL_CANDIDATE_ALIASES.get(normalized) or MODEL_CANDIDATE_ALIASES.get(
        normalized.replace("_", " ")
    )


def apply_model_candidate_to_baseline_plan(
    baseline_plan: dict[str, Any], model_candidate: str, task_type: str
) -> None:
    baseline_plan["requested_model_candidate"] = model_candidate
    baseline_plan["candidate_model"] = baseline_type_for_candidate(model_candidate, task_type)
    baseline_plan["model_family"] = model_family_for_candidate(model_candidate)
    baseline_plan["selection_policy"] = "explicit_user_requested_model_candidate"


def baseline_type_for_candidate(model_candidate: str, task_type: str) -> str:
    if model_candidate == "xgboost":
        return "xgboost_regressor" if task_type == "regression" else "xgboost_classifier"
    if model_candidate == "lightgbm":
        return "lightgbm_regressor" if task_type == "regression" else "lightgbm_classifier"
    if model_candidate == "logistic_regression":
        return "logistic_regression"
    if model_candidate == "ridge_regression":
        return "ridge_regression"
    return model_candidate


def model_family_for_candidate(model_candidate: str) -> str:
    return {
        "xgboost": "xgboost",
        "lightgbm": "lightgbm",
        "logistic_regression": "linear",
        "ridge_regression": "linear",
    }.get(model_candidate, model_candidate)


def run_classification_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    target_column: str,
    excluded_columns: list[str],
    baseline_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = baseline_plan or build_baseline_plan(
        rows,
        task_type="binary_classification",
        target_column=target_column,
        primary_metric=primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=None,
    )
    try:
        return run_xgboost_classification_baseline(rows, primary_metric, baseline_plan=plan)
    except Exception as xgb_exc:
        plan.setdefault("fallback_events", []).append(
            {"from": "xgboost_classifier", "reason": str(xgb_exc)}
        )
    try:
        return run_logistic_regression_baseline(
            rows,
            primary_metric,
            target_column=target_column,
            excluded_columns=excluded_columns,
            baseline_plan=plan,
        )
    except Exception as linear_exc:
        metrics, predictions = run_dummy_classification_baseline(rows, primary_metric)
        metrics["model_baseline_attempted"] = True
        metrics["model_baseline_error"] = str(linear_exc)
        metrics["fallback_reason"] = "xgboost_and_logistic_regression_failed"
        metrics["feature_recipe"] = build_fallback_feature_recipe("majority_classifier")
        return metrics, predictions


def run_classification_model_candidate(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    model_candidate: str,
    target_column: str,
    excluded_columns: list[str],
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if model_candidate == "xgboost":
        return run_xgboost_classification_baseline(rows, primary_metric, baseline_plan=baseline_plan)
    if model_candidate == "lightgbm":
        return run_lightgbm_classification_baseline(rows, primary_metric, baseline_plan=baseline_plan)
    if model_candidate == "logistic_regression":
        return run_logistic_regression_baseline(
            rows,
            primary_metric,
            target_column=target_column,
            excluded_columns=excluded_columns,
            baseline_plan=baseline_plan,
        )
    raise ValueError(f"{model_candidate} is not supported for classification training")


def run_xgboost_classification_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    feature_rows = augment_rows_for_baseline_plan(rows, baseline_plan)
    train_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")

    y_train_raw = [str(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [str(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    label_encoder = LabelEncoder()
    y_train = label_encoder.fit_transform(y_train_raw)
    classes = [str(label) for label in label_encoder.classes_]
    if len(classes) < 2:
        raise ValueError("XGBoost classification requires at least two train classes")

    feature_builder = StrongFeatureBuilder(baseline_plan)
    x_train = feature_builder.fit_transform(train_rows)
    x_valid = feature_builder.transform(valid_rows)
    model_params: dict[str, Any] = {
        "n_estimators": 80,
        "max_depth": 3,
        "learning_rate": 0.08,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": 42,
        "n_jobs": 1,
        "tree_method": "hist",
        "eval_metric": "logloss",
    }
    if len(classes) == 2:
        model_params["objective"] = "binary:logistic"
    else:
        model_params["objective"] = "multi:softprob"
        model_params["num_class"] = len(classes)
    model = XGBClassifier(**model_params)
    model.fit(x_train, y_train)

    predicted_encoded = model.predict(x_valid)
    predicted = [str(value) for value in label_encoder.inverse_transform(predicted_encoded)]
    probabilities = model.predict_proba(x_valid)
    probability_maps = [
        {classes[index]: float(probability) for index, probability in enumerate(row)}
        for row in probabilities
    ]
    labels = sorted({*classes, *y_true, *predicted})
    positive_label = labels[-1] if len(labels) == 2 else None

    predictions: list[dict[str, Any]] = []
    positive_scores: list[float] = []
    for source_row, actual, prediction, probability_map in zip(
        valid_rows, y_true, predicted, probability_maps, strict=True
    ):
        score = (
            probability_map.get(positive_label, 0.0)
            if positive_label
            else probability_map.get(prediction, 0.0)
        )
        positive_scores.append(score)
        predictions.append(
            {
                "row_index": source_row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
                "score": score,
            }
        )

    dummy_metrics, _ = run_dummy_classification_baseline(rows, primary_metric)
    macro_f1_value = macro_f1(y_true, predicted, labels)
    feature_recipe = feature_builder.recipe("xgboost_classifier", model_params)
    metrics: dict[str, Any] = {
        "baseline_type": "xgboost_classifier",
        "baseline_strength": "strong",
        "model_family": "xgboost",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train_raw),
        "feature_count": feature_recipe["feature_count"],
        "numeric_feature_count": feature_recipe["numeric_feature_count"],
        "categorical_feature_count": feature_recipe["categorical_feature_count"],
        "text_feature_count": feature_recipe["text_feature_count"],
        "excluded_columns": baseline_plan.get("excluded_columns", []),
        "accuracy": accuracy(y_true, predicted),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss_from_probability_maps(y_true, probability_maps),
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
        "feature_recipe": feature_recipe,
        "_model_package_payload": ModelPackagePayload(
            package={
                "schema_version": "model_package.v1",
                "model": model,
                "feature_builder": feature_builder,
                "label_encoder": label_encoder,
                "classes": classes,
                "prediction_kind": "classification",
            },
            baseline_type="xgboost_classifier",
            model_family="xgboost",
            task_type=str(baseline_plan.get("task_type", "classification")),
        ),
    }
    if positive_label:
        y_binary = [1 if value == positive_label else 0 for value in y_true]
        metrics["positive_label"] = positive_label
        metrics["f1"] = label_f1(y_true, predicted, positive_label)
        metrics["roc_auc"] = binary_roc_auc(y_binary, positive_scores)
        metrics["pr_auc"] = average_precision(y_binary, positive_scores)
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, metrics["accuracy"])
    return metrics, predictions


def run_lightgbm_classification_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from lightgbm import LGBMClassifier
    except ImportError as exc:
        raise ModelDependencyRequiredError(
            model_candidate="lightgbm",
            package_name="lightgbm",
            install_spec="lightgbm>=4.0",
        ) from exc

    feature_rows = augment_rows_for_baseline_plan(rows, baseline_plan)
    train_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("LightGBM baseline requires non-empty train and valid target values")

    y_train_raw = [str(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [str(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    label_encoder = LabelEncoder()
    y_train = label_encoder.fit_transform(y_train_raw)
    classes = [str(label) for label in label_encoder.classes_]
    if len(classes) < 2:
        raise ValueError("LightGBM classification requires at least two train classes")

    feature_builder = StrongFeatureBuilder(baseline_plan)
    x_train = feature_builder.fit_transform(train_rows)
    x_valid = feature_builder.transform(valid_rows)
    model_params: dict[str, Any] = {
        "n_estimators": 120,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": 42,
        "n_jobs": 1,
        "verbose": -1,
    }
    if len(classes) == 2:
        model_params["objective"] = "binary"
    else:
        model_params["objective"] = "multiclass"
        model_params["num_class"] = len(classes)
    model = LGBMClassifier(**model_params)
    model.fit(x_train, y_train)

    predicted_encoded = model.predict(x_valid)
    predicted = [str(value) for value in label_encoder.inverse_transform(predicted_encoded)]
    probabilities = model.predict_proba(x_valid)
    probability_maps = [
        {classes[index]: float(probability) for index, probability in enumerate(row)}
        for row in probabilities
    ]
    labels = sorted({*classes, *y_true, *predicted})
    positive_label = labels[-1] if len(labels) == 2 else None

    predictions: list[dict[str, Any]] = []
    positive_scores: list[float] = []
    for source_row, actual, prediction, probability_map in zip(
        valid_rows, y_true, predicted, probability_maps, strict=True
    ):
        score = (
            probability_map.get(positive_label, 0.0)
            if positive_label
            else probability_map.get(prediction, 0.0)
        )
        positive_scores.append(score)
        predictions.append(
            {
                "row_index": source_row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
                "score": score,
            }
        )

    dummy_metrics, _ = run_dummy_classification_baseline(rows, primary_metric)
    macro_f1_value = macro_f1(y_true, predicted, labels)
    feature_recipe = feature_builder.recipe("lightgbm_classifier", model_params)
    metrics: dict[str, Any] = {
        "baseline_type": "lightgbm_classifier",
        "baseline_strength": "strong",
        "model_family": "lightgbm",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train_raw),
        "feature_count": feature_recipe["feature_count"],
        "numeric_feature_count": feature_recipe["numeric_feature_count"],
        "categorical_feature_count": feature_recipe["categorical_feature_count"],
        "text_feature_count": feature_recipe["text_feature_count"],
        "excluded_columns": baseline_plan.get("excluded_columns", []),
        "accuracy": accuracy(y_true, predicted),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss_from_probability_maps(y_true, probability_maps),
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
        "feature_recipe": feature_recipe,
        "_model_package_payload": ModelPackagePayload(
            package={
                "schema_version": "model_package.v1",
                "model": model,
                "feature_builder": feature_builder,
                "label_encoder": label_encoder,
                "classes": classes,
                "prediction_kind": "classification",
            },
            baseline_type="lightgbm_classifier",
            model_family="lightgbm",
            task_type=str(baseline_plan.get("task_type", "classification")),
        ),
    }
    if positive_label:
        y_binary = [1 if value == positive_label else 0 for value in y_true]
        metrics["positive_label"] = positive_label
        metrics["f1"] = label_f1(y_true, predicted, positive_label)
        metrics["roc_auc"] = binary_roc_auc(y_binary, positive_scores)
        metrics["pr_auc"] = average_precision(y_binary, positive_scores)
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, metrics["accuracy"])
    return metrics, predictions


def run_logistic_regression_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    target_column: str,
    excluded_columns: list[str],
    baseline_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = baseline_plan or build_baseline_plan(
        rows,
        task_type="binary_classification",
        target_column=target_column,
        primary_metric=primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=None,
    )
    feature_rows = augment_rows_for_baseline_plan(rows, plan)
    train_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")

    y_train = [str(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [str(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    if len(set(y_train)) < 2:
        raise ValueError("Logistic regression requires at least two train classes")

    feature_builder = StrongFeatureBuilder(plan)
    x_train = feature_builder.fit_transform(train_rows)
    x_valid = feature_builder.transform(valid_rows)
    model_params = {"class_weight": "balanced", "max_iter": 1000, "n_jobs": 1}
    model = LogisticRegression(**model_params)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(x_train, y_train)

    predicted = [str(value) for value in model.predict(x_valid)]
    classes = [str(value) for value in model.classes_]
    probabilities = model.predict_proba(x_valid)
    probability_maps = [
        {classes[index]: float(probability) for index, probability in enumerate(row)}
        for row in probabilities
    ]
    labels = sorted({*classes, *y_true, *predicted})
    positive_label = labels[-1] if len(labels) == 2 else None

    predictions: list[dict[str, Any]] = []
    positive_scores: list[float] = []
    for source_row, actual, prediction, probability_map in zip(
        valid_rows, y_true, predicted, probability_maps, strict=True
    ):
        score = (
            probability_map.get(positive_label, 0.0)
            if positive_label
            else probability_map.get(prediction, 0.0)
        )
        positive_scores.append(score)
        predictions.append(
            {
                "row_index": source_row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
                "score": score,
            }
        )

    dummy_metrics, _ = run_dummy_classification_baseline(rows, primary_metric)
    macro_f1_value = macro_f1(y_true, predicted, labels)
    feature_recipe = feature_builder.recipe("logistic_regression", model_params)
    metrics: dict[str, Any] = {
        "baseline_type": "logistic_regression",
        "baseline_strength": "interpretable",
        "model_family": "linear",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train),
        "feature_count": feature_recipe["feature_count"],
        "numeric_feature_count": feature_recipe["numeric_feature_count"],
        "categorical_feature_count": feature_recipe["categorical_feature_count"],
        "text_feature_count": feature_recipe["text_feature_count"],
        "excluded_columns": plan.get("excluded_columns", excluded_columns),
        "accuracy": accuracy(y_true, predicted),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss_from_probability_maps(y_true, probability_maps),
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
        "feature_recipe": feature_recipe,
        "_model_package_payload": ModelPackagePayload(
            package={
                "schema_version": "model_package.v1",
                "model": model,
                "feature_builder": feature_builder,
                "label_encoder": None,
                "classes": classes,
                "prediction_kind": "classification",
            },
            baseline_type="logistic_regression",
            model_family="linear",
            task_type=str(plan.get("task_type", "classification")),
        ),
    }
    if positive_label:
        y_binary = [1 if value == positive_label else 0 for value in y_true]
        metrics["positive_label"] = positive_label
        metrics["f1"] = label_f1(y_true, predicted, positive_label)
        metrics["roc_auc"] = binary_roc_auc(y_binary, positive_scores)
        metrics["pr_auc"] = average_precision(y_binary, positive_scores)
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, metrics["accuracy"])
    return metrics, predictions


def run_dummy_classification_baseline(
    rows: list[dict[str, Any]], primary_metric: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train_targets = [
        str(row[TARGET_VALUE_COLUMN])
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_targets or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")

    counts = Counter(train_targets)
    total = sum(counts.values())
    labels = sorted({*counts.keys(), *(str(row[TARGET_VALUE_COLUMN]) for row in valid_rows)})
    distribution = {label: counts.get(label, 0) / total for label in labels}
    majority_label = max(labels, key=lambda label: (distribution.get(label, 0.0), label))
    positive_label = labels[-1] if len(labels) == 2 else None

    predictions: list[dict[str, Any]] = []
    y_true: list[str] = []
    y_pred: list[str] = []
    scores: list[float] = []
    for row in valid_rows:
        actual = str(row[TARGET_VALUE_COLUMN])
        score = distribution.get(positive_label, 0.0) if positive_label else distribution[majority_label]
        y_true.append(actual)
        y_pred.append(majority_label)
        scores.append(score)
        predictions.append(
            {
                "row_index": row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": majority_label,
                "score": score,
            }
        )

    macro_f1_value = macro_f1(y_true, y_pred, labels)
    metrics: dict[str, Any] = {
        "baseline_type": "majority_classifier",
        "model_baseline_attempted": False,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "class_distribution_train": distribution,
        "majority_label": majority_label,
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss(y_true, distribution),
    }
    if positive_label:
        y_binary = [1 if value == positive_label else 0 for value in y_true]
        metrics["positive_label"] = positive_label
        metrics["f1"] = label_f1(y_true, y_pred, positive_label)
        metrics["roc_auc"] = binary_roc_auc(y_binary, scores)
        metrics["pr_auc"] = average_precision(y_binary, scores)
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, metrics["accuracy"])
    return metrics, predictions


def run_regression_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    target_column: str,
    excluded_columns: list[str],
    baseline_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = baseline_plan or build_baseline_plan(
        rows,
        task_type="regression",
        target_column=target_column,
        primary_metric=primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=None,
    )
    try:
        return run_xgboost_regression_baseline(rows, primary_metric, baseline_plan=plan)
    except Exception as xgb_exc:
        plan.setdefault("fallback_events", []).append(
            {"from": "xgboost_regressor", "reason": str(xgb_exc)}
        )
    try:
        return run_ridge_regression_baseline(
            rows,
            primary_metric,
            target_column=target_column,
            excluded_columns=excluded_columns,
        )
    except Exception as linear_exc:
        metrics, predictions = run_dummy_regression_baseline(rows, primary_metric)
        metrics["model_baseline_attempted"] = True
        metrics["model_baseline_error"] = str(linear_exc)
        metrics["fallback_reason"] = "xgboost_and_ridge_regression_failed"
        metrics["feature_recipe"] = build_fallback_feature_recipe("mean_regressor")
        return metrics, predictions


def run_regression_model_candidate(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    model_candidate: str,
    target_column: str,
    excluded_columns: list[str],
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if model_candidate == "xgboost":
        return run_xgboost_regression_baseline(rows, primary_metric, baseline_plan=baseline_plan)
    if model_candidate == "lightgbm":
        return run_lightgbm_regression_baseline(rows, primary_metric, baseline_plan=baseline_plan)
    if model_candidate == "ridge_regression":
        return run_ridge_regression_baseline(
            rows,
            primary_metric,
            target_column=target_column,
            excluded_columns=excluded_columns,
        )
    raise ValueError(f"{model_candidate} is not supported for regression training")


def run_xgboost_regression_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    feature_rows = augment_rows_for_baseline_plan(rows, baseline_plan)
    train_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")

    y_train = [float(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [float(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    feature_builder = StrongFeatureBuilder(baseline_plan)
    x_train = feature_builder.fit_transform(train_rows)
    x_valid = feature_builder.transform(valid_rows)
    model_params: dict[str, Any] = {
        "n_estimators": 100,
        "max_depth": 3,
        "learning_rate": 0.06,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": 42,
        "n_jobs": 1,
        "tree_method": "hist",
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
    }
    model = XGBRegressor(**model_params)
    model.fit(x_train, y_train)
    predicted = [float(value) for value in model.predict(x_valid)]

    predictions: list[dict[str, Any]] = []
    for row, actual, prediction in zip(valid_rows, y_true, predicted, strict=True):
        predictions.append(
            {
                "row_index": row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
            }
        )

    dummy_metrics, _ = run_dummy_regression_baseline(rows, primary_metric)
    rmse_value = root_mean_squared_error(y_true, predicted)
    mae_value = mean_absolute_error(y_true, predicted)
    r2_value = r2_score(y_true, predicted)
    feature_recipe = feature_builder.recipe("xgboost_regressor", model_params)
    metrics: dict[str, Any] = {
        "baseline_type": "xgboost_regressor",
        "baseline_strength": "strong",
        "model_family": "xgboost",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train),
        "feature_count": feature_recipe["feature_count"],
        "numeric_feature_count": feature_recipe["numeric_feature_count"],
        "categorical_feature_count": feature_recipe["categorical_feature_count"],
        "text_feature_count": feature_recipe["text_feature_count"],
        "excluded_columns": baseline_plan.get("excluded_columns", []),
        "rmse": rmse_value,
        "mae": mae_value,
        "r2": r2_value,
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
        "feature_recipe": feature_recipe,
        "_model_package_payload": ModelPackagePayload(
            package={
                "schema_version": "model_package.v1",
                "model": model,
                "feature_builder": feature_builder,
                "label_encoder": None,
                "classes": None,
                "prediction_kind": "regression",
            },
            baseline_type="xgboost_regressor",
            model_family="xgboost",
            task_type=str(baseline_plan.get("task_type", "regression")),
        ),
    }
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, rmse_value)
    return metrics, predictions


def run_lightgbm_regression_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    baseline_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        from lightgbm import LGBMRegressor
    except ImportError as exc:
        raise ModelDependencyRequiredError(
            model_candidate="lightgbm",
            package_name="lightgbm",
            install_spec="lightgbm>=4.0",
        ) from exc

    feature_rows = augment_rows_for_baseline_plan(rows, baseline_plan)
    train_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("LightGBM baseline requires non-empty train and valid target values")

    y_train = [float(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [float(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    feature_builder = StrongFeatureBuilder(baseline_plan)
    x_train = feature_builder.fit_transform(train_rows)
    x_valid = feature_builder.transform(valid_rows)
    model_params: dict[str, Any] = {
        "n_estimators": 140,
        "learning_rate": 0.04,
        "num_leaves": 31,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "random_state": 42,
        "n_jobs": 1,
        "objective": "regression",
        "verbose": -1,
    }
    model = LGBMRegressor(**model_params)
    model.fit(x_train, y_train)
    predicted = [float(value) for value in model.predict(x_valid)]

    predictions: list[dict[str, Any]] = []
    for row, actual, prediction in zip(valid_rows, y_true, predicted, strict=True):
        predictions.append(
            {
                "row_index": row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
            }
        )

    dummy_metrics, _ = run_dummy_regression_baseline(rows, primary_metric)
    rmse_value = root_mean_squared_error(y_true, predicted)
    mae_value = mean_absolute_error(y_true, predicted)
    r2_value = r2_score(y_true, predicted)
    feature_recipe = feature_builder.recipe("lightgbm_regressor", model_params)
    metrics: dict[str, Any] = {
        "baseline_type": "lightgbm_regressor",
        "baseline_strength": "strong",
        "model_family": "lightgbm",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train),
        "feature_count": feature_recipe["feature_count"],
        "numeric_feature_count": feature_recipe["numeric_feature_count"],
        "categorical_feature_count": feature_recipe["categorical_feature_count"],
        "text_feature_count": feature_recipe["text_feature_count"],
        "excluded_columns": baseline_plan.get("excluded_columns", []),
        "rmse": rmse_value,
        "mae": mae_value,
        "r2": r2_value,
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
        "feature_recipe": feature_recipe,
        "_model_package_payload": ModelPackagePayload(
            package={
                "schema_version": "model_package.v1",
                "model": model,
                "feature_builder": feature_builder,
                "label_encoder": None,
                "classes": None,
                "prediction_kind": "regression",
            },
            baseline_type="lightgbm_regressor",
            model_family="lightgbm",
            task_type=str(baseline_plan.get("task_type", "regression")),
        ),
    }
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, rmse_value)
    return metrics, predictions


def run_ridge_regression_baseline(
    rows: list[dict[str, Any]],
    primary_metric: str,
    *,
    target_column: str,
    excluded_columns: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train_rows = [
        row
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_rows or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")

    y_train = [float(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [float(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    x_train = [
        build_feature_dict(row, target_column=target_column, excluded_columns=excluded_columns)
        for row in train_rows
    ]
    x_valid = [
        build_feature_dict(row, target_column=target_column, excluded_columns=excluded_columns)
        for row in valid_rows
    ]
    pipeline = Pipeline(
        [
            ("features", DictVectorizer(sparse=True)),
            ("regressor", Ridge(alpha=1.0)),
        ]
    )
    pipeline.fit(x_train, y_train)
    predicted = [float(value) for value in pipeline.predict(x_valid)]

    predictions: list[dict[str, Any]] = []
    for row, actual, prediction in zip(valid_rows, y_true, predicted, strict=True):
        predictions.append(
            {
                "row_index": row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
            }
        )

    dummy_metrics, _ = run_dummy_regression_baseline(rows, primary_metric)
    rmse_value = root_mean_squared_error(y_true, predicted)
    mae_value = mean_absolute_error(y_true, predicted)
    r2_value = r2_score(y_true, predicted)
    metrics: dict[str, Any] = {
        "baseline_type": "ridge_regression",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train),
        "feature_count": len(pipeline.named_steps["features"].get_feature_names_out()),
        "excluded_columns": excluded_columns,
        "rmse": rmse_value,
        "mae": mae_value,
        "r2": r2_value,
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
    }
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, rmse_value)
    return metrics, predictions


def run_dummy_regression_baseline(
    rows: list[dict[str, Any]], primary_metric: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train_values = [
        float(row[TARGET_VALUE_COLUMN])
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "train" and row[TARGET_VALUE_COLUMN] is not None
    ]
    valid_rows = [
        row
        for row in rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not train_values or not valid_rows:
        raise ValueError("Baseline requires non-empty train and valid target values")
    prediction = sum(train_values) / len(train_values)

    y_true: list[float] = []
    predictions: list[dict[str, Any]] = []
    for row in valid_rows:
        actual = float(row[TARGET_VALUE_COLUMN])
        y_true.append(actual)
        predictions.append(
            {
                "row_index": row[ROW_INDEX_COLUMN],
                "split": "valid",
                "target": actual,
                "prediction": prediction,
            }
        )
    y_pred = [prediction for _ in y_true]
    rmse_value = root_mean_squared_error(y_true, y_pred)
    mae_value = mean_absolute_error(y_true, y_pred)
    r2_value = r2_score(y_true, y_pred)
    metrics: dict[str, Any] = {
        "baseline_type": "mean_regressor",
        "model_baseline_attempted": False,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "prediction_mean": prediction,
        "rmse": rmse_value,
        "mae": mae_value,
        "r2": r2_value,
        "primary_metric_value": metric_value(
            {"rmse": rmse_value, "mae": mae_value, "r2": r2_value},
            primary_metric,
            rmse_value,
        ),
    }
    return metrics, predictions


def build_baseline_plan(
    rows: list[dict[str, Any]],
    *,
    task_type: str,
    target_column: str,
    primary_metric: str,
    excluded_columns: list[str],
    evaluation_spec: EvaluationSpec | None,
) -> dict[str, Any]:
    feature_columns = collect_feature_columns(rows, target_column, excluded_columns)
    column_profiles = [
        profile_feature_column(column, rows)
        for column in feature_columns
    ]
    return build_baseline_plan_from_column_profiles(
        column_profiles,
        task_type=task_type,
        target_column=target_column,
        primary_metric=primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=evaluation_spec,
        row_count=len(rows),
        column_count=len(feature_columns),
        planning_source="observed_split_rows",
        profile_boundary=None,
    )


def build_baseline_plan_from_profile(
    profile: dict[str, Any],
    *,
    task_type: str,
    target_column: str,
    primary_metric: str,
    excluded_columns: list[str],
    evaluation_spec: EvaluationSpec | None,
    row_count: int,
    column_count: int,
) -> dict[str, Any]:
    blocked = {target_column, *excluded_columns, *SYSTEM_COLUMNS}
    profile_columns_raw = profile.get("columns")
    profile_columns: list[Any] = profile_columns_raw if isinstance(profile_columns_raw, list) else []
    column_profiles = [
        baseline_profile_from_eda_column(item)
        for item in profile_columns
        if isinstance(item, dict) and str(item.get("name")) not in blocked
    ]
    return build_baseline_plan_from_column_profiles(
        column_profiles,
        task_type=task_type,
        target_column=target_column,
        primary_metric=primary_metric,
        excluded_columns=excluded_columns,
        evaluation_spec=evaluation_spec,
        row_count=row_count,
        column_count=column_count,
        planning_source="eda_profile",
        profile_boundary={
            "profile_mode": profile.get("profile_mode"),
            "column_stat_scope": profile.get("column_stat_scope"),
            "sample_row_count": profile.get("profile_sample", {}).get("sample_row_count")
            if isinstance(profile.get("profile_sample"), dict)
            else None,
            "deep_profile_recommended": profile.get("deferred_deep_profile", {}).get("recommended")
            if isinstance(profile.get("deferred_deep_profile"), dict)
            else None,
        },
    )


def build_baseline_plan_from_column_profiles(
    column_profiles: list[dict[str, Any]],
    *,
    task_type: str,
    target_column: str,
    primary_metric: str,
    excluded_columns: list[str],
    evaluation_spec: EvaluationSpec | None,
    row_count: int,
    column_count: int,
    planning_source: str,
    profile_boundary: dict[str, Any] | None,
) -> dict[str, Any]:
    numeric_columns = [item["name"] for item in column_profiles if item["role"] == "numeric"]
    categorical_columns = [item["name"] for item in column_profiles if item["role"] == "categorical"]
    text_columns = [item["name"] for item in column_profiles if item["role"] == "text"]
    datetime_columns = [item["name"] for item in column_profiles if item["role"] == "datetime"]
    identifier_columns = [item["name"] for item in column_profiles if item["role"] == "identifier"]
    ignored_columns = [item["name"] for item in column_profiles if item["role"] == "ignored"]
    feature_columns = [item["name"] for item in column_profiles]

    split_type = evaluation_spec.split_type if evaluation_spec else "ad_hoc"
    spec_time_column = evaluation_spec.time_column if evaluation_spec else None
    spec_group_column = evaluation_spec.group_column if evaluation_spec else None
    time_column = spec_time_column if spec_time_column in feature_columns else (datetime_columns[0] if datetime_columns else None)
    group_column = spec_group_column if spec_group_column in feature_columns else None
    calendar_feature_columns = calendar_feature_names(datetime_columns)
    lag_rolling_specs: list[dict[str, Any]] = []
    skipped_features: list[dict[str, Any]] = []
    if time_column and split_type == "time":
        for column in numeric_columns[:MAX_LAG_ROLLING_SOURCE_COLUMNS]:
            lag_rolling_specs.append(
                {
                    "source_column": column,
                    "features": [
                        lag_feature_name(column, 1),
                        rolling_feature_name(column, 3),
                    ],
                    "policy": "historical_covariates_only",
                }
            )
    elif time_column:
        skipped_features.append(
            {
                "feature_family": "lag_rolling",
                "reason": "disabled because the approved EvaluationSpec is not a time split",
                "time_column": time_column,
            }
        )

    model_family = "xgboost"
    if task_type == "regression":
        candidate_model = "xgboost_regressor"
    else:
        candidate_model = "xgboost_classifier"
    rationale = [
        "Use a strong tabular baseline before agent-authored model work.",
        "Numeric columns use median imputation.",
        "Categorical columns use ordinal encoding with an unknown bucket.",
        "Text-like columns use TF-IDF with bounded vocabulary.",
        "Datetime columns produce calendar features.",
    ]
    if lag_rolling_specs:
        rationale.append("Lag and rolling features are enabled only for an approved time split.")
    else:
        rationale.append("Target-derived lags are disabled until time semantics and availability are confirmed.")

    return {
        "plan_version": "baseline_plan.v1",
        "candidate_model": candidate_model,
        "model_family": model_family,
        "task_type": task_type,
        "primary_metric": primary_metric,
        "target_column": target_column,
        "split_type": split_type,
        "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
        "time_column": time_column,
        "group_column": group_column,
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "text_columns": text_columns,
        "datetime_columns": datetime_columns,
        "identifier_columns": identifier_columns,
        "ignored_columns": ignored_columns,
        "excluded_columns": excluded_columns,
        "calendar_feature_columns": calendar_feature_columns,
        "lag_rolling_specs": lag_rolling_specs,
        "skipped_features": skipped_features,
        "column_profiles": column_profiles,
        "planning_source": planning_source,
        "profile_boundary": profile_boundary or {},
        "resource_guard": baseline_resource_guard(
            row_count=row_count,
            column_count=column_count,
            numeric_count=len(numeric_columns),
            categorical_count=len(categorical_columns),
            text_count=len(text_columns),
            datetime_count=len(datetime_columns),
        ),
        "safeguards": [
            "target_column excluded from features",
            "EvaluationSpec.excluded_columns respected",
            "SplitManifest train/valid labels respected",
            "validation/test target values are not used for feature fitting",
            "target lags disabled in MVP strong baseline",
        ],
        "assumptions": [
            {
                "topic": "prediction_time_availability",
                "statement": "Columns not excluded by EvaluationSpec are treated as available at prediction time for this baseline.",
                "risk_level": "medium",
                "fallback_policy": "scenario_compare",
            },
            {
                "topic": "categorical_encoding",
                "statement": "Ordinal encoding is acceptable for the initial XGBoost baseline because tree models can handle ordered integer bins as a pragmatic starting point.",
                "risk_level": "low",
                "fallback_policy": "infer_and_continue",
            },
        ],
        "rationale": rationale,
        "fallback_events": [],
    }


def create_baseline_strategy_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
) -> BaselineStrategyPlanResult:
    if not project.target_column:
        raise ValueError("Project target_column is required before planning baseline strategy")
    dataset = db.get(DatasetSnapshot, evaluation_spec.dataset_snapshot_id)
    if dataset is None:
        raise ValueError("DatasetSnapshot not found")
    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    split_artifact = db.get(Artifact, split_manifest.artifact_id)
    if dataset_artifact is None or split_artifact is None:
        raise ValueError("Required dataset or split artifact not found")
    profile = load_profile_for_dataset(db, dataset)
    task_type = resolve_task_type_from_profile(project.task_type, profile)
    baseline_plan = build_baseline_plan_from_profile(
        profile,
        task_type=task_type,
        target_column=project.target_column,
        primary_metric=evaluation_spec.primary_metric,
        excluded_columns=parse_string_list(loads_json(evaluation_spec.excluded_columns_json, [])),
        evaluation_spec=evaluation_spec,
        row_count=int(dataset.row_count or profile.get("row_count") or 0),
        column_count=int(dataset.column_count or profile.get("column_count") or 0),
    )
    strategy_plan = build_baseline_strategy_plan(
        db,
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        baseline_plan=baseline_plan,
    )
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="baseline_strategy_plan",
        name=f"baseline_strategy_plan_{new_id('bsp')}",
        filename="baseline_strategy_plan.json",
        payload=strategy_plan,
        metadata={
            "dataset_snapshot_id": dataset.id,
            "evaluation_spec_id": evaluation_spec.id,
            "split_manifest_id": split_manifest.id,
            "strategy_count": len(strategy_plan.get("candidate_strategies", [])),
            "selected_baseline_type": strategy_plan["selected_execution"].get("baseline_type"),
            "strategy_mode": strategy_plan.get("context", {}).get("strategy_mode"),
            "matched_asset_count": strategy_plan.get("context", {})
            .get("library_context", {})
            .get("matched_asset_count"),
            "agent_task_count": len(strategy_plan.get("next_agent_tasks", [])),
            "planning_source": baseline_plan.get("planning_source"),
            "resource_guard_level": baseline_plan.get("resource_guard", {}).get("level"),
        },
    )
    for from_type, from_id, relation in [
        ("dataset_snapshot", dataset.id, "plans_from"),
        ("evaluation_spec", evaluation_spec.id, "constrains"),
        ("split_manifest", split_manifest.id, "constrains"),
    ]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type=from_type,
            from_asset_id=from_id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type=relation,
        )
    return BaselineStrategyPlanResult(plan=strategy_plan, artifact=artifact)


def build_baseline_strategy_plan(
    db: Session,
    *,
    project: Project,
    dataset: DatasetSnapshot,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
    baseline_plan: dict[str, Any],
) -> dict[str, Any]:
    quality_artifact = latest_project_artifact(db, project.id, "data_quality_gate")
    relational_artifact = latest_project_artifact(db, project.id, "relational_catalog")
    numeric_count = len(parse_string_list(baseline_plan.get("numeric_columns", [])))
    categorical_count = len(parse_string_list(baseline_plan.get("categorical_columns", [])))
    text_columns = parse_string_list(baseline_plan.get("text_columns", []))
    datetime_columns = parse_string_list(baseline_plan.get("datetime_columns", []))
    lag_specs = baseline_plan.get("lag_rolling_specs", [])
    relational_metadata = loads_json(relational_artifact.metadata_json, {}) if relational_artifact else {}
    table_count = int(relational_metadata.get("table_count") or 0)
    relationship_count = int(relational_metadata.get("relationship_count") or 0)
    library_context = baseline_library_context(db, baseline_plan, table_count)
    resource_guard_raw = baseline_plan.get("resource_guard")
    resource_guard: dict[str, Any] = resource_guard_raw if isinstance(resource_guard_raw, dict) else {}
    strong_status = (
        "selected_for_guarded_local_run"
        if resource_guard.get("level") in {"large_local_run", "moderate_local_run"}
        else "selected_for_local_run"
    )
    candidates = [
        {
            "id": "sanity_floor",
            "name": "Distribution sanity floor",
            "status": "always_run",
            "implementation": "majority_classifier_or_mean_regressor",
            "why": "Provides a minimum viable reference and detects broken evaluation wiring.",
            "uses": ["target_distribution", "SplitManifest"],
        },
        {
            "id": "strong_single_table_xgboost",
            "name": "Strong single-table XGBoost baseline",
            "status": strong_status,
            "implementation": baseline_plan.get("candidate_model"),
            "why": "Good pragmatic baseline for mixed numeric, categorical, datetime, and sparse text features when the profiled table supports it.",
            "uses": ["numeric_median_imputation", "ordinal_categorical_encoding", "text_tfidf", "datetime_calendar_features"],
            "selection_policy": "chosen from dataset signals and approved EvaluationSpec, not treated as the only acceptable modeling approach",
            "resource_guard": resource_guard,
        },
        {
            "id": "text_tfidf",
            "name": "Text TF-IDF branch",
            "status": "included" if text_columns else "not_applicable",
            "columns": text_columns,
            "why": "Short text/comment/description columns should be represented without requiring a GenAI feature dependency.",
        },
        {
            "id": "categorical_ordinal_encoding",
            "name": "Categorical ordinal encoding",
            "status": "included" if categorical_count else "not_applicable",
            "column_count": categorical_count,
            "why": "Tree baselines can use stable integer bins as a first pass; later recipes can compare target encoding or learned embeddings.",
        },
        {
            "id": "datetime_calendar_features",
            "name": "Datetime calendar features",
            "status": "included" if datetime_columns else "not_applicable",
            "columns": datetime_columns,
            "why": "Calendar decomposition is low risk when the timestamp exists at prediction time.",
        },
        {
            "id": "time_series_lag_rolling",
            "name": "Lag and rolling covariates",
            "status": "included" if lag_specs else ("deferred" if baseline_plan.get("time_column") else "not_applicable"),
            "specs": lag_specs,
            "why": "Only enabled when EvaluationSpec uses a time split, so future information is not mixed into feature fitting.",
        },
        {
            "id": "relational_aggregation_features",
            "name": "Relational aggregation feature recipe",
            "status": "agent_required" if table_count > 1 else "not_applicable",
            "table_count": table_count,
            "relationship_count": relationship_count,
            "why": "Supporting tables need join semantics, aggregation windows, and availability checks before becoming model features.",
            "uses": ["RelationalCatalog", "FeatureRecipe", "SplitManifest", "controlled_agent_workspace"],
        },
    ]
    next_agent_tasks = []
    if table_count > 1:
        next_agent_tasks.append(
            {
                "task_type": "design_feature_recipe",
                "title": "Design relational aggregation baseline candidate",
                "required_context": ["relational_catalog", "EvaluationSpec", "SplitManifest", "DataQualityGate"],
                "guardrails": [
                    "respect SplitManifest",
                    "fit aggregations on train split only",
                    "confirm prediction-time availability before using supporting tables",
                ],
            }
        )
    return {
        "schema_version": "baseline_strategy_plan.v1",
        "id": new_id("bsp"),
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "dataset": {
            "dataset_snapshot_id": dataset.id,
            "source_type": dataset.source_type,
            "source_ref": dataset.source_ref,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "schema_hash": dataset.schema_hash,
        },
        "evaluation": {
            "evaluation_spec_id": evaluation_spec.id,
            "split_manifest_id": split_manifest.id,
            "split_type": evaluation_spec.split_type,
            "primary_metric": evaluation_spec.primary_metric,
            "time_column": evaluation_spec.time_column,
            "group_column": evaluation_spec.group_column,
            "stratify_column": evaluation_spec.stratify_column,
        },
        "context": {
            "strategy_mode": "adaptive_baseline_planning",
            "feature_inventory": {
                "numeric_count": numeric_count,
                "categorical_count": categorical_count,
                "text_count": len(text_columns),
                "datetime_count": len(datetime_columns),
                "identifier_count": len(parse_string_list(baseline_plan.get("identifier_columns", []))),
            },
            "library_context": library_context,
            "quality_gate": artifact_summary(quality_artifact),
            "relational_catalog": artifact_summary(relational_artifact),
            "current_baseline_plan": {
                "candidate_model": baseline_plan.get("candidate_model"),
                "model_family": baseline_plan.get("model_family"),
                "planning_source": baseline_plan.get("planning_source"),
                "resource_guard": baseline_plan.get("resource_guard"),
                "profile_boundary": baseline_plan.get("profile_boundary"),
                "skipped_features": baseline_plan.get("skipped_features", []),
                "safeguards": baseline_plan.get("safeguards", []),
            },
        },
        "candidate_strategies": candidates,
        "runner_policy": baseline_runner_policy(
            baseline_plan=baseline_plan,
            table_count=table_count,
            relationship_count=relationship_count,
            library_context=library_context,
        ),
        "selected_execution": {
            "status": "planned",
            "baseline_type": baseline_plan.get("candidate_model"),
            "reason": "Local runner can execute the current single-table strong baseline now; richer relational or time-aware variants are proposed as explicit candidate strategies or AgentTasks.",
        },
        "risk_register": baseline_strategy_risks(baseline_plan, quality_artifact, table_count, relationship_count),
        "next_agent_tasks": next_agent_tasks,
        "reporting_plan": baseline_reporting_plan(
            baseline_plan=baseline_plan,
            table_count=table_count,
            relationship_count=relationship_count,
        ),
    }


def baseline_library_context(
    db: Session,
    baseline_plan: dict[str, Any],
    table_count: int,
) -> dict[str, Any]:
    requested_tags = {
        "tabular_modeling",
        "gradient_boosting",
        "baseline_strategy",
        "split_manifest",
    }
    if baseline_plan.get("text_columns"):
        requested_tags.update({"text_features", "tfidf"})
    if baseline_plan.get("datetime_columns") or baseline_plan.get("lag_rolling_specs"):
        requested_tags.update({"time_features", "datetime_features", "lag_features", "rolling_statistics"})
    if table_count > 1:
        requested_tags.update({"relational_features", "multi_table", "leakage_control"})
    requested_tags.update({"reports", "visualization", "decision_dashboard"})

    assets = db.scalars(select(Asset).where(Asset.status == "active")).all()
    matched_assets: list[dict[str, Any]] = []
    for asset in assets:
        semantic_tags = {str(tag) for tag in loads_json(asset.semantic_tags_json, [])}
        matched = sorted(semantic_tags & requested_tags)
        if not matched:
            continue
        matched_assets.append(
            {
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "name": asset.name,
                "latest_version_id": asset.latest_version_id,
                "matched_semantic_tags": matched,
            }
        )
    matched_assets.sort(key=lambda item: (str(item["asset_type"]), str(item["name"])))
    return {
        "requested_semantic_tags": sorted(requested_tags),
        "matched_assets": matched_assets[:12],
        "matched_asset_count": len(matched_assets),
        "seed_hint": None
        if matched_assets
        else "Seed the cross-project asset library to attach Skill, FeatureRecipe, EvaluationPattern, and VisualizationTemplate assets.",
        "research_support_policy": {
            "mode": "controlled_web_search_or_skill_lookup_when_allowed",
            "network_default": "disabled_until_runner_policy_allows",
            "evidence_required": True,
            "purpose": "Support approach selection with current sources without making Tablex depend on external dashboards.",
        },
    }


def baseline_runner_policy(
    *,
    baseline_plan: dict[str, Any],
    table_count: int,
    relationship_count: int,
    library_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "strategy": "adaptive_baseline_planning",
        "local_runner_scope": {
            "can_execute_now": True,
            "candidate_model": baseline_plan.get("candidate_model"),
            "model_family": baseline_plan.get("model_family"),
            "resource_guard": baseline_plan.get("resource_guard"),
            "feature_families": {
                "numeric_median_imputation": bool(baseline_plan.get("numeric_columns")),
                "categorical_ordinal_encoding": bool(baseline_plan.get("categorical_columns")),
                "text_tfidf": bool(baseline_plan.get("text_columns")),
                "datetime_calendar": bool(baseline_plan.get("datetime_columns")),
                "causal_lag_rolling": bool(baseline_plan.get("lag_rolling_specs")),
            },
        },
        "agent_runner_scope": {
            "required_for_relational_features": table_count > 1,
            "relationship_count": relationship_count,
            "expected_outputs": ["feature_recipe", "experiment_plan", "run_report", "visualization_spec"],
            "guardrails": [
                "respect SplitManifest",
                "fit encoders, TF-IDF, joins, and aggregations on train folds only",
                "do not include validation/test targets in prompts or feature generation",
                "confirm prediction-time availability before using supporting tables",
            ],
        },
        "dependency_checks": {
            "xgboost": "available",
            "scikit_learn": "available",
            "duckdb": "available",
            "library_asset_matches": library_context.get("matched_asset_count", 0),
        },
    }


def baseline_reporting_plan(
    *,
    baseline_plan: dict[str, Any],
    table_count: int,
    relationship_count: int,
) -> dict[str, Any]:
    visualizations: list[dict[str, Any]] = [
        {
            "id": "baseline_vs_sanity_floor",
            "chart_type": "metric_cards",
            "purpose": "Compare the selected baseline against majority/mean sanity floors.",
        },
        {
            "id": "feature_inventory",
            "chart_type": "category_bars",
            "purpose": "Show numeric, categorical, text, datetime, and skipped feature families.",
        },
        {
            "id": "leaderboard_position",
            "chart_type": "leaderboard_bar",
            "purpose": "Place the run in the in-product leaderboard without external tracking tools.",
        },
    ]
    if table_count > 1:
        visualizations.append(
            {
                "id": "relational_coverage",
                "chart_type": "relationship_summary",
                "purpose": "Show supporting table count and inferred relationship coverage before relational features are trusted.",
                "table_count": table_count,
                "relationship_count": relationship_count,
            }
        )
    return {
        "expected_artifacts": [
            "baseline_strategy_plan",
            "baseline_plan",
            "feature_recipe",
            "baseline_metrics",
            "baseline_report",
            "prediction_output",
            "model_package",
            "run_report",
            "visualization_spec",
        ],
        "report_sections": [
            "Evaluation lock",
            "Feature recipe rationale",
            "Sanity floor comparison",
            "Risk and unresolved assumptions",
            "Next candidate approaches",
        ],
        "visualization_specs": visualizations,
        "decision_notes": [
            "Baseline results are evidence for the next approach, not a fixed recipe.",
            "Relational, text, and time-series feature variants should be scenario-compared when their assumptions materially affect the task.",
        ],
    }


def baseline_strategy_risks(
    baseline_plan: dict[str, Any],
    quality_artifact: Artifact | None,
    table_count: int,
    relationship_count: int,
) -> list[dict[str, Any]]:
    risks = [
        {
            "topic": "prediction_time_availability",
            "risk_level": "medium",
            "mitigation": "Use DataQualityGate and questions to exclude unavailable columns or scenario-compare them.",
        }
    ]
    if baseline_plan.get("time_column") and not baseline_plan.get("lag_rolling_specs"):
        risks.append(
            {
                "topic": "time_series_features",
                "risk_level": "medium",
                "mitigation": "Enable lag/rolling covariates only under an approved time split.",
            }
        )
    if table_count > 1:
        risks.append(
            {
                "topic": "relational_join_semantics",
                "risk_level": "high" if relationship_count == 0 else "medium",
                "mitigation": "Treat relational joins as an AgentTask/FeatureRecipe candidate until join keys and temporal availability are verified.",
            }
        )
    if quality_artifact is not None:
        metadata = loads_json(quality_artifact.metadata_json, {})
        if metadata.get("severity") in {"warning", "fail"}:
            risks.append(
                {
                    "topic": "data_quality_gate",
                    "risk_level": "high" if metadata.get("severity") == "fail" else "medium",
                    "mitigation": "Review leakage and evaluation-readiness findings before interpreting baseline metrics.",
                    "artifact_id": quality_artifact.id,
                }
            )
    return risks


def artifact_summary(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": metadata,
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def load_profile_for_dataset(db: Session, dataset: DatasetSnapshot) -> dict[str, Any]:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == dataset.project_id, Artifact.asset_type == "eda_profile")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("dataset_snapshot_id") != dataset.id:
            continue
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except OSError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def resolve_task_type_from_profile(task_type: str | None, profile: dict[str, Any]) -> str:
    if task_type in {"regression", "binary_classification", "multiclass_classification"}:
        return task_type
    target_profile_raw = profile.get("target_profile")
    target_profile: dict[str, Any] = target_profile_raw if isinstance(target_profile_raw, dict) else {}
    unique_count = int(target_profile.get("unique_count") or 0)
    if 0 < unique_count <= 2:
        return "binary_classification"
    if 2 < unique_count <= 20:
        return "multiclass_classification"
    return "regression"


def baseline_profile_from_eda_column(column: dict[str, Any]) -> dict[str, Any]:
    name = str(column.get("name") or "")
    semantic_type = str(column.get("semantic_type") or "").lower()
    role_hint = str(column.get("role") or "").lower()
    physical_type = str(column.get("physical_type") or "")
    role = "categorical"
    reason = f"eda_profile semantic_type={semantic_type or 'unknown'} physical_type={physical_type}"
    if role_hint in {"identifier", "group"} or semantic_type == "identifier":
        role = "identifier"
    elif semantic_type == "datetime":
        role = "datetime"
    elif semantic_type == "text":
        role = "text"
    elif semantic_type == "numeric":
        role = "numeric"
    elif semantic_type == "categorical":
        role = "categorical"
    elif any(token in physical_type.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC")):
        role = "numeric"
        reason = f"{reason}; numeric physical type fallback"
    return {
        "name": name,
        "role": role,
        "reason": reason,
        "unique_count": int(column.get("unique_count") or 0),
        "missing_fraction": float(column.get("missing_rate") or 0.0),
        "observed_count": int(column.get("stats_row_count") or 0),
        "stats_scope": column.get("stats_scope"),
        "unique_count_is_approximate": bool(column.get("unique_count_is_approximate")),
        "missing_count_is_estimated": bool(column.get("missing_count_is_estimated")),
    }


def baseline_resource_guard(
    *,
    row_count: int,
    column_count: int,
    numeric_count: int,
    categorical_count: int,
    text_count: int,
    datetime_count: int,
) -> dict[str, Any]:
    estimated_feature_families = {
        "numeric": numeric_count,
        "categorical": categorical_count,
        "text": text_count,
        "datetime": datetime_count,
    }
    if row_count >= 250_000 or column_count >= 100:
        level = "large_local_run"
        recommendation = "plan_first_then_run_with_operator_awareness"
        notes = [
            "Strategy planning uses EDA profile metadata and does not load all split rows.",
            "A full local baseline will load the approved split into Python and may take minutes on a single Docker host.",
            "Prefer an AgentTask/runner workspace or explicit smoke run before expanding relational features.",
        ]
    elif row_count >= 100_000 or column_count >= 80:
        level = "moderate_local_run"
        recommendation = "local_run_with_monitoring"
        notes = ["Local strong baseline is feasible but should be monitored for memory and runtime."]
    else:
        level = "standard_local_run"
        recommendation = "local_run"
        notes = ["Local strong baseline is within MVP size assumptions."]
    return {
        "level": level,
        "recommendation": recommendation,
        "row_count": row_count,
        "column_count": column_count,
        "estimated_feature_families": estimated_feature_families,
        "notes": notes,
    }


def collect_feature_columns(
    rows: list[dict[str, Any]], target_column: str, excluded_columns: list[str]
) -> list[str]:
    blocked = {target_column, *excluded_columns, *SYSTEM_COLUMNS}
    columns: set[str] = set()
    for row in rows:
        columns.update(column for column in row if column not in blocked)
    return sorted(columns)


def profile_feature_column(column: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_values = [row.get(column) for row in rows]
    present_values = [value for value in raw_values if not is_missing_value(value)]
    unique_count = len({canonical_value(value) for value in present_values})
    missing_fraction = 1.0 - (len(present_values) / len(raw_values)) if raw_values else 1.0
    role, reason = infer_column_role(column, present_values, len(raw_values), unique_count)
    return {
        "name": column,
        "role": role,
        "reason": reason,
        "unique_count": unique_count,
        "missing_fraction": missing_fraction,
        "observed_count": len(present_values),
    }


def infer_column_role(
    column: str, values: list[Any], row_count: int, unique_count: int
) -> tuple[str, str]:
    if not values:
        return "ignored", "all values are missing"
    lower_name = column.lower()
    unique_ratio = unique_count / max(row_count, 1)
    if looks_like_datetime_column(column, values):
        return "datetime", "date/time name or parseable datetime values"
    if all(numeric_value(value) is not None for value in values):
        if unique_count <= 2 and any(token in lower_name for token in ["flag", "is_", "has_"]):
            return "categorical", "binary indicator treated as categorical"
        return "numeric", "values are numeric"
    string_values = [str(value) for value in values]
    avg_length = sum(len(value) for value in string_values) / len(string_values)
    whitespace_fraction = sum(bool(TEXT_TOKEN_PATTERN.search(value) and " " in value) for value in string_values) / len(string_values)
    if is_identifier_like(lower_name, unique_ratio, avg_length):
        return "identifier", "high-cardinality identifier-like column"
    if avg_length >= 32 or (whitespace_fraction >= 0.35 and unique_count >= min(8, max(3, row_count // 3))):
        return "text", "free-text-like values"
    return "categorical", "string or mixed low-cardinality values"


def is_identifier_like(lower_name: str, unique_ratio: float, avg_length: float) -> bool:
    name_match = any(token in lower_name for token in ["id", "uuid", "guid", "key"])
    return name_match and unique_ratio >= 0.8 and avg_length <= 80


def looks_like_datetime_column(column: str, values: list[Any]) -> bool:
    lower_name = column.lower()
    if any(token in lower_name for token in ["date", "time", "timestamp", "datetime"]):
        return any(parse_datetime_value(value) is not None for value in values[:20])
    parsed = sum(parse_datetime_value(value) is not None for value in values[:20])
    return parsed >= max(3, min(len(values[:20]), 8))


def calendar_feature_names(datetime_columns: list[str]) -> list[str]:
    names: list[str] = []
    for column in datetime_columns:
        names.extend(
            [
                f"{column}__year",
                f"{column}__month",
                f"{column}__day",
                f"{column}__dayofweek",
                f"{column}__hour",
                f"{column}__is_weekend",
            ]
        )
    return names


def augment_rows_for_baseline_plan(
    rows: list[dict[str, Any]], baseline_plan: dict[str, Any]
) -> list[dict[str, Any]]:
    augmented = [dict(row) for row in rows]
    datetime_columns = parse_string_list(baseline_plan.get("datetime_columns", []))
    for row in augmented:
        for column in datetime_columns:
            add_calendar_features(row, column)
    lag_specs = baseline_plan.get("lag_rolling_specs", [])
    if isinstance(lag_specs, list) and lag_specs:
        add_lag_rolling_features(
            augmented,
            time_column=string_or_none(baseline_plan.get("time_column")),
            group_column=string_or_none(baseline_plan.get("group_column")),
            lag_specs=lag_specs,
        )
    return augmented


def add_calendar_features(row: dict[str, Any], column: str) -> None:
    parsed = parse_datetime_value(row.get(column))
    values: dict[str, float] = {
        f"{column}__year": math.nan,
        f"{column}__month": math.nan,
        f"{column}__day": math.nan,
        f"{column}__dayofweek": math.nan,
        f"{column}__hour": math.nan,
        f"{column}__is_weekend": math.nan,
    }
    if parsed is not None:
        values = {
            f"{column}__year": float(parsed.year),
            f"{column}__month": float(parsed.month),
            f"{column}__day": float(parsed.day),
            f"{column}__dayofweek": float(parsed.weekday()),
            f"{column}__hour": float(parsed.hour),
            f"{column}__is_weekend": 1.0 if parsed.weekday() >= 5 else 0.0,
        }
    row.update(values)


def add_lag_rolling_features(
    rows: list[dict[str, Any]],
    *,
    time_column: str | None,
    group_column: str | None,
    lag_specs: list[Any],
) -> None:
    if not time_column:
        return
    indexed_rows = [
        (index, row, parse_datetime_value(row.get(time_column)))
        for index, row in enumerate(rows)
    ]
    sortable_rows = [
        item
        for item in indexed_rows
        if item[2] is not None
    ]
    sortable_rows.sort(
        key=lambda item: (
            str(item[1].get(group_column)) if group_column else "",
            item[2] or datetime.min,
            item[0],
        )
    )
    histories: dict[tuple[str, str], list[float]] = {}
    for _, row, _ in sortable_rows:
        group_value = str(row.get(group_column)) if group_column else "__all__"
        for spec in lag_specs:
            if not isinstance(spec, dict):
                continue
            source_column = string_or_none(spec.get("source_column"))
            if not source_column:
                continue
            history_key = (group_value, source_column)
            history = histories.setdefault(history_key, [])
            row[lag_feature_name(source_column, 1)] = history[-1] if history else math.nan
            row[rolling_feature_name(source_column, 3)] = (
                sum(history[-3:]) / len(history[-3:]) if history else math.nan
            )
            value = numeric_value(row.get(source_column))
            if value is not None:
                history.append(value)


def lag_feature_name(column: str, lag: int) -> str:
    return f"{column}__lag_{lag}"


def rolling_feature_name(column: str, window: int) -> str:
    return f"{column}__rolling_{window}_mean"


class StrongFeatureBuilder:
    def __init__(self, baseline_plan: dict[str, Any]) -> None:
        self.baseline_plan = baseline_plan
        self.numeric_columns = [
            *parse_string_list(baseline_plan.get("numeric_columns", [])),
            *parse_string_list(baseline_plan.get("calendar_feature_columns", [])),
        ]
        for spec in baseline_plan.get("lag_rolling_specs", []):
            if isinstance(spec, dict) and isinstance(spec.get("features"), list):
                self.numeric_columns.extend(parse_string_list(spec["features"]))
        self.categorical_columns = parse_string_list(baseline_plan.get("categorical_columns", []))
        self.text_columns = parse_string_list(baseline_plan.get("text_columns", []))
        self.numeric_medians: dict[str, float] = {}
        self.category_maps: dict[str, dict[str, int]] = {}
        self.text_vectorizers: dict[str, TfidfVectorizer] = {}

    def fit_transform(self, rows: list[dict[str, Any]]) -> Any:
        self.fit(rows)
        return self.transform(rows)

    def fit(self, rows: list[dict[str, Any]]) -> None:
        for column in self.numeric_columns:
            values = [
                value
                for value in (numeric_value(row.get(column)) for row in rows)
                if value is not None
            ]
            self.numeric_medians[column] = median(values) if values else 0.0
        for column in self.categorical_columns:
            categories = sorted(
                {canonical_value(row.get(column)) for row in rows if not is_missing_value(row.get(column))}
            )
            self.category_maps[column] = {
                category: index
                for index, category in enumerate(categories)
            }
        for column in self.text_columns:
            vectorizer = TfidfVectorizer(
                max_features=TEXT_MAX_FEATURES_PER_COLUMN,
                ngram_range=(1, 2),
                lowercase=True,
            )
            texts = [text_value(row.get(column)) for row in rows]
            try:
                vectorizer.fit(texts)
            except ValueError:
                continue
            self.text_vectorizers[column] = vectorizer

    def transform(self, rows: list[dict[str, Any]]) -> Any:
        parts: list[Any] = []
        row_count = len(rows)
        if self.numeric_columns:
            numeric_matrix = np.array(
                [
                    [
                        coalesce_numeric(row.get(column), self.numeric_medians.get(column, 0.0))
                        for column in self.numeric_columns
                    ]
                    for row in rows
                ],
                dtype=float,
            )
            parts.append(sparse.csr_matrix(numeric_matrix))
        if self.categorical_columns:
            categorical_matrix = np.array(
                [
                    [
                        self.category_maps.get(column, {}).get(canonical_value(row.get(column)), -1)
                        for column in self.categorical_columns
                    ]
                    for row in rows
                ],
                dtype=float,
            )
            parts.append(sparse.csr_matrix(categorical_matrix))
        for column, vectorizer in self.text_vectorizers.items():
            parts.append(vectorizer.transform([text_value(row.get(column)) for row in rows]))
        if not parts:
            return sparse.csr_matrix(np.ones((row_count, 1), dtype=float))
        return sparse.hstack(parts, format="csr")

    def recipe(self, baseline_type: str, model_params: dict[str, Any]) -> dict[str, Any]:
        text_vocabulary_sizes = {
            column: len(vectorizer.vocabulary_)
            for column, vectorizer in self.text_vectorizers.items()
        }
        numeric_count = len(self.numeric_columns)
        categorical_count = len(self.categorical_columns)
        text_count = sum(text_vocabulary_sizes.values())
        return {
            "recipe_version": "feature_recipe.v1",
            "baseline_type": baseline_type,
            "model_params": model_params,
            "numeric_columns": self.numeric_columns,
            "categorical_columns": self.categorical_columns,
            "text_columns": self.text_columns,
            "active_text_columns": sorted(self.text_vectorizers),
            "text_max_features_per_column": TEXT_MAX_FEATURES_PER_COLUMN,
            "text_vocabulary_sizes": text_vocabulary_sizes,
            "ordinal_encoding": {
                column: {"known_category_count": len(mapping), "unknown_value": -1}
                for column, mapping in self.category_maps.items()
            },
            "numeric_imputation": {
                "strategy": "median",
                "medians": self.numeric_medians,
            },
            "time_features": {
                "calendar_feature_columns": parse_string_list(self.baseline_plan.get("calendar_feature_columns", [])),
                "lag_rolling_specs": self.baseline_plan.get("lag_rolling_specs", []),
            },
            "feature_count": numeric_count + categorical_count + text_count,
            "numeric_feature_count": numeric_count,
            "categorical_feature_count": categorical_count,
            "text_feature_count": text_count,
        }


def build_fallback_feature_recipe(baseline_type: str) -> dict[str, Any]:
    return {
        "recipe_version": "feature_recipe.v1",
        "baseline_type": baseline_type,
        "feature_count": 0,
        "note": "Fallback baseline uses target distribution statistics only.",
    }


def build_feature_dict(
    row: dict[str, Any],
    *,
    target_column: str,
    excluded_columns: list[str],
) -> dict[str, Any]:
    blocked_columns = {target_column, *excluded_columns, *SYSTEM_COLUMNS}
    features = {
        column: normalize_feature_value(value)
        for column, value in row.items()
        if column not in blocked_columns
    }
    if not features:
        return {"__constant__": 1.0}
    return features


def normalize_feature_value(value: Any) -> Any:
    if value is None:
        return "__missing__"
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return "__missing__"
        return float(value)
    return str(value)


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def canonical_value(value: Any) -> str:
    if is_missing_value(value):
        return "__missing__"
    return str(value)


def text_value(value: Any) -> str:
    if is_missing_value(value):
        return ""
    return str(value)


def numeric_value(value: Any) -> float | None:
    if is_missing_value(value) or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def coalesce_numeric(value: Any, default: float) -> float:
    parsed = numeric_value(value)
    return parsed if parsed is not None else default


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for pattern in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
            try:
                parsed = datetime.strptime(value.strip(), pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=None)


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def metric_value(metrics: dict[str, Any], metric_name: str, default: float) -> float:
    value = metrics.get(metric_name, default)
    if isinstance(value, int | float):
        return float(value)
    return default


def compact_sanity_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "baseline_type",
        "primary_metric_name",
        "primary_metric_value",
        "accuracy",
        "macro_f1",
        "f1",
        "log_loss",
        "roc_auc",
        "pr_auc",
        "rmse",
        "mae",
        "r2",
    ]
    return {key: metrics[key] for key in keys if key in metrics}


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    return sum(actual == predicted for actual, predicted in zip(y_true, y_pred, strict=True)) / len(y_true)


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    scores = []
    for label in labels:
        scores.append(label_f1(y_true, y_pred, label))
    return sum(scores) / len(scores) if scores else 0.0


def label_f1(y_true: list[str], y_pred: list[str], label: str) -> float:
    tp = sum(actual == label and predicted == label for actual, predicted in zip(y_true, y_pred, strict=True))
    fp = sum(actual != label and predicted == label for actual, predicted in zip(y_true, y_pred, strict=True))
    fn = sum(actual == label and predicted != label for actual, predicted in zip(y_true, y_pred, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def log_loss(y_true: list[str], distribution: dict[str, float]) -> float:
    eps = 1e-15
    total = 0.0
    for actual in y_true:
        probability = min(max(distribution.get(actual, 0.0), eps), 1.0 - eps)
        total -= math.log(probability)
    return total / len(y_true)


def log_loss_from_probability_maps(
    y_true: list[str], probability_maps: list[dict[str, float]]
) -> float:
    eps = 1e-15
    total = 0.0
    for actual, probability_map in zip(y_true, probability_maps, strict=True):
        probability = min(max(probability_map.get(actual, 0.0), eps), 1.0 - eps)
        total -= math.log(probability)
    return total / len(y_true)


def root_mean_squared_error(y_true: list[float], y_pred: list[float]) -> float:
    return math.sqrt(
        sum((actual - predicted) ** 2 for actual, predicted in zip(y_true, y_pred, strict=True))
        / len(y_true)
    )


def mean_absolute_error(y_true: list[float], y_pred: list[float]) -> float:
    return sum(abs(actual - predicted) for actual, predicted in zip(y_true, y_pred, strict=True)) / len(y_true)


def r2_score(y_true: list[float], y_pred: list[float]) -> float:
    mean_true = sum(y_true) / len(y_true)
    total_sum_squares = sum((actual - mean_true) ** 2 for actual in y_true)
    if total_sum_squares == 0:
        return 0.0
    residual_sum_squares = sum(
        (actual - predicted) ** 2 for actual, predicted in zip(y_true, y_pred, strict=True)
    )
    return 1.0 - residual_sum_squares / total_sum_squares


def binary_roc_auc(y_true: list[int], scores: list[float]) -> float:
    positives = sum(y_true)
    negatives = len(y_true) - positives
    if positives == 0 or negatives == 0:
        return 0.5
    ranked = sorted(zip(scores, y_true, strict=True), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ranked):
        next_index = index + 1
        while next_index < len(ranked) and ranked[next_index][0] == ranked[index][0]:
            next_index += 1
        average_rank = (index + 1 + next_index) / 2
        rank_sum += average_rank * sum(label for _, label in ranked[index:next_index])
        index = next_index
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def average_precision(y_true: list[int], scores: list[float]) -> float:
    positives = sum(y_true)
    if positives == 0:
        return 0.0
    if len(set(scores)) == 1:
        return positives / len(y_true)
    ordered = sorted(zip(scores, y_true, strict=True), key=lambda item: item[0], reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ordered, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positives


def render_baseline_report(
    *,
    project: Project,
    spec: EvaluationSpec,
    split: SplitManifest,
    baseline_name: str,
    metrics: dict[str, Any],
    predictions: list[dict[str, Any]],
    baseline_plan: dict[str, Any] | None = None,
    feature_recipe: dict[str, Any] | None = None,
    baseline_strategy_plan: dict[str, Any] | None = None,
) -> str:
    summary = loads_json(split.summary_json, {})
    sanity_floor = metrics.get("sanity_floor")
    plan = baseline_plan or {}
    recipe = feature_recipe or {}
    strategy_plan = baseline_strategy_plan or {}
    raw_selected_execution = strategy_plan.get("selected_execution")
    selected_execution: dict[str, Any] = raw_selected_execution if isinstance(raw_selected_execution, dict) else {}
    lines = [
        "# Baseline Report",
        "",
        f"- Project: {project.name}",
        f"- Baseline: {baseline_name}",
        f"- Model family: {metrics.get('model_family', 'fallback')}",
        f"- EvaluationSpec: {spec.id}",
        f"- SplitManifest: {split.id}",
        f"- Split summary: {summary.get('counts', {})}",
        f"- Primary metric: {metrics['primary_metric_name']} = {metrics['primary_metric_value']:.6f}",
        f"- Valid predictions: {len(predictions)}",
        f"- Numeric features: {metrics.get('numeric_feature_count', '-')}",
        f"- Categorical features: {metrics.get('categorical_feature_count', '-')}",
        f"- Text features: {metrics.get('text_feature_count', '-')}",
        "",
        "## Baseline Plan",
        f"- Candidate model: {plan.get('candidate_model', baseline_name)}",
        f"- Numeric columns: {', '.join(parse_string_list(plan.get('numeric_columns', []))) or 'none'}",
        f"- Categorical columns: {', '.join(parse_string_list(plan.get('categorical_columns', []))) or 'none'}",
        f"- Text columns: {', '.join(parse_string_list(plan.get('text_columns', []))) or 'none'}",
        f"- Datetime columns: {', '.join(parse_string_list(plan.get('datetime_columns', []))) or 'none'}",
        f"- Identifier columns ignored: {', '.join(parse_string_list(plan.get('identifier_columns', []))) or 'none'}",
        f"- Active text columns: {', '.join(parse_string_list(recipe.get('active_text_columns', []))) or 'none'}",
        "",
        "## Strategy Plan",
        f"- Selected execution: {selected_execution.get('baseline_type', baseline_name)}",
        f"- Candidate strategies: {len(strategy_plan.get('candidate_strategies', [])) if isinstance(strategy_plan.get('candidate_strategies'), list) else 0}",
        f"- Next agent tasks: {len(strategy_plan.get('next_agent_tasks', [])) if isinstance(strategy_plan.get('next_agent_tasks'), list) else 0}",
        "",
        "## Metrics",
    ]
    for key, value in sorted(metrics.items()):
        if isinstance(value, float):
            lines.append(f"- {key}: {value:.6f}")
        else:
            lines.append(f"- {key}: {value}")
    if isinstance(sanity_floor, dict):
        lines.extend(["", "## Sanity Floor"])
        for key, value in sorted(sanity_floor.items()):
            if isinstance(value, float):
                lines.append(f"- {key}: {value:.6f}")
            else:
                lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Sanity Check",
            "This baseline uses only the approved EvaluationSpec, SplitManifest, and train split data. It is a first floor for later agent-produced models and validates that the harness can drive a repeatable run without external experiment tooling.",
        ]
    )
    return "\n".join(lines)


def predictions_to_csv(predictions: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = ["row_index", "split", "target", "prediction", "score"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in predictions:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue()


def store_model_package_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str,
    run_id: str,
    package: dict[str, Any],
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project_id, "model_package", f"model_package_{run_id}")
    buffer = io.BytesIO()
    joblib.dump(package, buffer)
    buffer.seek(0)
    artifact_dir, stored, content_hash = store.store_stream(
        org_id="local-org",
        project_id=project_id,
        asset_type="model_package",
        name=f"model_package_{run_id}",
        version=version,
        filename="model_package.joblib",
        stream=buffer,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type="model_package",
        name=f"model_package_{run_id}",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path), "schema_version": "model_package.v1"},
        version=version,
    )


def create_model_version(
    db: Session,
    *,
    project: Project,
    run: ExperimentRun,
    dataset: DatasetSnapshot,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
    model_artifact: Artifact,
    baseline_type: str,
    model_family: str,
    task_type: str,
    metrics: dict[str, Any],
    params: dict[str, Any],
) -> ModelVersion:
    model_name = "baseline_model"
    metric_value = metrics.get("primary_metric_value")
    model_version = ModelVersion(
        id=new_id("model"),
        project_id=project.id,
        experiment_run_id=run.id,
        dataset_snapshot_id=dataset.id,
        evaluation_spec_id=evaluation_spec.id,
        split_manifest_id=split_manifest.id,
        artifact_id=model_artifact.id,
        name=model_name,
        version=next_model_version_number(db, project.id, model_name),
        model_family=model_family,
        model_type=baseline_type,
        task_type=task_type,
        target_column=project.target_column,
        primary_metric_name=str(metrics.get("primary_metric_name")) if metrics.get("primary_metric_name") else None,
        primary_metric_value=float(metric_value) if isinstance(metric_value, int | float) else None,
        metrics_json=dumps_json(metrics),
        params_json=dumps_json(params),
        status="created",
    )
    db.add(model_version)
    db.flush()
    return model_version


def next_model_version_number(db: Session, project_id: str, name: str) -> int:
    current = db.scalar(
        select(func.max(ModelVersion.version)).where(
            ModelVersion.project_id == project_id,
            ModelVersion.name == name,
        )
    )
    return int(current or 0) + 1


def store_json_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    filename: str,
    payload: Any,
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project_id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_json(
        org_id="local-org",
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        payload=payload,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
    )


def store_text_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    filename: str,
    text: str,
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project_id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_text(
        org_id="local-org",
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        text=text,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
    )


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
