from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    Evidence,
    ExperimentRun,
    Job,
    Project,
    Report,
    VisualizationSpec,
)
from tabular_harness.services.agent_result_ingestion import load_json_artifact

AGENT_TASK_RESULT_JOB_TYPES = {"run_planned_agent_task_stub", "run_agent_task"}


def list_agent_task_result_summaries(db: Session, *, project: Project) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(Job)
        .where(Job.project_id == project.id, Job.job_type.in_(AGENT_TASK_RESULT_JOB_TYPES))
        .order_by(Job.created_at.desc())
    ).all()
    outputs_by_job = {job.id: loads_json(job.output_json, {}) for job in jobs}
    artifact_ids = {
        artifact_id
        for output in outputs_by_job.values()
        for artifact_id in collect_artifact_ids(output)
    }
    artifacts_by_id = {
        artifact.id: artifact
        for artifact in db.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all()
    } if artifact_ids else {}
    report_ids = {
        value
        for output in outputs_by_job.values()
        for key, value in output.items()
        if key.endswith("_report_id") or key == "report_id"
        if isinstance(value, str)
    }
    reports_by_id = {
        report.id: report
        for report in db.scalars(select(Report).where(Report.id.in_(report_ids))).all()
    } if report_ids else {}
    run_ids = {
        output.get("experiment_run_id")
        for output in outputs_by_job.values()
        if isinstance(output.get("experiment_run_id"), str)
    }
    runs_by_id = {
        run.id: run
        for run in db.scalars(select(ExperimentRun).where(ExperimentRun.id.in_(run_ids))).all()
    } if run_ids else {}
    evidence_ids = {
        value
        for output in outputs_by_job.values()
        for key, value in output.items()
        if key.endswith("_evidence_id") or key == "evidence_id"
        if isinstance(value, str)
    }
    evidence_by_id = {
        evidence.id: evidence
        for evidence in db.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids))).all()
    } if evidence_ids else {}
    visualization_ids = {
        value
        for output in outputs_by_job.values()
        for key, value in output.items()
        if key.endswith("_visualization_id")
        if isinstance(value, str)
    }
    visualizations_by_id = {
        visualization.id: visualization
        for visualization in db.scalars(select(VisualizationSpec).where(VisualizationSpec.id.in_(visualization_ids))).all()
    } if visualization_ids else {}

    return [
        build_agent_task_result_summary(
            job,
            outputs_by_job[job.id],
            artifacts_by_id=artifacts_by_id,
            reports_by_id=reports_by_id,
            runs_by_id=runs_by_id,
            evidence_by_id=evidence_by_id,
            visualizations_by_id=visualizations_by_id,
        )
        for job in jobs
    ]


def build_agent_task_result_summary(
    job: Job,
    output: dict[str, Any],
    *,
    artifacts_by_id: dict[str, Artifact],
    reports_by_id: dict[str, Report],
    runs_by_id: dict[str, ExperimentRun],
    evidence_by_id: dict[str, Evidence],
    visualizations_by_id: dict[str, VisualizationSpec],
) -> dict[str, Any]:
    manifest_artifact = artifacts_by_id.get(string_value(output.get("source_citation_manifest_artifact_id")) or "")
    citation_manifest = load_json_artifact(manifest_artifact)
    run = runs_by_id.get(string_value(output.get("experiment_run_id")) or "")
    artifact_refs = {
        "agent_task_contract": artifact_ref(
            artifacts_by_id.get(string_value(output.get("agent_task_contract_artifact_id")) or "")
        ),
        "workspace_manifest": artifact_ref(
            artifacts_by_id.get(
                string_value(output.get("agent_workspace_manifest_artifact_id"))
                or string_value(output.get("workspace_artifact_id"))
                or ""
            )
        ),
        "readiness_review": artifact_ref(
            artifacts_by_id.get(string_value(output.get("agent_task_readiness_review_artifact_id")) or "")
        ),
        "metrics": artifact_ref(artifacts_by_id.get(string_value(output.get("agent_metrics_artifact_id")) or "")),
        "feature_recipe": artifact_ref(
            artifacts_by_id.get(string_value(output.get("agent_feature_recipe_artifact_id")) or "")
        ),
        "source_citation_manifest": artifact_ref(manifest_artifact),
        "citation_audit_report": artifact_ref(
            artifacts_by_id.get(string_value(output.get("citation_audit_report_artifact_id")) or "")
        ),
        "citation_visualization": artifact_ref(
            artifacts_by_id.get(string_value(output.get("citation_visualization_artifact_id")) or "")
        ),
        "agent_result": first_ingested_artifact_ref(output, artifacts_by_id, "agent_result"),
        "agent_task_report": first_ingested_artifact_ref(output, artifacts_by_id, "agent_task_report"),
    }
    report = reports_by_id.get(string_value(output.get("report_id")) or "")
    citation_report = reports_by_id.get(string_value(output.get("citation_audit_report_id")) or "")
    evidence = evidence_by_id.get(string_value(output.get("evidence_id")) or "")
    citation_evidence = evidence_by_id.get(string_value(output.get("citation_evidence_id")) or "")
    citation_visualization = visualizations_by_id.get(string_value(output.get("citation_visualization_id")) or "")
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "job_status": job.status,
        "created_at": job.created_at.isoformat(),
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "source": source_ref(job, output),
        "task_id": output.get("task_id"),
        "agent_status": output.get("agent_status"),
        "agent_final_message": output.get("agent_final_message"),
        "readiness_status": output.get("readiness_status"),
        "requires_human_review": output.get("requires_human_review"),
        "auto_prepared_workspace": output.get("auto_prepared_workspace"),
        "experiment_run": experiment_run_ref(run),
        "metrics": loads_json(run.metrics_json, {}) if run is not None else {},
        "reports": {
            "agent_task_report": report_ref(report),
            "citation_audit_report": report_ref(citation_report),
        },
        "evidence": {
            "agent_result": evidence_ref(evidence),
            "citation_audit": evidence_ref(citation_evidence),
        },
        "visualizations": {
            "citation_audit": visualization_ref(citation_visualization),
        },
        "artifacts": artifact_refs,
        "artifact_ids": collect_artifact_ids(output),
        "citation_audit": citation_audit_summary(citation_manifest),
    }


