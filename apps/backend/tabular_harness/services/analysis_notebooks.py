from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    LineageEdge,
    ModelVersion,
    Project,
    Report,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.agent_task_planner import validate_agent_task_contract
from tabular_harness.services.approach import (
    store_json_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.locales import locale_is_japanese

NOTEBOOK_INDEX_FIGURE_ID_LIMIT = 12


@dataclass(frozen=True)
class AnalysisNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    authoring_brief_artifact: Artifact | None
    artifact_ids: list[str]


@dataclass(frozen=True)
class ModelDiagnosticsNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
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
    "notebook_run_manifest",
    "notebook_report",
    "notebook_execution_plan",
    "notebook_figure_manifest",
    "notebook_evidence_bundle",
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
        artifact
        for artifact in project_artifacts
        if artifact.asset_type in {"analysis_notebook", "marimo_notebook"}
        and _notebook_index_has_native_marimo_source_or_unchecked(artifact)
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
    items_by_recommendation = sorted(items, key=_notebook_index_display_sort_key)
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
            "with_native_source": len(items_by_created),
            "with_report": sum(1 for item in items_by_created if item["coverage"]["has_report"]),
            "with_visualization": sum(1 for item in items_by_created if item["coverage"]["has_visualization"]),
            "with_execution_plan": sum(1 for item in items_by_created if item["coverage"]["has_execution_plan"]),
        },
        "recommended_notebook": recommended,
        "groups": _notebook_groups(items_by_recommendation),
        "items": items_by_recommendation,
        "next_actions": _notebook_index_next_actions(project, items_by_recommendation, recommended=recommended),
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
                "headline": "Create the first native marimo analysis notebook.",
                "reason": (
                    "No native marimo analysis notebook is registered for this project yet. Let Codex author and "
                    "register the first notebook so Tablex can open it through the native marimo viewer."
                ),
                "primary_action": {
                    "label": "Start Full Auto",
                    "action_type": "start_autonomous_loop",
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
    recommended = _dict_value(notebook_index.get("recommended_notebook")) or None
    selected_item = recommended
    if selected_item is None:
        return None
    notebook_artifact = db.get(Artifact, str(selected_item["notebook_artifact_id"]))
    if notebook_artifact is None:
        return None
    summary = _notebook_artifact_context_summary(notebook_artifact)
    brief = _dict_value(summary.get("analysis_brief"))
    linked_artifact_ids = _dict_value(selected_item.get("artifact_ids"))
    evidence_figures = _artifacts_for_metadata(
        db,
        project.id,
        "notebook_evidence_svg",
        "notebook_artifact_id",
        notebook_artifact.id,
    )
    source_artifact_id = notebook_artifact.id
    read_order = _analysis_story_read_order(brief.get("read_this_first"))
    story_cards = _analysis_story_cards(summary.get("visual_story_cards"))
    playbook = _analysis_story_playbook(summary.get("eda_playbook") or summary.get("review_playbook"))
    codex_prompts = _string_list(summary.get("codex_navigation_prompts"))
    if not codex_prompts:
        codex_prompts = _string_list(summary.get("analysis_questions"))
    caveats = _notebook_story_caveats(
        brief=brief,
        selected_item=selected_item,
        notebook_quality_issue=_story_item_is_empty_diagnostics(selected_item),
    )
    selection_score = int(selected_item.get("recommendation_score") or 0)
    return {
        "source_type": "analysis_notebook",
        "headline": _story_headline(
            brief.get("headline"),
            selected_item.get("title"),
            fallback="Read the recommended analysis notebook.",
        ),
        "deck": str(summary.get("overview") or selected_item.get("recommendation_reason") or ""),
        "why_this_story": str(selected_item.get("recommendation_reason") or "This notebook has the strongest current analysis evidence."),
        "selected_source": {
            "source_type": "analysis_notebook",
            "title": str(selected_item.get("title") or "Analysis Notebook"),
            "artifact_id": notebook_artifact.id,
            "source_artifact_id": source_artifact_id,
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
        ),
        "figure_refs": _artifact_refs(evidence_figures[:6]),
        "raw_artifacts": _story_raw_artifact_refs(db, project.id, notebook_artifact, linked_artifact_ids, evidence_figures),
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


def _analysis_story_source_summary(story: dict[str, Any]) -> dict[str, Any]:
    selected = _dict_value(story.get("selected_source"))
    return {
        "source_type": story.get("source_type"),
        "title": selected.get("title"),
        "artifact_id": selected.get("artifact_id"),
        "source_artifact_id": selected.get("source_artifact_id"),
        "status": selected.get("status"),
        "reason": selected.get("reason"),
    }


def create_notebook_execution_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    notebook_artifact: Artifact,
) -> NotebookExecutionPlanResult:
    if notebook_artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        raise ValueError("Artifact is not a native marimo notebook source artifact")
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


def _notebook_index_accepts_native_marimo_source(artifact: Artifact) -> bool:
    validation = _notebook_source_validation_for_index(artifact)
    if validation is None:
        return True
    return bool(validation.get("is_valid_marimo_notebook"))


def _notebook_index_has_native_marimo_source_or_unchecked(artifact: Artifact) -> bool:
    validation = _notebook_source_validation_for_index(artifact)
    if validation is None:
        return True
    return bool(validation.get("is_native_marimo_source"))


def _notebook_source_validation_for_index(artifact: Artifact) -> dict[str, Any] | None:
    try:
        source_path = source_notebook_path_for_export(artifact)
    except (OSError, json.JSONDecodeError):
        return None
    if source_path is None or not source_path.exists():
        return None
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _validate_marimo_notebook_source(source)


def assert_valid_marimo_notebook_artifact_source(artifact: Artifact) -> None:
    validation = marimo_notebook_source_validation_for_artifact(artifact)
    if validation.get("is_valid_marimo_notebook") is True:
        return
    errors = validation.get("errors")
    if isinstance(errors, list) and errors:
        raise ValueError("Referenced notebook artifact is not a valid native marimo source: " + "; ".join(map(str, errors)))
    checks = validation.get("checks")
    raise ValueError(f"Referenced notebook artifact is not a valid native marimo source: {checks}")


def marimo_notebook_source_validation_for_artifact(artifact: Artifact) -> dict[str, Any]:
    source_path = source_notebook_path_for_export(artifact)
    if source_path is None or not source_path.exists():
        raise ValueError("Referenced notebook artifact source file was not found")
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Referenced notebook artifact source file is not readable") from exc
    return _validate_marimo_notebook_source(source)


def assert_marimo_notebook_runtime_preflight(artifact: Artifact, *, timeout_seconds: int = 60) -> dict[str, Any]:
    result = marimo_notebook_runtime_preflight_for_artifact(artifact, timeout_seconds=timeout_seconds)
    if result.get("ok") is True:
        return result
    error_summary = str(result.get("error_summary") or result.get("stderr") or result.get("stdout") or "unknown runtime error")
    raise ValueError("Referenced notebook artifact failed native marimo runtime preflight: " + error_summary)


def marimo_notebook_runtime_preflight_for_artifact(artifact: Artifact, *, timeout_seconds: int = 60) -> dict[str, Any]:
    if not marimo_available():
        return {
            "schema_version": "marimo_notebook_runtime_preflight.v1",
            "ok": False,
            "error_type": "MarimoUnavailable",
            "error_summary": "marimo is not installed in the backend environment.",
        }
    source_path = source_notebook_path_for_export(artifact)
    if source_path is None or not source_path.exists():
        return {
            "schema_version": "marimo_notebook_runtime_preflight.v1",
            "ok": False,
            "error_type": "FileNotFoundError",
            "error_summary": "Notebook source file was not found.",
        }
    workdir = source_notebook_working_dir_for_export(artifact, source_path) or source_path.parent
    with tempfile.TemporaryDirectory(prefix="tablex_marimo_preflight_") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        output_path = temp_dir / "preflight.html"
        command = [
            sys.executable,
            "-m",
            "marimo",
            "export",
            "html",
            str(source_path),
            "-o",
            str(output_path),
            "--no-include-code",
            "--force",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(workdir),
                env=notebook_export_env(temp_dir),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "schema_version": "marimo_notebook_runtime_preflight.v1",
                "ok": False,
                "error_type": "TimeoutExpired",
                "error_summary": f"marimo runtime preflight exceeded {timeout_seconds} seconds.",
                "stdout": _excerpt(exc.stdout, 2000),
                "stderr": _excerpt(exc.stderr, 4000),
                "command": command_for_manifest(command),
                "working_dir": str(workdir),
            }
        stderr = _excerpt(completed.stderr, 4000)
        stdout = _excerpt(completed.stdout, 2000)
        ok = completed.returncode == 0 and output_path.exists()
        return {
            "schema_version": "marimo_notebook_runtime_preflight.v1",
            "ok": ok,
            "return_code": completed.returncode,
            "error_type": None if ok else "RuntimeError",
            "error_summary": None if ok else _compact_marimo_preflight_error(stderr or stdout),
            "stdout": stdout,
            "stderr": stderr,
            "command": command_for_manifest(command),
            "working_dir": str(workdir),
        }


def _compact_marimo_preflight_error(value: str, limit: int = 1600) -> str:
    text = value.strip()
    if not text:
        return "marimo runtime preflight failed without stderr output."
    traceback_start = text.rfind("Traceback (most recent call last):")
    if traceback_start >= 0:
        text = text[traceback_start:]
    if len(text) <= limit:
        return text
    head_limit = max(400, limit // 2)
    tail_limit = max(400, limit - head_limit)
    return text[:head_limit].rstrip() + "\n...\n" + text[-tail_limit:].lstrip()


def _validate_marimo_notebook_source(source: str) -> dict[str, Any]:
    checks = _marimo_source_checks(source)
    is_marimo_notebook = all(checks[key] for key in ("imports_marimo", "defines_marimo_app"))
    errors = _marimo_source_validation_errors(checks)
    return {
        "schema_version": "marimo_notebook_source_validation.v1",
        "is_valid_marimo_notebook": is_marimo_notebook and not errors,
        "is_native_marimo_source": is_marimo_notebook,
        "checks": checks,
        "errors": errors,
    }


def _marimo_source_checks(source: str) -> dict[str, Any]:
    checks = {
        "imports_marimo": False,
        "defines_marimo_app": False,
        "has_main_run_guard": 'if __name__ == "__main__"' in source,
        "mentions_artifact_policy": "EvaluationSpec" in source and "SplitManifest" in source,
        "has_duplicate_public_cell_definitions": False,
        "duplicate_public_cell_definitions": [],
        "visual_call_count": 0,
        "visual_call_kinds": [],
    }
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        checks["parse_error"] = f"{exc.__class__.__name__}: {exc.msg}"
        return checks
    marimo_module_names: set[str] = set()
    marimo_app_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "marimo":
                    checks["imports_marimo"] = True
                    marimo_module_names.add(alias.asname or "marimo")
        elif isinstance(node, ast.ImportFrom) and node.module == "marimo":
            checks["imports_marimo"] = True
            for alias in node.names:
                if alias.name == "App":
                    marimo_app_names.add(alias.asname or "App")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "App":
            if isinstance(callee.value, ast.Name) and callee.value.id in marimo_module_names:
                checks["defines_marimo_app"] = True
                break
        elif isinstance(callee, ast.Name) and callee.id in marimo_app_names:
            checks["defines_marimo_app"] = True
            break
    duplicate_definitions = _duplicate_marimo_public_cell_definitions(tree)
    if duplicate_definitions:
        checks["has_duplicate_public_cell_definitions"] = True
        checks["duplicate_public_cell_definitions"] = duplicate_definitions
    visual_call_kinds = _marimo_visual_call_kinds(tree)
    checks["visual_call_count"] = len(visual_call_kinds)
    checks["visual_call_kinds"] = sorted(set(visual_call_kinds))
    return checks


def _marimo_source_validation_errors(checks: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    parse_error = checks.get("parse_error")
    if parse_error:
        errors.append(f"source did not parse as Python: {parse_error}")
    if not checks.get("imports_marimo"):
        errors.append("source does not import marimo")
    if not checks.get("defines_marimo_app"):
        errors.append("source does not define a marimo App")
    duplicate_definitions = checks.get("duplicate_public_cell_definitions")
    if isinstance(duplicate_definitions, list):
        for item in duplicate_definitions:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            lines = item.get("lines")
            errors.append(f"marimo public variable `{name}` is defined in multiple cells at lines {lines}")
    return errors


def _duplicate_marimo_public_cell_definitions(tree: ast.AST) -> list[dict[str, Any]]:
    definitions_by_name: dict[str, list[int]] = {}
    for cell in _marimo_cell_functions(tree):
        collector = _MarimoCellPublicDefinitionCollector()
        for statement in cell.body:
            collector.visit(statement)
        cell_definitions: dict[str, int] = {}
        for name, line_number in collector.definitions:
            if name.startswith("_"):
                continue
            cell_definitions.setdefault(name, line_number)
        for name, line_number in cell_definitions.items():
            definitions_by_name.setdefault(name, []).append(line_number)
    duplicates: list[dict[str, Any]] = []
    for name, lines in sorted(definitions_by_name.items()):
        unique_lines = sorted(set(lines))
        if len(unique_lines) > 1:
            duplicates.append({"name": name, "lines": unique_lines})
    return duplicates


def _marimo_cell_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    cells: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_decorator_is_marimo_cell(decorator) for decorator in node.decorator_list):
            cells.append(node)
    return cells


def _decorator_is_marimo_cell(decorator: ast.expr) -> bool:
    candidate = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(candidate, ast.Attribute) and candidate.attr == "cell"


def _marimo_visual_call_kinds(tree: ast.AST) -> list[str]:
    aliases = _import_aliases(tree)
    kinds: list[str] = []
    plotly_express_aliases = aliases.get("plotly.express", set()) | {"px"}
    plotly_go_aliases = aliases.get("plotly.graph_objects", set()) | {"go"}
    matplotlib_aliases = aliases.get("matplotlib.pyplot", set()) | {"plt"}
    seaborn_aliases = aliases.get("seaborn", set()) | {"sns"}
    altair_aliases = aliases.get("altair", set()) | {"alt"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute):
            continue
        root_name = _attribute_root_name(callee)
        if root_name in plotly_express_aliases:
            kinds.append(f"plotly.express.{callee.attr}")
        elif root_name in plotly_go_aliases:
            kinds.append(f"plotly.graph_objects.{callee.attr}")
        elif root_name in matplotlib_aliases:
            kinds.append(f"matplotlib.pyplot.{callee.attr}")
        elif root_name in seaborn_aliases:
            kinds.append(f"seaborn.{callee.attr}")
        elif root_name in altair_aliases or callee.attr in {"mark_bar", "mark_line", "mark_point", "mark_circle", "mark_area", "mark_rect"}:
            kinds.append(f"altair.{callee.attr}")
        elif callee.attr in {"plot", "hist", "boxplot", "scatter"}:
            kinds.append(f"pandas.{callee.attr}")
    return kinds


def _import_aliases(tree: ast.AST) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases.setdefault(alias.name, set()).add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases.setdefault(f"{node.module}.{alias.name}", set()).add(alias.asname or alias.name)
    return aliases


def _attribute_root_name(node: ast.Attribute) -> str | None:
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


class _MarimoCellPublicDefinitionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.definitions: list[tuple[str, int]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.definitions.append(((alias.asname or alias.name.split(".", 1)[0]), node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            self.definitions.append(((alias.asname or alias.name), node.lineno))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.definitions.extend((name, node.lineno) for name in _assignment_target_names(target))
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.definitions.extend((name, node.lineno) for name in _assignment_target_names(node.target))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.definitions.extend((name, node.lineno) for name in _assignment_target_names(node.target))
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self.definitions.extend((name, node.lineno) for name in _assignment_target_names(node.target))
        self.visit(node.iter)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.definitions.extend((name, node.lineno) for name in _assignment_target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.definitions.append((node.name, node.lineno))
        for statement in node.body:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.definitions.append((node.name, node.lineno))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.definitions.append((node.name, node.lineno))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.definitions.append((node.name, node.lineno))

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _assignment_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_assignment_target_names(element))
        return names
    if isinstance(target, ast.Starred):
        return _assignment_target_names(target.value)
    return []


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
    workspace_info = agent_session_notebook_workspace_info(notebook_artifact)
    if workspace_info is not None:
        candidate, _session_root = workspace_info
        if candidate.exists():
            return candidate
    primary = artifact_primary_path(notebook_artifact)
    return primary.resolve() if primary.exists() else None


def marimo_notebook_source_hash_for_artifact(notebook_artifact: Artifact) -> str | None:
    try:
        source_path = source_notebook_path_for_export(notebook_artifact)
    except (OSError, json.JSONDecodeError):
        return None
    if source_path is None or not source_path.exists():
        return None
    try:
        return hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError:
        return None


def source_notebook_working_dir_for_export(notebook_artifact: Artifact, notebook_path: Path | None = None) -> Path | None:
    workspace_info = agent_session_notebook_workspace_info(notebook_artifact)
    if workspace_info is not None:
        _candidate, session_root = workspace_info
        if session_root.exists():
            return session_root
    resolved_notebook_path = notebook_path or source_notebook_path_for_export(notebook_artifact)
    return resolved_notebook_path.parent.resolve() if resolved_notebook_path is not None else None


def agent_session_notebook_workspace_info(notebook_artifact: Artifact) -> tuple[Path, Path] | None:
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
                return candidate, session_root
    return None


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
    mpl_config_dir = workspace / ".tablex_matplotlib"
    xdg_config_home = workspace / ".tablex_config"
    xdg_cache_home = workspace / ".tablex_cache"
    mpl_config_dir.mkdir(parents=True, exist_ok=True)
    xdg_config_home.mkdir(parents=True, exist_ok=True)
    xdg_cache_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(isolated_home)
    env["MPLBACKEND"] = "Agg"
    env["MPLCONFIGDIR"] = str(mpl_config_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    env["XDG_CACHE_HOME"] = str(xdg_cache_home)
    env["TABLEX_NOTEBOOK_RENDER"] = "1"
    return env


def command_for_manifest(command: list[str]) -> list[str]:
    return [Path(part).name if index == 0 else part for index, part in enumerate(command)]


def _excerpt(value: object, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    if len(text) <= limit:
        return text
    head_limit = max(400, limit // 2)
    tail_limit = max(400, limit - head_limit)
    return text[:head_limit].rstrip() + "\n...\n" + text[-tail_limit:].lstrip()


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


def _notebook_index_context_links(
    db: Session,
    project: Project,
    *,
    notebook_kind: str,
    dataset_snapshot_id: str | None,
    run_id: str | None,
    model_version_id: str | None,
    context_source: str | None = None,
) -> dict[str, str | None]:
    context_source = context_source or ("metadata" if any((dataset_snapshot_id, run_id, model_version_id)) else "none")
    run: ExperimentRun | None = None
    model_version: ModelVersion | None = None

    if run_id:
        run = db.get(ExperimentRun, run_id)
        if run is not None and run.project_id == project.id:
            dataset_snapshot_id = dataset_snapshot_id or run.dataset_snapshot_id
            model_version_id = model_version_id or run.model_version_id

    if model_version_id:
        model_version = db.get(ModelVersion, model_version_id)
        if model_version is not None and model_version.project_id == project.id:
            run_id = run_id or model_version.experiment_run_id
            dataset_snapshot_id = dataset_snapshot_id or model_version.dataset_snapshot_id

    if notebook_kind == "data_understanding" and not dataset_snapshot_id:
        dataset_snapshot = _unique_project_dataset_snapshot(db, project.id)
        if dataset_snapshot is not None:
            dataset_snapshot_id = dataset_snapshot.id
            context_source = "unique_project_dataset"

    if not dataset_snapshot_id and str(context_source or "").startswith("research_plan_node"):
        dataset_snapshot = _unique_project_dataset_snapshot(db, project.id)
        if dataset_snapshot is not None:
            dataset_snapshot_id = dataset_snapshot.id

    if notebook_kind == "model_diagnostics" and not run_id and not model_version_id:
        unique_run = _unique_project_experiment_run(db, project.id)
        if unique_run is not None:
            run_id = unique_run.id
            dataset_snapshot_id = dataset_snapshot_id or unique_run.dataset_snapshot_id
            model_version_id = unique_run.model_version_id
            context_source = "unique_project_run"
        else:
            unique_model_version = _unique_project_model_version(db, project.id)
            if unique_model_version is not None:
                model_version_id = unique_model_version.id
                run_id = unique_model_version.experiment_run_id
                dataset_snapshot_id = dataset_snapshot_id or unique_model_version.dataset_snapshot_id
                context_source = "unique_project_model_version"

    return {
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
        "context_link_source": context_source,
    }


def _unique_project_dataset_snapshot(db: Session, project_id: str) -> DatasetSnapshot | None:
    candidates = list(
        db.scalars(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.desc())
            .limit(2)
        ).all()
    )
    return candidates[0] if len(candidates) == 1 else None


def _unique_project_experiment_run(db: Session, project_id: str) -> ExperimentRun | None:
    candidates = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project_id)
            .order_by(ExperimentRun.started_at.desc().nullslast(), ExperimentRun.id.desc())
            .limit(2)
        ).all()
    )
    return candidates[0] if len(candidates) == 1 else None


def _unique_project_model_version(db: Session, project_id: str) -> ModelVersion | None:
    candidates = list(
        db.scalars(
            select(ModelVersion)
            .where(ModelVersion.project_id == project_id)
            .order_by(ModelVersion.created_at.desc())
            .limit(2)
        ).all()
    )
    return candidates[0] if len(candidates) == 1 else None


def _notebook_context_links_from_research_plan_edges(
    db: Session,
    project: Project,
    notebook_artifact: Artifact,
) -> dict[str, Any]:
    notebook_edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == project.id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == notebook_artifact.id,
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.desc())
            .limit(20)
        ).all()
    )
    node_refs: list[dict[str, str]] = []
    for notebook_edge in notebook_edges:
        metadata = loads_json(notebook_edge.metadata_json, {})
        node_id = str(metadata.get("node_id") or "").strip()
        research_plan_id = str(metadata.get("research_plan_id") or "").strip()
        revision_id = str(metadata.get("revision_id") or notebook_edge.from_asset_id or "").strip()
        if not node_id:
            continue
        node_refs.append(
            {
                "node_id": node_id,
                "research_plan_id": research_plan_id,
                "revision_id": revision_id,
            }
        )

    def _empty_context(context_source: str = "none") -> dict[str, Any]:
        return {
            "dataset_snapshot_id": None,
            "run_id": None,
            "model_version_id": None,
            "context_link_source": context_source,
            "research_plan_id": None,
            "research_plan_node_id": None,
            "related_run_ids": [],
        }

    if not node_refs:
        return _empty_context()

    def _single_value(values: list[str]) -> str | None:
        unique_values = {value for value in values if value}
        return next(iter(unique_values)) if len(unique_values) == 1 else None

    research_plan_id = _single_value([ref["research_plan_id"] for ref in node_refs])
    node_id = _single_value([ref["node_id"] for ref in node_refs])
    run_edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "research_plan_revision",
                LineageEdge.to_asset_type == "experiment_run",
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.desc())
            .limit(1000)
        ).all()
    )
    candidate_run_ids: list[str] = []
    for ref in node_refs:
        for run_edge in run_edges:
            run_metadata = loads_json(run_edge.metadata_json, {})
            edge_node_id = str(run_metadata.get("node_id") or "").strip()
            edge_research_plan_id = str(run_metadata.get("research_plan_id") or "").strip()
            edge_revision_id = str(run_metadata.get("revision_id") or run_edge.from_asset_id or "").strip()
            same_node = edge_node_id == ref["node_id"]
            same_plan = bool(ref["research_plan_id"]) and edge_research_plan_id == ref["research_plan_id"]
            same_revision = bool(ref["revision_id"]) and edge_revision_id == ref["revision_id"]
            if same_node and (same_plan or same_revision) and run_edge.to_asset_id not in candidate_run_ids:
                candidate_run_ids.append(run_edge.to_asset_id)

    if not candidate_run_ids:
        context = _empty_context("research_plan_node")
        context["research_plan_id"] = research_plan_id
        context["research_plan_node_id"] = node_id
        return context

    runs = [
        run
        for run_id in candidate_run_ids
        if (run := db.get(ExperimentRun, run_id)) is not None and run.project_id == project.id
    ]
    if not runs:
        return _empty_context()

    dataset_ids = {run.dataset_snapshot_id for run in runs if run.dataset_snapshot_id}
    dataset_snapshot_id = next(iter(dataset_ids)) if len(dataset_ids) == 1 else None

    if len(runs) != 1:
        return {
            "dataset_snapshot_id": dataset_snapshot_id,
            "run_id": None,
            "model_version_id": None,
            "context_link_source": "research_plan_node_runs",
            "research_plan_id": research_plan_id,
            "research_plan_node_id": node_id,
            "related_run_ids": [run.id for run in runs],
        }

    run = runs[0]
    model_version_id = run.model_version_id
    if not model_version_id:
        model_version = _model_version_for_run(db, run)
        model_version_id = model_version.id if model_version is not None else None
    return {
        "dataset_snapshot_id": run.dataset_snapshot_id,
        "run_id": run.id,
        "model_version_id": model_version_id,
        "context_link_source": "research_plan_node",
        "research_plan_id": research_plan_id,
        "research_plan_node_id": node_id,
        "related_run_ids": [run.id],
    }


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
    if (
        notebook_kind == "model_diagnostics"
        and not metadata.get("run_id")
        and metadata.get("related_run_ids")
    ):
        notebook_kind = "model_comparison"
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
    figure_manifest_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_figure_manifest", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    evidence_bundle_artifact = _latest_artifact_for_metadata_cached(
        db, project.id, "notebook_evidence_bundle", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    evidence_figure_artifacts = _artifacts_for_metadata_cached(
        db, project.id, "notebook_evidence_svg", "notebook_artifact_id", notebook_artifact.id, artifact_lookup
    )
    session_linked = _agent_session_notebook_artifacts(db, project.id, notebook_artifact, notebook_kind, artifact_lookup)
    report_artifact = report_artifact or session_linked["report_artifact"]
    manifest_artifact = manifest_artifact or session_linked["manifest"]
    figure_manifest_artifact = figure_manifest_artifact or session_linked["figure_manifest"]
    evidence_bundle_artifact = evidence_bundle_artifact or session_linked["evidence_bundle"]
    evidence_figure_artifacts = _unique_artifacts([*evidence_figure_artifacts, *session_linked["evidence_figures"]])
    report = reports_by_artifact_id.get(report_artifact.id) if report_artifact else None
    visualization = visualizations_by_artifact_id.get(visualization_artifact.id) if visualization_artifact else None
    related_metadata_sources = [
        metadata,
        loads_json(report_artifact.metadata_json, {}) if report_artifact else {},
        loads_json(figure_manifest_artifact.metadata_json, {}) if figure_manifest_artifact else {},
        loads_json(evidence_bundle_artifact.metadata_json, {}) if evidence_bundle_artifact else {},
        loads_json(agent_task_contract_artifact.metadata_json, {}) if agent_task_contract_artifact else {},
        loads_json(execution_plan_artifact.metadata_json, {}) if execution_plan_artifact else {},
    ]
    metadata_dataset_snapshot_id = _first_metadata_text(related_metadata_sources, "dataset_snapshot_id")
    metadata_run_id = _first_metadata_text(related_metadata_sources, "run_id")
    metadata_model_version_id = _first_metadata_text(related_metadata_sources, "model_version_id")
    metadata_related_run_ids = _first_metadata_string_list(related_metadata_sources, "related_run_ids")
    research_plan_context = _notebook_context_links_from_research_plan_edges(db, project, notebook_artifact)
    context_source = (
        "metadata"
        if any((metadata_dataset_snapshot_id, metadata_run_id, metadata_model_version_id, metadata_related_run_ids))
        else research_plan_context["context_link_source"]
    )
    context_links = _notebook_index_context_links(
        db,
        project,
        notebook_kind=notebook_kind,
        dataset_snapshot_id=metadata_dataset_snapshot_id or research_plan_context["dataset_snapshot_id"],
        run_id=metadata_run_id or research_plan_context["run_id"],
        model_version_id=metadata_model_version_id or research_plan_context["model_version_id"],
        context_source=context_source,
    )
    dataset_snapshot_id = context_links["dataset_snapshot_id"]
    run_id = context_links["run_id"]
    model_version_id = context_links["model_version_id"]
    context_summary = _notebook_artifact_context_summary(notebook_artifact)
    content = _notebook_content_signal(notebook_kind, context_summary)
    if content["readiness"] in {"source_only", "unknown"}:
        content = _agent_session_notebook_content_signal(
            notebook_kind=notebook_kind,
            current=content,
            report_artifact=report_artifact,
            figure_manifest_artifact=figure_manifest_artifact,
            evidence_bundle_artifact=evidence_bundle_artifact,
            evidence_figure_artifacts=evidence_figure_artifacts,
            visual_story_artifact=session_linked["visual_story_cards"],
        )
    execution_status = str(metadata.get("execution_status") or "unknown")
    source_validation = _notebook_source_validation_for_index(notebook_artifact)
    source_validation_errors = (
        [str(item) for item in source_validation.get("errors", [])]
        if isinstance(source_validation, dict) and isinstance(source_validation.get("errors"), list)
        else []
    )
    latest_runtime_failure = _latest_native_marimo_runtime_failure(db, project.id, notebook_artifact.id)
    if latest_runtime_failure is not None:
        native_marimo_status = "runtime_error"
    elif isinstance(source_validation, dict) and source_validation.get("is_valid_marimo_notebook") is False:
        native_marimo_status = "source_error"
    else:
        native_marimo_status = "source_registered"
    quality_manifest = metadata.get("notebook_quality_manifest") if isinstance(metadata.get("notebook_quality_manifest"), dict) else None
    manifest_key_findings = quality_manifest.get("key_findings") if isinstance(quality_manifest, dict) else None
    manifest_read_order = quality_manifest.get("read_order") if isinstance(quality_manifest, dict) else None
    if isinstance(quality_manifest, dict) and str(content.get("readiness") or "") in {"source_only", "unknown"}:
        manifest_figure_count = int(quality_manifest.get("figure_count") or 0)
        if manifest_figure_count > 0 and manifest_key_findings and manifest_read_order:
            content = {
                **content,
                "readiness": "narrative_ready" if notebook_kind == "data_understanding" else "evidence_ready",
                "quality_score": max(int(content.get("quality_score") or 0), 70),
                "read_order_count": max(int(content.get("read_order_count") or 0), len(manifest_read_order)),
                "story_card_count": max(int(content.get("story_card_count") or 0), len(manifest_key_findings)),
                "evidence_figure_count": max(int(content.get("evidence_figure_count") or 0), manifest_figure_count),
            }
    notebook_quality_status = str(metadata.get("notebook_quality_status") or "")
    if not isinstance(quality_manifest, dict):
        notebook_quality_status = notebook_quality_status or "needs_manifest"
    elif int(quality_manifest.get("figure_count") or 0) <= 0:
        notebook_quality_status = "needs_figures"
    elif not manifest_key_findings or not manifest_read_order:
        notebook_quality_status = "needs_manifest_detail"
    coverage = {
        "has_native_source": True,
        "has_manifest": manifest_artifact is not None,
        "has_quality_manifest": isinstance(quality_manifest, dict),
        "notebook_quality_status": notebook_quality_status or None,
        "has_report": report_artifact is not None,
        "has_visualization": visualization_artifact is not None and visualization is not None,
        "has_execution_plan": execution_plan_artifact is not None,
        "has_execution_report": False,
        "has_evidence_bundle": evidence_bundle_artifact is not None,
        "evidence_figure_count": len(evidence_figure_artifacts),
        "declared_figure_count": int(quality_manifest.get("figure_count") or 0) if isinstance(quality_manifest, dict) else 0,
        "declared_table_count": int(quality_manifest.get("table_count") or 0) if isinstance(quality_manifest, dict) else 0,
        "declared_finding_count": len(manifest_key_findings) if isinstance(manifest_key_findings, list) else 0,
        "declared_read_order_count": len(manifest_read_order) if isinstance(manifest_read_order, list) else 0,
        "has_figure_manifest": figure_manifest_artifact is not None,
        "execution_status": execution_status,
        "native_marimo_status": native_marimo_status,
        "native_marimo_source_validation": source_validation,
        "native_marimo_source_errors": source_validation_errors,
        "native_marimo_error_artifact_id": latest_runtime_failure.id if latest_runtime_failure is not None else None,
        "content_readiness": content["readiness"],
        "content_quality_score": content["quality_score"],
    }
    recommendation_score = _notebook_recommendation_score(notebook_kind, coverage, metadata, content)
    title = _notebook_display_title(notebook_kind, metadata, quality_manifest)
    related_run_ids = _unique_texts([*metadata_related_run_ids, *research_plan_context["related_run_ids"]])
    return {
        "notebook_artifact_id": notebook_artifact.id,
        "notebook_kind": notebook_kind,
        "title": title,
        "status": _notebook_index_status(
            execution_status,
            native_marimo_status=native_marimo_status,
            notebook_quality_status=notebook_quality_status,
        ),
        "created_at": notebook_artifact.created_at.isoformat(),
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
        "context_link_source": context_links["context_link_source"],
        "research_plan_id": research_plan_context["research_plan_id"],
        "research_plan_node_id": research_plan_context["research_plan_node_id"],
        "related_run_ids": related_run_ids,
        "related_context": {
            "dataset_snapshot_id": dataset_snapshot_id,
            "run_id": run_id,
            "model_version_id": model_version_id,
            "context_link_source": context_links["context_link_source"],
            "research_plan_id": research_plan_context["research_plan_id"],
            "research_plan_node_id": research_plan_context["research_plan_node_id"],
            "related_run_ids": related_run_ids,
        },
        "artifact_ids": {
            "notebook": notebook_artifact.id,
            "source": notebook_artifact.id,
            "manifest": manifest_artifact.id if manifest_artifact else None,
            "report_artifact": report_artifact.id if report_artifact else None,
            "visualization_artifact": visualization_artifact.id if visualization_artifact else None,
            "execution_plan": execution_plan_artifact.id if execution_plan_artifact else None,
            "agent_task_contract": agent_task_contract_artifact.id if agent_task_contract_artifact else None,
            "figure_manifest": figure_manifest_artifact.id if figure_manifest_artifact else None,
            "evidence_bundle": evidence_bundle_artifact.id if evidence_bundle_artifact else None,
            "evidence_figures": [artifact.id for artifact in evidence_figure_artifacts[:NOTEBOOK_INDEX_FIGURE_ID_LIMIT]],
        },
        "source_artifact_id": notebook_artifact.id,
        "report_id": report.id if report else None,
        "visualization_id": visualization.id if visualization else None,
        "coverage": coverage,
        "quality_manifest": quality_manifest,
        "content": content,
        "recommendation_score": recommendation_score,
        "recommendation_reason": _notebook_recommendation_reason(notebook_kind, coverage, content),
    }


