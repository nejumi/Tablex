from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    Evidence,
    Job,
    Project,
    Report,
    VisualizationSpec,
)
from tabular_harness.services.agent_result_ingestion import load_json_artifact
from tabular_harness.services.approach import (
    first_sentence,
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge


@dataclass(frozen=True)
class RelationalFeaturePlanResult:
    plan: dict[str, Any]
    report_md: str
    plan_artifact: Artifact
    report: Report
    report_artifact: Artifact
    evidence: Evidence
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def create_relational_feature_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
) -> RelationalFeaturePlanResult:
    context = collect_relational_feature_context(db, project.id)
    relational_catalog_artifact = context.get("relational_catalog")
    if relational_catalog_artifact is None:
        raise ValueError("RelationalCatalog artifact is required before relational feature planning")
    plan = build_relational_feature_plan(
        project,
        relational_catalog=load_json_artifact(relational_catalog_artifact),
        context=context,
        recommended_assets=recommended_relational_assets(db),
    )
    plan_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_plan",
        name=f"relational_feature_plan_{new_id('rfp')}",
        filename="relational_feature_plan.json",
        payload=plan,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_id": plan["source_summary"].get("benchmark_id"),
            "relational_catalog_artifact_id": relational_catalog_artifact.id,
            "table_count": plan["table_coverage"]["table_count"],
            "supporting_table_count": plan["table_coverage"]["supporting_table_count"],
            "relationship_count": plan["table_coverage"]["relationship_count"],
            "aggregation_candidate_count": len(plan["aggregation_candidates"]),
            "high_risk_count": len([item for item in plan["risk_register"] if item["risk_level"] == "high"]),
        },
    )
    report_md = render_relational_feature_report(plan)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_report",
        name=f"relational_feature_report_{new_id('rfpr')}",
        filename="relational_feature_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_plan_artifact_id": plan_artifact.id,
            "benchmark_id": plan["source_summary"].get("benchmark_id"),
            "aggregation_candidate_count": len(plan["aggregation_candidates"]),
            "high_risk_count": len([item for item in plan["risk_register"] if item["risk_level"] == "high"]),
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="relational_feature_report",
        title="Relational Feature Plan",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(source_asset_refs(plan_artifact.id, context)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_relational_feature_visualization(plan)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"relational_feature_visualization_{new_id('vizart')}",
        filename="relational_feature_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_plan_artifact_id": plan_artifact.id,
            "visualization_role": "relational_feature_plan",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Relational Feature Plan",
        chart_type="stage_status",
        spec_json=dumps_json(visualization_payload),
        source_artifact_id=plan_artifact.id,
        artifact_id=visualization_artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(visualization)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="relational_feature_plan",
        summary=(
            f"Relational feature plan found {len(plan['aggregation_candidates'])} aggregation candidates "
            f"across {plan['table_coverage']['supporting_table_count']} supporting tables."
        ),
        strength="medium" if plan["aggregation_candidates"] else "weak",
        source_artifact_id=plan_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "relational_catalog_artifact_id": relational_catalog_artifact.id,
                "high_risk_count": len([item for item in plan["risk_register"] if item["risk_level"] == "high"]),
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_relational_feature_lineage(
        db,
        project=project,
        job=job,
        context=context,
        plan_artifact=plan_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
    )
    return RelationalFeaturePlanResult(
        plan=plan,
        report_md=report_md,
        plan_artifact=plan_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=[plan_artifact.id, report_artifact.id, visualization_artifact.id],
    )


def collect_relational_feature_context(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "relational_catalog": latest_project_artifact(db, project_id, "relational_catalog"),
        "benchmark_import_manifest": latest_project_artifact(db, project_id, "benchmark_import_manifest"),
        "benchmark_scenario_pack": latest_project_artifact(db, project_id, "benchmark_scenario_pack"),
        "benchmark_collection_plan": latest_project_artifact(db, project_id, "benchmark_collection_plan"),
        "data_quality_gate": latest_project_artifact(db, project_id, "data_quality_gate"),
        "evaluation_spec": latest_project_artifact(db, project_id, "evaluation_spec"),
        "split_manifest": latest_project_artifact(db, project_id, "split_manifest"),
    }


def build_relational_feature_plan(
    project: Project,
    *,
    relational_catalog: dict[str, Any],
    context: dict[str, Artifact | None],
    recommended_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    tables = list_value(relational_catalog.get("tables"))
    primary = dict_value(relational_catalog.get("primary_table"))
    relationships = list_value(relational_catalog.get("relationships"))
    relational_catalog_artifact = context.get("relational_catalog")
    benchmark_scenario_pack_artifact = context.get("benchmark_scenario_pack")
    benchmark_collection_plan_artifact = context.get("benchmark_collection_plan")
    aggregation_candidates = build_aggregation_candidates(tables, relationships, primary)
    risk_register = build_relational_risk_register(relational_catalog, aggregation_candidates)
    return {
        "schema_version": "relational_feature_plan.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "source_summary": {
            "benchmark_id": relational_catalog.get("benchmark_id"),
            "benchmark_name": relational_catalog.get("benchmark_name"),
            "relational_catalog_artifact_id": relational_catalog_artifact.id
            if relational_catalog_artifact
            else None,
            "benchmark_scenario_pack_artifact_id": benchmark_scenario_pack_artifact.id
            if benchmark_scenario_pack_artifact
            else None,
            "benchmark_collection_plan_artifact_id": benchmark_collection_plan_artifact.id
            if benchmark_collection_plan_artifact
            else None,
        },
        "table_coverage": table_coverage(relational_catalog, tables, relationships),
        "join_key_candidates": join_key_candidates(relationships),
        "aggregation_candidates": aggregation_candidates,
        "time_aware_requirements": time_aware_requirements(tables, primary),
        "risk_register": risk_register,
        "deferred_agent_questions": deferred_agent_questions(relational_catalog, risk_register),
        "recommended_skill_references": recommended_assets,
        "artifact_expectations": relational_artifact_expectations(),
        "agent_task_handoff": {
            "use_as_plan_not_recipe": True,
            "fit_aggregations_on_training_folds_only": True,
            "must_respect_split_manifest": True,
            "requires_prediction_time_availability_review": True,
            "scenario_compare": ["primary_table_only", "candidate_relational_aggregates"],
        },
    }


def table_coverage(
    relational_catalog: dict[str, Any],
    tables: list[Any],
    relationships: list[Any],
) -> dict[str, Any]:
    table_items = [dict_value(table) for table in tables]
    supporting = [table for table in table_items if not table.get("is_primary")]
    return {
        "table_count": int(relational_catalog.get("table_count") or len(table_items)),
        "supporting_table_count": len(supporting),
        "relationship_count": len(relationships),
        "target_locations": list_value(relational_catalog.get("target_locations")),
        "table_discovery_truncated": bool(relational_catalog.get("table_discovery_truncated")),
        "supporting_tables": [
            {
                "table_name": table.get("table_name"),
                "path": table.get("path"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
                "key_candidate_count": len(list_value(table.get("key_candidates"))),
                "time_candidate_count": len(list_value(table.get("time_candidates"))),
            }
            for table in supporting
        ],
    }


def join_key_candidates(relationships: list[Any]) -> list[dict[str, Any]]:
    candidates = []
    for relationship in relationships[:40]:
        item = dict_value(relationship)
        candidates.append(
            {
                "left_table": item.get("left_table"),
                "right_table": item.get("right_table"),
                "left_column": item.get("left_column"),
                "right_column": item.get("right_column"),
                "relation_type": item.get("relation_type"),
                "confidence": item.get("confidence"),
                "evidence": item.get("evidence"),
                "validation_required": True,
            }
        )
    return candidates


def build_aggregation_candidates(
    tables: list[Any],
    relationships: list[Any],
    primary_table: dict[str, Any],
) -> list[dict[str, Any]]:
    table_by_name = {str(table.get("table_name")): dict_value(table) for table in tables if isinstance(table, dict)}
    primary_names = {str(table.get("table_name")) for table in tables if isinstance(table, dict) and table.get("is_primary")}
    candidates: list[dict[str, Any]] = []
    for relationship in relationships:
        item = dict_value(relationship)
        left = str(item.get("left_table") or "")
        right = str(item.get("right_table") or "")
        if left in primary_names:
            supporting_name = right
            join_key = item.get("right_column")
            primary_key = item.get("left_column")
        elif right in primary_names:
            supporting_name = left
            join_key = item.get("left_column")
            primary_key = item.get("right_column")
        else:
            continue
        supporting = table_by_name.get(supporting_name, {})
        profiles = [dict_value(profile) for profile in list_value(supporting.get("column_profiles"))]
        numeric_columns = feature_columns(profiles, join_key, primary_table, kind="numeric")
        categorical_columns = feature_columns(profiles, join_key, primary_table, kind="categorical")
        time_columns = [str(value) for value in list_value(supporting.get("time_candidates"))]
        if numeric_columns:
            candidates.append(
                {
                    "candidate_id": f"{supporting_name}_numeric_aggregates",
                    "supporting_table": supporting_name,
                    "join_key": join_key,
                    "primary_key": primary_key,
                    "feature_family": "numeric_aggregations",
                    "columns": numeric_columns[:12],
                    "aggregations": ["count", "mean", "min", "max", "sum", "std"],
                    "fold_safety": "fit aggregation definitions and imputers on training folds only",
                    "requires_point_in_time_filter": bool(time_columns),
                    "time_columns": time_columns,
                }
            )
        if categorical_columns:
            candidates.append(
                {
                    "candidate_id": f"{supporting_name}_categorical_summaries",
                    "supporting_table": supporting_name,
                    "join_key": join_key,
                    "primary_key": primary_key,
                    "feature_family": "categorical_summaries",
                    "columns": categorical_columns[:12],
                    "aggregations": ["count", "nunique", "mode_or_top_rate"],
                    "fold_safety": "fit category vocabularies on training folds only",
                    "requires_point_in_time_filter": bool(time_columns),
                    "time_columns": time_columns,
                }
            )
    return candidates[:30]


def feature_columns(
    profiles: list[dict[str, Any]],
    join_key: Any,
    primary_table: dict[str, Any],
    *,
    kind: str,
) -> list[str]:
    excluded = {
        str(join_key),
        str(primary_table.get("target_column") or ""),
        str(primary_table.get("entity_id_column") or ""),
        str(primary_table.get("group_column") or ""),
    }
    result: list[str] = []
    for profile in profiles:
        name = str(profile.get("name") or "")
        dtype = str(profile.get("physical_type") or "").upper()
        lower = name.lower()
        if not name or name in excluded or any(token in lower for token in ("target", "label", "status_final")):
            continue
        is_numeric = any(token in dtype for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "BIGINT"))
        is_textish = any(token in dtype for token in ("VARCHAR", "TEXT", "STRING", "CHAR"))
        if kind == "numeric" and is_numeric:
            result.append(name)
        elif kind == "categorical" and is_textish:
            result.append(name)
    return result


def time_aware_requirements(tables: list[Any], primary_table: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = []
    primary_time = primary_table.get("time_column")
    if primary_time:
        requirements.append(
            {
                "requirement": f"Use primary decision time column `{primary_time}` as the cutoff when creating relational aggregates.",
                "risk_level": "high",
            }
        )
    for table in [dict_value(item) for item in tables]:
        time_columns = list_value(table.get("time_candidates"))
        if time_columns:
            requirements.append(
                {
                    "requirement": f"Confirm point-in-time availability for `{table.get('table_name')}` time columns: {', '.join(str(value) for value in time_columns)}.",
                    "risk_level": "high",
                }
            )
    if not requirements:
        requirements.append(
            {
                "requirement": "No reliable time columns were inferred; require a user/domain assumption before claiming production realism.",
                "risk_level": "medium",
            }
        )
    return requirements


def build_relational_risk_register(
    relational_catalog: dict[str, Any],
    aggregation_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    risks = [
        {
            "risk": "Supporting table joins may introduce post-outcome or unavailable-at-prediction-time fields.",
            "risk_level": "high",
            "fallback_policy": "scenario_compare",
        },
        {
            "risk": "Aggregation features must be generated inside train folds and applied to validation/test by key only.",
            "risk_level": "high",
            "fallback_policy": "require_before_deployment",
        },
    ]
    for note in list_value(relational_catalog.get("risk_notes"))[:6]:
        risks.append({"risk": str(note), "risk_level": "medium", "fallback_policy": "infer_and_continue"})
    if not aggregation_candidates:
        risks.append(
            {
                "risk": "No aggregation candidates were inferred from current relationship hints.",
                "risk_level": "medium",
                "fallback_policy": "exclude_until_confirmed",
            }
        )
    return risks


def deferred_agent_questions(
    relational_catalog: dict[str, Any],
    risk_register: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    benchmark_id = relational_catalog.get("benchmark_id") or "current benchmark"
    questions = [
        {
            "question": f"For {benchmark_id}, which supporting tables are known to be available at prediction time?",
            "fallback_policy": "scenario_compare",
            "risk_level": "high",
        },
        {
            "question": "Should validation be group-aware or time-aware before accepting relational feature lift?",
            "fallback_policy": "conservative_default",
            "risk_level": "high",
        },
    ]
    if any(item["risk_level"] == "high" for item in risk_register):
        questions.append(
            {
                "question": "Which relational feature families should be blocked until domain confirmation?",
                "fallback_policy": "exclude_until_confirmed",
                "risk_level": "medium",
            }
        )
    return questions


def recommended_relational_assets(db: Session) -> list[dict[str, Any]]:
    names = {
        "relational_aggregation_recipe",
        "causal_time_lag_rolling_features",
        "tabular_gradient_boosting_strategy",
        "xgboost_mixed_type_baseline",
    }
    assets = list(db.scalars(select(Asset).where(Asset.name.in_(names)).order_by(Asset.name)).all())
    return [
        {
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "latest_version_id": asset.latest_version_id,
            "reason": "Relevant to relational feature planning, leakage controls, or mixed-type baseline comparison.",
        }
        for asset in assets
    ]


def relational_artifact_expectations() -> list[dict[str, Any]]:
    return [
        {"asset_type": "feature_recipe", "required": True, "purpose": "encode confirmed relational aggregations"},
        {"asset_type": "evaluation_spec", "required": True, "purpose": "lock validation before comparing lift"},
        {"asset_type": "split_manifest", "required": True, "purpose": "enforce fold-safe aggregation generation"},
        {"asset_type": "evidence", "required": True, "purpose": "support prediction-time availability claims"},
        {"asset_type": "visualization_spec", "required": True, "purpose": "summarize relational coverage and risk"},
    ]


def render_relational_feature_report(plan: dict[str, Any]) -> str:
    coverage = plan["table_coverage"]
    lines = [
        "# Relational Feature Plan",
        "",
        f"Project: {plan['project']['name']} (`{plan['project']['id']}`)",
        "",
        "## Coverage",
        "",
        f"- Benchmark: {plan['source_summary'].get('benchmark_name') or plan['source_summary'].get('benchmark_id')}",
        f"- Tables: {coverage['table_count']}",
        f"- Supporting tables: {coverage['supporting_table_count']}",
        f"- Relationships: {coverage['relationship_count']}",
        f"- Aggregation candidates: {len(plan['aggregation_candidates'])}",
        "",
        "## Aggregation Candidates",
        "",
    ]
    for candidate in plan["aggregation_candidates"][:12]:
        lines.append(
            f"- {candidate['candidate_id']}: {candidate['feature_family']} on `{candidate['supporting_table']}` "
            f"by `{candidate['join_key']}` ({len(candidate['columns'])} columns)."
        )
    if not plan["aggregation_candidates"]:
        lines.append("- No aggregation candidates inferred yet.")
    lines.extend(["", "## Time And Leakage Requirements", ""])
    for requirement in plan["time_aware_requirements"]:
        lines.append(f"- {requirement['requirement']} ({requirement['risk_level']})")
    lines.extend(["", "## Risk Register", ""])
    for risk in plan["risk_register"]:
        lines.append(f"- {risk['risk']} ({risk['risk_level']}; {risk['fallback_policy']})")
    lines.extend(["", "## AgentTask Handoff", ""])
    for question in plan["deferred_agent_questions"]:
        lines.append(f"- {question['question']} ({question['fallback_policy']})")
    return "\n".join(lines).strip() + "\n"


def build_relational_feature_visualization(plan: dict[str, Any]) -> dict[str, Any]:
    coverage = plan["table_coverage"]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Relational Feature Plan",
        "chart_type": "stage_status",
        "data": [
            {"stage": "Tables", "status": "ready", "count": coverage["table_count"]},
            {"stage": "Supporting", "status": "ready", "count": coverage["supporting_table_count"]},
            {"stage": "Relationships", "status": "ready" if coverage["relationship_count"] else "warning", "count": coverage["relationship_count"]},
            {"stage": "Candidates", "status": "ready" if plan["aggregation_candidates"] else "warning", "count": len(plan["aggregation_candidates"])},
            {"stage": "High risk", "status": "warning", "count": len([item for item in plan["risk_register"] if item["risk_level"] == "high"])},
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "count"]},
        "empty_state": "Import a multi-table benchmark to create relational feature planning context.",
    }


def create_relational_feature_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    context: dict[str, Artifact | None],
    plan_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    if job is not None:
        for artifact in [plan_artifact, report_artifact, visualization_artifact]:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="job",
                from_asset_id=job.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="produces",
            )
    for source_artifact in context.values():
        if source_artifact is None:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_artifact.id,
            to_asset_type="artifact",
            to_asset_id=plan_artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=plan_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=plan_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=plan_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualizes",
    )


def source_asset_refs(plan_artifact_id: str, context: dict[str, Artifact | None]) -> list[dict[str, str]]:
    refs = [{"asset_type": "artifact", "asset_id": plan_artifact_id}]
    for artifact in context.values():
        if artifact is not None:
            refs.append({"asset_type": "artifact", "asset_id": artifact.id})
    return refs


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
