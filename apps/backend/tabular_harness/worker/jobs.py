from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
import sys
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings, get_settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Job,
    ModelVersion,
    PilotDeployment,
    PilotOutcomeBatch,
    PilotPredictionBatch,
    Project,
    Question,
    Report,
    ResearchBrief,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.adaptive_strategy import create_adaptive_strategy_brief
from tabular_harness.services.agent_chat import handle_agent_chat_turn
from tabular_harness.services.agent_context import prepare_idea_agent_context_pack
from tabular_harness.services.agent_inbox import write_inbox_entry
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import review_agent_task_readiness
from tabular_harness.services.agent_tasks import run_idea_agent_task_stub
from tabular_harness.services.analysis_notebooks import create_notebook_execution_plan
from tabular_harness.services.approach import (
    create_decision_dashboard,
    create_research_plan,
    draft_project_report,
    generate_approach_candidates,
    generate_research_brief,
    store_json_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    artifact_to_dict,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.autonomy import (
    RUNNER_MODE_CODEX_IF_AVAILABLE,
    AutonomousLoopState,
    active_autonomous_child_job_ids,
    ingest_codex_target_definition_proposal,
    queue_autonomous_session_continuation,
    run_autonomous_loop_tick,
)
from tabular_harness.services.avatar_generation import generate_user_avatar_candidates
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    create_baseline_strategy_plan,
    normalize_model_candidate_name,
    run_baseline,
    run_model_candidate,
)
from tabular_harness.services.benchmark_collection import create_benchmark_collection_plan
from tabular_harness.services.benchmark_evidence import create_benchmark_evidence_pack
from tabular_harness.services.prediction_input_feedback import (
    maybe_send_prediction_pipeline_runtime_failure_to_codex,
    prediction_pipeline_runtime_failure_message,
)
from tabular_harness.services.benchmarks import (
    benchmark_import_readiness,
    benchmark_to_dict,
    build_import_manifest,
    build_relational_catalog,
    create_benchmark_scenario_pack,
    default_benchmark_root,
    download_public_benchmark_archive,
    generate_benchmark_fixture,
    inspect_benchmark_local_files,
    raw_benchmark_dataset,
    relative_path,
    resolve_benchmark_root,
    select_primary_file,
    store_benchmark_supporting_table_artifacts,
    validate_required_files,
)
from tabular_harness.services.data_quality import analyze_dataset_quality
from tabular_harness.services.dataset_profile import profile_dataset_artifact
from tabular_harness.services.decision_reporting import create_decision_report_v1
from tabular_harness.services.deliverable_expectations import (
    create_project_data_understanding_notebook_expectation,
    create_run_model_diagnostics_notebook_expectations,
    fulfill_run_pipeline_bundle_expectations,
)
from tabular_harness.services.diagnostics import analyze_run_diagnostics
from tabular_harness.services.eda_review import create_dataset_eda_review
from tabular_harness.services.evaluation import (
    approve_spec,
    create_default_evaluation_candidates,
    create_evaluation_approval_review,
    create_evaluation_scenario_comparison,
    generate_split_manifest,
    promote_candidate_to_spec,
    write_spec_artifact,
)
from tabular_harness.services.experiment_lifecycle import (
    compare_project_experiments,
    create_experiment_plan_for_idea,
    draft_run_report,
)
from tabular_harness.services.jobs import JOB_TYPES, create_job
from tabular_harness.services.kaggle_probe import (
    download_kaggle_selected_files,
    fetch_kaggle_competition_inventory,
    probe_kaggle_benchmark_access,
)
from tabular_harness.services.marimo_sessions import (
    NATIVE_MARIMO_PREWARM_READY_TIMEOUT_SECONDS,
    cleanup_native_marimo_sessions,
    marimo_available,
    start_or_get_native_marimo_session,
    wait_for_native_marimo_session_ready,
)
from tabular_harness.services.model_diagnostics_artifacts import (
    materialize_model_diagnostics_artifacts,
)
from tabular_harness.services.model_versions import validate_model_version_package
from tabular_harness.services.notebook_authoring import create_notebook_authoring_brief
from tabular_harness.services.planned_agent_execution import (
    PlannedAgentTaskExecutionResult,
    run_planned_agent_task_codex_cli,
    run_planned_agent_task_local_stub,
)
from tabular_harness.services.planned_agent_workspace import (
    load_contract_payload,
    prepare_workspace_from_contract_artifact,
)
from tabular_harness.services.project_guidance import (
    create_autonomous_decision_brief,
    create_guided_journey_comparison,
    create_guided_journey_snapshot,
)
from tabular_harness.services.relational_evidence import create_relational_schema_hint
from tabular_harness.services.relational_feature_diagnostics import (
    diagnose_relational_feature_scenarios,
)
from tabular_harness.services.relational_feature_planning import create_relational_feature_plan
from tabular_harness.services.relational_feature_recipe import build_relational_feature_recipe
from tabular_harness.services.reporting import (
    create_project_visualization_dashboard,
    generate_project_insights,
)
from tabular_harness.services.research_plans import (
    record_harness_dataset_upload_in_research_plan,
    record_harness_objective_in_research_plan,
)
from tabular_harness.services.research_runner import run_research_source_pack_local_stub
from tabular_harness.services.research_sources import create_research_source_pack
from tabular_harness.services.research_synthesis import create_research_finding_synthesis
from tabular_harness.services.result_notebook_evidence import (
    prepare_result_notebook_evidence,
    result_notebook_evidence_job_output,
)
from tabular_harness.services.translation import translate_artifact
from tabular_harness.worker.runner import JobHandler, SyncWorker

INITIAL_JOB_TYPES = tuple(sorted(JOB_TYPES))


@dataclass
class StagedUploadFile:
    filename: str
    content_type: str | None
    file: Any


def set_data_understanding_phase_without_turning_agent_off(project: Project) -> None:
    if project.current_phase == "AUTONOMOUS_LOOP":
        return
    project.current_phase = "UNDERSTANDING_REVIEW"


def stub_job_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    del db
    del store
    return {
        "message": "Queued job processed by SyncWorker stub handler.",
        "job_type": job.job_type,
        "input": loads_json(job.input_json, {}),
        "context": loads_json(job.context_json, {}),
        "policy": loads_json(job.policy_json, {}),
        "attempt_count": job.attempt_count,
    }


def agent_chat_turn_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("agent_chat_turn requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("agent_chat_turn requires a non-empty message")
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    agent_model = payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None
    utility_model = payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None
    result = handle_agent_chat_turn(
        db,
        store=store,
        project=project,
        job=job,
        message=message,
        locale=locale,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    return {
        "schema_version": result.response["schema_version"],
        "agent_chat_turn_artifact_id": result.artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "intent_type": result.response["intent"]["type"],
        "action_count": len(result.response["actions"]),
        "assistant_message": result.response["assistant_message"],
        "response_composer": result.response["response_composer"],
        "worker_events": result.response["worker_events"],
        "token_usage": result.response["token_usage"],
        "agent_task_contract_artifact_id": result.planned_agent_task.artifact.id
        if result.planned_agent_task
        else None,
    }


def save_guided_journey_snapshot_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "save_guided_journey_snapshot")
    result = create_guided_journey_snapshot(db, store=store, project=project)
    return {
        "schema_version": result.snapshot["schema_version"],
        "guided_journey_snapshot_artifact_id": result.artifact.id,
        "guided_journey_report_id": result.report.id,
        "guided_journey_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": result.artifact_ids,
        "current_stage_id": result.snapshot["current_stage_id"],
        "recommended_focus_key": result.snapshot["recommended_focus_key"],
    }


def save_autonomous_decision_brief_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "save_autonomous_decision_brief")
    result = create_autonomous_decision_brief(db, store=store, project=project)
    return {
        "schema_version": result.brief["schema_version"],
        "autonomous_decision_brief_artifact_id": result.artifact.id,
        "autonomous_decision_brief_report_id": result.report.id,
        "autonomous_decision_brief_report_artifact_id": result.report_artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": result.artifact_ids,
        "focus_key": result.brief["focus_key"],
        "target_tab": result.brief["target_tab"],
    }


def compare_guided_journey_snapshots_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "compare_guided_journey_snapshots")
    result = create_guided_journey_comparison(db, store=store, project=project)
    return {
        "schema_version": result.comparison["schema_version"],
        "guided_journey_comparison_artifact_id": result.artifact.id,
        "guided_journey_comparison_report_id": result.report.id,
        "guided_journey_comparison_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": result.artifact_ids,
        "changed_stage_count": result.comparison["summary"]["changed_stage_count"],
        "recommended_focus_changed": result.comparison["summary"]["recommended_focus_changed"],
    }


def upload_relational_schema_hint_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "upload_relational_schema_hint")
    staging_artifact_id = payload.get("staging_artifact_id")
    if not isinstance(staging_artifact_id, str) or not staging_artifact_id.strip():
        raise ValueError("upload_relational_schema_hint requires staging_artifact_id")
    staging_artifact = db.get(Artifact, staging_artifact_id)
    if staging_artifact is None:
        raise ValueError("Staged relational schema hint artifact not found")
    source_path = artifact_primary_path(staging_artifact)
    data = source_path.read_bytes()
    filename = payload.get("filename") if isinstance(payload.get("filename"), str) else source_path.name
    content_type = payload.get("content_type") if isinstance(payload.get("content_type"), str) else None
    note = payload.get("note") if isinstance(payload.get("note"), str) else None
    result = create_relational_schema_hint(
        db,
        store=store,
        project=project,
        filename=filename,
        content_type=content_type,
        data=data,
        note=note,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=staging_artifact.id,
        to_asset_type="artifact",
        to_asset_id=result.artifact.id,
        relation_type="materialized_schema_hint",
    )
    return {
        "schema_version": result.summary["schema_version"],
        "relational_schema_hint_artifact_id": result.artifact.id,
        "relational_schema_hint_report_artifact_id": result.report_artifact.id,
        "report_id": result.report.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [staging_artifact.id, result.artifact.id, result.report_artifact.id],
        "staging_artifact_id": staging_artifact.id,
        "content_type": result.summary["content_type"],
        "media_kind": result.summary["media_kind"],
        "parsed_table_count": result.summary["parsed_table_count"],
        "parsed_relationship_count": result.summary["parsed_relationship_count"],
    }


def upload_data_bundle_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "upload_data_bundle")
    table_artifact_ids = require_string_list(payload.get("staged_table_artifact_ids"), "upload_data_bundle", "staged_table_artifact_ids")
    hint_artifact_ids = require_string_list(
        payload.get("staged_relational_hint_artifact_ids"), "upload_data_bundle", "staged_relational_hint_artifact_ids"
    )
    primary_filename = payload.get("primary_filename") if isinstance(payload.get("primary_filename"), str) else None
    target_column = payload.get("target_column") if isinstance(payload.get("target_column"), str) else None
    note = payload.get("note") if isinstance(payload.get("note"), str) else None
    response_locale = payload.get("response_locale") if isinstance(payload.get("response_locale"), str) else None

    def progress(stage: str, percent: int, detail: dict[str, Any] | None = None) -> None:
        update_upload_data_bundle_progress(
            db,
            job,
            stage=stage,
            percent=percent,
            response_locale=response_locale,
            detail=detail,
        )

    progress(
        "opening_staged_files",
        5,
        {"table_file_count": len(table_artifact_ids), "relational_hint_file_count": len(hint_artifact_ids)},
    )
    staged_artifacts: list[Artifact] = []
    with ExitStack() as stack:
        table_uploads: list[StagedUploadFile] = []
        hint_uploads: list[StagedUploadFile] = []
        for artifact_id in table_artifact_ids:
            artifact = staged_upload_artifact_for_job(db, project, artifact_id, "table")
            staged_artifacts.append(artifact)
            metadata = loads_json(artifact.metadata_json, {})
            path = artifact_primary_path(artifact)
            table_uploads.append(
                StagedUploadFile(
                    filename=str(metadata.get("source_filename") or path.name),
                    content_type=str(metadata.get("content_type") or "") or None,
                    file=stack.enter_context(path.open("rb")),
                )
            )
        for artifact_id in hint_artifact_ids:
            artifact = staged_upload_artifact_for_job(db, project, artifact_id, "relational_hint")
            staged_artifacts.append(artifact)
            metadata = loads_json(artifact.metadata_json, {})
            path = artifact_primary_path(artifact)
            hint_uploads.append(
                StagedUploadFile(
                    filename=str(metadata.get("source_filename") or path.name),
                    content_type=str(metadata.get("content_type") or "") or None,
                    file=stack.enter_context(path.open("rb")),
                )
            )
        from tabular_harness.api.routes import ingest_uploaded_data_bundle

        output = ingest_uploaded_data_bundle(
            db,
            store=store,
            project=project,
            job=job,
            table_uploads=cast(Any, table_uploads),
            hint_uploads=cast(Any, hint_uploads),
            target_column=target_column,
            primary_filename=primary_filename,
            note=note,
            response_locale=response_locale,
            progress_callback=progress,
        )
    output["staging_artifact_ids"] = [artifact.id for artifact in staged_artifacts]
    return output


def select_primary_table_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "select_primary_table")
    dataset_snapshot_id = payload.get("dataset_snapshot_id") if isinstance(payload.get("dataset_snapshot_id"), str) else None
    artifact_id = payload.get("artifact_id") if isinstance(payload.get("artifact_id"), str) else None
    target_column_present = "target_column" in payload
    target_column = payload.get("target_column") if isinstance(payload.get("target_column"), str) else None
    response_locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None

    def progress(stage: str, percent: int, detail: dict[str, Any] | None = None) -> None:
        update_select_primary_table_progress(
            db,
            job,
            stage=stage,
            percent=percent,
            response_locale=response_locale,
            detail=detail,
        )

    if bool(dataset_snapshot_id) == bool(artifact_id):
        raise ValueError("select_primary_table requires exactly one of dataset_snapshot_id or artifact_id")

    progress("validating", 10, {"dataset_snapshot_id": dataset_snapshot_id, "artifact_id": artifact_id})
    if dataset_snapshot_id:
        dataset = db.get(DatasetSnapshot, dataset_snapshot_id)
        if dataset is None or dataset.project_id != project.id:
            raise ValueError("DatasetSnapshot not found for this project")
    else:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project.id:
            raise ValueError("Table artifact not found for this project")
        if artifact.asset_type not in {"dataset_snapshot", "uploaded_supporting_table"}:
            raise ValueError("Primary table must be an uploaded table artifact")
        path = artifact_primary_path(artifact)
        if path.suffix.lower() not in {".csv", ".parquet"}:
            raise ValueError("Primary table artifact must be CSV or Parquet")
        existing = db.scalar(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project.id, DatasetSnapshot.artifact_id == artifact.id)
            .order_by(DatasetSnapshot.created_at.desc())
        )
        if existing is not None:
            dataset = existing
        else:
            metadata = loads_json(artifact.metadata_json, {})
            progress("profiling", 35, {"artifact_id": artifact.id, "source_filename": metadata.get("source_filename")})
            dataset = profile_dataset_artifact(
                db,
                store,
                project,
                artifact,
                target_column if target_column_present else project.target_column,
                source_type="user_selected_primary_table",
                source_ref=str(metadata.get("source_filename") or metadata.get("table_name") or artifact.name),
            )

    progress("applying", 82, {"dataset_snapshot_id": dataset.id})
    project.primary_dataset_snapshot_id = dataset.id
    if target_column_present:
        project.target_column = target_column.strip() if target_column else None
    set_data_understanding_phase_without_turning_agent_off(project)
    project.updated_at = utc_now()
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is not None:
        metadata = loads_json(artifact.metadata_json, {})
        artifact.metadata_json = dumps_json(
            {
                **metadata,
                "selected_as_primary_dataset_snapshot_id": dataset.id,
                "selected_as_project_primary_at": utc_now().isoformat(),
            }
        )
        record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=[artifact.id],
            dataset_snapshot_id=dataset.id,
            primary_artifact_id=artifact.id,
        )
    record_harness_objective_in_research_plan(
        db,
        project_id=project.id,
        objective_label=project.target_column,
    )
    progress("finalizing", 100, {"dataset_snapshot_id": dataset.id, "target_column": project.target_column})
    return {
        "schema_version": "select_primary_table.v1",
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "target_column": project.target_column,
        "assistant_message": (
            "主表を更新しました。列候補と目的設定は新しい主表を基準に表示されます。"
            if response_locale and response_locale.lower().startswith("ja")
            else "Primary table updated. Column choices and objective controls now use the selected table."
        ),
    }


