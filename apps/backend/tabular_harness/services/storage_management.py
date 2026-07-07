from __future__ import annotations

import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    LineageEdge,
    ModelVersion,
    PilotDeployment,
    PilotOutcomeBatch,
    PilotPredictionBatch,
    ResearchPlanRevision,
    SplitManifest,
)

PROTECTED_ASSET_TYPES = {
    "dataset_snapshot",
    "evaluation_spec",
    "split_manifest",
    "prediction_pipeline",
}

DATASET_ASSET_TYPES = {
    "dataset_snapshot",
    "uploaded_supporting_table",
    "uploaded_table",
    "benchmark_dataset",
}


def storage_usage_report(settings: Settings, db: Session) -> dict[str, Any]:
    artifact_root = settings.artifact_root.resolve()
    data_dir = settings.data_dir.resolve()
    artifact_workspace_path = artifact_root / "agent_sessions"
    local_workspace_path = data_dir / "_workspaces"
    pipeline_envs_path = data_dir / "_pipeline_envs"
    marimo_path = data_dir / "marimo_sessions"
    db_path = data_dir / "metadata"
    dataset_bytes = artifact_bytes_for_asset_types(db, DATASET_ASSET_TYPES)
    artifact_workspace_bytes = directory_size(artifact_workspace_path)
    local_workspace_bytes = directory_size(local_workspace_path)
    workspace_bytes = artifact_workspace_bytes + local_workspace_bytes
    pipeline_envs_bytes = directory_size(pipeline_envs_path)
    marimo_bytes = directory_size(marimo_path)
    db_bytes = directory_size(db_path)
    artifact_root_bytes = directory_size(artifact_root)
    artifacts_bytes = max(0, artifact_root_bytes - artifact_workspace_bytes - dataset_bytes)
    categories = {
        "datasets": dataset_bytes,
        "artifacts": artifacts_bytes,
        "workspaces": workspace_bytes,
        "pipeline_envs": pipeline_envs_bytes,
        "marimo": marimo_bytes,
        "db": db_bytes,
    }
    return {
        "schema_version": "storage_usage.v1",
        "data_dir": str(data_dir),
        "artifact_root": str(artifact_root),
        "total_bytes": directory_size(data_dir),
        "categories": categories,
    }


