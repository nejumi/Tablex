from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Idea,
    Insight,
    ModelVersion,
    Project,
    Report,
    SplitManifest,
    VisualizationSpec,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)


@dataclass(frozen=True)
class InsightGenerationResult:
    insights: list[Insight]
    artifact: Artifact
    evidence_ids: list[str]


@dataclass(frozen=True)
class DashboardResult:
    visualizations: list[VisualizationSpec]
    artifact_ids: list[str]


def generate_project_insights(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> InsightGenerationResult:
    dataset = latest_dataset(db, project.id)
    profile_artifact = latest_project_artifact(db, project.id, "eda_profile")
    assumptions = list(
        db.scalars(select(Assumption).where(Assumption.project_id == project.id).order_by(Assumption.created_at.desc())).all()
    )
    candidates = list(
        db.scalars(select(EvaluationCandidate).where(EvaluationCandidate.project_id == project.id)).all()
    )
    specs = list(db.scalars(select(EvaluationSpec).where(EvaluationSpec.project_id == project.id)).all())
    splits = list(db.scalars(select(SplitManifest).where(SplitManifest.project_id == project.id)).all())
    runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
    ideas = list(db.scalars(select(Idea).where(Idea.project_id == project.id)).all())
    model_versions = list(db.scalars(select(ModelVersion).where(ModelVersion.project_id == project.id)).all())

    insight_payloads = build_insight_payloads(
        project=project,
        dataset=dataset,
        profile_artifact=profile_artifact,
        assumptions=assumptions,
        candidates=candidates,
        specs=specs,
        splits=splits,
        runs=runs,
        ideas=ideas,
        model_versions=model_versions,
    )
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="insight_set",
        name=f"insight_set_{new_id('insart')}",
        filename="insights.json",
        payload={
            "schema_version": "insight_set.v1",
            "project_id": project.id,
            "insights": insight_payloads,
        },
        metadata={"project_id": project.id, "insight_count": len(insight_payloads)},
    )

    insights: list[Insight] = []
    evidence_ids: list[str] = []
    for payload in insight_payloads:
        evidence = Evidence(
            id=new_id("ev"),
            project_id=project.id,
            evidence_type="insight_summary",
            summary=str(payload["summary"]),
            strength=evidence_strength(float(payload["confidence"])),
            source_artifact_id=artifact.id,
            metadata_json=dumps_json(
                {
                    "insight_type": payload["insight_type"],
                    "severity": payload["severity"],
                    "source_asset_ids": payload["source_asset_ids"],
                }
            ),
        )
        db.add(evidence)
        evidence_ids.append(evidence.id)
        insight = Insight(
            id=str(payload["id"]),
            project_id=project.id,
            insight_type=str(payload["insight_type"]),
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            severity=str(payload["severity"]),
            confidence=float(payload["confidence"]),
            status=str(payload["status"]),
            source_asset_ids_json=dumps_json(payload["source_asset_ids"]),
            evidence_ids_json=dumps_json([evidence.id]),
            artifact_id=artifact.id,
            created_by_type="system",
        )
        db.add(insight)
        db.flush()
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="insight",
            from_asset_id=insight.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="materializes",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="insight",
            from_asset_id=insight.id,
            to_asset_type="evidence",
            to_asset_id=evidence.id,
            relation_type="supported_by",
        )
        for source in payload["source_asset_ids"]:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type=str(source["asset_type"]),
                from_asset_id=str(source["asset_id"]),
                to_asset_type="insight",
                to_asset_id=insight.id,
                relation_type="informs",
            )
        insights.append(insight)
    return InsightGenerationResult(insights=insights, artifact=artifact, evidence_ids=evidence_ids)


