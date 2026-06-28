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
    Evidence,
    ExperimentRun,
    Job,
    Project,
    Report,
    SplitManifest,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.schemas import AgentResult, AgentTaskContract
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)


@dataclass(frozen=True)
class AgentResultExperimentIngestion:
    experiment_run_id: str | None
    visualization_ids: list[str]
    metrics_artifact_id: str | None
    feature_recipe_artifact_id: str | None
    citation_manifest_artifact_id: str | None
    citation_audit_report_id: str | None
    citation_audit_report_artifact_id: str | None
    citation_evidence_id: str | None
    citation_visualization_id: str | None
    citation_visualization_artifact_id: str | None


@dataclass(frozen=True)
class AgentResultCitationIngestion:
    manifest_artifact_id: str | None
    report_id: str | None
    report_artifact_id: str | None
    evidence_id: str | None
    visualization_id: str | None
    visualization_artifact_id: str | None


def ingest_agent_result_experiment_outputs(
    db: Session,
    *,
    store: LocalArtifactStore,
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
        if not is_citation_visualization_artifact(artifact)
    ]
    citation_visualization_artifact = next(
        (artifact for artifact in visualization_artifacts if is_citation_visualization_artifact(artifact)),
        None,
    )
    citation_ingestion = ingest_agent_result_citations(
        db,
        store=store,
        project=project,
        job=job,
        contract=contract,
        agent_result=agent_result,
        ingested_artifacts=ingested_artifacts,
        citation_visualization_artifact=citation_visualization_artifact,
        run=run,
        source_asset_type=source_asset_type,
        source_asset_id=source_asset_id,
    )
    db.flush()
    return AgentResultExperimentIngestion(
        experiment_run_id=run.id if run is not None else None,
        visualization_ids=[visualization.id for visualization in visualizations],
        metrics_artifact_id=metrics_artifact.id if metrics_artifact else None,
        feature_recipe_artifact_id=feature_recipe_artifact.id if feature_recipe_artifact else None,
        citation_manifest_artifact_id=citation_ingestion.manifest_artifact_id,
        citation_audit_report_id=citation_ingestion.report_id,
        citation_audit_report_artifact_id=citation_ingestion.report_artifact_id,
        citation_evidence_id=citation_ingestion.evidence_id,
        citation_visualization_id=citation_ingestion.visualization_id,
        citation_visualization_artifact_id=citation_ingestion.visualization_artifact_id,
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


def ingest_agent_result_citations(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    contract: AgentTaskContract,
    agent_result: AgentResult,
    ingested_artifacts: list[Artifact],
    citation_visualization_artifact: Artifact | None,
    run: ExperimentRun | None,
    source_asset_type: str,
    source_asset_id: str,
) -> AgentResultCitationIngestion:
    manifest_artifact = first_artifact_of_type(ingested_artifacts, "source_citation_manifest")
    manifest = load_json_artifact(manifest_artifact)
    if not manifest and should_materialize_citation_manifest(agent_result, contract):
        manifest = build_citation_manifest_from_result(agent_result, contract)
        manifest_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="source_citation_manifest",
            name=f"source_citation_manifest_{job.id}",
            filename="source_citation_manifest.json",
            payload=manifest,
            metadata={
                "project_id": project.id,
                "job_id": job.id,
                "task_id": agent_result.task_id,
                "source_asset_type": source_asset_type,
                "source_asset_id": source_asset_id,
                "materialized_by_harness": True,
            },
        )
    if manifest_artifact is None or not manifest:
        return AgentResultCitationIngestion(None, None, None, None, None, None)

    report_artifact = first_artifact_of_type(ingested_artifacts, "citation_audit_report")
    report_md = load_text_artifact(report_artifact) if report_artifact is not None else ""
    if not report_md:
        report_md = render_citation_audit_report(manifest)
        report_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="citation_audit_report",
            name=f"citation_audit_report_{job.id}",
            filename="citation_audit_report.md",
            text=report_md,
            metadata={
                "project_id": project.id,
                "job_id": job.id,
                "task_id": agent_result.task_id,
                "source_citation_manifest_artifact_id": manifest_artifact.id,
                "materialized_by_harness": True,
            },
        )
    if report_artifact is None:
        raise ValueError("Citation audit report artifact could not be materialized")

    evidence_sources = list_value(manifest.get("evidence_sources"))
    citations = list_value(manifest.get("citations"))
    source_pack_artifact_id = string_or_none(manifest.get("research_source_pack_artifact_id")) or (
        source_pack_artifact_id_from_contract(contract)
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="citation_audit_report",
        title=f"Citation Audit Report: {agent_result.task_id}",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": source_asset_type, "asset_id": source_asset_id},
                {"asset_type": "artifact", "asset_id": manifest_artifact.id},
                *(
                    [{"asset_type": "artifact", "asset_id": source_pack_artifact_id}]
                    if source_pack_artifact_id
                    else []
                ),
                {"asset_type": "job", "asset_id": job.id},
            ]
        ),
        status="draft",
        created_by_type="agent_runner",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="citation_audit",
        summary=(
            f"AgentResult citation audit captured {len(evidence_sources)} source candidates and "
            f"{len(citations)} citations for task `{agent_result.task_id}`."
        ),
        strength="medium" if citations else "weak",
        source_artifact_id=manifest_artifact.id,
        source_run_id=run.id if run is not None else None,
        metadata_json=dumps_json(
            {
                "job_id": job.id,
                "task_id": agent_result.task_id,
                "source_pack_artifact_id": source_pack_artifact_id,
                "external_network_accessed": bool(manifest.get("external_network_accessed")),
                "connector_credentials_materialized": bool(manifest.get("connector_credentials_materialized")),
                "source_count": len(evidence_sources),
                "citation_count": len(citations),
            }
        ),
    )
    db.add(evidence)

    if citation_visualization_artifact is None:
        citation_visualization_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="visualization_spec",
            name=f"citation_visualization_{job.id}",
            filename="citation_visualization_spec.json",
            payload=build_citation_visualization_spec(manifest),
            metadata={
                "project_id": project.id,
                "job_id": job.id,
                "task_id": agent_result.task_id,
                "visualization_role": "citation_audit",
                "source_citation_manifest_artifact_id": manifest_artifact.id,
                "materialized_by_harness": True,
            },
        )
    if citation_visualization_artifact is None:
        raise ValueError("Citation visualization artifact could not be materialized")
    visualization = create_visualization_row(
        db,
        project=project,
        artifact=citation_visualization_artifact,
        source_artifact_id=manifest_artifact.id,
        run=run,
    )
    create_citation_lineage(
        db,
        project=project,
        job=job,
        source_asset_type=source_asset_type,
        source_asset_id=source_asset_id,
        manifest_artifact=manifest_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
        visualization=visualization,
        visualization_artifact=citation_visualization_artifact,
        source_pack_artifact_id=source_pack_artifact_id,
        run=run,
    )
    return AgentResultCitationIngestion(
        manifest_artifact_id=manifest_artifact.id,
        report_id=report.id,
        report_artifact_id=report_artifact.id,
        evidence_id=evidence.id,
        visualization_id=visualization.id,
        visualization_artifact_id=citation_visualization_artifact.id,
    )


