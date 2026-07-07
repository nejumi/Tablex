from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Artifact, DatasetSnapshot, ExperimentRun, ModelVersion, Project
from tabular_harness.services.agent_notebook_quality import (
    NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION,
    NotebookToolValidationError,
    assert_human_facing_notebook_quality,
    normalize_notebook_quality_manifest,
    notebook_quality_feedback_from_manifest,
    notebook_quality_feedback_from_metadata,
    notebook_source_validation_issues,
)
from tabular_harness.services.agent_requests.pipelines import require_string_list
from tabular_harness.services.analysis_notebooks import marimo_notebook_source_validation_for_artifact
from tabular_harness.services.research_plans import research_plan_artifact_is_native_marimo_source

ResolveWorkspaceArtifact = Callable[..., Artifact | None]


def notebook_registration_chat_status(notebook_artifact: Artifact) -> str:
    quality = notebook_quality_feedback_from_metadata(notebook_artifact)
    quality_status = str(quality.get("status") or "")
    if quality_status.startswith("needs_"):
        return "quality_needs_attention"
    return "source_saved"


def notebook_registration_visible_surfaces(
    *,
    notebook_artifact: Artifact,
    chat_artifact_id: str | None,
    linked_plan_node_id: str | None,
    dataset_snapshot_id: str | None,
    run_id: str | None,
    model_version_id: str | None,
    related_run_ids: list[str] | None = None,
) -> dict[str, Any]:
    surfaces: dict[str, Any] = {
        "notebooks": {
            "target_tab": "Notebooks",
            "target_anchor": "notebook-native-marimo-top",
            "artifact_id": notebook_artifact.id,
        },
        "assets": {
            "target_tab": "Assets",
            "target_anchor": "asset-notebooks",
            "artifact_id": notebook_artifact.id,
        },
        "research_plan": {
            "target_tab": "Home",
            "target_anchor": "research-plan",
            "node_id": linked_plan_node_id,
            "artifact_id": notebook_artifact.id,
        },
        "chat": {
            "target_tab": "Home",
            "target_anchor": "agent-workspace",
            "artifact_id": chat_artifact_id,
        },
    }
    if dataset_snapshot_id:
        surfaces["data"] = {
            "target_tab": "Data",
            "target_anchor": "data-focus",
            "dataset_snapshot_id": dataset_snapshot_id,
            "artifact_id": notebook_artifact.id,
        }
    visible_run_ids = [run_id] if run_id else []
    for related_run_id in related_run_ids or []:
        if related_run_id and related_run_id not in visible_run_ids:
            visible_run_ids.append(related_run_id)
    if run_id or model_version_id or visible_run_ids:
        surfaces["leaderboard"] = {
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "run_id": run_id,
            "run_ids": visible_run_ids,
            "model_version_id": model_version_id,
            "artifact_id": notebook_artifact.id,
        }
    return surfaces