def update_upload_data_bundle_progress(
    db: Session,
    job: Job,
    *,
    stage: str,
    percent: int,
    response_locale: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    japanese = response_locale.lower().startswith("ja") if response_locale else False
    labels = {
        "opening_staged_files": ("アップロード済みファイルを開いています", "Opening received files"),
        "storing_tables": ("テーブルをartifactとして保存しています", "Storing table artifacts"),
        "profiling_tables": ("テーブル構造とprofileを作成しています", "Profiling table structure"),
        "processing_schema_hints": ("ER/schema hintを登録しています", "Processing ER/schema hints"),
        "building_catalog": ("複数テーブルのcatalogを作成しています", "Building table catalog"),
        "preparing_notebook_context": ("データ理解notebookの作成文脈を準備しています", "Preparing notebook context"),
        "finalizing": ("データ取り込みを完了しています", "Finalizing data intake"),
    }
    ja_label, en_label = labels.get(stage, ("データ取り込みを進めています", "Importing data"))
    existing = loads_json(job.output_json, {})
    output = {
        **existing,
        "schema_version": "upload_data_bundle_progress.v1",
        "status": "running",
        "progress_stage": stage,
        "progress_percent": max(0, min(100, int(percent))),
        "assistant_message": ja_label if japanese else en_label,
        "progress_detail": detail or {},
    }
    job.output_json = dumps_json(output)
    job.updated_at = utc_now()
    db.commit()


def update_select_primary_table_progress(
    db: Session,
    job: Job,
    *,
    stage: str,
    percent: int,
    response_locale: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    japanese = response_locale.lower().startswith("ja") if response_locale else False
    labels = {
        "validating": ("選択した主表を確認しています", "Checking the selected primary table"),
        "profiling": ("主表の列とprofileを作成しています", "Profiling the selected primary table"),
        "applying": ("主表の設定を反映しています", "Applying the primary table selection"),
        "finalizing": ("主表の変更を完了しています", "Finalizing the primary table change"),
    }
    ja_label, en_label = labels.get(stage, ("主表の変更を進めています", "Updating the primary table"))
    existing = loads_json(job.output_json, {})
    job.output_json = dumps_json(
        {
            **existing,
            "schema_version": "select_primary_table_progress.v1",
            "status": "running" if percent < 100 else "succeeded",
            "progress_stage": stage,
            "progress_percent": max(0, min(100, int(percent))),
            "assistant_message": ja_label if japanese else en_label,
            "progress_detail": detail or {},
        }
    )
    job.updated_at = utc_now()
    db.commit()


def staged_upload_artifact_for_job(db: Session, project: Project, artifact_id: str, stage_kind: str) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise ValueError(f"upload_data_bundle staged {stage_kind} artifact not found")
    metadata = loads_json(artifact.metadata_json, {})
    if artifact.asset_type != "upload_staging_file" or metadata.get("upload_stage_kind") != stage_kind:
        raise ValueError(f"upload_data_bundle staged {stage_kind} artifact has an invalid type")
    return artifact


def require_string_list(value: Any, job_type: str, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{job_type} requires {field_name}")
    return list(value)


def report_to_dict_for_worker(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "project_id": report.project_id,
        "report_type": report.report_type,
        "title": report.title,
        "summary": report.summary,
        "artifact_id": report.artifact_id,
        "source_asset_ids": loads_json(report.source_asset_ids_json, []),
        "status": report.status,
        "created_by_type": report.created_by_type,
        "created_at": report.created_at.isoformat(),
    }


def translate_tier3_content_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    source_type = payload.get("source_type")
    source_id = payload.get("source_id")
    source_artifact_id = payload.get("source_artifact_id")
    source_locale = payload.get("source_locale")
    target_locale = payload.get("target_locale")
    if not isinstance(source_type, str) or source_type not in {"artifact", "report"}:
        raise ValueError("translate_tier3_content requires source_type artifact or report")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("translate_tier3_content requires source_id")
    if not isinstance(source_artifact_id, str) or not source_artifact_id.strip():
        raise ValueError("translate_tier3_content requires source_artifact_id")
    if not isinstance(source_locale, str) or not source_locale.strip():
        raise ValueError("translate_tier3_content requires source_locale")
    if not isinstance(target_locale, str) or not target_locale.strip():
        raise ValueError("translate_tier3_content requires target_locale")
    artifact = db.get(Artifact, source_artifact_id)
    if artifact is None:
        raise ValueError("Source artifact not found")
    source_report = db.get(Report, source_id) if source_type == "report" else None
    if source_type == "report" and source_report is None:
        raise ValueError("Source report not found")
    result = translate_artifact(
        db,
        store=store,
        artifact=artifact,
        source_report=source_report,
        source_locale=source_locale,
        target_locale=target_locale,
        job_id=job.id,
    )
    translation_payload = {
        "source_type": source_type,
        "source_id": source_id,
        "source_artifact_id": source_artifact_id,
        "source_locale": source_locale,
        "target_locale": target_locale,
        "provider_status": result.provider_status,
        "translation_status": result.translation_status,
        "artifact": artifact_to_dict(result.translated_artifact),
        "report": report_to_dict_for_worker(result.translated_report) if result.translated_report else None,
        "preview": result.preview,
    }
    return {
        "translated_artifact_id": result.translated_artifact.id,
        "translated_report_id": result.translated_report.id if result.translated_report else None,
        "codex_translation_contract_artifact_id": result.contract_artifact.id,
        "provider_status": result.provider_status,
        "translation_status": result.translation_status,
        "artifact_id": result.translated_artifact.id,
        "artifact_ids": [result.contract_artifact.id, result.translated_artifact.id],
        "translation": translation_payload,
    }


def generate_user_avatar_candidates_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    del db, store
    payload = loads_json(job.input_json, {})
    prompt = payload.get("prompt")
    count = payload.get("count", 3)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("generate_user_avatar_candidates requires prompt")
    if not isinstance(count, int):
        raise ValueError("generate_user_avatar_candidates requires integer count")
    candidates = generate_user_avatar_candidates(prompt=prompt, count=count, user="tablex-user-avatar")
    return {
        "candidates": [
            {
                "id": candidate.id,
                "data_url": candidate.data_url,
                "model": candidate.model,
                "revised_prompt": candidate.revised_prompt,
            }
            for candidate in candidates
        ],
        "candidate_count": len(candidates),
        "worker_events": [
            {
                "worker_id": "avatar-generator",
                "display_name": "Avatar Generator",
                "status": "succeeded",
                "headline": "Avatar candidates generated",
                "detail": f"Generated {len(candidates)} user avatar candidate(s).",
                "target_tab": "Settings",
                "target_anchor": "user-avatar",
                "current_tokens": 40,
                "cumulative_tokens": 120,
                "token_series": [18, 45, 72, 120],
                "source": "avatar_generation_worker",
            }
        ],
    }


def settings_for_job_payload(job: Job, store: LocalArtifactStore) -> Settings:
    payload = loads_json(job.input_json, {})
    base = get_settings()
    data_dir = payload.get("data_dir")
    artifact_root = payload.get("artifact_root")
    if not isinstance(data_dir, str):
        return base
    return replace(
        base,
        data_dir=Path(data_dir),
        artifact_root=Path(artifact_root) if isinstance(artifact_root, str) else store.root,
    )


def benchmark_id_for_job(job: Job, job_type: str) -> str:
    payload = loads_json(job.input_json, {})
    benchmark_id = payload.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise ValueError(f"{job_type} requires benchmark_id")
    return benchmark_id


def download_public_benchmark_archive_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    benchmark_id = benchmark_id_for_job(job, "download_public_benchmark_archive")
    settings = settings_for_job_payload(job, store)
    manifest = download_public_benchmark_archive(
        settings,
        benchmark_id,
        overwrite=bool(payload.get("overwrite")),
    )
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="benchmark_public_download_manifest",
        name=f"benchmark_public_download_{benchmark_id}",
        filename="benchmark_public_download_manifest.json",
        payload=manifest,
        metadata={
            "benchmark_id": benchmark_id,
            "download_url": manifest["download_url"],
            "extracted_file_count": len(manifest["extracted_files"]),
            "skipped_file_count": len(manifest["skipped_files"]),
            "local_ready": manifest["local_status"]["ready"],
        },
    )
    return {
        "benchmark_id": benchmark_id,
        "artifact_id": artifact.id,
        "schema_version": manifest["schema_version"],
        "download_url": manifest["download_url"],
        "root_path": manifest["root_path"],
        "extracted_file_count": len(manifest["extracted_files"]),
        "skipped_file_count": len(manifest["skipped_files"]),
        "local_ready": manifest["local_status"]["ready"],
    }


def dataset_snapshot_to_dict_for_worker(dataset: DatasetSnapshot) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "artifact_id": dataset.artifact_id,
        "source_type": dataset.source_type,
        "source_ref": dataset.source_ref,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema_hash": dataset.schema_hash,
        "data_hash": dataset.data_hash,
        "created_at": dataset.created_at.isoformat(),
    }


def import_benchmark_dataset_for_worker(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    settings: Settings,
    benchmark_id: str,
    target_column: str | None = None,
    local_path: str | None = None,
    primary_file_name: str | None = None,
) -> dict[str, Any]:
    benchmark = raw_benchmark_dataset(benchmark_id)
    root = resolve_benchmark_root(settings, benchmark_id, local_path)
    local_status = validate_required_files(benchmark, root)
    primary_file = select_primary_file(benchmark, root, primary_file_name)
    catalog_target = (benchmark.get("primary_table") or {}).get("target_column")
    effective_target = target_column or (str(catalog_target) if catalog_target else None) or project.target_column
    if effective_target and effective_target != project.target_column:
        project.target_column = str(effective_target)

    primary_relative_path = relative_path(root, primary_file)
    version = next_artifact_version(db, project.id, "dataset_snapshot", f"benchmark_{benchmark_id}")
    artifact_dir, stored, content_hash = store.store_existing_file(
        org_id="local-org",
        project_id=project.id,
        asset_type="dataset_snapshot",
        name=f"benchmark_{benchmark_id}",
        version=version,
        source_path=primary_file,
        filename=primary_file.name,
        metadata={
            "project_id": project.id,
            "source_type": "benchmark_catalog",
            "benchmark_id": benchmark_id,
            "benchmark_name": benchmark.get("name"),
            "source_url": benchmark.get("source_url"),
            "primary_file": primary_relative_path,
        },
    )
    dataset_artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="dataset_snapshot",
        name=f"benchmark_{benchmark_id}",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "primary_path": str(stored.path),
            "source_type": "benchmark_catalog",
            "benchmark_id": benchmark_id,
            "benchmark_name": benchmark.get("name"),
            "source_url": benchmark.get("source_url"),
            "primary_file": primary_relative_path,
            "target_column": effective_target,
            "project_id": project.id,
        },
        version=version,
    )
    dataset = profile_dataset_artifact(
        db,
        store,
        project,
        dataset_artifact,
        str(effective_target) if effective_target else None,
        source_type="benchmark_catalog",
        source_ref=f"{benchmark_id}:{primary_relative_path}",
    )
    import_manifest = build_import_manifest(
        benchmark=benchmark,
        root=root,
        primary_file=primary_file,
        local_status=local_status,
        target_column=str(effective_target) if effective_target else None,
    )
    import_manifest["dataset_snapshot_id"] = dataset.id
    import_manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_import_manifest",
        name=f"benchmark_import_{benchmark_id}",
        filename="benchmark_import_manifest.json",
        payload=import_manifest,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "benchmark_id": benchmark_id,
            "primary_file": primary_relative_path,
        },
    )
    relational_catalog = build_relational_catalog(
        benchmark=benchmark,
        root=root,
        primary_file=primary_file,
        local_status=local_status,
        target_column=str(effective_target) if effective_target else None,
    )
    relational_catalog["dataset_snapshot_id"] = dataset.id
    relational_catalog_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_catalog",
        name=f"relational_catalog_{benchmark_id}",
        filename="relational_catalog.json",
        payload=relational_catalog,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "benchmark_id": benchmark_id,
            "table_count": relational_catalog["table_count"],
            "relationship_count": len(relational_catalog["relationships"]),
            "primary_file": primary_relative_path,
        },
    )
    supporting_tables = store_benchmark_supporting_table_artifacts(
        db,
        store=store,
        project_id=project.id,
        benchmark=benchmark,
        root=root,
        primary_file=primary_file,
        relational_catalog_artifact=relational_catalog_artifact,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=import_manifest_artifact.id,
        to_asset_type="dataset_snapshot",
        to_asset_id=dataset.id,
        relation_type="describes_source",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=relational_catalog_artifact.id,
        relation_type="profiles_table_bundle",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=import_manifest_artifact.id,
        to_asset_type="artifact",
        to_asset_id=relational_catalog_artifact.id,
        relation_type="summarizes_bundle",
    )
    set_data_understanding_phase_without_turning_agent_off(project)
    project.updated_at = utc_now()
    return {
        "benchmark": benchmark,
        "root": root,
        "local_status": local_status,
        "primary_file": primary_file,
        "primary_relative_path": primary_relative_path,
        "target_column": effective_target,
        "dataset": dataset,
        "dataset_artifact": dataset_artifact,
        "import_manifest_artifact": import_manifest_artifact,
        "relational_catalog_artifact": relational_catalog_artifact,
        "supporting_table_artifacts": supporting_tables.artifacts,
        "skipped_supporting_tables": supporting_tables.skipped,
    }


def import_benchmark_dataset_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "import_benchmark_dataset")
    benchmark_id = benchmark_id_for_job(job, "import_benchmark_dataset")
    settings = settings_for_job_payload(job, store)
    imported = import_benchmark_dataset_for_worker(
        db,
        store=store,
        project=project,
        settings=settings,
        benchmark_id=benchmark_id,
        target_column=payload.get("target_column") if isinstance(payload.get("target_column"), str) else None,
        local_path=payload.get("local_path") if isinstance(payload.get("local_path"), str) else None,
        primary_file_name=payload.get("primary_file") if isinstance(payload.get("primary_file"), str) else None,
    )
    benchmark = cast(dict[str, Any], imported["benchmark"])
    local_status = cast(dict[str, Any], imported["local_status"])
    dataset = cast(DatasetSnapshot, imported["dataset"])
    dataset_artifact = cast(Artifact, imported["dataset_artifact"])
    import_manifest_artifact = cast(Artifact, imported["import_manifest_artifact"])
    relational_catalog_artifact = cast(Artifact, imported["relational_catalog_artifact"])
    supporting_artifacts = cast(list[Artifact], imported["supporting_table_artifacts"])
    benchmark_payload = benchmark_to_dict(benchmark, settings=settings, include_status=True)
    benchmark_payload["local_status"] = local_status
    return {
        "benchmark": benchmark_payload,
        "dataset_snapshot": dataset_snapshot_to_dict_for_worker(dataset),
        "artifact": artifact_to_dict(dataset_artifact),
        "import_manifest_artifact": artifact_to_dict(import_manifest_artifact),
        "relational_catalog_artifact": artifact_to_dict(relational_catalog_artifact),
        "supporting_table_artifacts": [artifact_to_dict(artifact) for artifact in supporting_artifacts],
        "skipped_supporting_tables": cast(list[dict[str, Any]], imported["skipped_supporting_tables"]),
        "profile_job_id": job.id,
        "primary_file": str(imported["primary_relative_path"]),
        "benchmark_id": benchmark_id,
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset_artifact.id,
        "import_manifest_artifact_id": import_manifest_artifact.id,
        "relational_catalog_artifact_id": relational_catalog_artifact.id,
        "target_column": imported["target_column"],
        "table_count": int(cast(dict[str, Any], loads_json(relational_catalog_artifact.metadata_json, {})).get("table_count", 0)),
        "relationship_count": int(cast(dict[str, Any], loads_json(relational_catalog_artifact.metadata_json, {})).get("relationship_count", 0)),
        "supporting_table_artifact_ids": [artifact.id for artifact in supporting_artifacts],
        "artifact_ids": [
            dataset_artifact.id,
            import_manifest_artifact.id,
            relational_catalog_artifact.id,
            *[artifact.id for artifact in supporting_artifacts],
        ],
    }


def run_benchmark_fixture_smoke_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "run_benchmark_fixture_smoke")
    benchmark_id = benchmark_id_for_job(job, "run_benchmark_fixture_smoke")
    settings = settings_for_job_payload(job, store)
    fixture = generate_benchmark_fixture(
        settings,
        benchmark_id,
        overwrite=bool(payload.get("overwrite")),
    )
    if not fixture["fixture_matches_expected"]:
        raise ValueError(
            "Existing benchmark files do not match the Tablex fixture. "
            "Use overwrite=true to replace fixture files, or run normal benchmark import manually."
        )
    imported = import_benchmark_dataset_for_worker(
        db,
        store=store,
        project=project,
        settings=settings,
        benchmark_id=benchmark_id,
        target_column=payload.get("target_column") if isinstance(payload.get("target_column"), str) else None,
    )
    dataset = cast(DatasetSnapshot, imported["dataset"])
    quality = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
    candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
    comparison_artifact = create_evaluation_scenario_comparison(
        db,
        store=store,
        project=project,
        dataset=dataset,
        candidates=list(candidates),
    )
    primary_candidate = next((item for item in candidates if item.status == "primary_candidate"), candidates[0])
    spec = promote_candidate_to_spec(db, store=store, candidate=primary_candidate)
    review = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=True)
    if review.blocked:
        raise ValueError("Fixture EvaluationSpec approval was blocked")
    approve_spec(spec)
    approved_artifact = write_spec_artifact(db, store, spec)
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="artifact",
        from_asset_id=review.artifact.id,
        to_asset_type="evaluation_spec",
        to_asset_id=spec.id,
        relation_type="supports_approval",
    )
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="evaluation_spec",
        from_asset_id=spec.id,
        to_asset_type="artifact",
        to_asset_id=approved_artifact.id,
        relation_type="produces",
    )
    split = generate_split_manifest(db, store=store, spec=spec)
    strategy = create_baseline_strategy_plan(
        db,
        store=store,
        project=project,
        evaluation_spec=spec,
        split_manifest=split,
    )
    research_plan = create_research_plan(
        db,
        store=store,
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
    )
    supporting_artifacts = cast(list[Artifact], imported["supporting_table_artifacts"])
    scenario = create_benchmark_scenario_pack(
        db,
        store=store,
        project=project,
        benchmark=raw_benchmark_dataset(benchmark_id),
        local_status=fixture["local_status"],
        fixture=fixture,
        dataset=dataset,
        supporting_table_artifacts=supporting_artifacts,
        skipped_supporting_tables=cast(list[dict[str, Any]], imported["skipped_supporting_tables"]),
    )
    dataset_artifact = cast(Artifact, imported["dataset_artifact"])
    import_manifest_artifact = cast(Artifact, imported["import_manifest_artifact"])
    relational_catalog_artifact = cast(Artifact, imported["relational_catalog_artifact"])
    artifact_ids = [
        dataset_artifact.id,
        import_manifest_artifact.id,
        relational_catalog_artifact.id,
        *[artifact.id for artifact in supporting_artifacts],
        *quality.artifact_ids,
        comparison_artifact.id,
        review.artifact.id,
        approved_artifact.id,
        split.artifact_id,
        strategy.artifact.id,
        research_plan.artifact.id,
        scenario.pack_artifact.id,
        scenario.report_artifact.id,
    ]
    return {
        "benchmark_id": benchmark_id,
        "fixture": fixture,
        "dataset_snapshot_id": dataset.id,
        "quality_gate": quality.gate,
        "evaluation_candidate_ids": [candidate.id for candidate in candidates],
        "evaluation_scenario_comparison_artifact_id": comparison_artifact.id,
        "evaluation_spec_id": spec.id,
        "approval_review_artifact_id": review.artifact.id,
        "split_manifest_id": split.id,
        "baseline_strategy_plan_artifact_id": strategy.artifact.id,
        "research_plan_artifact_id": research_plan.artifact.id,
        "benchmark_scenario_pack_artifact_id": scenario.pack_artifact.id,
        "benchmark_scenario_report_artifact_id": scenario.report_artifact.id,
        "artifact_ids": artifact_ids,
    }


