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


@dataclass(frozen=True)
class BaselineResult:
    run: ExperimentRun
    artifact_ids: list[str]
    metrics: dict[str, Any]
    model_version_id: str | None = None


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
    if task_type == "regression":
        metrics, predictions = run_regression_baseline(
            rows,
            evaluation_spec.primary_metric,
            target_column=project.target_column,
            excluded_columns=excluded_columns,
            baseline_plan=baseline_plan,
        )
        baseline_name = str(metrics["baseline_type"])
    else:
        metrics, predictions = run_classification_baseline(
            rows,
            evaluation_spec.primary_metric,
            target_column=project.target_column,
            excluded_columns=excluded_columns,
            baseline_plan=baseline_plan,
        )
        baseline_name = str(metrics["baseline_type"])
    model_package_payload = metrics.pop("_model_package_payload", None)
    feature_recipe = metrics.pop("feature_recipe", build_fallback_feature_recipe(baseline_name))
    baseline_plan["selected_baseline_type"] = baseline_name
    baseline_plan["execution_status"] = "succeeded"

    report = render_baseline_report(
        project=project,
        spec=evaluation_spec,
        split=split_manifest,
        baseline_name=baseline_name,
        metrics=metrics,
        predictions=predictions,
        baseline_plan=baseline_plan,
        feature_recipe=feature_recipe,
    )
    run = ExperimentRun(
        id=new_id("run"),
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        evaluation_spec_id=evaluation_spec.id,
        split_manifest_id=split_manifest.id,
        runner_type="local_baseline",
        status="succeeded",
        started_at=utc_now(),
        ended_at=utc_now(),
        params_json=dumps_json(
            {
                "baseline": baseline_name,
                "target_column": project.target_column,
                "excluded_columns": excluded_columns,
            }
        ),
        metrics_json=dumps_json(metrics),
        summary_md=report,
    )
    db.add(run)
    db.flush()

    model_artifact: Artifact | None = None
    model_version: ModelVersion | None = None
    if isinstance(model_package_payload, ModelPackagePayload):
        model_package_payload.package["baseline_plan"] = baseline_plan
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
        )
    except Exception as linear_exc:
        metrics, predictions = run_dummy_classification_baseline(rows, primary_metric)
        metrics["model_baseline_attempted"] = True
        metrics["model_baseline_error"] = str(linear_exc)
        metrics["fallback_reason"] = "xgboost_and_logistic_regression_failed"
        metrics["feature_recipe"] = build_fallback_feature_recipe("majority_classifier")
        return metrics, predictions


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


def run_logistic_regression_baseline(
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

    y_train = [str(row[TARGET_VALUE_COLUMN]) for row in train_rows]
    y_true = [str(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    if len(set(y_train)) < 2:
        raise ValueError("Logistic regression requires at least two train classes")

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
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        pipeline.fit(x_train, y_train)

    predicted = [str(value) for value in pipeline.predict(x_valid)]
    classifier = pipeline.named_steps["classifier"]
    classes = [str(value) for value in classifier.classes_]
    probabilities = pipeline.predict_proba(x_valid)
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
    metrics: dict[str, Any] = {
        "baseline_type": "logistic_regression",
        "model_baseline_attempted": True,
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "train_count": len(y_train),
        "feature_count": len(pipeline.named_steps["features"].get_feature_names_out()),
        "excluded_columns": excluded_columns,
        "accuracy": accuracy(y_true, predicted),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss_from_probability_maps(y_true, probability_maps),
        "sanity_floor": compact_sanity_metrics(dummy_metrics),
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
    numeric_columns = [item["name"] for item in column_profiles if item["role"] == "numeric"]
    categorical_columns = [item["name"] for item in column_profiles if item["role"] == "categorical"]
    text_columns = [item["name"] for item in column_profiles if item["role"] == "text"]
    datetime_columns = [item["name"] for item in column_profiles if item["role"] == "datetime"]
    identifier_columns = [item["name"] for item in column_profiles if item["role"] == "identifier"]
    ignored_columns = [item["name"] for item in column_profiles if item["role"] == "ignored"]

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
) -> str:
    summary = loads_json(split.summary_json, {})
    sanity_floor = metrics.get("sanity_floor")
    plan = baseline_plan or {}
    recipe = feature_recipe or {}
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
