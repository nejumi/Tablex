from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Artifact, Evidence, ExperimentRun, Insight
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.baseline import (
    SPLIT_VALUE_COLUMN,
    TARGET_VALUE_COLUMN,
    accuracy,
    augment_rows_for_baseline_plan,
    average_precision,
    binary_roc_auc,
    label_f1,
    log_loss_from_probability_maps,
    macro_f1,
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)
from tabular_harness.services.diagnostics import (
    build_diagnostics,
    diagnostics_summary,
    latest_prediction_artifact,
    load_prediction_csv,
    require_artifact,
    require_dataset,
    require_project,
    require_spec,
    require_split,
)

LOSS_METRICS = {"rmse", "mae", "log_loss", "mape", "mean_absolute_error"}
MAX_PERMUTATION_ROWS = 2000
MAX_PERMUTATION_FEATURES = 30
MAX_DENSE_CELLS = 2_500_000


@dataclass(frozen=True)
class ModelDiagnosticsArtifactsResult:
    run: ExperimentRun
    artifact_ids: list[str]
    diagnostics: dict[str, Any]
    insight_id: str
    evidence_id: str


def materialize_model_diagnostics_artifacts(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> ModelDiagnosticsArtifactsResult:
    project = require_project(db, run.project_id)
    if not run.dataset_snapshot_id or not run.evaluation_spec_id or not run.split_manifest_id:
        raise ValueError("Run must reference DatasetSnapshot, EvaluationSpec, and SplitManifest")
    if not project.target_column:
        raise ValueError("Project target_column is required for model diagnostics artifacts")
    dataset = require_dataset(db, run.dataset_snapshot_id)
    spec = require_spec(db, run.evaluation_spec_id)
    split = require_split(db, run.split_manifest_id)
    dataset_artifact = require_artifact(db, dataset.artifact_id)
    split_artifact = require_artifact(db, split.artifact_id)
    predictions_artifact = latest_prediction_artifact(db, run)
    if predictions_artifact is None:
        raise ValueError("Prediction output artifact not found for run")

    split_rows = load_split_rows_for_diagnostics(
        dataset_path=artifact_primary_path(dataset_artifact),
        split_path=artifact_primary_path(split_artifact),
        target_column=project.target_column,
    )
    predictions = load_prediction_csv(predictions_artifact)
    evaluation_diagnostics_artifact = latest_run_artifact(db, run, "evaluation_diagnostics")
    evaluation_diagnostics = load_json_artifact(evaluation_diagnostics_artifact) if evaluation_diagnostics_artifact else None
    if evaluation_diagnostics is None:
        evaluation_diagnostics = build_diagnostics(
            run=run,
            project=project,
            evaluation_spec=spec,
            split_manifest=split,
            split_rows=split_rows,
            predictions=predictions,
        )
    model_package_artifact = latest_run_artifact(db, run, "model_package")
    feature_recipe_artifact = latest_run_artifact(db, run, "feature_recipe")
    metrics = loads_json(run.metrics_json, {})
    model_package = load_model_package(model_package_artifact)

    native_importance = build_native_feature_importance(model_package)
    permutation_importance = build_permutation_importance(
        model_package=model_package,
        split_rows=split_rows,
        metrics=metrics,
        task_kind=str(evaluation_diagnostics.get("task_kind") or "classification"),
    )
    prediction_review = build_prediction_review(
        predictions=predictions,
        metrics=metrics,
        task_kind=str(evaluation_diagnostics.get("task_kind") or "classification"),
    )
    diagnostics = {
        "schema_version": "model_diagnostics_artifact_pack.v1",
        "run_id": run.id,
        "project_id": project.id,
        "model_version_id": run.model_version_id,
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
        "task_kind": evaluation_diagnostics.get("task_kind"),
        "availability": diagnostics_availability(
            native_importance=native_importance,
            permutation_importance=permutation_importance,
            prediction_review=prediction_review,
            evaluation_diagnostics=evaluation_diagnostics,
        ),
        "source_artifacts": {
            "model_package": artifact_ref(model_package_artifact),
            "prediction_output": artifact_ref(predictions_artifact),
            "evaluation_diagnostics": artifact_ref(evaluation_diagnostics_artifact),
            "feature_recipe": artifact_ref(feature_recipe_artifact),
            "dataset_snapshot": artifact_ref(dataset_artifact),
            "split_manifest": artifact_ref(split_artifact),
        },
        "native_feature_importance": native_importance,
        "permutation_importance": permutation_importance,
        "prediction_review": prediction_review,
        "evaluation_diagnostics_summary": {
            "summary": evaluation_diagnostics.get("summary", {}),
            "slice_metric_count": len(list_value(evaluation_diagnostics.get("slice_metrics"))),
            "worst_example_count": len(list_value(evaluation_diagnostics.get("worst_examples"))),
            "sanity_checks": evaluation_diagnostics.get("sanity_checks", {}),
        },
        "slice_metrics": list_value(evaluation_diagnostics.get("slice_metrics"))[:40],
        "worst_examples": list_value(evaluation_diagnostics.get("worst_examples"))[:20],
        "interpretation": model_diagnostics_interpretation(
            native_importance=native_importance,
            permutation_importance=permutation_importance,
            prediction_review=prediction_review,
            evaluation_diagnostics=evaluation_diagnostics,
        ),
        "limitations": diagnostics_limitations(native_importance, permutation_importance),
        "policy": {
            "split_manifest_respected": True,
            "evaluation_spec_modified": False,
            "secrets_materialized": False,
            "permutation_sample_policy": (
                f"valid split only, deterministic bounded sample up to {MAX_PERMUTATION_ROWS} rows "
                f"and {MAX_PERMUTATION_FEATURES} transformed features"
            ),
        },
    }
    feature_importance_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="feature_importance",
        name=f"feature_importance_{run.id}",
        filename="feature_importance.json",
        payload=native_importance,
        metadata={
            "project_id": project.id,
            "run_id": run.id,
            "model_version_id": run.model_version_id,
            "status": native_importance["status"],
        },
    )
    permutation_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="permutation_importance",
        name=f"permutation_importance_{run.id}",
        filename="permutation_importance.json",
        payload=permutation_importance,
        metadata={
            "project_id": project.id,
            "run_id": run.id,
            "model_version_id": run.model_version_id,
            "status": permutation_importance["status"],
            "sample_row_count": permutation_importance.get("sample_row_count"),
        },
    )
    diagnostics_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="model_diagnostics_artifact_pack",
        name=f"model_diagnostics_artifact_pack_{run.id}",
        filename="model_diagnostics_artifact_pack.json",
        payload=diagnostics,
        metadata={
            "project_id": project.id,
            "run_id": run.id,
            "model_version_id": run.model_version_id,
            "feature_importance_status": native_importance["status"],
            "permutation_importance_status": permutation_importance["status"],
        },
    )
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="model_diagnostics_artifact_report",
        name=f"model_diagnostics_artifact_report_{run.id}",
        filename="model_diagnostics_artifact_report.md",
        text=render_model_diagnostics_artifact_report(diagnostics),
        metadata={"project_id": project.id, "run_id": run.id, "model_version_id": run.model_version_id},
    )
    visualization_spec = build_model_diagnostics_visualization_spec(diagnostics)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"model_diagnostics_visualization_{run.id}",
        filename="model_diagnostics_visualization.json",
        payload=visualization_spec,
        metadata={"project_id": project.id, "run_id": run.id, "chart_type": visualization_spec["chart_type"]},
    )
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="model_diagnostics_artifact_pack",
        summary=model_diagnostics_summary(diagnostics),
        strength="strong" if permutation_importance["status"] == "ready" else "medium",
        source_artifact_id=diagnostics_artifact.id,
        source_run_id=run.id,
        metadata_json=dumps_json({"run_id": run.id, "model_version_id": run.model_version_id}),
    )
    db.add(evidence)
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="model_diagnostics_artifact_pack",
        title=f"Model diagnostics artifacts for {run.id}",
        summary=evidence.summary,
        severity="info" if permutation_importance["status"] == "ready" else "warning",
        confidence=0.82 if permutation_importance["status"] == "ready" else 0.66,
        status="open",
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "experiment_run", "asset_id": run.id},
                {"asset_type": "model_package", "asset_id": model_package_artifact.id}
                if model_package_artifact
                else {"asset_type": "model_package", "asset_id": None},
                {"asset_type": "prediction_output", "asset_id": predictions_artifact.id},
                {"asset_type": "evaluation_diagnostics", "asset_id": evaluation_diagnostics_artifact.id}
                if evaluation_diagnostics_artifact
                else {"asset_type": "evaluation_diagnostics", "asset_id": None},
            ]
        ),
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=diagnostics_artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    db.flush()

    produced_artifacts = [
        feature_importance_artifact,
        permutation_artifact,
        diagnostics_artifact,
        report_artifact,
        visualization_artifact,
    ]
    for artifact in produced_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="diagnoses",
        )
    for source in [model_package_artifact, predictions_artifact, evaluation_diagnostics_artifact, feature_recipe_artifact]:
        if source is None:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="informs",
        )
    return ModelDiagnosticsArtifactsResult(
        run=run,
        artifact_ids=[artifact.id for artifact in produced_artifacts],
        diagnostics=diagnostics,
        insight_id=insight.id,
        evidence_id=evidence.id,
    )