def run_public_benchmark_workflow_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "run_public_benchmark_workflow")
    benchmark_id = benchmark_id_for_job(job, "run_public_benchmark_workflow")
    settings = settings_for_job_payload(job, store)
    download_manifest = download_public_benchmark_archive(
        settings,
        benchmark_id,
        overwrite=bool(payload.get("overwrite")),
    )
    download_artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="benchmark_public_download_manifest",
        name=f"benchmark_public_download_{benchmark_id}",
        filename="benchmark_public_download_manifest.json",
        payload=download_manifest,
        metadata={
            "benchmark_id": benchmark_id,
            "download_url": download_manifest["download_url"],
            "archive_type": download_manifest["archive_type"],
            "extracted_file_count": len(download_manifest["extracted_files"]),
            "skipped_file_count": len(download_manifest["skipped_files"]),
            "local_ready": download_manifest["local_status"]["ready"],
        },
    )
    imported = import_benchmark_dataset_for_worker(
        db,
        store=store,
        project=project,
        settings=settings,
        benchmark_id=benchmark_id,
        target_column=payload.get("target_column") if isinstance(payload.get("target_column"), str) else None,
    )
    dataset = cast(DatasetSnapshot, imported["dataset"])
    quality = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
    candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
    comparison_artifact = create_evaluation_scenario_comparison(
        db,
        store=store,
        project=project,
        dataset=dataset,
        candidates=list(candidates),
    )
    primary_candidate = next((item for item in candidates if item.status == "primary_candidate"), candidates[0])
    spec = promote_candidate_to_spec(db, store=store, candidate=primary_candidate)
    review = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=True)
    if review.blocked:
        raise ValueError("Public benchmark EvaluationSpec approval was blocked")
    approve_spec(spec)
    approved_artifact = write_spec_artifact(db, store, spec)
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="artifact",
        from_asset_id=review.artifact.id,
        to_asset_type="evaluation_spec",
        to_asset_id=spec.id,
        relation_type="supports_approval",
    )
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="evaluation_spec",
        from_asset_id=spec.id,
        to_asset_type="artifact",
        to_asset_id=approved_artifact.id,
        relation_type="produces",
    )
    split = generate_split_manifest(db, store=store, spec=spec)
    strategy = create_baseline_strategy_plan(
        db,
        store=store,
        project=project,
        evaluation_spec=spec,
        split_manifest=split,
    )
    baseline = run_baseline(
        db,
        store=store,
        project=project,
        evaluation_spec=spec,
        split_manifest=split,
    )
    diagnostics = analyze_run_diagnostics(db, store=store, run=baseline.run)
    run_report = draft_run_report(db, store=store, run=baseline.run)
    dashboard = create_project_visualization_dashboard(db, store=store, project=project)
    insights = generate_project_insights(db, store=store, project=project)
    decision = create_decision_dashboard(db, store=store, project=project)
    supporting_artifacts = cast(list[Artifact], imported["supporting_table_artifacts"])
    scenario = create_benchmark_scenario_pack(
        db,
        store=store,
        project=project,
        benchmark=raw_benchmark_dataset(benchmark_id),
        local_status=download_manifest["local_status"],
        dataset=dataset,
        supporting_table_artifacts=supporting_artifacts,
        skipped_supporting_tables=cast(list[dict[str, Any]], imported["skipped_supporting_tables"]),
    )
    import_manifest_artifact = cast(Artifact, imported["import_manifest_artifact"])
    relational_catalog_artifact = cast(Artifact, imported["relational_catalog_artifact"])
    dataset_artifact = cast(Artifact, imported["dataset_artifact"])
    artifact_ids = list(
        dict.fromkeys(
            [
                download_artifact.id,
                dataset_artifact.id,
                import_manifest_artifact.id,
                relational_catalog_artifact.id,
                *[artifact.id for artifact in supporting_artifacts],
                *quality.artifact_ids,
                comparison_artifact.id,
                review.artifact.id,
                approved_artifact.id,
                split.artifact_id,
                strategy.artifact.id,
                *baseline.artifact_ids,
                *diagnostics.artifact_ids,
                run_report.artifact.id,
                *dashboard.artifact_ids,
                insights.artifact.id,
                decision.dashboard_artifact.id,
                decision.report_artifact.id,
                *decision.artifact_ids,
                scenario.pack_artifact.id,
                scenario.report_artifact.id,
            ]
        )
    )
    return {
        "benchmark_id": benchmark_id,
        "download_manifest_artifact_id": download_artifact.id,
        "download_manifest_schema": download_manifest["schema_version"],
        "dataset_snapshot_id": dataset.id,
        "quality_gate": quality.gate,
        "evaluation_candidate_ids": [candidate.id for candidate in candidates],
        "evaluation_scenario_comparison_artifact_id": comparison_artifact.id,
        "evaluation_spec_id": spec.id,
        "approval_review_artifact_id": review.artifact.id,
        "split_manifest_id": split.id,
        "baseline_strategy_plan_artifact_id": strategy.artifact.id,
        "experiment_run_id": baseline.run.id,
        "model_version_id": baseline.model_version_id,
        "metrics": baseline.metrics,
        "diagnostics_artifact_ids": diagnostics.artifact_ids,
        "run_report_id": run_report.report.id,
        "run_report_artifact_id": run_report.artifact.id,
        "visualization_ids": [visualization.id for visualization in dashboard.visualizations],
        "insight_ids": [insight.id for insight in insights.insights],
        "decision_dashboard_artifact_id": decision.dashboard_artifact.id,
        "decision_report_id": decision.report.id,
        "decision_report_artifact_id": decision.report_artifact.id,
        "benchmark_scenario_pack_artifact_id": scenario.pack_artifact.id,
        "benchmark_scenario_report_artifact_id": scenario.report_artifact.id,
        "artifact_ids": artifact_ids,
        "worker_events": [
            {
                "worker_id": "public-benchmark-workflow",
                "display_name": "Benchmark Worker",
                "status": "succeeded",
                "headline": "Public benchmark workflow completed",
                "detail": "Downloaded, imported, evaluated, trained a baseline, and registered reporting artifacts.",
                "job_id": job.id,
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "benchmark_workflow_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "download", "tokens": 120},
                        {"step": "import", "tokens": 160},
                        {"step": "evaluate", "tokens": 180},
                        {"step": "train", "tokens": 220},
                        {"step": "report", "tokens": 180},
                    ],
                },
            }
        ],
    }


def latest_benchmark_import_local_status_for_worker(
    db: Session,
    *,
    project_id: str,
    benchmark_id: str,
) -> dict[str, Any] | None:
    artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type == "benchmark_import_manifest",
            Artifact.metadata_json.contains(benchmark_id),
        )
        .order_by(Artifact.created_at.desc())
    )
    if artifact is None:
        return None
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return None
    local_status = payload.get("local_status")
    return cast(dict[str, Any], local_status) if isinstance(local_status, dict) else None


def create_benchmark_scenario_pack_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_benchmark_scenario_pack")
    benchmark_id = benchmark_id_for_job(job, "create_benchmark_scenario_pack")
    settings = settings_for_job_payload(job, store)
    benchmark = raw_benchmark_dataset(benchmark_id)
    root = default_benchmark_root(settings, benchmark_id)
    local_status = latest_benchmark_import_local_status_for_worker(
        db,
        project_id=project.id,
        benchmark_id=benchmark_id,
    ) or inspect_benchmark_local_files(benchmark, root)
    result = create_benchmark_scenario_pack(
        db,
        store=store,
        project=project,
        benchmark=benchmark,
        local_status=local_status,
    )
    return {
        "benchmark_id": benchmark_id,
        "schema_version": result.pack["schema_version"],
        "scenario_kind": result.pack["scenario"]["kind"],
        "benchmark_scenario_pack_artifact_id": result.pack_artifact.id,
        "benchmark_scenario_report_artifact_id": result.report_artifact.id,
        "dataset_snapshot_id": result.pack["dataset"].get("dataset_snapshot_id"),
        "supporting_table_artifact_count": len(result.pack["supporting_table_artifacts"]),
        "artifact_id": result.pack_artifact.id,
        "artifact_ids": [result.pack_artifact.id, result.report_artifact.id],
    }


def create_benchmark_collection_plan_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_benchmark_collection_plan")
    settings = settings_for_job_payload(job, store)
    result = create_benchmark_collection_plan(
        db,
        store=store,
        project=project,
        settings=settings,
        job=job,
    )
    return {
        "schema_version": result.plan["schema_version"],
        "benchmark_count": result.plan["summary"]["benchmark_count"],
        "credentialed_count": result.plan["summary"]["credentialed_count"],
        "public_direct_count": result.plan["summary"]["public_direct_count"],
        "fixture_available_count": result.plan["summary"]["fixture_available_count"],
        "local_ready_count": result.plan["summary"]["local_ready_count"],
        "multitable_count": result.plan["summary"]["multitable_count"],
        "time_series_count": result.plan["summary"]["time_series_count"],
        "benchmark_collection_plan_artifact_id": result.plan_artifact.id,
        "benchmark_collection_report_id": result.report.id,
        "benchmark_collection_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.plan_artifact.id,
        "artifact_ids": result.artifact_ids,
    }


def create_relational_feature_plan_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_relational_feature_plan")
    result = create_relational_feature_plan(db, store=store, project=project, job=job)
    return {
        "schema_version": result.plan["schema_version"],
        "benchmark_id": result.plan["source_summary"].get("benchmark_id"),
        "relational_feature_plan_artifact_id": result.plan_artifact.id,
        "relational_feature_report_id": result.report.id,
        "relational_feature_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.plan_artifact.id,
        "artifact_ids": result.artifact_ids,
        "table_count": result.plan["table_coverage"]["table_count"],
        "supporting_table_count": result.plan["table_coverage"]["supporting_table_count"],
        "relationship_count": result.plan["table_coverage"]["relationship_count"],
        "aggregation_candidate_count": len(result.plan["aggregation_candidates"]),
        "high_risk_count": len([item for item in result.plan["risk_register"] if item["risk_level"] == "high"]),
    }


def build_relational_feature_recipe_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "build_relational_feature_recipe")
    result = build_relational_feature_recipe(db, store=store, project=project, job=job)
    return {
        "schema_version": result.recipe["schema_version"],
        "benchmark_id": result.recipe["source_summary"].get("benchmark_id"),
        "relational_feature_recipe_artifact_id": result.recipe_artifact.id,
        "relational_feature_preview_artifact_id": result.preview_artifact.id,
        "relational_feature_preview_profile_artifact_id": result.preview_profile_artifact.id,
        "relational_feature_recipe_report_id": result.report.id,
        "relational_feature_recipe_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.recipe_artifact.id,
        "artifact_ids": result.artifact_ids,
        "generated_feature_count": len(result.preview_profile["generated_feature_columns"]),
        "executed_step_count": len(result.recipe["steps"]),
        "deferred_step_count": len(result.recipe["deferred_steps"]),
        "preview_row_count": result.preview_profile["preview_row_count"],
    }


def diagnose_relational_feature_scenarios_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "diagnose_relational_feature_scenarios")
    result = diagnose_relational_feature_scenarios(db, store=store, project=project, job=job)
    summary = result.diagnostics["preview_summary"]
    deferred = result.diagnostics["deferred_reason_summary"]
    return {
        "schema_version": result.diagnostics["schema_version"],
        "benchmark_id": result.diagnostics["source_summary"].get("benchmark_id"),
        "relational_feature_scenario_diagnostics_artifact_id": result.diagnostics_artifact.id,
        "relational_feature_scenario_report_id": result.report.id,
        "relational_feature_scenario_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.diagnostics_artifact.id,
        "artifact_ids": result.artifact_ids,
        "generated_feature_count": summary["generated_feature_count"],
        "usable_feature_count": summary["usable_feature_count"],
        "constant_feature_count": summary["constant_feature_count"],
        "high_missing_feature_count": summary["high_missing_feature_count"],
        "deferred_step_count": deferred["total_deferred_step_count"],
        "scenario_count": len(result.diagnostics["scenario_comparison"]),
    }


def create_benchmark_evidence_pack_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_benchmark_evidence_pack")
    settings = settings_for_job_payload(job, store)
    result = create_benchmark_evidence_pack(
        db,
        store=store,
        project=project,
        settings=settings,
        job=job,
    )
    return {
        "benchmark_count": result.pack["benchmark_count"],
        "benchmark_ids": [entry["benchmark_id"] for entry in result.pack["benchmarks"]],
        "benchmark_evidence_pack_artifact_id": result.pack_artifact.id,
        "benchmark_evidence_report_id": result.report.id,
        "benchmark_evidence_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_id": result.pack_artifact.id,
        "artifact_ids": result.artifact_ids,
    }


def probe_kaggle_benchmark_access_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    benchmark_id = benchmark_id_for_job(job, "probe_kaggle_benchmark_access")
    benchmark = raw_benchmark_dataset(benchmark_id)
    payload = probe_kaggle_benchmark_access(benchmark)
    credential_status = cast(dict[str, Any], payload["credential_status"])
    probe = cast(dict[str, Any], payload["probe"])
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="kaggle_credential_probe",
        name=f"kaggle_credential_probe_{benchmark_id}",
        filename="kaggle_credential_probe.json",
        payload=payload,
        metadata={
            "benchmark_id": benchmark_id,
            "competition_slug": payload["competition_slug"],
            "probe_status": probe["status"],
            "credential_available": credential_status["available"],
            "credential_sources": credential_status["credential_sources"],
            "auth_schemes": credential_status["auth_schemes"],
            "username_available": credential_status["username_available"],
            "can_access_competition_files": probe["can_access_competition_files"],
            "http_status": probe["http_status"],
            "secret_value_artifacted": False,
            "agent_runner_access": False,
        },
    )
    return {
        "schema_version": payload["schema_version"],
        "benchmark_id": benchmark_id,
        "competition_slug": payload["competition_slug"],
        "probe_status": probe["status"],
        "credential_available": credential_status["available"],
        "credential_sources": credential_status["credential_sources"],
        "auth_schemes": credential_status["auth_schemes"],
        "username_available": credential_status["username_available"],
        "can_access_competition_files": probe["can_access_competition_files"],
        "http_status": probe["http_status"],
        "attempt_count": probe["attempt_count"],
        "kaggle_probe_artifact_id": artifact.id,
        "artifact_id": artifact.id,
        "artifact_ids": [artifact.id],
    }


def fetch_kaggle_competition_inventory_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    benchmark_id = benchmark_id_for_job(job, "fetch_kaggle_competition_inventory")
    benchmark = raw_benchmark_dataset(benchmark_id)
    payload = fetch_kaggle_competition_inventory(benchmark)
    credential_status = cast(dict[str, Any], payload["credential_status"])
    inventory = cast(dict[str, Any], payload["inventory"])
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="kaggle_file_inventory",
        name=f"kaggle_file_inventory_{benchmark_id}",
        filename="kaggle_file_inventory.json",
        payload=payload,
        metadata={
            "benchmark_id": benchmark_id,
            "competition_slug": payload["competition_slug"],
            "inventory_status": inventory["status"],
            "file_count": inventory["file_count"],
            "total_size_bytes": inventory["total_size_bytes"],
            "required_present_count": inventory["required_present_count"],
            "required_missing_count": inventory["required_missing_count"],
            "recommended_present_count": inventory["recommended_present_count"],
            "holdout_file_count": inventory["holdout_file_count"],
            "credential_available": credential_status["available"],
            "credential_sources": credential_status["credential_sources"],
            "auth_schemes": credential_status["auth_schemes"],
            "secret_value_artifacted": False,
            "agent_runner_access": False,
        },
    )
    return {
        "schema_version": payload["schema_version"],
        "benchmark_id": benchmark_id,
        "competition_slug": payload["competition_slug"],
        "inventory_status": inventory["status"],
        "credential_available": credential_status["available"],
        "file_count": inventory["file_count"],
        "total_size_bytes": inventory["total_size_bytes"],
        "required_present_count": inventory["required_present_count"],
        "required_missing_count": inventory["required_missing_count"],
        "recommended_present_count": inventory["recommended_present_count"],
        "holdout_file_count": inventory["holdout_file_count"],
        "attempt_count": inventory["attempt_count"],
        "kaggle_inventory_artifact_id": artifact.id,
        "artifact_id": artifact.id,
        "artifact_ids": [artifact.id],
    }


def download_kaggle_selected_files_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    benchmark_id = benchmark_id_for_job(job, "download_kaggle_selected_files")
    benchmark = raw_benchmark_dataset(benchmark_id)
    settings = settings_for_job_payload(job, store)
    root = default_benchmark_root(settings, benchmark_id)
    selected_files = payload.get("selected_files") if isinstance(payload.get("selected_files"), list) else []
    manifest = download_kaggle_selected_files(
        benchmark,
        root=root,
        selected_files=[str(item) for item in selected_files],
        include_required=bool(payload.get("include_required")),
        include_recommended=bool(payload.get("include_recommended")),
        include_holdout=bool(payload.get("include_holdout")),
        overwrite=bool(payload.get("overwrite")),
        max_total_bytes=payload.get("max_total_bytes") if isinstance(payload.get("max_total_bytes"), int) else None,
    )
    local_status = inspect_benchmark_local_files(benchmark, root)
    readiness = benchmark_import_readiness(benchmark, root, local_status)
    manifest["local_status"] = local_status
    manifest["import_readiness"] = readiness
    credential_status = cast(dict[str, Any], manifest["credential_status"])
    download = cast(dict[str, Any], manifest["download"])
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="kaggle_selective_download_manifest",
        name=f"kaggle_selective_download_{benchmark_id}",
        filename="kaggle_selective_download_manifest.json",
        payload=manifest,
        metadata={
            "benchmark_id": benchmark_id,
            "competition_slug": manifest["competition_slug"],
            "download_status": download["status"],
            "downloaded_count": download["downloaded_count"],
            "skipped_count": download["skipped_count"],
            "downloaded_bytes": download["downloaded_bytes"],
            "local_ready": local_status["ready"],
            "credential_available": credential_status["available"],
            "secret_value_artifacted": False,
            "agent_runner_access": False,
        },
    )
    return {
        "schema_version": manifest["schema_version"],
        "benchmark_id": benchmark_id,
        "competition_slug": manifest["competition_slug"],
        "download_status": download["status"],
        "downloaded_count": download["downloaded_count"],
        "skipped_count": download["skipped_count"],
        "downloaded_bytes": download["downloaded_bytes"],
        "local_ready": local_status["ready"],
        "can_import_now": readiness["can_import_now"],
        "kaggle_download_manifest_artifact_id": artifact.id,
        "artifact_id": artifact.id,
        "artifact_ids": [artifact.id],
    }


