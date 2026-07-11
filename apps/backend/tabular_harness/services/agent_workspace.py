from __future__ import annotations

import csv
import importlib.metadata as importlib_metadata
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import get_settings
from tabular_harness.core.json import loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    Asset,
    AssetReference,
    AssetVersion,
    DatasetSnapshot,
    Job,
    Project,
    ResearchPlanRevision,
    User,
    utc_now,
)
from tabular_harness.services.agent_prompting import session_protocol_text
from tabular_harness.services.agent_requests.data import (
    DATA_REQUEST_SCHEMA_VERSION,
    TASK_SPEC_SCHEMA_VERSION,
    data_acks_dir,
    data_requests_dir,
)
from tabular_harness.services.agent_requests.deliverables import (
    DELIVERABLE_REQUEST_SCHEMA_VERSION,
    deliverable_acks_dir,
    deliverable_requests_dir,
)
from tabular_harness.services.agent_requests.evaluation import (
    EVALUATION_REQUEST_SCHEMA_VERSION,
    evaluation_acks_dir,
    evaluation_requests_dir,
)
from tabular_harness.services.agent_requests.model_diagnostics import (
    MODEL_DIAGNOSTIC_CHECK_NAMES,
    MODEL_DIAGNOSTIC_CHECK_STATUSES,
    MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION,
    model_diagnostics_acks_dir,
    model_diagnostics_requests_dir,
)
from tabular_harness.services.agent_requests.notebooks import (
    NOTEBOOK_REQUEST_SCHEMA_VERSION,
    notebook_acks_dir,
    notebook_requests_dir,
)
from tabular_harness.services.agent_requests.pilot import (
    PILOT_REQUEST_SCHEMA_VERSION,
    pilot_acks_dir,
    pilot_requests_dir,
)
from tabular_harness.services.agent_requests.pipelines import (
    PIPELINE_REQUEST_SCHEMA_VERSION,
    pipeline_acks_dir,
    pipeline_requests_dir,
)
from tabular_harness.services.agent_requests.research import (
    RESEARCH_REQUEST_SCHEMA_VERSION,
    research_acks_dir,
    research_requests_dir,
)
from tabular_harness.services.agent_requests.research_plan import (
    research_plan_acks_dir,
    research_plan_requests_dir,
)
from tabular_harness.services.agent_session_results import (
    experiment_acks_dir,
    experiment_requests_dir,
)
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path
from tabular_harness.services.research_plan_timeline import (
    research_plan_contract_validation_summary,
)
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    commit_research_plan_artifact_revision,
    ensure_harness_initial_research_plan_revision,
    latest_research_plan_revision,
    research_plan_revision_document,
)

SESSION_INTERNAL_DIR = ".tablex"
SESSION_INBOX_DIR = "inbox"
SESSION_BIN_DIR = "bin"
SESSION_CACHE_DIR = "cache"
SESSION_DATA_DIR = "data"
SESSION_DATASET_PROFILE_CACHE_DIR = "dataset_profiles"
SESSION_DATASET_SAMPLE_CACHE_DIR = "dataset_samples"
SESSION_DATA_MANIFEST_FILENAME = "data_manifest.json"
SESSION_PROTOCOL_FILENAME = "PROTOCOL.md"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
CODEX_RAW_TRANSCRIPT_FILENAME = "codex_raw_transcript.jsonl"
CODEX_STDERR_LOG_FILENAME = "codex_stderr.log"


def session_workspace_path(store: LocalArtifactStore, project_id: str, session_id: str) -> Path:
    return store.root / "agent_sessions" / project_id / session_id


def raw_codex_transcript_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / CODEX_RAW_TRANSCRIPT_FILENAME


