from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    DatasetSnapshot,
    EvaluationSpec,
    Evidence,
    Job,
    Project,
    Report,
)
from tabular_harness.services.approach import (
    create_research_plan,
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
class ResearchSourcePackResult:
    pack: dict[str, Any]
    report: Report
    evidence: Evidence
    pack_artifact: Artifact
    report_artifact: Artifact
    research_plan_artifact: Artifact


def create_research_source_pack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    job: Job | None = None,
) -> ResearchSourcePackResult:
    research_plan_artifact = latest_project_artifact(db, project.id, "research_plan")
    if research_plan_artifact is None:
        research_plan = create_research_plan(
            db,
            store=store,
            project=project,
            dataset=dataset,
            evaluation_spec=evaluation_spec,
        )
        research_plan_artifact = research_plan.artifact
    research_plan_payload = load_json_artifact(research_plan_artifact)
    context_artifacts = collect_context_artifacts(db, project.id)
    assets = list(db.scalars(select(Asset).where(Asset.status == "active").order_by(Asset.asset_type, Asset.name).limit(32)).all())
    pack = {
        "schema_version": "research_source_pack.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "research_plan_artifact_id": research_plan_artifact.id,
        "generated_at": research_plan_artifact.created_at.isoformat(),
        "source_policy": build_source_policy(research_plan_payload),
        "freshness_expectations": {
            "retrieved_at_required": True,
            "prefer_current_sources_for": ["libraries", "benchmark access policy", "competition rules", "modeling practice"],
            "stale_source_review": "Runner must flag source claims whose retrieval date or publication context is missing.",
        },
        "citation_requirements": {
            "required_fields": ["title", "url_or_doi", "source_type", "retrieved_at", "claim", "relevance", "risk_level"],
            "quote_policy": "Use short excerpts only; store summaries and links as Evidence.",
            "claim_policy": "External claims must be linked to source_summary Evidence before reports treat them as support.",
        },
        "controlled_queries": research_plan_payload.get("query_plan", []),
        "project_sources": [artifact_source_ref(role, artifact) for role, artifact in context_artifacts.items() if artifact],
        "library_sources": [asset_source_ref(asset) for asset in assets],
        "benchmark_sources": benchmark_source_refs(context_artifacts),
        "evidence_slots": evidence_slots(research_plan_payload),
        "runner_handoff": {
            "may_execute_network_search": False,
            "future_policy": "Only a controlled runner with explicit network approval may resolve query candidates.",
            "agent_must_return": ["source_summary artifacts", "Evidence rows or evidence_set artifact", "report citations"],
            "forbidden": ["secrets", "connector credentials", "credentialed benchmark downloads inside runner"],
        },
    }
    pack_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_source_pack",
        name=f"research_source_pack_{new_id('rsp')}",
        filename="research_source_pack.json",
        payload=pack,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "research_plan_artifact_id": research_plan_artifact.id,
            "query_count": len(pack["controlled_queries"]) if isinstance(pack["controlled_queries"], list) else 0,
            "project_source_count": len(pack["project_sources"]),
            "library_source_count": len(pack["library_sources"]),
            "network_default": pack["source_policy"]["network_default"],
        },
    )
    report_md = render_research_source_report(pack)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_source_report",
        name=f"research_source_report_{new_id('rsr')}",
        filename="research_source_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "research_plan_artifact_id": research_plan_artifact.id,
            "source_pack_artifact_id": pack_artifact.id,
            "report_type": "research_source_report",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="research_source_report",
        title="Research Source Pack",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [{"asset_type": "artifact", "asset_id": research_plan_artifact.id}, {"asset_type": "artifact", "asset_id": pack_artifact.id}]
        ),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="research_source_pack",
        summary=f"Research Source Pack defines {len(pack['project_sources'])} project sources and {len(pack['library_sources'])} library sources for controlled runner handoff.",
        strength="medium",
        source_artifact_id=pack_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "research_plan_artifact_id": research_plan_artifact.id,
                "report_artifact_id": report_artifact.id,
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_research_source_lineage(
        db,
        project=project,
        job=job,
        research_plan_artifact=research_plan_artifact,
        pack_artifact=pack_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        context_artifacts=context_artifacts,
        assets=assets,
    )
    return ResearchSourcePackResult(
        pack=pack,
        report=report,
        evidence=evidence,
        pack_artifact=pack_artifact,
        report_artifact=report_artifact,
        research_plan_artifact=research_plan_artifact,
    )


def collect_context_artifacts(db: Session, project_id: str) -> dict[str, Artifact | None]:
    roles = [
        "research_plan",
        "data_quality_gate",
        "relational_catalog",
        "relational_table_bundle_manifest",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "evaluation_diagnostics",
        "baseline_strategy_plan",
        "benchmark_scenario_pack",
        "benchmark_evidence_pack",
        "decision_dashboard",
        "agent_task_contract",
    ]
    return {role: latest_project_artifact(db, project_id, role) for role in roles}


