from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    Project,
    SplitManifest,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.baseline import (
    average_precision,
    binary_roc_auc,
    label_f1,
    macro_f1,
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)
from tabular_harness.services.metric_preferences import normalize_metric_name
from tabular_harness.services.profiler import read_sql

EXPERIMENT_EVIDENCE_SCHEMA_VERSION = "experiment_evidence.v1"
PREDICTION_REQUIRED_COLUMNS = {"row_index", "fold"}
REGRESSION_METRICS = {"mae", "rmse", "r2"}
SUPPORTED_REPLAY_METRICS = REGRESSION_METRICS | {
    "accuracy",
    "f1",
    "log_loss",
    "macro_f1",
    "pr_auc",
    "roc_auc",
}


def register_experiment_evidence(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    run: ExperimentRun,
    payload: dict[str, Any],
) -> Artifact:
    normalized = validate_experiment_evidence_payload(db, project=project, run=run, payload=payload)
    verification = replay_prediction_evidence(db, project=project, run=run, payload=normalized)
    evidence_payload = {
        **normalized,
        "run_id": run.id,
        "verification": verification,
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="experiment_evidence",
        name=f"experiment_evidence_{run.id}",
        filename="experiment_evidence.json",
        payload=evidence_payload,
        metadata={
            "schema_version": EXPERIMENT_EVIDENCE_SCHEMA_VERSION,
            "run_id": run.id,
            "parent_run_id": normalized.get("parent_run_id"),
            "prediction_evidence_artifact_id": prediction_artifact_id(normalized),
            "metric_replay_status": verification["metric_replay"]["status"],
            "prediction_coverage_status": verification["predictions"]["coverage_status"],
            "prediction_coverage_scope": verification["predictions"]["coverage_scope"],
            "hypothesis_verdict": normalized["learning"]["verdict"],
            "decision_action": normalized["decision"]["action"],
        },
        created_by=run.created_by,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="experiment_run",
        from_asset_id=run.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="documents_experiment_evidence",
        org_id=project.org_id,
    )
    oof_artifact_id = prediction_artifact_id(normalized)
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=oof_artifact_id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="supports_experiment_evidence",
        org_id=project.org_id,
    )
    parent_run_id = normalized.get("parent_run_id")
    if parent_run_id:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=parent_run_id,
            to_asset_type="experiment_run",
            to_asset_id=run.id,
            relation_type="parent_of_experiment",
            metadata={"experiment_evidence_artifact_id": artifact.id},
            org_id=project.org_id,
        )
    params = loads_json(run.params_json, {})
    params["experiment_evidence_status"] = (
        "verified" if verification["metric_replay"]["status"] == "passed" else "registered_unreplayed"
    )
    params["experiment_evidence_artifact_id"] = artifact.id
    params["parent_run_id"] = parent_run_id
    run.params_json = dumps_json(params)
    return artifact