def _first_metadata_text(metadata_sources: list[dict[str, Any]], key: str) -> str | None:
    for metadata in metadata_sources:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _first_metadata_string_list(metadata_sources: list[dict[str, Any]], key: str) -> list[str]:
    for metadata in metadata_sources:
        value = metadata.get(key)
        if not isinstance(value, list):
            continue
        strings = [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
        if strings:
            return _unique_texts(strings)
    return []


def _unique_texts(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _notebook_index_status(
    execution_status: str,
    *,
    native_marimo_status: str = "source_registered",
    notebook_quality_status: str = "",
) -> str:
    if native_marimo_status == "runtime_error":
        return "needs_attention"
    if native_marimo_status == "source_error":
        return "needs_attention"
    if notebook_quality_status.startswith("needs_"):
        return "needs_attention"
    if execution_status == "unknown":
        return "ready"
    return execution_status


def _latest_native_marimo_runtime_failure(db: Session, project_id: str, notebook_artifact_id: str) -> Artifact | None:
    candidates = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type == "agent_chat_turn",
        )
        .order_by(Artifact.created_at.desc())
        .limit(200)
    ).all()
    current_source_hash: str | None = None
    current_source_hash_loaded = False
    for artifact in candidates:
        metadata = loads_json(artifact.metadata_json, {})
        failure_source_hash = metadata.get("notebook_source_hash")
        if (
            metadata.get("source") != "native_marimo_runtime_failure"
            or metadata.get("notebook_artifact_id") != notebook_artifact_id
            or metadata.get("status") == "recovered"
        ):
            continue
        if not current_source_hash_loaded:
            notebook_artifact = db.get(Artifact, notebook_artifact_id)
            current_source_hash = (
                marimo_notebook_source_hash_for_artifact(notebook_artifact) if notebook_artifact is not None else None
            )
            current_source_hash_loaded = True
        if (
            current_source_hash is None
            or (isinstance(failure_source_hash, str) and failure_source_hash == current_source_hash)
        ):
            return artifact
    return None


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
        "visual_story_cards": _best_agent_session_artifact(
            artifacts, role="visual_story_cards", notebook_stem=notebook_stem, notebook_kind=notebook_kind, artifact_lookup=artifact_lookup
        ),
        "evidence_figures": _agent_session_figure_artifacts(artifacts),
    }


