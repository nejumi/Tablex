from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from html import escape
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    ModelVersion,
    Project,
    Report,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.agent_task_planner import validate_agent_task_contract
from tabular_harness.services.approach import (
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.reporting import persist_visualization_spec


@dataclass(frozen=True)
class AnalysisNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class ModelDiagnosticsNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class NotebookExecutionPlanResult:
    contract: dict[str, Any]
    plan: dict[str, Any]
    contract_artifact: Artifact
    plan_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class NotebookExecutionCaptureResult:
    manifest: dict[str, Any]
    report: Report
    manifest_artifact: Artifact
    report_artifact: Artifact
    html_artifact: Artifact
    figure_manifest_artifact: Artifact
    source_artifact: Artifact
    plan_artifact: Artifact
    contract_artifact: Artifact
    artifact_ids: list[str]


def create_data_understanding_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> AnalysisNotebookResult:
    dataset = _latest_dataset(db, project.id)
    if dataset is None:
        raise ValueError("A DatasetSnapshot is required before generating an analysis notebook")

    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    profile_artifact = latest_project_artifact(db, project.id, "eda_profile")
    understanding_artifact = latest_project_artifact(db, project.id, "understanding_report")
    quality_artifact = latest_project_artifact(db, project.id, "data_quality_gate")
    baseline_metrics_artifact = latest_project_artifact(db, project.id, "baseline_metrics")
    diagnostics_artifact = latest_project_artifact(db, project.id, "evaluation_diagnostics")
    profile_payload = _read_json_artifact(profile_artifact)
    quality_payload = _read_json_artifact(quality_artifact)
    diagnostics_payload = _read_json_artifact(diagnostics_artifact)
    latest_runs = _latest_runs(db, project.id)
    summary = _profile_summary(project, dataset, profile_payload, quality_payload, diagnostics_payload, latest_runs)
    notebook = {
        "schema_version": "analysis_notebook.v1",
        "notebook_kind": "data_understanding",
        "project_id": project.id,
        "project_name": project.name,
        "dataset_snapshot_id": dataset.id,
        "generated_at": utc_now().isoformat(),
        "source_artifacts": {
            "dataset_artifact_id": dataset_artifact.id if dataset_artifact else None,
            "profile_artifact_id": profile_artifact.id if profile_artifact else None,
            "understanding_artifact_id": understanding_artifact.id if understanding_artifact else None,
            "quality_artifact_id": quality_artifact.id if quality_artifact else None,
            "baseline_metrics_artifact_id": baseline_metrics_artifact.id if baseline_metrics_artifact else None,
            "diagnostics_artifact_id": diagnostics_artifact.id if diagnostics_artifact else None,
        },
        "summary": summary,
        "execution_policy": _execution_policy(),
    }
    suffix = new_id("nb")
    notebook_source = render_marimo_notebook(notebook)
    notebook_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="analysis_notebook",
        name=f"data_understanding_notebook_{suffix}",
        filename="data_understanding_notebook.py",
        text=notebook_source,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_kind": "data_understanding",
            "engine": "marimo",
            "execution_status": "generated_not_executed",
            "source_profile_artifact_id": profile_artifact.id if profile_artifact else None,
        },
    )
    html = render_notebook_html_preview(notebook, notebook_artifact.id)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_html",
        name=f"data_understanding_notebook_preview_{suffix}",
        filename="data_understanding_notebook_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": "data_understanding",
            "render_mode": "static_preview",
            "content_type": "text/html",
        },
    )
    report_md = render_notebook_report(notebook, notebook_artifact.id, html_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_report",
        name=f"data_understanding_notebook_report_{suffix}",
        filename="data_understanding_notebook_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_kind": "data_understanding",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="analysis_notebook",
        title="Data Understanding Analysis Notebook",
        summary=summary["overview"],
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(_source_asset_ids(dataset, profile_artifact, understanding_artifact)),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    manifest = {
        "schema_version": "analysis_notebook_run_manifest.v1",
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "notebook_kind": "data_understanding",
        "engine": "marimo",
        "status": "generated_not_executed",
        "generated_at": notebook["generated_at"],
        "execution_policy": _execution_policy(),
        "libraries_referenced": ["marimo", "pandas", "matplotlib", "plotly"],
        "inputs": notebook["source_artifacts"],
        "outputs": {
            "analysis_notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_report_id": report.id,
            "notebook_report_artifact_id": report_artifact.id,
        },
        "analysis_quality": {
            "eda_quality_score": summary["eda_quality_score"],
            "rubric_area_count": len(summary["quality_rubric"]),
            "guardrail_count": len(summary["evaluation_guardrails"]),
            "storyboard_section_count": len(summary["analysis_storyboard"]),
            "quality_bar": "human_readable_target_aware_scaffold",
        },
        "next_execution_modes": [
            "local marimo edit/run from downloaded artifact",
            "future controlled marimo runner with artifact capture",
            "future static HTML export when marimo runtime is enabled",
        ],
        "visualization_scope": {
            "data_understanding": True,
            "model_diagnostics": bool(latest_runs),
            "prediction_analysis": diagnostics_artifact is not None,
            "feature_importance": baseline_metrics_artifact is not None,
            "partial_dependence": "planned_runner_output",
        },
    }
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_run_manifest",
        name=f"data_understanding_notebook_manifest_{suffix}",
        filename="data_understanding_notebook_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "report_id": report.id,
            "execution_status": "generated_not_executed",
        },
    )
    _record_lineage(
        db,
        project,
        dataset,
        [
            artifact
            for artifact in [
                dataset_artifact,
                profile_artifact,
                understanding_artifact,
                quality_artifact,
                baseline_metrics_artifact,
                diagnostics_artifact,
            ]
            if artifact is not None
        ],
        notebook_artifact,
        html_artifact,
        manifest_artifact,
        report,
        report_artifact,
    )
    artifact_ids = [notebook_artifact.id, html_artifact.id, manifest_artifact.id, report_artifact.id]
    return AnalysisNotebookResult(
        notebook=notebook,
        report=report,
        notebook_artifact=notebook_artifact,
        html_artifact=html_artifact,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        artifact_ids=artifact_ids,
    )


def build_project_notebook_index(db: Session, project: Project) -> dict[str, Any]:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "analysis_notebook")
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    reports = list(
        db.scalars(
            select(Report)
            .where(Report.project_id == project.id, Report.report_type == "analysis_notebook")
            .order_by(Report.created_at.desc())
        ).all()
    )
    reports_by_artifact_id = {report.artifact_id: report for report in reports}
    visualizations = list(
        db.scalars(
            select(VisualizationSpec)
            .where(VisualizationSpec.project_id == project.id)
            .order_by(VisualizationSpec.created_at.desc())
        ).all()
    )
    visualizations_by_artifact_id = {visualization.artifact_id: visualization for visualization in visualizations}
    items = [
        _notebook_index_item(
            db,
            project,
            notebook_artifact,
            reports_by_artifact_id=reports_by_artifact_id,
            visualizations_by_artifact_id=visualizations_by_artifact_id,
        )
        for notebook_artifact in notebook_artifacts
    ]
    items_by_created = sorted(items, key=lambda item: str(item["created_at"]), reverse=True)
    counts_by_kind: dict[str, int] = {}
    for item in items_by_created:
        kind = str(item["notebook_kind"])
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
    recommended = _recommended_notebook(items_by_created)
    return {
        "schema_version": "analysis_notebook_index.v1",
        "project_id": project.id,
        "generated_at": utc_now().isoformat(),
        "counts": {
            "total": len(items_by_created),
            "by_kind": counts_by_kind,
            "with_html_preview": sum(1 for item in items_by_created if item["coverage"]["has_html_preview"]),
            "with_report": sum(1 for item in items_by_created if item["coverage"]["has_report"]),
            "with_visualization": sum(1 for item in items_by_created if item["coverage"]["has_visualization"]),
            "with_execution_plan": sum(1 for item in items_by_created if item["coverage"]["has_execution_plan"]),
            "with_execution_capture": sum(1 for item in items_by_created if item["coverage"]["has_execution_capture"]),
        },
        "recommended_notebook": recommended,
        "groups": _notebook_groups(items_by_created),
        "items": items_by_created,
        "next_actions": _notebook_index_next_actions(project, items_by_created),
    }


def create_notebook_execution_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    notebook_artifact: Artifact,
) -> NotebookExecutionPlanResult:
    if notebook_artifact.asset_type != "analysis_notebook":
        raise ValueError("Artifact is not an analysis_notebook")
    if notebook_artifact.project_id is None:
        raise ValueError("Analysis notebook artifact must be project-scoped")
    project = _require_project(db, notebook_artifact.project_id)
    metadata = loads_json(notebook_artifact.metadata_json, {})
    notebook_kind = str(metadata.get("notebook_kind") or "unknown")
    linked_artifacts = _linked_notebook_artifacts(db, project.id, notebook_artifact)
    manifest_payload = _read_json_artifact(linked_artifacts.get("manifest"))
    task_id = new_id("agt")
    plan = build_notebook_execution_plan_payload(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        linked_artifacts=linked_artifacts,
        manifest_payload=manifest_payload,
        task_id=task_id,
    )
    contract = build_notebook_execution_contract(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        linked_artifacts=linked_artifacts,
        manifest_payload=manifest_payload,
        plan=plan,
        task_id=task_id,
    )
    validate_agent_task_contract(contract)
    suffix = new_id("nbexec")
    manifest_artifact = linked_artifacts.get("manifest")
    contract_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_task_contract",
        name=f"notebook_execution_contract_{suffix}",
        filename="notebook_execution_agent_task_contract.json",
        payload=contract,
        metadata={
            "project_id": project.id,
            "task_id": task_id,
            "task_type": contract["task_type"],
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "source_manifest_artifact_id": manifest_artifact.id if manifest_artifact is not None else None,
            "artifact_expectation_count": len(contract["required_outputs"]),
            "execution_status": "planned_not_executed",
        },
    )
    plan["outputs"]["agent_task_contract_artifact_id"] = contract_artifact.id
    plan_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_execution_plan",
        name=f"notebook_execution_plan_{suffix}",
        filename="notebook_execution_plan.json",
        payload=plan,
        metadata={
            "project_id": project.id,
            "task_id": task_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "agent_task_contract_artifact_id": contract_artifact.id,
            "execution_status": "planned_not_executed",
        },
    )
    _record_notebook_execution_plan_lineage(
        db,
        project=project,
        notebook_artifact=notebook_artifact,
        linked_artifacts=[artifact for artifact in linked_artifacts.values() if artifact is not None],
        contract_artifact=contract_artifact,
        plan_artifact=plan_artifact,
    )
    return NotebookExecutionPlanResult(
        contract=contract,
        plan=plan,
        contract_artifact=contract_artifact,
        plan_artifact=plan_artifact,
        artifact_ids=[contract_artifact.id, plan_artifact.id],
    )


def create_notebook_execution_capture(
    db: Session,
    *,
    store: LocalArtifactStore,
    notebook_artifact: Artifact,
) -> NotebookExecutionCaptureResult:
    if notebook_artifact.asset_type != "analysis_notebook":
        raise ValueError("Artifact is not an analysis_notebook")
    if notebook_artifact.project_id is None:
        raise ValueError("Analysis notebook artifact must be project-scoped")
    project = _require_project(db, notebook_artifact.project_id)
    metadata = loads_json(notebook_artifact.metadata_json, {})
    notebook_kind = str(metadata.get("notebook_kind") or "unknown")
    linked_artifacts = _linked_notebook_artifacts(db, project.id, notebook_artifact)
    plan_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_plan", "notebook_artifact_id", notebook_artifact.id
    )
    contract_artifact = _latest_artifact_for_metadata(
        db, project.id, "agent_task_contract", "notebook_artifact_id", notebook_artifact.id
    )
    plan_created = False
    if plan_artifact is None or contract_artifact is None:
        plan_result = create_notebook_execution_plan(db, store=store, notebook_artifact=notebook_artifact)
        plan_artifact = plan_result.plan_artifact
        contract_artifact = plan_result.contract_artifact
        plan_created = True
    linked_artifacts["execution_plan"] = plan_artifact
    linked_artifacts["agent_task_contract"] = contract_artifact

    notebook_source = _read_text_artifact(notebook_artifact)
    source_validation = _validate_tablex_notebook_source(notebook_source)
    if not source_validation["is_tablex_generated"]:
        raise ValueError("Only Tablex-generated analysis notebooks can be captured by the local execution path")
    compile_result = run_notebook_static_compile(notebook_source)
    execution_status = "static_capture_succeeded" if compile_result["status"] == "succeeded" else "static_capture_failed"
    generated_at = utc_now().isoformat()
    suffix = new_id("nbcap")
    figure_manifest = build_notebook_figure_manifest(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        compile_result=compile_result,
        generated_at=generated_at,
    )
    figure_manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_figure_manifest",
        name=f"notebook_figure_manifest_{suffix}",
        filename="notebook_figure_manifest.json",
        payload=figure_manifest,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_static_capture",
        },
    )
    source_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_execution_source",
        name=f"notebook_execution_source_{suffix}",
        filename="updated_notebook.py",
        text=notebook_source,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_static_capture",
        },
    )
    manifest = build_notebook_execution_manifest(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        linked_artifacts=linked_artifacts,
        source_validation=source_validation,
        compile_result=compile_result,
        execution_status=execution_status,
        generated_at=generated_at,
        plan_created=plan_created,
        output_artifacts={
            "notebook_figure_manifest_artifact_id": figure_manifest_artifact.id,
            "notebook_execution_source_artifact_id": source_artifact.id,
        },
    )
    html = render_notebook_execution_html_preview(manifest)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_execution_html",
        name=f"notebook_execution_preview_{suffix}",
        filename="notebook_execution_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_static_capture",
            "content_type": "text/html",
        },
    )
    report_md = render_notebook_execution_report(manifest, html_artifact.id, figure_manifest_artifact.id, source_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_execution_report",
        name=f"notebook_execution_report_{suffix}",
        filename="notebook_execution_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_static_capture",
            "notebook_execution_html_artifact_id": html_artifact.id,
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="notebook_execution",
        title="Notebook Execution Capture Report",
        summary=str(manifest["summary"]["headline"]),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "artifact", "asset_id": notebook_artifact.id},
                {"asset_type": "artifact", "asset_id": plan_artifact.id},
                {"asset_type": "artifact", "asset_id": contract_artifact.id},
            ]
        ),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    manifest["outputs"].update(
        {
            "notebook_execution_html_artifact_id": html_artifact.id,
            "notebook_execution_report_id": report.id,
            "notebook_execution_report_artifact_id": report_artifact.id,
        }
    )
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_execution_manifest",
        name=f"notebook_execution_manifest_{suffix}",
        filename="notebook_execution_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_static_capture",
            "notebook_execution_html_artifact_id": html_artifact.id,
            "notebook_execution_report_id": report.id,
            "notebook_execution_report_artifact_id": report_artifact.id,
        },
    )
    _record_notebook_execution_capture_lineage(
        db,
        project=project,
        notebook_artifact=notebook_artifact,
        linked_artifacts=[artifact for artifact in linked_artifacts.values() if artifact is not None],
        manifest_artifact=manifest_artifact,
        report=report,
        report_artifact=report_artifact,
        html_artifact=html_artifact,
        figure_manifest_artifact=figure_manifest_artifact,
        source_artifact=source_artifact,
    )
    artifact_ids = [
        manifest_artifact.id,
        report_artifact.id,
        html_artifact.id,
        figure_manifest_artifact.id,
        source_artifact.id,
    ]
    return NotebookExecutionCaptureResult(
        manifest=manifest,
        report=report,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        html_artifact=html_artifact,
        figure_manifest_artifact=figure_manifest_artifact,
        source_artifact=source_artifact,
        plan_artifact=plan_artifact,
        contract_artifact=contract_artifact,
        artifact_ids=artifact_ids,
    )


