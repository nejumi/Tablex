from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
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
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.profiler import quote_ident, read_sql

PREVIEW_ROW_LIMIT = 200
SAFE_FEATURE_NAME = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(frozen=True)
class RelationalFeatureRecipeResult:
    recipe: dict[str, Any]
    preview_profile: dict[str, Any]
    recipe_artifact: Artifact
    preview_artifact: Artifact
    preview_profile_artifact: Artifact
    report: Report
    report_artifact: Artifact
    evidence: Evidence
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def build_relational_feature_recipe(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
) -> RelationalFeatureRecipeResult:
    context = collect_relational_recipe_context(db, project.id)
    plan_artifact = require_artifact(context.get("relational_feature_plan"), "RelationalFeaturePlan")
    catalog_artifact = require_artifact(context.get("relational_catalog"), "RelationalCatalog")
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        raise ValueError("DatasetSnapshot is required before building a relational feature recipe")
    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    if dataset_artifact is None:
        raise ValueError("DatasetSnapshot artifact not found")
    supporting_artifacts = supporting_table_artifacts(db, project.id)
    plan = load_json_artifact(plan_artifact)
    catalog = load_json_artifact(catalog_artifact)
    compiled = compile_recipe(
        project=project,
        dataset=dataset,
        plan=plan,
        catalog=catalog,
        plan_artifact=plan_artifact,
        catalog_artifact=catalog_artifact,
        supporting_artifacts=supporting_artifacts,
        split_manifest_artifact=context.get("split_manifest"),
    )
    preview_csv, preview_profile = execute_recipe_preview(
        recipe=compiled,
        dataset_artifact=dataset_artifact,
        supporting_artifacts=supporting_artifacts,
        target_column=project.target_column,
    )
    compiled["execution_summary"] = {
        "status": "preview_succeeded",
        "preview_row_count": preview_profile["preview_row_count"],
        "preview_column_count": preview_profile["preview_column_count"],
        "generated_feature_count": len(preview_profile["generated_feature_columns"]),
        "executed_step_count": len(compiled["steps"]),
        "deferred_step_count": len(compiled["deferred_steps"]),
    }
    recipe_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_recipe",
        name=f"relational_feature_recipe_{new_id('rfr')}",
        filename="relational_feature_recipe.json",
        payload=compiled,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "dataset_snapshot_id": dataset.id,
            "benchmark_id": compiled["source_summary"].get("benchmark_id"),
            "relational_feature_plan_artifact_id": plan_artifact.id,
            "relational_catalog_artifact_id": catalog_artifact.id,
            "executed_step_count": len(compiled["steps"]),
            "deferred_step_count": len(compiled["deferred_steps"]),
            "generated_feature_count": len(preview_profile["generated_feature_columns"]),
            "preview_row_count": preview_profile["preview_row_count"],
        },
    )
    preview_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_preview",
        name=f"relational_feature_preview_{new_id('rfpv')}",
        filename="relational_feature_preview.csv",
        text=preview_csv,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "dataset_snapshot_id": dataset.id,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "preview_row_count": preview_profile["preview_row_count"],
            "generated_feature_count": len(preview_profile["generated_feature_columns"]),
        },
    )
    preview_profile["relational_feature_recipe_artifact_id"] = recipe_artifact.id
    preview_profile["relational_feature_preview_artifact_id"] = preview_artifact.id
    preview_profile_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_preview_profile",
        name=f"relational_feature_preview_profile_{new_id('rfpp')}",
        filename="relational_feature_preview_profile.json",
        payload=preview_profile,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "relational_feature_preview_artifact_id": preview_artifact.id,
            "preview_row_count": preview_profile["preview_row_count"],
            "generated_feature_count": len(preview_profile["generated_feature_columns"]),
        },
    )
    report_md = render_relational_feature_recipe_report(compiled, preview_profile)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_feature_recipe_report",
        name=f"relational_feature_recipe_report_{new_id('rfrr')}",
        filename="relational_feature_recipe_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "generated_feature_count": len(preview_profile["generated_feature_columns"]),
            "deferred_step_count": len(compiled["deferred_steps"]),
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="relational_feature_recipe_report",
        title="Relational Feature Recipe",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(source_asset_refs(recipe_artifact.id, context, supporting_artifacts)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_relational_feature_recipe_visualization(compiled, preview_profile)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"relational_feature_recipe_visualization_{new_id('vizart')}",
        filename="relational_feature_recipe_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "relational_feature_recipe_artifact_id": recipe_artifact.id,
            "visualization_role": "relational_feature_recipe",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Relational Feature Recipe",
        chart_type="stage_status",
        spec_json=dumps_json(visualization_payload),
        source_artifact_id=recipe_artifact.id,
        artifact_id=visualization_artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(visualization)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="relational_feature_recipe",
        summary=(
            f"Relational feature recipe preview generated {len(preview_profile['generated_feature_columns'])} "
            f"features from {len(compiled['steps'])} executed aggregation steps."
        ),
        strength="medium" if compiled["steps"] else "weak",
        source_artifact_id=recipe_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "preview_artifact_id": preview_artifact.id,
                "deferred_step_count": len(compiled["deferred_steps"]),
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_recipe_lineage(
        db,
        project=project,
        job=job,
        context=context,
        dataset=dataset,
        supporting_artifacts=supporting_artifacts,
        recipe_artifact=recipe_artifact,
        preview_artifact=preview_artifact,
        preview_profile_artifact=preview_profile_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
    )
    artifact_ids = [
        recipe_artifact.id,
        preview_artifact.id,
        preview_profile_artifact.id,
        report_artifact.id,
        visualization_artifact.id,
    ]
    return RelationalFeatureRecipeResult(
        recipe=compiled,
        preview_profile=preview_profile,
        recipe_artifact=recipe_artifact,
        preview_artifact=preview_artifact,
        preview_profile_artifact=preview_profile_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def collect_relational_recipe_context(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "relational_feature_plan": latest_project_artifact(db, project_id, "relational_feature_plan"),
        "relational_catalog": latest_project_artifact(db, project_id, "relational_catalog"),
        "benchmark_scenario_pack": latest_project_artifact(db, project_id, "benchmark_scenario_pack"),
        "benchmark_collection_plan": latest_project_artifact(db, project_id, "benchmark_collection_plan"),
        "data_quality_gate": latest_project_artifact(db, project_id, "data_quality_gate"),
        "evaluation_spec": latest_project_artifact(db, project_id, "evaluation_spec"),
        "split_manifest": latest_project_artifact(db, project_id, "split_manifest"),
    }


def compile_recipe(
    *,
    project: Project,
    dataset: DatasetSnapshot,
    plan: dict[str, Any],
    catalog: dict[str, Any],
    plan_artifact: Artifact,
    catalog_artifact: Artifact,
    supporting_artifacts: list[Artifact],
    split_manifest_artifact: Artifact | None,
) -> dict[str, Any]:
    support_by_table = support_artifacts_by_table(supporting_artifacts)
    leakage_by_table = leakage_suspects_by_table(catalog)
    steps: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for raw_candidate in list_value(plan.get("aggregation_candidates")):
        candidate = dict_value(raw_candidate)
        supporting_table = str(candidate.get("supporting_table") or "")
        support_artifact = support_by_table.get(supporting_table)
        if support_artifact is None:
            deferred.append(deferred_step(candidate, "supporting_table_artifact_missing"))
            continue
        if bool(candidate.get("requires_point_in_time_filter")):
            deferred.append(deferred_step(candidate, "point_in_time_filter_not_confirmed"))
            continue
        columns = [
            str(column)
            for column in list_value(candidate.get("columns"))
            if safe_candidate_column(str(column), project.target_column, leakage_by_table.get(supporting_table, set()))
        ]
        if candidate.get("feature_family") != "categorical_summaries" and not columns:
            deferred.append(deferred_step(candidate, "no_safe_columns_after_leakage_filter"))
            continue
        steps.append(
            {
                "step_id": safe_feature_name(str(candidate.get("candidate_id") or f"step_{len(steps) + 1}")),
                "source_candidate_id": candidate.get("candidate_id"),
                "supporting_table": supporting_table,
                "supporting_artifact_id": support_artifact.id,
                "primary_key": candidate.get("primary_key"),
                "join_key": candidate.get("join_key"),
                "feature_family": candidate.get("feature_family"),
                "columns": columns[:12],
                "aggregations": executable_aggregations(candidate),
                "fold_safety": "preview only; production training must fit aggregations inside training folds",
                "prediction_time_availability": "requires confirmation before deployment",
            }
        )
    return {
        "schema_version": "relational_feature_recipe.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "source_summary": {
            "dataset_snapshot_id": dataset.id,
            "relational_feature_plan_artifact_id": plan_artifact.id,
            "relational_catalog_artifact_id": catalog_artifact.id,
            "split_manifest_artifact_id": split_manifest_artifact.id if split_manifest_artifact else None,
            "benchmark_id": plan.get("source_summary", {}).get("benchmark_id") if isinstance(plan.get("source_summary"), dict) else catalog.get("benchmark_id"),
            "benchmark_name": catalog.get("benchmark_name"),
        },
        "execution_scope": {
            "mode": "preview_only",
            "max_preview_rows": PREVIEW_ROW_LIMIT,
            "model_training": False,
            "small_supporting_artifacts_only": True,
            "requires_split_manifest_for_training": True,
        },
        "steps": steps,
        "deferred_steps": deferred,
        "safety": {
            "target_column_excluded": project.target_column,
            "holdout_tables_excluded": True,
            "leakage_suspect_columns_excluded": True,
            "point_in_time_unconfirmed_candidates_deferred": True,
            "fit_on_training_folds_only": True,
        },
        "artifact_expectations": [
            {"asset_type": "relational_feature_recipe", "purpose": "record executable preview steps"},
            {"asset_type": "relational_feature_preview", "purpose": "preview generated features without model training"},
            {"asset_type": "feature_recipe", "purpose": "future confirmed production recipe"},
            {"asset_type": "evidence", "purpose": "support prediction-time availability claims"},
        ],
    }


def execute_recipe_preview(
    *,
    recipe: dict[str, Any],
    dataset_artifact: Artifact,
    supporting_artifacts: list[Artifact],
    target_column: str | None,
) -> tuple[str, dict[str, Any]]:
    support_by_id = {artifact.id: artifact for artifact in supporting_artifacts}
    con = duckdb.connect(database=":memory:")
    con.execute(f"CREATE VIEW primary_view AS SELECT * FROM {read_sql(artifact_primary_path(dataset_artifact))}")
    primary_columns = view_columns(con, "primary_view")
    select_columns = ["p.__tablex_row_index"]
    join_clauses: list[str] = []
    generated_columns: list[str] = []
    executed_steps: list[dict[str, Any]] = []
    deferred_steps = list(recipe["deferred_steps"])
    for index, step in enumerate(recipe["steps"]):
        support_artifact = support_by_id.get(str(step.get("supporting_artifact_id")))
        if support_artifact is None:
            deferred_steps.append(deferred_step(step, "supporting_artifact_not_found_at_execution"))
            continue
        primary_key = str(step.get("primary_key") or "")
        join_key = str(step.get("join_key") or "")
        if primary_key not in primary_columns:
            deferred_steps.append(deferred_step(step, "primary_key_missing"))
            continue
        support_view = f"support_view_{index}"
        con.execute(f"CREATE VIEW {support_view} AS SELECT * FROM {read_sql(artifact_primary_path(support_artifact))}")
        support_columns = view_columns(con, support_view)
        if join_key not in support_columns:
            deferred_steps.append(deferred_step(step, "support_join_key_missing"))
            continue
        expressions, feature_names = aggregate_expressions(step, support_columns)
        if not expressions:
            deferred_steps.append(deferred_step(step, "no_executable_aggregate_expressions"))
            continue
        alias = f"agg_{index}"
        join_clauses.append(
            "LEFT JOIN ("
            f"SELECT {quote_ident(join_key)} AS __join_key_{index}, {', '.join(expressions)} "
            f"FROM {support_view} GROUP BY {quote_ident(join_key)}"
            f") {alias} ON p.{quote_ident(primary_key)} = {alias}.__join_key_{index}"
        )
        for feature_name in feature_names:
            generated_columns.append(feature_name)
            select_columns.append(f"{alias}.{quote_ident(feature_name)} AS {quote_ident(feature_name)}")
        executed_steps.append({"step_id": step.get("step_id"), "generated_features": feature_names})
    preview_primary_key = first_primary_key(recipe, primary_columns)
    if preview_primary_key:
        select_columns.insert(1, f"p.{quote_ident(preview_primary_key)} AS {quote_ident(preview_primary_key)}")
    con.execute("CREATE TEMP TABLE primary_rows AS SELECT row_number() OVER () - 1 AS __tablex_row_index, * FROM primary_view")
    query = (
        f"SELECT {', '.join(select_columns)} FROM primary_rows p "
        f"{' '.join(join_clauses)} LIMIT {PREVIEW_ROW_LIMIT}"
    )
    rows = con.execute(query).fetchall()
    columns = [str(item[0]) for item in con.description]
    if target_column and target_column in columns:
        target_index = columns.index(target_column)
        columns.pop(target_index)
        rows = [tuple(value for index, value in enumerate(row) if index != target_index) for row in rows]
    csv_text = rows_to_csv(columns, rows)
    profile = {
        "schema_version": "relational_feature_preview_profile.v1",
        "preview_row_count": len(rows),
        "preview_column_count": len(columns),
        "generated_feature_columns": generated_columns,
        "executed_steps": executed_steps,
        "deferred_steps": deferred_steps,
        "source_dataset_artifact_id": dataset_artifact.id,
        "preview_limit": PREVIEW_ROW_LIMIT,
    }
    return csv_text, profile


def aggregate_expressions(step: dict[str, Any], support_columns: set[str]) -> tuple[list[str], list[str]]:
    expressions: list[str] = []
    feature_names: list[str] = []
    prefix = safe_feature_name(str(step.get("step_id") or "rel"))
    count_name = safe_feature_name(f"{prefix}__row_count")
    expressions.append(f"COUNT(*) AS {quote_ident(count_name)}")
    feature_names.append(count_name)
    family = str(step.get("feature_family") or "")
    for column in [str(value) for value in list_value(step.get("columns")) if str(value) in support_columns]:
        if family == "categorical_summaries":
            feature_name = safe_feature_name(f"{prefix}__{column}__nunique")
            expressions.append(f"APPROX_COUNT_DISTINCT({quote_ident(column)}) AS {quote_ident(feature_name)}")
            feature_names.append(feature_name)
            continue
        for aggregation, function_name in [
            ("mean", "AVG"),
            ("min", "MIN"),
            ("max", "MAX"),
            ("sum", "SUM"),
            ("std", "STDDEV_SAMP"),
        ]:
            if aggregation not in set(str(item) for item in list_value(step.get("aggregations"))):
                continue
            feature_name = safe_feature_name(f"{prefix}__{column}__{aggregation}")
            expressions.append(f"{function_name}({quote_ident(column)}) AS {quote_ident(feature_name)}")
            feature_names.append(feature_name)
    return expressions, feature_names


def view_columns(con: duckdb.DuckDBPyConnection, view_name: str) -> set[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {view_name}").fetchall()
    return {str(row[0]) for row in rows}


def rows_to_csv(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def render_relational_feature_recipe_report(recipe: dict[str, Any], preview_profile: dict[str, Any]) -> str:
    lines = [
        "# Relational Feature Recipe",
        "",
        f"Benchmark: {recipe['source_summary'].get('benchmark_name') or recipe['source_summary'].get('benchmark_id')}",
        "",
        "## Execution Summary",
        "",
        f"- Mode: {recipe['execution_scope']['mode']}",
        f"- Executed steps: {len(recipe['steps'])}",
        f"- Deferred steps: {len(recipe['deferred_steps'])}",
        f"- Generated features: {len(preview_profile['generated_feature_columns'])}",
        f"- Preview rows: {preview_profile['preview_row_count']}",
        "",
        "## Executed Steps",
        "",
    ]
    for step in recipe["steps"]:
        lines.append(f"- {step['step_id']}: {step['feature_family']} from `{step['supporting_table']}` by `{step['join_key']}`")
    if not recipe["steps"]:
        lines.append("- No steps were executed.")
    lines.extend(["", "## Deferred Steps", ""])
    for step in recipe["deferred_steps"]:
        lines.append(f"- {step.get('candidate_id') or step.get('step_id')}: {step['reason']}")
    if not recipe["deferred_steps"]:
        lines.append("- No steps were deferred.")
    lines.extend(["", "## Safety", ""])
    for key, value in recipe["safety"].items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines).strip() + "\n"


def build_relational_feature_recipe_visualization(recipe: dict[str, Any], preview_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Relational Feature Recipe",
        "chart_type": "stage_status",
        "data": [
            {"stage": "Executed steps", "status": "ready" if recipe["steps"] else "warning", "count": len(recipe["steps"])},
            {"stage": "Deferred steps", "status": "warning" if recipe["deferred_steps"] else "ready", "count": len(recipe["deferred_steps"])},
            {"stage": "Generated features", "status": "ready" if preview_profile["generated_feature_columns"] else "warning", "count": len(preview_profile["generated_feature_columns"])},
            {"stage": "Preview rows", "status": "ready" if preview_profile["preview_row_count"] else "warning", "count": preview_profile["preview_row_count"]},
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "count"]},
        "empty_state": "Build a relational feature recipe preview from a relational feature plan.",
    }


def create_recipe_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    context: dict[str, Artifact | None],
    dataset: DatasetSnapshot,
    supporting_artifacts: list[Artifact],
    recipe_artifact: Artifact,
    preview_artifact: Artifact,
    preview_profile_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    if job is not None:
        for artifact in [recipe_artifact, preview_artifact, preview_profile_artifact, report_artifact, visualization_artifact]:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="job",
                from_asset_id=job.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="produces",
            )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=recipe_artifact.id,
        relation_type="informs",
    )
    for source_artifact in [*context.values(), *supporting_artifacts]:
        if source_artifact is None:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_artifact.id,
            to_asset_type="artifact",
            to_asset_id=recipe_artifact.id,
            relation_type="informs",
        )
    for artifact, relation in [
        (preview_artifact, "materializes_preview"),
        (preview_profile_artifact, "profiles_preview"),
        (report_artifact, "materializes_report"),
        (visualization_artifact, "materializes_visualization"),
    ]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=recipe_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type=relation,
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=recipe_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=recipe_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=recipe_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualizes",
    )


def supporting_table_artifacts(db: Session, project_id: str) -> list[Artifact]:
    return list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "benchmark_supporting_table")
            .order_by(Artifact.created_at.desc())
        ).all()
    )


def support_artifacts_by_table(artifacts: list[Artifact]) -> dict[str, Artifact]:
    mapping: dict[str, Artifact] = {}
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        table_name = metadata.get("table_name")
        if isinstance(table_name, str) and table_name:
            mapping.setdefault(table_name, artifact)
    return mapping


def leakage_suspects_by_table(catalog: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for table in [dict_value(item) for item in list_value(catalog.get("tables"))]:
        table_name = str(table.get("table_name") or "")
        result[table_name] = {str(value) for value in list_value(table.get("leakage_name_suspects"))}
    return result


def executable_aggregations(candidate: dict[str, Any]) -> list[str]:
    family = str(candidate.get("feature_family") or "")
    if family == "categorical_summaries":
        return ["count", "nunique"]
    allowed = {"count", "mean", "min", "max", "sum", "std"}
    return [str(item) for item in list_value(candidate.get("aggregations")) if str(item) in allowed] or ["count"]


def first_primary_key(recipe: dict[str, Any], primary_columns: set[str]) -> str | None:
    for step in recipe["steps"]:
        primary_key = str(step.get("primary_key") or "")
        if primary_key in primary_columns:
            return primary_key
    return None


def safe_candidate_column(column: str, target_column: str | None, leakage_suspects: set[str]) -> bool:
    lower = column.lower()
    if target_column and column == target_column:
        return False
    if column in leakage_suspects:
        return False
    return not any(token in lower for token in ("target", "label", "final_status", "test", "holdout"))


def deferred_step(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id") or candidate.get("source_candidate_id") or candidate.get("step_id"),
        "supporting_table": candidate.get("supporting_table"),
        "feature_family": candidate.get("feature_family"),
        "reason": reason,
        "fallback_policy": "exclude_until_confirmed",
    }


def safe_feature_name(value: str) -> str:
    cleaned = SAFE_FEATURE_NAME.sub("_", value).strip("_").lower()
    return cleaned[:96] or "rel_feature"


def require_artifact(artifact: Artifact | None, label: str) -> Artifact:
    if artifact is None:
        raise ValueError(f"{label} artifact is required")
    return artifact


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    )


def source_asset_refs(
    recipe_artifact_id: str,
    context: dict[str, Artifact | None],
    supporting_artifacts: list[Artifact],
) -> list[dict[str, str]]:
    refs = [{"asset_type": "artifact", "asset_id": recipe_artifact_id}]
    for artifact in [*context.values(), *supporting_artifacts]:
        if artifact is not None:
            refs.append({"asset_type": "artifact", "asset_id": artifact.id})
    return refs


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