def raw_codex_stderr_path(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / CODEX_STDERR_LOG_FILENAME


def prepare_session_workspace(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> Path:
    stored_workspace = Path(session.workspace_path or session_workspace_path(store, project.id, session.id))
    workspace = resolve_runtime_data_path(stored_workspace)
    if not session.workspace_path:
        session.workspace_path = str(stored_workspace)
    (workspace / ".tablex").mkdir(parents=True, exist_ok=True)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    (workspace / "notebooks").mkdir(parents=True, exist_ok=True)
    (workspace / "artifacts").mkdir(parents=True, exist_ok=True)
    (workspace / SESSION_INTERNAL_DIR / SESSION_INBOX_DIR).mkdir(parents=True, exist_ok=True)
    ensure_session_python_shims(workspace)
    research_plan_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    research_plan_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    research_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    research_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    data_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    data_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    evaluation_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    evaluation_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    pipeline_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    pipeline_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    pilot_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    pilot_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    deliverable_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    deliverable_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    model_diagnostics_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    model_diagnostics_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    notebook_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    notebook_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    experiment_requests_dir(workspace).mkdir(parents=True, exist_ok=True)
    experiment_acks_dir(workspace).mkdir(parents=True, exist_ok=True)
    write_session_context_file(db, project=project, session=session)
    (workspace / ".tablex" / "GOAL.md").write_text(session.goal_text, encoding="utf-8")
    (workspace / SESSION_INTERNAL_DIR / SESSION_PROTOCOL_FILENAME).write_text(session_protocol_text(), encoding="utf-8")
    return workspace


def ensure_session_python_shims(workspace: Path) -> None:
    bin_dir = workspace / SESSION_INTERNAL_DIR / SESSION_BIN_DIR
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for name in ("python", "python3"):
        target = bin_dir / name
        script = f"#!/usr/bin/env sh\nexec {json.dumps(sys.executable)} \"$@\"\n"
        try:
            if target.exists() or target.is_symlink():
                target.unlink()
            target.write_text(script, encoding="utf-8")
            target.chmod(0o755)
        except OSError:
            continue


def ensure_session_dataset_links(db: Session, *, workspace: Path, project_id: str) -> list[dict[str, Any]]:
    data_dir = workspace / SESSION_INTERNAL_DIR / SESSION_DATA_DIR
    cache_dir = workspace / SESSION_INTERNAL_DIR / SESSION_CACHE_DIR
    sample_cache_dir = cache_dir / SESSION_DATASET_SAMPLE_CACHE_DIR
    profile_cache_dir = cache_dir / SESSION_DATASET_PROFILE_CACHE_DIR
    settings = get_settings()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        sample_cache_dir.mkdir(parents=True, exist_ok=True)
        profile_cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc()).limit(24)
        ).all()
    )
    manifest: list[dict[str, Any]] = []
    used_names: set[str] = set()
    profile_artifacts_by_dataset_id = latest_profile_artifacts_by_dataset_id(db, project_id=project_id)
    for dataset in datasets:
        artifact = db.get(Artifact, dataset.artifact_id) if dataset.artifact_id else None
        if artifact is None:
            continue
        try:
            source_path = artifact_primary_path(artifact).resolve()
        except (OSError, KeyError, IndexError, json.JSONDecodeError):
            continue
        if not source_path.exists() or not source_path.is_file():
            continue
        source_name = Path(dataset.source_ref or source_path.name).name or source_path.name
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name).strip("._") or source_path.name
        base_link_name = f"{dataset.id}__{safe_name}"
        link_name = base_link_name
        duplicate_index = 2
        while link_name in used_names:
            link_name = f"{base_link_name}.{duplicate_index}"
            duplicate_index += 1
        used_names.add(link_name)
        target = data_dir / link_name
        materialization = "symlink"
        try:
            if target.exists() or target.is_symlink():
                target.unlink()
            if not target.exists() and not target.is_symlink():
                target.symlink_to(source_path)
        except OSError:
            try:
                if source_path.stat().st_size > settings.notebook_data_copy_max_bytes:
                    continue
                if target.exists() or target.is_symlink():
                    target.unlink()
                shutil.copy2(source_path, target)
                materialization = "copy"
            except OSError:
                continue
        fast_paths = materialize_dataset_fast_paths(
            workspace=workspace,
            dataset=dataset,
            profile_artifact=profile_artifacts_by_dataset_id.get(dataset.id),
            sample_cache_dir=sample_cache_dir,
            profile_cache_dir=profile_cache_dir,
        )
        manifest.append(
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_id": artifact.id,
                "source_ref": dataset.source_ref,
                "row_count": dataset.row_count,
                "column_count": dataset.column_count,
                "workspace_path": str(target),
                "workspace_relative_path": str(target.relative_to(workspace)),
                "source_artifact_path": str(source_path),
                "materialization": materialization,
                "fast_paths": fast_paths,
                "notebook_load_strategy": (
                    "Use fast_paths.profile_json and fast_paths.sample_rows_json/sample_rows_csv for native marimo "
                    "initial rendering. Use workspace_relative_path for deliberate full-data scans or model training."
                ),
            }
        )
    manifest_path = workspace / SESSION_INTERNAL_DIR / SESSION_DATA_MANIFEST_FILENAME
    try:
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "tablex_session_data_manifest.v1",
                    "root": f"{SESSION_INTERNAL_DIR}/{SESSION_DATA_DIR}",
                    "cache_root": f"{SESSION_INTERNAL_DIR}/{SESSION_CACHE_DIR}",
                    "guarantee": (
                        "These paths are relative to the AgentSession workspace and are readable from registered "
                        "marimo notebooks when Tablex starts the native marimo runtime."
                    ),
                    "notebook_load_strategy": (
                        "Prefer per-dataset fast_paths for the first native marimo render. They contain cached profile "
                        "and deterministic sample rows from registered Tablex artifacts. Read full data only when the "
                        "notebook needs a full scan."
                    ),
                    "datasets": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return manifest


def latest_profile_artifacts_by_dataset_id(db: Session, *, project_id: str) -> dict[str, Artifact]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "eda_profile")
            .order_by(Artifact.created_at.desc())
            .limit(200)
        ).all()
    )
    by_dataset_id: dict[str, Artifact] = {}
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        dataset_id = metadata.get("dataset_snapshot_id")
        if isinstance(dataset_id, str) and dataset_id.strip() and dataset_id not in by_dataset_id:
            by_dataset_id[dataset_id] = artifact
    return by_dataset_id


def materialize_dataset_fast_paths(
    *,
    workspace: Path,
    dataset: DatasetSnapshot,
    profile_artifact: Artifact | None,
    sample_cache_dir: Path,
    profile_cache_dir: Path,
) -> dict[str, Any]:
    if profile_artifact is None:
        return {}
    try:
        profile_path = artifact_primary_path(profile_artifact).resolve()
        profile = loads_json(profile_path.read_text(encoding="utf-8"), {})
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return {}
    if not isinstance(profile, dict):
        return {}

    fast_paths: dict[str, Any] = {
        "profile_artifact_id": profile_artifact.id,
        "profile_mode": profile.get("profile_mode"),
        "column_stat_scope": profile.get("column_stat_scope"),
    }
    profile_cache_path = profile_cache_dir / f"{dataset.id}__profile.json"
    if write_text_if_changed(profile_cache_path, json.dumps(profile, ensure_ascii=False, indent=2) + "\n"):
        fast_paths["profile_json"] = str(profile_cache_path.relative_to(workspace))

    sample_rows = profile.get("sample_rows")
    if isinstance(sample_rows, list) and sample_rows:
        rows = [row for row in sample_rows if isinstance(row, dict)]
        if rows:
            sample_json_path = sample_cache_dir / f"{dataset.id}__sample_rows.json"
            sample_csv_path = sample_cache_dir / f"{dataset.id}__sample_rows.csv"
            sample_payload = {
                "schema_version": "tablex_dataset_sample_rows.v1",
                "dataset_snapshot_id": dataset.id,
                "profile_artifact_id": profile_artifact.id,
                "row_count": len(rows),
                "rows": rows,
            }
            if write_text_if_changed(sample_json_path, json.dumps(sample_payload, ensure_ascii=False, indent=2) + "\n"):
                fast_paths["sample_rows_json"] = str(sample_json_path.relative_to(workspace))
            if write_sample_rows_csv(sample_csv_path, rows):
                fast_paths["sample_rows_csv"] = str(sample_csv_path.relative_to(workspace))
            fast_paths["sample_row_count"] = len(rows)
    return fast_paths


def write_text_if_changed(path: Path, text: str) -> bool:
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except OSError:
        return False


def write_sample_rows_csv(path: Path, rows: list[dict[str, Any]]) -> bool:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in columns})
        return True
    except OSError:
        return False


def python_runtime_context(workspace: Path) -> dict[str, Any]:
    workspace_python = workspace / SESSION_INTERNAL_DIR / SESSION_BIN_DIR / "python"
    packages = {
        "marimo": package_version_or_none("marimo"),
        "pandas": package_version_or_none("pandas"),
        "numpy": package_version_or_none("numpy"),
        "scikit_learn": package_version_or_none("scikit-learn"),
        "matplotlib": package_version_or_none("matplotlib"),
        "japanize_matplotlib": package_version_or_none("japanize-matplotlib"),
        "plotly": package_version_or_none("plotly"),
        "duckdb": package_version_or_none("duckdb"),
        "polars": package_version_or_none("polars"),
        "xgboost": package_version_or_none("xgboost"),
        "lightgbm": package_version_or_none("lightgbm"),
        "catboost": package_version_or_none("catboost"),
        "tabpfn": package_version_or_none("tabpfn"),
        "torch": package_version_or_none("torch"),
    }
    return {
        "tablex_backend": {
            "executable": sys.executable,
            "workspace_python": str(workspace_python),
            "workspace_python_exists": workspace_python.exists(),
            "packages": packages,
            "gpu": {
                "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
            },
        },
        "notebook_execution": {
            "marimo_available": packages["marimo"] is not None,
            "rendering_owner": "tablex_harness",
            "source_dirs": ["notebooks", "outputs/notebooks"],
        },
    }