def cleanup_temporary_storage(
    *,
    settings: Settings,
    now: datetime | None = None,
    pipeline_env_ttl_days: int = 14,
    marimo_workdir_ttl_days: int = 7,
    ack_ttl_days: int = 90,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    pipeline_envs = remove_old_children(
        settings.data_dir / "_pipeline_envs",
        older_than=current - timedelta(days=pipeline_env_ttl_days),
    )
    marimo_workdirs = remove_old_children(
        settings.data_dir / "marimo_sessions",
        older_than=current - timedelta(days=marimo_workdir_ttl_days),
    )
    ack_files = remove_old_files(
        settings.artifact_root / "agent_sessions",
        pattern=".tablex/acks/**/*.json",
        older_than=current - timedelta(days=ack_ttl_days),
    )
    return {
        "schema_version": "temporary_storage_cleanup.v1",
        "pipeline_envs_removed": pipeline_envs,
        "marimo_workdirs_removed": marimo_workdirs,
        "ack_files_removed": ack_files,
    }


def artifact_gc_plan(
    db: Session,
    *,
    settings: Settings,
    dry_run: bool = True,
    retention: int | None = None,
) -> dict[str, Any]:
    keep_versions = max(1, int(retention if retention is not None else settings.artifact_version_retention))
    protected_ids = protected_artifact_ids(db)
    artifacts = list(
        db.scalars(
            select(Artifact).order_by(
                Artifact.project_id,
                Artifact.asset_type,
                Artifact.name,
                Artifact.version.desc(),
            )
        ).all()
    )
    groups: dict[tuple[str | None, str, str], list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        groups[(artifact.project_id, artifact.asset_type, artifact.name)].append(artifact)

    candidates: list[dict[str, Any]] = []
    protected_count = 0
    deleted_count = 0
    for group_artifacts in groups.values():
        for artifact in sorted(group_artifacts, key=lambda item: item.version, reverse=True)[:keep_versions]:
            if artifact.id in protected_ids or artifact.asset_type in PROTECTED_ASSET_TYPES:
                protected_count += 1
        for artifact in sorted(group_artifacts, key=lambda item: item.version, reverse=True)[keep_versions:]:
            reason = protected_reason(artifact, protected_ids)
            if reason is not None:
                protected_count += 1
                continue
            uri = Path(artifact.uri)
            size_bytes = artifact_storage_bytes(artifact)
            candidate = {
                "artifact_id": artifact.id,
                "project_id": artifact.project_id,
                "asset_type": artifact.asset_type,
                "name": artifact.name,
                "version": artifact.version,
                "content_hash": artifact.content_hash,
                "uri": str(uri),
                "size_bytes": size_bytes,
                "reason": f"older_than_retention_{keep_versions}",
            }
            if not dry_run and uri.exists():
                shutil.rmtree(uri, ignore_errors=True)
                candidate["deleted"] = True
                deleted_count += 1
            candidates.append(candidate)

    reclaimable_bytes = sum(int(item.get("size_bytes") or 0) for item in candidates)
    return {
        "schema_version": "artifact_gc_plan.v1",
        "dry_run": dry_run,
        "retention": keep_versions,
        "candidate_count": len(candidates),
        "protected_count": protected_count,
        "deleted_count": deleted_count,
        "reclaimable_bytes": reclaimable_bytes,
        "candidates": candidates,
    }


def protected_artifact_ids(db: Session) -> set[str]:
    protected: set[str] = set()
    protected.update(
        artifact.id for artifact in db.scalars(select(Artifact).where(Artifact.asset_type.in_(PROTECTED_ASSET_TYPES)))
    )
    protected.update(
        artifact_id
        for artifact_id in db.scalars(select(DatasetSnapshot.artifact_id))
        if isinstance(artifact_id, str) and artifact_id
    )
    protected.update(
        artifact_id
        for artifact_id in db.scalars(select(SplitManifest.artifact_id))
        if isinstance(artifact_id, str) and artifact_id
    )
    protected.update(
        artifact_id
        for artifact_id in db.scalars(select(ModelVersion.artifact_id))
        if isinstance(artifact_id, str) and artifact_id
    )
    protected.update(
        artifact_id
        for artifact_id in db.scalars(select(PilotDeployment.pipeline_artifact_id))
        if isinstance(artifact_id, str) and artifact_id
    )
    for input_artifact_id, predictions_artifact_id in db.execute(
        select(PilotPredictionBatch.input_artifact_id, PilotPredictionBatch.predictions_artifact_id)
    ):
        protected.update(value for value in (input_artifact_id, predictions_artifact_id) if isinstance(value, str) and value)
    protected.update(
        artifact_id
        for artifact_id in db.scalars(select(PilotOutcomeBatch.outcomes_artifact_id))
        if isinstance(artifact_id, str) and artifact_id
    )
    for from_type, from_id, to_type, to_id in db.execute(
        select(
            LineageEdge.from_asset_type,
            LineageEdge.from_asset_id,
            LineageEdge.to_asset_type,
            LineageEdge.to_asset_id,
        )
    ):
        if from_type == "artifact" and isinstance(from_id, str) and from_id:
            protected.add(from_id)
        if to_type == "artifact" and isinstance(to_id, str) and to_id:
            protected.add(to_id)
    artifact_ids = set(db.scalars(select(Artifact.id)).all())
    for document_json in db.scalars(select(ResearchPlanRevision.document_json)):
        if not isinstance(document_json, str) or not document_json:
            continue
        for artifact_id in artifact_ids:
            if artifact_id in document_json:
                protected.add(artifact_id)
    return protected


def protected_reason(artifact: Artifact, protected_ids: set[str]) -> str | None:
    if artifact.asset_type in PROTECTED_ASSET_TYPES:
        return "protected_asset_type"
    if artifact.id in protected_ids:
        return "referenced_by_lineage_plan_model_or_pilot"
    return None


def artifact_bytes_for_asset_types(db: Session, asset_types: set[str]) -> int:
    total = 0
    for artifact in db.scalars(select(Artifact).where(Artifact.asset_type.in_(asset_types))):
        total += artifact_storage_bytes(artifact)
    return total


def artifact_storage_bytes(artifact: Artifact) -> int:
    try:
        return directory_size(Path(artifact.uri))
    except OSError:
        return 0


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def remove_old_children(path: Path, *, older_than: datetime) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    removed = 0
    for child in path.iterdir():
        try:
            modified_at = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified_at >= older_than:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                continue
        removed += 1
    return removed


def remove_old_files(root: Path, *, pattern: str, older_than: datetime) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in root.glob(f"**/{pattern}"):
        if not path.is_file():
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified_at >= older_than:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed
