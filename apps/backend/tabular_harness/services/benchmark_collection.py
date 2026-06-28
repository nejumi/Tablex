from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    Evidence,
    Job,
    Project,
    Report,
    VisualizationSpec,
)
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.benchmarks import benchmark_source_card, catalog_datasets


@dataclass(frozen=True)
class BenchmarkCollectionPlanResult:
    plan: dict[str, Any]
    report_md: str
    plan_artifact: Artifact
    report: Report
    report_artifact: Artifact
    evidence: Evidence
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def create_benchmark_collection_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    settings: Settings,
    job: Job | None = None,
) -> BenchmarkCollectionPlanResult:
    plan = build_benchmark_collection_plan(project, settings)
    plan_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_collection_plan",
        name=f"benchmark_collection_plan_{new_id('bcp')}",
        filename="benchmark_collection_plan.json",
        payload=plan,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_count": plan["summary"]["benchmark_count"],
            "credentialed_count": plan["summary"]["credentialed_count"],
            "public_direct_count": plan["summary"]["public_direct_count"],
            "fixture_available_count": plan["summary"]["fixture_available_count"],
            "local_ready_count": plan["summary"]["local_ready_count"],
            "multitable_count": plan["summary"]["multitable_count"],
            "time_series_count": plan["summary"]["time_series_count"],
        },
    )
    report_md = render_benchmark_collection_report(plan)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_collection_report",
        name=f"benchmark_collection_report_{new_id('bcpr')}",
        filename="benchmark_collection_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_collection_plan_artifact_id": plan_artifact.id,
            "benchmark_count": plan["summary"]["benchmark_count"],
            "credentialed_count": plan["summary"]["credentialed_count"],
            "public_direct_count": plan["summary"]["public_direct_count"],
            "fixture_available_count": plan["summary"]["fixture_available_count"],
            "local_ready_count": plan["summary"]["local_ready_count"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="benchmark_collection_report",
        title="Benchmark Collection Plan",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": plan_artifact.id}]),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_benchmark_collection_visualization(plan)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"benchmark_collection_visualization_{new_id('vizart')}",
        filename="benchmark_collection_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "benchmark_collection_plan_artifact_id": plan_artifact.id,
            "visualization_role": "benchmark_collection_plan",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Benchmark Collection Plan",
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
        evidence_type="benchmark_collection_plan",
        summary=(
            f"Benchmark collection plan covers {plan['summary']['benchmark_count']} catalog entries, "
            f"{plan['summary']['credentialed_count']} credentialed sources, and "
            f"{plan['summary']['public_direct_count']} credential-free direct sources."
        ),
        strength="medium",
        source_artifact_id=plan_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "local_ready_count": plan["summary"]["local_ready_count"],
                "fixture_available_count": plan["summary"]["fixture_available_count"],
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_benchmark_collection_lineage(
        db,
        project=project,
        job=job,
        plan_artifact=plan_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
    )
    return BenchmarkCollectionPlanResult(
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


def build_benchmark_collection_plan(project: Project, settings: Settings) -> dict[str, Any]:
    entries = [benchmark_collection_entry(item, settings) for item in catalog_datasets()]
    entries.sort(key=lambda item: (int(item["priority_rank"]), str(item["name"])))
    summary = benchmark_collection_summary(entries)
    return {
        "schema_version": "benchmark_collection_plan.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "summary": summary,
        "recommended_initial_suite": recommended_initial_suite(entries),
        "benchmarks": entries,
        "source_audit": source_audit(entries),
        "credential_policy": {
            "secret_access": "forbidden",
            "connector_credentials": "never_materialized",
            "kaggle_credentials": "user_managed_outside_tablex",
            "agent_task_contract_policy": "credentials are never inserted into prompts, contracts, or runner workspaces",
        },
        "runner_guidance": [
            "Use credential-free public workflows for repeatable CI and smoke tests.",
            "Use Home Credit Default Risk as the primary real-world multi-table benchmark after the user downloads files outside Tablex.",
            "Treat fixtures as product smoke data only; never report fixture scores as benchmark performance.",
            "For time-series benchmarks, require time-aware EvaluationSpec or a documented scenario comparison before accepting results.",
        ],
    }


def benchmark_collection_entry(benchmark: dict[str, Any], settings: Settings) -> dict[str, Any]:
    card = benchmark_source_card(benchmark, settings=settings)
    access = dict_value(card.get("access"))
    readiness = dict_value(card.get("import_readiness"))
    table_bundle = dict_value(card.get("table_bundle"))
    source_verification = dict_value(card.get("source_verification"))
    fixture = dict_value(card.get("fixture"))
    benchmark_id = str(benchmark["id"])
    actions = recommended_actions(
        access=access,
        readiness=readiness,
        fixture=fixture,
        table_bundle=table_bundle,
        benchmark_id=benchmark_id,
    )
    priority = benchmark_priority(benchmark, access=access, table_bundle=table_bundle)
    return {
        "benchmark_id": benchmark_id,
        "name": benchmark["name"],
        "source_kind": benchmark["source_kind"],
        "source_url": benchmark["source_url"],
        "scale": benchmark.get("scale"),
        "task_types": list_value(benchmark.get("task_types")),
        "modality_tags": list_value(benchmark.get("modality_tags")),
        "scenario": dict_value(benchmark.get("scenario")),
        "priority_bucket": priority["bucket"],
        "priority_rank": priority["rank"],
        "access": access,
        "local_readiness": readiness,
        "table_bundle": table_bundle,
        "fixture": fixture,
        "source_verification": source_verification,
        "official_sources": list_value(card.get("official_sources")),
        "credential_policy": dict_value(card.get("credential_policy")),
        "recommended_actions": actions,
        "collection_status": collection_status(access, readiness, fixture),
    }


def benchmark_collection_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "benchmark_count": len(entries),
        "credentialed_count": count_where(entries, lambda item: item["access"].get("requires_account") is True),
        "public_direct_count": count_where(entries, lambda item: item["access"].get("supports_direct_download") is True),
        "fixture_available_count": count_where(entries, lambda item: item["fixture"].get("available") is True),
        "local_ready_count": count_where(entries, lambda item: item["local_readiness"].get("local_ready") is True),
        "multitable_count": count_where(entries, lambda item: item["table_bundle"].get("kind") == "multi_table_bundle"),
        "time_series_count": count_where(
            entries,
            lambda item: "time_series" in item["modality_tags"] or "forecasting" in item["task_types"],
        ),
        "primary_recommendation": "Start with credential-free public workflows for CI, then Home Credit fixture smoke, then real Home Credit after user-managed Kaggle download.",
    }


def source_audit(entries: list[dict[str, Any]]) -> dict[str, Any]:
    source_count = sum(len(entry["official_sources"]) for entry in entries)
    return {
        "official_source_count": source_count,
        "catalog_verified_count": count_where(
            entries,
            lambda item: item["source_verification"].get("status") == "verified_from_catalog_sources",
        ),
        "credentialed_source_count": count_where(entries, lambda item: item["access"].get("requires_account") is True),
        "external_network_accessed": False,
        "notes": [
            "Source cards use catalog metadata and official source URLs; this endpoint does not download external data.",
            "Credentialed competition files remain user-managed under HARNESS_DATA_DIR/benchmarks.",
        ],
    }


def recommended_initial_suite(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_ids = [
        "openml_credit_g",
        "uci_bank_marketing",
        "kaggle_home_credit_default_risk",
        "kaggle_store_sales_forecasting",
        "kaggle_ieee_cis_fraud_detection",
        "kaggle_home_credit_model_stability",
    ]
    by_id = {entry["benchmark_id"]: entry for entry in entries}
    suite = []
    for benchmark_id in preferred_ids:
        entry = by_id.get(benchmark_id)
        if entry is None:
            continue
        suite.append(
            {
                "benchmark_id": benchmark_id,
                "name": entry["name"],
                "priority_bucket": entry["priority_bucket"],
                "collection_status": entry["collection_status"],
                "recommended_first_action": entry["recommended_actions"][0] if entry["recommended_actions"] else None,
            }
        )
    return suite


def benchmark_priority(
    benchmark: dict[str, Any],
    *,
    access: dict[str, Any],
    table_bundle: dict[str, Any],
) -> dict[str, Any]:
    benchmark_id = str(benchmark["id"])
    tags = {str(item) for item in list_value(benchmark.get("modality_tags"))}
    task_types = {str(item) for item in list_value(benchmark.get("task_types"))}
    if benchmark_id == "kaggle_home_credit_default_risk":
        return {"bucket": "primary_real_world_multitable_credit", "rank": 10}
    if benchmark_id == "kaggle_home_credit_model_stability":
        return {"bucket": "advanced_multitable_stability", "rank": 20}
    if access.get("supports_direct_download") is True and "credit_risk" in tags:
        return {"bucket": "credential_free_credit_smoke", "rank": 30}
    if "fraud" in tags:
        return {"bucket": "fraud_imbalance_multitable", "rank": 40}
    if "time_series" in tags or "forecasting" in task_types:
        return {"bucket": "time_series_forecasting", "rank": 50}
    if table_bundle.get("kind") == "multi_table_bundle":
        return {"bucket": "general_multitable", "rank": 60}
    if access.get("supports_direct_download") is True:
        return {"bucket": "credential_free_public_smoke", "rank": 70}
    return {"bucket": "manual_catalog_entry", "rank": 90}


def collection_status(access: dict[str, Any], readiness: dict[str, Any], fixture: dict[str, Any]) -> list[str]:
    status = []
    if readiness.get("local_ready") is True:
        status.append("ready_to_import")
    if fixture.get("available") is True:
        status.append("fixture_smoke_available")
    if access.get("supports_direct_download") is True and access.get("requires_account") is not True:
        status.append("public_workflow_available")
    if access.get("requires_account") is True:
        status.append("credentialed_manual_download_required")
    if not status:
        status.append("manual_setup_required")
    return status


def recommended_actions(
    *,
    access: dict[str, Any],
    readiness: dict[str, Any],
    fixture: dict[str, Any],
    table_bundle: dict[str, Any],
    benchmark_id: str,
) -> list[str]:
    actions: list[str] = []
    if readiness.get("local_ready") is True:
        actions.append("Import the local benchmark files into the project and create a BenchmarkScenarioPack.")
    if access.get("supports_direct_download") is True and access.get("requires_account") is not True:
        actions.append("Run the managed public workflow for repeatable credential-free smoke coverage.")
    if fixture.get("available") is True:
        actions.append("Generate fixture smoke data when real files are unavailable.")
    if access.get("requires_account") is True:
        actions.append(f"Download `{benchmark_id}` with user-managed credentials outside Tablex, then place files under the default benchmark root.")
    if table_bundle.get("kind") == "multi_table_bundle":
        actions.append("Use relational catalog and FeatureRecipe/AgentTask planning before joining supporting tables.")
    if not actions:
        actions.append("Prepare required files manually under HARNESS_DATA_DIR/benchmarks before import.")
    return actions


def render_benchmark_collection_report(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        "# Benchmark Collection Plan",
        "",
        f"Project: {plan['project']['name']} (`{plan['project']['id']}`)",
        "",
        "## Summary",
        "",
        f"- Benchmarks: {summary['benchmark_count']}",
        f"- Credentialed sources: {summary['credentialed_count']}",
        f"- Credential-free direct sources: {summary['public_direct_count']}",
        f"- Fixture-enabled sources: {summary['fixture_available_count']}",
        f"- Local-ready sources: {summary['local_ready_count']}",
        f"- Multi-table sources: {summary['multitable_count']}",
        f"- Time-series sources: {summary['time_series_count']}",
        f"- Primary recommendation: {summary['primary_recommendation']}",
        "",
        "## Recommended Initial Suite",
        "",
    ]
    for item in plan["recommended_initial_suite"]:
        lines.append(
            f"- {item['name']} (`{item['benchmark_id']}`): {item['priority_bucket']}; "
            f"{item['recommended_first_action']}"
        )
    lines.extend(["", "## Catalog Readiness", ""])
    lines.append("| Benchmark | Priority | Access | Local | Bundle | Next action |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for entry in plan["benchmarks"]:
        access = "credentialed" if entry["access"].get("requires_account") else "credential-free"
        local = "ready" if entry["local_readiness"].get("local_ready") else "missing"
        bundle = str(entry["table_bundle"].get("kind") or "-").replace("_", " ")
        action = str(entry["recommended_actions"][0] if entry["recommended_actions"] else "-")
        lines.append(
            f"| {entry['name']} | {entry['priority_bucket']} | {access} | {local} | {bundle} | {action} |"
        )
    lines.extend(["", "## Credential Policy", ""])
    for key, value in plan["credential_policy"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Source Audit", ""])
    audit = plan["source_audit"]
    lines.append(f"- Official source refs: {audit['official_source_count']}")
    lines.append(f"- Catalog-verified entries: {audit['catalog_verified_count']}")
    lines.append(f"- External network accessed by this endpoint: {str(audit['external_network_accessed']).lower()}")
    return "\n".join(lines).strip() + "\n"


def build_benchmark_collection_visualization(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan["summary"]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Benchmark Collection Plan",
        "chart_type": "stage_status",
        "data": [
            {"stage": "Credentialed", "status": "warning", "count": summary["credentialed_count"]},
            {"stage": "Public direct", "status": "ready", "count": summary["public_direct_count"]},
            {"stage": "Fixtures", "status": "ready", "count": summary["fixture_available_count"]},
            {"stage": "Local ready", "status": "ready" if summary["local_ready_count"] else "warning", "count": summary["local_ready_count"]},
            {"stage": "Multi-table", "status": "ready", "count": summary["multitable_count"]},
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "count"]},
        "empty_state": "Create a benchmark collection plan to review source readiness.",
    }


def create_benchmark_collection_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    plan_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="artifact",
        to_asset_id=plan_artifact.id,
        relation_type="plans_benchmark_collection",
    )
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


def count_where(entries: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> int:
    return sum(1 for item in entries if predicate(item))


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