def build_source_policy(research_plan_payload: dict[str, Any]) -> dict[str, Any]:
    raw_policy = research_plan_payload.get("source_policy")
    source_policy = raw_policy if isinstance(raw_policy, dict) else {}
    return {
        "allowed_source_types": source_policy.get(
            "allowed_source_types",
            ["project_artifacts", "cross_project_asset_library", "controlled_web_search", "literature_search"],
        ),
        "network_default": source_policy.get("network_default", "disabled_until_runner_policy_allows"),
        "credential_policy": source_policy.get(
            "credential_policy",
            {
                "secret_access": "forbidden",
                "connector_credentials": "never_materialized_for_agent",
                "kaggle_credentials": "user_managed_outside_tablex",
            },
        ),
        "citation_requirement": source_policy.get(
            "citation_requirement",
            "External claims must return citation metadata as Evidence or source-summary artifacts.",
        ),
        "ui_completeness_requirement": source_policy.get(
            "ui_completeness_requirement",
            "Reports must be understandable in Tablex without external dashboards.",
        ),
    }


def artifact_source_ref(role: str, artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "source_type": "project_artifact",
        "role": role,
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": {
            key: metadata.get(key)
            for key in [
                "benchmark_id",
                "dataset_snapshot_id",
                "evaluation_spec_id",
                "split_manifest_id",
                "run_id",
                "report_type",
                "readiness_status",
            ]
            if key in metadata
        },
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def asset_source_ref(asset: Asset) -> dict[str, Any]:
    return {
        "source_type": "cross_project_asset",
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "description": asset.description,
        "latest_version_id": asset.latest_version_id,
        "tags": loads_json(asset.tags_json, []),
        "semantic_tags": loads_json(asset.semantic_tags_json, []),
    }


def benchmark_source_refs(context_artifacts: dict[str, Artifact | None]) -> list[dict[str, Any]]:
    refs = []
    for role in ["benchmark_scenario_pack", "benchmark_evidence_pack", "relational_catalog"]:
        artifact = context_artifacts.get(role)
        if artifact is None:
            continue
        metadata = loads_json(artifact.metadata_json, {})
        benchmark_id = metadata.get("benchmark_id")
        benchmark_ids = metadata.get("benchmark_ids")
        refs.append(
            {
                "source_type": "benchmark_context",
                "role": role,
                "artifact_id": artifact.id,
                "benchmark_id": benchmark_id,
                "benchmark_ids": benchmark_ids if isinstance(benchmark_ids, list) else [],
                "policy": "Benchmark context may guide approach research but does not become a benchmark score claim.",
            }
        )
    return refs


def evidence_slots(research_plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    expected = research_plan_payload.get("expected_evidence")
    if isinstance(expected, list) and expected:
        return [item for item in expected if isinstance(item, dict)]
    return [
        {
            "evidence_type": "source_summary",
            "strength": "medium",
            "required_fields": ["title", "url_or_doi", "retrieved_at", "claim", "relevance"],
        }
    ]


def render_research_source_report(pack: dict[str, Any]) -> str:
    lines = [
        "# Research Source Pack",
        "",
        f"Project: {pack['project']['name']} (`{pack['project']['id']}`)",
        f"ResearchPlan artifact: `{pack['research_plan_artifact_id']}`",
        "",
        "## Policy",
        "",
        f"- Network default: {pack['source_policy']['network_default']}",
        f"- Citation fields: {', '.join(pack['citation_requirements']['required_fields'])}",
        "- Connector credentials and secrets are not materialized for agents.",
        "- External claims must be stored as source-summary Evidence or artifacts.",
        "",
        "## Controlled Queries",
        "",
    ]
    queries = pack["controlled_queries"] if isinstance(pack["controlled_queries"], list) else []
    if queries:
        for item in queries[:12]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('query') or item.get('question') or item.get('topic') or item}")
    else:
        lines.append("- No query candidates are available yet.")
    lines.extend(
        [
            "",
            "## Project Sources",
            "",
        ]
    )
    if pack["project_sources"]:
        for source in pack["project_sources"][:16]:
            lines.append(f"- {source['role']}: `{source['asset_type']}` `{source['artifact_id']}`")
    else:
        lines.append("- No project source artifacts are available yet.")
    lines.extend(["", "## Library Sources", ""])
    if pack["library_sources"]:
        for source in pack["library_sources"][:16]:
            lines.append(f"- {source['asset_type']}: {source['name']} (`{source['asset_id']}`)")
    else:
        lines.append("- No library assets are available yet.")
    lines.extend(["", "## Runner Handoff", ""])
    lines.append("- Network search is not executed by this job.")
    lines.append("- A future controlled runner must return source summaries, Evidence, and report citations.")
    return "\n".join(lines)


def create_research_source_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    research_plan_artifact: Artifact,
    pack_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    context_artifacts: dict[str, Artifact | None],
    assets: list[Asset],
) -> None:
    if job is not None:
        for artifact in [pack_artifact, report_artifact]:
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
        from_asset_id=research_plan_artifact.id,
        to_asset_type="artifact",
        to_asset_id=pack_artifact.id,
        relation_type="defines_source_policy_for",
    )
    for context_artifact in context_artifacts.values():
        if context_artifact is not None:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=context_artifact.id,
                to_asset_type="artifact",
                to_asset_id=pack_artifact.id,
                relation_type="candidate_source_for",
            )
    for asset in assets[:32]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="asset",
            from_asset_id=asset.id,
            to_asset_type="artifact",
            to_asset_id=pack_artifact.id,
            relation_type="candidate_source_for",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pack_artifact.id,
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
        from_asset_id=pack_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )


def load_json_artifact(artifact: Artifact) -> dict[str, Any]:
    try:
        value = json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