def create_model_diagnostics_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> ModelDiagnosticsNotebookResult:
    project = _require_project(db, run.project_id)
    dataset = db.get(DatasetSnapshot, run.dataset_snapshot_id) if run.dataset_snapshot_id else None
    model_version = _model_version_for_run(db, run)
    source_artifacts = _model_diagnostics_source_artifacts(db, run, model_version)
    metrics_payload = _read_json_artifact(source_artifacts.get("baseline_metrics"))
    diagnostics_payload = _read_json_artifact(source_artifacts.get("evaluation_diagnostics"))
    validation_payload = _read_json_artifact(source_artifacts.get("model_validation_metrics"))
    prediction_summary = _read_prediction_summary(source_artifacts.get("prediction_output"))
    summary = _model_diagnostics_summary(
        project=project,
        run=run,
        model_version=model_version,
        dataset=dataset,
        metrics=metrics_payload or loads_json(run.metrics_json, {}),
        diagnostics=diagnostics_payload,
        validation=validation_payload,
        prediction_summary=prediction_summary,
        source_artifacts=source_artifacts,
    )
    notebook = {
        "schema_version": "analysis_notebook.v1",
        "notebook_kind": "model_diagnostics",
        "project_id": project.id,
        "project_name": project.name,
        "dataset_snapshot_id": dataset.id if dataset else run.dataset_snapshot_id,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "generated_at": utc_now().isoformat(),
        "source_artifacts": {
            key: artifact.id if artifact else None for key, artifact in source_artifacts.items()
        },
        "summary": summary,
        "execution_policy": _execution_policy(),
    }
    suffix = new_id("nb")
    notebook_source = render_model_diagnostics_marimo_notebook(notebook)
    notebook_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="analysis_notebook",
        name=f"model_diagnostics_notebook_{suffix}",
        filename="model_diagnostics_notebook.py",
        text=notebook_source,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_kind": "model_diagnostics",
            "engine": "marimo",
            "execution_status": "generated_not_executed",
        },
    )
    html = render_model_diagnostics_html_preview(notebook, notebook_artifact.id)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_html",
        name=f"model_diagnostics_notebook_preview_{suffix}",
        filename="model_diagnostics_notebook_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": "model_diagnostics",
            "render_mode": "static_preview",
            "content_type": "text/html",
        },
    )
    report_md = render_model_diagnostics_report(notebook, notebook_artifact.id, html_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_report",
        name=f"model_diagnostics_notebook_report_{suffix}",
        filename="model_diagnostics_notebook_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_kind": "model_diagnostics",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="analysis_notebook",
        title="Model Diagnostics Analysis Notebook",
        summary=summary["overview"],
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(_model_source_asset_ids(run, model_version, source_artifacts)),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    visualization_spec = build_model_diagnostics_visualization_spec(notebook)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=visualization_spec,
        source_artifact_id=notebook_artifact.id,
    )
    manifest = {
        "schema_version": "analysis_notebook_run_manifest.v1",
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id if dataset else None,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "notebook_kind": "model_diagnostics",
        "engine": "marimo",
        "status": "generated_not_executed",
        "generated_at": notebook["generated_at"],
        "execution_policy": _execution_policy(),
        "libraries_referenced": ["marimo", "pandas", "matplotlib", "plotly"],
        "inputs": notebook["source_artifacts"],
        "outputs": {
            "analysis_notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_report_id": report.id,
            "notebook_report_artifact_id": report_artifact.id,
            "visualization_id": visualization.id,
            "visualization_artifact_id": visualization_artifact.id,
        },
        "diagnostic_extension_points": [
            "model-native feature importance when package exposes fitted estimator metadata",
            "permutation importance against SplitManifest validation rows",
            "partial dependence for high-value numeric/categorical features",
            "prediction slice analysis from evaluation_diagnostics artifacts",
            "calibration and threshold analysis for probabilistic classifiers",
        ],
    }
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_run_manifest",
        name=f"model_diagnostics_notebook_manifest_{suffix}",
        filename="model_diagnostics_notebook_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "report_id": report.id,
            "visualization_id": visualization.id,
            "execution_status": "generated_not_executed",
        },
    )
    _record_model_notebook_lineage(
        db,
        project,
        run,
        model_version,
        [artifact for artifact in source_artifacts.values() if artifact is not None],
        notebook_artifact,
        html_artifact,
        manifest_artifact,
        report,
        report_artifact,
        visualization,
        visualization_artifact,
    )
    artifact_ids = [
        notebook_artifact.id,
        html_artifact.id,
        manifest_artifact.id,
        report_artifact.id,
        visualization_artifact.id,
    ]
    return ModelDiagnosticsNotebookResult(
        notebook=notebook,
        report=report,
        notebook_artifact=notebook_artifact,
        html_artifact=html_artifact,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def render_marimo_notebook(notebook: dict[str, Any]) -> str:
    context_json = json.dumps(notebook, ensure_ascii=False, indent=2, sort_keys=True)
    return f'''# Generated by Tablex. Product name is working-name only.
# Run with: marimo edit data_understanding_notebook.py
import marimo

__generated_with = "0.1.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import matplotlib.pyplot as plt
    import plotly.express as px
    return mo, pd, plt, px


@app.cell
def _():
    context = {context_json}
    return (context,)


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        # Data Understanding Notebook

        **Project:** {{context["project_name"]}}  
        **DatasetSnapshot:** `{{context["dataset_snapshot_id"]}}`  
        **Rows:** {{summary["row_count"]}} | **Columns:** {{summary["column_count"]}}  
        **Target:** {{summary["target_column"] or "not selected"}}

        This notebook is generated as a Tablex artifact. It is intentionally editable:
        Codex, Skills, or a human analyst can revise the analysis while keeping the
        harness-owned EvaluationSpec, SplitManifest, artifacts, and lineage intact.
        """
    )
    return


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        ## Reader brief

        Start with the data story, not the model. This notebook should help a human answer:

        1. What is one row, and what decision will be made from it?
        2. Which columns look useful, risky, duplicated, unavailable at prediction time, or too sparse?
        3. Is the target selected, and if so does its distribution make the proposed metric sensible?
        4. What should EvaluationSpec and SplitManifest protect before Codex writes modeling code?

        **Current read:** {{summary["overview"]}}
        """
    )
    return


@app.cell
def _(context, pd):
    columns = pd.DataFrame(context["summary"]["columns"])
    findings = pd.DataFrame(context["summary"]["findings"])
    guardrails = pd.DataFrame(context["summary"]["evaluation_guardrails"])
    quality_rubric = pd.DataFrame(context["summary"]["quality_rubric"])
    runs = pd.DataFrame(context["summary"]["recent_runs"])
    storyboard = pd.DataFrame(context["summary"]["analysis_storyboard"])
    return columns, findings, guardrails, quality_rubric, runs, storyboard


@app.cell
def _(context, mo, quality_rubric):
    score = context["summary"]["eda_quality_score"]
    mo.md(
        f"""
        ## EDA quality rubric

        **Status:** {{score["status"]}}  
        **Score:** {{score["score"]}}  
        {{score["interpretation"]}}
        """
    )
    mo.ui.table(quality_rubric) if not quality_rubric.empty else mo.md("No quality rubric available.")
    return


@app.cell
def _(mo, storyboard):
    mo.md("## Analysis storyboard")
    mo.ui.table(storyboard) if not storyboard.empty else mo.md("No storyboard available.")
    return


@app.cell
def _(context, mo):
    target = context["summary"]["target_readiness"]
    mo.md(
        f"""
        ## Target readiness

        **Status:** {{target["status"]}}  
        {{target["summary"]}}

        **Metric note:** {{target["metric_note"]}}
        """
    )
    return


@app.cell
def _(guardrails, mo):
    mo.md("## Leakage and evaluation guardrails")
    mo.ui.table(guardrails) if not guardrails.empty else mo.md("No guardrails generated yet.")
    return


@app.cell
def _(columns, context, mo):
    mo.md("## Column Profile")
    queues = context["summary"]["feature_review_sections"]
    mo.md(
        f"""
        High-signal queues: {{len(queues["top_missing"])}} missingness, 
        {{len(queues["high_cardinality"])}} high-cardinality, 
        {{len(queues["datetime"])}} datetime, 
        {{len(queues["text"])}} text, 
        {{len(queues["leakage_suspects"])}} leakage-suspect columns.
        """
    )
    mo.ui.table(columns) if not columns.empty else mo.md("No profile columns are available yet.")
    return


@app.cell
def _(columns, plt):
    top_missing = columns.sort_values("missing_rate", ascending=False).head(15) if not columns.empty else columns
    fig, ax = plt.subplots(figsize=(9, 4))
    if not top_missing.empty:
        ax.barh(top_missing["name"], top_missing["missing_rate"], color="#16b8a6")
        ax.set_xlabel("Missing rate")
        ax.set_title("Top missing columns")
        ax.invert_yaxis()
    else:
        ax.text(0.5, 0.5, "No column profile", ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    fig
    return


@app.cell
def _(columns, px):
    fig = None
    if not columns.empty and "semantic_type" in columns:
        fig = px.histogram(columns, x="semantic_type", color="role", title="Semantic type and role mix")
        fig.update_layout(bargap=0.2)
    fig
    return


@app.cell
def _(findings, mo):
    mo.md("## Findings and Investigation Queue")
    mo.ui.table(findings) if not findings.empty else mo.md("No findings have been generated yet.")
    return


@app.cell
def _(context, mo):
    queue = context["summary"].get("analysis_questions", [])
    mo.md("## What to inspect next")
    if queue:
        mo.md("\\n".join([f"- {{item}}" for item in queue]))
    else:
        mo.md(
            "- Confirm row semantics and prediction time.\\n"
            "- Review high-missing and high-cardinality columns.\\n"
            "- Decide whether the target is direct, delayed, or derived by aggregation.\\n"
            "- Lock evaluation only after leakage and grouping/time risks are understood."
        )
    return


@app.cell
def _(context, mo):
    target = context["summary"]["target_readiness"]
    mo.md("## Target value details")
    if target.get("top_values"):
        rows = "\\n".join([f"- {{item.get('value')}}: {{item.get('count')}}" for item in target["top_values"]])
        mo.md(rows)
    else:
        mo.md("No target value counts are available yet.")
    return


@app.cell
def _(runs, mo):
    mo.md("## Modeling Diagnostics")
    if runs.empty:
        mo.md(
            "No experiment runs are available yet. Once baseline or Codex-run experiments emit metrics, "
            "this notebook should add feature importance, permutation importance, partial dependence, "
            "slice diagnostics, and prediction analysis cells."
        )
    else:
        mo.ui.table(runs)
    return


if __name__ == "__main__":
    app.run()
'''


def render_notebook_html_preview(notebook: dict[str, Any], notebook_artifact_id: str) -> str:
    summary = notebook["summary"]
    columns = cast(list[dict[str, Any]], summary["columns"])
    findings = cast(list[dict[str, Any]], summary["findings"])
    type_rows = _count_rows(columns, "semantic_type")
    role_rows = _count_rows(columns, "role")
    missing_rows = sorted(columns, key=lambda item: _float_value(item.get("missing_rate")), reverse=True)[:8]
    quality_score = cast(dict[str, Any], summary.get("eda_quality_score") or {})
    rubric = cast(list[dict[str, Any]], summary.get("quality_rubric") or [])
    storyboard = cast(list[dict[str, Any]], summary.get("analysis_storyboard") or [])
    target = cast(dict[str, Any], summary.get("target_readiness") or {})
    guardrails = cast(list[dict[str, Any]], summary.get("evaluation_guardrails") or [])
    feature_sections = cast(dict[str, list[dict[str, Any]]], summary.get("feature_review_sections") or {})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Analysis Notebook</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #10183f;
      --muted: #53617d;
      --line: #dbe3f3;
      --panel: #ffffff;
      --wash: #f4f9fb;
      --teal: #18b8a6;
      --blue: #3867f3;
      --violet: #7b5cf0;
      --amber: #f4a62a;
    }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #f8fbff 0%, #eef8f6 100%);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ padding: 28px; display: grid; gap: 18px; }}
    header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: start; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .eyebrow {{ color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,.86); padding: 16px; box-shadow: 0 16px 42px rgba(34, 48, 88, .08); }}
    .metric strong {{ display: block; font-size: 24px; }}
    .metric span, .tiny {{ color: var(--muted); font-size: 12px; }}
    .badge-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{ border: 1px solid var(--line); border-radius: 999px; padding: 6px 9px; background: var(--wash); font-size: 12px; font-weight: 700; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(100px, 180px) 1fr 54px; gap: 10px; align-items: center; margin: 8px 0; }}
    .bar-track {{ height: 9px; border-radius: 999px; background: #e5ecf8; overflow: hidden; }}
    .bar {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--teal), var(--blue)); }}
    .findings {{ display: grid; gap: 10px; }}
    .finding {{ border-left: 4px solid var(--teal); padding: 10px 12px; background: var(--wash); border-radius: 8px; }}
    .finding.high {{ border-color: #d84c6f; }}
    .finding.medium {{ border-color: var(--amber); }}
    code {{ background: #eef3ff; border-radius: 6px; padding: 2px 5px; }}
    footer {{ color: var(--muted); font-size: 12px; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink: #eef4ff; --muted: #aab6d3; --line: #2e3a5b; --panel: #11182f; --wash: #17213a; }}
      body {{ background: #0c1225; }}
      .panel {{ background: rgba(17,24,47,.9); box-shadow: none; }}
      code {{ background: #1e2a48; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Tablex Analysis Notebook</div>
        <h1>{escape(str(summary["title"]))}</h1>
        <p>{escape(str(summary["overview"]))}</p>
      </div>
      <div class="panel">
        <div class="tiny">Notebook artifact</div>
        <code>{escape(notebook_artifact_id)}</code>
      </div>
    </header>
    <section class="grid">
      {_metric_card("Rows", summary["row_count"])}
      {_metric_card("Columns", summary["column_count"])}
      {_metric_card("Missing cells", summary["missing_cell_count"])}
      {_metric_card("Target", summary["target_column"] or "not selected")}
    </section>
    <section class="panel">
      <h2>Reader brief</h2>
      <p>Start with the data story before modeling. Inspect row semantics, target meaning, missingness, leakage suspects, prediction-time availability, and evaluation constraints. A strong notebook should tell the reader what matters next, not only display artifacts.</p>
      <div class="badge-row">
        <span class="badge">narrative EDA</span>
        <span class="badge">evaluation-first</span>
        <span class="badge">human-readable</span>
        <span class="badge">artifact-backed</span>
      </div>
    </section>
    <section class="panel">
      <h2>EDA quality rubric</h2>
      <p><strong>{escape(str(quality_score.get("status", "unknown")))}</strong> · score {escape(str(quality_score.get("score", "-")))}. {escape(str(quality_score.get("interpretation", "")))}</p>
      <div class="findings">{_rubric_rows(rubric)}</div>
    </section>
    <section class="panel">
      <h2>Analysis storyboard</h2>
      <div class="findings">{_storyboard_rows(storyboard)}</div>
    </section>
    <section class="panel">
      <h2>Target readiness</h2>
      {_target_readiness_html(target)}
    </section>
    <section class="panel">
      <h2>Leakage and evaluation guardrails</h2>
      <div class="findings">{_guardrail_rows(guardrails)}</div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Semantic mix</h2>
        <div class="badge-row">{_badge_rows(type_rows)}</div>
      </div>
      <div class="panel">
        <h2>Column roles</h2>
        <div class="badge-row">{_badge_rows(role_rows)}</div>
      </div>
    </section>
    <section class="panel">
      <h2>Missingness scan</h2>
      {_missing_rows(missing_rows)}
    </section>
    <section class="panel">
      <h2>Feature review queues</h2>
      {_feature_queue_rows(feature_sections)}
    </section>
    <section class="panel">
      <h2>Findings and investigation queue</h2>
      <div class="findings">{_finding_rows(findings)}</div>
    </section>
    <section class="panel">
      <h2>What to inspect next</h2>
      <div class="findings">
        <div class="finding"><strong>Row semantics</strong><br/>Confirm what one row represents and whether rows are independent.</div>
        <div class="finding"><strong>Target readiness</strong><br/>Confirm whether the target is direct, delayed, derived by aggregation, or not selected yet.</div>
        <div class="finding"><strong>Evaluation guardrails</strong><br/>Resolve leakage, time, group, and prediction-time availability questions before treating scores as evidence.</div>
      </div>
    </section>
    <section class="panel">
      <h2>Target value details</h2>
      <p>{escape(_target_values_text(target))}</p>
    </section>
    <section class="panel">
      <h2>Modeling diagnostics cells</h2>
      <p>The generated marimo source includes matplotlib and Plotly cells for profile visualization. It also reserves diagnostics space for feature importance, permutation importance, partial dependence, slice metrics, and prediction analysis once experiment artifacts exist.</p>
    </section>
    <footer>
      Static preview rendered inside the workbench. External dashboards are not required; secrets and connector credentials are not embedded.
    </footer>
  </main>
</body>
</html>"""


def render_notebook_report(notebook: dict[str, Any], notebook_artifact_id: str, html_artifact_id: str) -> str:
    summary = notebook["summary"]
    findings = cast(list[dict[str, Any]], summary["findings"])
    rubric = cast(list[dict[str, Any]], summary.get("quality_rubric") or [])
    guardrails = cast(list[dict[str, Any]], summary.get("evaluation_guardrails") or [])
    target = cast(dict[str, Any], summary.get("target_readiness") or {})
    score = cast(dict[str, Any], summary.get("eda_quality_score") or {})
    finding_lines = [
        f"- **{item['severity']}**: {item['message']} ({item['next_action']})" for item in findings[:8]
    ] or ["- No findings generated yet."]
    rubric_lines = [
        f"- **{item['area']}**: {item['status']} - {item['upgrade_path']}" for item in rubric
    ] or ["- No EDA quality rubric generated yet."]
    guardrail_lines = [
        f"- **{item['guardrail']}** ({item['risk']}): {item['detail']}" for item in guardrails
    ] or ["- No evaluation guardrails generated yet."]
    return "\n".join(
        [
            "# Data Understanding Analysis Notebook",
            "",
            str(summary["overview"]),
            "",
            "## EDA Quality",
            "",
            f"- Status: `{score.get('status', 'unknown')}`",
            f"- Score: `{score.get('score', '-')}`",
            f"- Interpretation: {score.get('interpretation', '')}",
            "",
            *rubric_lines,
            "",
            "## Target Readiness",
            "",
            f"- Status: `{target.get('status', 'unknown')}`",
            f"- Summary: {target.get('summary', 'No target readiness summary available.')}",
            f"- Metric note: {target.get('metric_note', '')}",
            "",
            "## Artifacts",
            "",
            f"- Notebook source: `{notebook_artifact_id}`",
            f"- HTML preview: `{html_artifact_id}`",
            "",
            "## Coverage",
            "",
            "- marimo notebook source with pandas, matplotlib, and Plotly cells.",
            "- Static in-product HTML preview for immediate inspection.",
            "- Reader brief and investigation queue for human-first review.",
            "- EDA quality rubric, analysis storyboard, target readiness, feature queues, and evaluation guardrails.",
            "- Placeholder diagnostics section for feature importance, permutation importance, partial dependence, and prediction analysis.",
            "- Execution policy keeps credentials out of notebooks and runner context.",
            "",
            "## Evaluation Guardrails",
            "",
            *guardrail_lines,
            "",
            "## Findings",
            "",
            *finding_lines,
        ]
    )


def render_model_diagnostics_marimo_notebook(notebook: dict[str, Any]) -> str:
    context_json = json.dumps(notebook, ensure_ascii=False, indent=2, sort_keys=True)
    return f'''# Generated by Tablex. Product name is working-name only.
# Run with: marimo edit model_diagnostics_notebook.py
import marimo

__generated_with = "0.1.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import matplotlib.pyplot as plt
    import plotly.express as px
    return mo, pd, plt, px


@app.cell
def _():
    context = {context_json}
    return (context,)


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        # Model Diagnostics Notebook

        **Project:** {{context["project_name"]}}<br/>
        **Run:** `{{context["run_id"]}}`<br/>
        **ModelVersion:** `{{context.get("model_version_id") or "not registered"}}`<br/>
        **Primary metric:** {{summary["primary_metric_name"] or "unknown"}} = {{summary["primary_metric_value"]}}

        The harness owns EvaluationSpec, SplitManifest, artifacts, reports, and lineage. This notebook is
        editable analysis context for Codex, Skills, or a human analyst; it is not a fixed AutoML recipe.
        """
    )
    return


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        ## Reader brief

        Treat this as the first model review, not a leaderboard screenshot.

        - Is the primary metric aligned with the user decision and class balance?
        - Does the run obey the approved EvaluationSpec and SplitManifest?
        - Did the model beat a sanity floor for reasons we understand?
        - Which failures, slices, calibration gaps, or feature families deserve the next Codex task?

        **Current read:** primary metric {{summary["primary_metric_name"] or "unknown"}} =
        {{summary["primary_metric_value"]}}. Validation status: {{summary.get("validation_status") or "not run"}}.
        """
    )
    return


@app.cell
def _(context, pd):
    metrics = pd.DataFrame(context["summary"]["metric_rows"])
    features = pd.DataFrame(context["summary"]["feature_family_rows"])
    findings = pd.DataFrame(context["summary"]["findings"])
    prediction_bins = pd.DataFrame(context["summary"]["prediction_summary"].get("score_bins", []))
    return metrics, features, findings, prediction_bins


@app.cell
def _(metrics, mo):
    mo.md("## Metrics")
    mo.ui.table(metrics) if not metrics.empty else mo.md("No metrics are available.")
    return


@app.cell
def _(features, px):
    fig = None
    if not features.empty:
        fig = px.bar(features, x="family", y="count", color="status", title="Feature family inventory")
    fig
    return


@app.cell
def _(prediction_bins, plt):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    if not prediction_bins.empty:
        ax.bar(prediction_bins["bin"], prediction_bins["count"], color="#3867f3")
        ax.set_title("Prediction score bins")
        ax.set_xlabel("Score bin")
        ax.set_ylabel("Rows")
    else:
        ax.text(0.5, 0.5, "No score bins available", ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    fig
    return


@app.cell
def _(context, mo):
    diagnostics = context["summary"].get("diagnostics_summary") or {{}}
    mo.md("## Evaluation Diagnostics")
    mo.md(str(diagnostics)) if diagnostics else mo.md("Run diagnostics are not available yet.")
    return


@app.cell
def _(findings, mo):
    mo.md("## Next Analysis Queue")
    mo.ui.table(findings) if not findings.empty else mo.md("No follow-up findings were generated.")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Human review checklist

        - Explain the score in plain language before optimizing it.
        - Compare against sanity floors and the approved primary metric.
        - Look for data slices where the model fails, not only aggregate lift.
        - Add feature importance, permutation importance, partial dependence, calibration, and threshold analysis when artifacts exist.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Extension Points

        Future controlled runners should add feature importance, permutation importance, partial dependence,
        calibration, threshold analysis, and prediction-slice drilldowns as separate artifacts. These additions
        must continue to respect EvaluationSpec and SplitManifest.
        """
    )
    return


if __name__ == "__main__":
    app.run()
'''


def render_model_diagnostics_html_preview(notebook: dict[str, Any], notebook_artifact_id: str) -> str:
    summary = notebook["summary"]
    metric_rows = cast(list[dict[str, Any]], summary.get("metric_rows", []))
    feature_rows = cast(list[dict[str, Any]], summary.get("feature_family_rows", []))
    findings = cast(list[dict[str, Any]], summary.get("findings", []))
    prediction_summary = cast(dict[str, Any], summary.get("prediction_summary", {}))
    score_bins = cast(list[dict[str, Any]], prediction_summary.get("score_bins", []))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Model Diagnostics Notebook</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #10183f;
      --muted: #53617d;
      --line: #dbe3f3;
      --wash: #f4f9fb;
      --teal: #18b8a6;
      --blue: #3867f3;
      --violet: #7b5cf0;
      --rose: #d84c6f;
      --amber: #f4a62a;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: radial-gradient(circle at top left, rgba(24,184,166,.16), transparent 34%), linear-gradient(180deg, #f8fbff 0%, #f2f6ff 100%);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ padding: 28px; display: grid; gap: 18px; }}
    header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: start; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .eyebrow {{ color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,.88); padding: 16px; box-shadow: 0 16px 42px rgba(34, 48, 88, .08); }}
    .metric strong {{ display: block; font-size: 23px; }}
    .metric span, .tiny {{ color: var(--muted); font-size: 12px; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(110px, 190px) 1fr 60px; gap: 10px; align-items: center; margin: 8px 0; }}
    .bar-track {{ height: 10px; border-radius: 999px; background: #e5ecf8; overflow: hidden; }}
    .bar {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--teal), var(--blue)); }}
    .finding {{ border-left: 4px solid var(--teal); margin: 10px 0; padding: 10px 12px; background: var(--wash); border-radius: 8px; }}
    .finding.high {{ border-color: var(--rose); }}
    .finding.medium {{ border-color: var(--amber); }}
    code {{ background: #eef3ff; border-radius: 6px; padding: 2px 5px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--line); padding: 8px; }}
    footer {{ color: var(--muted); font-size: 12px; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink: #eef4ff; --muted: #aab6d3; --line: #2e3a5b; --wash: #17213a; }}
      body {{ background: #0c1225; }}
      .panel {{ background: rgba(17,24,47,.9); box-shadow: none; }}
      code {{ background: #1e2a48; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Tablex Model Diagnostics Notebook</div>
        <h1>{escape(str(summary["title"]))}</h1>
        <p>{escape(str(summary["overview"]))}</p>
      </div>
      <div class="panel">
        <div class="tiny">Run</div>
        <code>{escape(str(notebook.get("run_id") or "-"))}</code>
        <div class="tiny">Notebook artifact</div>
        <code>{escape(notebook_artifact_id)}</code>
      </div>
    </header>
    <section class="grid">
      {_metric_card("Primary metric", _format_metric(summary.get("primary_metric_value")))}
      {_metric_card("Metric name", summary.get("primary_metric_name") or "-")}
      {_metric_card("Predictions", prediction_summary.get("row_count", 0))}
      {_metric_card("Validation", summary.get("validation_status") or "not run")}
    </section>
    <section class="panel">
      <h2>Reader brief</h2>
      <p>Treat this as a model review. The useful question is not only whether the metric is higher, but whether the metric matches the decision, the split is respected, the sanity floor is beaten for credible reasons, and the next failure analysis is obvious.</p>
      <div class="badge-row">
        <span class="badge">metric interpretation</span>
        <span class="badge">split-respecting</span>
        <span class="badge">failure analysis</span>
        <span class="badge">next Codex task</span>
      </div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Metric snapshot</h2>
        {_html_table(metric_rows, ["metric", "value"])}
      </div>
      <div class="panel">
        <h2>Feature families</h2>
        {_bar_rows(feature_rows, "family", "count")}
      </div>
    </section>
    <section class="panel">
      <h2>Prediction score bins</h2>
      {_bar_rows(score_bins, "bin", "count")}
    </section>
    <section class="panel">
      <h2>Findings and next analysis queue</h2>
      {_finding_rows(findings)}
    </section>
    <section class="panel">
      <h2>Human review checklist</h2>
      <div class="findings">
        <div class="finding"><strong>Metric meaning</strong><br/>Explain what {escape(str(summary.get("primary_metric_name") or "the primary metric"))} means for the user's decision.</div>
        <div class="finding"><strong>Failure slices</strong><br/>Inspect segment, time, group, and score-bin behavior before trusting aggregate lift.</div>
        <div class="finding"><strong>Interpretability next</strong><br/>Add feature importance, permutation importance, partial dependence, calibration, and threshold analysis when execution artifacts are available.</div>
      </div>
    </section>
    <section class="panel">
      <h2>Diagnostics coverage</h2>
      <p>{escape(str(summary.get("diagnostics_coverage")))} Feature importance, permutation importance, and partial dependence are explicit extension points for the next controlled runner.</p>
    </section>
    <footer>
      Static preview rendered inside the workbench. It references existing model, prediction, validation, and diagnostics artifacts without external dashboards.
    </footer>
  </main>
</body>
</html>"""


def render_model_diagnostics_report(notebook: dict[str, Any], notebook_artifact_id: str, html_artifact_id: str) -> str:
    summary = notebook["summary"]
    findings = cast(list[dict[str, Any]], summary.get("findings", []))
    finding_lines = [
        f"- **{item['severity']}**: {item['message']} ({item['next_action']})" for item in findings[:10]
    ] or ["- No follow-up findings generated."]
    return "\n".join(
        [
            "# Model Diagnostics Analysis Notebook",
            "",
            str(summary["overview"]),
            "",
            "## Context",
            "",
            f"- Run: `{notebook.get('run_id')}`",
            f"- ModelVersion: `{notebook.get('model_version_id') or '-'}`",
            f"- Primary metric: {summary.get('primary_metric_name') or '-'} = {summary.get('primary_metric_value')}",
            f"- Prediction rows summarized: {summary.get('prediction_summary', {}).get('row_count', 0)}",
            "",
            "## Artifacts",
            "",
            f"- Notebook source: `{notebook_artifact_id}`",
            f"- HTML preview: `{html_artifact_id}`",
            "",
            "## Coverage",
            "",
            "- marimo notebook source with pandas, matplotlib, and Plotly cells.",
            "- In-product static HTML preview for immediate model diagnostic inspection.",
            "- Reader brief and human review checklist for interpretation before optimization.",
            "- Uses existing prediction, baseline metric, diagnostics, validation, and model package artifacts when available.",
            "- Leaves feature importance, permutation importance, partial dependence, calibration, and threshold analysis as explicit controlled-runner extension points.",
            "",
            "## Findings",
            "",
            *finding_lines,
        ]
    )


def build_model_diagnostics_visualization_spec(notebook: dict[str, Any]) -> dict[str, Any]:
    summary = notebook["summary"]
    prediction_summary = cast(dict[str, Any], summary.get("prediction_summary", {}))
    rows = [
        {
            "label": str(summary.get("primary_metric_name") or "primary metric"),
            "value": _float_value(summary.get("primary_metric_value")),
        },
        {"label": "prediction rows", "value": int(prediction_summary.get("row_count") or 0)},
        {"label": "feature families", "value": len(summary.get("feature_family_rows") or [])},
        {"label": "findings", "value": len(summary.get("findings") or [])},
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Model Diagnostics Notebook Summary",
        "chart_type": "metric_cards",
        "data": rows,
        "encoding": {"label": "label", "value": "value"},
        "empty_state": "Generate a model diagnostics notebook after a run has metrics or predictions.",
        "source": {
            "notebook_kind": notebook["notebook_kind"],
            "run_id": notebook.get("run_id"),
            "model_version_id": notebook.get("model_version_id"),
        },
    }


def _latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def _latest_runs(db: Session, project_id: str, limit: int = 5) -> list[ExperimentRun]:
    return list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project_id)
            .order_by(ExperimentRun.started_at.desc().nullslast(), ExperimentRun.id.desc())
            .limit(limit)
        ).all()
    )


def _model_version_for_run(db: Session, run: ExperimentRun) -> ModelVersion | None:
    if run.model_version_id:
        model_version = db.get(ModelVersion, run.model_version_id)
        if model_version is not None:
            return model_version
    return db.scalar(
        select(ModelVersion)
        .where(ModelVersion.project_id == run.project_id, ModelVersion.experiment_run_id == run.id)
        .order_by(ModelVersion.created_at.desc())
    )


def _read_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text_artifact(artifact: Artifact) -> str:
    try:
        return artifact_primary_path(artifact).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Artifact content is not readable: {artifact.id}") from exc


def _validate_tablex_notebook_source(source: str) -> dict[str, Any]:
    checks = {
        "has_tablex_marker": "Generated by Tablex" in source,
        "imports_marimo": "import marimo" in source,
        "defines_marimo_app": "marimo.App" in source,
        "has_main_run_guard": 'if __name__ == "__main__"' in source,
        "mentions_artifact_policy": "EvaluationSpec" in source and "SplitManifest" in source,
    }
    return {
        "schema_version": "notebook_source_validation.v1",
        "is_tablex_generated": all(
            checks[key] for key in ("has_tablex_marker", "imports_marimo", "defines_marimo_app", "has_main_run_guard")
        ),
        "checks": checks,
    }


def run_notebook_static_compile(source: str, timeout_seconds: int = 15) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tablex_notebook_capture_") as tmp_dir:
        notebook_path = f"{tmp_dir}/notebook.py"
        with open(notebook_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-m", "py_compile", notebook_path],
                cwd=tmp_dir,
                env={"PYTHONHASHSEED": "0"},
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "schema_version": "notebook_static_compile.v1",
                "status": "timed_out",
                "returncode": None,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timeout_seconds": timeout_seconds,
                "stdout_excerpt": _excerpt(exc.stdout),
                "stderr_excerpt": _excerpt(exc.stderr),
                "isolated_python": True,
                "executed_user_code": False,
            }
    return {
        "schema_version": "notebook_static_compile.v1",
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "timeout_seconds": timeout_seconds,
        "stdout_excerpt": _excerpt(completed.stdout),
        "stderr_excerpt": _excerpt(completed.stderr),
        "isolated_python": True,
        "executed_user_code": False,
    }


def _excerpt(value: object, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[:limit]


def _model_diagnostics_source_artifacts(
    db: Session,
    run: ExperimentRun,
    model_version: ModelVersion | None,
) -> dict[str, Artifact | None]:
    model_version_id = model_version.id if model_version else run.model_version_id
    model_package_artifact = db.get(Artifact, model_version.artifact_id) if model_version else None
    return {
        "baseline_metrics": _latest_artifact_for_metadata(db, run.project_id, "baseline_metrics", "run_id", run.id),
        "baseline_report": _latest_artifact_for_metadata(db, run.project_id, "baseline_report", "run_id", run.id),
        "baseline_plan": _latest_artifact_for_metadata(db, run.project_id, "baseline_plan", "run_id", run.id),
        "baseline_strategy_plan": _latest_artifact_for_metadata(
            db, run.project_id, "baseline_strategy_plan", "run_id", run.id
        ),
        "feature_recipe": _latest_artifact_for_metadata(db, run.project_id, "feature_recipe", "run_id", run.id),
        "prediction_output": _latest_artifact_for_metadata(db, run.project_id, "prediction_output", "run_id", run.id),
        "evaluation_diagnostics": _latest_artifact_for_metadata(
            db, run.project_id, "evaluation_diagnostics", "run_id", run.id
        ),
        "evaluation_diagnostics_report": _latest_artifact_for_metadata(
            db, run.project_id, "evaluation_diagnostics_report", "run_id", run.id
        ),
        "run_report": _latest_artifact_for_metadata(db, run.project_id, "run_report", "run_id", run.id),
        "model_package": model_package_artifact,
        "model_validation_metrics": _latest_artifact_for_metadata(
            db, run.project_id, "model_validation_metrics", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
        "model_validation_report": _latest_artifact_for_metadata(
            db, run.project_id, "model_validation_report", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
        "prediction_replay": _latest_artifact_for_metadata(
            db, run.project_id, "prediction_replay", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
    }


def _notebook_index_item(
    db: Session,
    project: Project,
    notebook_artifact: Artifact,
    *,
    reports_by_artifact_id: dict[str, Report],
    visualizations_by_artifact_id: dict[str, VisualizationSpec],
) -> dict[str, Any]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    notebook_kind = str(metadata.get("notebook_kind") or "unknown")
    html_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_html", "notebook_artifact_id", notebook_artifact.id
    )
    manifest_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_run_manifest", "notebook_artifact_id", notebook_artifact.id
    )
    report_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_report", "notebook_artifact_id", notebook_artifact.id
    )
    visualization_artifact = _latest_artifact_for_metadata(
        db, project.id, "visualization_spec", "source_artifact_id", notebook_artifact.id
    )
    execution_plan_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_plan", "notebook_artifact_id", notebook_artifact.id
    )
    agent_task_contract_artifact = _latest_artifact_for_metadata(
        db, project.id, "agent_task_contract", "notebook_artifact_id", notebook_artifact.id
    )
    execution_manifest_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_manifest", "notebook_artifact_id", notebook_artifact.id
    )
    execution_report_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_report", "notebook_artifact_id", notebook_artifact.id
    )
    execution_html_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_html", "notebook_artifact_id", notebook_artifact.id
    )
    figure_manifest_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_figure_manifest", "notebook_artifact_id", notebook_artifact.id
    )
    execution_source_artifact = _latest_artifact_for_metadata(
        db, project.id, "notebook_execution_source", "notebook_artifact_id", notebook_artifact.id
    )
    report = reports_by_artifact_id.get(report_artifact.id) if report_artifact else None
    visualization = visualizations_by_artifact_id.get(visualization_artifact.id) if visualization_artifact else None
    execution_metadata = loads_json(execution_manifest_artifact.metadata_json, {}) if execution_manifest_artifact else {}
    coverage = {
        "has_html_preview": html_artifact is not None,
        "has_manifest": manifest_artifact is not None,
        "has_report": report_artifact is not None and report is not None,
        "has_visualization": visualization_artifact is not None and visualization is not None,
        "has_execution_plan": execution_plan_artifact is not None,
        "has_execution_capture": execution_manifest_artifact is not None,
        "has_execution_report": execution_report_artifact is not None,
        "has_execution_html": execution_html_artifact is not None,
        "has_figure_manifest": figure_manifest_artifact is not None,
        "execution_status": str(metadata.get("execution_status") or "unknown"),
        "execution_capture_status": str(execution_metadata.get("execution_status") or "not_captured"),
    }
    recommendation_score = _notebook_recommendation_score(notebook_kind, coverage, metadata)
    return {
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "title": _notebook_title(notebook_kind),
        "status": str(metadata.get("execution_status") or "ready"),
        "created_at": notebook_artifact.created_at.isoformat(),
        "dataset_snapshot_id": metadata.get("dataset_snapshot_id"),
        "run_id": metadata.get("run_id"),
        "model_version_id": metadata.get("model_version_id"),
        "artifact_ids": {
            "notebook": notebook_artifact.id,
            "html_preview": html_artifact.id if html_artifact else None,
            "manifest": manifest_artifact.id if manifest_artifact else None,
            "report_artifact": report_artifact.id if report_artifact else None,
            "visualization_artifact": visualization_artifact.id if visualization_artifact else None,
            "execution_plan": execution_plan_artifact.id if execution_plan_artifact else None,
            "agent_task_contract": agent_task_contract_artifact.id if agent_task_contract_artifact else None,
            "execution_manifest": execution_manifest_artifact.id if execution_manifest_artifact else None,
            "execution_report": execution_report_artifact.id if execution_report_artifact else None,
            "execution_html": execution_html_artifact.id if execution_html_artifact else None,
            "figure_manifest": figure_manifest_artifact.id if figure_manifest_artifact else None,
            "execution_source": execution_source_artifact.id if execution_source_artifact else None,
        },
        "report_id": report.id if report else None,
        "visualization_id": visualization.id if visualization else None,
        "coverage": coverage,
        "recommendation_score": recommendation_score,
        "recommendation_reason": _notebook_recommendation_reason(notebook_kind, coverage),
    }


def _linked_notebook_artifacts(
    db: Session,
    project_id: str,
    notebook_artifact: Artifact,
) -> dict[str, Artifact | None]:
    return {
        "notebook": notebook_artifact,
        "html_preview": _latest_artifact_for_metadata(
            db, project_id, "notebook_html", "notebook_artifact_id", notebook_artifact.id
        ),
        "manifest": _latest_artifact_for_metadata(
            db, project_id, "notebook_run_manifest", "notebook_artifact_id", notebook_artifact.id
        ),
        "report": _latest_artifact_for_metadata(
            db, project_id, "notebook_report", "notebook_artifact_id", notebook_artifact.id
        ),
        "visualization": _latest_artifact_for_metadata(
            db, project_id, "visualization_spec", "source_artifact_id", notebook_artifact.id
        ),
    }


def build_notebook_execution_plan_payload(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    linked_artifacts: dict[str, Artifact | None],
    manifest_payload: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "notebook_execution_plan.v1",
        "project_id": project.id,
        "task_id": task_id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": utc_now().isoformat(),
        "execution_status": "planned_not_executed",
        "runner_policy": {
            "mode": "controlled_runner_required",
            "execute_now": False,
            "external_network_default": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "artifact_capture_required": True,
            "human_review_required": True,
        },
        "linked_artifacts": _linked_artifact_refs(linked_artifacts),
        "manifest_summary": {
            "schema_version": manifest_payload.get("schema_version"),
            "status": manifest_payload.get("status"),
            "libraries_referenced": manifest_payload.get("libraries_referenced", []),
            "diagnostic_extension_points": manifest_payload.get("diagnostic_extension_points", []),
        },
        "expected_outputs": notebook_execution_required_outputs(),
        "outputs": {"agent_task_contract_artifact_id": None},
    }


def build_notebook_execution_contract(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    linked_artifacts: dict[str, Artifact | None],
    manifest_payload: dict[str, Any],
    plan: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    manifest_artifact = linked_artifacts.get("manifest")
    return {
        "task_id": task_id,
        "task_type": "execute_analysis_notebook",
        "project_id": project.id,
        "objective": (
            "Review, safely execute or extend the generated marimo analysis notebook in a controlled workspace. "
            "Capture every useful output as Tablex artifacts and preserve EvaluationSpec, SplitManifest, and credential boundaries."
        ),
        "inputs": {
            "schema_version": "notebook_execution_contract.v1",
            "notebook": {
                "artifact_id": notebook_artifact.id,
                "notebook_kind": notebook_kind,
                "download_url": f"/api/artifacts/{notebook_artifact.id}/download",
            },
            "linked_artifacts": _linked_artifact_refs(linked_artifacts),
            "notebook_manifest": {
                "artifact_id": manifest_artifact.id if manifest_artifact is not None else None,
                "payload_summary": plan["manifest_summary"],
            },
            "execution_plan": plan,
            "runtime_requirements": ["marimo", "pandas", "matplotlib", "plotly"],
            "artifact_expectations": notebook_execution_required_outputs(),
            "research_source_policy": {
                "network_default": "disabled_until_runner_policy_allows",
                "external_claims_require_citations": True,
                "use_project_artifacts_first": True,
            },
            "notebook_extension_points": manifest_payload.get("diagnostic_extension_points", []),
        },
        "required_outputs": notebook_execution_required_outputs(),
        "quality_checks": [
            "Run or inspect notebook code only inside the controlled workspace.",
            "Do not read secrets, connector credentials, or local files outside materialized context.",
            "Preserve EvaluationSpec and SplitManifest; do not recompute metrics on ad hoc splits.",
            "Register exported HTML, figure manifests, reports, metrics, and updated notebooks as artifacts.",
            "Keep feature importance, permutation importance, partial dependence, and calibration claims evidence-backed.",
        ],
        "forbidden_actions": [
            "Do not read secrets or connector credentials.",
            "Do not include validation/test targets in feature generation or prompts.",
            "Do not destructively modify evaluation_spec or split_manifest.",
            "Do not call external dashboards as required evidence.",
            "Do not write to production databases.",
        ],
        "context_files": [
            "AGENTS.md",
            "docs/dev.md",
            "schemas/agent_task_contract.schema.json",
            "schemas/agent_result.schema.json",
            "schemas/visualization_spec.schema.json",
        ],
        "output_schema_path": "schemas/agent_result.schema.json",
        "assumption_context": {
            "product_name_status": "working_name_only",
            "notebook_kind": notebook_kind,
            "requires_human_review": True,
            "external_dashboard_required": False,
        },
        "autonomy_level": 3,
    }


def notebook_execution_required_outputs() -> list[dict[str, Any]]:
    return [
        {
            "path": "reports/notebook_execution_report.md",
            "schema": "markdown_report.v1",
            "description": "Narrative report covering notebook execution, findings, caveats, and recommended follow-up.",
        },
        {
            "path": "artifacts/notebook_execution_manifest.json",
            "schema": "notebook_execution_manifest.v1",
            "description": "Executed cells, runtime package versions, captured outputs, and safety policy result.",
        },
        {
            "path": "artifacts/notebook_export.html",
            "schema": "html_report.v1",
            "description": "Self-contained or workbench-renderable notebook HTML export.",
        },
        {
            "path": "artifacts/notebook_figure_manifest.json",
            "schema": "notebook_figure_manifest.v1",
            "description": "Figures/tables generated by the notebook with lineage to source cells and artifacts.",
        },
        {
            "path": "artifacts/updated_notebook.py",
            "schema": "marimo_notebook_source.v1",
            "description": "Updated marimo notebook source when the runner adds analysis cells.",
        },
    ]


def _linked_artifact_refs(linked_artifacts: dict[str, Artifact | None]) -> list[dict[str, Any]]:
    refs = []
    for role, artifact in linked_artifacts.items():
        if artifact is None:
            continue
        refs.append(
            {
                "role": role,
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "download_url": f"/api/artifacts/{artifact.id}/download",
                "preview_url": f"/api/artifacts/{artifact.id}/preview",
            }
        )
    return refs


def build_notebook_figure_manifest(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    compile_result: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    expected_figures = {
        "data_understanding": [
            "top_missing_columns_bar",
            "semantic_type_role_mix",
            "target_profile_summary",
        ],
        "model_diagnostics": [
            "feature_family_inventory",
            "prediction_score_bins",
            "diagnostics_coverage_summary",
        ],
    }.get(notebook_kind, ["notebook_generated_figures"])
    return {
        "schema_version": "notebook_figure_manifest.v1",
        "project_id": project.id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": generated_at,
        "capture_mode": "safe_static_capture",
        "status": "planned_figures_only",
        "runtime_execution_status": "deferred",
        "compile_status": compile_result["status"],
        "figures": [],
        "expected_figure_slots": [
            {
                "slot": slot,
                "status": "not_rendered",
                "reason": "Static capture validates notebook source but does not execute marimo cells.",
            }
            for slot in expected_figures
        ],
    }


def build_notebook_execution_manifest(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    linked_artifacts: dict[str, Artifact | None],
    source_validation: dict[str, Any],
    compile_result: dict[str, Any],
    execution_status: str,
    generated_at: str,
    plan_created: bool,
    output_artifacts: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "notebook_execution_manifest.v1",
        "project_id": project.id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": generated_at,
        "capture_mode": "safe_static_capture",
        "execution_status": execution_status,
        "summary": {
            "headline": _notebook_execution_headline(execution_status, compile_result),
            "runtime_execution_status": "deferred",
            "python_compile_status": compile_result["status"],
            "plan_created_by_capture": plan_created,
        },
        "safety_policy": {
            "arbitrary_notebook_code_executed": False,
            "python_compile_only": True,
            "python_isolated_mode": True,
            "external_network_accessed": False,
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "local_files_outside_workspace_materialized": False,
            "human_review_required_before_full_execution": True,
        },
        "source_validation": source_validation,
        "static_compile": compile_result,
        "linked_artifacts": _linked_artifact_refs(linked_artifacts),
        "outputs": {
            **output_artifacts,
            "notebook_execution_html_artifact_id": None,
            "notebook_execution_report_id": None,
            "notebook_execution_report_artifact_id": None,
        },
        "next_runner_steps": [
            "Run marimo in a restricted workspace only after approval.",
            "Capture executed HTML export as an artifact.",
            "Capture generated figures and tables with source-cell lineage.",
            "Preserve EvaluationSpec and SplitManifest when adding diagnostics.",
        ],
    }


def _notebook_execution_headline(execution_status: str, compile_result: dict[str, Any]) -> str:
    if execution_status == "static_capture_succeeded":
        return "Notebook source passed isolated Python syntax validation; marimo runtime execution is deferred."
    if compile_result["status"] == "timed_out":
        return "Notebook source syntax validation timed out in the controlled static capture path."
    return "Notebook source did not pass isolated Python syntax validation; inspect stderr before runner execution."


def render_notebook_execution_html_preview(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    safety = manifest["safety_policy"]
    compile_result = manifest["static_compile"]
    source_validation = manifest["source_validation"]
    linked_artifacts = cast(list[dict[str, Any]], manifest["linked_artifacts"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Notebook Execution Capture</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #10183f;
      --muted: #53617d;
      --line: #dbe3f3;
      --wash: #f4f9fb;
      --teal: #18b8a6;
      --blue: #3867f3;
      --rose: #d84c6f;
      --amber: #f4a62a;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #f8fbff 0%, #eef8f6 100%);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ display: grid; gap: 18px; padding: 28px; }}
    h1 {{ margin: 0; font-size: 29px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 16px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .eyebrow {{ color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,.88); padding: 16px; box-shadow: 0 16px 42px rgba(34, 48, 88, .08); }}
    .metric strong {{ display: block; font-size: 22px; overflow-wrap: anywhere; }}
    .metric span, .tiny {{ color: var(--muted); font-size: 12px; }}
    .badge-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{ border: 1px solid var(--line); border-radius: 999px; padding: 6px 9px; background: var(--wash); font-size: 12px; font-weight: 700; }}
    .badge.good {{ color: #0f6848; }}
    .badge.warn {{ color: var(--amber); }}
    .badge.fail {{ color: var(--rose); }}
    code, pre {{ background: #eef3ff; border-radius: 6px; }}
    code {{ padding: 2px 5px; }}
    pre {{ max-height: 260px; overflow: auto; padding: 12px; white-space: pre-wrap; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--line); padding: 8px; overflow-wrap: anywhere; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink: #eef4ff; --muted: #aab6d3; --line: #2e3a5b; --wash: #17213a; }}
      body {{ background: #0c1225; }}
      .panel {{ background: rgba(17,24,47,.9); box-shadow: none; }}
      code, pre {{ background: #1e2a48; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="eyebrow">Notebook Execution Capture</div>
      <h1>{escape(str(summary["headline"]))}</h1>
      <p>This capture validates the generated marimo notebook source and records runner boundaries before full execution. It does not execute notebook cells or access external dashboards.</p>
    </header>
    <section class="grid">
      {_metric_card("Status", manifest["execution_status"])}
      {_metric_card("Notebook kind", manifest["notebook_kind"])}
      {_metric_card("Compile", compile_result["status"])}
      {_metric_card("Runtime", summary["runtime_execution_status"])}
    </section>
    <section class="panel">
      <h2>Safety boundary</h2>
      {_html_table([{"policy": key, "value": value} for key, value in safety.items()], ["policy", "value"])}
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Source validation</h2>
        {_html_table([{"check": key, "value": value} for key, value in source_validation["checks"].items()], ["check", "value"])}
      </div>
      <div class="panel">
        <h2>Linked artifacts</h2>
        {_html_table(linked_artifacts, ["role", "asset_type", "artifact_id"])}
      </div>
    </section>
    <section class="panel">
      <h2>Compile stderr</h2>
      <pre>{escape(str(compile_result.get("stderr_excerpt") or "No stderr."))}</pre>
    </section>
  </main>
</body>
</html>"""


def render_notebook_execution_report(
    manifest: dict[str, Any],
    html_artifact_id: str,
    figure_manifest_artifact_id: str,
    source_artifact_id: str,
) -> str:
    compile_result = manifest["static_compile"]
    safety = manifest["safety_policy"]
    safety_lines = [f"- {key}: `{value}`" for key, value in safety.items()]
    return "\n".join(
        [
            "# Notebook Execution Capture Report",
            "",
            str(manifest["summary"]["headline"]),
            "",
            "## Scope",
            "",
            "- Capture mode: `safe_static_capture`",
            f"- Notebook artifact: `{manifest['notebook_artifact_id']}`",
            f"- Notebook kind: `{manifest['notebook_kind']}`",
            "- Full marimo runtime execution: `deferred`",
            "- Python validation: `python -I -m py_compile` in a temporary workspace.",
            "",
            "## Safety Policy",
            "",
            *safety_lines,
            "",
            "## Compile Result",
            "",
            f"- Status: `{compile_result['status']}`",
            f"- Return code: `{compile_result['returncode']}`",
            f"- Duration: `{compile_result['duration_ms']} ms`",
            f"- Stderr excerpt: `{compile_result.get('stderr_excerpt') or 'none'}`",
            "",
            "## Captured Artifacts",
            "",
            f"- HTML preview: `{html_artifact_id}`",
            f"- Figure manifest: `{figure_manifest_artifact_id}`",
            f"- Notebook source copy: `{source_artifact_id}`",
            "",
            "## Next Runner Steps",
            "",
            *[f"- {item}" for item in manifest["next_runner_steps"]],
        ]
    )


def _notebook_recommendation_score(
    notebook_kind: str,
    coverage: dict[str, Any],
    metadata: dict[str, Any],
) -> int:
    score = 20
    if notebook_kind == "model_diagnostics":
        score += 30
    if notebook_kind == "data_understanding":
        score += 20
    if coverage.get("has_html_preview"):
        score += 20
    if coverage.get("has_report"):
        score += 10
    if coverage.get("has_visualization"):
        score += 10
    if coverage.get("has_execution_plan"):
        score += 6
    if coverage.get("has_execution_capture"):
        score += 14
    if metadata.get("run_id"):
        score += 8
    if coverage.get("execution_status") == "generated_not_executed":
        score += 2
    return score


def _recommended_notebook(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    return max(items, key=lambda item: (int(item["recommendation_score"]), str(item["created_at"])))


def _notebook_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "model_diagnostics": "Model diagnostics",
        "data_understanding": "Data understanding",
        "unknown": "Other notebooks",
    }
    groups = []
    for kind in ("model_diagnostics", "data_understanding", "unknown"):
        group_items = [item for item in items if item["notebook_kind"] == kind or (kind == "unknown" and item["notebook_kind"] not in labels)]
        if not group_items:
            continue
        groups.append(
            {
                "notebook_kind": kind,
                "title": labels[kind],
                "count": len(group_items),
                "latest_created_at": group_items[0]["created_at"],
                "items": group_items,
            }
        )
    return groups


def _notebook_index_next_actions(project: Project, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kinds = {str(item["notebook_kind"]) for item in items}
    actions: list[dict[str, Any]] = []
    if "data_understanding" not in kinds:
        actions.append(
            {
                "label": "Generate Data Understanding notebook",
                "endpoint": f"/api/projects/{project.id}/analysis-notebooks/data-understanding",
                "reason": "Start with profile, target, missingness, and assumption context before model analysis.",
            }
        )
    if "model_diagnostics" not in kinds:
        actions.append(
            {
                "label": "Generate Model Diagnostics notebook after a run",
                "endpoint": "/api/runs/{run_id}/analysis-notebook",
                "reason": "Use persisted ExperimentRun evidence, prediction outputs, validation status, and diagnostics artifacts.",
            }
        )
    uncaptured = next((item for item in items if not item["coverage"].get("has_execution_capture")), None)
    if uncaptured is not None:
        actions.append(
            {
                "label": "Capture notebook execution evidence",
                "endpoint": f"/api/analysis-notebooks/{uncaptured['artifact_ids']['notebook']}/execution-capture",
                "reason": "Create a safe static capture manifest, report, HTML preview, and figure manifest before full notebook execution.",
            }
        )
    if not actions:
        actions.append(
            {
                "label": "Open the recommended notebook evidence",
                "endpoint": None,
                "reason": "The notebook index already has data understanding, model diagnostics, and execution capture coverage.",
            }
        )
    return actions


def _notebook_title(notebook_kind: str) -> str:
    if notebook_kind == "model_diagnostics":
        return "Model Diagnostics Notebook"
    if notebook_kind == "data_understanding":
        return "Data Understanding Notebook"
    return "Analysis Notebook"


def _notebook_recommendation_reason(notebook_kind: str, coverage: dict[str, Any]) -> str:
    if coverage.get("has_execution_capture"):
        return "Most complete notebook evidence: preview, report, execution plan, and safe static capture are available."
    if notebook_kind == "model_diagnostics":
        return "Most actionable after experiments because it ties metrics, predictions, validation, and diagnostics together."
    if notebook_kind == "data_understanding":
        return "Best starting point before target, evaluation, or feature decisions."
    if coverage.get("has_html_preview"):
        return "Preview is available inside the workbench."
    return "Notebook source exists, but preview/report coverage is incomplete."


def _latest_artifact_for_metadata(
    db: Session,
    project_id: str,
    asset_type: str,
    key: str,
    value: object,
) -> Artifact | None:
    if value is None:
        return None
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get(key) == value:
            return artifact
    return None


def _read_prediction_summary(artifact: Artifact | None, limit_rows: int = 200_000) -> dict[str, Any]:
    if artifact is None:
        return {
            "status": "missing",
            "row_count": 0,
            "target_counts": [],
            "prediction_counts": [],
            "score_bins": [],
            "accuracy": None,
        }
    path = artifact_primary_path(artifact)
    if not path.exists():
        return {"status": "missing_file", "row_count": 0, "artifact_id": artifact.id}
    row_count = 0
    correct_count = 0
    comparable_count = 0
    target_counts: dict[str, int] = {}
    prediction_counts: dict[str, int] = {}
    score_values: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row_count >= limit_rows:
                break
            row_count += 1
            target = str(row.get("target") or "")
            prediction = str(row.get("prediction") or "")
            if target:
                target_counts[target] = target_counts.get(target, 0) + 1
            if prediction:
                prediction_counts[prediction] = prediction_counts.get(prediction, 0) + 1
            if target and prediction:
                comparable_count += 1
                correct_count += int(target == prediction)
            score = _optional_float(row.get("score"))
            if score is not None:
                score_values.append(score)
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "row_count": row_count,
        "truncated_at": limit_rows if row_count >= limit_rows else None,
        "target_counts": _count_dict_rows(target_counts),
        "prediction_counts": _count_dict_rows(prediction_counts),
        "score_summary": _score_summary(score_values),
        "score_bins": _score_bins(score_values),
        "accuracy": correct_count / comparable_count if comparable_count else None,
    }


def _model_diagnostics_summary(
    *,
    project: Project,
    run: ExperimentRun,
    model_version: ModelVersion | None,
    dataset: DatasetSnapshot | None,
    metrics: dict[str, Any],
    diagnostics: dict[str, Any],
    validation: dict[str, Any],
    prediction_summary: dict[str, Any],
    source_artifacts: dict[str, Artifact | None],
) -> dict[str, Any]:
    primary_metric_name = str(metrics.get("primary_metric_name") or model_version.primary_metric_name if model_version else metrics.get("primary_metric_name") or "")
    primary_metric_value = metrics.get("primary_metric_value")
    if primary_metric_value is None and model_version is not None:
        primary_metric_value = model_version.primary_metric_value
    feature_rows = _feature_family_rows(metrics)
    diagnostics_summary = diagnostics.get("summary") if isinstance(diagnostics.get("summary"), dict) else {}
    validation_status = validation.get("validation_status") if validation else None
    artifact_coverage = {
        key: artifact.id for key, artifact in source_artifacts.items() if artifact is not None
    }
    findings = _model_diagnostics_findings(
        metrics=metrics,
        diagnostics=diagnostics,
        validation=validation,
        prediction_summary=prediction_summary,
        model_version=model_version,
    )
    overview = (
        f"Generated model diagnostics notebook for run {run.id}. "
        f"Primary metric is {primary_metric_name or 'unknown'}={_format_metric(primary_metric_value)}; "
        f"prediction rows summarized: {prediction_summary.get('row_count', 0)}."
    )
    return {
        "title": "Model Diagnostics Notebook",
        "overview": overview,
        "project_name": project.name,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "dataset_snapshot_id": dataset.id if dataset else run.dataset_snapshot_id,
        "dataset_shape": {
            "row_count": dataset.row_count if dataset else None,
            "column_count": dataset.column_count if dataset else None,
        },
        "runner_type": run.runner_type,
        "run_status": run.status,
        "model_family": model_version.model_family if model_version else metrics.get("model_family"),
        "model_type": model_version.model_type if model_version else metrics.get("baseline_type"),
        "task_type": model_version.task_type if model_version else project.task_type,
        "target_column": model_version.target_column if model_version else project.target_column,
        "primary_metric_name": primary_metric_name or None,
        "primary_metric_value": _optional_float(primary_metric_value),
        "metric_rows": _metric_rows(metrics, validation),
        "feature_family_rows": feature_rows,
        "prediction_summary": prediction_summary,
        "diagnostics_summary": diagnostics_summary,
        "diagnostics_coverage": _diagnostics_coverage(diagnostics, source_artifacts),
        "validation_status": validation_status,
        "artifact_coverage": artifact_coverage,
        "findings": findings,
    }


def _feature_family_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        ("numeric", metrics.get("numeric_feature_count")),
        ("categorical", metrics.get("categorical_feature_count")),
        ("text", metrics.get("text_feature_count")),
        ("datetime", metrics.get("datetime_feature_count")),
    ]
    output = []
    for family, value in rows:
        count = int(value or 0)
        output.append({"family": family, "count": count, "status": "used" if count else "not_used"})
    return output


def _metric_rows(metrics: dict[str, Any], validation: dict[str, Any]) -> list[dict[str, Any]]:
    preferred_keys = [
        "primary_metric_value",
        "accuracy",
        "roc_auc",
        "average_precision",
        "rmse",
        "mae",
        "r2",
        "model_baseline_attempted",
    ]
    rows = [
        {"metric": key, "value": _metric_cell(metrics.get(key))}
        for key in preferred_keys
        if key in metrics
    ]
    if validation:
        rows.append({"metric": "validation_status", "value": _metric_cell(validation.get("validation_status"))})
        rows.append({"metric": "max_abs_metric_delta", "value": _metric_cell(validation.get("max_abs_metric_delta"))})
    return rows[:14]


def _model_diagnostics_findings(
    *,
    metrics: dict[str, Any],
    diagnostics: dict[str, Any],
    validation: dict[str, Any],
    prediction_summary: dict[str, Any],
    model_version: ModelVersion | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if model_version is None:
        findings.append(
            {
                "severity": "medium",
                "message": "No ModelVersion is linked to this run.",
                "next_action": "Register or validate a model package before treating the run as reusable.",
            }
        )
    if prediction_summary.get("status") != "available":
        findings.append(
            {
                "severity": "high",
                "message": "Prediction output is unavailable for this run.",
                "next_action": "Persist validation predictions before diagnostics or reporting claims.",
            }
        )
    accuracy = prediction_summary.get("accuracy")
    if isinstance(accuracy, int | float):
        findings.append(
            {
                "severity": "info",
                "message": f"Prediction summary accuracy is {accuracy:.3f} over {prediction_summary.get('row_count', 0)} rows.",
                "next_action": "Compare this with EvaluationSpec primary metric and slice diagnostics.",
            }
        )
    sanity = diagnostics.get("sanity_checks") if isinstance(diagnostics.get("sanity_checks"), dict) else {}
    if sanity:
        if sanity.get("prediction_count_matches_split") is False or sanity.get("all_predictions_joined_to_valid_rows") is False:
            findings.append(
                {
                    "severity": "high",
                    "message": "Evaluation diagnostics found prediction coverage or join issues.",
                    "next_action": "Fix prediction artifact alignment before comparing models.",
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "message": "Evaluation diagnostics sanity checks passed for prediction coverage.",
                    "next_action": "Inspect slice metrics and worst examples for model behavior.",
                }
            )
    else:
        findings.append(
            {
                "severity": "medium",
                "message": "Evaluation diagnostics artifact is not available.",
                "next_action": "Run diagnostics to populate slice metrics, score/error bins, and worst examples.",
            }
        )
    if validation:
        status = str(validation.get("validation_status") or "unknown")
        findings.append(
            {
                "severity": "info" if status == "passed" else "medium",
                "message": f"Model package validation status is {status}.",
                "next_action": "Review metric deltas before relying on the packaged model.",
            }
        )
    else:
        findings.append(
            {
                "severity": "medium",
                "message": "Model package replay validation has not been run.",
                "next_action": "Run ModelVersion validation before deployment or benchmark claims.",
            }
        )
    if not any(key in metrics for key in ("feature_importance", "permutation_importance", "partial_dependence")):
        findings.append(
            {
                "severity": "info",
                "message": "Feature importance, permutation importance, and partial dependence are not yet materialized.",
                "next_action": "Ask a controlled runner to add these analyses as artifact-backed notebook cells.",
            }
        )
    return findings


def _diagnostics_coverage(diagnostics: dict[str, Any], source_artifacts: dict[str, Artifact | None]) -> str:
    if not diagnostics:
        return "Evaluation diagnostics are missing."
    coverage = []
    for key in ("summary", "bins", "slice_metrics", "worst_examples", "sanity_checks"):
        value = diagnostics.get(key)
        if isinstance(value, list):
            coverage.append(f"{key}:{len(value)}")
        elif isinstance(value, dict):
            coverage.append(f"{key}:available")
    if source_artifacts.get("model_validation_metrics"):
        coverage.append("model_validation:available")
    return ", ".join(coverage) or "Diagnostics artifact exists but contains no recognized sections."


def _model_source_asset_ids(
    run: ExperimentRun,
    model_version: ModelVersion | None,
    source_artifacts: dict[str, Artifact | None],
) -> list[dict[str, str]]:
    sources = [{"asset_type": "experiment_run", "asset_id": run.id}]
    if model_version:
        sources.append({"asset_type": "model_version", "asset_id": model_version.id})
    for key, artifact in source_artifacts.items():
        if artifact is not None:
            sources.append({"asset_type": "artifact", "asset_id": artifact.id, "role": key})
    return sources


def _profile_summary(
    project: Project,
    dataset: DatasetSnapshot,
    profile: dict[str, Any],
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    raw_columns = profile.get("columns")
    columns = [cast(dict[str, Any], item) for item in raw_columns] if isinstance(raw_columns, list) else []
    compact_columns = [_compact_column(item) for item in columns[:80]]
    target_profile = profile.get("target_profile") if isinstance(profile.get("target_profile"), dict) else None
    findings = _build_findings(profile, quality, diagnostics, runs)
    row_count = int(profile.get("row_count") or dataset.row_count or 0)
    column_count = int(profile.get("column_count") or dataset.column_count or len(compact_columns))
    target_column = str(profile.get("target_column") or project.target_column or "") or None
    profile_mode = str(profile.get("profile_mode") or "unknown")
    overview = (
        f"Generated analysis notebook for {row_count:,} rows and {column_count:,} columns. "
        f"Profile mode is {profile_mode}; target is {target_column or 'not selected'}."
    )
    quality_rubric = _eda_quality_rubric(
        target_column=target_column,
        target_profile=target_profile,
        profile_mode=profile_mode,
        quality=quality,
        diagnostics=diagnostics,
        runs=runs,
    )
    feature_sections = _feature_review_sections(compact_columns)
    evaluation_guardrails = _evaluation_guardrails(
        target_column=target_column,
        profile=profile,
        quality=quality,
        diagnostics=diagnostics,
    )
    target_readiness = _target_readiness(target_column, target_profile, row_count)
    analysis_questions = _analysis_questions(
        target_column=target_column,
        target_readiness=target_readiness,
        feature_sections=feature_sections,
        evaluation_guardrails=evaluation_guardrails,
        runs=runs,
    )
    return {
        "title": "Data Understanding Notebook",
        "overview": overview,
        "row_count": row_count,
        "column_count": column_count,
        "missing_cell_count": int(profile.get("missing_cell_count") or 0),
        "target_column": target_column,
        "target_profile": target_profile,
        "profile_mode": profile_mode,
        "profile_boundary": profile.get("deferred_deep_profile") if isinstance(profile.get("deferred_deep_profile"), dict) else {},
        "columns": compact_columns,
        "sample_rows": profile.get("sample_rows") if isinstance(profile.get("sample_rows"), list) else [],
        "time_candidates": profile.get("time_candidates") if isinstance(profile.get("time_candidates"), list) else [],
        "group_candidates": profile.get("group_candidates") if isinstance(profile.get("group_candidates"), list) else [],
        "leakage_suspects": profile.get("leakage_suspects") if isinstance(profile.get("leakage_suspects"), list) else [],
        "findings": findings,
        "quality_rubric": quality_rubric,
        "eda_quality_score": _eda_quality_score(quality_rubric),
        "analysis_storyboard": _analysis_storyboard(target_column, profile_mode, bool(runs)),
        "target_readiness": target_readiness,
        "feature_review_sections": feature_sections,
        "evaluation_guardrails": evaluation_guardrails,
        "analysis_questions": analysis_questions,
        "recent_runs": [_run_summary(run) for run in runs],
    }


def _eda_quality_rubric(
    *,
    target_column: str | None,
    target_profile: dict[str, Any] | None,
    profile_mode: str,
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
    runs: list[ExperimentRun],
) -> list[dict[str, str]]:
    raw_quality_summary = quality.get("summary")
    quality_summary: dict[str, Any] = raw_quality_summary if isinstance(raw_quality_summary, dict) else {}
    return [
        {
            "area": "Data story",
            "status": "started",
            "evidence": f"Profile mode: {profile_mode}",
            "upgrade_path": "Clarify row semantics, prediction-time decision, unit of analysis, and data collection process.",
        },
        {
            "area": "Target-aware EDA",
            "status": "started" if target_column and target_profile else "missing_target",
            "evidence": target_column or "No target selected",
            "upgrade_path": "Explain target construction, class balance or distribution shape, and metric suitability.",
        },
        {
            "area": "Leakage and availability",
            "status": "started" if quality_summary else "needs_quality_gate",
            "evidence": str(quality_summary.get("severity") or "quality gate not available"),
            "upgrade_path": "Inspect leakage suspects, post-outcome fields, duplicates, temporal leakage, and availability at prediction time.",
        },
        {
            "area": "Evaluation guardrails",
            "status": "started",
            "evidence": "SplitManifest and EvaluationSpec remain harness-owned",
            "upgrade_path": "Compare random, stratified, time, and group scenarios before treating model lift as trustworthy.",
        },
        {
            "area": "Model diagnostics",
            "status": "available" if runs or diagnostics else "deferred_until_runs",
            "evidence": f"{len(runs)} recent run(s)" if runs else "No run diagnostics yet",
            "upgrade_path": "Add feature importance, permutation importance, PDP, calibration, residuals/errors, and prediction examples.",
        },
    ]


def _eda_quality_score(rubric: list[dict[str, str]]) -> dict[str, Any]:
    weights = {
        "available": 1.0,
        "started": 0.55,
        "needs_quality_gate": 0.35,
        "deferred_until_runs": 0.25,
        "missing_target": 0.2,
    }
    score = sum(weights.get(item["status"], 0.3) for item in rubric) / max(len(rubric), 1)
    return {
        "score": round(score, 3),
        "status": "strong_start" if score >= 0.7 else "needs_analysis_depth",
        "interpretation": (
            "Notebook has enough evidence for a useful narrative start."
            if score >= 0.7
            else "Notebook is a scaffold plus initial findings; executed, target-aware analysis still needs depth."
        ),
    }


def _analysis_storyboard(target_column: str | None, profile_mode: str, has_runs: bool) -> list[dict[str, str]]:
    return [
        {
            "section": "Executive read",
            "question": "What should a human inspect first?",
            "artifact_expectation": "Short narrative, quality score, and top risks.",
        },
        {
            "section": "Data shape and semantics",
            "question": "What does one row mean, and which columns define time, entity, text, or outcome?",
            "artifact_expectation": f"Profile mode and sample boundary are explicit: {profile_mode}.",
        },
        {
            "section": "Target and metric readiness",
            "question": "Is the target selected, interpretable, and compatible with the proposed metric?",
            "artifact_expectation": f"Target is {target_column or 'not selected; continue without blocking'}",
        },
        {
            "section": "Feature landscape",
            "question": "Which numeric, categorical, text, datetime, group, sparse, or high-cardinality fields deserve attention?",
            "artifact_expectation": "Ranked feature review queues instead of a raw column dump.",
        },
        {
            "section": "Evaluation guardrails",
            "question": "What split, leakage, group, and time constraints must Codex respect?",
            "artifact_expectation": "Guardrails stay visible before model or feature recommendations.",
        },
        {
            "section": "Diagnostics and next hypotheses",
            "question": "What would change the decision if a baseline or agent run exists?",
            "artifact_expectation": (
                "Use run artifacts for importance/error analysis." if has_runs else "Defer model diagnostics until runs exist."
            ),
        },
    ]


def _target_readiness(
    target_column: str | None,
    target_profile: dict[str, Any] | None,
    row_count: int,
) -> dict[str, Any]:
    if not target_column:
        return {
            "status": "not_selected",
            "summary": "No target is selected yet; this is acceptable before data understanding is complete.",
            "metric_note": "Do not lock metric or split until target construction and prediction timing are clear.",
            "top_values": [],
        }
    if not target_profile:
        return {
            "status": "selected_without_profile",
            "summary": f"Target `{target_column}` is selected but was not profiled in the latest artifact.",
            "metric_note": "Regenerate profile or verify target exists before evaluation design.",
            "top_values": [],
        }
    unique_count = int(target_profile.get("unique_count") or 0)
    missing_count = int(target_profile.get("missing_count") or 0)
    raw_top_values = target_profile.get("top_values")
    top_values: list[Any] = raw_top_values if isinstance(raw_top_values, list) else []
    largest_class = max((int(item.get("count") or 0) for item in top_values if isinstance(item, dict)), default=0)
    imbalance = largest_class / row_count if row_count else 0.0
    if unique_count <= 20:
        metric_note = (
            "Classification-like target. Inspect imbalance before preferring ROC-AUC, PR-AUC, F1, log loss, or accuracy."
        )
    else:
        metric_note = "Regression-like target. Inspect distribution, outliers, and error cost before preferring RMSE, MAE, or R2."
    return {
        "status": "profiled",
        "summary": (
            f"Target `{target_column}` has {unique_count} unique value(s), {missing_count} missing value(s), "
            f"and largest-class share about {imbalance:.1%}."
        ),
        "unique_count": unique_count,
        "missing_count": missing_count,
        "largest_class_share": round(imbalance, 4),
        "metric_note": metric_note,
        "top_values": top_values[:8],
    }


def _feature_review_sections(columns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    feature_columns = [column for column in columns if column.get("role") != "target"]
    return {
        "top_missing": sorted(feature_columns, key=lambda item: _float_value(item.get("missing_rate")), reverse=True)[:12],
        "high_cardinality": sorted(feature_columns, key=lambda item: int(item.get("unique_count") or 0), reverse=True)[:12],
        "identifier_or_group": [
            column for column in feature_columns if column.get("role") in {"identifier", "group"}
        ][:12],
        "datetime": [column for column in feature_columns if column.get("semantic_type") == "datetime"][:12],
        "text": [column for column in feature_columns if column.get("semantic_type") == "text"][:12],
        "leakage_suspects": [column for column in feature_columns if column.get("is_leakage_suspect")][:12],
    }


def _evaluation_guardrails(
    *,
    target_column: str | None,
    profile: dict[str, Any],
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[dict[str, str]]:
    guardrails: list[dict[str, str]] = []
    if not target_column:
        guardrails.append(
            {
                "guardrail": "Target definition",
                "risk": "blocking",
                "status": "open",
                "detail": "Target may be selected after data understanding or derived by aggregation.",
            }
        )
    leakage = profile.get("leakage_suspects") if isinstance(profile.get("leakage_suspects"), list) else []
    guardrails.append(
        {
            "guardrail": "Prediction-time availability",
            "risk": "high" if leakage else "medium",
            "status": "needs_review" if leakage else "watch",
            "detail": (
                f"Review leakage-suspect columns: {', '.join(str(item) for item in leakage[:8])}."
                if leakage
                else "No name-based leakage suspects, but availability still needs domain confirmation."
            ),
        }
    )
    time_candidates = profile.get("time_candidates") if isinstance(profile.get("time_candidates"), list) else []
    guardrails.append(
        {
            "guardrail": "Time split readiness",
            "risk": "medium" if time_candidates else "low",
            "status": "scenario_compare" if time_candidates else "not_detected",
            "detail": (
                f"Candidate time columns: {', '.join(str(item) for item in time_candidates[:8])}."
                if time_candidates
                else "No time-like columns detected by profile heuristics."
            ),
        }
    )
    group_candidates = profile.get("group_candidates") if isinstance(profile.get("group_candidates"), list) else []
    guardrails.append(
        {
            "guardrail": "Group leakage",
            "risk": "medium" if group_candidates else "low",
            "status": "scenario_compare" if group_candidates else "not_detected",
            "detail": (
                f"Candidate group columns: {', '.join(str(item) for item in group_candidates[:8])}."
                if group_candidates
                else "No repeated entity/group column detected by profile heuristics."
            ),
        }
    )
    quality_summary = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    if quality_summary:
        guardrails.append(
            {
                "guardrail": "Data quality gate",
                "risk": str(quality_summary.get("severity") or "medium"),
                "status": "available",
                "detail": f"Latest quality gate severity: {quality_summary.get('severity', 'unknown')}.",
            }
        )
    if diagnostics:
        guardrails.append(
            {
                "guardrail": "Prediction diagnostics",
                "risk": "medium",
                "status": "available",
                "detail": "Diagnostics artifact can support slice/error analysis in a controlled notebook runner.",
            }
        )
    return guardrails


def _analysis_questions(
    *,
    target_column: str | None,
    target_readiness: dict[str, Any],
    feature_sections: dict[str, list[dict[str, Any]]],
    evaluation_guardrails: list[dict[str, str]],
    runs: list[ExperimentRun],
) -> list[str]:
    questions = [
        "What does one row represent, and what decision happens at prediction time?",
        str(target_readiness["metric_note"]),
    ]
    if not target_column:
        questions.append("Should the target be selected from a column, or derived by aggregation after understanding the tables?")
    if feature_sections["leakage_suspects"]:
        questions.append("Which leakage-suspect columns must be excluded until prediction-time availability is confirmed?")
    if feature_sections["high_cardinality"]:
        questions.append("Which high-cardinality identifiers are entity/group keys versus useful categorical signals?")
    if feature_sections["text"]:
        questions.append("Which text columns deserve TF-IDF, embeddings, summarization, or exclusion because they are leakage-prone?")
    if any(item["status"] == "scenario_compare" for item in evaluation_guardrails):
        questions.append("Should evaluation compare random, stratified, time, and group scenarios before approving a primary spec?")
    questions.append(
        "After the first baseline, inspect feature importance, permutation importance, partial dependence, calibration, slice metrics, and concrete prediction errors."
        if runs
        else "After the first baseline, generate model diagnostics before reading leaderboard rank as a decision."
    )
    return questions


def _compact_column(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(column.get("name") or column.get("column_name") or ""),
        "physical_type": str(column.get("physical_type") or "unknown"),
        "semantic_type": str(column.get("semantic_type") or "unknown"),
        "role": str(column.get("role") or "feature"),
        "missing_rate": _float_value(column.get("missing_rate")),
        "missing_count": int(column.get("missing_count") or 0),
        "unique_count": int(column.get("unique_count") or 0),
        "stats_scope": str(column.get("stats_scope") or "unknown"),
        "is_leakage_suspect": bool(column.get("is_leakage_suspect")),
    }


def _build_findings(
    profile: dict[str, Any],
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
    runs: list[ExperimentRun],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    boundary = profile.get("deferred_deep_profile")
    if isinstance(boundary, dict) and boundary.get("recommended"):
        findings.append(
            {
                "severity": "medium",
                "message": "Column statistics are sample-backed; deep profiling should be scheduled before final evaluation decisions.",
                "next_action": "Run a bounded-to-deep profile follow-up or keep the sampling boundary visible in reports.",
            }
        )
    leakage = profile.get("leakage_suspects")
    if isinstance(leakage, list) and leakage:
        findings.append(
            {
                "severity": "high",
                "message": f"Potential leakage columns detected: {', '.join(str(item) for item in leakage[:6])}.",
                "next_action": "Confirm prediction-time availability and exclude until confirmed.",
            }
        )
    if not profile.get("target_column"):
        findings.append(
            {
                "severity": "medium",
                "message": "No target column is selected; this is acceptable during data understanding.",
                "next_action": "Use profile evidence or aggregation design before creating EvaluationSpec.",
            }
        )
    gate = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    if gate:
        findings.append(
            {
                "severity": str(gate.get("severity") or "info"),
                "message": f"Latest data quality gate reports {gate.get('severity', 'unknown')} severity.",
                "next_action": "Review quality gate evidence before feature design.",
            }
        )
    if diagnostics:
        findings.append(
            {
                "severity": "info",
                "message": "Evaluation diagnostics artifact is available for prediction/error analysis cells.",
                "next_action": "Extend the notebook with diagnostic plots from the artifact.",
            }
        )
    if runs:
        findings.append(
            {
                "severity": "info",
                "message": f"{len(runs)} recent experiment run(s) are available for model comparison cells.",
                "next_action": "Add feature importance, permutation importance, PDP, and slice analysis once model artifacts expose them.",
            }
        )
    return findings or [
        {
            "severity": "info",
            "message": "Profile artifact is available and no high-priority notebook finding was generated.",
            "next_action": "Inspect column profile and decide the next evaluation question.",
        }
    ]


def _run_summary(run: ExperimentRun) -> dict[str, Any]:
    metrics = loads_json(run.metrics_json, {})
    return {
        "id": run.id,
        "status": run.status,
        "runner_type": run.runner_type,
        "evaluation_spec_id": run.evaluation_spec_id,
        "model_version_id": run.model_version_id,
        "metrics": metrics,
    }


def _source_asset_ids(
    dataset: DatasetSnapshot,
    profile_artifact: Artifact | None,
    understanding_artifact: Artifact | None,
) -> list[dict[str, str]]:
    sources = [{"asset_type": "dataset_snapshot", "asset_id": dataset.id}]
    if profile_artifact:
        sources.append({"asset_type": "artifact", "asset_id": profile_artifact.id})
    if understanding_artifact:
        sources.append({"asset_type": "artifact", "asset_id": understanding_artifact.id})
    return sources


def _record_lineage(
    db: Session,
    project: Project,
    dataset: DatasetSnapshot,
    source_artifacts: list[Artifact],
    notebook_artifact: Artifact,
    html_artifact: Artifact,
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=notebook_artifact.id,
        relation_type="informs",
    )
    for artifact in source_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in [html_artifact, manifest_artifact, report_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=notebook_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
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


def _record_model_notebook_lineage(
    db: Session,
    project: Project,
    run: ExperimentRun,
    model_version: ModelVersion | None,
    source_artifacts: list[Artifact],
    notebook_artifact: Artifact,
    html_artifact: Artifact,
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="experiment_run",
        from_asset_id=run.id,
        to_asset_type="artifact",
        to_asset_id=notebook_artifact.id,
        relation_type="diagnoses",
    )
    if model_version is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="model_version",
            from_asset_id=model_version.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in source_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in [html_artifact, manifest_artifact, report_artifact, visualization_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=notebook_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
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
        from_asset_id=notebook_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarizes",
    )


def _record_notebook_execution_plan_lineage(
    db: Session,
    *,
    project: Project,
    notebook_artifact: Artifact,
    linked_artifacts: list[Artifact],
    contract_artifact: Artifact,
    plan_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=notebook_artifact.id,
        to_asset_type="artifact",
        to_asset_id=contract_artifact.id,
        relation_type="plans_execution_for",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=notebook_artifact.id,
        to_asset_type="artifact",
        to_asset_id=plan_artifact.id,
        relation_type="plans_execution_for",
    )
    for artifact in linked_artifacts:
        if artifact.id in {notebook_artifact.id, contract_artifact.id, plan_artifact.id}:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=contract_artifact.id,
            relation_type="informs",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=plan_artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=contract_artifact.id,
        to_asset_type="artifact",
        to_asset_id=plan_artifact.id,
        relation_type="materializes",
    )


def _record_notebook_execution_capture_lineage(
    db: Session,
    *,
    project: Project,
    notebook_artifact: Artifact,
    linked_artifacts: list[Artifact],
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    html_artifact: Artifact,
    figure_manifest_artifact: Artifact,
    source_artifact: Artifact,
) -> None:
    outputs = [manifest_artifact, report_artifact, html_artifact, figure_manifest_artifact, source_artifact]
    for artifact in linked_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=manifest_artifact.id,
            relation_type="informs",
        )
    for artifact in outputs:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=notebook_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="captures_execution_as",
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
    for artifact in [report_artifact, html_artifact, figure_manifest_artifact, source_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=manifest_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="documents",
        )


def _execution_policy() -> dict[str, Any]:
    return {
        "external_dashboard_required": False,
        "external_network_accessed": False,
        "connector_credentials_embedded": False,
        "secrets_embedded": False,
        "notebook_execution": "not_executed_by_generation_endpoint",
        "artifact_capture_required": True,
        "runner_role": "editable_analysis_surface_under_harness_control",
    }


def _count_dict_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"label": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _score_bins(values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    bins: list[dict[str, Any]] = [
        {"bin": "0.0-0.2", "count": 0},
        {"bin": "0.2-0.4", "count": 0},
        {"bin": "0.4-0.6", "count": 0},
        {"bin": "0.6-0.8", "count": 0},
        {"bin": "0.8-1.0", "count": 0},
    ]
    for value in values:
        index = min(4, max(0, int(value * 5)))
        bins[index]["count"] = int(bins[index]["count"]) + 1
    return bins


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _format_metric(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    return f"{number:.6g}"


def _metric_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int | bool | str):
        return str(value)
    if value is None:
        return "-"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _metric_card(label: str, value: object) -> str:
    return f'<div class="panel metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'


def _html_table(rows: list[dict[str, Any]], keys: list[str]) -> str:
    if not rows:
        return "<p>No rows available.</p>"
    head = "".join(f"<th>{escape(key)}</th>" for key in keys)
    body = []
    for row in rows[:16]:
        cells = "".join(f"<td>{escape(str(row.get(key, '-')))}</td>" for key in keys)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _bar_rows(rows: list[dict[str, Any]], label_key: str, value_key: str) -> str:
    if not rows:
        return "<p>No rows available.</p>"
    values = [_float_value(row.get(value_key)) for row in rows]
    max_value = max(values, default=0.0)
    output = []
    for row, value in zip(rows, values, strict=True):
        width = 0.0 if max_value <= 0 else max(4.0, value / max_value * 100)
        output.append(
            '<div class="bar-row">'
            f'<code>{escape(str(row.get(label_key) or ""))}</code>'
            f'<div class="bar-track"><div class="bar" style="width:{width:.1f}%"></div></div>'
            f"<span>{escape(_format_metric(value))}</span>"
            "</div>"
        )
    return "".join(output)


def _badge_rows(rows: list[tuple[str, int]]) -> str:
    if not rows:
        return '<span class="badge">No data</span>'
    return "".join(f'<span class="badge">{escape(label)}: {count}</span>' for label, count in rows)


def _missing_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No missingness profile is available.</p>"
    output = []
    for row in rows:
        rate = max(0.0, min(1.0, _float_value(row.get("missing_rate"))))
        output.append(
            '<div class="bar-row">'
            f'<code>{escape(str(row.get("name") or ""))}</code>'
            f'<div class="bar-track"><div class="bar" style="width:{rate * 100:.1f}%"></div></div>'
            f"<span>{rate:.1%}</span>"
            "</div>"
        )
    return "".join(output)


def _finding_rows(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "<p>No findings generated yet.</p>"
    output = []
    for item in findings:
        severity = str(item.get("severity") or "info")
        output.append(
            f'<div class="finding {escape(severity)}">'
            f"<strong>{escape(severity.upper())}</strong>"
            f"<p>{escape(str(item.get('message') or ''))}</p>"
            f'<div class="tiny">{escape(str(item.get("next_action") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _rubric_rows(rubric: list[dict[str, Any]]) -> str:
    if not rubric:
        return "<p>No rubric available.</p>"
    output = []
    for item in rubric:
        status = str(item.get("status") or "unknown")
        output.append(
            f'<div class="finding {escape(status)}">'
            f"<strong>{escape(str(item.get('area') or 'Quality area'))}</strong>"
            f"<p>{escape(str(item.get('evidence') or 'No evidence yet.'))}</p>"
            f'<div class="tiny">{escape(status)} · {escape(str(item.get("upgrade_path") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _storyboard_rows(storyboard: list[dict[str, Any]]) -> str:
    if not storyboard:
        return "<p>No storyboard available.</p>"
    output = []
    for item in storyboard:
        output.append(
            '<div class="finding">'
            f"<strong>{escape(str(item.get('section') or 'Section'))}</strong>"
            f"<p>{escape(str(item.get('question') or ''))}</p>"
            f'<div class="tiny">{escape(str(item.get("artifact_expectation") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _guardrail_rows(guardrails: list[dict[str, Any]]) -> str:
    if not guardrails:
        return "<p>No guardrails available.</p>"
    output = []
    for item in guardrails:
        risk = str(item.get("risk") or "medium")
        output.append(
            f'<div class="finding {escape(risk)}">'
            f"<strong>{escape(str(item.get('guardrail') or 'Guardrail'))}</strong>"
            f"<p>{escape(str(item.get('detail') or ''))}</p>"
            f'<div class="tiny">{escape(risk)} · {escape(str(item.get("status") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _target_readiness_html(target: dict[str, Any]) -> str:
    if not target:
        return "<p>No target readiness summary available.</p>"
    badges = [
        f'<span class="badge">status: {escape(str(target.get("status") or "unknown"))}</span>',
        f'<span class="badge">unique: {escape(str(target.get("unique_count", "-")))}</span>',
        f'<span class="badge">missing: {escape(str(target.get("missing_count", "-")))}</span>',
    ]
    return (
        f"<p>{escape(str(target.get('summary') or 'No target summary.'))}</p>"
        f"<p><strong>Metric note:</strong> {escape(str(target.get('metric_note') or ''))}</p>"
        f'<div class="badge-row">{"".join(badges)}</div>'
    )


def _feature_queue_rows(feature_sections: dict[str, list[dict[str, Any]]]) -> str:
    if not feature_sections:
        return "<p>No feature queues available.</p>"
    labels = {
        "top_missing": "Missingness",
        "high_cardinality": "High cardinality",
        "identifier_or_group": "Identifier/group",
        "datetime": "Datetime",
        "text": "Text",
        "leakage_suspects": "Leakage suspects",
    }
    blocks = []
    for key, label in labels.items():
        rows = feature_sections.get(key) or []
        names = ", ".join(str(row.get("name") or "") for row in rows[:6]) or "none"
        blocks.append(
            '<div class="finding">'
            f"<strong>{escape(label)}</strong>"
            f"<p>{escape(names)}</p>"
            f'<div class="tiny">{len(rows)} queued column(s)</div>'
            "</div>"
        )
    return f'<div class="findings">{"".join(blocks)}</div>'


def _target_values_text(target: dict[str, Any]) -> str:
    values = target.get("top_values") if isinstance(target.get("top_values"), list) else []
    if not values:
        return "No target value counts are available yet."
    return "; ".join(
        f"{item.get('value')}: {item.get('count')}" for item in values[:8] if isinstance(item, dict)
    )


def _count_rows(rows: list[dict[str, Any]], field: str) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]


def _float_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