def create_project_visualization_dashboard(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> DashboardResult:
    dataset = latest_dataset(db, project.id)
    profile_artifact = latest_project_artifact(db, project.id, "eda_profile")
    assumptions = list(db.scalars(select(Assumption).where(Assumption.project_id == project.id)).all())
    candidates = list(db.scalars(select(EvaluationCandidate).where(EvaluationCandidate.project_id == project.id)).all())
    specs = list(db.scalars(select(EvaluationSpec).where(EvaluationSpec.project_id == project.id)).all())
    splits = list(db.scalars(select(SplitManifest).where(SplitManifest.project_id == project.id)).all())
    runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
    reports = list(db.scalars(select(Report).where(Report.project_id == project.id)).all())
    model_versions = list(db.scalars(select(ModelVersion).where(ModelVersion.project_id == project.id)).all())
    profile = load_profile(profile_artifact)

    specs_to_store = [
        build_metric_cards_spec(
            project=project,
            dataset=dataset,
            profile=profile,
            assumptions=assumptions,
            candidates=candidates,
            specs=specs,
            splits=splits,
            runs=runs,
            reports=reports,
            model_versions=model_versions,
        ),
        build_assumption_risk_spec(assumptions),
        build_evaluation_readiness_spec(candidates=candidates, specs=specs, splits=splits, runs=runs),
        build_leaderboard_spec(runs),
    ]
    visualizations: list[VisualizationSpec] = []
    artifact_ids: list[str] = []
    for spec in specs_to_store:
        visualization, artifact = persist_visualization_spec(
            db,
            store=store,
            project=project,
            spec=spec,
            source_artifact_id=profile_artifact.id if spec["chart_type"] == "metric_cards" and profile_artifact else None,
        )
        visualizations.append(visualization)
        artifact_ids.append(artifact.id)
    return DashboardResult(visualizations=visualizations, artifact_ids=artifact_ids)


def build_insight_payloads(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    profile_artifact: Artifact | None,
    assumptions: list[Assumption],
    candidates: list[EvaluationCandidate],
    specs: list[EvaluationSpec],
    splits: list[SplitManifest],
    runs: list[ExperimentRun],
    ideas: list[Idea],
    model_versions: list[ModelVersion],
) -> list[dict[str, Any]]:
    source_project: list[dict[str, str]] = [{"asset_type": "project", "asset_id": project.id}]
    dataset_sources: list[dict[str, str]] = list(source_project)
    if dataset:
        dataset_sources.append({"asset_type": "dataset_snapshot", "asset_id": dataset.id})
    if profile_artifact:
        dataset_sources.append({"asset_type": "artifact", "asset_id": profile_artifact.id})

    high_risk = [item for item in assumptions if item.risk_level in {"high", "blocking", "deployment_blocking"}]
    approved_specs = [item for item in specs if item.status == "approved"]
    successful_runs = [item for item in runs if item.status == "succeeded"]
    best_run = best_leaderboard_run(successful_runs)

    payloads: list[dict[str, Any]] = [
        {
            "id": new_id("ins"),
            "insight_type": "data_readiness",
            "title": "Dataset readiness summary",
            "summary": dataset_readiness_summary(dataset),
            "severity": "info" if dataset else "warning",
            "confidence": 0.88 if dataset else 0.72,
            "status": "open",
            "source_asset_ids": dataset_sources,
        },
        {
            "id": new_id("ins"),
            "insight_type": "assumption_risk",
            "title": "Assumption risk concentration",
            "summary": assumption_risk_summary(assumptions, high_risk),
            "severity": "warning" if high_risk else "info",
            "confidence": 0.82 if assumptions else 0.6,
            "status": "open",
            "source_asset_ids": source_project
            + [{"asset_type": "assumption", "asset_id": item.id} for item in high_risk[:8]],
        },
        {
            "id": new_id("ins"),
            "insight_type": "evaluation_readiness",
            "title": "Evaluation readiness",
            "summary": evaluation_readiness_summary(candidates, approved_specs, splits),
            "severity": evaluation_severity(approved_specs, splits),
            "confidence": 0.84,
            "status": "open",
            "source_asset_ids": source_project
            + [{"asset_type": "evaluation_spec", "asset_id": item.id} for item in approved_specs[:3]]
            + [{"asset_type": "split_manifest", "asset_id": item.id} for item in splits[:3]],
        },
        {
            "id": new_id("ins"),
            "insight_type": "approach_progress",
            "title": "Approach and agent-task progress",
            "summary": approach_progress_summary(ideas),
            "severity": "info" if ideas else "warning",
            "confidence": 0.76 if ideas else 0.58,
            "status": "open",
            "source_asset_ids": source_project + [{"asset_type": "idea", "asset_id": item.id} for item in ideas[:8]],
        },
        {
            "id": new_id("ins"),
            "insight_type": "experiment_result",
            "title": "Current experiment signal",
            "summary": experiment_result_summary(best_run, model_versions),
            "severity": "info" if best_run else "warning",
            "confidence": 0.74 if best_run else 0.52,
            "status": "open",
            "source_asset_ids": source_project
            + ([{"asset_type": "experiment_run", "asset_id": best_run.id}] if best_run else [])
            + [{"asset_type": "model_version", "asset_id": item.id} for item in model_versions[:3]],
        },
    ]
    return payloads


def build_metric_cards_spec(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    profile: dict[str, Any],
    assumptions: list[Assumption],
    candidates: list[EvaluationCandidate],
    specs: list[EvaluationSpec],
    splits: list[SplitManifest],
    runs: list[ExperimentRun],
    reports: list[Report],
    model_versions: list[ModelVersion],
) -> dict[str, Any]:
    high_risk_count = sum(1 for item in assumptions if item.risk_level in {"high", "blocking", "deployment_blocking"})
    cards = [
        {"label": "Rows", "value": dataset.row_count if dataset else 0, "detail": "latest dataset snapshot"},
        {"label": "Columns", "value": dataset.column_count if dataset else 0, "detail": "latest dataset snapshot"},
        {"label": "Target", "value": project.target_column or "unset", "detail": "project metadata"},
        {"label": "Missing Cells", "value": profile.get("missing_cell_count", "-"), "detail": "profile artifact"},
        {"label": "High Risk Assumptions", "value": high_risk_count, "detail": "risk review queue"},
        {"label": "Evaluation Candidates", "value": len(candidates), "detail": "candidate designs"},
        {"label": "Approved Specs", "value": sum(1 for item in specs if item.status == "approved"), "detail": "primary evaluation design"},
        {"label": "Split Manifests", "value": len(splits), "detail": "reproducible splits"},
        {"label": "Succeeded Runs", "value": sum(1 for item in runs if item.status == "succeeded"), "detail": "experiment history"},
        {"label": "Model Versions", "value": len(model_versions), "detail": "registered model packages"},
        {"label": "Reports", "value": len(reports), "detail": "artifact-backed summaries"},
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Project Readiness Metrics",
        "chart_type": "metric_cards",
        "data": cards,
        "encoding": {"label": "label", "value": "value", "detail": "detail"},
        "empty_state": "Upload data and run workflow steps to populate project readiness metrics.",
    }


def build_assumption_risk_spec(assumptions: list[Assumption]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for assumption in assumptions:
        counts[assumption.risk_level] = counts.get(assumption.risk_level, 0) + 1
    rows = [{"label": risk, "count": count} for risk, count in sorted(counts.items())]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Assumption Risk Breakdown",
        "chart_type": "category_bars",
        "data": rows,
        "encoding": {"x": "label", "y": "count", "color": "label"},
        "empty_state": "Run dataset understanding to infer assumptions and risk levels.",
    }


def build_evaluation_readiness_spec(
    *,
    candidates: list[EvaluationCandidate],
    specs: list[EvaluationSpec],
    splits: list[SplitManifest],
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    approved_specs = [item for item in specs if item.status == "approved"]
    rows = [
        {
            "stage": "Evaluation candidates",
            "status": "ready" if candidates else "missing",
            "count": len(candidates),
            "detail": "Primary, alternative, rejected, and scenario candidates.",
        },
        {
            "stage": "Approved EvaluationSpec",
            "status": "ready" if approved_specs else "missing",
            "count": len(approved_specs),
            "detail": "Primary evaluation design that should not be destructively changed.",
        },
        {
            "stage": "SplitManifest",
            "status": "ready" if splits else "missing",
            "count": len(splits),
            "detail": "Train/valid/test membership used by baselines and agents.",
        },
        {
            "stage": "Experiment results",
            "status": "ready" if any(run.status == "succeeded" for run in runs) else "missing",
            "count": sum(1 for run in runs if run.status == "succeeded"),
            "detail": "Runs with metrics against the approved split.",
        },
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Evaluation Readiness",
        "chart_type": "stage_status",
        "data": rows,
        "encoding": {"stage": "stage", "status": "status", "count": "count", "detail": "detail"},
        "empty_state": "Design evaluation, approve a spec, generate a split, and run experiments.",
    }


def build_leaderboard_spec(runs: list[ExperimentRun]) -> dict[str, Any]:
    metric_rows = []
    for rank, run in enumerate(sorted([run for run in runs if run.status == "succeeded"], key=leaderboard_sort_key), start=1):
        metrics = loads_json(run.metrics_json, {})
        metric_rows.append(
            {
                "rank": rank,
                "run_id": run.id,
                "runner_type": run.runner_type,
                "status": run.status,
                "primary_metric_name": metrics.get("primary_metric_name"),
                "primary_metric_value": metrics.get("primary_metric_value"),
                "model_version_id": run.model_version_id,
            }
        )
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Leaderboard Primary Metric",
        "chart_type": "leaderboard_bar",
        "data": metric_rows,
        "encoding": {
            "x": "run_id",
            "y": "primary_metric_value",
            "color": "runner_type",
            "tooltip": ["rank", "run_id", "status", "primary_metric_name", "model_version_id"],
        },
        "empty_state": "Run experiments before comparing leaderboard metrics.",
    }


def persist_visualization_spec(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    spec: dict[str, Any],
    source_artifact_id: str | None,
) -> tuple[VisualizationSpec, Artifact]:
    chart_type = str(spec["chart_type"])
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"visualization_spec_{chart_type}_{new_id('vizart')}",
        filename=f"{chart_type}.json",
        payload=spec,
        metadata={"project_id": project.id, "chart_type": chart_type, "source_artifact_id": source_artifact_id},
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title=str(spec["title"]),
        chart_type=chart_type,
        spec_json=dumps_json(spec),
        source_artifact_id=source_artifact_id,
        artifact_id=artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(visualization)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarizes",
    )
    if source_artifact_id:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_artifact_id,
            to_asset_type="visualization_spec",
            to_asset_id=visualization.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="visualization_spec",
        from_asset_id=visualization.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    return visualization, artifact


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    )


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def load_profile(profile_artifact: Artifact | None) -> dict[str, Any]:
    if profile_artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact_primary_path(profile_artifact).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def evidence_strength(confidence: float) -> str:
    if confidence >= 0.85:
        return "strong"
    if confidence >= 0.65:
        return "medium"
    return "weak"


