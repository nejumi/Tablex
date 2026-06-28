from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

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
from tabular_harness.services.agent_result_ingestion import load_json_artifact
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge


@dataclass(frozen=True)
class ResearchRunnerStubResult:
    manifest: dict[str, Any]
    manifest_artifact: Artifact
    findings_report: Report
    findings_report_artifact: Artifact
    citation_manifest_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    evidence: Evidence
    artifact_ids: list[str]


def run_research_source_pack_local_stub(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    source_pack_artifact: Artifact,
    job: Job,
) -> ResearchRunnerStubResult:
    if source_pack_artifact.project_id != project.id:
        raise ValueError("Research Source Pack belongs to a different project")
    if source_pack_artifact.asset_type != "research_source_pack":
        raise ValueError("Artifact is not a research_source_pack")
    pack = load_json_artifact(source_pack_artifact)
    if pack.get("schema_version") != "research_source_pack.v1":
        raise ValueError("Artifact is not a valid Research Source Pack")

    manifest = build_research_run_manifest(pack, source_pack_artifact, job)
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_run_manifest",
        name=f"research_run_manifest_{job.id}",
        filename="research_run_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "source_pack_artifact_id": source_pack_artifact.id,
            "runner": manifest["runner"],
            "execution_status": manifest["execution_status"],
            "query_count": manifest["query_count"],
            "external_network_accessed": manifest["external_network_accessed"],
        },
    )
    citation_manifest = build_research_source_citation_manifest(pack, source_pack_artifact, manifest)
    citation_manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="source_citation_manifest",
        name=f"research_source_citation_manifest_{job.id}",
        filename="source_citation_manifest.json",
        payload=citation_manifest,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "source_pack_artifact_id": source_pack_artifact.id,
            "research_run_manifest_artifact_id": manifest_artifact.id,
            "source_count": len(citation_manifest["evidence_sources"]),
            "citation_count": len(citation_manifest["citations"]),
            "external_network_accessed": False,
        },
    )
    report_md = render_research_findings_report(pack, manifest, citation_manifest)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_findings_report",
        name=f"research_findings_report_{job.id}",
        filename="research_findings_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "source_pack_artifact_id": source_pack_artifact.id,
            "research_run_manifest_artifact_id": manifest_artifact.id,
            "source_citation_manifest_artifact_id": citation_manifest_artifact.id,
            "report_type": "research_findings_report",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="research_findings_report",
        title="Controlled Research Runner Stub",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "artifact", "asset_id": source_pack_artifact.id},
                {"asset_type": "artifact", "asset_id": manifest_artifact.id},
                {"asset_type": "artifact", "asset_id": citation_manifest_artifact.id},
                {"asset_type": "job", "asset_id": job.id},
            ]
        ),
        status="draft",
        created_by_type="research_runner",
    )
    db.add(report)
    visualization_payload = build_research_runner_visualization(pack, manifest, citation_manifest)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"research_runner_visualization_{job.id}",
        filename="research_runner_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "source_pack_artifact_id": source_pack_artifact.id,
            "visualization_role": "research_runner_stub",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Controlled Research Runner Stub",
        chart_type="stage_status",
        spec_json=dumps_json(visualization_payload),
        source_artifact_id=manifest_artifact.id,
        artifact_id=visualization_artifact.id,
        status="ready",
        created_by_type="research_runner",
    )
    db.add(visualization)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="research_runner_stub",
        summary=(
            f"LocalStubResearchRunner inspected {manifest['query_count']} controlled queries without external "
            "network access."
        ),
        strength="weak",
        source_artifact_id=manifest_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id,
                "source_pack_artifact_id": source_pack_artifact.id,
                "research_run_manifest_artifact_id": manifest_artifact.id,
                "source_citation_manifest_artifact_id": citation_manifest_artifact.id,
                "external_network_accessed": False,
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_research_runner_lineage(
        db,
        project=project,
        job=job,
        source_pack_artifact=source_pack_artifact,
        manifest_artifact=manifest_artifact,
        citation_manifest_artifact=citation_manifest_artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        evidence=evidence,
    )
    artifact_ids = [
        manifest_artifact.id,
        report_artifact.id,
        citation_manifest_artifact.id,
        visualization_artifact.id,
    ]
    return ResearchRunnerStubResult(
        manifest=manifest,
        manifest_artifact=manifest_artifact,
        findings_report=report,
        findings_report_artifact=report_artifact,
        citation_manifest_artifact=citation_manifest_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        evidence=evidence,
        artifact_ids=artifact_ids,
    )


def build_research_run_manifest(pack: dict[str, Any], source_pack_artifact: Artifact, job: Job) -> dict[str, Any]:
    queries = list_value(pack.get("controlled_queries"))
    findings = [
        {
            "finding_id": f"finding_{index}",
            "query": query_text(query),
            "status": "not_executed",
            "finding": "LocalStubResearchRunner did not resolve this query; controlled retrieval remains future work.",
            "required_follow_up": "Run an approved controlled web/literature/Skill research runner and return citations.",
        }
        for index, query in enumerate(queries[:24], start=1)
    ]
    return {
        "schema_version": "research_run_manifest.v1",
        "job_id": job.id,
        "source_pack_artifact_id": source_pack_artifact.id,
        "runner": "local_stub_research_runner",
        "execution_status": "not_executed",
        "external_network_accessed": False,
        "connector_credentials_materialized": False,
        "source_policy": dict_value(pack.get("source_policy")),
        "citation_requirements": dict_value(pack.get("citation_requirements")),
        "freshness_expectations": dict_value(pack.get("freshness_expectations")),
        "query_count": len(queries),
        "project_source_count": len(list_value(pack.get("project_sources"))),
        "library_source_count": len(list_value(pack.get("library_sources"))),
        "benchmark_source_count": len(list_value(pack.get("benchmark_sources"))),
        "findings": findings,
        "runner_handoff": {
            "research_task_type": "controlled_research_stub",
            "future_runner_contract": [
                "resolve approved controlled queries",
                "return source summaries with retrieved_at",
                "return citations linked to report claims",
                "avoid secrets and connector credentials",
            ],
        },
    }