def _empty_agent_session_notebook_artifacts() -> dict[str, Any]:
    return {
        "manifest": None,
        "report_artifact": None,
        "figure_manifest": None,
        "evidence_bundle": None,
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
            "artifact_registration_required": True,
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
            "Register every useful output as Tablex artifacts and preserve EvaluationSpec, SplitManifest, and credential boundaries."
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
            "Register figure manifests, reports, metrics, and updated marimo notebooks as artifacts.",
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
            "description": "Narrative report covering findings, caveats, runtime assumptions, and recommended follow-up.",
        },
        {
            "path": "artifacts/notebook_execution_manifest.json",
            "schema": "notebook_execution_manifest.v1",
            "description": "Runtime package versions, checked cells, generated outputs, and safety policy result.",
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


def _notebook_recommendation_score(
    notebook_kind: str,
    coverage: dict[str, Any],
    metadata: dict[str, Any],
    content: dict[str, Any],
) -> int:
    score = 20
    if coverage.get("native_marimo_status") == "runtime_error":
        score -= 120
    if notebook_kind in {"model_diagnostics", "model_comparison"}:
        score += 10
    if notebook_kind == "data_understanding":
        score += 35
    if notebook_kind == "solution_writeup":
        score += 30
    if coverage.get("has_report"):
        score += 10
    if coverage.get("has_visualization"):
        score += 10
    if coverage.get("has_execution_plan"):
        score += 6
    if metadata.get("run_id"):
        score += 8
    if coverage.get("execution_status") == "generated_not_executed":
        score += 2
    readiness = str(content.get("readiness") or "unknown")
    quality_score = int(content.get("quality_score") or 0)
    if notebook_kind in {"model_diagnostics", "model_comparison"}:
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


def _notebook_index_display_sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
    status = str(item.get("status") or "")
    coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
    needs_attention = status == "needs_attention" or coverage.get("native_marimo_status") == "runtime_error"
    return (
        1 if needs_attention else 0,
        -int(item.get("recommendation_score") or 0),
        -iso_datetime_timestamp(item.get("created_at")),
    )


def iso_datetime_timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


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
                "latest_created_at": max(str(item["created_at"]) for item in group_items),
                "items": group_items,
            }
        )
    return groups