def source_ref(job: Job, output: dict[str, Any]) -> dict[str, str | None]:
    if job.job_type == "run_agent_task":
        return {"type": "idea", "id": string_value(output.get("idea_id"))}
    return {"type": "agent_task_contract", "id": string_value(output.get("agent_task_contract_artifact_id"))}


def first_ingested_artifact_ref(
    output: dict[str, Any],
    artifacts_by_id: dict[str, Artifact],
    asset_type: str,
) -> dict[str, Any] | None:
    for artifact_id in list_value(output.get("ingested_artifact_ids")):
        if not isinstance(artifact_id, str):
            continue
        artifact = artifacts_by_id.get(artifact_id)
        if artifact is not None and artifact.asset_type == asset_type:
            return artifact_ref(artifact)
    return None


def collect_artifact_ids(value: Any) -> list[str]:
    collected: list[str] = []

    def visit(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                visit(child_value, str(child_key))
            return
        if isinstance(node, list):
            if key and (key == "artifact_ids" or key.endswith("_artifact_ids")):
                for item in node:
                    if isinstance(item, str):
                        collected.append(item)
                return
            for item in node:
                visit(item, key)
            return
        if isinstance(node, str) and key and (key == "artifact_id" or key.endswith("_artifact_id")):
            collected.append(node)

    visit(value)
    return list(dict.fromkeys(collected))


def artifact_ref(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": loads_json(artifact.metadata_json, {}),
        "created_at": artifact.created_at.isoformat(),
    }


def report_ref(report: Report | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "id": report.id,
        "report_type": report.report_type,
        "title": report.title,
        "artifact_id": report.artifact_id,
        "status": report.status,
        "created_at": report.created_at.isoformat(),
    }


def evidence_ref(evidence: Evidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "summary": evidence.summary,
        "strength": evidence.strength,
        "source_artifact_id": evidence.source_artifact_id,
    }


def experiment_run_ref(run: ExperimentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "runner_type": run.runner_type,
        "status": run.status,
        "evaluation_spec_id": run.evaluation_spec_id,
        "split_manifest_id": run.split_manifest_id,
        "dataset_snapshot_id": run.dataset_snapshot_id,
    }


def visualization_ref(visualization: VisualizationSpec | None) -> dict[str, Any] | None:
    if visualization is None:
        return None
    return {
        "id": visualization.id,
        "title": visualization.title,
        "chart_type": visualization.chart_type,
        "artifact_id": visualization.artifact_id,
        "status": visualization.status,
    }


def citation_audit_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_count": len(list_value(manifest.get("evidence_sources"))),
        "citation_count": len(list_value(manifest.get("citations"))),
        "external_network_accessed": bool(manifest.get("external_network_accessed")),
        "connector_credentials_materialized": bool(manifest.get("connector_credentials_materialized")),
        "research_source_pack_artifact_id": string_value(manifest.get("research_source_pack_artifact_id")),
    }


def string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
