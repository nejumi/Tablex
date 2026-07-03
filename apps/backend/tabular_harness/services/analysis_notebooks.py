from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, cast

from sqlalchemy import and_, func, select
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


@dataclass(frozen=True)
class AnalysisNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    authoring_brief_artifact: Artifact | None
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
    evidence_bundle_artifact: Artifact | None
    evidence_html_artifact: Artifact | None
    figure_artifacts: list[Artifact]
    plan_artifact: Artifact
    contract_artifact: Artifact
    artifact_ids: list[str]


@dataclass
class NotebookArtifactLookup:
    by_asset_type: dict[str, list[Artifact]]
    by_session_id: dict[str, list[Artifact]]
    metadata_by_artifact_id: dict[str, dict[str, Any]]
    workspace_path_by_artifact_id: dict[str, str]
    text_by_artifact_id: dict[str, str]
    generic_candidates_by_session_id: dict[str, list[Artifact]]
    kind_candidates_by_session_id: dict[tuple[str, str], list[Artifact]]
    stem_candidates_by_session_id: dict[tuple[str, str], list[Artifact]]


NOTEBOOK_INDEX_ASSET_TYPES = {
    "analysis_notebook",
    "marimo_notebook",
    "notebook_html",
    "notebook_run_manifest",
    "notebook_report",
    "notebook_execution_plan",
    "notebook_execution_manifest",
    "notebook_execution_report",
    "notebook_execution_html",
    "notebook_execution_source",
    "notebook_figure_manifest",
    "notebook_evidence_bundle",
    "notebook_evidence_html",
    "notebook_evidence_svg",
    "agent_task_contract",
    "visualization_spec",
    "agent_session_report",
    "agent_session_artifact",
    "agent_session_output",
    "agent_session_figure",
}


def create_data_understanding_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    response_locale: str | None = None,
) -> AnalysisNotebookResult:
    raise ValueError(
        "Harness-authored Data Understanding notebooks are disabled. "
        "Create a notebook_authoring_brief and let Codex/AgentRunner author the notebook artifact."
    )


def build_project_notebook_index(db: Session, project: Project) -> dict[str, Any]:
    project_artifacts = list_latest_notebook_index_artifacts(db, project.id)
    artifact_lookup = _build_notebook_artifact_lookup(project_artifacts)
    notebook_artifacts = [
        artifact for artifact in project_artifacts if artifact.asset_type in {"analysis_notebook", "marimo_notebook"}
    ]
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
            artifact_lookup=artifact_lookup,
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


def list_latest_notebook_index_artifacts(db: Session, project_id: str) -> list[Artifact]:
    latest_versions = (
        select(
            Artifact.asset_type.label("asset_type"),
            Artifact.name.label("name"),
            func.max(Artifact.version).label("version"),
        )
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type.in_(NOTEBOOK_INDEX_ASSET_TYPES),
        )
        .group_by(Artifact.asset_type, Artifact.name)
        .subquery()
    )
    return list(
        db.scalars(
            select(Artifact)
            .join(
                latest_versions,
                and_(
                    Artifact.asset_type == latest_versions.c.asset_type,
                    Artifact.name == latest_versions.c.name,
                    Artifact.version == latest_versions.c.version,
                ),
            )
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
        ).all()
    )


def build_project_analysis_story(db: Session, project: Project) -> dict[str, Any]:
    notebook_index = build_project_notebook_index(db, project)
    candidates = [
        candidate
        for candidate in [
            _analysis_story_from_notebook(db, project, notebook_index),
            _analysis_story_from_eda_review(db, project),
        ]
        if candidate is not None
    ]
    selected = max(candidates, key=lambda candidate: int(candidate["selection_score"])) if candidates else None
    if selected is None:
        return {
            "schema_version": "analysis_story_surface.v1",
            "project_id": project.id,
            "generated_at": utc_now().isoformat(),
            "available": False,
            "story": None,
            "empty_state": {
                "headline": "Create the first readable analysis story.",
                "reason": (
                    "No Data Review or analysis notebook evidence is available yet. Start with harness-owned EDA, "
                    "then let Codex extend the notebook when the next question is clear."
                ),
                "primary_action": {
                    "label": "Run EDA Review",
                    "action_type": "api",
                    "endpoint": "/api/datasets/{dataset_snapshot_id}/eda-review",
                    "target_tab": "Notebooks",
                },
            },
            "notebook_index": notebook_index,
        }
    source_candidates = [
        _analysis_story_source_summary(candidate)
        for candidate in sorted(candidates, key=lambda candidate: int(candidate["selection_score"]), reverse=True)
    ]
    selected["supporting_sources"] = source_candidates[1:4]
    selected.pop("selection_score", None)
    return {
        "schema_version": "analysis_story_surface.v1",
        "project_id": project.id,
        "generated_at": utc_now().isoformat(),
        "available": True,
        "story": selected,
        "empty_state": None,
        "notebook_index": notebook_index,
    }


def _analysis_story_from_notebook(
    db: Session,
    project: Project,
    notebook_index: dict[str, Any],
) -> dict[str, Any] | None:
    items = [cast(dict[str, Any], item) for item in _list_value(notebook_index.get("items"))]
    recommended = _dict_value(notebook_index.get("recommended_notebook")) or None
    fallback_data = next((item for item in items if str(item.get("notebook_kind")) == "data_understanding"), None)
    diverted = bool(recommended and _story_item_is_empty_diagnostics(recommended) and fallback_data is not None)
    selected_item = fallback_data if diverted else recommended
    if selected_item is None:
        return None
    notebook_artifact = db.get(Artifact, str(selected_item["notebook_artifact_id"]))
    if notebook_artifact is None:
        return None
    summary = _notebook_artifact_context_summary(notebook_artifact)
    brief = _dict_value(summary.get("analysis_brief"))
    linked_artifact_ids = _dict_value(selected_item.get("artifact_ids"))
    evidence_html = _latest_artifact_for_metadata(
        db,
        project.id,
        "notebook_evidence_html",
        "notebook_artifact_id",
        notebook_artifact.id,
    )
    evidence_figures = _artifacts_for_metadata(
        db,
        project.id,
        "notebook_evidence_svg",
        "notebook_artifact_id",
        notebook_artifact.id,
    )
    preview_artifact_id = (
        evidence_html.id
        if evidence_html is not None
        else _first_text_value(
            linked_artifact_ids.get("execution_html"),
            linked_artifact_ids.get("html_preview"),
            linked_artifact_ids.get("report_artifact"),
            linked_artifact_ids.get("notebook"),
        )
    )
    read_order = _analysis_story_read_order(brief.get("read_this_first"))
    story_cards = _analysis_story_cards(summary.get("visual_story_cards"))
    playbook = _analysis_story_playbook(summary.get("eda_playbook") or summary.get("review_playbook"))
    codex_prompts = _string_list(summary.get("codex_navigation_prompts"))
    if not codex_prompts:
        codex_prompts = _string_list(summary.get("analysis_questions"))
    caveats = _notebook_story_caveats(
        brief=brief,
        selected_item=selected_item,
        diverted_from_empty_diagnostics=diverted,
    )
    selection_score = int(selected_item.get("recommendation_score") or 0)
    if evidence_html is not None:
        selection_score += 35
    if diverted:
        selection_score += 20
    return {
        "source_type": "analysis_notebook",
        "headline": _story_headline(
            brief.get("headline"),
            selected_item.get("title"),
            fallback="Read the recommended analysis notebook.",
        ),
        "deck": str(summary.get("overview") or selected_item.get("recommendation_reason") or ""),
        "why_this_story": (
            "Tablex is routing around an empty diagnostics notebook and returning to Data Understanding first."
            if diverted
            else str(selected_item.get("recommendation_reason") or "This notebook has the strongest current analysis evidence.")
        ),
        "selected_source": {
            "source_type": "analysis_notebook",
            "title": str(selected_item.get("title") or "Analysis Notebook"),
            "artifact_id": notebook_artifact.id,
            "preview_artifact_id": preview_artifact_id,
            "report_id": selected_item.get("report_id"),
            "notebook_kind": selected_item.get("notebook_kind"),
            "status": selected_item.get("content", {}).get("readiness")
            if isinstance(selected_item.get("content"), dict)
            else selected_item.get("status"),
            "created_at": selected_item.get("created_at"),
            "reason": selected_item.get("recommendation_reason"),
        },
        "read_order": read_order,
        "visual_story_cards": story_cards,
        "evidence_cards": _notebook_evidence_cards(selected_item, evidence_figures),
        "playbook": playbook,
        "caveats": caveats,
        "codex_prompts": codex_prompts[:4],
        "primary_action": _notebook_story_primary_action(
            selected_item=selected_item,
            preview_artifact_id=preview_artifact_id,
            evidence_html=evidence_html,
        ),
        "figure_refs": _artifact_refs(evidence_figures[:6]),
        "raw_artifacts": _story_raw_artifact_refs(db, project.id, notebook_artifact, linked_artifact_ids, evidence_html, evidence_figures),
        "metrics": {
            "quality_score": selected_item.get("content", {}).get("quality_score")
            if isinstance(selected_item.get("content"), dict)
            else None,
            "read_order_count": len(read_order),
            "story_card_count": len(story_cards),
            "figure_count": len(evidence_figures),
        },
        "selection_score": selection_score,
    }


def _analysis_story_from_eda_review(db: Session, project: Project) -> dict[str, Any] | None:
    bundle_artifact = latest_project_artifact(db, project.id, "eda_review_bundle")
    review = _read_json_artifact(bundle_artifact)
    if bundle_artifact is None or not review:
        return None
    summary = _dict_value(review.get("summary"))
    html_artifact = _latest_artifact_for_metadata(
        db,
        project.id,
        "eda_review_html",
        "eda_review_bundle_artifact_id",
        bundle_artifact.id,
    )
    report_artifact = _latest_artifact_for_metadata(
        db,
        project.id,
        "eda_review_report",
        "eda_review_bundle_artifact_id",
        bundle_artifact.id,
    )
    figure_artifacts = _artifacts_for_metadata(
        db,
        project.id,
        "eda_review_svg",
        "eda_review_bundle_artifact_id",
        bundle_artifact.id,
    )
    quality_score = int(summary.get("quality_score") or 0)
    preview_artifact_id = html_artifact.id if html_artifact is not None else report_artifact.id if report_artifact else bundle_artifact.id
    return {
        "source_type": "eda_review",
        "headline": _story_headline(summary.get("headline"), None, fallback="Read the latest Data Review."),
        "deck": (
            f"{int(summary.get('row_count') or 0):,} rows, {int(summary.get('column_count') or 0):,} columns, "
            f"objective {summary.get('target_column') or 'not selected'}."
        ),
        "why_this_story": (
            "The Data Review is harness-controlled DuckDB analysis with figures, findings, read order, and Codex prompts. "
            "Use it as the first human-readable analysis surface before scanning raw artifacts."
        ),
        "selected_source": {
            "source_type": "eda_review",
            "title": "Data Review",
            "artifact_id": bundle_artifact.id,
            "preview_artifact_id": preview_artifact_id,
            "report_id": _latest_report_id_for_artifact(db, report_artifact),
            "notebook_kind": None,
            "status": summary.get("severity") or "review",
            "created_at": bundle_artifact.created_at.isoformat(),
            "reason": "Latest harness-controlled EDA review.",
        },
        "read_order": _analysis_story_read_order(review.get("read_this_first")),
        "visual_story_cards": _analysis_story_cards(review.get("story_cards")),
        "evidence_cards": _eda_review_evidence_cards(review),
        "playbook": _analysis_story_playbook(review.get("playbook")),
        "caveats": _eda_review_caveats(review),
        "codex_prompts": _string_list(review.get("codex_next_prompts"))[:4],
        "primary_action": {
            "label": "Open Data Review",
            "action_type": "preview",
            "artifact_id": preview_artifact_id,
            "target_tab": "Notebooks",
        },
        "figure_refs": _artifact_refs(figure_artifacts[:6]),
        "raw_artifacts": _artifact_refs([bundle_artifact, *[item for item in [html_artifact, report_artifact] if item is not None], *figure_artifacts[:6]]),
        "metrics": {
            "quality_score": quality_score,
            "read_order_count": len(_list_value(review.get("read_this_first"))),
            "story_card_count": len(_list_value(review.get("story_cards"))),
            "figure_count": len(figure_artifacts),
        },
        "selection_score": 85 + min(35, quality_score // 2) + (20 if html_artifact is not None else 0),
    }


def _analysis_story_source_summary(story: dict[str, Any]) -> dict[str, Any]:
    selected = _dict_value(story.get("selected_source"))
    return {
        "source_type": story.get("source_type"),
        "title": selected.get("title"),
        "artifact_id": selected.get("artifact_id"),
        "preview_artifact_id": selected.get("preview_artifact_id"),
        "status": selected.get("status"),
        "reason": selected.get("reason"),
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
    if not source_validation["is_capture_eligible"]:
        raise ValueError("Only valid marimo analysis notebooks can be captured by the local execution path")
    compile_result = run_notebook_static_compile(notebook_source)
    marimo_export_result = (
        run_marimo_html_export(notebook_artifact, notebook_source)
        if compile_result["status"] == "succeeded"
        else {
            "schema_version": "marimo_html_export.v1",
            "status": "skipped",
            "reason": "python_compile_failed",
            "html": None,
        }
    )
    execution_status = notebook_execution_status(compile_result, marimo_export_result)
    capture_mode = (
        "marimo_html_export"
        if marimo_export_result["status"] == "succeeded"
        else "safe_static_capture"
    )
    generated_at = utc_now().isoformat()
    suffix = new_id("nbcap")
    evidence_capture = create_notebook_evidence_artifacts(
        db,
        store,
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        notebook_source=notebook_source,
        linked_artifacts=linked_artifacts,
        suffix=suffix,
        generated_at=generated_at,
        execution_status=execution_status,
    )
    figure_manifest = build_notebook_figure_manifest(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        compile_result=compile_result,
        generated_at=generated_at,
        rendered_figures=evidence_capture["figures"],
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
            "capture_mode": capture_mode,
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
            "capture_mode": capture_mode,
        },
    )
    manifest = build_notebook_execution_manifest(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        linked_artifacts=linked_artifacts,
        source_validation=source_validation,
        compile_result=compile_result,
        marimo_export_result=marimo_export_result,
        execution_status=execution_status,
        generated_at=generated_at,
        plan_created=plan_created,
        output_artifacts={
            "notebook_figure_manifest_artifact_id": figure_manifest_artifact.id,
            "notebook_execution_source_artifact_id": source_artifact.id,
            "notebook_evidence_bundle_artifact_id": evidence_capture["bundle_artifact"].id
            if evidence_capture["bundle_artifact"]
            else None,
            "notebook_evidence_html_artifact_id": evidence_capture["html_artifact"].id
            if evidence_capture["html_artifact"]
            else None,
            "notebook_evidence_figure_artifact_ids": [
                artifact.id for artifact in evidence_capture["figure_artifacts"]
            ],
        },
    )
    html = (
        str(marimo_export_result["html"])
        if marimo_export_result["status"] == "succeeded" and marimo_export_result.get("html")
        else render_notebook_execution_html_preview(manifest)
    )
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
            "capture_mode": capture_mode,
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
            "capture_mode": capture_mode,
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
            "capture_mode": capture_mode,
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
        evidence_artifacts=[
            artifact
            for artifact in [
                evidence_capture["bundle_artifact"],
                evidence_capture["html_artifact"],
                *evidence_capture["figure_artifacts"],
            ]
            if artifact is not None
        ],
    )
    artifact_ids = [
        manifest_artifact.id,
        report_artifact.id,
        html_artifact.id,
        figure_manifest_artifact.id,
        source_artifact.id,
        *[artifact.id for artifact in evidence_capture["figure_artifacts"]],
    ]
    if evidence_capture["bundle_artifact"]:
        artifact_ids.append(evidence_capture["bundle_artifact"].id)
    if evidence_capture["html_artifact"]:
        artifact_ids.append(evidence_capture["html_artifact"].id)
    return NotebookExecutionCaptureResult(
        manifest=manifest,
        report=report,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        html_artifact=html_artifact,
        figure_manifest_artifact=figure_manifest_artifact,
        source_artifact=source_artifact,
        evidence_bundle_artifact=evidence_capture["bundle_artifact"],
        evidence_html_artifact=evidence_capture["html_artifact"],
        figure_artifacts=evidence_capture["figure_artifacts"],
        plan_artifact=plan_artifact,
        contract_artifact=contract_artifact,
        artifact_ids=artifact_ids,
    )