def should_materialize_citation_manifest(agent_result: AgentResult, contract: AgentTaskContract) -> bool:
    return bool(
        agent_result.evidence_sources
        or agent_result.citations
        or agent_result.report_citations
        or source_pack_artifact_id_from_contract(contract)
    )


def build_citation_manifest_from_result(agent_result: AgentResult, contract: AgentTaskContract) -> dict[str, Any]:
    source_pack_artifact_id = source_pack_artifact_id_from_contract(contract)
    return {
        "schema_version": "source_citation_manifest.v1",
        "task_id": agent_result.task_id,
        "runner": string_or_none(agent_result.outputs.get("runner")) or "agent_runner",
        "execution_status": agent_result.status,
        "external_network_accessed": False,
        "connector_credentials_materialized": False,
        "research_source_pack_artifact_id": source_pack_artifact_id,
        "source_policy": dict_value(contract.inputs.get("research_source_policy")),
        "citation_requirements": list_value(dict_value(contract.inputs.get("research_source_pack")).get("citation_requirements")),
        "freshness_expectations": dict_value(
            dict_value(contract.inputs.get("research_source_pack")).get("freshness_expectations")
        ),
        "evidence_sources": agent_result.evidence_sources,
        "citations": agent_result.citations,
        "report_citations": agent_result.report_citations,
        "audit": {
            "real_sources_retrieved": len(agent_result.evidence_sources),
            "citation_count": len(agent_result.citations),
            "materialized_by_harness": True,
        },
    }


