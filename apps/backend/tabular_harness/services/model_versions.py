from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    ModelVersion,
    SplitManifest,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.baseline import (
    ROW_INDEX_COLUMN,
    SPLIT_VALUE_COLUMN,
    TARGET_VALUE_COLUMN,
    accuracy,
    augment_rows_for_baseline_plan,
    average_precision,
    binary_roc_auc,
    label_f1,
    load_split_rows,
    log_loss_from_probability_maps,
    macro_f1,
    mean_absolute_error,
    metric_value,
    predictions_to_csv,
    r2_score,
    root_mean_squared_error,
)


@dataclass(frozen=True)
class ModelValidationResult:
    model_version: ModelVersion
    artifact_ids: list[str]
    metrics: dict[str, Any]
    report_md: str


def validate_model_version_package(
    db: Session,
    *,
    store: LocalArtifactStore,
    model_version: ModelVersion,
) -> ModelValidationResult:
    model_artifact = db.get(Artifact, model_version.artifact_id)
    dataset = db.get(DatasetSnapshot, model_version.dataset_snapshot_id)
    split_manifest = db.get(SplitManifest, model_version.split_manifest_id)
    evaluation_spec = db.get(EvaluationSpec, model_version.evaluation_spec_id)
    run = db.get(ExperimentRun, model_version.experiment_run_id)
    if model_artifact is None:
        raise ValueError("Model package artifact not found")
    if dataset is None or split_manifest is None or evaluation_spec is None:
        raise ValueError("ModelVersion is missing dataset, split, or evaluation context")
    if not model_version.target_column:
        raise ValueError("ModelVersion target_column is required for validation replay")

    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    split_artifact = db.get(Artifact, split_manifest.artifact_id)
    if dataset_artifact is None or split_artifact is None:
        raise ValueError("Dataset or SplitManifest artifact not found")

    package = load_model_package(artifact_primary_path(model_artifact))
    baseline_plan = package_dict(package.get("baseline_plan"))
    rows = load_split_rows(
        dataset_path=artifact_primary_path(dataset_artifact),
        split_path=artifact_primary_path(split_artifact),
        target_column=model_version.target_column,
    )
    feature_rows = augment_rows_for_baseline_plan(rows, baseline_plan)
    valid_rows = [
        row
        for row in feature_rows
        if row[SPLIT_VALUE_COLUMN] == "valid" and row[TARGET_VALUE_COLUMN] is not None
    ]
    if not valid_rows:
        raise ValueError("Model package validation requires non-empty validation rows")

    metrics, predictions = replay_predictions(
        package,
        valid_rows,
        primary_metric=model_version.primary_metric_name or "primary_metric_value",
    )
    stored_metrics = loads_json(model_version.metrics_json, {})
    metric_deltas = compare_numeric_metrics(stored_metrics, metrics)
    metrics["stored_primary_metric_value"] = model_version.primary_metric_value
    metrics["metric_deltas"] = metric_deltas
    metrics["max_abs_metric_delta"] = max((abs(value) for value in metric_deltas.values()), default=0.0)
    metrics["validation_status"] = "passed" if metrics["max_abs_metric_delta"] <= 1e-9 else "warning"

    report = render_validation_report(
        model_version=model_version,
        run=run,
        model_artifact=model_artifact,
        metrics=metrics,
        stored_metrics=stored_metrics,
        predictions=predictions,
    )
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=model_version.project_id,
        asset_type="model_validation_report",
        name=f"model_validation_report_{model_version.id}",
        filename="model_validation_report.md",
        text=report,
        metadata={"model_version_id": model_version.id, "experiment_run_id": model_version.experiment_run_id},
    )
    metrics_artifact = store_json_artifact(
        db,
        store,
        project_id=model_version.project_id,
        asset_type="model_validation_metrics",
        name=f"model_validation_metrics_{model_version.id}",
        filename="model_validation_metrics.json",
        payload=metrics,
        metadata={"model_version_id": model_version.id, "experiment_run_id": model_version.experiment_run_id},
    )
    predictions_artifact = store_text_artifact(
        db,
        store,
        project_id=model_version.project_id,
        asset_type="prediction_replay",
        name=f"prediction_replay_{model_version.id}",
        filename="prediction_replay_valid.csv",
        text=predictions_to_csv(predictions),
        metadata={"model_version_id": model_version.id, "split_manifest_id": split_manifest.id},
    )
    for artifact in (report_artifact, metrics_artifact, predictions_artifact):
        create_lineage_edge(
            db,
            project_id=model_version.project_id,
            from_asset_type="model_version",
            from_asset_id=model_version.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="validates_with",
        )
    return ModelValidationResult(
        model_version=model_version,
        artifact_ids=[report_artifact.id, metrics_artifact.id, predictions_artifact.id],
        metrics=metrics,
        report_md=report,
    )


def load_model_package(path: Path) -> dict[str, Any]:
    package = joblib.load(path)
    if not isinstance(package, dict):
        raise ValueError("Model package must be a dictionary")
    if package.get("schema_version") != "model_package.v1":
        raise ValueError("Unsupported model package schema_version")
    return package


