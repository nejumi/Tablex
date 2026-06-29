from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, ExperimentRun, Project
from tabular_harness.services.analysis_notebooks import (
    NotebookExecutionCaptureResult,
    build_project_notebook_index,
    create_model_diagnostics_notebook,
    create_notebook_execution_capture,
)
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.reporting import leaderboard_sort_key


@dataclass(frozen=True)
class ResultNotebookEvidenceResult:
    status: str
    top_run: ExperimentRun
    notebook_artifact: Artifact
    notebook_generated: bool
    capture_created: bool
    evidence_html_artifact: Artifact | None
    evidence_bundle_artifact: Artifact | None
    evidence_figure_artifacts: list[Artifact]
    capture: NotebookExecutionCaptureResult | None
    notebook_index: dict[str, Any]
    artifact_ids: list[str]

    @property
    def preview_artifact_id(self) -> str:
        return self.evidence_html_artifact.id if self.evidence_html_artifact else self.notebook_artifact.id


def prepare_result_notebook_evidence(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> ResultNotebookEvidenceResult:
    top_run = top_leaderboard_run(db, project.id)
    if top_run is None:
        raise ValueError("A successful ExperimentRun is required before preparing result notebook evidence")

    notebook_artifact = latest_model_diagnostics_notebook_for_run(db, project.id, top_run.id)
    notebook_generated = False
    generated_artifact_ids: list[str] = []
    if notebook_artifact is None:
        notebook_result = create_model_diagnostics_notebook(db, store=store, run=top_run)
        notebook_artifact = notebook_result.notebook_artifact
        notebook_generated = True
        generated_artifact_ids = notebook_result.artifact_ids

    evidence_html = latest_notebook_artifact(db, project.id, notebook_artifact.id, "notebook_evidence_html")
    evidence_bundle = latest_notebook_artifact(db, project.id, notebook_artifact.id, "notebook_evidence_bundle")
    evidence_figures = notebook_artifacts(db, project.id, notebook_artifact.id, "notebook_evidence_svg")
    capture: NotebookExecutionCaptureResult | None = None
    capture_created = False
    capture_artifact_ids: list[str] = []
    if evidence_html is None:
        capture = create_notebook_execution_capture(db, store=store, notebook_artifact=notebook_artifact)
        capture_created = True
        evidence_html = capture.evidence_html_artifact
        evidence_bundle = capture.evidence_bundle_artifact
        evidence_figures = capture.figure_artifacts
        capture_artifact_ids = capture.artifact_ids

    notebook_index = build_project_notebook_index(db, project)
    artifact_ids = unique_ids(
        [
            *generated_artifact_ids,
            *capture_artifact_ids,
            notebook_artifact.id,
            evidence_html.id if evidence_html else None,
            evidence_bundle.id if evidence_bundle else None,
            *[artifact.id for artifact in evidence_figures],
        ]
    )
    if evidence_html is not None and capture_created:
        status = "evidence_captured"
    elif evidence_html is not None:
        status = "already_ready"
    else:
        status = "notebook_generated_without_evidence"
    return ResultNotebookEvidenceResult(
        status=status,
        top_run=top_run,
        notebook_artifact=notebook_artifact,
        notebook_generated=notebook_generated,
        capture_created=capture_created,
        evidence_html_artifact=evidence_html,
        evidence_bundle_artifact=evidence_bundle,
        evidence_figure_artifacts=evidence_figures,
        capture=capture,
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
        "notebook_generated": result.notebook_generated,
        "capture_created": result.capture_created,
        "analysis_notebook_artifact_id": result.notebook_artifact.id,
        "notebook_evidence_html_artifact_id": result.evidence_html_artifact.id
        if result.evidence_html_artifact
        else None,
        "notebook_evidence_bundle_artifact_id": result.evidence_bundle_artifact.id
        if result.evidence_bundle_artifact
        else None,
        "notebook_evidence_figure_artifact_ids": [artifact.id for artifact in result.evidence_figure_artifacts],
        "notebook_execution_manifest_artifact_id": result.capture.manifest_artifact.id if result.capture else None,
        "notebook_execution_html_artifact_id": result.capture.html_artifact.id if result.capture else None,
        "notebook_execution_plan_artifact_id": result.capture.plan_artifact.id if result.capture else None,
        "agent_task_contract_artifact_id": result.capture.contract_artifact.id if result.capture else None,
        "recommended_notebook": recommended if isinstance(recommended, dict) else None,
        "preview_artifact_id": result.preview_artifact_id,
        "artifact_ids": result.artifact_ids,
        "execution_status": result.capture.manifest["execution_status"] if result.capture else "already_captured",
        "capture_mode": result.capture.manifest["capture_mode"] if result.capture else "existing_evidence",
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
            .where(Artifact.project_id == project_id, Artifact.asset_type == "analysis_notebook")
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in notebooks:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("notebook_kind") == "model_diagnostics" and metadata.get("run_id") == run_id:
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