def create_notebook_evidence_artifacts(
    db: Session,
    store: LocalArtifactStore,
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    notebook_source: str,
    linked_artifacts: dict[str, Artifact | None],
    suffix: str,
    generated_at: str,
    execution_status: str,
) -> dict[str, Any]:
    context = extract_notebook_context(notebook_source)
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    if not summary:
        return {
            "bundle_artifact": None,
            "html_artifact": None,
            "figure_artifacts": [],
            "figures": [],
        }

    figure_specs = build_notebook_evidence_figure_specs(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        summary=cast(dict[str, Any], summary),
        generated_at=generated_at,
    )
    figure_artifacts: list[Artifact] = []
    figure_refs: list[dict[str, Any]] = []
    for spec in figure_specs:
        artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="notebook_evidence_svg",
            name=f"{spec['figure_id']}_{suffix}",
            filename=f"{spec['figure_id']}.svg",
            text=str(spec["svg"]),
            metadata={
                "project_id": project.id,
                "notebook_artifact_id": notebook_artifact.id,
                "notebook_kind": notebook_kind,
                "execution_status": execution_status,
                "capture_mode": "safe_profile_evidence_render",
                "figure_id": spec["figure_id"],
                "content_type": "image/svg+xml",
            },
        )
        figure_artifacts.append(artifact)
        figure_refs.append(
            {
                "slot": spec["figure_id"],
                "figure_id": spec["figure_id"],
                "title": spec["title"],
                "description": spec["description"],
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "content_type": "image/svg+xml",
                "render_status": "rendered_from_profile_artifacts",
                "runtime_execution_status": "notebook_cells_not_executed",
            }
        )

    bundle = build_notebook_evidence_bundle(
        project=project,
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        summary=cast(dict[str, Any], summary),
        linked_artifacts=linked_artifacts,
        figures=figure_refs,
        generated_at=generated_at,
        execution_status=execution_status,
    )
    bundle_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_evidence_bundle",
        name=f"notebook_evidence_bundle_{suffix}",
        filename="notebook_evidence_bundle.json",
        payload=bundle,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_profile_evidence_render",
            "figure_count": len(figure_refs),
        },
    )
    html = render_notebook_evidence_html(bundle, figure_specs)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_evidence_html",
        name=f"notebook_evidence_preview_{suffix}",
        filename="notebook_evidence_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": notebook_kind,
            "execution_status": execution_status,
            "capture_mode": "safe_profile_evidence_render",
            "notebook_evidence_bundle_artifact_id": bundle_artifact.id,
            "content_type": "text/html",
        },
    )
    return {
        "bundle_artifact": bundle_artifact,
        "html_artifact": html_artifact,
        "figure_artifacts": figure_artifacts,
        "figures": figure_refs,
    }


def extract_notebook_context(source: str) -> dict[str, Any]:
    marker = "context = "
    start = source.find(marker)
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(source[start + len(marker) :].lstrip())
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def build_notebook_evidence_bundle(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    summary: dict[str, Any],
    linked_artifacts: dict[str, Artifact | None],
    figures: list[dict[str, Any]],
    generated_at: str,
    execution_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": "notebook_evidence_bundle.v1",
        "project_id": project.id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": generated_at,
        "capture_mode": "safe_profile_evidence_render",
        "execution_status": execution_status,
        "runtime_execution_status": "notebook_cells_not_executed",
        "summary": {
            "title": summary.get("title"),
            "overview": summary.get("overview"),
            "primary_metric_name": summary.get("primary_metric_name"),
            "primary_metric_value": summary.get("primary_metric_value"),
            "eda_quality_score": summary.get("eda_quality_score"),
            "target_readiness": summary.get("target_readiness"),
            "result_interpretation": summary.get("result_interpretation", {}),
            "metric_comparison": summary.get("metric_comparison", {}),
            "sanity_floor": summary.get("sanity_floor", {}),
            "model_diagnostics_artifacts": summary.get("model_diagnostics_artifacts", {}),
            "figure_count": len(figures),
            "guardrail_count": len(summary.get("evaluation_guardrails", []))
            if isinstance(summary.get("evaluation_guardrails"), list)
            else 0,
            "analysis_question_count": len(summary.get("analysis_questions", []))
            if isinstance(summary.get("analysis_questions"), list)
            else 0,
        },
        "figures": figures,
        "tables": {
            "analysis_brief": summary.get("analysis_brief", {}),
            "result_interpretation": summary.get("result_interpretation", {}),
            "metric_comparison": summary.get("metric_comparison", {}),
            "sanity_floor": summary.get("sanity_floor", {}),
            "model_diagnostics_artifacts": summary.get("model_diagnostics_artifacts", {}),
            "quality_rubric": summary.get("quality_rubric", []),
            "analysis_storyboard": summary.get("analysis_storyboard", []),
            "eda_playbook": summary.get("eda_playbook", []),
            "visual_story_cards": summary.get("visual_story_cards", []),
            "feature_family_summary": summary.get("feature_family_summary", []),
            "evaluation_guardrails": summary.get("evaluation_guardrails", []),
            "analysis_questions": summary.get("analysis_questions", []),
            "codex_navigation_prompts": summary.get("codex_navigation_prompts", []),
            "feature_review_sections": summarize_feature_review_sections(summary.get("feature_review_sections")),
        },
        "linked_artifacts": _linked_artifact_refs(linked_artifacts),
        "safety_policy": {
            "arbitrary_notebook_code_executed": False,
            "marimo_cells_executed": False,
            "external_network_accessed": False,
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "render_source": "embedded_notebook_context_and_profile_artifacts",
        },
    }


def summarize_feature_review_sections(value: object) -> dict[str, Any]:
    sections = value if isinstance(value, dict) else {}
    output: dict[str, Any] = {}
    for key, rows in sections.items():
        if not isinstance(rows, list):
            continue
        output[str(key)] = {
            "count": len(rows),
            "columns": [
                {
                    "name": str(row.get("name") or ""),
                    "semantic_type": str(row.get("semantic_type") or "unknown"),
                    "role": str(row.get("role") or "feature"),
                    "missing_rate": _float_value(row.get("missing_rate")),
                    "unique_count": int(row.get("unique_count") or 0),
                }
                for row in rows[:12]
                if isinstance(row, dict)
            ],
        }
    return output


def build_notebook_evidence_figure_specs(
    *,
    project: Project,
    notebook_artifact: Artifact,
    notebook_kind: str,
    summary: dict[str, Any],
    generated_at: str,
) -> list[dict[str, str]]:
    if notebook_kind == "model_diagnostics":
        prediction_summary = _dict_value(summary.get("prediction_summary"))
        score_bins = [
            cast(dict[str, Any], item)
            for item in _list_value(prediction_summary.get("score_bins"))
            if isinstance(item, dict)
        ]
        feature_rows = [
            cast(dict[str, Any], item)
            for item in _list_value(summary.get("feature_family_rows"))
            if isinstance(item, dict)
        ]
        findings = [
            cast(dict[str, Any], item)
            for item in _list_value(summary.get("findings"))
            if isinstance(item, dict)
        ]
        model_artifacts = _dict_value(summary.get("model_diagnostics_artifacts"))
        native_top_features = [
            cast(dict[str, Any], item)
            for item in _list_value(_dict_value(model_artifacts.get("native_feature_importance")).get("top_features"))
            if isinstance(item, dict)
        ]
        permutation_top_features = [
            cast(dict[str, Any], item)
            for item in _list_value(_dict_value(model_artifacts.get("permutation_importance")).get("top_features"))
            if isinstance(item, dict)
        ]
        return [
            {
                "figure_id": "diagnostics_readiness",
                "title": "Diagnostics Readiness",
                "description": "Whether the model notebook has enough evidence for human review.",
                "svg": svg_metric_cards(
                    title="Diagnostics readiness",
                    rows=[
                        {
                            "label": "Primary metric",
                            "value": f"{summary.get('primary_metric_name') or 'metric'}={_format_metric(summary.get('primary_metric_value'))}",
                            "detail": "approved EvaluationSpec metric",
                        },
                        {
                            "label": "Predictions",
                            "value": f"{int(prediction_summary.get('row_count') or 0):,}",
                            "detail": "validation rows summarized",
                        },
                        {
                            "label": "Diagnostics",
                            "value": str(summary.get("evidence_readiness") or "unknown").replace("_", " "),
                            "detail": str(summary.get("diagnostics_coverage") or "coverage not recorded")[:72],
                        },
                        {
                            "label": "Quality",
                            "value": str(summary.get("evidence_quality_score") or 0),
                            "detail": f"{len(findings)} finding(s), {len(feature_rows)} feature families",
                        },
                    ],
                ),
            },
            {
                "figure_id": "feature_family_inventory",
                "title": "Feature Family Inventory",
                "description": "Feature families reported by the model run.",
                "svg": svg_bar_chart(
                    title="Feature family inventory",
                    rows=[
                        {"label": str(row.get("family") or "unknown"), "value": int(row.get("count") or 0)}
                        for row in feature_rows
                    ],
                    value_format="integer",
                    empty_message="Feature-family counts are not available for this run yet.",
                ),
            },
            {
                "figure_id": "native_feature_importance",
                "title": "Native Feature Importance",
                "description": "Top stored-model feature importances when the model package exposes them.",
                "svg": svg_bar_chart(
                    title="Native feature importance",
                    rows=[
                        {
                            "label": str(row.get("feature_name") or "feature")[:80],
                            "value": _float_value(row.get("importance")),
                        }
                        for row in native_top_features[:12]
                    ],
                    value_format="float",
                    empty_message="Native feature importance is not available yet. Materialize model diagnostics artifacts first.",
                ),
            },
            {
                "figure_id": "permutation_importance",
                "title": "Permutation Importance",
                "description": "Bounded validation-split permutation deltas for the stored model package.",
                "svg": svg_bar_chart(
                    title="Permutation importance",
                    rows=[
                        {
                            "label": str(row.get("feature_name") or "feature")[:80],
                            "value": _float_value(row.get("importance_delta")),
                        }
                        for row in permutation_top_features[:12]
                    ],
                    value_format="float",
                    empty_message="Permutation importance is not available yet. Materialize model diagnostics artifacts first.",
                ),
            },
            {
                "figure_id": "prediction_score_bins",
                "title": "Prediction Score Bins",
                "description": "Prediction score distribution when prediction artifacts are available.",
                "svg": svg_bar_chart(
                    title="Prediction score bins",
                    rows=[
                        {"label": str(row.get("bin") or "bin"), "value": int(row.get("count") or 0)}
                        for row in score_bins
                    ],
                    value_format="integer",
                    empty_message="Prediction score bins are not available. Persist validation predictions before reading model behavior.",
                ),
            },
            {
                "figure_id": "diagnostics_attention_counts",
                "title": "Diagnostics Attention Counts",
                "description": "Finding severity counts for the next model-review action.",
                "svg": svg_bar_chart(
                    title="Diagnostics attention counts",
                    rows=[
                        {"label": severity, "value": count}
                        for severity, count in _count_rows(findings, "severity")
                    ],
                    value_format="integer",
                    empty_message="No findings are available yet.",
                ),
            },
        ]
    if notebook_kind != "data_understanding":
        return [
            {
                "figure_id": "notebook_evidence_summary",
                "title": "Notebook Evidence Summary",
                "description": "Evidence rendered from available notebook context.",
                "svg": svg_message_chart(
                    title="Notebook evidence",
                    message="No specialized evidence renderer exists for this notebook kind yet.",
                    subtitle=f"Project {project.name} | Notebook {notebook_artifact.id} | {generated_at}",
                ),
            }
        ]

    columns = [cast(dict[str, Any], item) for item in _list_value(summary.get("columns")) if isinstance(item, dict)]
    target = _dict_value(summary.get("target_readiness"))
    feature_sections = _dict_value(summary.get("feature_review_sections"))
    top_missing = [cast(dict[str, Any], item) for item in _list_value(feature_sections.get("top_missing")) if isinstance(item, dict)]
    target_top_values = [cast(dict[str, Any], item) for item in _list_value(target.get("top_values")) if isinstance(item, dict)]
    feature_family_summary = [
        cast(dict[str, Any], item) for item in _list_value(summary.get("feature_family_summary")) if isinstance(item, dict)
    ]
    findings = [cast(dict[str, Any], item) for item in _list_value(summary.get("findings")) if isinstance(item, dict)]
    guardrails = [
        cast(dict[str, Any], item) for item in _list_value(summary.get("evaluation_guardrails")) if isinstance(item, dict)
    ]
    return [
        {
            "figure_id": "feature_family_counts",
            "title": "Feature Family Counts",
            "description": "Semantic feature-family counts for choosing analysis tactics.",
            "svg": svg_bar_chart(
                title="Feature family counts",
                rows=[
                    {"label": str(row.get("family") or "unknown"), "value": int(row.get("count") or 0)}
                    for row in feature_family_summary
                    if isinstance(row, dict)
                ],
                value_format="integer",
            ),
        },
        {
            "figure_id": "top_missing_columns_bar",
            "title": "Top Missing Columns",
            "description": "Highest missing-rate columns from the profiled dataset.",
            "svg": svg_bar_chart(
                title="Top missing columns",
                rows=[
                    {"label": str(row.get("name") or ""), "value": _float_value(row.get("missing_rate"))}
                    for row in top_missing
                ][:12],
                value_format="percent",
            ),
        },
        {
            "figure_id": "semantic_type_role_mix",
            "title": "Semantic Type Mix",
            "description": "Column semantic-type counts inferred from names and physical types.",
            "svg": svg_bar_chart(
                title="Semantic type mix",
                rows=[
                    {"label": label, "value": count}
                    for label, count in _count_rows([row for row in columns if isinstance(row, dict)], "semantic_type")
                ],
                value_format="integer",
            ),
        },
        {
            "figure_id": "target_profile_summary",
            "title": "Target Profile Summary",
            "description": "Top target values when a target is selected; otherwise a target-readiness reminder.",
            "svg": svg_bar_chart(
                title="Target value distribution",
                rows=[
                    {"label": str(row.get("value") or "null"), "value": int(row.get("count") or 0)}
                    for row in target_top_values
                ],
                value_format="integer",
                empty_message=str(target.get("summary") or "No target selected yet."),
            ),
        },
        {
            "figure_id": "risk_attention_counts",
            "title": "Risk Attention Counts",
            "description": "Counts of findings and guardrails that deserve human/Codex attention.",
            "svg": svg_bar_chart(
                title="Risk attention counts",
                rows=[
                    {
                        "label": "high findings",
                        "value": len(
                            [
                                item
                                for item in findings
                                if str(item.get("severity") or "") in {"high", "blocking"}
                            ]
                        ),
                    },
                    {"label": "all findings", "value": len(findings)},
                    {
                        "label": "high guardrails",
                        "value": len(
                            [
                                item
                                for item in guardrails
                                if str(item.get("risk") or "") in {"high", "blocking"}
                            ]
                        ),
                    },
                    {"label": "all guardrails", "value": len(guardrails)},
                ],
                value_format="integer",
            ),
        },
        {
            "figure_id": "feature_review_queue_counts",
            "title": "Feature Review Queue Counts",
            "description": "Counts of columns queued for focused human/Codex review.",
            "svg": svg_bar_chart(
                title="Feature review queues",
                rows=[
                    {
                        "label": label,
                        "value": len(items) if isinstance(items, list) else 0,
                    }
                    for label, items in feature_sections.items()
                ],
                value_format="integer",
            ),
        },
    ]


