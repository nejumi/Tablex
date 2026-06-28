from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Job,
    Project,
    SplitManifest,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.schemas import AgentResult, AgentTaskContract
from tabular_harness.services.artifacts import artifact_primary_path, create_lineage_edge


@dataclass(frozen=True)
class AgentResultExperimentIngestion:
    experiment_run_id: str | None
    visualization_ids: list[str]
    metrics_artifact_id: str | None
    feature_recipe_artifact_id: str | None


def ingest_agent_result_experiment_outputs(
    db: Session,
    *,
    project: Project,
    job: Job,
    contract: AgentTaskContract,
    agent_result: AgentResult,
    ingested_artifacts: list[Artifact],
    source_asset_type: str,
    source_asset_id: str,
) -> AgentResultExperimentIngestion:
    metrics_artifact = first_artifact_of_type(ingested_artifacts, "experiment_metrics")
    feature_recipe_artifact = first_artifact_of_type(ingested_artifacts, "feature_recipe")
    visualization_artifacts = [artifact for artifact in ingested_artifacts if artifact.asset_type == "visualization_spec"]
    metrics_payload = load_json_artifact(metrics_artifact)
    run = (
        create_agent_experiment_run(
            db,
            project=project,
            job=job,
            contract=contract,
            agent_result=agent_result,
            metrics_artifact=metrics_artifact,
            feature_recipe_artifact=feature_recipe_artifact,
            metrics_payload=metrics_payload,
            source_asset_type=source_asset_type,
            source_asset_id=source_asset_id,
        )
        if metrics_artifact is not None
        else None
    )
    visualizations = [
        create_visualization_row(
            db,
            project=project,
            artifact=artifact,
            source_artifact_id=metrics_artifact.id if metrics_artifact is not None else artifact.id,
            run=run,
        )
        for artifact in visualization_artifacts
    ]
    db.flush()
    return AgentResultExperimentIngestion(
        experiment_run_id=run.id if run is not None else None,
        visualization_ids=[visualization.id for visualization in visualizations],
        metrics_artifact_id=metrics_artifact.id if metrics_artifact else None,
        feature_recipe_artifact_id=feature_recipe_artifact.id if feature_recipe_artifact else None,
    )


def create_agent_experiment_run(
    db: Session,
    *,
    project: Project,
    job: Job,
    contract: AgentTaskContract,
    agent_result: AgentResult,
    metrics_artifact: Artifact,
    feature_recipe_artifact: Artifact | None,
    metrics_payload: dict[str, Any],
    source_asset_type: str,
    source_asset_id: str,
) -> ExperimentRun:
    resolved = resolve_evaluation_refs(db, project=project, contract=contract, metrics_payload=metrics_payload)
    primary_metric_name = string_or_none(metrics_payload.get("primary_metric_name")) or resolved["primary_metric_name"]
    primary_metric_value = number_or_none(metrics_payload.get("primary_metric_value"))
    execution_status = string_or_none(metrics_payload.get("execution_status")) or agent_result.status
    run_status = "succeeded" if primary_metric_value is not None and execution_status == "succeeded" else execution_status
    normalized_metrics = {
        **metrics_payload,
        "primary_metric_name": primary_metric_name,
        "primary_metric_value": primary_metric_value,
        "agent_task_id": agent_result.task_id,
        "agent_status": agent_result.status,
        "runner": string_or_none(agent_result.outputs.get("runner")) or "agent_runner",
        "metrics_artifact_id": metrics_artifact.id,
        "feature_recipe_artifact_id": feature_recipe_artifact.id if feature_recipe_artifact else None,
    }
    run = ExperimentRun(
        id=new_id("run"),
        project_id=project.id,
        dataset_snapshot_id=resolved["dataset_snapshot_id"],
        evaluation_spec_id=resolved["evaluation_spec_id"],
        split_manifest_id=resolved["split_manifest_id"],
        runner_type=string_or_none(agent_result.outputs.get("runner")) or "agent_runner",
        status=run_status,
        started_at=utc_now(),
        ended_at=utc_now(),
        params_json=dumps_json(
            {
                "agent_task_id": agent_result.task_id,
                "source_asset_type": source_asset_type,
                "source_asset_id": source_asset_id,
                "job_id": job.id,
                "model_code_executed": bool(metrics_payload.get("model_code_executed")),
                "split_manifest_respected": bool(metrics_payload.get("split_manifest_respected")),
            }
        ),
        metrics_json=dumps_json(normalized_metrics),
        summary_md=agent_result.final_message,
        failure_reason=agent_result.failure_reason,
        created_by="agent_runner",
    )
    db.add(run)
    db.flush()
    create_agent_run_lineage(
        db,
        project=project,
        job=job,
        run=run,
        contract=contract,
        source_asset_type=source_asset_type,
        source_asset_id=source_asset_id,
        metrics_artifact=metrics_artifact,
        feature_recipe_artifact=feature_recipe_artifact,
        resolved=resolved,
    )
    return run


