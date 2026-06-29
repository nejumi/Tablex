from __future__ import annotations

import csv
import io
from collections import Counter
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
    Job,
    Project,
    Report,
    SemanticCatalog,
    SplitManifest,
    VisualizationSpec,
)
from tabular_harness.services.agent_result_ingestion import load_json_artifact
from tabular_harness.services.approach import (
    first_sentence,
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)


@dataclass(frozen=True)
class RelationalFeatureDiagnosticsResult:
    diagnostics: dict[str, Any]
    diagnostics_artifact: Artifact
    report: Report
    report_artifact: Artifact
    evidence: Evidence
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def diagnose_relational_feature_scenarios(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
) -> RelationalFeatureDiagnosticsResult:
    context = collect_diagnostics_context(db, project.id)
    recipe_artifact = require_artifact(context.get("relational_feature_recipe"), "RelationalFeatureRecipe")
    preview_profile_artifact = require_artifact(
        context.get("relational_feature_preview_profile"), "RelationalFeaturePreviewProfile"
    )
    preview_artifact = require_artifact(context.get("relational_feature_preview"), "RelationalFeaturePreview")
    dataset = latest_dataset(db, project.id)
    evaluation_spec = latest_approved_spec(db, project.id)
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    recipe = load_json_artifact(recipe_artifact)
    preview_profile = load_json_artifact(preview_profile_artifact)
    preview_columns, preview_rows = read_preview_csv(preview_artifact)
    generated_columns = [
        str(column)
        for column in list_value(preview_profile.get("generated_feature_columns"))
        if str(column) in preview_columns
    ]
    feature_diagnostics = diagnose_feature_columns(preview_rows, generated_columns)
    diagnostics: dict[str, Any] = {
        "schema_version": "relational_feature_scenario_diagnostics.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "source_summary": {
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "relational_feature_preview_artifact_id": preview_artifact.id,
            "relational_feature_preview_profile_artifact_id": preview_profile_artifact.id,
            "benchmark_id": dict_value(recipe.get("source_summary")).get("benchmark_id"),
        },
        "preview_summary": preview_summary(preview_profile, preview_columns, preview_rows, feature_diagnostics),
        "feature_diagnostics": feature_diagnostics,
        "split_compatibility": split_compatibility(evaluation_spec, split_manifest),
        "target_availability": target_availability(project, dataset, latest_semantic_columns(db, dataset)),
        "deferred_reason_summary": deferred_reason_summary(recipe, preview_profile),
        "scenario_comparison": scenario_comparison(feature_diagnostics, recipe, evaluation_spec, split_manifest),
        "recommended_agent_task_scenarios": recommended_agent_task_scenarios(
            feature_diagnostics,
            recipe,
            evaluation_spec,
            split_manifest,
        ),
        "safety": {
            "model_training_performed": False,
            "preview_only": True,
            "fixed_model_strategy": False,
            "runner_should_select_approach_from_evidence": True,
            "must_respect_split_manifest": True,
            "target_column_excluded_from_preview": project.target_column,
        },
    }
    diagnostics_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_scenario_diagnostics",
        name=f"relational_feature_scenario_diagnostics_{new_id('rfsd')}",
        filename="relational_feature_scenario_diagnostics.json",
        payload=diagnostics,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "relational_feature_preview_artifact_id": preview_artifact.id,
            "generated_feature_count": diagnostics["preview_summary"]["generated_feature_count"],
            "usable_feature_count": diagnostics["preview_summary"]["usable_feature_count"],
            "constant_feature_count": diagnostics["preview_summary"]["constant_feature_count"],
            "high_missing_feature_count": diagnostics["preview_summary"]["high_missing_feature_count"],
            "deferred_step_count": diagnostics["deferred_reason_summary"]["total_deferred_step_count"],
            "scenario_count": len(diagnostics["scenario_comparison"]),
            "split_status": diagnostics["split_compatibility"]["status"],
            "benchmark_id": diagnostics["source_summary"].get("benchmark_id"),
        },
    )
    report_md = render_relational_feature_scenario_report(diagnostics)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_scenario_report",
        name=f"relational_feature_scenario_report_{new_id('rfsr')}",
        filename="relational_feature_scenario_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_scenario_diagnostics_artifact_id": diagnostics_artifact.id,
            "usable_feature_count": diagnostics["preview_summary"]["usable_feature_count"],
            "deferred_step_count": diagnostics["deferred_reason_summary"]["total_deferred_step_count"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="relational_feature_scenario_report",
        title="Relational Feature Scenario Diagnostics",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(source_asset_refs(diagnostics_artifact.id, context)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_relational_feature_scenario_visualization(diagnostics)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"relational_feature_scenario_visualization_{new_id('vizart')}",
        filename="relational_feature_scenario_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_scenario_diagnostics_artifact_id": diagnostics_artifact.id,
            "visualization_role": "relational_feature_scenario_diagnostics",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Relational Feature Scenario Diagnostics",
        chart_type="stage_status",
        spec_json=dumps_json(visualization_payload),
        source_artifact_id=diagnostics_artifact.id,
        artifact_id=visualization_artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(visualization)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="relational_feature_scenario_diagnostics",
        summary=(
            "Relational feature scenario diagnostics found "
            f"{diagnostics['preview_summary']['usable_feature_count']} usable preview features and "
            f"{diagnostics['deferred_reason_summary']['total_deferred_step_count']} deferred steps."
        ),
        strength="medium" if diagnostics["preview_summary"]["usable_feature_count"] else "weak",
        source_artifact_id=diagnostics_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "report_artifact_id": report_artifact.id,
                "visualization_artifact_id": visualization_artifact.id,
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_diagnostics_lineage(
        db,
        project=project,
        job=job,
        context=context,
        diagnostics_artifact=diagnostics_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
    )
    artifact_ids = [diagnostics_artifact.id, report_artifact.id, visualization_artifact.id]
    return RelationalFeatureDiagnosticsResult(
        diagnostics=diagnostics,
        diagnostics_artifact=diagnostics_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def collect_diagnostics_context(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "relational_feature_recipe": latest_project_artifact(db, project_id, "relational_feature_recipe"),
        "relational_feature_preview": latest_project_artifact(db, project_id, "relational_feature_preview"),
        "relational_feature_preview_profile": latest_project_artifact(
            db, project_id, "relational_feature_preview_profile"
        ),
        "relational_feature_plan": latest_project_artifact(db, project_id, "relational_feature_plan"),
        "relational_catalog": latest_project_artifact(db, project_id, "relational_catalog"),
        "evaluation_spec": latest_project_artifact(db, project_id, "evaluation_spec"),
        "split_manifest": latest_project_artifact(db, project_id, "split_manifest"),
    }


def read_preview_csv(preview_artifact: Artifact) -> tuple[list[str], list[dict[str, str]]]:
    text = artifact_primary_path(preview_artifact).read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    columns = [str(column) for column in (reader.fieldnames or [])]
    return columns, [dict(row) for row in reader]


def diagnose_feature_columns(
    rows: list[dict[str, str]],
    generated_columns: list[str],
) -> list[dict[str, Any]]:
    row_count = len(rows)
    diagnostics = []
    for column in generated_columns:
        values = [row.get(column, "") for row in rows]
        non_missing = [value for value in values if value not in {"", "NULL", "None", "nan"}]
        unique_values = set(non_missing)
        missing_count = row_count - len(non_missing)
        missing_rate = missing_count / row_count if row_count else 0.0
        unique_count = len(unique_values)
        diagnostics.append(
            {
                "column": column,
                "non_missing_count": len(non_missing),
                "missing_count": missing_count,
                "missing_rate": round(missing_rate, 6),
                "unique_count": unique_count,
                "is_constant": unique_count <= 1,
                "is_high_missing": missing_rate >= 0.8,
                "is_high_cardinality_preview": row_count > 0 and unique_count >= max(20, int(row_count * 0.7)),
                "sample_values": sorted(unique_values)[:5],
            }
        )
    return diagnostics


def preview_summary(
    preview_profile: dict[str, Any],
    preview_columns: list[str],
    preview_rows: list[dict[str, str]],
    feature_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_feature_count = len(feature_diagnostics)
    constant_count = sum(1 for item in feature_diagnostics if item["is_constant"])
    high_missing_count = sum(1 for item in feature_diagnostics if item["is_high_missing"])
    high_cardinality_count = sum(1 for item in feature_diagnostics if item["is_high_cardinality_preview"])
    usable_count = generated_feature_count - constant_count - high_missing_count
    return {
        "preview_row_count": len(preview_rows),
        "preview_column_count": len(preview_columns),
        "profile_preview_row_count": preview_profile.get("preview_row_count"),
        "generated_feature_count": generated_feature_count,
        "usable_feature_count": max(0, usable_count),
        "constant_feature_count": constant_count,
        "high_missing_feature_count": high_missing_count,
        "high_cardinality_feature_count": high_cardinality_count,
    }


def split_compatibility(
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> dict[str, Any]:
    if evaluation_spec is None:
        return {
            "status": "missing_evaluation_spec",
            "policy": "diagnostics_only_until_evaluation_spec_is_approved",
        }
    return {
        "status": "ready" if split_manifest else "missing_split_manifest",
        "evaluation_spec_id": evaluation_spec.id,
        "split_manifest_id": split_manifest.id if split_manifest else None,
        "split_type": evaluation_spec.split_type,
        "primary_metric": evaluation_spec.primary_metric,
        "policy": "runner_must_respect_approved_evaluation_and_fit_preprocessing_inside_training_folds",
    }


def target_availability(
    project: Project,
    dataset: DatasetSnapshot | None,
    semantic_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    target_column = project.target_column
    column_names = {str(column.get("column_name")) for column in semantic_columns}
    return {
        "target_column": target_column,
        "target_in_primary_dataset": bool(target_column and target_column in column_names),
        "dataset_snapshot_id": dataset.id if dataset else None,
        "policy": "target must remain excluded from preview features and any feature-generation prompt",
    }


def deferred_reason_summary(recipe: dict[str, Any], preview_profile: dict[str, Any]) -> dict[str, Any]:
    deferred_steps = [
        dict_value(item)
        for item in [*list_value(recipe.get("deferred_steps")), *list_value(preview_profile.get("deferred_steps"))]
    ]
    reason_counts = Counter(str(item.get("reason") or "unknown") for item in deferred_steps)
    return {
        "total_deferred_step_count": len(deferred_steps),
        "reason_counts": dict(reason_counts),
        "top_reasons": [{"reason": reason, "count": count} for reason, count in reason_counts.most_common(8)],
    }


def scenario_comparison(
    feature_diagnostics: list[dict[str, Any]],
    recipe: dict[str, Any],
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> list[dict[str, Any]]:
    usable_count = sum(1 for item in feature_diagnostics if not item["is_constant"] and not item["is_high_missing"])
    deferred_count = len(list_value(recipe.get("deferred_steps")))
    return [
        {
            "scenario": "primary_table_only",
            "status": "baseline_required",
            "feature_count": 0,
            "risk_level": "low",
            "next_action": "Keep as a sanity floor and compare any relational lift against it.",
        },
        {
            "scenario": "safe_relational_preview",
            "status": "ready_for_agent_review" if usable_count and split_manifest else "needs_evaluation_context",
            "feature_count": usable_count,
            "risk_level": "medium" if usable_count else "high",
            "next_action": (
                "Runner may consider these features only after confirming prediction-time availability and "
                "fitting preprocessing inside training folds."
            ),
        },
        {
            "scenario": "deferred_relational_features",
            "status": "blocked_until_evidence" if deferred_count else "none_deferred",
            "feature_count": deferred_count,
            "risk_level": "high" if deferred_count else "low",
            "next_action": "Resolve point-in-time, missing-artifact, and leakage questions before implementation.",
        },
        {
            "scenario": "evaluation_readiness",
            "status": "ready" if evaluation_spec and split_manifest else "missing_contract",
            "feature_count": 0,
            "risk_level": "medium" if evaluation_spec and split_manifest else "high",
            "next_action": "Approve EvaluationSpec and SplitManifest before accepting any model comparison.",
        },
    ]


def recommended_agent_task_scenarios(
    feature_diagnostics: list[dict[str, Any]],
    recipe: dict[str, Any],
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> list[dict[str, Any]]:
    usable_features = [
        str(item["column"])
        for item in feature_diagnostics
        if not item["is_constant"] and not item["is_high_missing"]
    ]
    scenarios = [
        {
            "name": "primary_table_only_sanity_floor",
            "priority": 1,
            "description": "Run or inspect a primary-table-only baseline under the approved harness evaluation.",
            "requires": ["evaluation_spec", "split_manifest"],
        },
        {
            "name": "safe_relational_preview_candidate",
            "priority": 2,
            "description": "Consider non-constant, low-missing relational preview features as a candidate scenario.",
            "feature_columns": usable_features[:40],
            "requires": ["prediction_time_availability_review", "fold_safe_preprocessing"],
        },
    ]
    if list_value(recipe.get("deferred_steps")):
        scenarios.append(
            {
                "name": "deferred_relational_feature_research",
                "priority": 3,
                "description": "Investigate deferred relational families with source-backed evidence before coding.",
                "requires": ["domain_confirmation", "evidence", "scenario_compare"],
            }
        )
    if not (evaluation_spec and split_manifest):
        scenarios.append(
            {
                "name": "evaluation_contract_first",
                "priority": 0,
                "description": "Lock EvaluationSpec and SplitManifest before model-training claims.",
                "requires": ["evaluation_spec", "split_manifest"],
            }
        )
    return scenarios


def render_relational_feature_scenario_report(diagnostics: dict[str, Any]) -> str:
    summary = diagnostics["preview_summary"]
    deferred = diagnostics["deferred_reason_summary"]
    lines = [
        "# Relational Feature Scenario Diagnostics",
        "",
        f"Benchmark: {diagnostics['source_summary'].get('benchmark_id') or '-'}",
        "",
        "## Preview Summary",
        "",
        f"- Preview rows: {summary['preview_row_count']}",
        f"- Generated features: {summary['generated_feature_count']}",
        f"- Usable preview features: {summary['usable_feature_count']}",
        f"- Constant features: {summary['constant_feature_count']}",
        f"- High-missing features: {summary['high_missing_feature_count']}",
        "",
        "## Scenario Comparison",
        "",
    ]
    for scenario in diagnostics["scenario_comparison"]:
        lines.append(
            f"- {scenario['scenario']}: {scenario['status']} "
            f"({scenario['risk_level']}; features={scenario['feature_count']})"
        )
    lines.extend(["", "## Deferred Reasons", ""])
    if deferred["top_reasons"]:
        for item in deferred["top_reasons"]:
            lines.append(f"- {item['reason']}: {item['count']}")
    else:
        lines.append("- No deferred relational feature steps.")
    lines.extend(["", "## Recommended AgentTask Scenarios", ""])
    for scenario in diagnostics["recommended_agent_task_scenarios"]:
        lines.append(f"- {scenario['name']}: {scenario['description']}")
    lines.extend(["", "## Safety", ""])
    for key, value in diagnostics["safety"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).strip() + "\n"


def build_relational_feature_scenario_visualization(diagnostics: dict[str, Any]) -> dict[str, Any]:
    summary = diagnostics["preview_summary"]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Relational Feature Scenario Diagnostics",
        "chart_type": "stage_status",
        "data": [
            {"stage": "Generated", "status": "ready", "count": summary["generated_feature_count"]},
            {"stage": "Usable", "status": "ready" if summary["usable_feature_count"] else "warning", "count": summary["usable_feature_count"]},
            {"stage": "Constant", "status": "warning" if summary["constant_feature_count"] else "ready", "count": summary["constant_feature_count"]},
            {"stage": "High missing", "status": "warning" if summary["high_missing_feature_count"] else "ready", "count": summary["high_missing_feature_count"]},
            {"stage": "Deferred", "status": "warning" if diagnostics["deferred_reason_summary"]["total_deferred_step_count"] else "ready", "count": diagnostics["deferred_reason_summary"]["total_deferred_step_count"]},
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "count"]},
        "empty_state": "Build relational feature recipe diagnostics to compare preview scenarios before runner execution.",
    }


def create_diagnostics_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    context: dict[str, Artifact | None],
    diagnostics_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> None:
    if job:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="produces",
        )
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="informs",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="constrains",
        )
    if split_manifest:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="split_manifest",
            from_asset_id=split_manifest.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="constrains",
        )
    for artifact in context.values():
        if artifact is None:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=diagnostics_artifact.id,
            relation_type="informs",
        )
    for artifact, relation in [
        (report_artifact, "materializes_report"),
        (visualization_artifact, "materializes_visualization"),
    ]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=diagnostics_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type=relation,
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=diagnostics_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=diagnostics_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=diagnostics_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualizes",
    )


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest)
        .where(SplitManifest.evaluation_spec_id == spec_id)
        .order_by(SplitManifest.created_at.desc())
    )


def latest_semantic_columns(db: Session, dataset: DatasetSnapshot | None) -> list[dict[str, Any]]:
    if dataset is None:
        return []
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        return []
    columns = loads_json(catalog.columns_json, [])
    return [dict_value(column) for column in columns if isinstance(column, dict)]


def source_asset_refs(
    diagnostics_artifact_id: str,
    context: dict[str, Artifact | None],
) -> list[dict[str, str]]:
    refs = [{"asset_type": "artifact", "asset_id": diagnostics_artifact_id}]
    for artifact in context.values():
        if artifact is not None:
            refs.append({"asset_type": "artifact", "asset_id": artifact.id})
    return refs


def require_artifact(artifact: Artifact | None, label: str) -> Artifact:
    if artifact is None:
        raise ValueError(f"{label} artifact is required")
    return artifact


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