def svg_bar_chart(
    *,
    title: str,
    rows: list[dict[str, Any]],
    value_format: str,
    empty_message: str = "No data available yet.",
) -> str:
    width = 900
    row_height = 34
    top = 74
    left = 230
    right = 64
    chart_width = width - left - right
    normalized_rows: list[tuple[str, float]] = [
        (str(row.get("label") or ""), max(0.0, _float_value(row.get("value"))))
        for row in rows
        if str(row.get("label") or "")
    ][:14]
    height = max(220, top + max(1, len(normalized_rows)) * row_height + 42)
    max_value = max((value for _, value in normalized_rows), default=0.0)
    body: list[str] = []
    if not normalized_rows or max_value <= 0:
        body.append(f'<text x="{left}" y="{top + 38}" fill="#52606f" font-size="18">{escape(empty_message)}</text>')
    else:
        for index, (label, value) in enumerate(normalized_rows):
            y = top + index * row_height
            bar_width = max(4.0, value / max_value * chart_width)
            body.extend(
                [
                    f'<text x="24" y="{y + 21}" fill="#20304f" font-size="15">{escape(label[:34])}</text>',
                    f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="6" fill="url(#bar)"/>',
                    f'<text x="{left + bar_width + 8:.1f}" y="{y + 17}" fill="#52606f" font-size="13">{escape(format_svg_value(value, value_format))}</text>',
                ]
            )
    return svg_chart_shell(title=title, width=width, height=height, body="\n".join(body))


def svg_metric_cards(*, title: str, rows: list[dict[str, Any]]) -> str:
    width = 900
    card_width = 196
    card_height = 118
    gap = 18
    left = 28
    top = 76
    normalized_rows = [
        {
            "label": str(row.get("label") or "Metric")[:30],
            "value": str(row.get("value") or "-")[:32],
            "detail": str(row.get("detail") or "")[:84],
        }
        for row in rows[:4]
    ]
    body: list[str] = []
    if not normalized_rows:
        body.append('<text x="42" y="120" fill="#52606f" font-size="18">No model diagnostic evidence is available yet.</text>')
    for index, row in enumerate(normalized_rows):
        x = left + index * (card_width + gap)
        detail_lines = wrap_svg_text(row["detail"], 34, 2)
        body.extend(
            [
                f'<rect x="{x}" y="{top}" width="{card_width}" height="{card_height}" rx="14" fill="#ffffff" stroke="#dbe3f3"/>',
                f'<text x="{x + 16}" y="{top + 30}" fill="#52606f" font-size="13" font-weight="700">{escape(row["label"])}</text>',
                f'<text x="{x + 16}" y="{top + 62}" fill="#10183f" font-size="20" font-weight="800">{escape(row["value"])}</text>',
            ]
        )
        for line_index, line in enumerate(detail_lines):
            body.append(
                f'<text x="{x + 16}" y="{top + 88 + line_index * 18}" fill="#52606f" font-size="12">{escape(line)}</text>'
            )
    return svg_chart_shell(title=title, width=width, height=230, body="\n".join(body))


def svg_message_chart(*, title: str, message: str, subtitle: str) -> str:
    body = (
        f'<text x="42" y="108" fill="#20304f" font-size="22">{escape(message)}</text>'
        f'<text x="42" y="146" fill="#52606f" font-size="14">{escape(subtitle)}</text>'
    )
    return svg_chart_shell(title=title, width=900, height=220, body=body)