def validate_experiment_evidence_payload(
    db: Session,
    *,
    project: Project,
    run: ExperimentRun,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if payload.get("schema_version") != EXPERIMENT_EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"experiment_evidence.schema_version must be {EXPERIMENT_EVIDENCE_SCHEMA_VERSION}")
    parent_run_id = optional_string(payload, "parent_run_id")
    if parent_run_id == run.id:
        raise ValueError("experiment_evidence.parent_run_id cannot reference the run itself")
    if parent_run_id:
        parent = db.get(ExperimentRun, parent_run_id)
        if parent is None or parent.project_id != project.id:
            raise ValueError("experiment_evidence.parent_run_id must reference a run in this project")

    hypothesis = required_object(payload, "hypothesis")
    require_string(hypothesis, "statement", context="experiment_evidence.hypothesis")
    require_string(hypothesis, "expected_observation", context="experiment_evidence.hypothesis")
    change_set = required_object(payload, "change_set")
    if not change_set:
        raise ValueError("experiment_evidence.change_set must describe what changed from the parent or baseline")

    evaluation = required_object(payload, "evaluation")
    split_manifest_id = require_string(evaluation, "split_manifest_id", context="experiment_evidence.evaluation")
    if run.split_manifest_id and split_manifest_id != run.split_manifest_id:
        raise ValueError("experiment_evidence evaluation split_manifest_id does not match the ExperimentRun")
    primary_metric = normalize_metric_name(
        require_string(evaluation, "primary_metric", context="experiment_evidence.evaluation")
    )
    run_metrics = loads_json(run.metrics_json, {})
    run_primary_metric = normalize_metric_name(str(run_metrics.get("primary_metric_name") or ""))
    if run_primary_metric and primary_metric != run_primary_metric:
        raise ValueError("experiment_evidence primary_metric does not match the ExperimentRun")
    aggregate_value = require_number(evaluation, "aggregate_value", context="experiment_evidence.evaluation")
    fold_values = evaluation.get("fold_values")
    if not isinstance(fold_values, list) or not fold_values:
        raise ValueError("experiment_evidence.evaluation.fold_values must be a non-empty array")
    normalized_fold_values = normalize_declared_fold_values(fold_values)

    artifacts = required_object(payload, "artifacts")
    oof_artifact_id = optional_string(artifacts, "oof_predictions") or optional_string(
        artifacts, "validation_predictions"
    )
    if not oof_artifact_id:
        raise ValueError(
            "experiment_evidence.artifacts requires oof_predictions or validation_predictions"
        )
    oof_artifact = db.get(Artifact, oof_artifact_id)
    if oof_artifact is None or oof_artifact.project_id != project.id:
        raise ValueError("experiment_evidence prediction artifact must reference an artifact in this project")
    for key, value in artifacts.items():
        if not isinstance(value, str) or not value.strip():
            continue
        referenced = db.get(Artifact, value.strip())
        if referenced is None or referenced.project_id != project.id:
            raise ValueError(f"experiment_evidence.artifacts.{key} must reference an artifact in this project")

    learning = required_object(payload, "learning")
    verdict = require_string(learning, "verdict", context="experiment_evidence.learning")
    if verdict not in {"supported", "mixed", "not_supported", "inconclusive"}:
        raise ValueError("experiment_evidence.learning.verdict is not supported")
    require_string(learning, "remaining_uncertainty", context="experiment_evidence.learning")
    decision = required_object(payload, "decision")
    action = require_string(decision, "action", context="experiment_evidence.decision")
    if action not in {"retain_and_refine", "retain", "combine", "defer", "reject"}:
        raise ValueError("experiment_evidence.decision.action is not supported")

    coverage_scope = str(evaluation.get("coverage_scope") or "full_labeled_dataset").strip()
    if coverage_scope not in {"full_labeled_dataset", "split_manifest_validation"}:
        raise ValueError(
            "experiment_evidence.evaluation.coverage_scope must be full_labeled_dataset "
            "or split_manifest_validation"
        )
    return {
        **payload,
        "schema_version": EXPERIMENT_EVIDENCE_SCHEMA_VERSION,
        "run_id": run.id,
        "parent_run_id": parent_run_id,
        "hypothesis": hypothesis,
        "change_set": change_set,
        "evaluation": {
            **evaluation,
            "split_manifest_id": split_manifest_id,
            "primary_metric": primary_metric,
            "aggregate_value": aggregate_value,
            "fold_values": normalized_fold_values,
            "coverage_scope": coverage_scope,
        },
        "artifacts": artifacts,
        "learning": learning,
        "decision": decision,
    }