def render_citation_audit_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Citation Audit Report",
        "",
        f"- Task: {manifest.get('task_id')}",
        f"- Runner: {manifest.get('runner')}",
        f"- Execution status: {manifest.get('execution_status')}",
        f"- External network accessed: {str(manifest.get('external_network_accessed')).lower()}",
        f"- Connector credentials materialized: {str(manifest.get('connector_credentials_materialized')).lower()}",
        f"- Research Source Pack artifact: {manifest.get('research_source_pack_artifact_id') or 'none'}",
        "",
        "## Evidence Sources",
    ]
    sources = list_value(manifest.get("evidence_sources"))
    if sources:
        for source in sources:
            if isinstance(source, dict):
                lines.append(
                    f"- `{source.get('source_id')}`: {source.get('title')} "
                    f"({source.get('verification_status')})"
                )
    else:
        lines.append("- No source summaries were supplied by the runner.")
    lines.extend(["", "## Citations"])
    citations = list_value(manifest.get("citations"))
    if citations:
        for citation in citations:
            if isinstance(citation, dict):
                lines.append(f"- `{citation.get('citation_id')}`: {citation.get('claim')}")
    else:
        lines.append("- No citations were supplied by the runner.")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- Connector credentials and secrets must not be passed to agent runners.",
            "- External claims are not decision-grade until source summaries and citations are verified as Evidence.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_citation_visualization_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    sources = list_value(manifest.get("evidence_sources"))
    citations = list_value(manifest.get("citations"))
    external_accessed = bool(manifest.get("external_network_accessed"))
    credentials_materialized = bool(manifest.get("connector_credentials_materialized"))
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Citation Audit",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": "Evidence sources",
                "status": "ready" if sources else "warning",
                "count": len(sources),
                "detail": "Runner supplied source summaries or harness materialized source policy.",
            },
            {
                "stage": "Citations",
                "status": "ready" if citations else "warning",
                "count": len(citations),
                "detail": "Claims should point to citation ids before report use.",
            },
            {
                "stage": "External access",
                "status": "warning" if external_accessed else "ready",
                "count": 1 if external_accessed else 0,
                "detail": "External access must be controlled and cited.",
            },
            {
                "stage": "Credentials",
                "status": "warning" if credentials_materialized else "ready",
                "count": 1 if credentials_materialized else 0,
                "detail": "Connector credentials must stay outside agent workspaces.",
            },
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "detail"]},
        "empty_state": "Citation audit data will appear after an AgentResult is ingested.",
    }


def create_citation_lineage(
    db: Session,
    *,
    project: Project,
    job: Job,
    source_asset_type: str,
    source_asset_id: str,
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
    source_pack_artifact_id: str | None,
    run: ExperimentRun | None,
) -> None:
    for artifact in [manifest_artifact, report_artifact, visualization_artifact]:
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
        from_asset_type=source_asset_type,
        from_asset_id=source_asset_id,
        to_asset_type="artifact",
        to_asset_id=manifest_artifact.id,
        relation_type="agent_task_source",
    )
    if source_pack_artifact_id:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_pack_artifact_id,
            to_asset_type="artifact",
            to_asset_id=manifest_artifact.id,
            relation_type="governs_sources_for",
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
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
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
    if run is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=manifest_artifact.id,
            relation_type="documents_citations_for",
        )


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


def load_text_artifact(artifact: Artifact | None) -> str:
    if artifact is None:
        return ""
    try:
        return artifact_primary_path(artifact).read_text(encoding="utf-8")
    except OSError:
        return ""


def first_artifact_of_type(artifacts: list[Artifact], asset_type: str) -> Artifact | None:
    return next((artifact for artifact in artifacts if artifact.asset_type == asset_type), None)


def is_citation_visualization_artifact(artifact: Artifact) -> bool:
    if artifact.asset_type != "visualization_spec":
        return False
    metadata = artifact_metadata(artifact)
    if metadata.get("visualization_role") == "citation_audit":
        return True
    spec = load_json_artifact(artifact)
    return spec.get("title") == "Citation Audit"


def artifact_metadata(artifact: Artifact) -> dict[str, Any]:
    try:
        value = json.loads(artifact.metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def source_pack_artifact_id_from_contract(contract: AgentTaskContract) -> str | None:
    source_pack = dict_value(contract.inputs.get("research_source_pack"))
    artifact_id = source_pack.get("artifact_id")
    return artifact_id if isinstance(artifact_id, str) and artifact_id else None


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