def dataset_for_job_payload(db: Session, job: Job, job_type: str) -> DatasetSnapshot:
    payload = loads_json(job.input_json, {})
    dataset_id = payload.get("dataset_snapshot_id")
    dataset = db.get(DatasetSnapshot, dataset_id) if isinstance(dataset_id, str) else None
    if dataset is None:
        raise ValueError(f"{job_type} requires an existing dataset_snapshot_id")
    return dataset


def evaluation_spec_for_job_payload(db: Session, job: Job, job_type: str) -> EvaluationSpec:
    payload = loads_json(job.input_json, {})
    spec_id = payload.get("evaluation_spec_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    if spec is None:
        raise ValueError(f"{job_type} requires an existing evaluation_spec_id")
    return spec


def design_evaluation_candidates_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "design_evaluation_candidates")
    dataset = dataset_for_job_payload(db, job, "design_evaluation_candidates")
    candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
    return {"evaluation_candidate_ids": [candidate.id for candidate in candidates]}


def compare_evaluation_scenarios_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "compare_evaluation_scenarios")
    dataset = dataset_for_job_payload(db, job, "compare_evaluation_scenarios")
    candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
    artifact = create_evaluation_scenario_comparison(
        db,
        store=store,
        project=project,
        dataset=dataset,
        candidates=list(candidates),
    )
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_id": artifact.id,
        "candidate_count": len(candidates),
        "recommended_candidate_id": metadata.get("recommended_candidate_id"),
    }


def review_evaluation_approval_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    spec = evaluation_spec_for_job_payload(db, job, "review_evaluation_approval")
    result = create_evaluation_approval_review(
        db,
        store=store,
        spec=spec,
        approval_intent=bool(payload.get("approval_intent")),
    )
    decision = result.payload["decision_support"]
    return {
        "evaluation_spec_id": spec.id,
        "artifact_id": result.artifact.id,
        "review_status": decision["review_status"],
        "blocked": decision["blocked"],
        "blocker_count": decision["blocker_count"],
        "warning_count": decision["warning_count"],
    }


def profile_dataset_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "profile_dataset")
    artifact_id = payload.get("artifact_id")
    source_dataset_id = payload.get("dataset_snapshot_id")
    source_dataset = db.get(DatasetSnapshot, source_dataset_id) if isinstance(source_dataset_id, str) else None
    if not isinstance(artifact_id, str) and source_dataset is not None:
        artifact_id = source_dataset.artifact_id
    dataset_artifact = db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
    if dataset_artifact is None:
        raise ValueError("profile_dataset requires an existing artifact_id or dataset_snapshot_id")
    target_column = payload.get("target_column") if isinstance(payload.get("target_column"), str) else project.target_column
    source_type = payload.get("source_type") if isinstance(payload.get("source_type"), str) else None
    source_ref = payload.get("source_ref") if isinstance(payload.get("source_ref"), str) else None
    if source_type is None and source_dataset is not None:
        source_type = source_dataset.source_type
    if source_ref is None and source_dataset is not None:
        source_ref = source_dataset.source_ref
    dataset = profile_dataset_artifact(
        db,
        store,
        project,
        dataset_artifact,
        target_column,
        source_type=source_type or "upload",
        source_ref=source_ref,
    )
    set_data_understanding_phase_without_turning_agent_off(project)
    project.updated_at = utc_now()
    return {
        "dataset_snapshot_id": dataset.id,
        "source_dataset_snapshot_id": source_dataset.id if source_dataset is not None else None,
        "artifact_id": dataset_artifact.id,
        "target_column": target_column,
    }


def infer_assumptions_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    del store
    project = project_for_job(db, job, "infer_assumptions")
    unresolved = db.scalars(select(Question).where(Question.project_id == project.id, Question.status == "open")).all()
    return {
        "unanswered_questions": len(unresolved),
        "policy": "fallbacks_already_materialized_in_assumptions",
    }


def latest_research_brief(db: Session, project_id: str) -> ResearchBrief | None:
    return db.scalar(
        select(ResearchBrief).where(ResearchBrief.project_id == project_id).order_by(ResearchBrief.created_at.desc())
    )


def idea_for_job(db: Session, job: Job, job_type: str) -> Idea:
    payload = loads_json(job.input_json, {})
    idea_id = payload.get("idea_id")
    idea = db.get(Idea, idea_id) if isinstance(idea_id, str) else None
    if idea is None:
        raise ValueError(f"{job_type} requires an existing idea_id")
    if job.project_id is not None and idea.project_id != job.project_id:
        raise ValueError(f"{job_type} project does not match the Idea")
    return idea


def create_research_source_pack_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_research_source_pack")
    dataset = latest_dataset(db, project.id)
    spec = latest_approved_spec(db, project.id)
    result = create_research_source_pack(
        db,
        store=store,
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
        job=job,
    )
    return {
        "schema_version": result.pack["schema_version"],
        "research_plan_artifact_id": result.research_plan_artifact.id,
        "research_source_pack_artifact_id": result.pack_artifact.id,
        "research_source_report_id": result.report.id,
        "research_source_report_artifact_id": result.report_artifact.id,
        "evidence_id": result.evidence.id,
        "query_count": len(result.pack.get("controlled_queries", [])),
        "project_source_count": len(result.pack.get("project_sources", [])),
        "library_source_count": len(result.pack.get("library_sources", [])),
        "network_default": result.pack["source_policy"]["network_default"],
        "artifact_ids": [result.pack_artifact.id, result.report_artifact.id],
    }


def run_research_source_pack_stub_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    artifact_id = payload.get("research_source_pack_artifact_id")
    source_pack_artifact = db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
    if source_pack_artifact is None:
        raise ValueError("Research Source Pack artifact not found")
    if source_pack_artifact.asset_type != "research_source_pack":
        raise ValueError("Artifact is not a research_source_pack")
    project = project_for_job(db, job, "run_research_source_pack_stub")
    result = run_research_source_pack_local_stub(
        db,
        store=store,
        project=project,
        source_pack_artifact=source_pack_artifact,
        job=job,
    )
    return {
        "research_source_pack_artifact_id": source_pack_artifact.id,
        "research_run_manifest_artifact_id": result.manifest_artifact.id,
        "research_findings_report_id": result.findings_report.id,
        "research_findings_report_artifact_id": result.findings_report_artifact.id,
        "source_citation_manifest_artifact_id": result.citation_manifest_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_ids": result.artifact_ids,
        "runner": result.manifest["runner"],
        "execution_status": result.manifest["execution_status"],
        "query_count": result.manifest["query_count"],
        "external_network_accessed": result.manifest["external_network_accessed"],
        "connector_credentials_materialized": result.manifest["connector_credentials_materialized"],
    }


def create_research_synthesis_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_research_synthesis")
    result = create_research_finding_synthesis(db, store=store, project=project, job=job)
    return {
        "schema_version": result.synthesis["schema_version"],
        "research_finding_synthesis_artifact_id": result.artifact.id,
        "research_finding_synthesis_report_id": result.report.id,
        "research_finding_synthesis_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "evidence_id": result.evidence.id,
        "artifact_ids": result.artifact_ids,
        "finding_count": result.synthesis["summary"]["finding_count"],
        "citation_count": result.synthesis["citation_audit"]["citation_count"],
        "external_network_accessed": result.synthesis["citation_audit"]["external_network_accessed"],
        "has_only_stub_findings": result.synthesis["summary"]["has_only_stub_findings"],
    }


def generate_research_brief_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "generate_research_brief")
    dataset = latest_dataset(db, project.id)
    spec = latest_approved_spec(db, project.id)
    question = payload.get("question") if isinstance(payload.get("question"), str) else None
    result = generate_research_brief(
        db,
        store=store,
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
        question=question,
    )
    return {"research_brief_id": result.brief.id, "artifact_id": result.artifact.id}


def generate_approach_candidates_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "generate_approach_candidates")
    dataset = latest_dataset(db, project.id)
    spec = latest_approved_spec(db, project.id)
    brief = latest_research_brief(db, project.id)
    result = generate_approach_candidates(
        db,
        store=store,
        project=project,
        research_brief=brief,
        dataset=dataset,
        evaluation_spec=spec,
    )
    return {"idea_ids": [idea.id for idea in result.ideas], "artifact_ids": result.artifact_ids}


def prepare_agent_context_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    idea = idea_for_job(db, job, "prepare_agent_context")
    project = project_for_job(db, job, "prepare_agent_context")
    result = prepare_idea_agent_context_pack(db, store=store, project=project, idea=idea, job=job)
    return {
        "idea_id": idea.id,
        "context_pack_id": result.context_pack["id"],
        "artifact_id": result.artifact.id,
        "schema_version": result.context_pack["schema_version"],
        "asset_recommendation_count": len(result.context_pack["asset_recommendations"]),
        "materialized_library_asset_count": len(result.context_pack["materialized_library_assets"]),
    }


def create_experiment_plan_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    idea = idea_for_job(db, job, "create_experiment_plan")
    project = project_for_job(db, job, "create_experiment_plan")
    result = create_experiment_plan_for_idea(db, store=store, project=project, idea=idea, job=job)
    return {
        "idea_id": idea.id,
        "plan_id": result.plan["id"],
        "artifact_id": result.artifact.id,
        "evidence_id": result.evidence_id,
        "insight_id": result.insight_id,
        "readiness": result.plan["readiness"],
    }


def run_agent_task_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    idea = idea_for_job(db, job, "run_agent_task")
    project = project_for_job(db, job, "run_agent_task")
    result = run_idea_agent_task_stub(db, store=store, project=project, idea=idea, job=job)
    return {
        "idea_id": idea.id,
        "agent_status": result.agent_result.status,
        "agent_final_message": result.agent_result.final_message,
        "artifact_ids": result.artifact_ids,
        "workspace_artifact_id": result.workspace_artifact_id,
        "ingested_artifact_ids": result.ingested_artifact_ids,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "experiment_run_id": result.experiment_ingestion.experiment_run_id,
        "agent_metrics_artifact_id": result.experiment_ingestion.metrics_artifact_id,
        "agent_feature_recipe_artifact_id": result.experiment_ingestion.feature_recipe_artifact_id,
        "approach_decision_trace_artifact_id": result.approach_decision_trace_artifact_id,
        "source_citation_manifest_artifact_id": result.experiment_ingestion.citation_manifest_artifact_id,
        "citation_audit_report_id": result.experiment_ingestion.citation_audit_report_id,
        "citation_audit_report_artifact_id": result.experiment_ingestion.citation_audit_report_artifact_id,
        "citation_evidence_id": result.experiment_ingestion.citation_evidence_id,
        "citation_visualization_id": result.experiment_ingestion.citation_visualization_id,
        "citation_visualization_artifact_id": result.experiment_ingestion.citation_visualization_artifact_id,
        "visualization_ids": result.experiment_ingestion.visualization_ids,
        "requires_human_review": result.agent_result.requires_human_review,
    }


def analyze_data_quality_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    dataset = dataset_for_job_payload(db, job, "analyze_data_quality")
    project = db.get(Project, dataset.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_ids": result.artifact_ids,
        "gate": result.gate,
        "evidence_ids": result.evidence_ids,
        "assumption_ids": result.assumption_ids,
        "question_ids": result.question_ids,
        "insight_id": result.insight_id,
    }


def run_eda_review_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    dataset = dataset_for_job_payload(db, job, "run_eda_review")
    result = create_dataset_eda_review(db, store=store, dataset=dataset)
    return {
        "schema_version": result.review["schema_version"],
        "dataset_snapshot_id": dataset.id,
        "eda_review_bundle_artifact_id": result.bundle_artifact.id,
        "eda_review_report_id": result.report.id,
        "eda_review_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "eda_review_figure_artifact_ids": [artifact.id for artifact in result.figure_artifacts],
        "evidence_id": result.evidence.id,
        "insight_id": result.insight.id,
        "artifact_id": result.bundle_artifact.id,
        "artifact_ids": result.artifact_ids,
        "quality_score": result.review["summary"]["quality_score"],
        "target_column": result.review["summary"].get("target_column"),
    }


def create_adaptive_strategy_brief_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_adaptive_strategy_brief")
    payload = loads_json(job.input_json, {})
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    result = create_adaptive_strategy_brief(db, store=store, project=project, job=job, locale=locale)
    return {
        "schema_version": result.brief["schema_version"],
        "response_locale": result.brief.get("response_locale"),
        "adaptive_strategy_brief_artifact_id": result.artifact.id,
        "adaptive_strategy_report_id": result.report.id,
        "adaptive_strategy_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": result.artifact_ids,
        "recommended_action_type": result.brief["recommended_next_action"]["action_type"],
        "recommended_label": result.brief["recommended_next_action"]["label"],
        "lane_count": len(result.brief["candidate_lanes"]),
        "worker_events": [
            approach_worker_event(
                job,
                project,
                status="succeeded",
                headline="Adaptive strategy brief created",
                detail="Registered the strategy brief, report, and visualization artifacts.",
                target_anchor="strategy-brief-focus",
            )
        ],
    }


def plan_research_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "plan_research")
    dataset = latest_dataset(db, project.id)
    spec = latest_approved_spec(db, project.id)
    result = create_research_plan(
        db,
        store=store,
        project=project,
        dataset=dataset,
        evaluation_spec=spec,
    )
    return {
        "schema_version": result.plan["schema_version"],
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "query_count": len(result.plan.get("query_plan", [])),
        "recommended_asset_count": len(result.plan.get("skill_plan", {}).get("recommended_references", [])),
        "network_default": result.plan["source_policy"]["network_default"],
        "worker_events": [
            approach_worker_event(
                job,
                project,
                status="succeeded",
                headline="Research plan created",
                detail="Registered the controlled research handoff as an artifact.",
                target_anchor="approach-handoff",
            )
        ],
    }


def create_notebook_authoring_brief_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "create_notebook_authoring_brief")
    objective = payload.get("objective") if isinstance(payload.get("objective"), str) else None
    response_locale = payload.get("response_locale") if isinstance(payload.get("response_locale"), str) else None
    result = create_notebook_authoring_brief(
        db,
        store=store,
        project=project,
        objective=objective,
        response_locale=response_locale,
    )
    return {
        "schema_version": result.brief["schema_version"],
        "response_locale": result.brief.get("response_locale"),
        "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
        "notebook_authoring_report_id": result.report.id,
        "notebook_authoring_report_artifact_id": result.report_artifact.id,
        "source_card_count": len(result.brief["source_inspirations"]),
        "principle_count": len(result.brief["authoring_principles"]),
        "context_artifact_count": len(result.brief["context_artifacts"]),
        "artifact_id": result.brief_artifact.id,
        "artifact_ids": result.artifact_ids,
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Notebook authoring brief prepared",
                detail="Registered source-backed guidance for Codex-authored notebook work.",
                target_tab="Assets",
                target_anchor="asset-notebooks",
            )
        ],
    }


def prepare_data_understanding_notebook_authoring_handler(
    db: Session, job: Job, store: LocalArtifactStore
) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "prepare_data_understanding_notebook_authoring")
    response_locale = payload.get("response_locale") if isinstance(payload.get("response_locale"), str) else None
    result = create_notebook_authoring_brief(
        db,
        store=store,
        project=project,
        objective=(
            "Author a deep, visual, Kaggle Grandmaster-caliber project data-understanding marimo notebook "
            "from current artifacts and equipped Skills. Include rich EDA, micro-to-macro row/entity deep dives, "
            "relationship and leakage inspection, visual hypotheses, and concrete implications for feature "
            "engineering and evaluation. "
            "Do not use harness-authored notebook prose."
        ),
        response_locale=response_locale,
    )
    create_project_data_understanding_notebook_expectation(
        db,
        project=project,
        created_from="prepare_data_understanding_notebook_authoring",
        authoring_brief_artifact_id=result.brief_artifact.id,
    )
    return {
        "schema_version": "notebook_authoring_preparation.v1",
        "notebook_kind": "data_understanding",
        "response_locale": response_locale,
        "analysis_notebook_artifact_id": None,
        "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
        "notebook_authoring_report_artifact_id": result.report_artifact.id,
        "notebook_run_manifest_artifact_id": None,
        "notebook_report_id": None,
        "notebook_report_artifact_id": None,
        "artifact_ids": result.artifact_ids,
        "execution_status": "awaiting_agent_authored_notebook",
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Data-understanding notebook context prepared",
                detail="Registered the Codex authoring brief; the notebook itself remains Codex-authored.",
                target_tab="Assets",
                target_anchor="asset-notebooks",
            )
        ],
    }


def plan_agent_task_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "plan_agent_task")
    result = plan_project_agent_task(
        db,
        store=store,
        project=project,
        job=job,
        objective=payload.get("objective") if isinstance(payload.get("objective"), str) else None,
        task_type=str(payload.get("task_type") or "implement_prediction_approach"),
    )
    inputs = result.contract["inputs"]
    return {
        "schema_version": inputs["schema_version"],
        "task_id": result.contract["task_id"],
        "agent_task_contract_artifact_id": result.artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "dataset_snapshot_id": result.dataset_snapshot_id,
        "evaluation_spec_id": result.evaluation_spec_id,
        "split_manifest_id": result.split_manifest_id,
        "recommended_approach_count": len(inputs["recommended_approach_candidates"]),
        "research_query_count": len(inputs["research_queries"]),
        "recommended_asset_count": len(inputs["library_recommendations"]),
        "artifact_expectation_count": len(inputs["artifact_expectations"]),
        "worker_events": [
            approach_worker_event(
                job,
                project,
                status="succeeded",
                headline="Agent task contract planned",
                detail="Registered the open-ended runner contract and handoff context.",
                target_anchor="approach-handoff",
            )
        ],
    }