def apply_notebook_request_metadata(
    db: Session,
    *,
    project: Project,
    notebook_artifact: Artifact,
    payload: dict[str, Any],
) -> dict[str, Any]:
    notebook_title = optional_text_field(payload, "title")
    notebook_kind = optional_text_field(payload, "notebook_kind")
    dataset_snapshot_id = optional_text_field(payload, "dataset_snapshot_id")
    run_id = optional_text_field(payload, "run_id")
    related_run_ids = require_string_list(payload.get("related_run_ids"), "payload.related_run_ids")
    model_version_id = optional_text_field(payload, "model_version_id")
    research_plan_node_id = optional_text_field(payload, "research_plan_node_id")
    run: ExperimentRun | None = None
    model_version: ModelVersion | None = None
    dataset_snapshot: DatasetSnapshot | None = None
    metadata = loads_json(notebook_artifact.metadata_json, {})

    if run_id:
        run = db.get(ExperimentRun, run_id)
        if run is None or run.project_id != project.id:
            raise ValueError(f"payload.run_id `{run_id}` does not belong to this project")
        if model_version_id and run.model_version_id and run.model_version_id != model_version_id:
            raise ValueError("payload.run_id and payload.model_version_id refer to different model results")
        if dataset_snapshot_id and run.dataset_snapshot_id and run.dataset_snapshot_id != dataset_snapshot_id:
            raise ValueError("payload.run_id and payload.dataset_snapshot_id refer to different datasets")
        model_version_id = model_version_id or run.model_version_id
        dataset_snapshot_id = dataset_snapshot_id or run.dataset_snapshot_id

    if model_version_id:
        model_version = db.get(ModelVersion, model_version_id)
        if model_version is None or model_version.project_id != project.id:
            raise ValueError(f"payload.model_version_id `{model_version_id}` does not belong to this project")
        if run_id and model_version.experiment_run_id != run_id:
            raise ValueError("payload.model_version_id and payload.run_id refer to different experiment runs")
        run_id = run_id or model_version.experiment_run_id
        dataset_snapshot_id = dataset_snapshot_id or model_version.dataset_snapshot_id

    if dataset_snapshot_id:
        dataset_snapshot = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset_snapshot is None or dataset_snapshot.project_id != project.id:
            raise ValueError(f"payload.dataset_snapshot_id `{dataset_snapshot_id}` does not belong to this project")
        if model_version and model_version.dataset_snapshot_id and model_version.dataset_snapshot_id != dataset_snapshot.id:
            raise ValueError("payload.model_version_id and payload.dataset_snapshot_id refer to different datasets")
        if run and run.dataset_snapshot_id and run.dataset_snapshot_id != dataset_snapshot.id:
            raise ValueError("payload.run_id and payload.dataset_snapshot_id refer to different datasets")

    validated_related_run_ids: list[str] = []
    for related_run_id in related_run_ids:
        related_run = db.get(ExperimentRun, related_run_id)
        if related_run is None or related_run.project_id != project.id:
            raise ValueError(f"payload.related_run_ids contains run id `{related_run_id}` that does not belong to this project")
        if dataset_snapshot_id and related_run.dataset_snapshot_id and related_run.dataset_snapshot_id != dataset_snapshot_id:
            raise ValueError("payload.related_run_ids contains runs from a different dataset")
        if related_run_id not in validated_related_run_ids:
            validated_related_run_ids.append(related_run_id)
        dataset_snapshot_id = dataset_snapshot_id or related_run.dataset_snapshot_id

    existing_linked_run_ids: list[str] = []
    existing_run_ids = notebook_metadata_existing_run_ids(metadata)
    for existing_run_id in existing_run_ids:
        existing_run = db.get(ExperimentRun, existing_run_id)
        if existing_run is None or existing_run.project_id != project.id:
            continue
        if dataset_snapshot_id and existing_run.dataset_snapshot_id and existing_run.dataset_snapshot_id != dataset_snapshot_id:
            raise ValueError("Existing notebook run links and payload run links refer to different datasets")
        dataset_snapshot_id = dataset_snapshot_id or existing_run.dataset_snapshot_id
        if existing_run_id not in existing_linked_run_ids:
            existing_linked_run_ids.append(existing_run_id)

    linked_run_ids = unique_texts([*existing_linked_run_ids, *([run_id] if run_id else []), *validated_related_run_ids])
    if len(linked_run_ids) > 1 or related_run_ids:
        validated_related_run_ids = linked_run_ids
        run_id = None
        model_version_id = None

    updates = {
        "title": notebook_title,
        "notebook_kind": notebook_kind,
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
        "research_plan_node_id": research_plan_node_id,
        "notebook_context_source": "tablex_notebook_request",
    }
    for key, value in updates.items():
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    if validated_related_run_ids:
        metadata["related_run_ids"] = validated_related_run_ids
        metadata.pop("run_id", None)
        metadata.pop("model_version_id", None)
    else:
        metadata.pop("related_run_ids", None)
    quality_manifest = normalize_notebook_quality_manifest(payload.get("quality_manifest"))
    assert_human_facing_notebook_quality(
        notebook_artifact=notebook_artifact,
        notebook_kind=notebook_kind,
        quality_manifest=quality_manifest,
    )
    if quality_manifest is not None:
        quality_feedback = notebook_quality_feedback_from_manifest(quality_manifest)
        metadata["notebook_quality_manifest"] = quality_manifest
        metadata["notebook_quality_status"] = quality_feedback["status"]
        metadata["notebook_quality_message"] = quality_feedback.get("message")
        metadata["notebook_quality_schema_version"] = NOTEBOOK_QUALITY_MANIFEST_SCHEMA_VERSION
        metadata["figure_count"] = quality_manifest.get("figure_count", 0)
        metadata["table_count"] = quality_manifest.get("table_count", 0)
        metadata["key_finding_count"] = len(quality_manifest.get("key_findings", []))
    else:
        metadata.setdefault("notebook_quality_status", "needs_manifest")
    notebook_artifact.metadata_json = dumps_json(metadata)
    return {
        "notebook_kind": str(metadata.get("notebook_kind") or "") or None,
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
        "related_run_ids": validated_related_run_ids,
    }


def notebook_artifact_from_request(
    db: Session,
    *,
    project: Project,
    workspace: Path,
    payload: dict[str, Any],
    resolve_workspace_artifact_fn: ResolveWorkspaceArtifact,
) -> Artifact:
    artifact_id = payload.get("artifact_id")
    artifact: Artifact | None = None
    if isinstance(artifact_id, str) and artifact_id.strip():
        artifact = db.get(Artifact, artifact_id.strip())
    else:
        workspace_path = payload.get("workspace_path")
        if not isinstance(workspace_path, str) or not workspace_path.strip():
            raise ValueError("payload.artifact_id or payload.workspace_path is required")
        artifact = resolve_workspace_artifact_fn(
            db,
            project_id=project.id,
            workspace=workspace,
            workspace_path=workspace_path,
        )
    if artifact is None or artifact.project_id != project.id:
        raise ValueError("Notebook artifact does not belong to this project or is not registered yet")
    if artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        raise ValueError(f"Referenced artifact must be a native marimo notebook source, not {artifact.asset_type}")
    if not research_plan_artifact_is_native_marimo_source(artifact):
        raise ValueError("Referenced notebook artifact is not a native marimo Python source")
    validation = marimo_notebook_source_validation_for_artifact(artifact)
    if validation.get("is_valid_marimo_notebook") is not True:
        errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
        message = "; ".join(str(item) for item in errors if str(item).strip())
        raise NotebookToolValidationError(
            "Referenced notebook artifact is not a valid native marimo source"
            + (f": {message}" if message else "."),
            issues=notebook_source_validation_issues(validation),
        )
    return artifact


def notebook_metadata_existing_run_ids(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    run_id = metadata.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        values.append(run_id.strip())
    related = metadata.get("related_run_ids")
    if isinstance(related, list):
        values.extend(item.strip() for item in related if isinstance(item, str) and item.strip())
    return unique_texts(values)


def unique_texts(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def optional_text_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"payload.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None
