from __future__ import annotations

import csv
import io
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Insight,
    Project,
    SplitManifest,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.baseline import load_split_rows


@dataclass(frozen=True)
class EvaluationDiagnosticsResult:
    run: ExperimentRun
    artifact_ids: list[str]
    diagnostics: dict[str, Any]
    insight_id: str
    evidence_id: str


def analyze_run_diagnostics(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> EvaluationDiagnosticsResult:
    project = require_project(db, run.project_id)
    if not run.dataset_snapshot_id or not run.evaluation_spec_id or not run.split_manifest_id:
        raise ValueError("Run must reference DatasetSnapshot, EvaluationSpec, and SplitManifest")
    dataset = require_dataset(db, run.dataset_snapshot_id)
    spec = require_spec(db, run.evaluation_spec_id)
    split = require_split(db, run.split_manifest_id)
    dataset_artifact = require_artifact(db, dataset.artifact_id)
    split_artifact = require_artifact(db, split.artifact_id)
    predictions_artifact = latest_prediction_artifact(db, run)
    if predictions_artifact is None:
        raise ValueError("Prediction output artifact not found for run")
    if not project.target_column:
        raise ValueError("Project target_column is required for diagnostics")

    split_rows = load_split_rows(
        dataset_path=artifact_primary_path(dataset_artifact),
        split_path=artifact_primary_path(split_artifact),
        target_column=project.target_column,
    )
    predictions = load_prediction_csv(predictions_artifact)
    diagnostics = build_diagnostics(
        run=run,
        project=project,
        evaluation_spec=spec,
        split_manifest=split,
        split_rows=split_rows,
        predictions=predictions,
    )
    report_md = render_diagnostics_report(project=project, run=run, diagnostics=diagnostics)
    visualization_spec = build_diagnostics_visualization_spec(diagnostics)

    diagnostics_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="evaluation_diagnostics",
        name=f"evaluation_diagnostics_{run.id}",
        filename="evaluation_diagnostics.json",
        payload=diagnostics,
        metadata={"project_id": project.id, "run_id": run.id, "evaluation_spec_id": spec.id},
    )
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="evaluation_diagnostics_report",
        name=f"evaluation_diagnostics_report_{run.id}",
        filename="evaluation_diagnostics.md",
        text=report_md,
        metadata={"project_id": project.id, "run_id": run.id, "evaluation_spec_id": spec.id},
    )
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"evaluation_diagnostics_visualization_{run.id}",
        filename="evaluation_diagnostics_visualization.json",
        payload=visualization_spec,
        metadata={"project_id": project.id, "run_id": run.id, "chart_type": visualization_spec["chart_type"]},
    )
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="evaluation_diagnostics",
        summary=diagnostics_summary(diagnostics),
        strength="medium",
        source_artifact_id=diagnostics_artifact.id,
        source_run_id=run.id,
        metadata_json=dumps_json({"run_id": run.id, "diagnostic_type": diagnostics["task_kind"]}),
    )
    db.add(evidence)
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="evaluation_diagnostics",
        title=f"Evaluation diagnostics for {run.id}",
        summary=evidence.summary,
        severity=diagnostics_severity(diagnostics),
        confidence=0.78,
        status="open",
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "experiment_run", "asset_id": run.id},
                {"asset_type": "evaluation_spec", "asset_id": spec.id},
                {"asset_type": "split_manifest", "asset_id": split.id},
            ]
        ),
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=diagnostics_artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    db.flush()

    for artifact in [diagnostics_artifact, report_artifact, visualization_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="diagnoses",
        )
    for source_type, source_id in [
        ("prediction_output", predictions_artifact.id),
        ("evaluation_spec", spec.id),
        ("split_manifest", split.id),
    ]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type=source_type,
            from_asset_id=source_id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="insight",
        from_asset_id=insight.id,
        to_asset_type="artifact",
        to_asset_id=diagnostics_artifact.id,
        relation_type="materializes",
    )
    return EvaluationDiagnosticsResult(
        run=run,
        artifact_ids=[diagnostics_artifact.id, report_artifact.id, visualization_artifact.id],
        diagnostics=diagnostics,
        insight_id=insight.id,
        evidence_id=evidence.id,
    )