def load_split_rows_for_diagnostics(*, dataset_path: Any, split_path: Any, target_column: str) -> list[dict[str, Any]]:
    from tabular_harness.services.baseline import load_split_rows

    return load_split_rows(dataset_path=dataset_path, split_path=split_path, target_column=target_column)


def latest_run_artifact(db: Session, run: ExperimentRun, asset_type: str) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == run.project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("run_id") == run.id:
            return artifact
    return None


def load_json_artifact(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return None
    return payload if isinstance(payload, dict) else None


def load_model_package(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    try:
        payload = joblib.load(artifact_primary_path(artifact))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def build_native_feature_importance(model_package: dict[str, Any] | None) -> dict[str, Any]:
    if not model_package:
        return blocked_payload(
            "feature_importance.v1",
            "missing_model_package",
            "No model package artifact is available for this run.",
        )
    model = model_package.get("model")
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return blocked_payload(
            "feature_importance.v1",
            "model_does_not_expose_native_importance",
            "The stored model does not expose feature_importances_.",
        )
    feature_names = feature_names_from_package(model_package)
    rows = []
    for index, value in enumerate(list(importances)):
        name = feature_names[index] if index < len(feature_names) else f"feature_{index}"
        importance = finite_float(value)
        rows.append(
            {
                "feature_index": index,
                "feature_name": name,
                "source_column": source_column_for_feature(name),
                "family": feature_family_for_feature(name, model_package),
                "importance": importance,
            }
        )
    if not any(row.get("importance") is not None for row in rows):
        return blocked_payload(
            "feature_importance.v1",
            "native_importance_values_not_finite",
            "The stored model exposes feature_importances_, but none of the values are finite.",
            feature_count=len(rows),
        )
    rows.sort(key=lambda item: finite_float(item.get("importance")) or 0.0, reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {
        "schema_version": "feature_importance.v1",
        "status": "ready",
        "method": "model_native_feature_importances",
        "feature_count": len(rows),
        "top_features": rows[:60],
        "family_importance": family_importance(rows),
    }


def build_permutation_importance(
    *,
    model_package: dict[str, Any] | None,
    split_rows: list[dict[str, Any]],
    metrics: dict[str, Any],
    task_kind: str,
) -> dict[str, Any]:
    if not model_package:
        return blocked_payload(
            "permutation_importance.v1",
            "missing_model_package",
            "No model package artifact is available, so Tablex cannot rerun the model on permuted validation rows.",
        )
    model = model_package.get("model")
    builder = model_package.get("feature_builder")
    baseline_plan = model_package.get("baseline_plan")
    if model is None or builder is None or not isinstance(baseline_plan, dict):
        return blocked_payload(
            "permutation_importance.v1",
            "incomplete_model_package",
            "The model package is missing model, feature_builder, or baseline_plan.",
        )
    valid_rows = [
        row
        for row in split_rows
        if row.get(SPLIT_VALUE_COLUMN) == "valid" and row.get(TARGET_VALUE_COLUMN) is not None
    ]
    if not valid_rows:
        return blocked_payload(
            "permutation_importance.v1",
            "missing_valid_rows",
            "No validation rows were available in the SplitManifest.",
        )
    sample_rows = deterministic_sample(valid_rows, MAX_PERMUTATION_ROWS)
    augmented_rows = augment_rows_for_baseline_plan(sample_rows, baseline_plan)
    matrix = builder.transform(augmented_rows)
    shape = getattr(matrix, "shape", (len(augmented_rows), 0))
    row_count, feature_count = int(shape[0]), int(shape[1])
    if row_count * feature_count > MAX_DENSE_CELLS:
        return blocked_payload(
            "permutation_importance.v1",
            "feature_matrix_too_large_for_inline_permutation",
            f"Bounded permutation would require {row_count * feature_count:,} dense cells.",
            sample_row_count=row_count,
            feature_count=feature_count,
        )
    dense = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
    feature_names = feature_names_from_package(model_package)
    predictions = predict_with_matrix(model_package, dense, metrics=metrics, task_kind=task_kind)
    metric_name = str(metrics.get("primary_metric_name") or "accuracy")
    baseline_score = score_predictions(
        metric_name=metric_name,
        task_kind=task_kind,
        rows=augmented_rows,
        predictions=predictions,
    )
    if baseline_score is None:
        return blocked_payload(
            "permutation_importance.v1",
            "unsupported_metric_for_permutation",
            f"Metric {metric_name!r} could not be computed from stored prediction outputs.",
            sample_row_count=row_count,
            feature_count=feature_count,
        )
    candidate_indices = top_native_feature_indices(model_package, feature_count, MAX_PERMUTATION_FEATURES)
    rng = np.random.default_rng(42)
    rows = []
    higher_is_better = metric_name not in LOSS_METRICS
    for feature_index in candidate_indices:
        permuted = np.array(dense, copy=True)
        shuffled = np.array(permuted[:, feature_index], copy=True)
        rng.shuffle(shuffled)
        permuted[:, feature_index] = shuffled
        permuted_predictions = predict_with_matrix(model_package, permuted, metrics=metrics, task_kind=task_kind)
        permuted_score = score_predictions(
            metric_name=metric_name,
            task_kind=task_kind,
            rows=augmented_rows,
            predictions=permuted_predictions,
        )
        if permuted_score is None:
            continue
        importance = baseline_score - permuted_score if higher_is_better else permuted_score - baseline_score
        name = feature_names[feature_index] if feature_index < len(feature_names) else f"feature_{feature_index}"
        rows.append(
            {
                "feature_index": feature_index,
                "feature_name": name,
                "source_column": source_column_for_feature(name),
                "family": feature_family_for_feature(name, model_package),
                "baseline_metric_value": finite_float(baseline_score),
                "permuted_metric_value": finite_float(permuted_score),
                "importance_delta": finite_float(importance),
            }
        )
    rows.sort(key=lambda item: finite_float(item.get("importance_delta")) or 0.0, reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {
        "schema_version": "permutation_importance.v1",
        "status": "ready",
        "method": "bounded_valid_split_feature_permutation",
        "metric_name": metric_name,
        "higher_is_better": higher_is_better,
        "baseline_metric_value": finite_float(baseline_score),
        "sample_row_count": row_count,
        "feature_count": feature_count,
        "evaluated_feature_count": len(rows),
        "top_features": rows,
        "policy": {
            "split": "valid",
            "sample_seed": 42,
            "max_rows": MAX_PERMUTATION_ROWS,
            "max_features": MAX_PERMUTATION_FEATURES,
            "negative_importance_policy": "kept_as_signal_of_noise_or_sampling_variance",
        },
    }


def build_prediction_review(
    *,
    predictions: list[dict[str, Any]],
    metrics: dict[str, Any],
    task_kind: str,
) -> dict[str, Any]:
    if task_kind == "regression":
        return regression_prediction_review(predictions)
    return classification_prediction_review(predictions, metrics)


def classification_prediction_review(predictions: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    if not predictions:
        return blocked_payload("prediction_review.v1", "missing_predictions", "No predictions are available.")
    positive_label = str(metrics.get("positive_label") or sorted({str(row["target"]) for row in predictions})[-1])
    scored = [row for row in predictions if row.get("score") is not None]
    if not scored:
        return blocked_payload(
            "prediction_review.v1",
            "missing_scores",
            "Classification predictions do not include probability scores.",
        )
    return {
        "schema_version": "prediction_review.v1",
        "status": "ready",
        "positive_label": positive_label,
        "row_count": len(predictions),
        "scored_row_count": len(scored),
        "calibration_bins": calibration_bins(scored, positive_label),
        "threshold_review": threshold_review(scored, positive_label),
    }


def regression_prediction_review(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    if not predictions:
        return blocked_payload("prediction_review.v1", "missing_predictions", "No predictions are available.")
    errors = [
        float(row["prediction"]) - float(row["target"])
        for row in predictions
        if is_number(row.get("prediction")) and is_number(row.get("target"))
    ]
    abs_errors = [abs(value) for value in errors]
    return {
        "schema_version": "prediction_review.v1",
        "status": "ready",
        "row_count": len(errors),
        "residual_summary": {
            "mean_error": sum(errors) / len(errors) if errors else None,
            "mean_abs_error": sum(abs_errors) / len(abs_errors) if abs_errors else None,
            "max_abs_error": max(abs_errors) if abs_errors else None,
        },
    }


def calibration_bins(predictions: list[dict[str, Any]], positive_label: str) -> list[dict[str, Any]]:
    rows_by_bin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        score = float(row.get("score") or 0.0)
        bucket_start = min(9, max(0, int(score * 10))) / 10
        rows_by_bin[f"{bucket_start:.1f}-{bucket_start + 0.1:.1f}"].append(row)
    output = []
    for label in sorted(rows_by_bin):
        rows = rows_by_bin[label]
        positive_rate = sum(str(row["target"]) == positive_label for row in rows) / len(rows)
        output.append(
            {
                "bin": label,
                "count": len(rows),
                "average_score": sum(float(row.get("score") or 0.0) for row in rows) / len(rows),
                "positive_rate": positive_rate,
            }
        )
    return output


def threshold_review(predictions: list[dict[str, Any]], positive_label: str) -> list[dict[str, Any]]:
    scores = sorted(float(row.get("score") or 0.0) for row in predictions)
    quantile_thresholds = [scores[int((len(scores) - 1) * q)] for q in [0.5, 0.75, 0.9, 0.95]]
    thresholds = sorted({0.05, 0.1, 0.2, 0.3, 0.5, *quantile_thresholds})
    total_positive = sum(str(row["target"]) == positive_label for row in predictions)
    output = []
    for threshold in thresholds:
        predicted_positive = [row for row in predictions if float(row.get("score") or 0.0) >= threshold]
        true_positive = sum(str(row["target"]) == positive_label for row in predicted_positive)
        false_positive = len(predicted_positive) - true_positive
        false_negative = total_positive - true_positive
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        output.append(
            {
                "threshold": finite_float(threshold),
                "predicted_positive_count": len(predicted_positive),
                "predicted_positive_rate": len(predicted_positive) / len(predictions),
                "precision": precision,
                "recall": recall,
                "captured_positive_rate": recall,
            }
        )
    return output


def predict_with_matrix(
    model_package: dict[str, Any],
    matrix: Any,
    *,
    metrics: dict[str, Any],
    task_kind: str,
) -> dict[str, Any]:
    model = model_package["model"]
    if task_kind == "regression":
        return {"prediction": [float(value) for value in model.predict(matrix)]}
    encoded = model.predict(matrix)
    label_encoder = model_package.get("label_encoder")
    if label_encoder is not None:
        predicted = [str(value) for value in label_encoder.inverse_transform(encoded)]
    else:
        predicted = [str(value) for value in encoded]
    probability_maps = []
    scores = []
    classes = [str(value) for value in (model_package.get("classes") or sorted(set(predicted)))]
    positive_label = str(metrics.get("positive_label") or (classes[-1] if classes else "1"))
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(matrix)
        for row in probabilities:
            probability_map = {classes[index]: float(probability) for index, probability in enumerate(row)}
            probability_maps.append(probability_map)
            scores.append(float(probability_map.get(positive_label, 0.0)))
    else:
        scores = [1.0 if value == positive_label else 0.0 for value in predicted]
    return {
        "prediction": predicted,
        "score": scores,
        "probability_maps": probability_maps,
        "positive_label": positive_label,
    }


def score_predictions(
    *,
    metric_name: str,
    task_kind: str,
    rows: list[dict[str, Any]],
    predictions: dict[str, Any],
) -> float | None:
    if task_kind == "regression":
        reg_y_true = [float(row[TARGET_VALUE_COLUMN]) for row in rows]
        reg_y_pred = [float(value) for value in list_value(predictions.get("prediction"))]
        if not reg_y_true or len(reg_y_true) != len(reg_y_pred):
            return None
        if metric_name in {"mae", "mean_absolute_error"}:
            return mean_absolute_error(reg_y_true, reg_y_pred)
        if metric_name == "r2":
            return r2_score(reg_y_true, reg_y_pred)
        return root_mean_squared_error(reg_y_true, reg_y_pred)
    class_y_true = [str(row[TARGET_VALUE_COLUMN]) for row in rows]
    class_y_pred = [str(value) for value in list_value(predictions.get("prediction"))]
    if not class_y_true or len(class_y_true) != len(class_y_pred):
        return None
    labels = sorted({*class_y_true, *class_y_pred})
    scores = [float(value) for value in list_value(predictions.get("score"))]
    positive_label = str(predictions.get("positive_label") or (labels[-1] if labels else "1"))
    if metric_name == "pr_auc" and scores:
        return average_precision([1 if value == positive_label else 0 for value in class_y_true], scores)
    if metric_name == "roc_auc" and scores:
        return binary_roc_auc([1 if value == positive_label else 0 for value in class_y_true], scores)
    if metric_name == "f1":
        return label_f1(class_y_true, class_y_pred, positive_label)
    if metric_name == "macro_f1":
        return macro_f1(class_y_true, class_y_pred, labels)
    if metric_name == "log_loss" and predictions.get("probability_maps"):
        return log_loss_from_probability_maps(class_y_true, list_value(predictions.get("probability_maps")))
    return accuracy(class_y_true, class_y_pred)


def deterministic_sample(rows: list[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    if len(rows) <= max_rows:
        return rows
    rng = np.random.default_rng(42)
    indices = sorted(int(index) for index in rng.choice(len(rows), size=max_rows, replace=False))
    return [rows[index] for index in indices]


def top_native_feature_indices(model_package: dict[str, Any], feature_count: int, limit: int) -> list[int]:
    model = model_package.get("model")
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return list(range(min(feature_count, limit)))
    ranked = sorted(
        range(min(feature_count, len(importances))),
        key=lambda index: float(importances[index] or 0.0),
        reverse=True,
    )
    return ranked[:limit]


def feature_names_from_package(model_package: dict[str, Any]) -> list[str]:
    builder = model_package.get("feature_builder")
    if builder is None:
        return []
    names: list[str] = []
    names.extend(str(column) for column in getattr(builder, "numeric_columns", []))
    names.extend(str(column) for column in getattr(builder, "categorical_columns", []))
    text_vectorizers = getattr(builder, "text_vectorizers", {})
    if isinstance(text_vectorizers, dict):
        for column, vectorizer in text_vectorizers.items():
            try:
                names.extend(f"{column}::tfidf::{feature}" for feature in vectorizer.get_feature_names_out())
            except Exception:
                continue
    return names or ["constant_bias"]


def source_column_for_feature(feature_name: str) -> str:
    if "::tfidf::" in feature_name:
        return feature_name.split("::tfidf::", 1)[0]
    if "__" in feature_name:
        return feature_name.split("__", 1)[0]
    return feature_name


def feature_family_for_feature(feature_name: str, model_package: dict[str, Any]) -> str:
    builder = model_package.get("feature_builder")
    if "::tfidf::" in feature_name:
        return "text"
    if builder is not None and feature_name in set(str(column) for column in getattr(builder, "categorical_columns", [])):
        return "categorical"
    if any(token in feature_name for token in ["__day", "__month", "__year", "__hour", "__is_weekend"]):
        return "datetime"
    return "numeric"


def family_importance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        family = str(row.get("family") or "unknown")
        totals[family] += float(row.get("importance") or 0.0)
        counts[family] += 1
    output = [
        {"family": family, "importance": value, "feature_count": counts[family]}
        for family, value in totals.items()
    ]
    return sorted(output, key=lambda item: item["importance"], reverse=True)


def diagnostics_availability(
    *,
    native_importance: dict[str, Any],
    permutation_importance: dict[str, Any],
    prediction_review: dict[str, Any],
    evaluation_diagnostics: dict[str, Any],
) -> dict[str, str]:
    return {
        "native_feature_importance": str(native_importance.get("status") or "blocked"),
        "permutation_importance": str(permutation_importance.get("status") or "blocked"),
        "prediction_review": str(prediction_review.get("status") or "blocked"),
        "score_bins": "ready" if evaluation_diagnostics.get("bins") else "missing",
        "slice_metrics": "ready" if evaluation_diagnostics.get("slice_metrics") else "missing",
        "worst_examples": "ready" if evaluation_diagnostics.get("worst_examples") else "missing",
    }


def model_diagnostics_interpretation(
    *,
    native_importance: dict[str, Any],
    permutation_importance: dict[str, Any],
    prediction_review: dict[str, Any],
    evaluation_diagnostics: dict[str, Any],
) -> list[dict[str, str]]:
    interpretation = []
    top_native = list_value(native_importance.get("top_features"))
    if top_native:
        first = dict_value(top_native[0])
        interpretation.append(
            {
                "title": "Dominant model signal",
                "summary": f"Native model importance is led by {first.get('feature_name')} ({first.get('family')}).",
                "next_action": "Compare this with permutation importance before treating it as causal or stable.",
            }
        )
    if permutation_importance.get("status") == "ready" and list_value(permutation_importance.get("top_features")):
        first = dict_value(list_value(permutation_importance["top_features"])[0])
        interpretation.append(
            {
                "title": "Validated perturbation signal",
                "summary": f"Bounded permutation ranks {first.get('feature_name')} highest by metric degradation.",
                "next_action": "Inspect whether the feature is available at prediction time and stable across slices.",
            }
        )
    elif permutation_importance.get("status") != "ready":
        interpretation.append(
            {
                "title": "Permutation evidence gap",
                "summary": str(permutation_importance.get("message") or "Permutation importance is not available."),
                "next_action": "Run the controlled runner only when model package, split, and prediction artifacts are present.",
            }
        )
    if prediction_review.get("status") == "ready" and prediction_review.get("threshold_review"):
        interpretation.append(
            {
                "title": "Thresholds need decision context",
                "summary": "Score bins and threshold rows are ready, but deployment threshold must come from the project decision, not leaderboard rank.",
                "next_action": "Ask Codex to turn threshold rows into a cost-aware decision note when business costs are known.",
            }
        )
    if evaluation_diagnostics.get("slice_metrics"):
        interpretation.append(
            {
                "title": "Slice diagnostics are available",
                "summary": f"{len(list_value(evaluation_diagnostics.get('slice_metrics')))} slice metric rows are available for failure analysis.",
                "next_action": "Prioritize the lowest-performing high-count slices before proposing a new model.",
            }
        )
    return interpretation


def diagnostics_limitations(native_importance: dict[str, Any], permutation_importance: dict[str, Any]) -> list[str]:
    limitations = [
        "Feature importance is model behavior evidence, not causal evidence.",
        "All diagnostics must be read inside the approved EvaluationSpec and SplitManifest.",
    ]
    if native_importance.get("status") != "ready":
        limitations.append(str(native_importance.get("message") or "Native feature importance is unavailable."))
    if permutation_importance.get("status") != "ready":
        limitations.append(str(permutation_importance.get("message") or "Permutation importance is unavailable."))
    else:
        limitations.append("Permutation importance uses a deterministic bounded validation sample for UI-safe latency.")
    return limitations


def build_model_diagnostics_visualization_spec(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Model Diagnostics Artifacts",
        "chart_type": "model_diagnostics_artifact_pack",
        "views": [
            {
                "id": "native_feature_importance",
                "chart_type": "bar",
                "data": list_value(diagnostics.get("native_feature_importance", {}).get("top_features"))[:20],
                "encoding": {"x": "importance", "y": "feature_name", "color": "family"},
            },
            {
                "id": "permutation_importance",
                "chart_type": "bar",
                "data": list_value(diagnostics.get("permutation_importance", {}).get("top_features"))[:20],
                "encoding": {"x": "importance_delta", "y": "feature_name", "color": "family"},
            },
            {
                "id": "calibration_bins",
                "chart_type": "calibration",
                "data": list_value(diagnostics.get("prediction_review", {}).get("calibration_bins")),
                "encoding": {"x": "average_score", "y": "positive_rate", "size": "count"},
            },
        ],
        "empty_state": "Materialize model diagnostics artifacts after a run has predictions and a model package.",
    }


def render_model_diagnostics_artifact_report(diagnostics: dict[str, Any]) -> str:
    lines = [
        "# Model Diagnostics Artifact Pack",
        "",
        f"- Run: {diagnostics['run_id']}",
        f"- ModelVersion: {diagnostics.get('model_version_id') or '-'}",
        f"- Primary metric: {diagnostics.get('primary_metric_name')}={format_metric(diagnostics.get('primary_metric_value'))}",
        "",
        "## Availability",
        "",
    ]
    for key, value in dict_value(diagnostics.get("availability")).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top Native Features", ""])
    native = dict_value(diagnostics.get("native_feature_importance"))
    if native.get("status") != "ready":
        lines.append(f"- {native.get('message') or 'Native feature importance is not available.'}")
    for row in list_value(native.get("top_features"))[:12]:
        item = dict_value(row)
        lines.append(f"- {item.get('feature_name')}: {format_metric(item.get('importance'))} ({item.get('family')})")
    lines.extend(["", "## Top Permutation Features", ""])
    permutation = dict_value(diagnostics.get("permutation_importance"))
    if permutation.get("status") == "ready":
        for row in list_value(permutation.get("top_features"))[:12]:
            item = dict_value(row)
            lines.append(
                f"- {item.get('feature_name')}: delta={format_metric(item.get('importance_delta'))} "
                f"({item.get('family')})"
            )
    else:
        lines.append(f"- {permutation.get('message') or 'Permutation importance is not available.'}")
    lines.extend(["", "## Interpretation", ""])
    for item in list_value(diagnostics.get("interpretation")):
        row = dict_value(item)
        lines.append(f"- {row.get('title')}: {row.get('summary')} Next: {row.get('next_action')}")
    lines.extend(["", "## Limitations", ""])
    for limitation in list_value(diagnostics.get("limitations")):
        lines.append(f"- {limitation}")
    return "\n".join(lines).strip() + "\n"


def model_diagnostics_summary(diagnostics: dict[str, Any]) -> str:
    native_count = len(list_value(diagnostics.get("native_feature_importance", {}).get("top_features")))
    permutation = dict_value(diagnostics.get("permutation_importance"))
    permutation_status = permutation.get("status") or "blocked"
    base = diagnostics_summary(
        {
            "task_kind": diagnostics.get("task_kind") or "classification",
            "summary": diagnostics.get("evaluation_diagnostics_summary", {}).get("summary", {}),
            "sanity_checks": {},
        }
    )
    return f"{base} Native importance rows={native_count}; permutation importance={permutation_status}."


def blocked_payload(schema_version: str, reason: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": "blocked",
        "reason": reason,
        "message": message,
        **extra,
    }


def artifact_ref(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "download_url": f"/api/artifacts/{artifact.id}/download",
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
    }


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def finite_float(value: object) -> float | None:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def format_metric(value: object) -> str:
    number = finite_float(value)
    if number is None:
        return "-"
    return f"{number:.6g}"


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