def plan_notebook_execution_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    notebook_artifact = notebook_artifact_for_job(db, job, "plan_notebook_execution")
    result = create_notebook_execution_plan(db, store=store, notebook_artifact=notebook_artifact)
    return {
        "schema_version": result.plan["schema_version"],
        "task_id": result.contract["task_id"],
        "task_type": result.contract["task_type"],
        "notebook_kind": result.plan["notebook_kind"],
        "analysis_notebook_artifact_id": notebook_artifact.id,
        "agent_task_contract_artifact_id": result.contract_artifact.id,
        "notebook_execution_plan_artifact_id": result.plan_artifact.id,
        "artifact_ids": result.artifact_ids,
        "execution_status": "planned_not_executed",
        "worker_events": [
            notebook_worker_event(
                job,
                notebook_artifact,
                status="succeeded",
                headline="Notebook execution plan created",
                detail="Registered the execution contract and plan without running notebook code.",
            )
        ],
    }


def prewarm_native_marimo_session_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    del store
    settings = get_settings()
    cleaned_session_count = cleanup_native_marimo_sessions(settings=settings)
    notebook_artifact = notebook_artifact_for_job(db, job, "prewarm_native_marimo_session")
    if not marimo_available():
        return {
            "schema_version": "native_marimo_prewarm.v1",
            "status": "skipped",
            "reason": "marimo_unavailable",
            "analysis_notebook_artifact_id": notebook_artifact.id,
            "cleaned_session_count": cleaned_session_count,
        }
    session = start_or_get_native_marimo_session(artifact=notebook_artifact, settings=settings)
    ready = wait_for_native_marimo_session_ready(
        session,
        timeout_seconds=NATIVE_MARIMO_PREWARM_READY_TIMEOUT_SECONDS,
    )
    return {
        "schema_version": "native_marimo_prewarm.v1",
        "status": "ready" if ready else session.status(),
        "analysis_notebook_artifact_id": notebook_artifact.id,
        "session_id": session.id,
        "session_status": session.status(),
        "ready": ready,
        "source_hash": session.source_hash,
        "cleaned_session_count": cleaned_session_count,
    }


def prepare_result_notebook_evidence_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "prepare_result_notebook_evidence")
    result = prepare_result_notebook_evidence(db, store=store, project=project)
    output = result_notebook_evidence_job_output(result)
    output["worker_events"] = [
        notebook_worker_event(
            job,
            result.authoring_brief_artifact,
            status="succeeded",
            headline="Result notebook evidence prepared",
            detail="Registered the notebook authoring brief for the current top run.",
        )
    ]
    return output


def generate_decision_report_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "generate_decision_report")
    result = create_decision_report_v1(db, store=store, project=project)
    return {
        "schema_version": result.bundle["schema_version"],
        "readiness_status": result.bundle["readiness"]["status"],
        "report_id": result.report.id,
        "decision_report_artifact_id": result.report_artifact.id,
        "decision_report_bundle_artifact_id": result.bundle_artifact.id,
        "decision_report_evidence_id": result.evidence.id,
        "next_action_count": len(result.bundle["next_actions"]),
        "coverage_ready_count": result.bundle["coverage_summary"]["ready_count"],
        "coverage_attention_count": result.bundle["coverage_summary"]["attention_count"],
        "source_asset_count": len(result.bundle["source_assets"]),
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Decision report generated",
                detail="Registered the decision report, evidence bundle, and source coverage summary.",
                target_tab="Insight",
                target_anchor="decision-report",
            )
        ],
    }


def draft_project_report_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "draft_project_report")
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    report_type = payload.get("report_type") if isinstance(payload.get("report_type"), str) else "project_summary"
    result = draft_project_report(
        db,
        store=store,
        project=project,
        title=title,
        report_type=report_type,
    )
    return {
        "report_id": result.report.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Project report drafted",
                detail="Registered the project report from current datasets, runs, insights, and artifacts.",
                target_tab="Insight",
                target_anchor="reports",
            )
        ],
    }


def create_visualization_spec_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "create_visualization_spec")
    result = create_project_visualization_dashboard(db, store=store, project=project)
    return {
        "visualization_id": result.visualizations[0].id if result.visualizations else None,
        "visualization_ids": [visualization.id for visualization in result.visualizations],
        "artifact_ids": result.artifact_ids,
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Visualization dashboard generated",
                detail="Registered in-product visualization specs from current project evidence.",
                target_tab="Insight",
                target_anchor="visualization-dashboard",
            )
        ],
    }


def generate_insights_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "generate_insights")
    result = generate_project_insights(db, store=store, project=project)
    return {
        "insight_ids": [insight.id for insight in result.insights],
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "evidence_ids": result.evidence_ids,
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Project insights generated",
                detail="Registered insight and evidence records from current project artifacts.",
                target_tab="Insight",
                target_anchor="ideas-findings",
            )
        ],
    }


def generate_decision_dashboard_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "generate_decision_dashboard")
    result = create_decision_dashboard(db, store=store, project=project)
    dashboard_metadata = loads_json(result.dashboard_artifact.metadata_json, {})
    return {
        "schema_version": result.dashboard["schema_version"],
        "readiness_status": dashboard_metadata.get("readiness_status"),
        "report_id": result.report.id,
        "decision_dashboard_artifact_id": result.dashboard_artifact.id,
        "decision_report_artifact_id": result.report_artifact.id,
        "visualization_ids": [visualization.id for visualization in result.visualizations],
        "artifact_ids": result.artifact_ids,
        "next_action_count": len(result.dashboard["next_actions"]),
        "risk_count": len(result.dashboard["risk_register"]),
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Decision dashboard generated",
                detail="Registered the decision dashboard, report, and readiness visualizations.",
                target_tab="Insight",
                target_anchor="decision-report",
            )
        ],
    }


def compare_experiments_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    project = project_for_job(db, job, "compare_experiments")
    result = compare_project_experiments(db, store=store, project=project)
    return {
        "artifact_ids": result.artifact_ids,
        "comparison": result.comparison,
        "visualization_id": result.visualization_id,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "insight_id": result.insight_id,
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Experiment comparison generated",
                detail="Registered comparable run evidence for the current leaderboard context.",
                target_tab="Leaderboard",
                target_anchor="result-readout",
            )
        ],
    }


def draft_run_report_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    run = run_for_job(db, job, "draft_run_report")
    result = draft_run_report(db, store=store, run=run)
    return {
        "run_id": run.id,
        "report_id": result.report.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "evidence_id": result.evidence_id,
        "insight_id": result.insight_id,
        "worker_events": [
            run_worker_event(
                job,
                run,
                status="succeeded",
                headline="Run report drafted",
                detail="Registered the run-level report, insight, and evidence records.",
                target_tab="Leaderboard",
                target_anchor="result-readout",
            )
        ],
    }


def prepare_model_diagnostics_notebook_authoring_handler(
    db: Session, job: Job, store: LocalArtifactStore
) -> dict[str, Any]:
    run = run_for_job(db, job, "prepare_model_diagnostics_notebook_authoring")
    project = db.get(Project, run.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = create_notebook_authoring_brief(
        db,
        store=store,
        project=project,
        objective=f"Author the model-diagnostics marimo notebook for ExperimentRun {run.id}.",
    )
    create_run_model_diagnostics_notebook_expectations(
        db,
        project=project,
        runs=[run],
        created_from="prepare_model_diagnostics_notebook_authoring",
    )
    return {
        "schema_version": "notebook_authoring_preparation.v1",
        "notebook_kind": "model_diagnostics",
        "run_id": run.id,
        "model_version_id": run.model_version_id,
        "analysis_notebook_artifact_id": None,
        "notebook_run_manifest_artifact_id": None,
        "notebook_report_id": None,
        "notebook_report_artifact_id": None,
        "visualization_id": None,
        "visualization_artifact_id": None,
        "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
        "notebook_authoring_report_artifact_id": result.report_artifact.id,
        "artifact_ids": result.artifact_ids,
        "execution_status": "awaiting_agent_authored_notebook",
        "worker_events": [
            run_worker_event(
                job,
                run,
                status="succeeded",
                headline="Model diagnostics notebook context prepared",
                detail="Registered the Codex authoring brief for this run's diagnostics notebook.",
                target_tab="Assets",
                target_anchor="asset-notebooks",
            )
        ],
    }


def analyze_evaluation_diagnostics_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    run = run_for_job(db, job, "analyze_evaluation_diagnostics")
    result = analyze_run_diagnostics(db, store=store, run=run)
    return {
        "run_id": run.id,
        "artifact_ids": result.artifact_ids,
        "diagnostics": result.diagnostics,
        "insight_id": result.insight_id,
        "evidence_id": result.evidence_id,
        "worker_events": [
            run_worker_event(
                job,
                run,
                status="succeeded",
                headline="Evaluation diagnostics analyzed",
                detail="Registered error, metric, and evaluation diagnostics artifacts for the run.",
                target_tab="Leaderboard",
                target_anchor="result-readout",
            )
        ],
    }


def materialize_model_diagnostics_artifacts_handler(
    db: Session, job: Job, store: LocalArtifactStore
) -> dict[str, Any]:
    run = run_for_job(db, job, "materialize_model_diagnostics_artifacts")
    result = materialize_model_diagnostics_artifacts(db, store=store, run=run)
    return {
        "run_id": run.id,
        "model_version_id": run.model_version_id,
        "artifact_ids": result.artifact_ids,
        "model_diagnostics_artifact_pack_id": result.artifact_ids[2],
        "model_diagnostics_report_artifact_id": result.artifact_ids[3],
        "feature_importance_artifact_id": result.artifact_ids[0],
        "permutation_importance_artifact_id": result.artifact_ids[1],
        "visualization_artifact_id": result.artifact_ids[4],
        "partial_dependence_artifact_id": result.artifact_ids[5],
        "shap_summary_artifact_id": result.artifact_ids[6],
        "availability": result.diagnostics.get("availability", {}),
        "insight_id": result.insight_id,
        "evidence_id": result.evidence_id,
        "worker_events": [
            run_worker_event(
                job,
                run,
                status="succeeded",
                headline="Model diagnostics artifacts materialized",
                detail="Registered feature importance, permutation importance, report, and visualization artifacts.",
                target_tab="Leaderboard",
                target_anchor="result-readout",
            )
        ],
    }


def validate_model_package_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    model_version_id = payload.get("model_version_id")
    model_version = db.get(ModelVersion, model_version_id) if isinstance(model_version_id, str) else None
    if model_version is None:
        raise ValueError("ModelVersion not found")
    if job.project_id is not None and model_version.project_id != job.project_id:
        raise ValueError("validate_model_package project does not match the model version")
    result = validate_model_version_package(db, store=store, model_version=model_version)
    return {
        "model_version_id": result.model_version.id,
        "artifact_ids": result.artifact_ids,
        "metrics": result.metrics,
        "worker_events": [
            project_worker_event(
                job,
                project_for_job(db, job, "validate_model_package"),
                status="succeeded",
                headline="Model package validated",
                detail="Replayed the model package and registered validation metrics.",
                target_tab="Assets",
                target_anchor="model-versions",
            )
        ],
    }


def register_prediction_pipeline_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "register_prediction_pipeline")
    session_id = payload.get("agent_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("register_prediction_pipeline requires agent_session_id")
    session = db.get(AgentSession, session_id.strip())
    if session is None or session.project_id != project.id:
        raise ValueError("AgentSession for prediction pipeline registration not found")
    workspace = resolve_runtime_data_path(session.workspace_path).resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise ValueError("AgentSession workspace for prediction pipeline registration not found")
    ack_path = workspace_relative_path_for_job(
        workspace,
        payload.get("ack_workspace_relative_path"),
        "register_prediction_pipeline",
        field_name="ack_workspace_relative_path",
    )
    request_relative_path = payload.get("request_workspace_relative_path")
    request_id = require_job_string(payload, "request_id", "register_prediction_pipeline")
    operation = require_job_string(payload, "operation", "register_prediction_pipeline")
    request_hash = require_job_string(payload, "request_hash", "register_prediction_pipeline")
    request_payload = payload.get("payload")
    if not isinstance(request_payload, dict):
        raise ValueError("register_prediction_pipeline payload must contain a request payload object")

    from tabular_harness.services.agent_requests.pipelines import (
        PIPELINE_ACK_SCHEMA_VERSION,
        execute_pipeline_registration_request,
        pipeline_tool_error_payload,
        write_pipeline_tool_ack,
    )
    from tabular_harness.services.agent_sessions import append_session_event

    try:
        compatibility_warnings = payload.get("compatibility_warnings")
        result = execute_pipeline_registration_request(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            request_id=request_id,
            payload=request_payload,
            compatibility_warnings=compatibility_warnings if isinstance(compatibility_warnings, list) else None,
        )
    except Exception as exc:
        ack = {
            "schema_version": PIPELINE_ACK_SCHEMA_VERSION,
            "request_id": request_id,
            "operation": operation,
            "status": "failed",
            "job_id": job.id,
            "request_hash": request_hash,
            "processed_at": utc_now().isoformat(),
            "error": pipeline_tool_error_payload(exc),
        }
        write_pipeline_tool_ack(ack_path, ack)
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="pipeline_request_failed",
            role="harness",
            title="Prediction pipeline request failed",
            content=str(exc),
            payload={**ack, "workspace_relative_path": request_relative_path},
            update_heartbeat=False,
        )
        return {
            "schema_version": "prediction_pipeline_registration_job.v1",
            "job_status": "failed",
            "status": "failed",
            "error_message": str(exc),
            "request_id": request_id,
            "ack_workspace_relative_path": str(ack_path.relative_to(workspace)),
        }

    ack = {
        "schema_version": PIPELINE_ACK_SCHEMA_VERSION,
        "request_id": request_id,
        "operation": operation,
        "status": "succeeded",
        "job_id": job.id,
        "request_hash": request_hash,
        "processed_at": utc_now().isoformat(),
        "result": result,
    }
    write_pipeline_tool_ack(ack_path, ack)
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="pipeline_request_succeeded",
        role="harness",
        title="Prediction pipeline registered",
        content=f"Processed pipeline request `{operation}` from `{request_relative_path}`.",
        payload=ack,
        artifact_id=result.get("pipeline_artifact_id"),
        update_heartbeat=False,
    )
    pipeline_artifact_id = result.get("pipeline_artifact_id")
    experiment_run_ids = result.get("experiment_run_ids")
    if isinstance(pipeline_artifact_id, str) and isinstance(experiment_run_ids, list):
        fulfill_run_pipeline_bundle_expectations(
            db,
            project=project,
            run_ids=[item for item in experiment_run_ids if isinstance(item, str)],
            pipeline_artifact_id=pipeline_artifact_id,
        )
    return {
        "schema_version": "prediction_pipeline_registration_job.v1",
        "status": "succeeded",
        "request_id": request_id,
        "pipeline_artifact_id": result.get("pipeline_artifact_id"),
        "experiment_run_ids": result.get("experiment_run_ids", []),
        "smoke_validation": result.get("smoke_validation"),
        "metric_reproduction": result.get("metric_reproduction"),
        "ack_workspace_relative_path": str(ack_path.relative_to(workspace)),
    }