def _notebook_index_next_actions(
    project: Project,
    items: list[dict[str, Any]],
    *,
    recommended: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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
    if not actions:
        actions.append(
            {
                "label": "Open the recommended marimo notebook",
                "endpoint": None,
                "reason": "The notebook index already has project notebooks; open the source through native marimo.",
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
    notebook_quality_issue: bool,
) -> list[str]:
    caveats: list[str] = []
    if notebook_quality_issue:
        caveats.append("This notebook is linked directly, but its metric or prediction evidence is incomplete and should be repaired.")
    profile_boundary = str(brief.get("profile_boundary") or "").strip()
    if profile_boundary:
        caveats.append(profile_boundary)
    caveats.extend(_string_list(brief.get("top_risks"))[:3])
    caveats.append("Notebook source is linked; runtime issues should surface when native marimo opens it.")
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
            "title": "Notebook source",
            "status": "ready",
            "signal": f"{len(figure_artifacts)} figure(s)",
            "why_read": "Open the source artifact through native marimo; supporting figures remain secondary evidence.",
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
) -> dict[str, Any]:
    return {
        "label": "Open notebook",
        "action_type": "open_native_marimo",
        "artifact_id": str(selected_item["notebook_artifact_id"]),
        "target_tab": "Notebooks",
    }


def _story_raw_artifact_refs(
    db: Session,
    project_id: str,
    notebook_artifact: Artifact,
    linked_artifact_ids: dict[str, Any],
    evidence_figures: list[Artifact],
) -> list[dict[str, Any]]:
    artifacts: list[Artifact] = [notebook_artifact]
    for artifact_id in linked_artifact_ids.values():
        if not isinstance(artifact_id, str):
            continue
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None and artifact.project_id == project_id:
            artifacts.append(artifact)
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


def _notebook_display_title(
    notebook_kind: str,
    metadata: dict[str, Any],
    quality_manifest: dict[str, Any] | None,
) -> str:
    metadata_title = _first_text_value(metadata.get("title"), metadata.get("display_name"), metadata.get("label"))
    if metadata_title is not None:
        return metadata_title
    if isinstance(quality_manifest, dict):
        purpose = _first_text_value(quality_manifest.get("notebook_purpose"), quality_manifest.get("visual_summary"))
        if purpose is not None:
            return purpose
        read_order = quality_manifest.get("read_order")
        if isinstance(read_order, list):
            for item in read_order:
                if isinstance(item, dict):
                    label = _first_text_value(item.get("label"), item.get("section"), item.get("title"))
                    if label is not None:
                        return label
                elif isinstance(item, str) and item.strip():
                    return item.strip()
    return _notebook_title(notebook_kind)


def _notebook_title(notebook_kind: str) -> str:
    if notebook_kind == "model_diagnostics":
        return "Model Diagnostics Notebook"
    if notebook_kind == "model_comparison":
        return "Model Comparison Notebook"
    if notebook_kind == "data_understanding":
        return "Data Understanding Notebook"
    if notebook_kind == "solution_writeup":
        return "Solution Writeup"
    return "Analysis Notebook"


def _notebook_recommendation_reason(notebook_kind: str, coverage: dict[str, Any], content: dict[str, Any]) -> str:
    readiness = str(content.get("readiness") or "unknown")
    if coverage.get("native_marimo_status") == "runtime_error":
        return "This notebook source is registered, but native marimo reported a runtime error. Repair it before treating it as the primary read."
    if notebook_kind == "model_diagnostics" and readiness == "not_ready":
        return "Model diagnostics exists, but it is not useful yet because metric, prediction, or diagnostic evidence is missing."
    if notebook_kind == "model_diagnostics" and readiness == "partial_review":
        return "Use only as a diagnostics coverage check; fill missing prediction or diagnostic evidence before model claims."
    if notebook_kind == "model_diagnostics" and readiness == "evidence_ready":
        return "Evidence-rich model review: metrics, prediction coverage, and diagnostics are available enough for a first read."
    if notebook_kind == "data_understanding" and readiness in {"evidence_ready", "narrative_ready"}:
        return "Best starting point: Data Understanding has narrative, story cards, playbook, and evidence figures."
    if notebook_kind == "data_understanding":
        return "Best starting point before target, evaluation, or feature decisions."
    return "Notebook source exists and should open through native marimo."


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
    story_cards = _list_value(visual_story.get("cards")) if isinstance(visual_story, dict) else _list_value(visual_story)
    figure_count = max(len(bundle_figures), len(evidence_figure_artifacts), 1 if figure_manifest_artifact is not None else 0)
    quality_score = min(
        100,
        int(current.get("quality_score") or 0)
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
    if locale_is_japanese(locale):
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
            "no_guardrails": "このノートブックでは追加のガードレールは検出されていません。",
            "no_columns": "カラムプロファイルはまだ利用できません。",
            "no_findings": "このノートブックでは追加の発見は検出されていません。",
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
        "no_guardrails": "No additional guardrails were detected in this notebook.",
        "no_columns": "No profile columns are available yet.",
        "no_findings": "No additional findings were detected in this notebook.",
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
    if locale_is_japanese(locale):
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


def _execution_policy() -> dict[str, Any]:
    return {
        "external_dashboard_required": False,
        "external_network_accessed": False,
        "connector_credentials_embedded": False,
        "secrets_embedded": False,
        "notebook_execution": "not_executed_by_generation_endpoint",
        "artifact_registration_required": True,
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


def _float_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