def package_version_or_none(package_name: str) -> str | None:
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def write_session_context_file(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    response_locale: str | None = None,
) -> None:
    if not session.workspace_path:
        raise RuntimeError("AgentSession workspace path is not configured")
    workspace = resolve_runtime_data_path(session.workspace_path)
    path = workspace / ".tablex" / "context.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_session_dataset_links(db, workspace=workspace, project_id=project.id)
        manifest_path = workspace / SESSION_INTERNAL_DIR / SESSION_DATA_MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise RuntimeError(f"AgentSession data manifest was not created: {manifest_path}")
        context = build_session_context(db, project=project, session=session, response_locale=response_locale)
        path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"AgentSession context could not be written: {path}") from exc


def session_data_manifest(workspace: Path) -> dict[str, Any]:
    manifest_path = workspace / SESSION_INTERNAL_DIR / SESSION_DATA_MANIFEST_FILENAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"datasets": []}
    if not isinstance(payload, dict):
        return {"datasets": []}
    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        return {"datasets": []}
    return {"datasets": [item for item in datasets if isinstance(item, dict)]}


def prior_research_status_context(db: Session, *, project_id: str) -> dict[str, Any]:
    def metadata_count(metadata: dict[str, Any], key: str) -> int:
        value = metadata.get(key)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return 0

    reports = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "research_findings_report")
            .order_by(Artifact.created_at.desc())
            .limit(20)
        ).all()
    )
    latest_reports: list[dict[str, Any]] = []
    source_count_total = 0
    finding_count_total = 0
    no_findings_report_count = 0
    for artifact in reports[:5]:
        metadata = loads_json(artifact.metadata_json, {})
        metadata = metadata if isinstance(metadata, dict) else {}
        source_count = metadata_count(metadata, "source_count")
        finding_count = metadata_count(metadata, "finding_count")
        no_findings = bool(metadata.get("no_findings")) if isinstance(metadata, dict) else False
        source_count_total += source_count
        finding_count_total += finding_count
        if no_findings:
            no_findings_report_count += 1
        latest_reports.append(
            {
                "artifact_id": artifact.id,
                "topic": metadata.get("topic") if isinstance(metadata.get("topic"), str) else None,
                "research_plan_node_id": (
                    metadata.get("research_plan_node_id")
                    if isinstance(metadata.get("research_plan_node_id"), str)
                    else None
                ),
                "source_count": source_count,
                "finding_count": finding_count,
                "no_findings": no_findings,
                "created_at": artifact.created_at.isoformat(),
            }
        )
    return {
        "schema_version": "prior_research_status.v1",
        "registered_report_count": len(reports),
        "source_count_total_latest": source_count_total,
        "finding_count_total_latest": finding_count_total,
        "no_findings_report_count_latest": no_findings_report_count,
        "latest_reports": latest_reports,
        "completion_signal": (
            "No research_findings_report is registered yet. If prior knowledge can affect validation, target definition, "
            "feature design, modeling, diagnostics, or reporting, perform source-backed research or register explicit "
            "no_findings through research_tool_requests before treating prior research as complete."
            if not reports
            else "Registered research_findings_report artifacts are available. Reuse them when relevant and add new findings when new questions arise."
        ),
    }