def replay_predictions(
    package: dict[str, Any],
    valid_rows: list[dict[str, Any]],
    *,
    primary_metric: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prediction_kind = package.get("prediction_kind")
    feature_builder = package.get("feature_builder")
    model = package.get("model")
    if feature_builder is None or model is None:
        raise ValueError("Model package is missing model or feature_builder")
    x_valid = feature_builder.transform(valid_rows)
    if prediction_kind == "classification":
        return replay_classification_predictions(
            package,
            valid_rows,
            x_valid=x_valid,
            primary_metric=primary_metric,
        )
    if prediction_kind == "regression":
        return replay_regression_predictions(
            package,
            valid_rows,
            x_valid=x_valid,
            primary_metric=primary_metric,
        )
    raise ValueError(f"Unsupported prediction_kind: {prediction_kind}")


def replay_classification_predictions(
    package: dict[str, Any],
    valid_rows: list[dict[str, Any]],
    *,
    x_valid: Any,
    primary_metric: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model = package["model"]
    label_encoder = package.get("label_encoder")
    classes = [str(value) for value in package.get("classes") or []]
    if label_encoder is None or not classes:
        raise ValueError("Classification package is missing label_encoder or classes")
    predicted_encoded = model.predict(x_valid)
    predicted = [str(value) for value in label_encoder.inverse_transform(predicted_encoded)]
    probabilities = model.predict_proba(x_valid)
    probability_maps = [
        {classes[index]: float(probability) for index, probability in enumerate(row)}
        for row in probabilities
    ]
    y_true = [str(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    labels = sorted({*classes, *y_true, *predicted})
    positive_label = labels[-1] if len(labels) == 2 else None
    positive_scores: list[float] = []
    predictions: list[dict[str, Any]] = []
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
    macro_f1_value = macro_f1(y_true, predicted, labels)
    metrics: dict[str, Any] = {
        "baseline_type": "model_package_replay",
        "prediction_kind": "classification",
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "accuracy": accuracy(y_true, predicted),
        "macro_f1": macro_f1_value,
        "f1": macro_f1_value,
        "log_loss": log_loss_from_probability_maps(y_true, probability_maps),
    }
    if positive_label:
        y_binary = [1 if value == positive_label else 0 for value in y_true]
        metrics["positive_label"] = positive_label
        metrics["f1"] = label_f1(y_true, predicted, positive_label)
        metrics["roc_auc"] = binary_roc_auc(y_binary, positive_scores)
        metrics["pr_auc"] = average_precision(y_binary, positive_scores)
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, metrics["accuracy"])
    return metrics, predictions


def replay_regression_predictions(
    package: dict[str, Any],
    valid_rows: list[dict[str, Any]],
    *,
    x_valid: Any,
    primary_metric: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model = package["model"]
    predicted = [float(value) for value in model.predict(x_valid)]
    y_true = [float(row[TARGET_VALUE_COLUMN]) for row in valid_rows]
    predictions = [
        {
            "row_index": row[ROW_INDEX_COLUMN],
            "split": "valid",
            "target": actual,
            "prediction": prediction,
        }
        for row, actual, prediction in zip(valid_rows, y_true, predicted, strict=True)
    ]
    rmse_value = root_mean_squared_error(y_true, predicted)
    mae_value = mean_absolute_error(y_true, predicted)
    r2_value = r2_score(y_true, predicted)
    metrics: dict[str, Any] = {
        "baseline_type": "model_package_replay",
        "prediction_kind": "regression",
        "primary_metric_name": primary_metric,
        "valid_count": len(y_true),
        "rmse": rmse_value,
        "mae": mae_value,
        "r2": r2_value,
    }
    metrics["primary_metric_value"] = metric_value(metrics, primary_metric, rmse_value)
    return metrics, predictions


def compare_numeric_metrics(stored_metrics: dict[str, Any], replay_metrics: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for key, replay_value in replay_metrics.items():
        stored_value = stored_metrics.get(key)
        if isinstance(stored_value, int | float) and isinstance(replay_value, int | float):
            deltas[key] = float(replay_value) - float(stored_value)
    return deltas


def render_validation_report(
    *,
    model_version: ModelVersion,
    run: ExperimentRun | None,
    model_artifact: Artifact,
    metrics: dict[str, Any],
    stored_metrics: dict[str, Any],
    predictions: list[dict[str, Any]],
) -> str:
    lines = [
        "# Model Package Validation Report",
        "",
        f"- ModelVersion: {model_version.id}",
        f"- Model package artifact: {model_artifact.id}",
        f"- Source run: {run.id if run else model_version.experiment_run_id}",
        f"- Validation status: {metrics['validation_status']}",
        f"- Max absolute metric delta: {metrics['max_abs_metric_delta']:.12f}",
        f"- Replayed predictions: {len(predictions)}",
        "",
        "## Replayed Metrics",
    ]
    for key, value in sorted(metrics.items()):
        if isinstance(value, float):
            lines.append(f"- {key}: {value:.12f}")
        else:
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Stored Metrics"])
    for key, value in sorted(stored_metrics.items()):
        if isinstance(value, float):
            lines.append(f"- {key}: {value:.12f}")
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


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


def package_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