def resolve_evaluation_refs(
    db: Session,
    *,
    project: Project,
    contract: AgentTaskContract,
    metrics_payload: dict[str, Any],
) -> dict[str, str | None]:
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    split_manifest_payload = dict_value(evaluation_contract.get("split_manifest"))
    evaluation_spec_id = (
        string_or_none(metrics_payload.get("evaluation_spec_id"))
        or string_or_none(evaluation_contract.get("evaluation_spec_id"))
    )
    split_manifest_id = (
        string_or_none(metrics_payload.get("split_manifest_id"))
        or string_or_none(split_manifest_payload.get("split_manifest_id"))
    )
    dataset_snapshot_id = (
        string_or_none(metrics_payload.get("dataset_snapshot_id"))
        or string_or_none(evaluation_contract.get("dataset_snapshot_id"))
        or string_or_none(dict_value(contract.inputs.get("dataset_context")).get("dataset_snapshot_id"))
    )
    primary_metric_name = string_or_none(metrics_payload.get("primary_metric_name")) or string_or_none(
        evaluation_contract.get("primary_metric")
    )

    evaluation_spec = db.get(EvaluationSpec, evaluation_spec_id) if evaluation_spec_id else None
    if evaluation_spec is not None:
        if evaluation_spec.project_id != project.id:
            raise ValueError("AgentResult EvaluationSpec belongs to a different project")
        dataset_snapshot_id = evaluation_spec.dataset_snapshot_id
        primary_metric_name = primary_metric_name or evaluation_spec.primary_metric
    elif evaluation_spec_id:
        raise ValueError("AgentResult references an unknown EvaluationSpec")

    split_manifest = db.get(SplitManifest, split_manifest_id) if split_manifest_id else None
    if split_manifest is not None:
        if split_manifest.project_id != project.id:
            raise ValueError("AgentResult SplitManifest belongs to a different project")
        if evaluation_spec_id and split_manifest.evaluation_spec_id != evaluation_spec_id:
            raise ValueError("AgentResult SplitManifest does not match EvaluationSpec")
    elif split_manifest_id:
        raise ValueError("AgentResult references an unknown SplitManifest")

    dataset = db.get(DatasetSnapshot, dataset_snapshot_id) if dataset_snapshot_id else None
    if dataset is not None and dataset.project_id != project.id:
        raise ValueError("AgentResult DatasetSnapshot belongs to a different project")
    if dataset is None and dataset_snapshot_id:
        raise ValueError("AgentResult references an unknown DatasetSnapshot")

    return {
        "evaluation_spec_id": evaluation_spec_id,
        "split_manifest_id": split_manifest_id,
        "dataset_snapshot_id": dataset_snapshot_id,
        "primary_metric_name": primary_metric_name,
    }


def create_visualization_row(
    db: Session,
    *,
    project: Project,
    artifact: Artifact,
    source_artifact_id: str,
    run: ExperimentRun | None,
) -> VisualizationSpec:
    spec = load_json_artifact(artifact)
    chart_type = string_or_none(spec.get("chart_type")) or "artifact_checklist"
    title = string_or_none(spec.get("title")) or f"Agent Visualization: {artifact.name}"
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title=title,
        chart_type=chart_type,
        spec_json=dumps_json(spec),
        source_artifact_id=source_artifact_id,
        artifact_id=artifact.id,
        status="ready",
        created_by_type="agent_runner",
    )
    db.add(visualization)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="visualization_spec",
        from_asset_id=visualization.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    if run is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="visualization_spec",
            to_asset_id=visualization.id,
            relation_type="summarized_by",
        )
    return visualization


def create_agent_run_lineage(
    db: Session,
    *,
    project: Project,
    job: Job,
    run: ExperimentRun,
    contract: AgentTaskContract,
    source_asset_type: str,
    source_asset_id: str,
    metrics_artifact: Artifact,
    feature_recipe_artifact: Artifact | None,
    resolved: dict[str, str | None],
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="job",
        from_asset_id=job.id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="produces",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type=source_asset_type,
        from_asset_id=source_asset_id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="agent_task_source",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=metrics_artifact.id,
        to_asset_type="experiment_run",
        to_asset_id=run.id,
        relation_type="materializes_metrics_for",
    )
    if feature_recipe_artifact is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=feature_recipe_artifact.id,
            to_asset_type="experiment_run",
            to_asset_id=run.id,
            relation_type="describes_features_for",
        )
    for asset_type, asset_id, relation_type in [
        ("dataset_snapshot", resolved["dataset_snapshot_id"], "trained_on"),
        ("evaluation_spec", resolved["evaluation_spec_id"], "evaluates_with"),
        ("split_manifest", resolved["split_manifest_id"], "uses"),
    ]:
        if asset_id:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type=asset_type,
                from_asset_id=asset_id,
                to_asset_type="experiment_run",
                to_asset_id=run.id,
                relation_type=relation_type,
            )
    if contract.task_id:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="agent_task",
            from_asset_id=contract.task_id,
            to_asset_type="experiment_run",
            to_asset_id=run.id,
            relation_type="declares",
        )


def load_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        value = json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def first_artifact_of_type(artifacts: list[Artifact], asset_type: str) -> Artifact | None:
    return next((artifact for artifact in artifacts if artifact.asset_type == asset_type), None)


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