def dataset_readiness_summary(dataset: DatasetSnapshot | None) -> str:
    if dataset is None:
        return "No dataset snapshot is available yet; reports and visualizations should stay in planning mode."
    return (
        f"Latest DatasetSnapshot has {dataset.row_count or 'unknown'} rows and "
        f"{dataset.column_count or 'unknown'} columns, with schema hash {dataset.schema_hash[:12]}."
    )


def assumption_risk_summary(assumptions: list[Assumption], high_risk: list[Assumption]) -> str:
    if not assumptions:
        return "No assumptions have been inferred yet; run data understanding before trusting evaluation or approach choices."
    if high_risk:
        return f"{len(high_risk)} high-risk assumptions require review before deployment-oriented decisions."
    return f"{len(assumptions)} assumptions are tracked, with no high-risk assumption currently open."


def evaluation_readiness_summary(
    candidates: list[EvaluationCandidate],
    approved_specs: list[EvaluationSpec],
    splits: list[SplitManifest],
) -> str:
    if not candidates:
        return "Evaluation candidates have not been generated; model work should wait for evaluation design."
    if not approved_specs:
        return "Evaluation candidates exist, but no primary EvaluationSpec has been approved."
    if not splits:
        return "An EvaluationSpec is approved, but no SplitManifest exists yet."
    return "Evaluation is ready for controlled runs: candidates, an approved EvaluationSpec, and SplitManifest are present."