def replay_prediction_evidence(
    db: Session,
    *,
    project: Project,
    run: ExperimentRun,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not project.target_column:
        raise ValueError("Project target_column is required to verify prediction evidence")
    if not run.dataset_snapshot_id:
        raise ValueError("ExperimentRun dataset_snapshot_id is required to verify prediction evidence")
    dataset = db.get(DatasetSnapshot, run.dataset_snapshot_id)
    if dataset is None or dataset.project_id != project.id:
        raise ValueError("ExperimentRun DatasetSnapshot was not found in this project")
    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    split_manifest = db.get(SplitManifest, run.split_manifest_id) if run.split_manifest_id else None
    split_artifact = db.get(Artifact, split_manifest.artifact_id) if split_manifest is not None else None
    oof_artifact = db.get(Artifact, prediction_artifact_id(payload))
    if dataset_artifact is None or oof_artifact is None:
        raise ValueError("Dataset or prediction evidence artifact was not found")
    coverage_scope = payload["evaluation"]["coverage_scope"]
    if coverage_scope == "split_manifest_validation" and split_artifact is None:
        raise ValueError("SplitManifest artifact is required for validation prediction replay")
    rows, expected_count, source_columns = load_prediction_rows(
        dataset_path=artifact_primary_path(dataset_artifact),
        oof_path=artifact_primary_path(oof_artifact),
        target_column=project.target_column,
        coverage_scope=coverage_scope,
        split_path=artifact_primary_path(split_artifact) if split_artifact is not None else None,
    )
    if not rows:
        raise ValueError("Prediction evidence artifact contains no matched labeled rows")
    row_indices = [int(row["row_index"]) for row in rows]
    if len(row_indices) != len(set(row_indices)):
        raise ValueError("Prediction evidence artifact contains duplicate row_index values")
    if len(rows) != expected_count:
        raise ValueError(
            f"Prediction evidence coverage is incomplete: matched {len(rows)} of {expected_count} expected rows"
        )
    metric_name = payload["evaluation"]["primary_metric"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["fold"])].append(row)
    declared_folds = payload["evaluation"]["fold_values"]
    declared_fold_ids = {str(item["fold"]) for item in declared_folds}
    if declared_fold_ids != set(grouped):
        raise ValueError("experiment_evidence fold identifiers do not match the prediction artifact")
    if metric_name not in SUPPORTED_REPLAY_METRICS:
        return {
            "schema_version": "experiment_evidence_verification.v1",
            "predictions": {
                "artifact_id": oof_artifact.id,
                "row_count": len(rows),
                "expected_row_count": expected_count,
                "coverage": len(rows) / expected_count if expected_count else 0.0,
                "coverage_status": "complete",
                "coverage_scope": coverage_scope,
                "unique_row_index": True,
                "fold_count": len(grouped),
                "source_columns": source_columns,
                "labels_read_from_frozen_dataset": True,
            },
            "metric_replay": {
                "status": "unsupported",
                "primary_metric": metric_name,
                "reason": "The prediction evidence contract is valid, but this metric does not yet have a harness replay implementation.",
            },
        }
    aggregate_value = calculate_metric(metric_name, rows)
    declared_aggregate = float(payload["evaluation"]["aggregate_value"])
    assert_metric_close("aggregate", declared_aggregate, aggregate_value)
    run_metrics = loads_json(run.metrics_json, {})
    run_value = numeric_metric_value(run_metrics, metric_name)
    if run_value is not None:
        assert_metric_close("ExperimentRun", run_value, aggregate_value)

    replayed_folds = [
        {"fold": fold, "value": calculate_metric(metric_name, fold_rows), "row_count": len(fold_rows)}
        for fold, fold_rows in sorted(grouped.items())
    ]
    if len(declared_folds) != len(replayed_folds):
        raise ValueError("experiment_evidence fold count does not match the prediction artifact")
    declared_by_fold = {str(item["fold"]): float(item["value"]) for item in declared_folds}
    for item in replayed_folds:
        if item["fold"] not in declared_by_fold:
            raise ValueError(f"experiment_evidence is missing declared value for fold {item['fold']}")
        assert_metric_close(f"fold {item['fold']}", declared_by_fold[item["fold"]], float(item["value"]))
    return {
        "schema_version": "experiment_evidence_verification.v1",
        "predictions": {
            "artifact_id": oof_artifact.id,
            "row_count": len(rows),
            "expected_row_count": expected_count,
            "coverage": len(rows) / expected_count if expected_count else 0.0,
            "coverage_status": "complete",
            "coverage_scope": coverage_scope,
            "unique_row_index": True,
            "fold_count": len(replayed_folds),
            "source_columns": source_columns,
            "labels_read_from_frozen_dataset": True,
        },
        "metric_replay": {
            "status": "passed",
            "primary_metric": metric_name,
            "replayed_aggregate_value": aggregate_value,
            "declared_aggregate_value": declared_aggregate,
            "experiment_run_value": run_value,
            "fold_values": replayed_folds,
            "tolerance": 1e-8,
        },
    }