def build_session_context(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    response_locale: str | None = None,
) -> dict[str, Any]:
    workspace = resolve_runtime_data_path(session.workspace_path or "")
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc()).limit(12)
        ).all()
    )
    artifacts = list(
        db.scalars(
            select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.created_at.desc()).limit(80)
        ).all()
    )
    skill_references = list(
        db.scalars(
            select(AssetReference)
            .where(AssetReference.source_type == "project", AssetReference.source_id == project.id)
            .order_by(AssetReference.created_at.desc())
            .limit(30)
        ).all()
    )
    response_locale = response_locale.strip() if isinstance(response_locale, str) and response_locale.strip() else latest_project_response_locale(db, project)
    equipped_skills = equipped_skill_context(db, skill_references)
    latest_research_plan_artifact = next((item for item in artifacts if item.asset_type == "research_plan"), None)
    data_manifest = session_data_manifest(workspace)
    data_links_by_dataset_id = {
        str(item.get("dataset_snapshot_id")): item
        for item in data_manifest.get("datasets", [])
        if isinstance(item, dict) and item.get("dataset_snapshot_id")
    }
    settings = get_settings()
    return {
        "schema_version": "tablex_agent_session_context.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
            "autonomy_mode": project.autonomy_mode,
        },
        "human_interface": {
            "response_locale": response_locale,
            "notebook_language": response_locale,
            "instruction": (
                "Write human-facing chat responses, marimo notebook narratives, research summaries, and reports "
                "in this locale unless the user explicitly asks otherwise."
            ),
        },
        "agent_capabilities": {
            "network_access_enabled": settings.agent_session_network_enabled,
            "web_search_enabled": settings.agent_session_web_search_enabled,
            "research_instruction": (
                "When prior knowledge can affect the project, use available network/web access to read sources and "
                "register project-relevant findings through research_tool_requests. If useful sources were searched but "
                "nothing should be adopted, register no_findings with the searched queries and rationale."
            ),
        },
        "prior_research_status": prior_research_status_context(db, project_id=project.id),
        "session": {"id": session.id, "turn_index": session.turn_index, "codex_thread_id": session.codex_thread_id},
        "protocol": {
            "path": f"{SESSION_INTERNAL_DIR}/{SESSION_PROTOCOL_FILENAME}",
            "instruction": "Read this runner-facing protocol for request/ack channels, inbox handling, and output registration.",
        },
        "datasets": [
            {
                "id": item.id,
                "artifact_id": item.artifact_id,
                "source_ref": item.source_ref,
                "row_count": item.row_count,
                "column_count": item.column_count,
                "workspace_path": data_links_by_dataset_id.get(item.id, {}).get("workspace_path"),
                "workspace_relative_path": data_links_by_dataset_id.get(item.id, {}).get("workspace_relative_path"),
            }
            for item in datasets
        ],
        "dataset_access": {
            "root": f"{SESSION_INTERNAL_DIR}/{SESSION_DATA_DIR}",
            "cache_root": f"{SESSION_INTERNAL_DIR}/{SESSION_CACHE_DIR}",
            "manifest_path": str(workspace / SESSION_INTERNAL_DIR / SESSION_DATA_MANIFEST_FILENAME),
            "manifest_relative_path": f"{SESSION_INTERNAL_DIR}/{SESSION_DATA_MANIFEST_FILENAME}",
            "data_dir": str(workspace / SESSION_INTERNAL_DIR / SESSION_DATA_DIR),
            "data_dir_relative_path": f"{SESSION_INTERNAL_DIR}/{SESSION_DATA_DIR}",
            "files": data_manifest.get("datasets", []),
            "datasets": data_manifest.get("datasets", []),
            "guarantee": (
                "These workspace_relative_path values are stable AgentSession workspace paths. Tablex starts native marimo "
                "for registered session notebooks with the AgentSession workspace as the working directory, so notebook code "
                "can read them directly."
            ),
            "instruction": (
                "For native marimo notebooks, use dataset_access.datasets[*].fast_paths profile/sample files for the first "
                "render whenever possible. Use workspace_relative_path for deliberate full-data scans, modeling scripts, "
                "or when a visualization truly needs the full table. These paths are Tablex-managed links, copies, or "
                "cache files in the session workspace."
            ),
        },
        "recent_artifacts": [
            {
                "id": item.id,
                "asset_type": item.asset_type,
                "name": item.name,
                "uri": item.uri,
                "path": str(artifact_primary_path(item)),
                "metadata": loads_json(item.metadata_json, {}),
            }
            for item in artifacts
        ],
        "equipped_skill_references": equipped_skills,
        "research_plan_display": research_plan_display_context(
            db,
            latest_research_plan_artifact,
            project_id=project.id,
            response_locale=response_locale,
        ),
        "python_runtimes": python_runtime_context(workspace),
        "output_contract": {
            "registerable_dirs": ["outputs", "reports", "notebooks", "artifacts"],
            "marimo_notebooks": "Place .py marimo notebooks under notebooks/ or outputs/notebooks/.",
            "notebook_runtime": (
                "For local notebook checks inside this workspace, prefer python_runtimes.tablex_backend.workspace_python. "
                "Use dataset_access links for data reads. Tablex opens registered marimo source notebooks with native marimo "
                "after they are saved as artifacts."
            ),
            "living_research_plan": (
                "When the project plan changes, write outputs/research_plan.json with optional timeline_blocks. "
                "Tablex renders those blocks directly; after the initial anchors, Codex may append, refine, supersede, or branch them. "
                "Keep top-level timeline_blocks coarse and capped at 7 nodes: use granularity chapter, phase, or milestone. Put individual analyses, "
                "model attempts, diagnostics, notebook sections, and reports in subtasks, ExperimentRuns, artifacts, or completion evidence. "
                "Completed nodes are append-only: keep them visible and add follow-up nodes when more work is needed. "
                "For validated tool commits, exactly one open top-level node should be active/waiting/blocked, and a done node needs "
                "structured completion_evidence, supporting_artifacts, or a no_output_required rationale. "
                "Write human-visible timeline fields such as title, subtitle, why_it_matters, next_action, done_criteria, blockers, "
                "and subtask title/detail in human_interface.response_locale. If you keep canonical English, also include "
                "localizations like {\"ja-JP\": {\"title\": \"...\", \"subtitle\": \"...\"}}."
            ),
            "research_plan_tool_requests": {
                "request_dir": ".tablex/requests/research_plan",
                "ack_dir": ".tablex/acks/research_plan",
                "schema_version": "tablex_research_plan_request.v1",
                "operations": [
                    "commit_revision",
                    "set_current_work",
                    "attach_artifact",
                    "request_human_attention",
                ],
                "description": (
                    "Use this fixed JSON request/ack channel when you need Tablex to commit a plan revision, update the "
                    "current plan node, link an output artifact to a node, or create a human-attention question. "
                    "Use a new request_id and file for each operation, then read the matching ack JSON."
                ),
                "commit_revision_contract": {
                    "top_level_granularity": ["chapter", "phase", "milestone"],
                    "max_top_level_nodes": 7,
                    "current_rule": "If any top-level work remains open, exactly one top-level node should be active, waiting, or blocked.",
                    "done_rule": (
                        "A done node must include completion_evidence/supporting_artifacts or no_output_required with rationale. "
                        "If it produced output, include deliverable_contract.expected_outputs and matching evidence output_type values."
                    ),
                    "known_output_types": [
                        "notebook",
                        "report",
                        "experiment_run",
                        "leaderboard_entry",
                        "prediction_pipeline",
                        "research_findings",
                        "prior_research",
                        "model_diagnostics",
                        "model_diagnostics_artifacts",
                        "native_feature_importance",
                        "permutation_importance",
                        "partial_dependence",
                        "shap",
                        "pilot_scoring",
                        "pilot_report",
                        "validation_audit",
                        "pilot_audit",
                        "artifact",
                        "evidence",
                        "visualization",
                        "question",
                    ],
                    "example_done_node": {
                        "id": "data_understanding",
                        "title": "Data understanding and relational map",
                        "granularity": "chapter",
                        "status": "done",
                        "deliverable_contract": {"expected_outputs": ["notebook", "report"]},
                        "completion_evidence": [
                            {"output_type": "notebook", "workspace_path": "notebooks/data_understanding.py"},
                            {"output_type": "report", "workspace_path": "reports/data_understanding.md"},
                        ],
                    },
                },
            },
            "data_tool_requests": {
                "request_dir": ".tablex/requests/data",
                "ack_dir": ".tablex/acks/data",
                "schema_version": DATA_REQUEST_SCHEMA_VERSION,
                "operations": ["set_primary_table", "register_derived_table", "commit_task_spec"],
                "description": (
                    "Use this fixed JSON request/ack channel when the data shape or task framing should become "
                    "registered Tablex state. Tablex validates ids, workspace files, enums, and references; Codex owns "
                    "the reasoning behind the objective, table grain, target construction, or unsupervised task shape."
                ),
                "task_spec_contract": {
                    "schema_version": TASK_SPEC_SCHEMA_VERSION,
                    "task_shape_enum": [
                        "supervised_regression",
                        "supervised_classification",
                        "multilabel",
                        "multi_target",
                        "clustering",
                        "anomaly_detection",
                        "forecasting",
                        "distribution_prediction",
                        "aggregate_prediction",
                        "inverse_optimization",
                        "exploratory",
                        "other",
                    ],
                    "target_rule": "targets may be empty for unsupervised or exploratory task shapes.",
                    "status_enum": ["provisional", "user_confirmed", "superseded", "rejected"],
                    "example_request": {
                        "schema_version": DATA_REQUEST_SCHEMA_VERSION,
                        "request_id": "commit_task_spec_001",
                        "operation": "commit_task_spec",
                        "payload": {
                            "task_spec": {
                                "schema_version": TASK_SPEC_SCHEMA_VERSION,
                                "objective_text": "Predict demand after reviewing row grain and supporting tables.",
                                "task_shape": "supervised_regression",
                                "targets": [
                                    {
                                        "table_ref": "ds_current",
                                        "column": "demand",
                                        "derivation": None,
                                    }
                                ],
                                "granularity": {
                                    "kind": "row",
                                    "table_ref": "ds_current",
                                    "description": "One row is one store-date observation.",
                                },
                                "assumptions": [],
                                "status": "provisional",
                            }
                        },
                    },
                },
            },
            "evaluation_tool_requests": {
                "request_dir": ".tablex/requests/evaluation",
                "ack_dir": ".tablex/acks/evaluation",
                "schema_version": EVALUATION_REQUEST_SCHEMA_VERSION,
                "operations": ["propose_evaluation", "generate_split"],
                "description": (
                    "Use this fixed JSON request/ack channel when the metric or validation split should become "
                    "registered Tablex evaluation state. Codex owns the reasoning and rationale; Tablex validates "
                    "fixed metric identifiers, dataset ids, split-policy enums, and referenced columns."
                ),
                "split_policy_kinds": [
                    "random",
                    "stratified",
                    "group",
                    "time",
                    "fixed_file",
                    "fold_column",
                    "rolling_forward",
                ],
                "example_propose_request": {
                    "schema_version": EVALUATION_REQUEST_SCHEMA_VERSION,
                    "request_id": "propose_stratified_auc_001",
                    "operation": "propose_evaluation",
                    "payload": {
                        "objective_metric": {"name": "roc_auc", "direction": "higher_is_better"},
                        "secondary_metrics": ["pr_auc", "log_loss"],
                        "split_policy": {
                            "kind": "stratified",
                            "params": {"n_folds": 5, "seed": 42, "stratify_column": "TARGET"},
                        },
                        "rationale": "Use class-stratified folds because the target is imbalanced.",
                        "provisional_assumption": "No external holdout has been provided yet.",
                    },
                },
                "example_generate_split_request": {
                    "schema_version": EVALUATION_REQUEST_SCHEMA_VERSION,
                    "request_id": "generate_split_for_eval_001",
                    "operation": "generate_split",
                    "payload": {"evaluation_spec_id": "eval_approved"},
                },
            },
            "experiment_result_tool_requests": {
                "request_dir": ".tablex/requests/experiments",
                "ack_dir": ".tablex/acks/experiments",
                "schema_version": "tablex_experiment_result_request.v1",
                "operations": ["register_runs"],
                "description": (
                    "Use this fixed JSON request/ack channel when model or evaluation results should become "
                    "Tablex ExperimentRun records and appear in the Leaderboard. Each run must include a stable "
                    "model_id and numeric metrics. Prefer one comparable primary metric across runs in the same result set. "
                    "After registering runs, inspect result.pipeline_registration in the ack; if it is missing or partial, "
                    "continue with register_prediction_pipeline requests for those run ids before marking modeling/reporting complete."
                ),
                "register_runs_contract": {
                    "research_plan_link": (
                        "When a ResearchPlan exists, every model/evaluation result must name the visible plan node. "
                        "For .tablex/requests/experiments use payload.research_plan_node_id; for artifacts/model_results.json "
                        "use top-level research_plan_node_id; per-run research_plan_node_id is also accepted. "
                        "If you moved from data understanding into modeling/evaluation, first commit a ResearchPlan revision or "
                        "set current work for the modeling/evaluation node, then register runs against that node."
                    ),
                    "optional_context_links": (
                        "Set payload.dataset_snapshot_id, payload.evaluation_spec_id, payload.split_manifest_id, "
                        "and payload.source_workspace_path when available. Tablex validates these fixed ids, derives "
                        "dataset/evaluation context from split manifests, resolves workspace paths to registered artifacts, "
                        "and links the resulting ExperimentRuns back to the evidence artifact and visible ResearchPlan node."
                    ),
                    "required_run_fields": ["model_id", "model_description", "features_used", "metrics"],
                    "recommended_run_fields": [
                        "model_label",
                        "feature_summary",
                        "primary_metric_name",
                        "source_workspace_path",
                        "dataset_snapshot_id",
                        "evaluation_spec_id",
                        "split_manifest_id",
                    ],
                    "example_request": {
                        "schema_version": "tablex_experiment_result_request.v1",
                        "request_id": "register_model_runs_001",
                        "operation": "register_runs",
                        "payload": {
                            "research_plan_node_id": "modeling_and_diagnostics",
                            "source_workspace_path": "reports/model_results_summary.md",
                            "split_manifest_id": "split_primary",
                            "runs": [
                                {
                                    "model_id": "xgboost_structured_text_v1",
                                    "model_description": "Fold-safe boosted baseline with structured and text features.",
                                    "features_used": ["structured_profile", "text_hashing"],
                                    "primary_metric_name": "mae",
                                    "metrics": {"mae": 123.4, "rmse": 180.0},
                                    "source_workspace_path": "artifacts/model_results.json",
                                }
                            ],
                        },
                    },
                    "example_model_results_file": {
                        "schema_version": "model_results.v1",
                        "research_plan_node_id": "modeling_and_diagnostics",
                        "primary_metric_name": "mae",
                        "runs": [
                            {
                                "model_id": "store_mean_baseline",
                                "model_description": "Fold-safe store mean baseline.",
                                "features_used": ["store_id"],
                                "primary_metric_name": "mae",
                                "metrics": {"mae": 3.2, "rmse": 4.1},
                            }
                        ],
                    },
                },
            },
            "model_diagnostics_tool_requests": {
                "request_dir": ".tablex/requests/model_diagnostics",
                "ack_dir": ".tablex/acks/model_diagnostics",
                "schema_version": MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION,
                "operations": ["register_model_diagnostics_artifacts"],
                "description": (
                    "Use this fixed JSON request/ack channel after producing model diagnostics files for leaderboard runs. "
                    "Tablex validates run ids, workspace file references, and diagnostic check coverage, then registers "
                    "permutation importance, native/tree feature importance, partial dependence, SHAP summaries, and a "
                    "model_diagnostics_artifact_pack as first-class artifacts linked to the runs and ResearchPlan node."
                ),
                "required_checks": list(MODEL_DIAGNOSTIC_CHECK_NAMES),
                "check_statuses": list(MODEL_DIAGNOSTIC_CHECK_STATUSES),
                "standard_artifact_types": [
                    "permutation_importance",
                    "native_feature_importance",
                    "feature_importance",
                    "partial_dependence",
                    "shap_summary",
                    "shap",
                    "model_diagnostics_artifact_pack",
                ],
                "completion_contract": (
                    "When a modeling or reporting node claims model diagnostics are done, first register the diagnostic "
                    "artifacts here and read the ack. If a check is not technically applicable or a dependency is missing, "
                    "declare that fixed status with a reason instead of omitting the check."
                ),
                "example_request": {
                    "schema_version": MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION,
                    "request_id": "register_model_diagnostics_001",
                    "operation": "register_model_diagnostics_artifacts",
                    "payload": {
                        "research_plan_node_id": "modeling_and_diagnostics",
                        "related_run_ids": ["run_a", "run_b"],
                        "checks": [
                            {
                                "name": "permutation_importance",
                                "status": "included",
                                "artifact_keys": ["permutation_importance"],
                            },
                            {
                                "name": "native_feature_importance",
                                "status": "included",
                                "artifact_keys": ["native_feature_importance"],
                            },
                            {
                                "name": "partial_dependence",
                                "status": "included",
                                "artifact_keys": ["partial_dependence"],
                            },
                            {
                                "name": "shap",
                                "status": "needs_dependency",
                                "reason": "SHAP is not available in the current runtime.",
                            },
                        ],
                        "artifacts": {
                            "permutation_importance": "artifacts/permutation_importance.csv",
                            "native_feature_importance": "artifacts/native_feature_importance.csv",
                            "partial_dependence": "artifacts/partial_dependence.csv",
                            "model_diagnostics_artifact_pack": "artifacts/model_diagnostics.json",
                        },
                    },
                },
            },
            "research_tool_requests": {
                "request_dir": ".tablex/requests/research",
                "ack_dir": ".tablex/acks/research",
                "schema_version": RESEARCH_REQUEST_SCHEMA_VERSION,
                "operations": ["register_research_findings"],
                "description": (
                    "Use this fixed JSON request/ack channel after reading external or project-specific prior knowledge. "
                    "Register sources and findings, or explicitly register no_findings after searching. Tablex validates "
                    "the JSON shape and source_indexes only; it does not judge prose quality or source truth."
                ),
                "completion_contract": (
                    "Do not mark a prior-knowledge research plan node done merely because Skill context or a search plan exists. "
                    "First register source-backed findings, a source-backed synthesis artifact, or an explicit no_findings request "
                    "after searching. If you intentionally postpone research, keep the node open or explain that order in the plan."
                ),
                "example_request": {
                    "schema_version": RESEARCH_REQUEST_SCHEMA_VERSION,
                    "request_id": "register_prior_research_001",
                    "operation": "register_research_findings",
                    "payload": {
                        "research_plan_node_id": "prior_research",
                        "topic": "project-specific tabular modeling prior knowledge",
                        "query_log": ["example search query"],
                        "sources": [
                            {
                                "url": "https://example.com/source",
                                "title": "Source title",
                                "source_type": "other",
                                "retrieved_at": utc_now().isoformat(),
                                "key_claims": ["Claim read from the source."],
                                "reliability_notes": "Why this source is or is not directly applicable.",
                            }
                        ],
                        "findings": [
                            {
                                "claim": "Project-relevant claim.",
                                "source_indexes": [0],
                                "implication_for_project": "How this changes validation, features, modeling, or reporting.",
                                "recommended_action": "Action Codex plans to take.",
                            }
                        ],
                        "no_findings": None,
                    },
                },
            },
            "pipeline_tool_requests": {
                "request_dir": ".tablex/requests/pipelines",
                "ack_dir": ".tablex/acks/pipelines",
                "schema_version": PIPELINE_REQUEST_SCHEMA_VERSION,
                "operations": ["register_prediction_pipeline"],
                "description": (
                    "Use this fixed JSON request/ack channel when a leaderboard run has a reproducible prediction pipeline. "
                    "Tablex validates required files and manifest shape, zips the pipeline directory as a prediction_pipeline artifact, "
                    "and links it to the declared ExperimentRun ids. predict.py must accept --input <file> for single-table inputs, "
                    "or --input-dir <directory> when input_contract.required_tables is declared. The --input-dir directory contains "
                    "a manifest.json and one file per table."
                ),
                "required_pipeline_files": [
                    "pipeline_manifest.json",
                    "train.py",
                    "predict.py",
                    "requirements.txt",
                    "README.md",
                ],
                "selftest_contract": {
                    "single_table": (
                        "Strongly recommended: include selftest/input.csv with target-free rows representative of prediction input. "
                        "If absent, Tablex smoke validation falls back to synthetic manifest values and marks the guarantee weaker."
                    ),
                    "multi_table": (
                        "Required when input_contract.required_tables is present: include selftest/input/<table>.csv for each "
                        "non-optional table. Tablex smoke validation runs predict.py with --input-dir using these files."
                    ),
                },
                "example_request": {
                    "schema_version": PIPELINE_REQUEST_SCHEMA_VERSION,
                    "request_id": "register_prediction_pipeline_001",
                    "operation": "register_prediction_pipeline",
                    "payload": {
                        "pipeline_name": "xgboost_structured_text_v1",
                        "workspace_dir": "pipelines/xgboost_structured_text_v1",
                        "experiment_run_ids": ["run_current"],
                        "research_plan_node_id": "modeling",
                        "manifest": {
                            "schema_version": "pipeline_manifest.v1",
                            "input_contract": {
                                "inference_format": {"columns": [{"name": "row_id", "dtype": "string", "required": True}]},
                                "required_tables": [
                                    {
                                        "name": "application",
                                        "role": "primary",
                                        "columns": [{"name": "row_id", "dtype": "string", "required": True}],
                                        "join_keys": ["row_id"],
                                        "entity_keys": ["row_id"],
                                        "forbidden_columns": ["TARGET"],
                                        "optional": False,
                                    },
                                    {
                                        "name": "history",
                                        "role": "history",
                                        "columns": [{"name": "row_id", "dtype": "string", "required": True}],
                                        "join_keys": ["row_id"],
                                        "as_of_column": None,
                                        "history_window": None,
                                        "optional": True,
                                    },
                                ],
                                "history_requirements": {"required": False},
                            },
                            "output_contract": {
                                "columns": [
                                    {"name": "row_id", "dtype": "string", "required": True},
                                    {"name": "prediction", "dtype": "float", "required": True},
                                ],
                                "id_columns": ["row_id"],
                                "prediction_column": "prediction",
                            },
                            "training": {"dataset_snapshot_id": "ds_current", "split_manifest_id": None, "evaluation_spec_id": None, "seed": 0, "deterministic": True},
                            "expected_metrics": [],
                            "runtime": {"python": ">=3.11", "timeout_seconds_predict": 120},
                        },
                    },
                },
            },
            "deliverable_tool_requests": {
                "request_dir": ".tablex/requests/deliverables",
                "ack_dir": ".tablex/acks/deliverables",
                "schema_version": DELIVERABLE_REQUEST_SCHEMA_VERSION,
                "operations": ["waive_deliverable"],
                "description": (
                    "Use this fixed JSON request/ack channel only when an expected deliverable is intentionally unnecessary. "
                    "Tablex does not block work on open expectations; it keeps them visible until the matching artifact is "
                    "registered or Codex waives the expectation with a rationale."
                ),
                "example_request": {
                    "schema_version": DELIVERABLE_REQUEST_SCHEMA_VERSION,
                    "request_id": "waive_non_applicable_deliverable_001",
                    "operation": "waive_deliverable",
                    "payload": {
                        "expectation_id": "deliv_current",
                        "rationale": "This output is not applicable because the corresponding model family does not expose it.",
                    },
                },
            },
            "pilot_tool_requests": {
                "request_dir": ".tablex/requests/pilot",
                "ack_dir": ".tablex/acks/pilot",
                "schema_version": PILOT_REQUEST_SCHEMA_VERSION,
                "operations": ["register_validation_audit"],
                "description": (
                    "Use this fixed JSON request/ack channel after pilot scoring evidence is available. Tablex stores the audit "
                    "and links referenced artifacts; Codex owns the interpretation, hypotheses, and next iteration plan."
                ),
                "observation_contract": (
                    "When a pilot observation envelope appears under `.tablex/inbox/`, read the referenced pilot_scoring_report "
                    "artifact, register a validation audit request, and update the ResearchPlan with the next iteration. "
                    "Tablex validates the fixed schema, artifact references, and enums; Codex owns the judgment."
                ),
                "component_enum": [
                    "temporal_drift",
                    "covariate_shift",
                    "target_shift",
                    "leakage",
                    "sample_noise",
                    "data_quality",
                    "other",
                ],
                "scheme_verdict_enum": ["confirmed", "partially_confirmed", "refuted"],
            },
            "notebook_tool_requests": {
                "request_dir": ".tablex/requests/notebooks",
                "ack_dir": ".tablex/acks/notebooks",
                "schema_version": NOTEBOOK_REQUEST_SCHEMA_VERSION,
                "operations": ["register_notebook"],
                "description": (
                    "Use this fixed JSON request/ack channel after saving a marimo notebook when you need Tablex "
                    "to register the source, link it to a ResearchPlan node, and post a human-facing Chat link that opens native marimo. "
                    "Read the matching ack before marking the plan node done."
                ),
                "register_notebook_contract": {
                    "required_reference": "payload.artifact_id or payload.workspace_path",
                    "optional_project_link": "Set payload.research_plan_node_id to link the notebook source to a visible plan node.",
                    "optional_context_links": (
                        "Set payload.dataset_snapshot_id for data notebooks, payload.run_id for single-run diagnostics, "
                        "payload.related_run_ids when one notebook compares multiple leaderboard runs, and "
                        "payload.model_version_id when the notebook explains a model package. Tablex validates these ids "
                        "and stores them on the notebook artifact so Data, Leaderboard, Assets, and ResearchPlan can all "
                        "open the same notebook viewer."
                    ),
                "quality_manifest": (
                    "Set payload.quality_manifest when the notebook is a human-facing deliverable. This is a fixed "
                    "structure, not prose validation: declare figure_count, table_count, key_findings, read_order, "
                    "data_sources_used, and limitations so Tablex can route and explain the notebook without guessing. "
                    "Human-facing data-understanding and model-diagnostics notebooks must include meaningful visual "
                    "diagnostics, not only markdown and tables. For notebook_kind=model_diagnostics, also include "
                    "quality_manifest.model_diagnostics with fixed check entries for permutation_importance, "
                    "native_feature_importance, partial_dependence, and shap. Mark each check as included, "
                    "not_applicable, needs_model_artifact, needs_dependency, or deferred, and give a short reason for "
                    "anything not included."
                ),
                "marimo_authoring_constraints": [
                        (
                            "Marimo public variables returned or assigned by cells must be unique across the notebook. "
                            "Use private underscore-prefixed names for repeated temporaries such as `_mo`, `_fig`, "
                            "`_ax`, `_table`, and `_data`."
                        ),
                        (
                            "Import shared modules such as marimo, pandas, numpy, or plotly once in an early cell and "
                            "return them for dependent cells, or use private aliases inside cells. Do not define public "
                            "`mo`, `pd`, `np`, or `fig` variables in multiple cells."
                        ),
                        (
                            "For the first visible render, prefer dataset_access.datasets[*].fast_paths profile/sample "
                            "files over full table reads. Read full data from `.tablex/data` only for deliberate scans "
                            "or modeling steps, and cache summaries for repeated native marimo rendering."
                        ),
                        (
                            "When using matplotlib or seaborn for human-facing Japanese labels, import "
                            "`japanize_matplotlib` in the notebook setup before drawing figures. The Tablex runtime "
                            "exposes its availability in python_runtimes.tablex_backend.packages."
                        ),
                    ],
                    "example_request": {
                        "schema_version": NOTEBOOK_REQUEST_SCHEMA_VERSION,
                        "request_id": "register_data_understanding_notebook_001",
                        "operation": "register_notebook",
                        "payload": {
                            "workspace_path": "notebooks/data_understanding.py",
                            "research_plan_node_id": "data_understanding",
                            "notebook_kind": "data_understanding",
                            "dataset_snapshot_id": "ds_current",
                            "quality_manifest": {
                                "schema_version": "tablex_notebook_quality_manifest.v1",
                                "figure_count": 6,
                                "table_count": 3,
                                "key_findings": [
                                    "Target distribution is right-skewed and unit-dependent.",
                                    "Company-level grouping is needed to avoid overly optimistic validation.",
                                ],
                                "read_order": [
                                    {"label": "Start here", "anchor": "overview"},
                                    {"label": "Leakage and evaluation risk", "anchor": "evaluation-risk"},
                                ],
                                "data_sources_used": ["ds_current"],
                                "limitations": ["Business objective is still provisional."],
                            },
                        },
                    },
                    "model_diagnostics_manifest_example": {
                        "schema_version": "tablex_model_diagnostics_manifest.v1",
                        "checks": [
                            {
                                "name": "permutation_importance",
                                "status": "included",
                                "evidence": ["notebooks/model_diagnostics.py"],
                            },
                            {
                                "name": "native_feature_importance",
                                "status": "included",
                                "evidence": ["notebooks/model_diagnostics.py"],
                            },
                            {
                                "name": "partial_dependence",
                                "status": "included",
                                "evidence": ["notebooks/model_diagnostics.py"],
                            },
                            {
                                "name": "shap",
                                "status": "needs_dependency",
                                "reason": "The runtime does not currently provide shap; record this explicitly instead of omitting it.",
                            },
                        ],
                    },
                },
            },
            "progress": "Explain progress naturally in Codex messages. Tablex stores the raw transcript and Chat explains it to humans.",
            "chat_update": (
                "reports/chat_update.md is the human-facing Chat update, not an internal changelog. "
                "Explain the current work, why it matters, what changed, open uncertainty, and the next useful place to look. "
                "Avoid raw artifact IDs, hashes, internal schema names, and implementation vocabulary unless they are needed for a user decision."
            ),
            "notebook_quality": (
                "Data understanding and research notebooks are human deliverables, not only model context. "
                "Use equipped Skills such as tablex-grandmaster-eda and tablex-notebook-quality when present. "
                "Prefer notebooks that execute against dataset_access links, include useful plots/tables, and explain findings, "
                "hypotheses, uncertainty, leakage risks, and next analysis moves in the user's response locale."
            ),
        },
    }