def require_job_string(payload: dict[str, Any], field_name: str, job_type: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{job_type} requires {field_name}")
    return value.strip()


def workspace_relative_path_for_job(workspace: Path, value: Any, job_type: str, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{job_type} requires {field_name}")
    candidate = Path(value.strip())
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative to the AgentSession workspace")
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes the AgentSession workspace") from exc
    return resolved


def run_prediction_pipeline_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "run_prediction_pipeline")
    batch_kind = prediction_batch_kind_from_payload(payload)
    pipeline_artifact_id = payload.get("pipeline_artifact_id")
    if not isinstance(pipeline_artifact_id, str) or not pipeline_artifact_id.strip():
        raise ValueError("run_prediction_pipeline requires pipeline_artifact_id")
    pipeline_artifact = db.get(Artifact, pipeline_artifact_id)
    if pipeline_artifact is None or pipeline_artifact.project_id != project.id:
        raise ValueError("Prediction pipeline artifact not found")
    if pipeline_artifact.asset_type != "prediction_pipeline":
        raise ValueError("Artifact is not a prediction_pipeline")

    input_dir = prediction_input_dir_for_job(db, project=project, payload=payload, run_dir=get_settings().data_dir / "_pipeline_runs" / job.id)
    input_path = None if input_dir is not None else prediction_input_path_for_job(db, project=project, payload=payload)
    history_path = prediction_history_path_for_job(db, project=project, payload=payload)
    run_dir = (get_settings().data_dir / "_pipeline_runs" / job.id).resolve()
    extract_dir = run_dir / "pipeline"
    output_path = run_dir / "predictions.csv"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_primary_path(pipeline_artifact)) as archive:
        archive.extractall(extract_dir)
    predict_path = extract_dir / "predict.py"
    if not predict_path.exists():
        raise ValueError("Pipeline bundle does not contain predict.py")
    runtime_python = sys.executable
    runtime_isolated = False
    requirements_hash = None
    requirements_path = extract_dir / "requirements.txt"
    if requirements_path.exists():
        from tabular_harness.services.agent_requests.pipelines import (
            ensure_prediction_pipeline_smoke_python,
            prediction_pipeline_predict_command,
            prediction_pipeline_requirements_hash,
            validate_pipeline_requirements_file,
        )

        validate_pipeline_requirements_file(requirements_path)
        runtime_python = str(ensure_prediction_pipeline_smoke_python(requirements_path))
        runtime_isolated = True
        requirements_hash = prediction_pipeline_requirements_hash(requirements_path)
    else:
        from tabular_harness.services.agent_requests.pipelines import prediction_pipeline_predict_command

    command = prediction_pipeline_predict_command(
        python_executable=runtime_python,
        predict_path=predict_path,
        input_dir=input_dir,
        input_path=input_path,
        output_path=output_path,
        history_path=history_path,
    )
    completed = subprocess.run(
        command,
        cwd=str(extract_dir),
        capture_output=True,
        text=True,
        timeout=int(payload.get("timeout_seconds") or 300),
        check=False,
    )
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or completed.stdout or "")[-4000:]
        error_summary = prediction_pipeline_runtime_failure_message(exit_code=completed.returncode)
        codex_feedback = maybe_send_prediction_pipeline_runtime_failure_to_codex(
            db,
            project=project,
            pipeline_artifact=pipeline_artifact,
            job_id=job.id,
            error_message=stderr_tail,
            error_summary=error_summary,
            exit_code=completed.returncode,
            input_artifact_id=payload.get("input_artifact_id") if isinstance(payload.get("input_artifact_id"), str) else None,
            dataset_snapshot_id=payload.get("dataset_snapshot_id") if isinstance(payload.get("dataset_snapshot_id"), str) else None,
            input_artifact_ids_by_table=payload.get("input_artifact_ids_by_table")
            if isinstance(payload.get("input_artifact_ids_by_table"), dict)
            else None,
        )
        return {
            "schema_version": "prediction_pipeline_job.v1",
            "job_status": "failed",
            "status": "failed",
            "error_message": error_summary,
            "pipeline_artifact_id": pipeline_artifact.id,
            "input_dataset_snapshot_id": payload.get("dataset_snapshot_id"),
            "input_artifact_id": payload.get("input_artifact_id"),
            "input_artifact_ids_by_table": payload.get("input_artifact_ids_by_table")
            if isinstance(payload.get("input_artifact_ids_by_table"), dict)
            else None,
            "batch_kind": batch_kind,
            "stderr_tail": stderr_tail,
            "exit_code": completed.returncode,
            "codex_feedback": codex_feedback,
            "runtime_isolated": runtime_isolated,
            "python_executable": runtime_python,
            "requirements_hash": requirements_hash,
        }
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ValueError("Prediction pipeline did not create a non-empty predictions.csv")
    version = next_artifact_version(db, project.id, "prediction_batch", f"prediction_batch_{job.id}")
    target_dir, stored, content_hash = store.store_existing_file(
        org_id=project.org_id,
        project_id=project.id,
        asset_type="prediction_batch",
        name=f"prediction_batch_{job.id}",
        version=version,
        source_path=output_path,
        filename="predictions.csv",
        metadata={
            "project_id": project.id,
            "pipeline_artifact_id": pipeline_artifact.id,
            "job_id": job.id,
            "input_dataset_snapshot_id": payload.get("dataset_snapshot_id"),
            "input_artifact_id": payload.get("input_artifact_id"),
            "input_artifact_ids_by_table": payload.get("input_artifact_ids_by_table")
            if isinstance(payload.get("input_artifact_ids_by_table"), dict)
            else None,
            "batch_kind": batch_kind,
            "history_artifact_id": payload.get("history_artifact_id"),
            "primary_path": str(output_path),
            "runtime_isolated": runtime_isolated,
            "python_executable": runtime_python,
            "requirements_hash": requirements_hash,
        },
    )
    prediction_artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="prediction_batch",
        name=f"prediction_batch_{job.id}",
        uri=str(target_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "project_id": project.id,
            "pipeline_artifact_id": pipeline_artifact.id,
            "job_id": job.id,
            "input_dataset_snapshot_id": payload.get("dataset_snapshot_id"),
            "input_artifact_id": payload.get("input_artifact_id"),
            "input_artifact_ids_by_table": payload.get("input_artifact_ids_by_table")
            if isinstance(payload.get("input_artifact_ids_by_table"), dict)
            else None,
            "batch_kind": batch_kind,
            "history_artifact_id": payload.get("history_artifact_id"),
            "primary_path": str(target_dir / "predictions.csv"),
            "runtime_isolated": runtime_isolated,
            "python_executable": runtime_python,
            "requirements_hash": requirements_hash,
        },
        version=version,
        org_id=project.org_id,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pipeline_artifact.id,
        to_asset_type="artifact",
        to_asset_id=prediction_artifact.id,
        relation_type="produces_prediction_batch",
        metadata={"job_id": job.id},
    )
    deployment_id = payload.get("deployment_id")
    pilot_prediction_batch_id = None
    if isinstance(deployment_id, str) and deployment_id.strip():
        deployment = db.get(PilotDeployment, deployment_id.strip())
        if deployment is None or deployment.project_id != project.id:
            raise ValueError("PilotDeployment not found")
        input_artifact_id = payload.get("input_artifact_id")
        if not isinstance(input_artifact_id, str) or not input_artifact_id.strip():
            dataset_snapshot_id = payload.get("dataset_snapshot_id")
            dataset = db.get(DatasetSnapshot, dataset_snapshot_id) if isinstance(dataset_snapshot_id, str) else None
            input_artifact_id = dataset.artifact_id if dataset is not None else None
        if not isinstance(input_artifact_id, str) or not input_artifact_id.strip():
            mapping = payload.get("input_artifact_ids_by_table")
            if isinstance(mapping, dict):
                table_artifact_ids = [
                    str(value).strip()
                    for key, value in sorted(mapping.items())
                    if isinstance(key, str) and isinstance(value, str) and value.strip()
                ]
                input_artifact_id = table_artifact_ids[0] if table_artifact_ids else None
        if not isinstance(input_artifact_id, str) or not input_artifact_id.strip():
            raise ValueError("Pilot prediction batch requires an input artifact")
        as_of = parse_iso_datetime(payload.get("as_of")) or utc_now()
        row_count = count_csv_data_rows(output_path)
        batch = PilotPredictionBatch(
            id=new_id("ppb"),
            deployment_id=deployment.id,
            as_of=as_of,
            input_artifact_id=input_artifact_id,
            predictions_artifact_id=prediction_artifact.id,
            row_count=row_count,
        )
        db.add(batch)
        pilot_prediction_batch_id = batch.id
    return {
        "schema_version": "prediction_pipeline_job.v1",
        "prediction_batch_artifact_id": prediction_artifact.id,
        "pilot_prediction_batch_id": pilot_prediction_batch_id,
        "artifact_id": prediction_artifact.id,
        "artifact_ids": [pipeline_artifact.id, prediction_artifact.id],
        "row_source": str(input_dir or input_path),
        "runtime_isolated": runtime_isolated,
        "python_executable": runtime_python,
        "requirements_hash": requirements_hash,
    }


def prediction_input_dir_for_job(db: Session, *, project: Project, payload: dict[str, Any], run_dir: Path) -> Path | None:
    raw_mapping = payload.get("input_artifact_ids_by_table")
    if not isinstance(raw_mapping, dict) or not raw_mapping:
        return None
    input_dir = (run_dir / "input_dir").resolve()
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"schema_version": "prediction_input_dir_manifest.v1", "tables": []}
    for raw_name, raw_artifact_id in raw_mapping.items():
        if not isinstance(raw_name, str) or not raw_name.strip() or not isinstance(raw_artifact_id, str) or not raw_artifact_id.strip():
            continue
        table_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._") or "table"
        artifact = db.get(Artifact, raw_artifact_id.strip())
        if artifact is None or artifact.project_id != project.id:
            raise ValueError(f"Prediction input artifact not found for table {table_name}")
        source_path = artifact_primary_path(artifact)
        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Prediction input file not found for table {table_name}")
        suffix = source_path.suffix.lower() if source_path.suffix.lower() in {".csv", ".parquet"} else ".csv"
        target_path = input_dir / f"{table_name}{suffix}"
        shutil.copy2(source_path, target_path)
        manifest["tables"].append(
            {
                "name": table_name,
                "artifact_id": artifact.id,
                "filename": target_path.name,
                "path": str(target_path),
            }
        )
    if not manifest["tables"]:
        raise ValueError("run_prediction_pipeline input_artifact_ids_by_table did not contain any valid table inputs")
    (input_dir / "manifest.json").write_text(dumps_json(manifest), encoding="utf-8")
    return input_dir


def prediction_batch_kind_from_payload(payload: dict[str, Any]) -> str:
    raw = payload.get("batch_kind")
    value = raw.strip().lower() if isinstance(raw, str) else "external_test"
    return value if value in {"validation", "external_test", "pilot", "benchmark_submission"} else "external_test"


def prediction_input_path_for_job(db: Session, *, project: Project, payload: dict[str, Any]) -> Path:
    dataset_snapshot_id = payload.get("dataset_snapshot_id")
    input_artifact_id = payload.get("input_artifact_id")
    artifact: Artifact | None = None
    if isinstance(dataset_snapshot_id, str) and dataset_snapshot_id.strip():
        dataset = db.get(DatasetSnapshot, dataset_snapshot_id.strip())
        if dataset is None or dataset.project_id != project.id:
            raise ValueError("DatasetSnapshot for prediction input not found")
        artifact = db.get(Artifact, dataset.artifact_id)
    elif isinstance(input_artifact_id, str) and input_artifact_id.strip():
        artifact = db.get(Artifact, input_artifact_id.strip())
        if artifact is not None and artifact.project_id != project.id:
            raise ValueError("Input artifact belongs to a different project")
    else:
        raise ValueError("run_prediction_pipeline requires dataset_snapshot_id or input_artifact_id")
    if artifact is None:
        raise ValueError("Prediction input artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists() or not path.is_file():
        raise ValueError("Prediction input file not found")
    return path


def prediction_history_path_for_job(db: Session, *, project: Project, payload: dict[str, Any]) -> Path | None:
    history_artifact_id = payload.get("history_artifact_id")
    if not isinstance(history_artifact_id, str) or not history_artifact_id.strip():
        return None
    artifact = db.get(Artifact, history_artifact_id.strip())
    if artifact is None or artifact.project_id != project.id:
        raise ValueError("Prediction history artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists() or not path.is_file():
        raise ValueError("Prediction history file not found")
    return path


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def count_csv_data_rows(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            line_count = sum(1 for _ in handle)
    except OSError:
        return None
    return max(line_count - 1, 0)


def score_pilot_outcomes_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "score_pilot_outcomes")
    deployment_id = payload.get("deployment_id")
    outcome_batch_id = payload.get("outcome_batch_id")
    if not isinstance(deployment_id, str) or not deployment_id.strip():
        raise ValueError("score_pilot_outcomes requires deployment_id")
    if not isinstance(outcome_batch_id, str) or not outcome_batch_id.strip():
        raise ValueError("score_pilot_outcomes requires outcome_batch_id")
    deployment = db.get(PilotDeployment, deployment_id.strip())
    if deployment is None or deployment.project_id != project.id:
        raise ValueError("PilotDeployment not found")
    outcome_batch = db.get(PilotOutcomeBatch, outcome_batch_id.strip())
    if outcome_batch is None or outcome_batch.deployment_id != deployment.id:
        raise ValueError("PilotOutcomeBatch not found")

    prediction_batch = pilot_prediction_batch_for_scoring(db, deployment=deployment, payload=payload)
    prediction_artifact = db.get(Artifact, prediction_batch.predictions_artifact_id)
    outcome_artifact = db.get(Artifact, outcome_batch.outcomes_artifact_id)
    pipeline_artifact = db.get(Artifact, deployment.pipeline_artifact_id)
    if prediction_artifact is None or prediction_artifact.project_id != project.id:
        raise ValueError("Pilot prediction artifact not found")
    if outcome_artifact is None or outcome_artifact.project_id != project.id:
        raise ValueError("Pilot outcome artifact not found")
    if pipeline_artifact is None or pipeline_artifact.project_id != project.id:
        raise ValueError("Prediction pipeline artifact not found")

    manifest = pipeline_manifest_from_bundle(pipeline_artifact)
    output_contract = manifest.get("output_contract") if isinstance(manifest, dict) else {}
    if not isinstance(output_contract, dict):
        output_contract = {}
    join_keys = pilot_join_keys(outcome_batch, output_contract=output_contract, payload=payload)
    prediction_column = string_or_none(payload.get("prediction_column")) or string_or_none(
        output_contract.get("prediction_column")
    )
    actual_column = string_or_none(payload.get("actual_column")) or project.target_column
    if not prediction_column:
        raise ValueError("Prediction column is required")
    if not actual_column:
        raise ValueError("Actual/outcome column is required")

    prediction_rows = read_csv_dict_rows(artifact_primary_path(prediction_artifact))
    outcome_rows = read_csv_dict_rows(artifact_primary_path(outcome_artifact))
    scoring = score_joined_prediction_outcomes(
        prediction_rows=prediction_rows,
        outcome_rows=outcome_rows,
        join_keys=join_keys,
        prediction_column=prediction_column,
        actual_column=actual_column,
        observed_at_column=string_or_none(payload.get("observed_at_column")),
        prediction_as_of=prediction_batch.as_of,
    )
    outcome_batch.matched_rows = scoring["matched_rows"]
    report_payload = {
        "schema_version": "pilot_scoring_report.v1",
        "deployment_id": deployment.id,
        "prediction_batch_id": prediction_batch.id,
        "outcome_batch_id": outcome_batch.id,
        "pipeline_artifact_id": pipeline_artifact.id,
        "as_of": prediction_batch.as_of.isoformat(),
        "join_keys": join_keys,
        "prediction_column": prediction_column,
        "actual_column": actual_column,
        "observed_at_column": string_or_none(payload.get("observed_at_column")),
        **scoring,
    }
    report_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="pilot_scoring_report",
        name=f"pilot_scoring_report_{deployment.id}_{job.id}",
        filename="pilot_scoring_report.json",
        payload=report_payload,
        metadata={
            "project_id": project.id,
            "deployment_id": deployment.id,
            "prediction_batch_id": prediction_batch.id,
            "outcome_batch_id": outcome_batch.id,
            "pipeline_artifact_id": pipeline_artifact.id,
            "job_id": job.id,
        },
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=prediction_artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="scores_prediction_batch",
        metadata={"job_id": job.id, "deployment_id": deployment.id},
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=outcome_artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="scores_outcome_batch",
        metadata={"job_id": job.id, "deployment_id": deployment.id},
    )
    notified_session_id = notify_main_agent_session_of_pilot_report(
        db,
        project=project,
        report_artifact=report_artifact,
        report_payload=report_payload,
    )
    if notified_session_id is not None and project.autonomy_mode == "full_auto" and project.current_phase != "AUTONOMOUS_LOOP":
        project.current_phase = "AUTONOMOUS_LOOP"
        project.updated_at = utc_now()
    output = {
        "schema_version": "pilot_outcome_scoring_job.v1",
        "pilot_scoring_report_artifact_id": report_artifact.id,
        "pilot_prediction_batch_id": prediction_batch.id,
        "pilot_outcome_batch_id": outcome_batch.id,
        "matched_rows": scoring["matched_rows"],
        "metric_count": scoring["metric_count"],
        "metrics": scoring["metrics"],
        "as_of_violations": scoring["as_of_violations"],
        "notified_agent_session_id": notified_session_id,
        "artifact_id": report_artifact.id,
        "artifact_ids": [prediction_artifact.id, outcome_artifact.id, report_artifact.id],
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Pilot scoring report registered",
                detail="Prediction and outcome batches were matched and scored.",
                target_tab="Leaderboard",
                target_anchor="pilot",
            )
        ],
    }
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="pilot_scoring_report_available",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def pilot_prediction_batch_for_scoring(
    db: Session,
    *,
    deployment: PilotDeployment,
    payload: dict[str, Any],
) -> PilotPredictionBatch:
    prediction_batch_id = string_or_none(payload.get("prediction_batch_id"))
    if prediction_batch_id:
        batch = db.get(PilotPredictionBatch, prediction_batch_id)
        if batch is None or batch.deployment_id != deployment.id:
            raise ValueError("PilotPredictionBatch not found")
        return batch
    batch = db.scalar(
        select(PilotPredictionBatch)
        .where(PilotPredictionBatch.deployment_id == deployment.id)
        .order_by(PilotPredictionBatch.created_at.desc())
        .limit(1)
    )
    if batch is None:
        raise ValueError("No PilotPredictionBatch is available for this deployment")
    return batch


def pipeline_manifest_from_bundle(pipeline_artifact: Artifact) -> dict[str, Any]:
    bundle_path = artifact_primary_path(pipeline_artifact)
    with zipfile.ZipFile(bundle_path) as archive:
        try:
            with archive.open("pipeline_manifest.json") as handle:
                return loads_json(handle.read().decode("utf-8"), {})
        except KeyError as exc:
            raise ValueError("Prediction pipeline bundle does not contain pipeline_manifest.json") from exc


def string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def pilot_join_keys(
    outcome_batch: PilotOutcomeBatch,
    *,
    output_contract: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    requested = payload.get("join_keys")
    if isinstance(requested, list):
        join_keys = [item.strip() for item in requested if isinstance(item, str) and item.strip()]
    else:
        join_keys = [item for item in loads_json(outcome_batch.join_keys_json, []) if isinstance(item, str) and item.strip()]
    if not join_keys:
        id_columns = output_contract.get("id_columns")
        if isinstance(id_columns, list):
            join_keys = [item.strip() for item in id_columns if isinstance(item, str) and item.strip()]
    if not join_keys:
        raise ValueError("join_keys are required for pilot outcome scoring")
    return join_keys


def read_csv_dict_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"{path.name} is missing a CSV header")
            return [dict(row) for row in reader]
    except OSError as exc:
        raise ValueError(f"Could not read CSV artifact {path}") from exc


def score_joined_prediction_outcomes(
    *,
    prediction_rows: list[dict[str, str]],
    outcome_rows: list[dict[str, str]],
    join_keys: list[str],
    prediction_column: str,
    actual_column: str,
    observed_at_column: str | None,
    prediction_as_of: datetime,
) -> dict[str, Any]:
    ensure_csv_columns(prediction_rows, join_keys + [prediction_column], "predictions")
    ensure_csv_columns(outcome_rows, join_keys + [actual_column], "outcomes")
    if observed_at_column:
        ensure_csv_columns(outcome_rows, [observed_at_column], "outcomes")
    predictions_by_key = {csv_join_key(row, join_keys): row for row in prediction_rows}
    matched_rows = 0
    metric_count = 0
    absolute_errors: list[float] = []
    squared_errors: list[float] = []
    as_of_violation_count = 0
    unparseable_observed_at_rows = 0
    normalized_prediction_as_of = ensure_utc_datetime(prediction_as_of)
    for outcome in outcome_rows:
        key = csv_join_key(outcome, join_keys)
        prediction = predictions_by_key.get(key)
        if prediction is None:
            continue
        matched_rows += 1
        if observed_at_column:
            observed_at = parse_iso_datetime(outcome.get(observed_at_column))
            if observed_at is None:
                unparseable_observed_at_rows += 1
            elif observed_at <= normalized_prediction_as_of:
                as_of_violation_count += 1
        predicted = parse_float(prediction.get(prediction_column))
        actual = parse_float(outcome.get(actual_column))
        if predicted is None or actual is None:
            continue
        error = predicted - actual
        metric_count += 1
        absolute_errors.append(abs(error))
        squared_errors.append(error * error)
    if metric_count == 0:
        raise ValueError("No numeric prediction/outcome pairs were available for scoring")
    return {
        "prediction_row_count": len(prediction_rows),
        "outcome_row_count": len(outcome_rows),
        "matched_rows": matched_rows,
        "metric_count": metric_count,
        "metrics": {
            "mae": sum(absolute_errors) / metric_count,
            "rmse": math.sqrt(sum(squared_errors) / metric_count),
        },
        "as_of_violations": {
            "count": as_of_violation_count,
            "unparseable_observed_at_rows": unparseable_observed_at_rows,
        },
    }