def evaluation_severity(approved_specs: list[EvaluationSpec], splits: list[SplitManifest]) -> str:
    if not approved_specs or not splits:
        return "warning"
    return "info"


def approach_progress_summary(ideas: list[Idea]) -> str:
    if not ideas:
        return "No approach Ideas have been generated yet; create a research brief and candidate Ideas before agent execution."
    completed = sum(1 for idea in ideas if idea.status == "agent_stub_completed")
    return f"{len(ideas)} Ideas are tracked; {completed} have completed the LocalStubAgentRunner contract path."


def experiment_result_summary(best_run: ExperimentRun | None, model_versions: list[ModelVersion]) -> str:
    if best_run is None:
        return "No successful experiment run is available; leaderboard and model reports are not decision-ready."
    metrics = loads_json(best_run.metrics_json, {})
    metric_name = metrics.get("primary_metric_name", "primary_metric")
    metric_value = metrics.get("primary_metric_value", "-")
    return (
        f"Best current run is {best_run.id} with {metric_name}={metric_value}; "
        f"{len(model_versions)} model version records are registered."
    )


def best_leaderboard_run(runs: list[ExperimentRun]) -> ExperimentRun | None:
    if not runs:
        return None
    return sorted(runs, key=leaderboard_sort_key)[0]


def leaderboard_sort_key(run: ExperimentRun) -> tuple[int, float]:
    metrics = loads_json(run.metrics_json, {})
    metric_name = metrics.get("primary_metric_name")
    metric_value = metrics.get("primary_metric_value")
    if metric_value is None:
        return (1, 0.0)
    value = float(metric_value)
    if metric_name in {"rmse", "mae", "log_loss"}:
        return (0, value)
    return (0, -value)