def build_research_source_citation_manifest(
    pack: dict[str, Any],
    source_pack_artifact: Artifact,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    evidence_sources = [
        {
            "source_id": "research_source_pack",
            "source_type": "harness_artifact",
            "title": "Research Source Pack",
            "url": None,
            "artifact_id": source_pack_artifact.id,
            "summary": "Harness-owned source policy, query candidates, and citation requirements.",
            "verification_status": "local_artifact",
            "retrieved_at": None,
            "freshness": "not_applicable",
            "risk_level": "low",
            "metadata": {
                "query_count": manifest["query_count"],
                "project_source_count": manifest["project_source_count"],
                "library_source_count": manifest["library_source_count"],
            },
        }
    ]
    citations = [
        {
            "citation_id": "cit_research_stub_policy_only",
            "source_id": "research_source_pack",
            "claim": "LocalStubResearchRunner inspected the source pack but did not retrieve external sources.",
            "usage_context": "research_findings_report",
            "confidence": 1.0,
            "requires_follow_up": True,
            "metadata": {
                "external_network_accessed": False,
                "connector_credentials_materialized": False,
            },
        }
    ]
    return {
        "schema_version": "source_citation_manifest.v1",
        "task_id": f"research_task_{source_pack_artifact.id}",
        "runner": manifest["runner"],
        "execution_status": manifest["execution_status"],
        "external_network_accessed": False,
        "connector_credentials_materialized": False,
        "research_source_pack_artifact_id": source_pack_artifact.id,
        "source_policy": manifest["source_policy"],
        "citation_requirements": manifest["citation_requirements"],
        "freshness_expectations": manifest["freshness_expectations"],
        "evidence_sources": evidence_sources,
        "citations": citations,
        "report_citations": [
            {
                "section": "Stub Findings",
                "citation_ids": [citation["citation_id"] for citation in citations],
                "note": "This citation records research-run policy compliance only.",
            }
        ],
    }


def render_research_findings_report(
    pack: dict[str, Any],
    manifest: dict[str, Any],
    citation_manifest: dict[str, Any],
) -> str:
    lines = [
        "# Controlled Research Runner Stub",
        "",
        f"- Runner: {manifest['runner']}",
        f"- Execution status: {manifest['execution_status']}",
        f"- Source Pack artifact: `{manifest['source_pack_artifact_id']}`",
        f"- External network accessed: {str(manifest['external_network_accessed']).lower()}",
        f"- Connector credentials materialized: {str(manifest['connector_credentials_materialized']).lower()}",
        "",
        "## Source Policy",
        "",
        f"- Network default: {dict_value(pack.get('source_policy')).get('network_default', 'unknown')}",
        "- Secrets and connector credentials are not available to this runner.",
        "",
        "## Stub Findings",
        "",
    ]
    findings = list_value(manifest.get("findings"))
    if findings:
        for finding in findings[:12]:
            if isinstance(finding, dict):
                lines.append(f"- {finding.get('query')}: {finding.get('finding')}")
    else:
        lines.append("- No controlled queries were available in the source pack.")
    lines.extend(
        [
            "",
            "## Citation Audit",
            "",
            f"- Evidence sources: {len(list_value(citation_manifest.get('evidence_sources')))}",
            f"- Citations: {len(list_value(citation_manifest.get('citations')))}",
            "- Current citations describe policy compliance only, not external modeling evidence.",
            "",
            "## Next Actions",
            "",
            "- Enable a controlled research runner only after network and source policy approval.",
            "- Store retrieved source summaries, citations, Evidence, and report references before using external claims.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_research_runner_visualization(
    pack: dict[str, Any],
    manifest: dict[str, Any],
    citation_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Controlled Research Runner Stub",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": "Controlled queries",
                "status": "warning" if manifest["query_count"] == 0 else "ready",
                "count": manifest["query_count"],
                "detail": "Query candidates are present but not resolved by LocalStub.",
            },
            {
                "stage": "Project sources",
                "status": "ready" if list_value(pack.get("project_sources")) else "warning",
                "count": len(list_value(pack.get("project_sources"))),
                "detail": "Harness-owned project artifacts are available as source context.",
            },
            {
                "stage": "Citations",
                "status": "ready" if list_value(citation_manifest.get("citations")) else "warning",
                "count": len(list_value(citation_manifest.get("citations"))),
                "detail": "Stub citations are policy-audit citations only.",
            },
            {
                "stage": "External access",
                "status": "ready",
                "count": 0,
                "detail": "External network access was not performed.",
            },
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "detail"]},
        "empty_state": "Research runner results will appear after a Research Source Pack is executed.",
    }


def create_research_runner_lineage(
    db: Session,
    *,
    project: Project,
    job: Job,
    source_pack_artifact: Artifact,
    manifest_artifact: Artifact,
    citation_manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
    evidence: Evidence,
) -> None:
    for artifact in [manifest_artifact, citation_manifest_artifact, report_artifact, visualization_artifact]:
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
            from_asset_id=source_pack_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="research_source_for",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=manifest_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=manifest_artifact.id,
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
        from_asset_id=manifest_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarized_by",
    )


def query_text(query: Any) -> str:
    if isinstance(query, dict):
        value = query.get("query") or query.get("question") or query.get("topic")
        return str(value) if value else str(query)
    return str(query)


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