def latest_project_response_locale(db: Session, project: Project) -> str:
    candidates: list[tuple[datetime, str]] = []
    user = db.get(User, project.created_by)
    if user is not None and user.locale and user.locale.strip():
        candidates.append((_utc_comparable(user.updated_at), user.locale.strip()))
    jobs = list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project.id, Job.job_type.in_(["start_autonomous_loop", "agent_chat_turn"]))
            .order_by(Job.created_at.desc())
            .limit(20)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            candidates.append((_utc_comparable(job.created_at), locale.strip()))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    legacy_job = db.scalar(
        select(Job)
        .where(Job.project_id == project.id, Job.job_type == "start_autonomous_loop")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if legacy_job is not None:
        payload = loads_json(legacy_job.input_json, {})
        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return "en-US"


def _utc_comparable(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def research_plan_display_context(
    db: Session,
    artifact: Artifact | None,
    *,
    project_id: str,
    response_locale: str,
) -> dict[str, Any]:
    payload, source = research_plan_context_payload(db, artifact=artifact, project_id=project_id)
    document = payload if isinstance(payload, dict) else {}
    timeline_blocks = document.get("timeline_blocks")
    return {
        **source,
        "response_locale": response_locale,
        "document": document,
        "timeline_blocks": timeline_blocks if isinstance(timeline_blocks, list) else [],
        "contract_validation": research_plan_contract_validation_summary(
            db,
            project_id=project_id,
            payload=document,
        ),
    }


def research_plan_context_payload(
    db: Session,
    *,
    artifact: Artifact | None,
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    revision = latest_research_plan_revision(db, project_id=project_id)
    if revision is not None:
        return research_plan_revision_context(revision)
    if artifact is None:
        initial = ensure_harness_initial_research_plan_revision(db, project_id=project_id)
        return research_plan_revision_context(initial)
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
    validation = research_plan_contract_validation_summary(
        db,
        project_id=project_id,
        payload=payload if isinstance(payload, dict) else {},
    )
    if validation["status"] == "ok":
        try:
            result = commit_research_plan_artifact_revision(
                db,
                artifact=artifact,
                reason=f"Committed valid legacy research_plan artifact {artifact.id} for AgentSession context.",
                strict_validation=True,
            )
        except ResearchPlanValidationError:
            result = None
        if result is not None:
            return research_plan_revision_context(result.revision)

    initial = ensure_harness_initial_research_plan_revision(db, project_id=project_id)
    canonical_payload, canonical_source = research_plan_revision_context(initial)
    canonical_source["ignored_source_artifact"] = {
        "schema_version": "ignored_research_plan_source.v1",
        "status": "needs_revision",
        "source_artifact_id": artifact.id,
        "artifact_name": artifact.name,
        "artifact_version": artifact.version,
        "reason": "latest_research_plan_artifact_failed_contract_validation",
        "contract_validation": validation,
    }
    return canonical_payload, canonical_source


def research_plan_revision_context(revision: ResearchPlanRevision) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = research_plan_revision_document(revision)
    return (
        payload if isinstance(payload, dict) else {},
        {
            "source": "research_plan_revision",
            "source_revision_id": revision.id,
            "research_plan_id": revision.research_plan_id,
            "revision_index": revision.revision_index,
            "revision_author_type": revision.author_type,
            "source_artifact_id": revision.source_artifact_id,
            "artifact_id": revision.source_artifact_id,
            "path": None,
        },
    )


def equipped_skill_context(db: Session, references: list[AssetReference]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for reference in references:
        asset = db.get(Asset, reference.target_asset_id)
        if asset is None or asset.asset_type != "skill":
            continue
        version = db.get(AssetVersion, reference.target_asset_version_id or asset.latest_version_id or "")
        artifact = db.get(Artifact, version.artifact_id) if version is not None else None
        content = read_skill_asset_content(artifact) if artifact is not None else {}
        items.append(
            {
                "reference_id": reference.id,
                "asset_id": asset.id,
                "asset_version_id": version.id if version is not None else None,
                "name": asset.name,
                "description": asset.description,
                "relation_type": reference.relation_type,
                "artifact_id": artifact.id if artifact is not None else None,
                "artifact_path": str(artifact_primary_path(artifact)) if artifact is not None else None,
                "skill_path": content.get("skill_path") if isinstance(content.get("skill_path"), str) else None,
                "reference_paths": content.get("reference_paths") if isinstance(content.get("reference_paths"), list) else [],
                "runner_guidance": content.get("runner_guidance") if isinstance(content.get("runner_guidance"), list) else [],
                "content": content,
            }
        )
    return items


def read_skill_asset_content(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    path = artifact_primary_path(artifact)
    try:
        if path.suffix.lower() == ".json":
            payload = loads_json(path.read_text(encoding="utf-8"), {})
            return payload if isinstance(payload, dict) else {}
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {"text": text[:12000]}