def load_prediction_rows(
    *,
    dataset_path: Path,
    oof_path: Path,
    target_column: str,
    coverage_scope: str,
    split_path: Path | None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    con = duckdb.connect(database=":memory:")
    oof_relation = read_sql(oof_path)
    dataset_relation = read_sql(dataset_path)
    source_columns = [str(item[0]) for item in con.execute(f"SELECT * FROM {oof_relation} LIMIT 0").description]
    missing = sorted(PREDICTION_REQUIRED_COLUMNS - set(source_columns))
    if missing:
        raise ValueError(f"Prediction evidence artifact is missing required columns: {', '.join(missing)}")
    if "score" not in source_columns and "prediction" not in source_columns:
        raise ValueError("Prediction evidence artifact must contain score or prediction")
    target_ident = quote_ident(target_column)
    dataset_with_index = f"(SELECT row_number() OVER () - 1 AS __row_index, * FROM {dataset_relation})"
    if coverage_scope == "split_manifest_validation":
        if split_path is None:
            raise ValueError("SplitManifest artifact is required for validation prediction replay")
        split_relation = read_sql(split_path)
        expected_rows = (
            f"(SELECT data.* FROM {dataset_with_index} AS data "
            f"JOIN {split_relation} AS split ON data.__row_index = try_cast(split.row_index AS BIGINT) "
            f"WHERE lower(cast(split.split AS VARCHAR)) = 'valid' AND data.{target_ident} IS NOT NULL)"
        )
    else:
        expected_rows = f"(SELECT * FROM {dataset_with_index} WHERE {target_ident} IS NOT NULL)"
    expected_count = int(con.execute(f"SELECT count(*) FROM {expected_rows}").fetchone()[0])
    if expected_count == 0:
        raise ValueError("Prediction evidence scope contains no labeled rows")
    raw_oof_count = int(con.execute(f"SELECT count(*) FROM {oof_relation}").fetchone()[0])
    score_expr = "try_cast(oof.score AS DOUBLE)" if "score" in source_columns else "NULL"
    prediction_expr = "cast(oof.prediction AS VARCHAR)" if "prediction" in source_columns else "NULL"
    target_copy_expr = "cast(oof.target AS VARCHAR)" if "target" in source_columns else "NULL"
    query = f"""
    SELECT
      try_cast(oof.row_index AS BIGINT) AS row_index,
      cast(oof.fold AS VARCHAR) AS fold,
      data.{target_ident} AS frozen_target,
      {score_expr} AS score,
      {prediction_expr} AS prediction,
      {target_copy_expr} AS supplied_target
    FROM {oof_relation} AS oof
    JOIN {expected_rows} AS data
      ON try_cast(oof.row_index AS BIGINT) = data.__row_index
    ORDER BY row_index
    """
    cursor = con.execute(query)
    names = [str(item[0]) for item in cursor.description]
    rows = [{names[index]: value for index, value in enumerate(row)} for row in cursor.fetchall()]
    if raw_oof_count != len(rows):
        raise ValueError("Prediction evidence contains row_index values outside the declared evaluation scope")
    if any(row["row_index"] is None or not str(row["fold"] or "").strip() for row in rows):
        raise ValueError("Prediction evidence row_index and fold values must be non-null")
    for row in rows:
        supplied = row.get("supplied_target")
        if supplied is not None and supplied != "" and str(supplied) != str(row["frozen_target"]):
            raise ValueError("Prediction evidence target does not match the frozen DatasetSnapshot label")
    return rows, expected_count, source_columns


def calculate_metric(metric_name: str, rows: list[dict[str, Any]]) -> float:
    if metric_name in REGRESSION_METRICS:
        actual = [float(row["frozen_target"]) for row in rows]
        predicted = [numeric_prediction(row) for row in rows]
        if metric_name == "mae":
            return mean_absolute_error(actual, predicted)
        if metric_name == "rmse":
            return root_mean_squared_error(actual, predicted)
        return r2_score(actual, predicted)

    actual_labels = [str(row["frozen_target"]) for row in rows]
    labels = sorted(set(actual_labels))
    predicted_labels = [prediction_label(row, labels) for row in rows]
    if metric_name == "accuracy":
        return sum(actual == predicted for actual, predicted in zip(actual_labels, predicted_labels, strict=True)) / len(rows)
    if metric_name == "macro_f1":
        return macro_f1(actual_labels, predicted_labels, sorted({*labels, *predicted_labels}))
    if metric_name == "f1":
        if len(labels) != 2:
            raise ValueError("F1 replay requires a binary target")
        return label_f1(actual_labels, predicted_labels, labels[-1])
    if metric_name in {"roc_auc", "pr_auc", "log_loss"}:
        if len(labels) != 2:
            raise ValueError(f"{metric_name} replay requires a binary target")
        scores = [required_score(row) for row in rows]
        binary = [1 if value == labels[-1] else 0 for value in actual_labels]
        if metric_name == "roc_auc":
            return binary_roc_auc(binary, scores)
        if metric_name == "pr_auc":
            return average_precision(binary, scores)
        epsilon = 1e-15
        return -sum(
            target * math.log(min(max(score, epsilon), 1 - epsilon))
            + (1 - target) * math.log(min(max(1 - score, epsilon), 1 - epsilon))
            for target, score in zip(binary, scores, strict=True)
        ) / len(binary)
    raise ValueError(f"Metric replay is not implemented for {metric_name}")


def prediction_label(row: dict[str, Any], labels: list[str]) -> str:
    value = row.get("prediction")
    if value is not None and str(value) != "":
        return str(value)
    if len(labels) == 2:
        return labels[-1] if required_score(row) >= 0.5 else labels[0]
    raise ValueError("Prediction column is required for multiclass metric replay")


def numeric_prediction(row: dict[str, Any]) -> float:
    value = row.get("prediction")
    if value is None or value == "":
        value = row.get("score")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError("Prediction evidence must be numeric for regression metric replay")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError("Prediction evidence must be numeric for regression metric replay") from exc


def required_score(row: dict[str, Any]) -> float:
    value = row.get("score")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Prediction evidence score must be numeric for probability metric replay")
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError("Prediction evidence score must be between 0 and 1")
    return score


def normalize_declared_fold_values(values: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        if isinstance(item, bool):
            raise ValueError("experiment_evidence fold values must be numeric")
        if isinstance(item, int | float):
            normalized.append({"fold": str(index), "value": float(item)})
            continue
        if isinstance(item, dict):
            fold = require_string(item, "fold", context="experiment_evidence.evaluation.fold_values")
            value = require_number(item, "value", context="experiment_evidence.evaluation.fold_values")
            normalized.append({"fold": fold, "value": value})
            continue
        raise ValueError("experiment_evidence fold values must be numbers or {fold, value} objects")
    if len({item["fold"] for item in normalized}) != len(normalized):
        raise ValueError("experiment_evidence fold identifiers must be unique")
    return normalized


def numeric_metric_value(metrics: dict[str, Any], metric_name: str) -> float | None:
    value = metrics.get(metric_name)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if normalize_metric_name(str(metrics.get("primary_metric_name") or "")) == metric_name:
        value = metrics.get("primary_metric_value")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def assert_metric_close(source: str, declared: float, replayed: float) -> None:
    if not math.isclose(declared, replayed, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError(
            f"{source} metric does not match prediction replay: declared={declared:.12g}, replayed={replayed:.12g}"
        )


def required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"experiment_evidence.{key} must be an object")
    return value


def optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"experiment_evidence.{key} must be a string when provided")
    return value.strip() or None


def require_string(payload: dict[str, Any], key: str, *, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} is required")
    return value.strip()


def require_number(payload: dict[str, Any], key: str, *, context: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{context}.{key} must be numeric")
    return float(value)


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def prediction_artifact_id(payload: dict[str, Any]) -> str:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("experiment_evidence.artifacts must be an object")
    value = artifacts.get("oof_predictions") or artifacts.get("validation_predictions")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "experiment_evidence.artifacts requires oof_predictions or validation_predictions"
        )
    return value.strip()