def svg_chart_shell(*, title: str, width: int, height: int, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop stop-color="#f8fbff"/>
      <stop offset="1" stop-color="#eef8f6"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" x2="1">
      <stop stop-color="#18b8a6"/>
      <stop offset="1" stop-color="#3867f3"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#bg)"/>
  <text x="24" y="42" fill="#10183f" font-size="24" font-weight="700">{escape(title)}</text>
  {body}
</svg>'''


def format_svg_value(value: float, value_format: str) -> str:
    if value_format == "percent":
        return f"{value:.1%}"
    if value_format == "integer":
        return f"{int(round(value)):,}"
    return f"{value:.4g}"


def wrap_svg_text(value: str, width: int, max_lines: int) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        joined = " ".join(words)
        if len(joined) > sum(len(line) for line in lines):
            lines[-1] = f"{lines[-1].rstrip('.')[: max(0, width - 3)]}..."
    return lines


def render_notebook_evidence_html(bundle: dict[str, Any], figure_specs: list[dict[str, str]]) -> str:
    summary = cast(dict[str, Any], bundle["summary"])
    tables = cast(dict[str, Any], bundle["tables"])
    notebook_kind = str(bundle.get("notebook_kind") or "analysis")
    kind_label = notebook_kind.replace("_", " ").title()
    playbook_title = "EDA playbook" if notebook_kind == "data_understanding" else "Review playbook"
    brief = _dict_value(tables.get("analysis_brief"))
    read_order = [
        cast(dict[str, Any], item) for item in _list_value(brief.get("read_this_first")) if isinstance(item, dict)
    ]
    playbook = [cast(dict[str, Any], item) for item in _list_value(tables.get("eda_playbook")) if isinstance(item, dict)]
    story_cards = [
        cast(dict[str, Any], item) for item in _list_value(tables.get("visual_story_cards")) if isinstance(item, dict)
    ]
    prompts = _list_value(tables.get("codex_navigation_prompts"))
    questions = _list_value(tables.get("analysis_questions"))
    interpretation = _dict_value(tables.get("result_interpretation") or summary.get("result_interpretation"))
    guardrails = [
        cast(dict[str, Any], item) for item in _list_value(tables.get("evaluation_guardrails")) if isinstance(item, dict)
    ]
    figures_html = "".join(
        f'<section class="panel"><h2>{escape(spec["title"])}</h2><p>{escape(spec["description"])}</p>{spec["svg"]}</section>'
        for spec in figure_specs
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Notebook Evidence Review</title>
  <style>
    :root {{ color-scheme: light dark; --ink:#10183f; --muted:#53617d; --line:#dbe3f3; --panel:#fff; --wash:#f4f9fb; --teal:#18b8a6; }}
    body {{ margin:0; background:linear-gradient(180deg,#f8fbff 0%,#eef8f6 100%); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ display:grid; gap:18px; padding:28px; }}
    h1 {{ margin:0; font-size:30px; letter-spacing:0; }}
    h2 {{ margin:0 0 10px; font-size:16px; }}
    p {{ color:var(--muted); line-height:1.55; }}
    svg {{ width:100%; height:auto; display:block; }}
    .eyebrow {{ color:var(--teal); font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
    .panel {{ border:1px solid var(--line); border-radius:10px; background:rgba(255,255,255,.88); padding:16px; box-shadow:0 16px 42px rgba(34,48,88,.08); overflow:hidden; }}
    .hero {{ display:grid; grid-template-columns:minmax(0,1fr) 220px; gap:18px; align-items:start; }}
    .brief {{ border-left:5px solid var(--teal); background:var(--wash); border-radius:10px; padding:14px; }}
    .story-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
    .story-card {{ border:1px solid var(--line); border-radius:10px; background:var(--wash); padding:12px; }}
    .result-callout {{ border:1px solid var(--line); border-left:5px solid var(--teal); border-radius:10px; background:#fff; padding:14px; }}
    .result-callout strong {{ display:block; margin-bottom:8px; font-size:18px; }}
    .story-card strong,.playbook-row strong {{ display:block; margin-bottom:6px; }}
    .playbook-row {{ border-left:4px solid var(--teal); margin:8px 0; padding:10px 12px; background:var(--wash); border-radius:8px; }}
    .prompt {{ display:inline-block; margin:4px; border:1px solid var(--line); border-radius:999px; background:var(--wash); padding:7px 10px; color:var(--ink); font-size:12px; font-weight:700; }}
    .metric strong {{ display:block; font-size:22px; overflow-wrap:anywhere; }}
    .metric span,.tiny {{ color:var(--muted); font-size:12px; }}
    .finding {{ border-left:4px solid var(--teal); padding:10px 12px; background:var(--wash); border-radius:8px; margin:8px 0; }}
    @media (max-width: 720px) {{ .hero {{ grid-template-columns:1fr; }} }}
    @media (prefers-color-scheme: dark) {{ :root {{ --ink:#eef4ff; --muted:#aab6d3; --line:#2e3a5b; --wash:#17213a; }} body {{ background:#0c1225; }} .panel {{ background:rgba(17,24,47,.9); box-shadow:none; }} }}
  </style>
</head>
<body>
  <main>
    <header class="hero">
      <div>
        <div class="eyebrow">Notebook Evidence Review · {escape(kind_label)}</div>
        <h1>{escape(str(summary.get("title") or "EDA evidence bundle"))}</h1>
        <p>{escape(str(brief.get("headline") or summary.get("overview") or ""))}</p>
      </div>
      <div class="brief">
        <strong>{escape(str(brief.get("decision_state") or "review"))}</strong>
        <p>{escape(str(brief.get("profile_boundary") or "Profile boundary is recorded in the source artifacts."))}</p>
      </div>
    </header>
    <section class="grid">
      {_metric_card("Figures", summary.get("figure_count", 0))}
      {_metric_card("Guardrails", summary.get("guardrail_count", 0))}
      {_metric_card("Questions", summary.get("analysis_question_count", 0))}
      {_metric_card("Runtime", bundle["runtime_execution_status"])}
    </section>
    {_result_interpretation_html(interpretation)}
    <section class="panel">
      <h2>Read this first</h2>
      <p>{escape(str(brief.get("why_it_matters") or ""))}</p>
      {_read_order_rows(read_order)}
    </section>
    <section class="panel">
      <h2>Visual story cards</h2>
      <div class="story-grid">{_story_card_rows(story_cards)}</div>
    </section>
    <section class="panel">
      <h2>{escape(playbook_title)}</h2>
      {_playbook_rows(playbook)}
    </section>
    {figures_html}
    <section class="panel">
      <h2>Evaluation guardrails</h2>
      {_guardrail_rows(guardrails)}
    </section>
    <section class="panel">
      <h2>Analysis questions</h2>
      {"".join(f'<div class="finding">{escape(str(item))}</div>' for item in questions) or "<p>No questions generated.</p>"}
    </section>
    <section class="panel">
      <h2>Ask Codex next</h2>
      {"".join(f'<span class="prompt">{escape(str(item))}</span>' for item in prompts) or "<p>No prompts generated.</p>"}
    </section>
  </main>
</body>
</html>"""


def create_model_diagnostics_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> ModelDiagnosticsNotebookResult:
    raise ValueError(
        "Harness-authored Model Diagnostics notebooks are disabled. "
        "Create a notebook_authoring_brief and let Codex/AgentRunner author the notebook artifact."
    )



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
        "imports_marimo": "import marimo" in source,
        "defines_marimo_app": "marimo.App" in source,
        "has_main_run_guard": 'if __name__ == "__main__"' in source,
        "mentions_artifact_policy": "EvaluationSpec" in source and "SplitManifest" in source,
    }
    is_marimo_notebook = all(checks[key] for key in ("imports_marimo", "defines_marimo_app"))
    return {
        "schema_version": "notebook_source_validation.v1",
        "is_valid_marimo_notebook": is_marimo_notebook,
        "is_tablex_generated": is_marimo_notebook,
        "is_capture_eligible": is_marimo_notebook,
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


def run_marimo_html_export(
    notebook_artifact: Artifact,
    source: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    started = time.monotonic()
    if not marimo_available():
        return {
            "schema_version": "marimo_html_export.v1",
            "status": "skipped",
            "reason": "marimo_not_installed",
            "returncode": None,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout_excerpt": "",
            "stderr_excerpt": "marimo is not installed in the backend environment.",
            "html": None,
        }
    with tempfile.TemporaryDirectory(prefix="tablex_marimo_export_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        notebook_path = source_notebook_path_for_export(notebook_artifact)
        cwd = notebook_path.parent if notebook_path is not None else tmp_path
        export_path = tmp_path / "notebook.html"
        if notebook_path is None:
            notebook_path = tmp_path / "notebook.py"
            notebook_path.write_text(source, encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html",
            str(notebook_path),
            "--no-include-code",
            "--force",
            "-o",
            str(export_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                env=notebook_export_env(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "schema_version": "marimo_html_export.v1",
                "status": "timed_out",
                "reason": "marimo_export_timeout",
                "returncode": None,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timeout_seconds": timeout_seconds,
                "command": command_for_manifest(command),
                "cwd": str(cwd),
                "stdout_excerpt": _excerpt(exc.stdout),
                "stderr_excerpt": _excerpt(exc.stderr),
                "html": None,
            }
        html = export_path.read_text(encoding="utf-8") if completed.returncode == 0 and export_path.exists() else None
        return {
            "schema_version": "marimo_html_export.v1",
            "status": "succeeded" if completed.returncode == 0 and html else "failed",
            "reason": None if completed.returncode == 0 and html else "marimo_export_failed",
            "returncode": completed.returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "timeout_seconds": timeout_seconds,
            "command": command_for_manifest(command),
            "cwd": str(cwd),
            "stdout_excerpt": _excerpt(completed.stdout),
            "stderr_excerpt": _excerpt(completed.stderr),
            "html": html,
        }


def notebook_execution_status(
    compile_result: dict[str, Any],
    marimo_export_result: dict[str, Any],
) -> str:
    if compile_result["status"] != "succeeded":
        return "static_capture_failed"
    marimo_status = str(marimo_export_result.get("status") or "unknown")
    if marimo_status == "succeeded":
        return "marimo_export_succeeded"
    if marimo_status == "skipped":
        return "static_capture_succeeded"
    return "marimo_export_failed"


def marimo_available() -> bool:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "marimo", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def source_notebook_path_for_export(notebook_artifact: Artifact) -> Path | None:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    primary = artifact_primary_path(notebook_artifact)
    workspace_relative_path = metadata.get("workspace_relative_path")
    agent_session_id = metadata.get("agent_session_id")
    if (
        notebook_artifact.project_id
        and isinstance(agent_session_id, str)
        and isinstance(workspace_relative_path, str)
    ):
        store_root = artifact_store_root_from_primary_path(notebook_artifact, primary)
        if store_root is not None:
            session_root = (store_root / "agent_sessions" / notebook_artifact.project_id / agent_session_id).resolve()
            candidate = (session_root / workspace_relative_path).resolve()
            try:
                candidate.relative_to(session_root)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.exists():
                return candidate
    return primary.resolve() if primary.exists() else None


def artifact_store_root_from_primary_path(artifact: Artifact, primary_path: Path) -> Path | None:
    parts = primary_path.resolve().parts
    project_part = artifact.project_id or "_cross_project"
    marker = (artifact.org_id, project_part, artifact.asset_type)
    for index in range(0, max(len(parts) - len(marker) + 1, 0)):
        if tuple(parts[index : index + len(marker)]) == marker:
            return Path(*parts[:index])
    return None


def notebook_export_env(workspace: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TERM", "PYTHONPATH"}
    }
    isolated_home = workspace / ".tablex_marimo_home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(isolated_home)
    env["MPLBACKEND"] = "Agg"
    env["TABLEX_NOTEBOOK_RENDER"] = "1"
    return env


def command_for_manifest(command: list[str]) -> list[str]:
    return [Path(part).name if index == 0 else part for index, part in enumerate(command)]


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
        "model_diagnostics_artifact_pack": _latest_artifact_for_metadata(
            db, run.project_id, "model_diagnostics_artifact_pack", "run_id", run.id
        ),
        "feature_importance": _latest_artifact_for_metadata(
            db, run.project_id, "feature_importance", "run_id", run.id
        ),
        "permutation_importance": _latest_artifact_for_metadata(
            db, run.project_id, "permutation_importance", "run_id", run.id
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


def _build_notebook_artifact_lookup(artifacts: list[Artifact]) -> NotebookArtifactLookup:
    by_asset_type: dict[str, list[Artifact]] = {}
    by_session_id: dict[str, list[Artifact]] = {}
    metadata_by_artifact_id: dict[str, dict[str, Any]] = {}
    workspace_path_by_artifact_id: dict[str, str] = {}
    text_by_artifact_id: dict[str, str] = {}
    generic_candidates_by_session_id: dict[str, list[Artifact]] = {}
    kind_candidates_by_session_id: dict[tuple[str, str], list[Artifact]] = {}
    stem_candidates_by_session_id: dict[tuple[str, str], list[Artifact]] = {}
    data_markers = ("eda", "data_understanding", "exploration", "visual_story", "session_summary")
    model_markers = ("model", "diagnostic", "leaderboard", "experiment", "result")
    generic_markers = (
        "notebook_figure_manifest",
        "notebook_evidence_bundle",
        "notebook_evidence",
        "visual_story_cards",
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        metadata_by_artifact_id[artifact.id] = metadata
        raw_workspace_path = str(metadata.get("workspace_relative_path") or artifact.name)
        workspace_path = raw_workspace_path.lower().replace("-", "_")
        name = artifact.name.lower().replace("-", "_")
        workspace_path_by_artifact_id[artifact.id] = workspace_path
        artifact_text = f"{workspace_path} {name}"
        text_by_artifact_id[artifact.id] = artifact_text
        by_asset_type.setdefault(artifact.asset_type, []).append(artifact)
        session_id = metadata.get("agent_session_id")
        if isinstance(session_id, str) and session_id.strip():
            by_session_id.setdefault(session_id, []).append(artifact)
            if artifact.asset_type == "agent_session_figure" or any(marker in artifact_text for marker in generic_markers):
                generic_candidates_by_session_id.setdefault(session_id, []).append(artifact)
            if any(marker in artifact_text for marker in data_markers):
                kind_candidates_by_session_id.setdefault((session_id, "data_understanding"), []).append(artifact)
            if any(marker in artifact_text for marker in model_markers):
                kind_candidates_by_session_id.setdefault((session_id, "model_diagnostics"), []).append(artifact)
            for stem in {
                Path(raw_workspace_path).stem.lower().replace("-", "_"),
                Path(artifact.name).stem.lower().replace("-", "_"),
            }:
                if stem:
                    stem_candidates_by_session_id.setdefault((session_id, stem), []).append(artifact)
    return NotebookArtifactLookup(
        by_asset_type=by_asset_type,
        by_session_id=by_session_id,
        metadata_by_artifact_id=metadata_by_artifact_id,
        workspace_path_by_artifact_id=workspace_path_by_artifact_id,
        text_by_artifact_id=text_by_artifact_id,
        generic_candidates_by_session_id=generic_candidates_by_session_id,
        kind_candidates_by_session_id=kind_candidates_by_session_id,
        stem_candidates_by_session_id=stem_candidates_by_session_id,
    )


def _notebook_index_item(
    db: Session,
    project: Project,
    notebook_artifact: Artifact,
    *,
    reports_by_artifact_id: dict[str, Report],
    visualizations_by_artifact_id: dict[str, VisualizationSpec],
    artifact_lookup: NotebookArtifactLookup | None = None,
) -> dict[str, Any]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    notebook_kind = str(metadata.get("notebook_kind") or _infer_notebook_kind_from_artifact(notebook_artifact, metadata))
    html_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_html", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    manifest_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_run_manifest", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    report_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_report", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    visualization_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "visualization_spec", "source_artifact_id", notebook_artifact.id, artifact_lookup
    )
    execution_plan_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_execution_plan", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    agent_task_contract_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "agent_task_contract", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    execution_manifest_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_execution_manifest", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    execution_report_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_execution_report", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    execution_html_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_execution_html", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    figure_manifest_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_figure_manifest", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    execution_source_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_execution_source", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    evidence_bundle_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_evidence_bundle", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    evidence_html_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_evidence_html", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    evidence_figure_artifacts = _artifacts_for_metadata_cached(
        db, project.id, "notebook_evidence_svg", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    session_linked = _agent_session_notebook_artifacts(db, project.id, notebook_artifact, notebook_kind, artifact_lookup)
    html_artifact = html_artifact or session_linked["html_preview"]
    report_artifact = report_artifact or session_linked["report_artifact"]
    manifest_artifact = manifest_artifact or session_linked["manifest"]
    figure_manifest_artifact = figure_manifest_artifact or session_linked["figure_manifest"]
    evidence_bundle_artifact = evidence_bundle_artifact or session_linked["evidence_bundle"]
    evidence_html_artifact = evidence_html_artifact or session_linked["evidence_html"]
    evidence_figure_artifacts = _unique_artifacts([*evidence_figure_artifacts, *session_linked["evidence_figures"]])
    report = reports_by_artifact_id.get(report_artifact.id) if report_artifact else None
    visualization = visualizations_by_artifact_id.get(visualization_artifact.id) if visualization_artifact else None
    execution_metadata = loads_json(execution_manifest_artifact.metadata_json, {}) if execution_manifest_artifact else {}
    context_summary = _notebook_artifact_context_summary(notebook_artifact)
    content = _notebook_content_signal(notebook_kind, context_summary)
    if content["readiness"] in {"source_only", "unknown"}:
        content = _agent_session_notebook_content_signal(
            notebook_kind=notebook_kind,
            current=content,
            html_artifact=html_artifact,
            report_artifact=report_artifact,
            figure_manifest_artifact=figure_manifest_artifact,
            evidence_bundle_artifact=evidence_bundle_artifact,
            evidence_figure_artifacts=evidence_figure_artifacts,
            visual_story_artifact=session_linked["visual_story_cards"],
        )
    coverage = {
        "has_html_preview": html_artifact is not None,
        "has_manifest": manifest_artifact is not None,
        "has_report": report_artifact is not None,
        "has_visualization": visualization_artifact is not None and visualization is not None,
        "has_execution_plan": execution_plan_artifact is not None,
        "has_execution_capture": execution_manifest_artifact is not None,
        "has_execution_report": execution_report_artifact is not None,
        "has_execution_html": execution_html_artifact is not None,
        "has_evidence_html": evidence_html_artifact is not None,
        "has_evidence_bundle": evidence_bundle_artifact is not None,
        "evidence_figure_count": len(evidence_figure_artifacts),
        "has_figure_manifest": figure_manifest_artifact is not None,
        "execution_status": str(metadata.get("execution_status") or "unknown"),
        "execution_capture_status": str(execution_metadata.get("execution_status") or "not_captured"),
        "content_readiness": content["readiness"],
        "content_quality_score": content["quality_score"],
    }
    recommendation_score = _notebook_recommendation_score(notebook_kind, coverage, metadata, content)
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
            "evidence_bundle": evidence_bundle_artifact.id if evidence_bundle_artifact else None,
            "evidence_html": evidence_html_artifact.id if evidence_html_artifact else None,
            "evidence_figures": [artifact.id for artifact in evidence_figure_artifacts],
        },
        "report_id": report.id if report else None,
        "visualization_id": visualization.id if visualization else None,
        "coverage": coverage,
        "content": content,
        "recommendation_score": recommendation_score,
        "recommendation_reason": _notebook_recommendation_reason(notebook_kind, coverage, content),
    }


def _linked_notebook_artifacts(
    db: Session,
    project_id: str,
    notebook_artifact: Artifact,
) -> dict[str, Artifact | None]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    notebook_kind = str(metadata.get("notebook_kind") or _infer_notebook_kind_from_artifact(notebook_artifact, metadata))
    session_linked = _agent_session_notebook_artifacts(db, project_id, notebook_artifact, notebook_kind)
    return {
        "notebook": notebook_artifact,
        "html_preview": _latest_artifact_for_metadata(
            db, project_id, "notebook_html", "notebook_artifact_id", notebook_artifact.id
        )
        or session_linked["html_preview"],
        "manifest": _latest_artifact_for_metadata(
            db, project_id, "notebook_run_manifest", "notebook_artifact_id", notebook_artifact.id
        )
        or session_linked["manifest"],
        "report": _latest_artifact_for_metadata(
            db, project_id, "notebook_report", "notebook_artifact_id", notebook_artifact.id
        )
        or session_linked["report_artifact"],
        "visualization": _latest_artifact_for_metadata(
            db, project_id, "visualization_spec", "source_artifact_id", notebook_artifact.id
        ),
    }


def _infer_notebook_kind_from_artifact(notebook_artifact: Artifact, metadata: dict[str, Any]) -> str:
    value = f"{notebook_artifact.name} {metadata.get('workspace_relative_path') or ''}".lower().replace("-", "_")
    if any(marker in value for marker in ("data_understanding", "grandmaster_eda", "_eda", "eda_", "exploration", "visual_story")):
        return "data_understanding"
    if any(marker in value for marker in ("model_diagnostics", "diagnostic", "leaderboard", "model", "experiment", "result")):
        return "model_diagnostics"
    return "unknown"


def _agent_session_notebook_artifacts(
    db: Session,
    project_id: str,
    notebook_artifact: Artifact,
    notebook_kind: str,
    artifact_lookup: NotebookArtifactLookup | None = None,
) -> dict[str, Any]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    session_id = metadata.get("agent_session_id")
    if not session_id:
        return _empty_agent_session_notebook_artifacts()
    notebook_path = str(metadata.get("workspace_relative_path") or notebook_artifact.name)
    notebook_stem = Path(notebook_path).stem.lower().replace("-", "_")
    if artifact_lookup is not None and isinstance(session_id, str):
        artifacts = _candidate_agent_session_artifacts(
            session_id=session_id,
            notebook_stem=notebook_stem,
            notebook_kind=notebook_kind,
            artifact_lookup=artifact_lookup,
            excluded_artifact_id=notebook_artifact.id,
        )
    else:
        artifacts = [
            artifact
            for artifact in db.scalars(
                select(Artifact)
                .where(Artifact.project_id == project_id, Artifact.id != notebook_artifact.id)
                .order_by(Artifact.created_at.desc())
            ).all()
            if loads_json(artifact.metadata_json, {}).get("agent_session_id") == session_id
        ]
    return {
        "html_preview": _best_agent_session_artifact(
            artifacts, role="html_preview", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "manifest": _best_agent_session_artifact(
            artifacts, role="manifest", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "report_artifact": _best_agent_session_artifact(
            artifacts, role="report", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "figure_manifest": _best_agent_session_artifact(
            artifacts, role="figure_manifest", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "evidence_bundle": _best_agent_session_artifact(
            artifacts, role="evidence_bundle", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "evidence_html": _best_agent_session_artifact(
            artifacts, role="evidence_html", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "visual_story_cards": _best_agent_session_artifact(
            artifacts, role="visual_story_cards", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "evidence_figures": _agent_session_figure_artifacts(artifacts),
    }


def _empty_agent_session_notebook_artifacts() -> dict[str, Any]:
    return {
        "html_preview": None,
        "manifest": None,
        "report_artifact": None,
        "figure_manifest": None,
        "evidence_bundle": None,
        "evidence_html": None,
        "visual_story_cards": None,
        "evidence_figures": [],
    }


def _candidate_agent_session_artifacts(
    *,
    session_id: str,
    notebook_stem: str,
    notebook_kind: str,
    artifact_lookup: NotebookArtifactLookup,
    excluded_artifact_id: str,
) -> list[Artifact]:
    return [
        artifact
        for artifact in _unique_artifacts(
            [
                *artifact_lookup.generic_candidates_by_session_id.get(session_id, []),
                *artifact_lookup.kind_candidates_by_session_id.get((session_id, notebook_kind), []),
                *artifact_lookup.stem_candidates_by_session_id.get((session_id, notebook_stem), []),
            ]
        )
        if artifact.id != excluded_artifact_id
    ]


def _best_agent_session_artifact(
    artifacts: list[Artifact],
    *,
    role: str,
    notebook_stem: str,
    notebook_kind: str,
    artifact_lookup: NotebookArtifactLookup | None = None,
) -> Artifact | None:
    scored = [
        (score, artifact)
        for artifact in artifacts
        if (
            score := _agent_session_artifact_link_score(
                artifact,
                role=role,
                notebook_stem=notebook_stem,
                notebook_kind=notebook_kind,
                metadata=artifact_lookup.metadata_by_artifact_id.get(artifact.id, {}) if artifact_lookup else None,
                workspace_path=artifact_lookup.workspace_path_by_artifact_id.get(artifact.id) if artifact_lookup else None,
                artifact_text=artifact_lookup.text_by_artifact_id.get(artifact.id) if artifact_lookup else None,
            )
        )
        > 0
    ]
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], item[1].created_at))[1]


def _agent_session_artifact_link_score(
    artifact: Artifact,
    *,
    role: str,
    notebook_stem: str,
    notebook_kind: str,
    metadata: dict[str, Any] | None = None,
    workspace_path: str | None = None,
    artifact_text: str | None = None,
) -> int:
    if workspace_path is None or artifact_text is None:
        resolved_metadata = metadata or loads_json(artifact.metadata_json, {})
        workspace_path = str(resolved_metadata.get("workspace_relative_path") or artifact.name).lower().replace("-", "_")
        name = artifact.name.lower().replace("-", "_")
        value = f"{workspace_path} {name}"
    else:
        value = artifact_text
    if role == "html_preview":
        if not workspace_path.endswith(".html"):
            return 0
        return _session_notebook_score(value, notebook_stem, notebook_kind) + (20 if "static" in value or "preview" in value else 0)
    if role == "manifest":
        if "generated_artifact_manifest" in value or value.endswith("manifest.json"):
            return _session_notebook_score(value, notebook_stem, notebook_kind)
        return 0
    if role == "report":
        if not workspace_path.endswith(".md") or "chat_update" in value or "export_error" in value:
            return 0
        score = _session_notebook_score(value, notebook_stem, notebook_kind)
        if notebook_kind == "data_understanding" and ("eda_story" in value or "session_summary" in value):
            score += 30
        if notebook_kind == "model_diagnostics" and "model_report" in value:
            score += 30
        return score
    if role == "figure_manifest":
        return 100 if "notebook_figure_manifest" in value else 0
    if role == "evidence_bundle":
        return 100 if "notebook_evidence_bundle" in value else 0
    if role == "evidence_html":
        return 100 if "notebook_evidence" in value and workspace_path.endswith(".html") else 0
    if role == "visual_story_cards":
        return 100 if "visual_story_cards" in value else 0
    return 0


def _session_notebook_score(value: str, notebook_stem: str, notebook_kind: str) -> int:
    score = 10
    if notebook_stem and notebook_stem in value:
        score += 50
    if notebook_kind == "data_understanding" and any(marker in value for marker in ("eda", "data_understanding", "exploration", "visual_story")):
        score += 25
    if notebook_kind == "model_diagnostics" and any(marker in value for marker in ("model", "diagnostic", "leaderboard", "experiment")):
        score += 25
    return score


def _agent_session_figure_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
    return [
        artifact
        for artifact in artifacts
        if artifact.asset_type == "agent_session_figure"
        or str(loads_json(artifact.metadata_json, {}).get("workspace_relative_path") or "").lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
    ]


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
    rendered_figures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected_figures = {
        "data_understanding": [
            "feature_family_counts",
            "top_missing_columns_bar",
            "semantic_type_role_mix",
            "target_profile_summary",
            "risk_attention_counts",
            "feature_review_queue_counts",
        ],
        "model_diagnostics": [
            "diagnostics_readiness",
            "feature_family_inventory",
            "prediction_score_bins",
            "diagnostics_attention_counts",
        ],
    }.get(notebook_kind, ["notebook_generated_figures"])
    rendered = rendered_figures or []
    rendered_slots = {str(item.get("slot") or item.get("figure_id") or "") for item in rendered}
    return {
        "schema_version": "notebook_figure_manifest.v1",
        "project_id": project.id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": generated_at,
        "capture_mode": "safe_static_capture",
        "status": "profile_evidence_rendered" if rendered else "planned_figures_only",
        "runtime_execution_status": "deferred",
        "profile_evidence_render_status": "rendered" if rendered else "not_rendered",
        "compile_status": compile_result["status"],
        "figures": rendered,
        "expected_figure_slots": [
            {
                "slot": slot,
                "status": "rendered_from_profile_artifacts" if slot in rendered_slots else "not_rendered",
                "reason": (
                    "Rendered by the harness from notebook/profile artifacts without executing marimo cells."
                    if slot in rendered_slots
                    else "Static capture validates notebook source but does not execute marimo cells."
                ),
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
    marimo_export_result: dict[str, Any],
    execution_status: str,
    generated_at: str,
    plan_created: bool,
    output_artifacts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "notebook_execution_manifest.v1",
        "project_id": project.id,
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "generated_at": generated_at,
        "capture_mode": "marimo_html_export"
        if marimo_export_result.get("status") == "succeeded"
        else "safe_static_capture",
        "execution_status": execution_status,
        "summary": {
            "headline": _notebook_execution_headline(execution_status, compile_result),
            "runtime_execution_status": marimo_export_result.get("status", "unknown"),
            "python_compile_status": compile_result["status"],
            "marimo_export_status": marimo_export_result.get("status"),
            "plan_created_by_capture": plan_created,
            "profile_evidence_render_status": "rendered"
            if output_artifacts.get("notebook_evidence_bundle_artifact_id")
            else "not_available",
            "profile_evidence_figure_count": len(output_artifacts.get("notebook_evidence_figure_artifact_ids", []))
            if isinstance(output_artifacts.get("notebook_evidence_figure_artifact_ids"), list)
            else 0,
        },
        "safety_policy": {
            "arbitrary_notebook_code_executed": marimo_export_result.get("status") != "skipped",
            "python_compile_only": marimo_export_result.get("status") == "skipped",
            "marimo_html_export_attempted": marimo_export_result.get("status") != "skipped",
            "harness_profile_evidence_rendered": bool(output_artifacts.get("notebook_evidence_bundle_artifact_id")),
            "marimo_cells_executed": marimo_export_result.get("status") == "succeeded",
            "python_isolated_mode": marimo_export_result.get("status") == "skipped",
            "external_network_accessed": "not_observed",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "local_files_outside_workspace_materialized": False,
            "human_review_required_before_full_execution": True,
        },
        "source_validation": source_validation,
        "static_compile": compile_result,
        "marimo_export": {
            key: value for key, value in marimo_export_result.items() if key != "html"
        },
        "linked_artifacts": _linked_artifact_refs(linked_artifacts),
        "outputs": {
            **output_artifacts,
            "notebook_execution_html_artifact_id": None,
            "notebook_execution_report_id": None,
            "notebook_execution_report_artifact_id": None,
        },
        "next_runner_steps": [
            "Open the rendered marimo HTML in the Tablex notebook viewer."
            if marimo_export_result.get("status") == "succeeded"
            else "Fix marimo export blockers, then capture executed HTML as an artifact.",
            "Capture generated figures and tables with source-cell lineage.",
            "Preserve EvaluationSpec and SplitManifest when adding diagnostics.",
        ],
    }


def _notebook_execution_headline(execution_status: str, compile_result: dict[str, Any]) -> str:
    if execution_status == "marimo_export_succeeded":
        return "Notebook was executed by marimo and exported as an in-product HTML report."
    if execution_status == "static_capture_succeeded":
        return "Notebook source passed isolated Python syntax validation; marimo runtime execution is deferred."
    if execution_status == "marimo_export_failed":
        return "Notebook source compiled, but marimo HTML export failed; inspect the export stderr."
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
      {_metric_card("Evidence figures", summary.get("profile_evidence_figure_count", 0))}
    </section>
    <section class="panel">
      <h2>Profile evidence capture</h2>
      <p>Notebook cells were not executed. Tablex rendered profile-backed EDA figures and tables from controlled notebook context and linked artifacts when available.</p>
      <div class="badge-row">
        <span class="badge">{escape(str(summary.get("profile_evidence_render_status", "not_available")))}</span>
        <span class="badge">marimo cells: not executed</span>
      </div>
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
            f"- Capture mode: `{manifest['capture_mode']}`",
            f"- Notebook artifact: `{manifest['notebook_artifact_id']}`",
            f"- Notebook kind: `{manifest['notebook_kind']}`",
            f"- marimo HTML export: `{manifest['summary'].get('marimo_export_status')}`",
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
            "## Profile Evidence Capture",
            "",
            f"- Render status: `{manifest['summary'].get('profile_evidence_render_status', 'not_available')}`",
            f"- Figure count: `{manifest['summary'].get('profile_evidence_figure_count', 0)}`",
            f"- Notebook cells executed: `{manifest['safety_policy'].get('marimo_cells_executed')}`",
            "",
            "## Captured Artifacts",
            "",
            f"- HTML preview: `{html_artifact_id}`",
            f"- Figure manifest: `{figure_manifest_artifact_id}`",
            f"- Notebook source copy: `{source_artifact_id}`",
            f"- Evidence bundle: `{manifest['outputs'].get('notebook_evidence_bundle_artifact_id') or 'not available'}`",
            f"- Evidence HTML: `{manifest['outputs'].get('notebook_evidence_html_artifact_id') or 'not available'}`",
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
    content: dict[str, Any],
) -> int:
    score = 20
    if notebook_kind == "model_diagnostics":
        score += 10
    if notebook_kind == "data_understanding":
        score += 35
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
    readiness = str(content.get("readiness") or "unknown")
    quality_score = int(content.get("quality_score") or 0)
    if notebook_kind == "model_diagnostics":
        if readiness == "evidence_ready":
            score += 90
        elif readiness == "partial_review":
            score += 14
        elif readiness == "not_ready":
            score -= 55
    elif notebook_kind == "data_understanding":
        score += min(50, quality_score)
    else:
        score += min(20, quality_score)
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


def _story_item_is_empty_diagnostics(item: dict[str, Any]) -> bool:
    if str(item.get("notebook_kind") or "") != "model_diagnostics":
        return False
    content = _dict_value(item.get("content"))
    coverage = _dict_value(item.get("coverage"))
    return str(content.get("readiness") or coverage.get("content_readiness") or "") == "not_ready"


def _story_headline(primary: object, secondary: object, *, fallback: str) -> str:
    for value in (primary, secondary, fallback):
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _analysis_story_read_order(value: object) -> list[dict[str, str]]:
    rows = []
    for item in _list_value(value)[:5]:
        row = _dict_value(item)
        title = str(row.get("title") or row.get("stage") or row.get("section") or "").strip()
        why = str(row.get("why") or row.get("reader_question") or row.get("detail") or "").strip()
        artifact_hint = str(row.get("artifact_hint") or row.get("current_evidence") or row.get("artifact_expectation") or "").strip()
        if not title and not why:
            continue
        rows.append({"title": title or "Review item", "why": why, "artifact_hint": artifact_hint})
    return rows


def _analysis_story_cards(value: object) -> list[dict[str, str]]:
    cards = []
    for item in _list_value(value)[:6]:
        row = _dict_value(item)
        title = str(row.get("title") or row.get("area") or "").strip()
        if not title:
            continue
        cards.append(
            {
                "title": title,
                "signal": str(row.get("signal") or row.get("evidence") or "").strip(),
                "why_read": str(row.get("why_read") or row.get("message") or row.get("detail") or "").strip(),
                "status": str(row.get("status") or row.get("severity") or "review").strip(),
            }
        )
    return cards


def _analysis_story_playbook(value: object) -> list[dict[str, str]]:
    rows = []
    for item in _list_value(value)[:5]:
        row = _dict_value(item)
        stage = str(row.get("stage") or row.get("title") or "").strip()
        question = str(row.get("reader_question") or row.get("question") or "").strip()
        evidence = str(row.get("current_evidence") or row.get("evidence") or "").strip()
        codex = str(row.get("codex_followup") or row.get("next_action") or "").strip()
        if stage or question or evidence or codex:
            rows.append({"stage": stage or "Review", "reader_question": question, "current_evidence": evidence, "codex_followup": codex})
    return rows


def _notebook_story_caveats(
    *,
    brief: dict[str, Any],
    selected_item: dict[str, Any],
    diverted_from_empty_diagnostics: bool,
) -> list[str]:
    caveats: list[str] = []
    if diverted_from_empty_diagnostics:
        caveats.append("A model diagnostics notebook exists, but metric or prediction evidence is missing, so it is not promoted.")
    profile_boundary = str(brief.get("profile_boundary") or "").strip()
    if profile_boundary:
        caveats.append(profile_boundary)
    caveats.extend(_string_list(brief.get("top_risks"))[:3])
    coverage = _dict_value(selected_item.get("coverage"))
    if coverage.get("has_execution_capture"):
        caveats.append("Notebook cells were not executed; Tablex rendered harness-owned static evidence for safe in-product review.")
    else:
        caveats.append("Notebook cells were not executed; read this as harness-generated review context until captured evidence exists.")
    if not coverage.get("has_html_preview"):
        caveats.append("No in-product preview artifact is linked yet; use controlled generation or capture before treating it as a report.")
    return _dedupe_strings(caveats)[:5]


def _eda_review_caveats(review: dict[str, Any]) -> list[str]:
    runner_notes = _dict_value(review.get("runner_notes"))
    caveats = [
        "EDA Review is harness-controlled DuckDB analysis, not arbitrary notebook execution.",
        "Use figures to choose the next question; do not treat them as final causal explanations.",
    ]
    if runner_notes.get("external_network_accessed") is False:
        caveats.append("No external network or connector credentials were used for this review.")
    findings = [_dict_value(item) for item in _list_value(review.get("findings"))]
    caveats.extend(str(item.get("message") or "") for item in findings if str(item.get("severity") or "") == "high")
    return _dedupe_strings(caveats)[:5]


def _notebook_evidence_cards(item: dict[str, Any], figure_artifacts: list[Artifact]) -> list[dict[str, str]]:
    coverage = _dict_value(item.get("coverage"))
    content = _dict_value(item.get("content"))
    return [
        {
            "title": "Reader value",
            "status": str(content.get("readiness") or coverage.get("content_readiness") or "unknown"),
            "signal": f"quality {content.get('quality_score', 0)}",
            "why_read": str(item.get("recommendation_reason") or ""),
        },
        {
            "title": "Evidence capture",
            "status": "ready" if coverage.get("has_execution_capture") else "missing",
            "signal": f"{len(figure_artifacts)} figure(s)",
            "why_read": "Captured figures and HTML keep the notebook readable inside Tablex.",
        },
        {
            "title": "Runner boundary",
            "status": "planned" if coverage.get("has_execution_plan") else "not_planned",
            "signal": "controlled execution required",
            "why_read": "Codex may extend the analysis, but the harness owns artifacts, lineage, safety, and evaluation boundaries.",
        },
    ]


def _eda_review_evidence_cards(review: dict[str, Any]) -> list[dict[str, str]]:
    summary = _dict_value(review.get("summary"))
    findings = _list_value(review.get("findings"))
    return [
        {
            "title": "Review quality",
            "status": str(summary.get("severity") or "review"),
            "signal": f"score {summary.get('quality_score', '-')}",
            "why_read": "Quality reflects target status, figures, findings, and target relationships.",
        },
        {
            "title": "Figures",
            "status": "ready" if int(summary.get("figure_count") or 0) else "missing",
            "signal": f"{summary.get('figure_count', 0)} rendered",
            "why_read": "Figures are selected for analysis decisions, not decoration.",
        },
        {
            "title": "Findings",
            "status": "review" if findings else "missing",
            "signal": f"{len(findings)} finding(s)",
            "why_read": "Each finding should become one narrow Codex or harness action.",
        },
    ]


def _notebook_story_primary_action(
    *,
    selected_item: dict[str, Any],
    preview_artifact_id: str | None,
    evidence_html: Artifact | None,
) -> dict[str, Any]:
    if preview_artifact_id and evidence_html is not None:
        return {
            "label": "Open evidence review",
            "action_type": "preview",
            "artifact_id": preview_artifact_id,
            "target_tab": "Notebooks",
        }
    if selected_item.get("coverage", {}).get("has_execution_capture") and preview_artifact_id:
        return {
            "label": "Open current review",
            "action_type": "preview",
            "artifact_id": preview_artifact_id,
            "target_tab": "Notebooks",
        }
    return {
        "label": "Capture readable evidence",
        "action_type": "api",
        "endpoint": f"/api/analysis-notebooks/{selected_item['notebook_artifact_id']}/execution-capture",
        "target_tab": "Notebooks",
    }


def _story_raw_artifact_refs(
    db: Session,
    project_id: str,
    notebook_artifact: Artifact,
    linked_artifact_ids: dict[str, Any],
    evidence_html: Artifact | None,
    evidence_figures: list[Artifact],
) -> list[dict[str, Any]]:
    artifacts: list[Artifact] = [notebook_artifact]
    for artifact_id in linked_artifact_ids.values():
        if not isinstance(artifact_id, str):
            continue
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None and artifact.project_id == project_id:
            artifacts.append(artifact)
    if evidence_html is not None:
        artifacts.append(evidence_html)
    artifacts.extend(evidence_figures[:6])
    return _artifact_refs(_unique_artifacts(artifacts))


def _artifact_refs(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": artifact.id,
            "asset_type": artifact.asset_type,
            "name": artifact.name,
            "created_at": artifact.created_at.isoformat(),
            "preview_url": f"/api/artifacts/{artifact.id}/preview",
            "download_url": f"/api/artifacts/{artifact.id}/download",
        }
        for artifact in artifacts
    ]


def _unique_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
    seen: set[str] = set()
    unique: list[Artifact] = []
    for artifact in artifacts:
        if artifact.id in seen:
            continue
        seen.add(artifact.id)
        unique.append(artifact)
    return unique


def _artifacts_for_metadata(
    db: Session,
    project_id: str,
    asset_type: str,
    key: str,
    value: object,
) -> list[Artifact]:
    if value is None:
        return []
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    return [artifact for artifact in artifacts if loads_json(artifact.metadata_json, {}).get(key) == value]


def _latest_report_id_for_artifact(db: Session, artifact: Artifact | None) -> str | None:
    if artifact is None:
        return None
    report = db.scalars(select(Report).where(Report.artifact_id == artifact.id).order_by(Report.created_at.desc())).first()
    return report.id if report is not None else None


def _string_list(value: object) -> list[str]:
    return [str(item).strip() for item in _list_value(value) if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _first_text_value(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _notebook_title(notebook_kind: str) -> str:
    if notebook_kind == "model_diagnostics":
        return "Model Diagnostics Notebook"
    if notebook_kind == "data_understanding":
        return "Data Understanding Notebook"
    return "Analysis Notebook"


def _notebook_recommendation_reason(notebook_kind: str, coverage: dict[str, Any], content: dict[str, Any]) -> str:
    readiness = str(content.get("readiness") or "unknown")
    if notebook_kind == "model_diagnostics" and readiness == "not_ready":
        return "Model diagnostics exists, but it is not useful yet because metric, prediction, or diagnostic evidence is missing."
    if notebook_kind == "model_diagnostics" and readiness == "partial_review":
        return "Use only as a diagnostics coverage check; fill missing prediction or diagnostic evidence before model claims."
    if notebook_kind == "model_diagnostics" and readiness == "evidence_ready":
        return "Evidence-rich model review: metrics, prediction coverage, and diagnostics are available enough for a first read."
    if notebook_kind == "data_understanding" and readiness in {"evidence_ready", "narrative_ready"}:
        return "Best starting point: Data Understanding has narrative, story cards, playbook, and evidence figures."
    if coverage.get("has_execution_capture"):
        return "Most complete notebook evidence: preview, report, execution plan, and safe static capture are available."
    if notebook_kind == "data_understanding":
        return "Best starting point before target, evaluation, or feature decisions."
    if coverage.get("has_html_preview"):
        return "Preview is available inside the workbench."
    return "Notebook source exists, but preview/report coverage is incomplete."


def _notebook_artifact_context_summary(notebook_artifact: Artifact) -> dict[str, Any]:
    try:
        source = artifact_primary_path(notebook_artifact).read_text(encoding="utf-8")
    except OSError:
        return {}
    context = extract_notebook_context(source)
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    return cast(dict[str, Any], summary)


def _notebook_content_signal(notebook_kind: str, summary: dict[str, Any]) -> dict[str, Any]:
    if notebook_kind == "data_understanding":
        brief = _dict_value(summary.get("analysis_brief"))
        read_count = len(_list_value(brief.get("read_this_first")))
        story_count = len(_list_value(summary.get("visual_story_cards")))
        playbook_count = len(_list_value(summary.get("eda_playbook")))
        figure_queue_count = len(_list_value(summary.get("feature_family_summary")))
        quality_score = min(100, read_count * 12 + story_count * 8 + playbook_count * 8 + figure_queue_count * 2)
        readiness = "narrative_ready" if read_count and story_count and playbook_count else "source_only"
        return {
            "readiness": readiness,
            "quality_score": quality_score,
            "read_order_count": read_count,
            "story_card_count": story_count,
            "playbook_count": playbook_count,
            "primary_metric_available": False,
            "prediction_rows": 0,
        }
    if notebook_kind == "model_diagnostics":
        prediction_summary = _dict_value(summary.get("prediction_summary"))
        prediction_rows = int(prediction_summary.get("row_count") or 0)
        has_metric = summary.get("primary_metric_value") is not None
        has_predictions = prediction_rows > 0 and prediction_summary.get("status") == "available"
        readiness = str(summary.get("evidence_readiness") or "not_ready")
        quality_score = int(summary.get("evidence_quality_score") or 0)
        return {
            "readiness": readiness,
            "quality_score": quality_score,
            "read_order_count": len(_list_value(_dict_value(summary.get("analysis_brief")).get("read_this_first"))),
            "story_card_count": len(_list_value(summary.get("visual_story_cards"))),
            "playbook_count": len(_list_value(summary.get("eda_playbook"))),
            "primary_metric_available": has_metric,
            "prediction_rows": prediction_rows,
            "has_predictions": has_predictions,
        }
    return {
        "readiness": "unknown",
        "quality_score": 0,
        "read_order_count": 0,
        "story_card_count": 0,
        "playbook_count": 0,
        "primary_metric_available": False,
        "prediction_rows": 0,
    }


def _agent_session_notebook_content_signal(
    *,
    notebook_kind: str,
    current: dict[str, Any],
    html_artifact: Artifact | None,
    report_artifact: Artifact | None,
    figure_manifest_artifact: Artifact | None,
    evidence_bundle_artifact: Artifact | None,
    evidence_figure_artifacts: list[Artifact],
    visual_story_artifact: Artifact | None,
) -> dict[str, Any]:
    if notebook_kind not in {"data_understanding", "model_diagnostics"}:
        return current
    evidence_bundle = _read_json_artifact(evidence_bundle_artifact)
    visual_story = _read_json_artifact(visual_story_artifact)
    claims = _list_value(evidence_bundle.get("claims"))
    bundle_figures = _list_value(evidence_bundle.get("figures"))
    story_cards = _list_value(visual_story.get("cards"))
    figure_count = max(len(bundle_figures), len(evidence_figure_artifacts), 1 if figure_manifest_artifact is not None else 0)
    quality_score = min(
        100,
        int(current.get("quality_score") or 0)
        + (20 if html_artifact is not None else 0)
        + (15 if report_artifact is not None else 0)
        + min(24, len(claims) * 6)
        + min(24, figure_count * 4)
        + min(21, len(story_cards) * 7),
    )
    if quality_score >= 70:
        readiness = "narrative_ready" if notebook_kind == "data_understanding" else "evidence_ready"
    elif quality_score >= 35:
        readiness = "evidence_ready" if notebook_kind == "data_understanding" else "partial_review"
    else:
        readiness = str(current.get("readiness") or "source_only")
    return {
        **current,
        "readiness": readiness,
        "quality_score": quality_score,
        "read_order_count": max(int(current.get("read_order_count") or 0), len(claims)),
        "story_card_count": max(int(current.get("story_card_count") or 0), len(story_cards)),
        "playbook_count": max(int(current.get("playbook_count") or 0), len(claims)),
        "evidence_figure_count": figure_count,
    }


def _read_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return {}


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


def _latest_artifact_for_metadata_cached(
    db: Session,
    project_id: str,
    asset_type: str,
    key: str,
    value: object,
    artifact_lookup: NotebookArtifactLookup | None,
) -> Artifact | None:
    if artifact_lookup is None:
        return _latest_artifact_for_metadata(db, project_id, asset_type, key, value)
    if value is None:
        return None
    for artifact in artifact_lookup.by_asset_type.get(asset_type, []):
        if artifact_lookup.metadata_by_artifact_id.get(artifact.id, {}).get(key) == value:
            return artifact
    return None


def _artifacts_for_metadata_cached(
    db: Session,
    project_id: str,
    asset_type: str,
    key: str,
    value: object,
    artifact_lookup: NotebookArtifactLookup | None,
) -> list[Artifact]:
    if artifact_lookup is None:
        return _artifacts_for_metadata(db, project_id, asset_type, key, value)
    if value is None:
        return []
    return [
        artifact
        for artifact in artifact_lookup.by_asset_type.get(asset_type, [])
        if artifact_lookup.metadata_by_artifact_id.get(artifact.id, {}).get(key) == value
    ]


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
    model_diagnostics_artifacts: dict[str, Any],
    validation: dict[str, Any],
    prediction_summary: dict[str, Any],
    source_artifacts: dict[str, Artifact | None],
) -> dict[str, Any]:
    primary_metric_name = str(
        metrics.get("primary_metric_name")
        or (model_version.primary_metric_name if model_version else None)
        or ""
    )
    primary_metric_value = metrics.get("primary_metric_value")
    if primary_metric_value is None and model_version is not None:
        primary_metric_value = model_version.primary_metric_value
    feature_rows = _feature_family_rows(metrics)
    model_artifacts = _dict_value(model_diagnostics_artifacts)
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
    evidence_state = _model_diagnostics_evidence_state(
        primary_metric_value=primary_metric_value,
        prediction_summary=prediction_summary,
        diagnostics=diagnostics,
        feature_rows=feature_rows,
        findings=findings,
    )
    sanity_floor = _dict_value(metrics.get("sanity_floor"))
    metric_comparison = _model_metric_comparison(
        primary_metric_name=primary_metric_name,
        primary_metric_value=primary_metric_value,
        sanity_floor=sanity_floor,
    )
    brief = _model_diagnostics_analysis_brief(
        run=run,
        primary_metric_name=primary_metric_name,
        primary_metric_value=primary_metric_value,
        prediction_summary=prediction_summary,
        evidence_state=evidence_state,
        metric_comparison=metric_comparison,
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
        "sanity_floor": sanity_floor,
        "metric_comparison": metric_comparison,
        "result_interpretation": _model_result_interpretation(
            evidence_state=evidence_state,
            metric_comparison=metric_comparison,
            findings=findings,
        ),
        "feature_family_rows": feature_rows,
        "model_diagnostics_artifacts": {
            "availability": _dict_value(model_artifacts.get("availability")),
            "native_feature_importance": _dict_value(model_artifacts.get("native_feature_importance")),
            "permutation_importance": _dict_value(model_artifacts.get("permutation_importance")),
            "prediction_review": _dict_value(model_artifacts.get("prediction_review")),
            "interpretation": _list_value(model_artifacts.get("interpretation")),
            "limitations": _list_value(model_artifacts.get("limitations")),
        },
        "prediction_summary": prediction_summary,
        "diagnostics_summary": diagnostics_summary,
        "diagnostics_coverage": _diagnostics_coverage(diagnostics, source_artifacts),
        "validation_status": validation_status,
        "artifact_coverage": artifact_coverage,
        "findings": findings,
        "evidence_readiness": evidence_state["readiness"],
        "evidence_quality_score": evidence_state["quality_score"],
        "analysis_brief": brief,
        "visual_story_cards": _model_diagnostics_story_cards(
            primary_metric_name=primary_metric_name,
            primary_metric_value=primary_metric_value,
            prediction_summary=prediction_summary,
            feature_rows=feature_rows,
            diagnostics=diagnostics,
            model_diagnostics_artifacts=model_artifacts,
            findings=findings,
            evidence_state=evidence_state,
        ),
        "eda_playbook": _model_diagnostics_playbook(
            primary_metric_name=primary_metric_name,
            prediction_summary=prediction_summary,
            diagnostics=diagnostics,
            model_diagnostics_artifacts=model_artifacts,
            findings=findings,
            evidence_state=evidence_state,
        ),
        "evaluation_guardrails": _model_diagnostics_guardrails(evidence_state),
        "analysis_questions": _model_diagnostics_questions(evidence_state),
        "codex_navigation_prompts": _model_diagnostics_prompts(evidence_state),
    }


def _model_diagnostics_evidence_state(
    *,
    primary_metric_value: object,
    prediction_summary: dict[str, Any],
    diagnostics: dict[str, Any],
    feature_rows: list[dict[str, Any]],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    has_metric = primary_metric_value is not None
    prediction_rows = int(prediction_summary.get("row_count") or 0)
    has_predictions = prediction_summary.get("status") == "available" and prediction_rows > 0
    has_diagnostics = bool(diagnostics)
    used_feature_families = sum(1 for row in feature_rows if int(row.get("count") or 0) > 0)
    high_findings = sum(1 for item in findings if str(item.get("severity") or "") == "high")
    quality_score = 0
    quality_score += 30 if has_metric else 0
    quality_score += 30 if has_predictions else 0
    quality_score += 20 if has_diagnostics else 0
    quality_score += min(15, used_feature_families * 4)
    quality_score += 5 if findings else 0
    if quality_score >= 70:
        readiness = "evidence_ready"
    elif quality_score >= 35:
        readiness = "partial_review"
    else:
        readiness = "not_ready"
    return {
        "readiness": readiness,
        "quality_score": quality_score,
        "has_metric": has_metric,
        "has_predictions": has_predictions,
        "has_diagnostics": has_diagnostics,
        "prediction_rows": prediction_rows,
        "used_feature_families": used_feature_families,
        "high_finding_count": high_findings,
    }


def _model_metric_comparison(
    *,
    primary_metric_name: str,
    primary_metric_value: object,
    sanity_floor: dict[str, Any],
) -> dict[str, Any]:
    metric_name = primary_metric_name or str(sanity_floor.get("primary_metric_name") or "")
    current = _optional_float(primary_metric_value)
    floor = _optional_float(sanity_floor.get(metric_name)) if metric_name else None
    if floor is None:
        floor = _optional_float(sanity_floor.get("primary_metric_value"))
    higher_is_better = metric_name not in {"rmse", "mae", "log_loss", "mape", "mean_absolute_error"}
    delta = None if current is None or floor is None else current - floor
    relative_delta = None if delta is None or floor is None or floor == 0.0 else delta / abs(floor)
    if delta is None:
        status = "missing_sanity_floor" if current is not None else "missing_metric"
    elif higher_is_better:
        status = "beats_sanity_floor" if delta > 0 else "below_sanity_floor"
    else:
        status = "beats_sanity_floor" if delta < 0 else "below_sanity_floor"
    return {
        "metric_name": metric_name or None,
        "current_value": current,
        "floor_value": floor,
        "floor_value_text": _format_metric(floor),
        "delta": delta,
        "relative_delta": relative_delta,
        "higher_is_better": higher_is_better,
        "status": status,
    }


def _model_result_interpretation(
    *,
    evidence_state: dict[str, Any],
    metric_comparison: dict[str, Any],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    status = str(metric_comparison.get("status") or "missing_metric")
    metric_name = str(metric_comparison.get("metric_name") or "primary metric")
    current = _format_metric(metric_comparison.get("current_value"))
    floor = _format_metric(metric_comparison.get("floor_value"))
    delta = _format_signed_metric(metric_comparison.get("delta"))
    if status == "beats_sanity_floor":
        verdict = "clears_sanity_floor"
        headline = f"{metric_name} clears the sanity floor"
        narrative = (
            f"The run reports {metric_name}={current} versus sanity floor {floor} ({delta}). "
            "Treat this as permission to inspect behavior, not as a final decision."
        )
    elif status == "below_sanity_floor":
        verdict = "does_not_clear_sanity_floor"
        headline = f"{metric_name} does not clear the sanity floor"
        narrative = (
            f"The run reports {metric_name}={current} versus sanity floor {floor} ({delta}). "
            "Do not optimize around this result until the baseline or evaluation setup is repaired."
        )
    elif status == "missing_sanity_floor":
        verdict = "missing_sanity_floor"
        headline = "Metric is recorded, but sanity floor comparison is missing"
        narrative = (
            f"The run reports {metric_name}={current}, but the comparable sanity floor is not available in "
            "the run metrics. Read this as incomplete decision evidence."
        )
    else:
        verdict = "missing_metric"
        headline = "No primary metric is available"
        narrative = "The run cannot be interpreted as model evidence until the primary metric is recorded."
    next_action = _model_result_next_action(evidence_state=evidence_state, findings=findings)
    return {
        "verdict": verdict,
        "headline": headline,
        "narrative": narrative,
        "next_action": next_action,
        "metric_comparison": metric_comparison,
    }


def _model_result_next_action(
    *,
    evidence_state: dict[str, Any],
    findings: list[dict[str, str]],
) -> str:
    if not evidence_state.get("has_predictions"):
        return "Persist validation predictions before asking for feature importance, calibration, or slice analysis."
    if not evidence_state.get("has_diagnostics"):
        return "Run evaluation diagnostics to materialize slice metrics, score bins, and worst examples."
    high_or_medium = [
        item
        for item in findings
        if str(item.get("severity") or "") in {"high", "medium"} and str(item.get("next_action") or "")
    ]
    if high_or_medium:
        return str(high_or_medium[0]["next_action"])
    return "Create one targeted Codex follow-up for feature importance, permutation importance, calibration, or slice review."


def _model_diagnostics_analysis_brief(
    *,
    run: ExperimentRun,
    primary_metric_name: str,
    primary_metric_value: object,
    prediction_summary: dict[str, Any],
    evidence_state: dict[str, Any],
    metric_comparison: dict[str, Any],
) -> dict[str, Any]:
    readiness = str(evidence_state["readiness"])
    prediction_rows = int(evidence_state["prediction_rows"])
    if readiness == "evidence_ready":
        headline = "This model review has enough run evidence for a first human read."
        decision_state = "review model behavior"
        why = (
            "Metric, prediction, and diagnostic artifacts are present enough to inspect model behavior, "
            "not just leaderboard position."
        )
    elif readiness == "partial_review":
        headline = "This model review is useful only as a coverage check, not as a model-quality claim."
        decision_state = "fill diagnostic gaps"
        why = "Some run evidence exists, but missing prediction or diagnostics coverage limits interpretation."
    else:
        headline = "Do not read this as a model diagnostic notebook yet."
        decision_state = "not ready"
        why = (
            "The run does not expose enough metric, prediction, or diagnostics evidence. Return to Data Understanding "
            "or rerun baseline diagnostics before spending attention here."
        )
    return {
        "headline": headline,
        "decision_state": decision_state,
        "why_it_matters": why,
        "profile_boundary": (
            f"Run {run.id}; primary metric "
            f"{primary_metric_name or 'unknown'}={_format_metric(primary_metric_value)}; "
            f"prediction rows={prediction_rows}; sanity floor={metric_comparison.get('floor_value_text') or 'not available'}."
        ),
        "read_this_first": [
            {
                "title": "Readiness verdict",
                "why": headline,
                "artifact_hint": "Check evidence readiness and prediction coverage before reading charts.",
            },
            {
                "title": "Metric and split context",
                "why": "A single metric only matters if it matches the approved EvaluationSpec, split, and sanity floor.",
                "artifact_hint": (
                    f"Primary metric: {primary_metric_name or 'unknown'}={_format_metric(primary_metric_value)}; "
                    f"sanity floor: {metric_comparison.get('floor_value_text') or 'not available'}."
                ),
            },
            {
                "title": "Prediction coverage",
                "why": "Model behavior cannot be diagnosed without persisted validation predictions.",
                "artifact_hint": f"Prediction rows summarized: {prediction_rows}.",
            },
            {
                "title": "Next Codex task",
                "why": "Use Codex to fill the most important missing evidence instead of hand-reading empty panels.",
                "artifact_hint": "Ask for diagnostics, feature importance, permutation importance, calibration, or slice analysis.",
            },
        ],
    }


def _model_diagnostics_story_cards(
    *,
    primary_metric_name: str,
    primary_metric_value: object,
    prediction_summary: dict[str, Any],
    feature_rows: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    model_diagnostics_artifacts: dict[str, Any],
    findings: list[dict[str, str]],
    evidence_state: dict[str, Any],
) -> list[dict[str, Any]]:
    prediction_rows = int(evidence_state["prediction_rows"])
    metric_status = "ready" if evidence_state["has_metric"] else "missing"
    prediction_status = "ready" if evidence_state["has_predictions"] else "missing"
    diagnostics_status = "ready" if evidence_state["has_diagnostics"] else "missing"
    feature_count = sum(int(row.get("count") or 0) for row in feature_rows)
    model_availability = _dict_value(model_diagnostics_artifacts.get("availability"))
    native_status = str(model_availability.get("native_feature_importance") or "missing")
    permutation_status = str(model_availability.get("permutation_importance") or "missing")
    cards = [
        {
            "title": "Metric credibility",
            "status": metric_status,
            "why_read": "Start by asking whether the primary metric is meaningful for the user's decision.",
            "signal": f"{primary_metric_name or 'unknown'}={_format_metric(primary_metric_value)}",
        },
        {
            "title": "Prediction coverage",
            "status": prediction_status,
            "why_read": "Prediction artifacts unlock score bins, threshold review, calibration, and error analysis.",
            "signal": f"{prediction_rows} prediction rows summarized.",
        },
        {
            "title": "Diagnostics depth",
            "status": diagnostics_status,
            "why_read": "Slice metrics, worst examples, and sanity checks are needed before trusting aggregate lift.",
            "signal": _diagnostics_coverage(diagnostics, {}),
        },
        {
            "title": "Feature evidence",
            "status": "partial" if feature_count else "missing",
            "why_read": "Feature-family usage tells Codex where to add importance, PDP, and error-slice analysis.",
            "signal": f"{feature_count} features reported across families.",
        },
    ]
    if native_status == "ready" or permutation_status == "ready":
        cards.append(
            {
                "title": "Model evidence",
                "status": "ready" if permutation_status == "ready" else "partial",
                "why_read": "Feature and permutation evidence explain model behavior without treating leaderboard rank as the story.",
                "signal": f"native={native_status}; permutation={permutation_status}.",
            }
        )
    cards.append(
        {
            "title": "Attention queue",
            "status": "review",
            "why_read": "Findings define the next useful analysis rather than leaving the user with raw artifacts.",
            "signal": f"{len(findings)} finding(s), {evidence_state['high_finding_count']} high severity.",
        }
    )
    return cards


def _model_diagnostics_playbook(
    *,
    primary_metric_name: str,
    prediction_summary: dict[str, Any],
    diagnostics: dict[str, Any],
    model_diagnostics_artifacts: dict[str, Any],
    findings: list[dict[str, str]],
    evidence_state: dict[str, Any],
) -> list[dict[str, Any]]:
    availability = _dict_value(model_diagnostics_artifacts.get("availability"))
    rows = [
        {
            "stage": "1. Decide whether the notebook is worth reading",
            "reader_question": "Is this a real diagnostic review or only a placeholder generated before evidence exists?",
            "current_evidence": f"readiness={evidence_state['readiness']}; quality_score={evidence_state['quality_score']}",
            "codex_followup": "If not_ready, ask Codex to run or repair baseline diagnostics before reading further.",
        },
        {
            "stage": "2. Interpret the primary metric",
            "reader_question": "Does the metric match the problem type, class balance, and business decision?",
            "current_evidence": primary_metric_name or "No primary metric recorded.",
            "codex_followup": "Ask Codex to explain metric choice and compare alternatives only through EvaluationSpec.",
        },
        {
            "stage": "3. Inspect prediction behavior",
            "reader_question": "Where do scores concentrate, and are predictions available for threshold/calibration review?",
            "current_evidence": f"{int(prediction_summary.get('row_count') or 0)} prediction rows.",
            "codex_followup": "Ask Codex for score bins, calibration, threshold, and error-slice artifacts.",
        },
        {
            "stage": "4. Diagnose failures before optimizing",
            "reader_question": "Which slices, time periods, groups, or examples explain model weakness?",
            "current_evidence": _diagnostics_coverage(diagnostics, {}),
            "codex_followup": "Ask Codex to add slice metrics and worst-example review when diagnostics are missing.",
        },
    ]
    if availability:
        rows.append(
            {
                "stage": "5. Read model behavior evidence",
                "reader_question": "Which features actually move the stored model, and do native and permutation signals agree?",
                "current_evidence": (
                    f"native={availability.get('native_feature_importance', 'missing')}; "
                    f"permutation={availability.get('permutation_importance', 'missing')}; "
                    f"prediction_review={availability.get('prediction_review', 'missing')}"
                ),
                "codex_followup": "Use this artifact pack for feature, permutation, calibration, threshold, and slice interpretation.",
            }
        )
    rows.append(
        {
            "stage": f"{len(rows) + 1}. Convert findings into the next experiment",
            "reader_question": "Which single missing evidence item blocks the next credible modeling step?",
            "current_evidence": f"{len(findings)} finding(s) queued.",
            "codex_followup": "Create one targeted agent task, not a broad rerun.",
        },
    )
    return rows


def _model_diagnostics_guardrails(evidence_state: dict[str, Any]) -> list[dict[str, str]]:
    guardrails = [
        {
            "guardrail": "Do not trust empty diagnostics",
            "detail": "A model notebook with no predictions or metrics is a readiness signal, not model evidence.",
            "risk": "high" if evidence_state["readiness"] == "not_ready" else "medium",
            "status": str(evidence_state["readiness"]),
        },
        {
            "guardrail": "Respect EvaluationSpec and SplitManifest",
            "detail": "Do not recompute metrics on ad hoc splits while creating model diagnostics.",
            "risk": "high",
            "status": "always_on",
        },
    ]
    if not evidence_state["has_predictions"]:
        guardrails.append(
            {
                "guardrail": "Persist predictions before explanation",
                "detail": "Importance, PDP, calibration, threshold, and error review need prediction artifacts.",
                "risk": "high",
                "status": "blocked",
            }
        )
    return guardrails


def _model_diagnostics_questions(evidence_state: dict[str, Any]) -> list[str]:
    questions = [
        "Does the primary metric align with the approved evaluation design?",
        "Which validation slices or examples explain the current score?",
    ]
    if not evidence_state["has_predictions"]:
        questions.insert(0, "Why were validation predictions not persisted for this run?")
    if not evidence_state["has_diagnostics"]:
        questions.append("Which diagnostics should the runner materialize first: slices, calibration, or worst examples?")
    return questions


def _model_diagnostics_prompts(evidence_state: dict[str, Any]) -> list[str]:
    if evidence_state["readiness"] == "not_ready":
        return [
            "This notebook is not ready. Generate or repair baseline diagnostics, then recreate the model diagnostics notebook.",
            "Find why prediction rows are zero and persist validation predictions as artifacts.",
            "Open Data Understanding evidence first; do not compare models from this placeholder.",
        ]
    return [
        "Explain the primary metric in business terms and identify one failure-analysis artifact to generate next.",
        "Add artifact-backed feature importance and permutation importance for this run.",
        "Create calibration, threshold, and score-bin interpretation without changing EvaluationSpec.",
        "Inspect worst examples and slice metrics before recommending a new modeling approach.",
    ]


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
    *,
    authoring_brief_artifact: Artifact | None = None,
    response_locale: str = "en-US",
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
    analysis_brief = _analysis_brief(
        project=project,
        row_count=row_count,
        column_count=column_count,
        target_column=target_column,
        profile_mode=profile_mode,
        target_readiness=target_readiness,
        feature_sections=feature_sections,
        evaluation_guardrails=evaluation_guardrails,
        findings=findings,
    )
    eda_playbook = _eda_playbook(
        target_column=target_column,
        target_readiness=target_readiness,
        feature_sections=feature_sections,
        evaluation_guardrails=evaluation_guardrails,
        runs=runs,
    )
    visual_story_cards = _visual_story_cards(
        target_readiness=target_readiness,
        feature_sections=feature_sections,
        evaluation_guardrails=evaluation_guardrails,
        runs=runs,
    )
    feature_family_summary = _feature_family_summary(compact_columns)
    return {
        "title": "Data Understanding Notebook",
        "overview": overview,
        "response_locale": response_locale,
        "ui_copy": _notebook_ui_copy(response_locale),
        "authoring_mode": "harness_scaffold_pending_codex_authoring",
        "authoring_brief_artifact_id": authoring_brief_artifact.id if authoring_brief_artifact else None,
        "authoring_notice": _notebook_authoring_notice(
            response_locale,
            authoring_brief_artifact_id=authoring_brief_artifact.id if authoring_brief_artifact else None,
        ),
        "analysis_brief": analysis_brief,
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
        "eda_playbook": eda_playbook,
        "visual_story_cards": visual_story_cards,
        "feature_family_summary": feature_family_summary,
        "target_readiness": target_readiness,
        "feature_review_sections": feature_sections,
        "evaluation_guardrails": evaluation_guardrails,
        "analysis_questions": analysis_questions,
        "codex_navigation_prompts": _codex_navigation_prompts(
            target_column=target_column,
            target_readiness=target_readiness,
            feature_sections=feature_sections,
            evaluation_guardrails=evaluation_guardrails,
            runs=runs,
        ),
        "recent_runs": [_run_summary(run) for run in runs],
    }


def _notebook_ui_copy(locale: str) -> dict[str, str]:
    if locale.lower().startswith("ja"):
        return {
            "title": "データ理解ノートブック",
            "reader_brief": "最初に読む要点",
            "quality_rubric": "EDA品質チェック",
            "analysis_storyboard": "分析ストーリーボード",
            "target_readiness": "目的変数・予測目的の準備状況",
            "guardrails": "リーケージと評価設計のガードレール",
            "column_profile": "カラムプロファイル",
            "findings": "発見と追加調査キュー",
            "next": "次に見るべきこと",
            "target_details": "目的変数の値の詳細",
            "modeling_diagnostics": "モデリング診断",
            "language": "言語",
            "target_not_selected": "未選択",
            "scaffold_notice": "これはTablexハーネスが生成した足場です。最終的な深いEDAはCodexがSkillと実データを読んで書きます。",
            "artifact_note": "このノートブックはTablexのアセットです。Codex、Skill、人間の分析者が内容を深めても、EvaluationSpec、SplitManifest、アーティファクト、リネージはハーネス側で保持します。",
            "reader_questions": (
                "モデルより先に、データの物語を確認します。\n\n"
                "1. 1行は何を表し、その予測はどの意思決定に使われるのか。\n"
                "2. 有用そうな列、危険な列、重複、予測時に使えない列、疎すぎる列はどれか。\n"
                "3. 予測目的は選ばれているか。分布や粒度は評価指標に合っているか。\n"
                "4. Codexがモデリングコードを書く前に、EvaluationSpecとSplitManifestは何を守るべきか。"
            ),
            "current_read": "現在の読み",
            "feature_queue_intro": "優先して見る列群",
            "missingness": "欠損",
            "high_cardinality": "高カーディナリティ",
            "datetime": "日時",
            "text": "テキスト",
            "leakage_suspect": "リーケージ疑い",
            "missing_rate": "欠損率",
            "top_missing_columns": "欠損率が高い列",
            "no_column_profile": "カラムプロファイルがまだありません。",
            "semantic_type_mix": "意味タイプとロールの構成",
            "no_quality_rubric": "EDA品質チェックはまだありません。",
            "no_storyboard": "分析ストーリーボードはまだありません。",
            "no_guardrails": "ガードレールはまだ生成されていません。",
            "no_columns": "カラムプロファイルはまだ利用できません。",
            "no_findings": "発見はまだ生成されていません。",
            "default_next_actions": (
                "- 1行の意味と予測時点を確認する。\n"
                "- 欠損が多い列と高カーディナリティ列を確認する。\n"
                "- 目的が直接列なのか、遅延ラベルなのか、集計で作るものなのかを確認する。\n"
                "- リーケージ、時系列、グループ分割のリスクを見てから評価設計を固定する。"
            ),
            "no_target_values": "目的変数の値カウントはまだありません。",
            "no_runs": "実験Runはまだありません。Runが登録されたら、特徴量重要度、permutation importance、partial dependence、スライス診断、予測例の分析を追加します。",
        }
    return {
        "title": "Data Understanding Notebook",
        "reader_brief": "Reader brief",
        "quality_rubric": "EDA quality rubric",
        "analysis_storyboard": "Analysis storyboard",
        "target_readiness": "Target readiness",
        "guardrails": "Leakage and evaluation guardrails",
        "column_profile": "Column Profile",
        "findings": "Findings and Investigation Queue",
        "next": "What to inspect next",
        "target_details": "Target value details",
        "modeling_diagnostics": "Modeling Diagnostics",
        "language": "Language",
        "target_not_selected": "not selected",
        "scaffold_notice": "This is a Tablex harness-generated scaffold. The final deep EDA should be authored by Codex from Skills and the actual data.",
        "artifact_note": "This notebook is generated as a Tablex artifact. Codex, Skills, or a human analyst can revise it while preserving harness-owned EvaluationSpec, SplitManifest, artifacts, and lineage.",
        "reader_questions": (
            "Start with the data story, not the model. This notebook should help a human answer:\n\n"
            "1. What is one row, and what decision will be made from it?\n"
            "2. Which columns look useful, risky, duplicated, unavailable at prediction time, or too sparse?\n"
            "3. Is the objective selected, and does its distribution make the proposed metric sensible?\n"
            "4. What should EvaluationSpec and SplitManifest protect before Codex writes modeling code?"
        ),
        "current_read": "Current read",
        "feature_queue_intro": "High-signal queues",
        "missingness": "missingness",
        "high_cardinality": "high-cardinality",
        "datetime": "datetime",
        "text": "text",
        "leakage_suspect": "leakage-suspect",
        "missing_rate": "Missing rate",
        "top_missing_columns": "Top missing columns",
        "no_column_profile": "No column profile",
        "semantic_type_mix": "Semantic type and role mix",
        "no_quality_rubric": "No quality rubric available.",
        "no_storyboard": "No storyboard available.",
        "no_guardrails": "No guardrails generated yet.",
        "no_columns": "No profile columns are available yet.",
        "no_findings": "No findings have been generated yet.",
        "default_next_actions": (
            "- Confirm row semantics and prediction time.\n"
            "- Review high-missing and high-cardinality columns.\n"
            "- Decide whether the objective is direct, delayed, or derived by aggregation.\n"
            "- Lock evaluation only after leakage and grouping/time risks are understood."
        ),
        "no_target_values": "No target value counts are available yet.",
        "no_runs": (
            "No experiment runs are available yet. Once baseline or Codex-run experiments emit metrics, "
            "this notebook should add feature importance, permutation importance, partial dependence, "
            "slice diagnostics, and prediction analysis cells."
        ),
    }


def _notebook_authoring_notice(locale: str, *, authoring_brief_artifact_id: str | None) -> str:
    brief = authoring_brief_artifact_id or "notebook_authoring_brief"
    if locale.lower().startswith("ja"):
        return (
            "このアーティファクトはハーネス生成の足場であり、最終的なCodex執筆の深いEDAではありません。"
            f"Codexは `{brief}` と tablex-grandmaster-eda / tablex-notebook-quality Skill、実データを読み、"
            f"人間向けノートブックを {locale} で書く必要があります。"
        )
    return (
        "This artifact is a harness-generated scaffold. It is not yet the final Codex-authored Grandmaster-style EDA. "
        f"Codex should read `{brief}` plus tablex-grandmaster-eda/tablex-notebook-quality Skills and actual data, "
        f"then write the human-facing notebook in locale {locale}."
    )


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


def _analysis_brief(
    *,
    project: Project,
    row_count: int,
    column_count: int,
    target_column: str | None,
    profile_mode: str,
    target_readiness: dict[str, Any],
    feature_sections: dict[str, list[dict[str, Any]]],
    evaluation_guardrails: list[dict[str, str]],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    high_findings = [item for item in findings if item.get("severity") in {"high", "blocking"}]
    blocking_guardrails = [
        item for item in evaluation_guardrails if item.get("risk") in {"blocking", "high"}
    ]
    text_count = len(feature_sections.get("text") or [])
    time_count = len(feature_sections.get("datetime") or [])
    leakage_count = len(feature_sections.get("leakage_suspects") or [])
    missing_count = len([row for row in feature_sections.get("top_missing", []) if _float_value(row.get("missing_rate")) > 0])
    if not target_column:
        decision_state = "target_discovery"
        headline = "Target is not locked yet; read the dataset like a product/event story before designing evaluation."
    elif blocking_guardrails or leakage_count:
        decision_state = "risk_review"
        headline = "Target exists, but leakage and evaluation guardrails should be reviewed before model lift matters."
    else:
        decision_state = "baseline_ready_review"
        headline = "Profile evidence is ready for a first baseline plan, while evaluation assumptions stay visible."
    return {
        "style_goal": "analysis_article_quality",
        "headline": headline,
        "decision_state": decision_state,
        "why_it_matters": (
            f"{project.name} currently has {row_count:,} profiled rows and {column_count:,} columns. "
            f"The notebook should reduce cognitive load by telling the reader where evidence is strong, "
            f"where assumptions are unresolved, and what Codex should investigate next."
        ),
        "profile_boundary": f"Profile mode: {profile_mode}. Treat sample-backed statistics as directional, not final.",
        "read_this_first": [
            {
                "title": "Target and decision timing",
                "why": str(target_readiness.get("summary") or "Target semantics are not resolved."),
                "artifact_hint": "Target readiness, questions, and Evaluation guardrails",
            },
            {
                "title": "Leakage and availability",
                "why": (
                    f"{leakage_count} leakage-suspect column(s) are queued."
                    if leakage_count
                    else "No name-based leakage suspect was detected, but prediction-time availability still needs domain review."
                ),
                "artifact_hint": "Guardrails and leakage-suspect feature queue",
            },
            {
                "title": "Feature terrain",
                "why": (
                    f"{missing_count} missingness signal(s), {text_count} text field(s), and {time_count} datetime field(s) need triage."
                ),
                "artifact_hint": "Feature review queues and semantic mix",
            },
        ],
        "top_risks": [
            str(item.get("message") or item.get("detail") or "")
            for item in [*high_findings, *blocking_guardrails][:4]
            if str(item.get("message") or item.get("detail") or "")
        ],
        "reader_contract": [
            "Separate observed evidence from assumptions.",
            "Do not treat leaderboard movement as insight until EvaluationSpec and SplitManifest are respected.",
            "Ask Codex for targeted follow-up when a section raises a question instead of scanning every artifact manually.",
        ],
    }


def _eda_playbook(
    *,
    target_column: str | None,
    target_readiness: dict[str, Any],
    feature_sections: dict[str, list[dict[str, Any]]],
    evaluation_guardrails: list[dict[str, str]],
    runs: list[ExperimentRun],
) -> list[dict[str, str]]:
    has_time_or_group = any(item.get("status") == "scenario_compare" for item in evaluation_guardrails)
    return [
        {
            "stage": "1. Data story",
            "reader_question": "What does one row mean, and what event or decision produced it?",
            "current_evidence": "Profile shape, sample rows, candidate ID/group/time columns.",
            "codex_followup": "Infer row semantics from names/profile, list competing interpretations, and ask only high-value questions.",
        },
        {
            "stage": "2. Target and metric",
            "reader_question": "Is the target direct, delayed, aggregate-derived, or still undecided?",
            "current_evidence": str(target_readiness.get("summary") or "No target summary."),
            "codex_followup": (
                "Compare metric choices and target construction risks."
                if target_column
                else "Propose target-selection scenarios after data understanding."
            ),
        },
        {
            "stage": "3. Missingness and sparsity",
            "reader_question": "Is missingness signal, collection artifact, leakage, or unusable noise?",
            "current_evidence": f"{len(feature_sections.get('top_missing') or [])} columns queued by missingness.",
            "codex_followup": "Create missingness patterns, target-conditioned missingness, and imputation hypotheses.",
        },
        {
            "stage": "4. Feature families",
            "reader_question": "Which numeric, categorical, text, datetime, ID, and grouped fields need distinct treatment?",
            "current_evidence": (
                f"{len(feature_sections.get('text') or [])} text, "
                f"{len(feature_sections.get('datetime') or [])} datetime, "
                f"{len(feature_sections.get('high_cardinality') or [])} high-cardinality fields."
            ),
            "codex_followup": "Choose feature tactics from evidence, not a fixed recipe.",
        },
        {
            "stage": "5. Evaluation guardrails",
            "reader_question": "Would random, stratified, time, or group split tell a misleading story?",
            "current_evidence": "Scenario comparison needed." if has_time_or_group else "No time/group signal detected by profile heuristics.",
            "codex_followup": "Design scenario comparison and preserve approved EvaluationSpec/SplitManifest boundaries.",
        },
        {
            "stage": "6. Model diagnostics",
            "reader_question": "After a baseline, where does it fail and which explanations are evidence-backed?",
            "current_evidence": f"{len(runs)} run(s) available." if runs else "No run diagnostics yet.",
            "codex_followup": "Add importance, permutation importance, PDP, calibration, slice metrics, and concrete error examples.",
        },
    ]


def _visual_story_cards(
    *,
    target_readiness: dict[str, Any],
    feature_sections: dict[str, list[dict[str, Any]]],
    evaluation_guardrails: list[dict[str, str]],
    runs: list[ExperimentRun],
) -> list[dict[str, str]]:
    leakage_count = len(feature_sections.get("leakage_suspects") or [])
    high_card_count = len(feature_sections.get("high_cardinality") or [])
    text_count = len(feature_sections.get("text") or [])
    datetime_count = len(feature_sections.get("datetime") or [])
    return [
        {
            "title": "Target plot",
            "signal": str(target_readiness.get("status") or "unknown"),
            "why_read": str(target_readiness.get("metric_note") or "Metric readiness is unresolved."),
            "status": "ready" if target_readiness.get("status") == "profiled" else "needs_target",
        },
        {
            "title": "Missingness bar",
            "signal": f"{len(feature_sections.get('top_missing') or [])} queued columns",
            "why_read": "Missingness often reveals collection process, leakage, or segmentation.",
            "status": "ready",
        },
        {
            "title": "Feature family map",
            "signal": f"{text_count} text / {datetime_count} datetime / {high_card_count} high-cardinality",
            "why_read": "Different families need different modeling and validation assumptions.",
            "status": "ready",
        },
        {
            "title": "Leakage watchlist",
            "signal": f"{leakage_count} suspect columns",
            "why_read": "Exclude or scenario-test unavailable fields before trusting validation scores.",
            "status": "risk" if leakage_count else "watch",
        },
        {
            "title": "Split scenario map",
            "signal": ", ".join(item.get("status", "") for item in evaluation_guardrails[:3]),
            "why_read": "A strong model on the wrong split is not evidence.",
            "status": "review",
        },
        {
            "title": "Model review",
            "signal": f"{len(runs)} run(s)",
            "why_read": "Importance, PDP, calibration, and errors should be read after the first defensible run.",
            "status": "ready" if runs else "deferred",
        },
    ]


def _feature_family_summary(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for column in columns:
        family = str(column.get("semantic_type") or "unknown")
        entry = families.setdefault(family, {"family": family, "count": 0, "examples": []})
        entry["count"] = int(entry["count"]) + 1
        if len(entry["examples"]) < 5:
            entry["examples"].append(str(column.get("name") or ""))
    return sorted(families.values(), key=lambda item: (-int(item["count"]), str(item["family"])))


def _codex_navigation_prompts(
    *,
    target_column: str | None,
    target_readiness: dict[str, Any],
    feature_sections: dict[str, list[dict[str, Any]]],
    evaluation_guardrails: list[dict[str, str]],
    runs: list[ExperimentRun],
) -> list[str]:
    prompts = [
        "Walk me through this notebook like a senior data scientist. What should I read first and why?",
        "Summarize the biggest unresolved assumptions before any modeling work.",
        "Which columns should Codex inspect for leakage or prediction-time availability?",
    ]
    if not target_column:
        prompts.append("Given the profile, propose target definition scenarios without blocking the workflow.")
    elif target_readiness.get("status") == "profiled":
        prompts.append(f"Explain whether `{target_column}` looks classification-like or regression-like and what metric risks remain.")
    if feature_sections.get("text"):
        prompts.append("Design an evidence-backed text feature investigation; do not default blindly to TF-IDF.")
    if any(item.get("status") == "scenario_compare" for item in evaluation_guardrails):
        prompts.append("Compare random, stratified, time, and group split risks for this project.")
    if runs:
        prompts.append("Use the latest run artifacts to plan feature importance, permutation importance, PDP, calibration, and error analysis.")
    else:
        prompts.append("After the first baseline, what model diagnostics should Tablex generate before reporting results?")
    return prompts


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


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
    evidence_artifacts: list[Artifact],
) -> None:
    outputs = [
        manifest_artifact,
        report_artifact,
        html_artifact,
        figure_manifest_artifact,
        source_artifact,
        *evidence_artifacts,
    ]
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
    for artifact in [report_artifact, html_artifact, figure_manifest_artifact, source_artifact, *evidence_artifacts]:
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


def _format_signed_metric(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    return f"{number:+.6g}"


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


def _result_interpretation_html(interpretation: dict[str, Any]) -> str:
    if not interpretation:
        return ""
    comparison = _dict_value(interpretation.get("metric_comparison"))
    comparison_line = ""
    if comparison:
        comparison_line = (
            f"<p><strong>Sanity floor:</strong> "
            f"{escape(str(comparison.get('metric_name') or 'primary metric'))} "
            f"{escape(_format_metric(comparison.get('current_value')))} vs "
            f"{escape(_format_metric(comparison.get('floor_value')))} "
            f"({escape(_format_signed_metric(comparison.get('delta')))}).</p>"
        )
    return (
        '<section class="panel result-callout">'
        "<h2>Result interpretation</h2>"
        f"<strong>{escape(str(interpretation.get('headline') or 'Review result evidence'))}</strong>"
        f"<p>{escape(str(interpretation.get('narrative') or 'No interpretation recorded.'))}</p>"
        f"{comparison_line}"
        f"<p><strong>Next one action:</strong> {escape(str(interpretation.get('next_action') or 'Choose one focused follow-up.'))}</p>"
        "</section>"
    )


def _read_order_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No read order generated yet.</p>"
    output = []
    for index, item in enumerate(rows[:6], start=1):
        output.append(
            '<div class="playbook-row">'
            f"<strong>{index}. {escape(str(item.get('title') or 'Review item'))}</strong>"
            f"<p>{escape(str(item.get('why') or ''))}</p>"
            f'<div class="tiny">{escape(str(item.get("artifact_hint") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _story_card_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No visual story cards generated yet.</p>"
    output = []
    for item in rows[:8]:
        output.append(
            '<div class="story-card">'
            f"<strong>{escape(str(item.get('title') or 'Story card'))}</strong>"
            f'<span class="badge">{escape(str(item.get("status") or "review"))}</span>'
            f"<p>{escape(str(item.get('why_read') or ''))}</p>"
            f'<div class="tiny">{escape(str(item.get("signal") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _playbook_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No EDA playbook generated yet.</p>"
    output = []
    for item in rows:
        output.append(
            '<div class="playbook-row">'
            f"<strong>{escape(str(item.get('stage') or 'EDA stage'))}</strong>"
            f"<p>{escape(str(item.get('reader_question') or ''))}</p>"
            f'<div class="tiny">Evidence: {escape(str(item.get("current_evidence") or ""))}</div>'
            f'<div class="tiny">Codex: {escape(str(item.get("codex_followup") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _feature_family_html_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No feature family summary available.</p>"
    output = []
    max_count = max((int(row.get("count") or 0) for row in rows if isinstance(row, dict)), default=0)
    for row in rows[:12]:
        count = int(row.get("count") or 0)
        width = 0.0 if max_count <= 0 else max(4.0, count / max_count * 100)
        examples = ", ".join(str(item) for item in row.get("examples", [])[:5]) if isinstance(row.get("examples"), list) else ""
        output.append(
            '<div class="bar-row">'
            f'<code>{escape(str(row.get("family") or "unknown"))}</code>'
            f'<div class="bar-track"><div class="bar" style="width:{width:.1f}%"></div></div>'
            f"<span>{count}</span>"
            f'<div class="tiny span-all">{escape(examples)}</div>'
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