def ensure_csv_columns(rows: list[dict[str, str]], columns: list[str], label: str) -> None:
    if not rows:
        raise ValueError(f"{label} CSV contains no data rows")
    available = set(rows[0].keys())
    missing = [column for column in columns if column not in available]
    if missing:
        raise ValueError(f"{label} CSV is missing required column(s): {', '.join(missing)}")


def csv_join_key(row: dict[str, str], join_keys: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(key, "")) for key in join_keys)


def parse_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def notify_main_agent_session_of_pilot_report(
    db: Session,
    *,
    project: Project,
    report_artifact: Artifact,
    report_payload: dict[str, Any],
) -> str | None:
    session = db.scalar(
        select(AgentSession)
        .where(
            AgentSession.project_id == project.id,
            AgentSession.status.in_(
                ["starting", "running", "between_turns", "waiting_for_runner", "recovering", "idle", "completed"]
            ),
        )
        .order_by(AgentSession.updated_at.desc())
        .limit(1)
    )
    if session is None or not session.workspace_path:
        return None
    session_workspace = resolve_runtime_data_path(session.workspace_path)
    observation_dir = session_workspace / ".tablex" / "pilot_observations"
    observation_dir.mkdir(parents=True, exist_ok=True)
    report_workspace_path = observation_dir / f"{report_artifact.id}.json"
    try:
        report_workspace_path.write_bytes(artifact_primary_path(report_artifact).read_bytes())
    except OSError:
        report_workspace_path.write_text(dumps_json(report_payload) + "\n", encoding="utf-8")
    notice_payload = {
        "schema_version": "tablex_pilot_observation_notice.v1",
        "pilot_scoring_report_artifact_id": report_artifact.id,
        "pilot_scoring_report_workspace_path": str(report_workspace_path.relative_to(session_workspace)),
        "deployment_id": report_payload.get("deployment_id"),
        "prediction_batch_id": report_payload.get("prediction_batch_id"),
        "outcome_batch_id": report_payload.get("outcome_batch_id"),
        "metrics": report_payload.get("metrics"),
        "as_of_violations": report_payload.get("as_of_violations"),
        "matched_rows": report_payload.get("matched_rows"),
        "metric_count": report_payload.get("metric_count"),
    }
    notice_path = write_inbox_entry(
        session_workspace,
        kind="observation",
        entry_type="pilot_observation_available",
        payload=notice_payload,
        content=dumps_json(notice_payload) + "\n",
        title="Pilot observation available",
    )
    from tabular_harness.services.agent_sessions import append_session_event

    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="pilot_observation_available",
        role="harness",
        title="Pilot observation available",
        content="A pilot scoring report was delivered to the main session inbox.",
        payload={**notice_payload, "workspace_relative_path": str(notice_path.relative_to(session_workspace))},
        artifact_id=report_artifact.id,
        update_heartbeat=False,
    )
    return session.id


def project_for_job(db: Session, job: Job, job_type: str) -> Project:
    if job.project_id is None:
        raise ValueError(f"{job_type} requires a project_id")
    project = db.get(Project, job.project_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def run_for_job(db: Session, job: Job, job_type: str) -> ExperimentRun:
    payload = loads_json(job.input_json, {})
    run_id = payload.get("run_id")
    run = db.get(ExperimentRun, run_id) if isinstance(run_id, str) else None
    if run is None:
        raise ValueError("ExperimentRun not found")
    if job.project_id is not None and run.project_id != job.project_id:
        raise ValueError(f"{job_type} project does not match the ExperimentRun")
    return run


def notebook_artifact_for_job(db: Session, job: Job, job_type: str) -> Artifact:
    payload = loads_json(job.input_json, {})
    artifact_id = payload.get("analysis_notebook_artifact_id")
    artifact = db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
    if artifact is None:
        raise ValueError("Analysis notebook artifact not found")
    if artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        raise ValueError(f"{job_type} requires a native marimo notebook source artifact")
    if artifact.project_id is None:
        raise ValueError(f"{job_type} requires a project-scoped native marimo notebook source artifact")
    if job.project_id is not None and artifact.project_id != job.project_id:
        raise ValueError(f"{job_type} project does not match the analysis notebook artifact")
    return artifact


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest).where(SplitManifest.evaluation_spec_id == spec_id).order_by(SplitManifest.created_at.desc())
    )


def approach_worker_event(
    job: Job,
    project: Project,
    *,
    status: str,
    headline: str,
    detail: str,
    target_anchor: str,
) -> dict[str, Any]:
    return {
        "worker_id": "approach-planning",
        "display_name": "Approach Worker",
        "status": status,
        "headline": headline,
        "detail": detail,
        "job_id": job.id,
        "project_id": project.id,
        "target_tab": "Home",
        "target_anchor": target_anchor,
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "approach_planning_estimate",
            "is_estimate": True,
            "series": [
                {"step": "context", "tokens": 60},
                {"step": "plan", "tokens": 120},
                {"step": "register", "tokens": 80},
            ],
        },
    }


def notebook_worker_event(
    job: Job,
    notebook_artifact: Artifact,
    *,
    status: str,
    headline: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "worker_id": "marimo-notebook",
        "display_name": "marimo Notebook",
        "status": status,
        "headline": headline,
        "detail": detail,
        "job_id": job.id,
        "project_id": notebook_artifact.project_id,
        "target_tab": "Assets",
        "target_anchor": "asset-notebooks",
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "notebook_execution_estimate",
            "is_estimate": True,
            "series": [
                {"step": "validate notebook", "tokens": 40},
                {"step": "register native source", "tokens": 120},
                {"step": "link artifacts", "tokens": 80},
            ],
        },
    }


def project_worker_event(
    job: Job,
    project: Project,
    *,
    status: str,
    headline: str,
    detail: str,
    target_tab: str,
    target_anchor: str,
) -> dict[str, Any]:
    return {
        "worker_id": "project-reporting",
        "display_name": "Reporting Worker",
        "status": status,
        "headline": headline,
        "detail": detail,
        "job_id": job.id,
        "project_id": project.id,
        "target_tab": target_tab,
        "target_anchor": target_anchor,
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "reporting_worker_estimate",
            "is_estimate": True,
            "series": [
                {"step": "load evidence", "tokens": 80},
                {"step": "compose report", "tokens": 160},
                {"step": "register artifacts", "tokens": 90},
            ],
        },
    }


def run_worker_event(
    job: Job,
    run: ExperimentRun,
    *,
    status: str,
    headline: str,
    detail: str,
    target_tab: str,
    target_anchor: str,
) -> dict[str, Any]:
    return {
        "worker_id": "run-reporting",
        "display_name": "Reporting Worker",
        "status": status,
        "headline": headline,
        "detail": detail,
        "job_id": job.id,
        "project_id": run.project_id,
        "target_tab": target_tab,
        "target_anchor": target_anchor,
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "run_reporting_worker_estimate",
            "is_estimate": True,
            "series": [
                {"step": "load run", "tokens": 60},
                {"step": "analyze evidence", "tokens": 180},
                {"step": "register artifacts", "tokens": 100},
            ],
        },
    }


