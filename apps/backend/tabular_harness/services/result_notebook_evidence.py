from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, ExperimentRun, Project
from tabular_harness.services.analysis_notebooks import (
    build_project_notebook_index,
)
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.notebook_authoring import create_notebook_authoring_brief
from tabular_harness.services.reporting import leaderboard_sort_key

NATIVE_NOTEBOOK_ASSET_TYPES = ("analysis_notebook", "marimo_notebook")


@dataclass(frozen=True)
class ResultNotebookEvidenceResult:
    status: str
    top_run: ExperimentRun
    authoring_brief_artifact: Artifact
    authoring_report_artifact: Artifact
    notebook_index: dict[str, Any]
    artifact_ids: list[str]


def prepare_result_notebook_evidence(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> ResultNotebookEvidenceResult:
    top_run = top_leaderboard_run(db, project.id)
    if top_run is None:
        raise ValueError("A successful ExperimentRun is required before preparing result notebook evidence")

    authoring = create_notebook_authoring_brief(
        db,
        store=store,
        project=project,
        objective=f"Author a model-diagnostics marimo notebook for ExperimentRun {top_run.id}.",
    )
    notebook_index = build_project_notebook_index(db, project)
    artifact_ids = unique_ids(authoring.artifact_ids)
    return ResultNotebookEvidenceResult(
        status="awaiting_agent_authored_notebook",
        top_run=top_run,
        authoring_brief_artifact=authoring.brief_artifact,
        authoring_report_artifact=authoring.report_artifact,
        notebook_index=notebook_index,
        artifact_ids=artifact_ids,
    )


def result_notebook_evidence_job_output(result: ResultNotebookEvidenceResult) -> dict[str, Any]:
    metrics = loads_json(result.top_run.metrics_json, {})
    recommended = result.notebook_index.get("recommended_notebook")
    return {
        "schema_version": "result_notebook_evidence.v1",
        "status": result.status,
        "top_run_id": result.top_run.id,
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
        "notebook_generated": False,
        "analysis_notebook_artifact_id": None,
        "notebook_evidence_bundle_artifact_id": None,
        "notebook_evidence_figure_artifact_ids": [],
        "notebook_execution_plan_artifact_id": None,
        "agent_task_contract_artifact_id": None,
        "notebook_authoring_brief_artifact_id": result.authoring_brief_artifact.id,
        "notebook_authoring_report_artifact_id": result.authoring_report_artifact.id,
        "recommended_notebook": recommended if isinstance(recommended, dict) else None,
        "source_artifact_id": None,
        "artifact_ids": result.artifact_ids,
        "execution_status": "awaiting_agent_authored_notebook",
        "source_registration": "awaiting_agent_authored_notebook",
    }


def top_leaderboard_run(db: Session, project_id: str) -> ExperimentRun | None:
    runs = list(
        db.scalars(
            select(ExperimentRun).where(ExperimentRun.project_id == project_id, ExperimentRun.status == "succeeded")
        ).all()
    )
    if not runs:
        return None
    return sorted(runs, key=leaderboard_sort_key)[0]


def latest_model_diagnostics_notebook_for_run(
    db: Session,
    project_id: str,
    run_id: str,
) -> Artifact | None:
    notebooks = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in notebooks:
        metadata = loads_json(artifact.metadata_json, {})
        related_run_ids = metadata.get("related_run_ids")
        if (
            metadata.get("notebook_kind") == "model_diagnostics"
            and (
                metadata.get("run_id") == run_id
                or (isinstance(related_run_ids, list) and run_id in related_run_ids)
            )
        ):
            return artifact
    return None


def latest_notebook_artifact(
    db: Session,
    project_id: str,
    notebook_artifact_id: str,
    asset_type: str,
) -> Artifact | None:
    artifacts = notebook_artifacts(db, project_id, notebook_artifact_id, asset_type)
    return artifacts[0] if artifacts else None


def notebook_artifacts(
    db: Session,
    project_id: str,
    notebook_artifact_id: str,
    asset_type: str,
) -> list[Artifact]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    return [
        artifact
        for artifact in artifacts
        if loads_json(artifact.metadata_json, {}).get("notebook_artifact_id") == notebook_artifact_id
    ]


def unique_ids(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