def build_diagnostics(
    *,
    run: ExperimentRun,
    project: Project,
    evaluation_spec: EvaluationSpec,
    split_manifest: SplitManifest,
    split_rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = loads_json(run.metrics_json, {})
    task_kind = infer_task_kind(metrics, predictions)
    valid_rows_by_index = {
        int(row["__harness_row_index"]): row
        for row in split_rows
        if row.get("__harness_split") == "valid"
    }
    joined = []
    duplicate_counter = Counter(int(row["row_index"]) for row in predictions)
    for prediction in predictions:
        row_index = int(prediction["row_index"])
        source = valid_rows_by_index.get(row_index, {})
        joined.append({"prediction": prediction, "source": source})
    missing_prediction_rows = sorted(set(valid_rows_by_index) - {int(row["row_index"]) for row in predictions})
    duplicate_prediction_rows = sorted(row_index for row_index, count in duplicate_counter.items() if count > 1)

    if task_kind == "regression":
        summary = regression_summary(predictions)
        slice_metrics = regression_slice_metrics(joined, project.target_column or "")
        bins = regression_error_bins(predictions)
        worst_examples = worst_regression_examples(joined)
    else:
        summary = classification_summary(predictions)
        slice_metrics = classification_slice_metrics(joined, project.target_column or "")
        bins = classification_score_bins(predictions)
        worst_examples = worst_classification_examples(joined)
    return {
        "schema_version": "evaluation_diagnostics.v1",
        "run_id": run.id,
        "project_id": project.id,
        "task_kind": task_kind,
        "evaluation_spec_id": evaluation_spec.id,
        "split_manifest_id": split_manifest.id,
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
        "summary": summary,
        "slice_metrics": slice_metrics,
        "bins": bins,
        "worst_examples": worst_examples,
        "sanity_checks": {
            "prediction_count": len(predictions),
            "valid_count_from_split": split_manifest.valid_count,
            "valid_rows_loaded": len(valid_rows_by_index),
            "missing_prediction_rows": missing_prediction_rows[:50],
            "duplicate_prediction_rows": duplicate_prediction_rows[:50],
            "prediction_count_matches_split": len(predictions) == split_manifest.valid_count,
            "all_predictions_joined_to_valid_rows": not missing_prediction_rows,
        },
    }


def load_prediction_csv(artifact: Artifact) -> list[dict[str, Any]]:
    text = artifact_primary_path(artifact).read_text(encoding="utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        parsed: dict[str, Any] = {
            "row_index": int(row["row_index"]),
            "split": row.get("split") or "valid",
            "target": parse_value(row.get("target")),
            "prediction": parse_value(row.get("prediction")),
        }
        if row.get("score") not in {None, ""}:
            parsed["score"] = float(row["score"])
        rows.append(parsed)
    return rows


def infer_task_kind(metrics: dict[str, Any], predictions: list[dict[str, Any]]) -> str:
    baseline_type = str(metrics.get("baseline_type") or "")
    if "class" in baseline_type or "logistic" in baseline_type:
        return "classification"
    if "regress" in baseline_type or "rmse" in metrics or "mae" in metrics:
        return "regression"
    if predictions and all(is_number(row.get("target")) and is_number(row.get("prediction")) for row in predictions):
        return "regression"
    return "classification"


def classification_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(predictions)
    correct = sum(1 for row in predictions if str(row["target"]) == str(row["prediction"]))
    confusion = Counter((str(row["target"]), str(row["prediction"])) for row in predictions)
    return {
        "count": total,
        "correct": correct,
        "error_count": total - correct,
        "accuracy": correct / total if total else None,
        "confusion_pairs": [
            {"target": target, "prediction": prediction, "count": count}
            for (target, prediction), count in confusion.most_common(20)
        ],
    }


def regression_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [float(row["prediction"]) - float(row["target"]) for row in predictions]
    abs_errors = [abs(error) for error in errors]
    squared = [error * error for error in errors]
    return {
        "count": len(predictions),
        "mae": sum(abs_errors) / len(abs_errors) if abs_errors else None,
        "rmse": math.sqrt(sum(squared) / len(squared)) if squared else None,
        "mean_error": sum(errors) / len(errors) if errors else None,
        "max_abs_error": max(abs_errors) if abs_errors else None,
    }


def classification_score_bins(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_bin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        score = float(row.get("score", 0.0))
        bucket_start = min(9, max(0, int(score * 10))) / 10
        label = f"{bucket_start:.1f}-{bucket_start + 0.1:.1f}"
        rows_by_bin[label].append(row)
    bins = []
    for label in sorted(rows_by_bin):
        rows = rows_by_bin[label]
        correct = sum(1 for row in rows if str(row["target"]) == str(row["prediction"]))
        bins.append({"bin": label, "count": len(rows), "accuracy": correct / len(rows) if rows else None})
    return bins


def regression_error_bins(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    abs_errors = [abs(float(row["prediction"]) - float(row["target"])) for row in predictions]
    if not abs_errors:
        return []
    sorted_errors = sorted(abs_errors)
    thresholds = [
        sorted_errors[int((len(sorted_errors) - 1) * quantile)]
        for quantile in [0.25, 0.5, 0.75, 1.0]
    ]
    rows_by_bin: dict[str, list[float]] = defaultdict(list)
    for error in abs_errors:
        if error <= thresholds[0]:
            label = "q1_low_error"
        elif error <= thresholds[1]:
            label = "q2"
        elif error <= thresholds[2]:
            label = "q3"
        else:
            label = "q4_high_error"
        rows_by_bin[label].append(error)
    return [
        {"bin": label, "count": len(values), "mean_abs_error": sum(values) / len(values)}
        for label, values in rows_by_bin.items()
    ]


def classification_slice_metrics(joined: list[dict[str, Any]], target_column: str) -> list[dict[str, Any]]:
    return slice_metrics(joined, target_column, metric_kind="classification")


def regression_slice_metrics(joined: list[dict[str, Any]], target_column: str) -> list[dict[str, Any]]:
    return slice_metrics(joined, target_column, metric_kind="regression")


def slice_metrics(joined: list[dict[str, Any]], target_column: str, metric_kind: str) -> list[dict[str, Any]]:
    candidate_columns = select_slice_columns([item["source"] for item in joined], target_column)
    rows = []
    for column in candidate_columns:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in joined:
            value = item["source"].get(column)
            groups[str(value)].append(item["prediction"])
        for value, predictions in groups.items():
            if metric_kind == "regression":
                summary = regression_summary(predictions)
                metric_value = summary["mae"]
                metric_name = "mae"
            else:
                summary = classification_summary(predictions)
                metric_value = summary["accuracy"]
                metric_name = "accuracy"
            rows.append(
                {
                    "column": column,
                    "value": value,
                    "count": len(predictions),
                    "metric_name": metric_name,
                    "metric_value": metric_value,
                }
            )
    return sorted(rows, key=lambda item: (item["column"], -item["count"], str(item["value"])))[:80]


def select_slice_columns(rows: list[dict[str, Any]], target_column: str) -> list[str]:
    if not rows:
        return []
    excluded = {
        target_column,
        "__harness_row_index",
        "__harness_target",
        "__harness_split",
    }
    candidates = []
    for column in rows[0]:
        if column in excluded:
            continue
        values = [row.get(column) for row in rows]
        unique_values = {str(value) for value in values if value is not None}
        if 1 < len(unique_values) <= 12:
            candidates.append(column)
    return candidates[:6]


def worst_classification_examples(joined: list[dict[str, Any]]) -> list[dict[str, Any]]:
    misses = [
        item
        for item in joined
        if str(item["prediction"]["target"]) != str(item["prediction"]["prediction"])
    ]
    misses.sort(key=lambda item: float(item["prediction"].get("score", 0.0)), reverse=True)
    return [compact_example(item) for item in misses[:20]]


def worst_regression_examples(joined: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        joined,
        key=lambda item: abs(float(item["prediction"]["prediction"]) - float(item["prediction"]["target"])),
        reverse=True,
    )
    return [compact_example(item) for item in ranked[:20]]


def compact_example(item: dict[str, Any]) -> dict[str, Any]:
    prediction = item["prediction"]
    source = item["source"]
    return {
        "row_index": prediction["row_index"],
        "target": diagnostic_json_value(prediction["target"]),
        "prediction": diagnostic_json_value(prediction["prediction"]),
        "score": prediction.get("score"),
        "features": {
            key: diagnostic_json_value(value)
            for key, value in list(source.items())[:12]
            if not str(key).startswith("__harness")
        },
    }


def diagnostic_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    if isinstance(value, dict):
        return {str(key): diagnostic_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [diagnostic_json_value(item) for item in value]
    return str(value)


def build_diagnostics_visualization_spec(diagnostics: dict[str, Any]) -> dict[str, Any]:
    if diagnostics["slice_metrics"]:
        return {
            "schema_version": "visualization_spec.v1",
            "title": "Evaluation Slice Metrics",
            "chart_type": "diagnostic_slice_bars",
            "data": diagnostics["slice_metrics"],
            "encoding": {"x": "value", "y": "metric_value", "color": "column"},
            "empty_state": "No slice metrics are available for this run.",
        }
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Evaluation Error Bins",
        "chart_type": "diagnostic_error_bins",
        "data": diagnostics["bins"],
        "encoding": {"x": "bin", "y": "count"},
        "empty_state": "No error bins are available for this run.",
    }


def render_diagnostics_report(*, project: Project, run: ExperimentRun, diagnostics: dict[str, Any]) -> str:
    lines = [
        "# Evaluation Diagnostics",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Run: {run.id}",
        f"- Task kind: {diagnostics['task_kind']}",
        f"- EvaluationSpec: {diagnostics['evaluation_spec_id']}",
        f"- SplitManifest: {diagnostics['split_manifest_id']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in diagnostics["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Sanity Checks", ""])
    for key, value in diagnostics["sanity_checks"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Slice Metrics", ""])
    for row in diagnostics["slice_metrics"][:20]:
        lines.append(
            f"- {row['column']}={row['value']}: {row['metric_name']}={row['metric_value']} over {row['count']} rows"
        )
    if not diagnostics["slice_metrics"]:
        lines.append("- No slice metrics generated.")
    lines.extend(["", "## Worst Examples", ""])
    for example in diagnostics["worst_examples"][:10]:
        lines.append(f"- row {example['row_index']}: target={example['target']}, prediction={example['prediction']}")
    if not diagnostics["worst_examples"]:
        lines.append("- No worst examples generated.")
    return "\n".join(lines).strip() + "\n"


def diagnostics_summary(diagnostics: dict[str, Any]) -> str:
    summary = diagnostics["summary"]
    if diagnostics["task_kind"] == "regression":
        return f"Regression diagnostics: mae={summary.get('mae')}, rmse={summary.get('rmse')}, rows={summary.get('count')}."
    return (
        f"Classification diagnostics: accuracy={summary.get('accuracy')}, "
        f"errors={summary.get('error_count')}, rows={summary.get('count')}."
    )


def diagnostics_severity(diagnostics: dict[str, Any]) -> str:
    sanity = diagnostics["sanity_checks"]
    if not sanity["prediction_count_matches_split"] or not sanity["all_predictions_joined_to_valid_rows"]:
        return "warning"
    summary = diagnostics["summary"]
    if diagnostics["task_kind"] == "classification" and summary.get("accuracy") is not None and summary["accuracy"] < 0.5:
        return "warning"
    return "info"


def parse_value(value: str | None) -> Any:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def latest_prediction_artifact(db: Session, run: ExperimentRun) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == run.project_id, Artifact.asset_type == "prediction_output")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("run_id") == run.id:
            return artifact
    return None


def require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def require_dataset(db: Session, dataset_id: str) -> DatasetSnapshot:
    dataset = db.get(DatasetSnapshot, dataset_id)
    if dataset is None:
        raise ValueError("DatasetSnapshot not found")
    return dataset


def require_spec(db: Session, spec_id: str) -> EvaluationSpec:
    spec = db.get(EvaluationSpec, spec_id)
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    return spec


def require_split(db: Session, split_id: str) -> SplitManifest:
    split = db.get(SplitManifest, split_id)
    if split is None:
        raise ValueError("SplitManifest not found")
    return split


def require_artifact(db: Session, artifact_id: str) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError("Artifact not found")
    return artifact