def plan_baseline_strategy_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project = project_for_job(db, job, "plan_baseline_strategy")
    spec_id = payload.get("evaluation_spec_id")
    split_id = payload.get("split_manifest_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else latest_approved_spec(db, project.id)
    split = db.get(SplitManifest, split_id) if isinstance(split_id, str) else None
    if spec is None:
        raise ValueError("Approve an EvaluationSpec before planning baseline strategy")
    if split is None:
        split = latest_split_for_spec(db, spec.id)
    if split is None:
        raise ValueError("Generate a SplitManifest before planning baseline strategy")
    result = create_baseline_strategy_plan(
        db,
        store=store,
        project=project,
        evaluation_spec=spec,
        split_manifest=split,
    )
    return {
        "baseline_strategy_plan_artifact_id": result.artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "strategy_count": len(result.plan.get("candidate_strategies", [])),
        "next_agent_task_count": len(result.plan.get("next_agent_tasks", [])),
        "selected_baseline_type": result.plan["selected_execution"].get("baseline_type"),
        "strategy_mode": result.plan.get("context", {}).get("strategy_mode"),
        "planning_source": result.plan.get("context", {}).get("current_baseline_plan", {}).get("planning_source"),
        "resource_guard_level": result.plan.get("context", {})
        .get("current_baseline_plan", {})
        .get("resource_guard", {})
        .get("level"),
        "matched_asset_count": result.plan.get("context", {}).get("library_context", {}).get("matched_asset_count"),
        "reporting_visualization_count": len(result.plan.get("reporting_plan", {}).get("visualization_specs", [])),
        "worker_events": [
            approach_worker_event(
                job,
                project,
                status="succeeded",
                headline="Baseline strategy planned",
                detail="Registered an advisory baseline strategy without constraining Codex to a fixed recipe.",
                target_anchor="strategy-brief-focus",
            )
        ],
    }


def run_baseline_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("run_baseline requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    spec_id = payload.get("evaluation_spec_id")
    split_id = payload.get("split_manifest_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    split = db.get(SplitManifest, split_id) if isinstance(split_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    if split is None:
        raise ValueError("SplitManifest not found")
    result = run_baseline(db, store=store, project=project, evaluation_spec=spec, split_manifest=split)
    output = {
        "schema_version": "baseline_training.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "experiment_run_id": result.run.id,
        "model_version_id": result.model_version_id,
        "artifact_ids": result.artifact_ids,
        "metrics": result.metrics,
        "primary_metric_name": result.metrics.get("primary_metric_name"),
        "primary_metric_value": result.metrics.get("primary_metric_value"),
        "worker_events": [
            {
                "worker_id": "adaptive-baseline",
                "display_name": "Training Worker",
                "status": "succeeded",
                "headline": f"Adaptive baseline trained: {result.run.id}",
                "detail": "Registered the baseline run, model package, metrics, and supporting artifacts.",
                "job_id": job.id,
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "training_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load split", "tokens": 80},
                        {"step": "fit baseline", "tokens": 180},
                        {"step": "score", "tokens": 120},
                        {"step": "register artifacts", "tokens": 140},
                    ],
                },
            }
        ],
    }
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="baseline_training_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def build_split_manifest_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    spec_id = payload.get("evaluation_spec_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    split = generate_split_manifest(db, store=store, spec=spec)
    queued_training_ids: list[str] = []
    if job.project_id:
        common_policy = {
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
            "queued_by": "split_manifest_worker",
        }
        baseline_job = create_job(
            db,
            job_type="run_baseline",
            project_id=job.project_id,
            input_payload={"evaluation_spec_id": spec.id, "split_manifest_id": split.id},
            context={
                "human_description": {
                    "source": "split_manifest_worker",
                    "title": "Train the adaptive baseline",
                    "summary": "Train the adaptive baseline after the queued SplitManifest has been materialized.",
                }
            },
            policy=common_policy,
            priority=70,
        )
        candidate_job = create_job(
            db,
            job_type="train_model_candidates",
            project_id=job.project_id,
            input_payload={
                "requested_models": ["xgboost", "logistic_regression", "lightgbm"],
                "normalized_models": ["xgboost", "logistic_regression", "lightgbm"],
                "unsupported_models": [],
                "evaluation_spec_id": spec.id,
                "split_manifest_id": split.id,
            },
            context={
                "human_description": {
                    "source": "split_manifest_worker",
                    "title": "Train candidate models",
                    "summary": "Train XGBoost, LogisticRegression, and LightGBM after the queued SplitManifest has been materialized.",
                }
            },
            policy=common_policy,
            priority=65,
        )
        queued_training_ids = [baseline_job.id, candidate_job.id]
    output = {
        "schema_version": "split_manifest_generation.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "artifact_ids": [split.artifact_id],
        "created_job_ids": queued_training_ids,
        "worker_events": [
            {
                "worker_id": "split-manifest-builder",
                "display_name": "Evaluation Worker",
                "status": "succeeded",
                "headline": "SplitManifest generated",
                "detail": "Created the stable train/validation split for downstream model runs.",
                "job_id": job.id,
                "target_tab": "Evaluation",
                "target_anchor": "evaluation-spec",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "split_generation_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load spec", "tokens": 40},
                        {"step": "split rows", "tokens": 140},
                        {"step": "write manifest", "tokens": 80},
                    ],
                },
            }
        ],
    }
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project_id=job.project_id,
        job=job,
        reason="split_manifest_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def train_model_candidates_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("train_model_candidates requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    spec_id = payload.get("evaluation_spec_id")
    split_id = payload.get("split_manifest_id")
    spec = db.get(EvaluationSpec, spec_id) if isinstance(spec_id, str) else None
    split = db.get(SplitManifest, split_id) if isinstance(split_id, str) else None
    if spec is None:
        raise ValueError("EvaluationSpec not found")
    if split is None:
        raise ValueError("SplitManifest not found")
    raw_requested_models = payload.get("requested_models") or payload.get("normalized_models") or []
    if not isinstance(raw_requested_models, list):
        raise ValueError("requested model list is invalid")
    requested_models = payload.get("normalized_models") or raw_requested_models
    if not isinstance(requested_models, list):
        raise ValueError("normalized model list is invalid")
    unsupported_models = payload.get("unsupported_models") or []
    if not isinstance(unsupported_models, list):
        unsupported_models = []
    normalized_models: list[str] = []
    failures: list[dict[str, Any]] = [
        {
            "model": str(model),
            "status": "unsupported",
            "reason": "Model candidate is not recognized by Tablex yet.",
        }
        for model in unsupported_models
    ]
    for model in requested_models:
        normalized = normalize_model_candidate_name(str(model))
        if normalized is None:
            failures.append(
                {
                    "model": str(model),
                    "status": "unsupported",
                    "reason": "Model candidate is not recognized by Tablex yet.",
                }
            )
            continue
        if normalized not in normalized_models:
            normalized_models.append(normalized)
    successes: list[dict[str, Any]] = []
    for model in normalized_models:
        try:
            result = run_model_candidate(
                db,
                store=store,
                project=project,
                evaluation_spec=spec,
                split_manifest=split,
                model_candidate=model,
            )
        except ModelDependencyRequiredError as exc:
            failures.append(
                {
                    "model": model,
                    "status": "dependency_required",
                    "package": exc.package_name,
                    "install_spec": exc.install_spec,
                    "reason": str(exc),
                    "approval_required": True,
                }
            )
            continue
        except ValueError as exc:
            failures.append({"model": model, "status": "failed", "reason": str(exc)})
            continue
        successes.append(
            {
                "model": model,
                "status": "succeeded",
                "experiment_run_id": result.run.id,
                "model_version_id": result.model_version_id,
                "artifact_ids": result.artifact_ids,
                "metrics": result.metrics,
                "primary_metric_name": result.metrics.get("primary_metric_name"),
                "primary_metric_value": result.metrics.get("primary_metric_value"),
                "roc_auc": result.metrics.get("roc_auc"),
                "pr_auc": result.metrics.get("pr_auc"),
            }
        )
    status = "succeeded" if successes else "failed"
    output: dict[str, Any] = {
        "schema_version": "model_candidate_training.v1",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "requested_models": raw_requested_models,
        "normalized_models": normalized_models,
        "trained_models": [item["model"] for item in successes],
        "failed_models": failures,
        "success_count": len(successes),
        "failure_count": len(failures),
        "experiment_run_ids": [item["experiment_run_id"] for item in successes],
        "model_version_ids": [item["model_version_id"] for item in successes if item.get("model_version_id")],
        "results": successes,
        "worker_events": [
            {
                "worker_id": "training-candidates",
                "display_name": "Training Worker",
                "status": status,
                "headline": (
                    f"Trained {len(successes)} model candidate(s)"
                    if successes
                    else "Model candidate training needs attention"
                ),
                "detail": "; ".join(
                    [
                        *(f"{item['model']} -> {item['experiment_run_id']}" for item in successes),
                        *(f"{item['model']}: {item['status']}" for item in failures),
                    ]
                ),
                "job_id": job.id,
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "training_progress_estimate",
                    "is_estimate": True,
                    "series": [
                        {"step": "load split", "tokens": 80},
                        {"step": "fit models", "tokens": 120 * max(len(normalized_models), 1)},
                        {"step": "score", "tokens": 90 * max(len(successes), 1)},
                        {"step": "register artifacts", "tokens": 110 * max(len(successes), 1)},
                    ],
                },
            }
        ],
    }
    if not successes:
        output["job_status"] = "failed"
        output["error_message"] = "; ".join(
            f"{item['model']}: {item['status']}" for item in failures
        ) or "No model candidates completed training"
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="model_candidate_training_completed",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def planned_agent_contract_artifact_for_job(db: Session, job: Job, job_type: str) -> Artifact:
    payload = loads_json(job.input_json, {})
    artifact_id = payload.get("agent_task_contract_artifact_id")
    if not isinstance(artifact_id, str):
        raise ValueError(f"{job_type} requires agent_task_contract_artifact_id")
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise ValueError("AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise ValueError("Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise ValueError("AgentTaskContract artifact is not project-scoped")
    return contract_artifact


def prepare_planned_agent_workspace_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    contract_artifact = planned_agent_contract_artifact_for_job(db, job, "prepare_planned_agent_workspace")
    project = db.get(Project, contract_artifact.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = prepare_workspace_from_contract_artifact(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    return {
        "schema_version": result.manifest["schema_version"],
        "task_id": result.manifest["task_id"],
        "agent_task_contract_artifact_id": contract_artifact.id,
        "agent_workspace_manifest_artifact_id": result.artifact.id,
        "artifact_id": result.artifact.id,
        "artifact_ids": [result.artifact.id],
        "materialized_context_count": result.materialized_context_count,
        "materialized_relational_context_count": result.materialized_relational_context_count,
        "materialized_library_asset_count": result.materialized_library_asset_count,
        "skipped_source_count": result.skipped_source_count,
        "workspace_path": result.manifest["workspace_path"],
    }


def review_agent_task_readiness_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    contract_artifact = planned_agent_contract_artifact_for_job(db, job, "review_agent_task_readiness")
    project = db.get(Project, contract_artifact.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = review_agent_task_readiness(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    return {
        "schema_version": result.review["schema_version"],
        "task_id": result.review["task_id"],
        "agent_task_contract_artifact_id": contract_artifact.id,
        "agent_task_readiness_review_artifact_id": result.review_artifact.id,
        "agent_task_readiness_report_artifact_id": result.report_artifact.id,
        "visualization_id": result.visualization.id,
        "visualization_artifact_id": result.visualization_artifact.id,
        "report_id": result.report.id,
        "artifact_id": result.review_artifact.id,
        "artifact_ids": result.artifact_ids,
        "readiness_status": result.review["status"],
        "blocker_count": result.review["blocker_count"],
        "warning_count": result.review["warning_count"],
        "pass_count": result.review["pass_count"],
        "next_actions": result.review["next_actions"][:3],
    }


def planned_agent_execution_job_output(
    contract_artifact: Artifact,
    result: PlannedAgentTaskExecutionResult,
) -> dict[str, Any]:
    return {
        "agent_task_contract_artifact_id": contract_artifact.id,
        "task_id": result.agent_result.task_id,
        "runner": result.agent_result.outputs.get("runner"),
        "agent_status": result.agent_result.status,
        "agent_final_message": result.agent_result.final_message,
        "agent_failure_reason": result.agent_result.failure_reason,
        "agent_workspace_manifest_artifact_id": result.workspace_artifact_id,
        "agent_task_readiness_review_artifact_id": result.readiness_artifact_id,
        "readiness_status": result.readiness_status,
        "artifact_ids": result.artifact_ids,
        "ingested_artifact_ids": result.ingested_artifact_ids,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "experiment_run_id": result.experiment_ingestion.experiment_run_id,
        "agent_metrics_artifact_id": result.experiment_ingestion.metrics_artifact_id,
        "agent_feature_recipe_artifact_id": result.experiment_ingestion.feature_recipe_artifact_id,
        "approach_decision_trace_artifact_id": result.approach_decision_trace_artifact_id,
        "relational_context_source_count": result.relational_context_summary.get("source_count"),
        "relational_context_summary_artifact_id": result.relational_context_summary_artifact_id,
        "source_citation_manifest_artifact_id": result.experiment_ingestion.citation_manifest_artifact_id,
        "citation_audit_report_id": result.experiment_ingestion.citation_audit_report_id,
        "citation_audit_report_artifact_id": result.experiment_ingestion.citation_audit_report_artifact_id,
        "citation_evidence_id": result.experiment_ingestion.citation_evidence_id,
        "citation_visualization_id": result.experiment_ingestion.citation_visualization_id,
        "citation_visualization_artifact_id": result.experiment_ingestion.citation_visualization_artifact_id,
        "visualization_ids": result.experiment_ingestion.visualization_ids,
        "requires_human_review": result.agent_result.requires_human_review,
        "auto_prepared_workspace": result.auto_prepared_workspace,
    }


def run_planned_agent_task_stub_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    contract_artifact = planned_agent_contract_artifact_for_job(db, job, "run_planned_agent_task_stub")
    project = db.get(Project, contract_artifact.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = run_planned_agent_task_local_stub(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    output = planned_agent_execution_job_output(contract_artifact, result)
    return output


def run_planned_agent_task_codex_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    contract_artifact = planned_agent_contract_artifact_for_job(db, job, "run_planned_agent_task_codex")
    project = db.get(Project, contract_artifact.project_id)
    if project is None:
        raise ValueError("Project not found")
    result = run_planned_agent_task_codex_cli(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    contract_payload = load_contract_payload(contract_artifact)
    target_state = AutonomousLoopState(project=project, job=job)
    if contract_payload.get("task_type") == "target_definition_review":
        ingest_codex_target_definition_proposal(
            db,
            project=project,
            state=target_state,
            agent_result=result.agent_result,
            source_artifact_id=result.artifact_ids[0] if result.artifact_ids else None,
        )
    status = "failed" if result.agent_result.status == "failed" else "succeeded"
    output: dict[str, Any] = {
        "schema_version": "planned_agent_task_codex_execution.v1",
        "agent_task_contract_artifact_id": contract_artifact.id,
        "task_id": result.agent_result.task_id,
        "agent_status": result.agent_result.status,
        "agent_final_message": result.agent_result.final_message,
        "agent_failure_reason": result.agent_result.failure_reason,
        "agent_give_up_reason": result.agent_result.give_up_reason,
        "required_next_inputs": result.agent_result.required_next_inputs,
        "codex_cli": result.agent_result.outputs.get("codex_cli") if isinstance(result.agent_result.outputs, dict) else None,
        "agent_workspace_manifest_artifact_id": result.workspace_artifact_id,
        "agent_task_readiness_review_artifact_id": result.readiness_artifact_id,
        "readiness_status": result.readiness_status,
        "artifact_ids": result.artifact_ids,
        "ingested_artifact_ids": result.ingested_artifact_ids,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "experiment_run_id": result.experiment_ingestion.experiment_run_id,
        "agent_metrics_artifact_id": result.experiment_ingestion.metrics_artifact_id,
        "agent_feature_recipe_artifact_id": result.experiment_ingestion.feature_recipe_artifact_id,
        "approach_decision_trace_artifact_id": result.approach_decision_trace_artifact_id,
        "visualization_ids": result.experiment_ingestion.visualization_ids,
        "autonomous_state_steps": [step.to_dict() for step in target_state.steps],
        "project_target_column": project.target_column,
        "worker_events": [
            {
                "worker_id": "codex-runner",
                "display_name": "Codex Runner",
                "status": status,
                "headline": (
                    "Codex completed the planned agent task"
                    if status == "succeeded"
                    else "Codex runner needs attention"
                ),
                "detail": result.agent_result.final_message,
                "job_id": job.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": False,
                "token_usage": {
                    "source": "codex_runner_result",
                    "is_estimate": True,
                    "series": [
                        {"step": "load workspace", "tokens": 160},
                        {"step": "reason", "tokens": 900},
                        {"step": "write artifacts", "tokens": 240},
                    ],
                },
            }
        ],
    }
    if status == "failed":
        output["job_status"] = "failed"
        output["error_message"] = result.agent_result.failure_reason or result.agent_result.final_message
    continuation_job = maybe_queue_autonomous_session_continuation(
        db,
        project=project,
        job=job,
        reason="codex_session_returned",
    )
    if continuation_job is not None:
        output["session_continuation_job_id"] = continuation_job.id
    return output


def start_autonomous_loop_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("start_autonomous_loop requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    if project.current_phase != "AUTONOMOUS_LOOP" or project.autonomy_mode != "full_auto":
        return {
            "schema_version": "autonomous_loop_start.v1",
            "status": "stopped",
            "reason": "Full Auto is no longer active for this project.",
            "worker_events": [
                autonomous_session_worker_event(
                    job,
                    project,
                    status="succeeded",
                    headline="Autonomous session is off",
                )
            ],
        }
    runner_mode = str(payload.get("runner_mode") or RUNNER_MODE_CODEX_IF_AVAILABLE)
    output = run_autonomous_loop_tick(
        db,
        store=store,
        project=project,
        job=job,
        runner_mode=runner_mode,
        autonomy_mode="full_auto",
        locale=locale,
        agent_model=payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None,
        utility_model=payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None,
    )
    next_job = queue_autonomous_session_continuation(
        db,
        project=project,
        reason="start_after_data_intake_completed",
        parent_job_id=job.id,
        exclude_job_id=job.id,
        runner_mode=runner_mode,
        locale=locale,
        run_after_seconds=15,
    )
    if next_job is not None:
        output["session_continuation_job_id"] = next_job.id
    output["schema_version"] = "autonomous_loop_start.v1"
    return output


def continue_autonomous_session_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    payload = loads_json(job.input_json, {})
    project_id = job.project_id
    if project_id is None:
        raise ValueError("continue_autonomous_session requires a project_id")
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    runner_mode = str(payload.get("runner_mode") or RUNNER_MODE_CODEX_IF_AVAILABLE)
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
    if project.current_phase != "AUTONOMOUS_LOOP" or project.autonomy_mode != "full_auto":
        return {
            "schema_version": "autonomous_session_continuation.v1",
            "status": "stopped",
            "reason": "Full Auto is no longer active for this project.",
            "worker_events": [autonomous_session_worker_event(job, project, status="succeeded", headline="Autonomous session is off")],
        }
    active_child_ids = active_autonomous_child_job_ids(db, project.id, exclude_job_id=job.id)
    if active_child_ids:
        next_job = queue_autonomous_session_continuation(
            db,
            project=project,
            reason="waiting_for_child_workers",
            parent_job_id=job.id,
            exclude_job_id=job.id,
            runner_mode=runner_mode,
            locale=locale,
            run_after_seconds=15,
        )
        return {
            "schema_version": "autonomous_session_continuation.v1",
            "status": "waiting_for_child_workers",
            "active_child_job_ids": active_child_ids,
            "session_continuation_job_id": next_job.id if next_job is not None else None,
            "worker_events": [
                autonomous_session_worker_event(
                    job,
                    project,
                    status="succeeded",
                    headline="Main session is waiting for child workers",
                    detail=f"Waiting for {len(active_child_ids)} worker(s) before resuming Codex context.",
                )
            ],
        }
    output = run_autonomous_loop_tick(
        db,
        store=store,
        project=project,
        job=job,
        runner_mode=runner_mode,
        autonomy_mode="full_auto",
        locale=locale,
        agent_model=payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None,
        utility_model=payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None,
    )
    created_job_ids = output.get("created_job_ids") if isinstance(output.get("created_job_ids"), list) else []
    next_delay_seconds = 15 if created_job_ids else 60
    next_job = queue_autonomous_session_continuation(
        db,
        project=project,
        reason="continuation_tick_completed",
        parent_job_id=job.id,
        exclude_job_id=job.id,
        runner_mode=runner_mode,
        locale=locale,
        run_after_seconds=next_delay_seconds,
    )
    if next_job is not None:
        output["session_continuation_job_id"] = next_job.id
    output["schema_version"] = "autonomous_session_continuation.v1"
    return output
def maybe_queue_autonomous_session_continuation(
    db: Session,
    *,
    job: Job,
    reason: str,
    project: Project | None = None,
    project_id: str | None = None,
) -> Job | None:
    resolved_project = project
    if resolved_project is None and project_id is not None:
        resolved_project = db.get(Project, project_id)
    if resolved_project is None or resolved_project.current_phase != "AUTONOMOUS_LOOP":
        return None
    return queue_autonomous_session_continuation(
        db,
        project=resolved_project,
        reason=reason,
        parent_job_id=job.id,
        runner_mode=RUNNER_MODE_CODEX_IF_AVAILABLE,
        run_after_seconds=10,
    )


def autonomous_session_worker_event(
    job: Job,
    project: Project,
    *,
    status: str,
    headline: str,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "worker_id": "autonomous-session",
        "display_name": "Autonomous Session",
        "status": status,
        "headline": headline,
        "detail": detail or "The harness is keeping the main Full Auto thread warm and ready to resume.",
        "job_id": job.id,
        "project_id": project.id,
        "target_tab": "Home",
        "target_anchor": "agent-workspace",
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "autonomous_session_heartbeat",
            "is_estimate": True,
            "series": [
                {"step": "observe", "tokens": 40},
                {"step": "resume", "tokens": 80},
                {"step": "handoff", "tokens": 120},
            ],
        },
    }


def default_handlers() -> dict[str, JobHandler]:
    handlers = {job_type: stub_job_handler for job_type in JOB_TYPES}
    handlers.update(concrete_handlers())
    return handlers


def concrete_handlers() -> dict[str, JobHandler]:
    handlers: dict[str, JobHandler] = {}
    handlers["profile_dataset"] = profile_dataset_handler
    handlers["infer_assumptions"] = infer_assumptions_handler
    handlers["save_guided_journey_snapshot"] = save_guided_journey_snapshot_handler
    handlers["save_autonomous_decision_brief"] = save_autonomous_decision_brief_handler
    handlers["compare_guided_journey_snapshots"] = compare_guided_journey_snapshots_handler
    handlers["upload_relational_schema_hint"] = upload_relational_schema_hint_handler
    handlers["upload_data_bundle"] = upload_data_bundle_handler
    handlers["select_primary_table"] = select_primary_table_handler
    handlers["translate_tier3_content"] = translate_tier3_content_handler
    handlers["generate_user_avatar_candidates"] = generate_user_avatar_candidates_handler
    handlers["download_public_benchmark_archive"] = download_public_benchmark_archive_handler
    handlers["import_benchmark_dataset"] = import_benchmark_dataset_handler
    handlers["run_benchmark_fixture_smoke"] = run_benchmark_fixture_smoke_handler
    handlers["run_public_benchmark_workflow"] = run_public_benchmark_workflow_handler
    handlers["create_benchmark_scenario_pack"] = create_benchmark_scenario_pack_handler
    handlers["create_benchmark_collection_plan"] = create_benchmark_collection_plan_handler
    handlers["create_relational_feature_plan"] = create_relational_feature_plan_handler
    handlers["build_relational_feature_recipe"] = build_relational_feature_recipe_handler
    handlers["diagnose_relational_feature_scenarios"] = diagnose_relational_feature_scenarios_handler
    handlers["create_benchmark_evidence_pack"] = create_benchmark_evidence_pack_handler
    handlers["probe_kaggle_benchmark_access"] = probe_kaggle_benchmark_access_handler
    handlers["fetch_kaggle_competition_inventory"] = fetch_kaggle_competition_inventory_handler
    handlers["download_kaggle_selected_files"] = download_kaggle_selected_files_handler
    handlers["design_evaluation_candidates"] = design_evaluation_candidates_handler
    handlers["compare_evaluation_scenarios"] = compare_evaluation_scenarios_handler
    handlers["review_evaluation_approval"] = review_evaluation_approval_handler
    handlers["analyze_data_quality"] = analyze_data_quality_handler
    handlers["run_eda_review"] = run_eda_review_handler
    handlers["create_adaptive_strategy_brief"] = create_adaptive_strategy_brief_handler
    handlers["plan_research"] = plan_research_handler
    handlers["create_research_source_pack"] = create_research_source_pack_handler
    handlers["run_research_source_pack_stub"] = run_research_source_pack_stub_handler
    handlers["create_research_synthesis"] = create_research_synthesis_handler
    handlers["generate_research_brief"] = generate_research_brief_handler
    handlers["generate_approach_candidates"] = generate_approach_candidates_handler
    handlers["prepare_agent_context"] = prepare_agent_context_handler
    handlers["create_experiment_plan"] = create_experiment_plan_handler
    handlers["run_agent_task"] = run_agent_task_handler
    handlers["create_notebook_authoring_brief"] = create_notebook_authoring_brief_handler
    handlers["prepare_data_understanding_notebook_authoring"] = prepare_data_understanding_notebook_authoring_handler
    handlers["plan_agent_task"] = plan_agent_task_handler
    handlers["plan_notebook_execution"] = plan_notebook_execution_handler
    handlers["prewarm_native_marimo_session"] = prewarm_native_marimo_session_handler
    handlers["prepare_result_notebook_evidence"] = prepare_result_notebook_evidence_handler
    handlers["generate_decision_report"] = generate_decision_report_handler
    handlers["draft_project_report"] = draft_project_report_handler
    handlers["create_visualization_spec"] = create_visualization_spec_handler
    handlers["generate_insights"] = generate_insights_handler
    handlers["generate_decision_dashboard"] = generate_decision_dashboard_handler
    handlers["compare_experiments"] = compare_experiments_handler
    handlers["draft_run_report"] = draft_run_report_handler
    handlers["analyze_evaluation_diagnostics"] = analyze_evaluation_diagnostics_handler
    handlers["materialize_model_diagnostics_artifacts"] = materialize_model_diagnostics_artifacts_handler
    handlers["validate_model_package"] = validate_model_package_handler
    handlers["register_prediction_pipeline"] = register_prediction_pipeline_handler
    handlers["run_prediction_pipeline"] = run_prediction_pipeline_handler
    handlers["score_pilot_outcomes"] = score_pilot_outcomes_handler
    handlers["prepare_model_diagnostics_notebook_authoring"] = prepare_model_diagnostics_notebook_authoring_handler
    handlers["plan_baseline_strategy"] = plan_baseline_strategy_handler
    handlers["run_baseline"] = run_baseline_handler
    handlers["build_split_manifest"] = build_split_manifest_handler
    handlers["train_model_candidates"] = train_model_candidates_handler
    handlers["prepare_planned_agent_workspace"] = prepare_planned_agent_workspace_handler
    handlers["review_agent_task_readiness"] = review_agent_task_readiness_handler
    handlers["run_planned_agent_task_stub"] = run_planned_agent_task_stub_handler
    handlers["run_planned_agent_task_codex"] = run_planned_agent_task_codex_handler
    handlers["start_autonomous_loop"] = start_autonomous_loop_handler
    handlers["continue_autonomous_session"] = continue_autonomous_session_handler
    handlers["agent_chat_turn"] = agent_chat_turn_handler
    return handlers


def create_default_worker(
    worker_id: str = "local-worker", store: LocalArtifactStore | None = None, include_stub_handlers: bool = False
) -> SyncWorker:
    artifact_store = store or LocalArtifactStore(get_settings().artifact_root)
    handlers = default_handlers() if include_stub_handlers else concrete_handlers()
    return SyncWorker(handlers=handlers, store=artifact_store, worker_id=worker_id)
