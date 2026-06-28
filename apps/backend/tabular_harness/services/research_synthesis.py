from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
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
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge


@dataclass(frozen=True)
class ResearchSynthesisResult:
    synthesis: dict[str, Any]
    artifact: Artifact
    report: Report
    report_artifact: Artifact
    evidence: Evidence
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def create_research_finding_synthesis(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job | None = None,
) -> ResearchSynthesisResult:
    context = collect_research_synthesis_context(db, project.id)
    synthesis = build_research_synthesis(project, context)
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_finding_synthesis",
        name=f"research_finding_synthesis_{new_id('rsyn')}",
        filename="research_finding_synthesis.json",
        payload=synthesis,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "research_source_pack_artifact_id": synthesis["source_artifacts"]["research_source_pack"]["artifact_id"]
            if synthesis["source_artifacts"].get("research_source_pack")
            else None,
            "research_run_manifest_artifact_id": synthesis["source_artifacts"]["research_run_manifest"]["artifact_id"]
            if synthesis["source_artifacts"].get("research_run_manifest")
            else None,
            "source_citation_manifest_artifact_id": synthesis["source_artifacts"]["source_citation_manifest"]["artifact_id"]
            if synthesis["source_artifacts"].get("source_citation_manifest")
            else None,
            "finding_count": synthesis["summary"]["finding_count"],
            "citation_count": synthesis["citation_audit"]["citation_count"],
            "external_network_accessed": synthesis["citation_audit"]["external_network_accessed"],
            "has_only_stub_findings": synthesis["summary"]["has_only_stub_findings"],
        },
    )
    report_md = render_research_synthesis_report(synthesis)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_finding_synthesis_report",
        name=f"research_finding_synthesis_report_{new_id('rsynr')}",
        filename="research_finding_synthesis_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "research_finding_synthesis_artifact_id": artifact.id,
            "report_type": "research_finding_synthesis_report",
            "finding_count": synthesis["summary"]["finding_count"],
            "citation_count": synthesis["citation_audit"]["citation_count"],
            "external_network_accessed": synthesis["citation_audit"]["external_network_accessed"],
            "has_only_stub_findings": synthesis["summary"]["has_only_stub_findings"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="research_finding_synthesis_report",
        title="Research Finding Synthesis",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(source_asset_refs(synthesis, artifact.id)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_research_synthesis_visualization(synthesis)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"research_finding_synthesis_visualization_{new_id('vizart')}",
        filename="research_finding_synthesis_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "research_finding_synthesis_artifact_id": artifact.id,
            "visualization_role": "research_finding_synthesis",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Research Finding Synthesis",
        chart_type="stage_status",
        spec_json=dumps_json(visualization_payload),
        source_artifact_id=artifact.id,
        artifact_id=visualization_artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(visualization)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="research_finding_synthesis",
        summary=(
            f"Research synthesis captured {synthesis['summary']['finding_count']} findings and "
            f"{synthesis['citation_audit']['citation_count']} citations for AgentTask handoff."
        ),
        strength="weak" if synthesis["summary"]["has_only_stub_findings"] else "medium",
        source_artifact_id=artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id if job else None,
                "follow_up_count": len(synthesis["follow_up_requirements"]),
                "has_only_stub_findings": synthesis["summary"]["has_only_stub_findings"],
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_research_synthesis_lineage(
        db,
        project=project,
        job=job,
        context=context,
        synthesis_artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
    )
    artifact_ids = [artifact.id, report_artifact.id, visualization_artifact.id]
    return ResearchSynthesisResult(
        synthesis=synthesis,
        artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def collect_research_synthesis_context(db: Session, project_id: str) -> dict[str, Artifact | None]:
    return {
        "research_plan": latest_project_artifact(db, project_id, "research_plan"),
        "research_source_pack": latest_project_artifact(db, project_id, "research_source_pack"),
        "research_run_manifest": latest_project_artifact(db, project_id, "research_run_manifest"),
        "research_findings_report": latest_project_artifact(db, project_id, "research_findings_report"),
        "source_citation_manifest": latest_project_artifact(db, project_id, "source_citation_manifest"),
        "benchmark_scenario_pack": latest_project_artifact(db, project_id, "benchmark_scenario_pack"),
        "benchmark_evidence_pack": latest_project_artifact(db, project_id, "benchmark_evidence_pack"),
        "baseline_strategy_plan": latest_project_artifact(db, project_id, "baseline_strategy_plan"),
    }


def build_research_synthesis(project: Project, context: dict[str, Artifact | None]) -> dict[str, Any]:
    source_pack_payload = load_json_artifact(context.get("research_source_pack"))
    run_manifest = load_json_artifact(context.get("research_run_manifest"))
    citation_manifest = load_json_artifact(context.get("source_citation_manifest"))
    findings = list_value(run_manifest.get("findings"))
    citations = list_value(citation_manifest.get("citations"))
    evidence_sources = list_value(citation_manifest.get("evidence_sources"))
    has_only_stub_findings = bool(run_manifest) and str(run_manifest.get("execution_status")) == "not_executed"
    return {
        "schema_version": "research_finding_synthesis.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "source_artifacts": {role: artifact_ref(artifact) for role, artifact in context.items() if artifact is not None},
        "summary": {
            "status": "available" if run_manifest or source_pack_payload else "source_context_missing",
            "finding_count": len(findings),
            "controlled_query_count": controlled_query_count(source_pack_payload, run_manifest),
            "has_only_stub_findings": has_only_stub_findings,
            "evidence_strength": "weak" if has_only_stub_findings else "medium",
            "interpretation": (
                "Research runner output is currently a policy-compliance stub; use it as context and follow-up requirements, not as verified external evidence."
                if has_only_stub_findings
                else "Research findings include runner-supplied source context; verify citations before decision-grade use."
            ),
        },
        "citation_audit": {
            "source_count": len(evidence_sources),
            "citation_count": len(citations),
            "external_network_accessed": bool(citation_manifest.get("external_network_accessed")),
            "connector_credentials_materialized": bool(citation_manifest.get("connector_credentials_materialized")),
            "research_source_pack_artifact_id": citation_manifest.get("research_source_pack_artifact_id"),
        },
        "approach_implications": approach_implications(source_pack_payload, run_manifest, citation_manifest),
        "follow_up_requirements": follow_up_requirements(source_pack_payload, run_manifest, citation_manifest),
        "agent_task_handoff": {
            "use_as_context_not_recipe": True,
            "must_respect_evaluation_spec_and_split_manifest": True,
            "external_claims_require_citations": True,
            "recommended_context_artifacts": [
                artifact.id for artifact in context.values() if artifact is not None
            ],
            "notes": [
                "Do not treat stub findings as external evidence.",
                "Use synthesis to decide what additional controlled research or Skill context is needed.",
                "Keep modeling approach flexible and justified by project data, evaluation constraints, and citations.",
            ],
        },
    }


def approach_implications(
    source_pack_payload: dict[str, Any],
    run_manifest: dict[str, Any],
    citation_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    implications: list[dict[str, Any]] = []
    if source_pack_payload:
        implications.append(
            {
                "topic": "source_policy",
                "status": "available",
                "summary": "Source policy, citation requirements, and freshness expectations are available for runner planning.",
            }
        )
    if run_manifest:
        implications.append(
            {
                "topic": "research_execution",
                "status": str(run_manifest.get("execution_status") or "unknown"),
                "summary": (
                    "Research runner has not retrieved external sources yet."
                    if run_manifest.get("execution_status") == "not_executed"
                    else "Research runner output should be reviewed with its citations."
                ),
            }
        )
    if citation_manifest:
        implications.append(
            {
                "topic": "citation_audit",
                "status": "available",
                "summary": f"{len(list_value(citation_manifest.get('citations')))} citations and {len(list_value(citation_manifest.get('evidence_sources')))} source summaries are attached.",
            }
        )
    return implications


def follow_up_requirements(
    source_pack_payload: dict[str, Any],
    run_manifest: dict[str, Any],
    citation_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    requirements = [
        {
            "requirement": "Keep validation/test target information out of prompts and generated features.",
            "risk_level": "high",
            "owner": "harness_and_runner",
        },
        {
            "requirement": "Respect the approved EvaluationSpec and SplitManifest before reporting metrics.",
            "risk_level": "high",
            "owner": "harness_and_runner",
        },
    ]
    if not run_manifest or run_manifest.get("execution_status") == "not_executed":
        requirements.append(
            {
                "requirement": "Run an approved controlled research runner before treating external approach claims as evidence.",
                "risk_level": "medium",
                "owner": "research_runner",
            }
        )
    if not citation_manifest or not list_value(citation_manifest.get("citations")):
        requirements.append(
            {
                "requirement": "Attach source summaries and citation ids for every external claim.",
                "risk_level": "medium",
                "owner": "research_runner",
            }
        )
    source_policy = dict_value(source_pack_payload.get("source_policy"))
    if source_policy:
        requirements.append(
            {
                "requirement": f"Follow source policy network default `{source_policy.get('network_default', 'unknown')}`.",
                "risk_level": "medium",
                "owner": "runner_policy",
            }
        )
    return requirements


def render_research_synthesis_report(synthesis: dict[str, Any]) -> str:
    lines = [
        "# Research Finding Synthesis",
        "",
        f"Project: {synthesis['project']['name']} (`{synthesis['project']['id']}`)",
        "",
        "## Summary",
        "",
        f"- Status: {synthesis['summary']['status']}",
        f"- Findings: {synthesis['summary']['finding_count']}",
        f"- Controlled queries: {synthesis['summary']['controlled_query_count']}",
        f"- Evidence strength: {synthesis['summary']['evidence_strength']}",
        f"- Stub-only findings: {str(synthesis['summary']['has_only_stub_findings']).lower()}",
        f"- Interpretation: {synthesis['summary']['interpretation']}",
        "",
        "## Citation Audit",
        "",
        f"- Sources: {synthesis['citation_audit']['source_count']}",
        f"- Citations: {synthesis['citation_audit']['citation_count']}",
        f"- External network accessed: {str(synthesis['citation_audit']['external_network_accessed']).lower()}",
        f"- Connector credentials materialized: {str(synthesis['citation_audit']['connector_credentials_materialized']).lower()}",
        "",
        "## Approach Implications",
        "",
    ]
    for implication in synthesis["approach_implications"]:
        lines.append(f"- {implication['topic']}: {implication['summary']}")
    lines.extend(["", "## Follow-up Requirements", ""])
    for requirement in synthesis["follow_up_requirements"]:
        lines.append(f"- {requirement['requirement']} ({requirement['risk_level']})")
    lines.extend(["", "## AgentTask Handoff", ""])
    for note in synthesis["agent_task_handoff"]["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines).strip() + "\n"


def build_research_synthesis_visualization(synthesis: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Research Finding Synthesis",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": "Findings",
                "status": "warning" if synthesis["summary"]["has_only_stub_findings"] else "ready",
                "count": synthesis["summary"]["finding_count"],
                "detail": synthesis["summary"]["interpretation"],
            },
            {
                "stage": "Citations",
                "status": "ready" if synthesis["citation_audit"]["citation_count"] else "warning",
                "count": synthesis["citation_audit"]["citation_count"],
                "detail": "Citation manifest is attached to the synthesis.",
            },
            {
                "stage": "External access",
                "status": "warning" if synthesis["citation_audit"]["external_network_accessed"] else "ready",
                "count": 1 if synthesis["citation_audit"]["external_network_accessed"] else 0,
                "detail": "Network access must remain controlled and cited.",
            },
            {
                "stage": "Follow-up",
                "status": "warning" if synthesis["follow_up_requirements"] else "ready",
                "count": len(synthesis["follow_up_requirements"]),
                "detail": "Open requirements must be resolved before decision-grade claims.",
            },
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "detail"]},
        "empty_state": "Research synthesis will appear after source context is synthesized.",
    }


def create_research_synthesis_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    context: dict[str, Artifact | None],
    synthesis_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    if job is not None:
        for artifact in [synthesis_artifact, report_artifact, visualization_artifact]:
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
            to_asset_id=synthesis_artifact.id,
            relation_type="synthesized_into",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=synthesis_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=synthesis_artifact.id,
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
        from_asset_id=synthesis_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualizes",
    )


def source_asset_refs(synthesis: dict[str, Any], synthesis_artifact_id: str) -> list[dict[str, str]]:
    refs = [{"asset_type": "artifact", "asset_id": synthesis_artifact_id}]
    for ref in synthesis.get("source_artifacts", {}).values():
        if isinstance(ref, dict) and isinstance(ref.get("artifact_id"), str):
            refs.append({"asset_type": "artifact", "asset_id": ref["artifact_id"]})
    return refs


def artifact_ref(artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": compact_metadata(metadata),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def controlled_query_count(source_pack_payload: dict[str, Any], run_manifest: dict[str, Any]) -> int:
    query_count = run_manifest.get("query_count")
    if isinstance(query_count, int):
        return query_count
    queries = source_pack_payload.get("controlled_queries")
    return len(queries) if isinstance(queries, list) else 0


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "job_id",
        "research_source_pack_artifact_id",
        "research_run_manifest_artifact_id",
        "source_citation_manifest_artifact_id",
        "benchmark_id",
        "benchmark_ids",
        "query_count",
        "citation_count",
        "external_network_accessed",
    ]
    return {key: metadata.get(key) for key in keys if key in metadata}


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
