from __future__ import annotations

import csv
import hashlib
import importlib.metadata as importlib_metadata
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.agent.runners import codex_harness_config_args, safe_env
from tabular_harness.core.config import get_settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    Asset,
    AssetReference,
    AssetVersion,
    DatasetSnapshot,
    Evidence,
    ExperimentRun,
    Job,
    LineageEdge,
    ModelVersion,
    Project,
    ResearchPlanRevision,
    User,
    utc_now,
)
from tabular_harness.services.agent_inbox import inbox_processed_path, list_inbox_entries
from tabular_harness.services.agent_notebook_quality import (
    notebook_quality_feedback_from_metadata,
)
from tabular_harness.services.agent_notebook_registration import (
    apply_notebook_request_metadata,
    notebook_artifact_from_request,
    notebook_registration_chat_status,
    notebook_registration_visible_surfaces,
)
from tabular_harness.services.agent_outputs import (
    asset_type_for_session_output,
    is_chat_update_path,
    metadata_for_session_output,
    notebook_kind_for_session_output,
    session_output_artifact_name,
    session_output_rejection_message_kind,
    session_output_rejection_reason,
    should_register_session_output,
    should_skip_session_output,
)
from tabular_harness.services.agent_prompting import build_turn_prompt, session_protocol_text
from tabular_harness.services.agent_requests.data import (
    DATA_REQUEST_SCHEMA_VERSION,
    TASK_SPEC_SCHEMA_VERSION,
    data_acks_dir,
    data_requests_dir,
)
from tabular_harness.services.agent_requests.data import (
    process_data_tool_requests as process_data_tool_requests_impl,
)
from tabular_harness.services.agent_requests.evaluation import (
    EVALUATION_ACK_SCHEMA_VERSION,
    EVALUATION_REQUEST_SCHEMA_VERSION,
    evaluation_acks_dir,
    evaluation_request_rejection_path,
    evaluation_requests_dir,
)
from tabular_harness.services.agent_requests.evaluation import (
    process_evaluation_tool_requests as process_evaluation_tool_requests_impl,
)
from tabular_harness.services.agent_requests.deliverables import (
    DELIVERABLE_ACK_SCHEMA_VERSION,
    DELIVERABLE_REQUEST_SCHEMA_VERSION,
)
from tabular_harness.services.agent_requests.deliverables import (
    process_deliverable_tool_requests as process_deliverable_tool_requests_impl,
)
from tabular_harness.services.agent_requests.model_diagnostics import (
    MODEL_DIAGNOSTICS_ACK_SCHEMA_VERSION,
    MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION,
    model_diagnostics_acks_dir,
    model_diagnostics_request_rejection_path,
    model_diagnostics_requests_dir,
)
from tabular_harness.services.agent_requests.model_diagnostics import (
    process_model_diagnostics_tool_requests as process_model_diagnostics_tool_requests_impl,
)
from tabular_harness.services.agent_requests.notebooks import (
    NOTEBOOK_REQUEST_SCHEMA_VERSION,
    notebook_acks_dir,
    notebook_requests_dir,
)
from tabular_harness.services.agent_requests.notebooks import (
    process_notebook_tool_requests as process_notebook_tool_requests_impl,
)
from tabular_harness.services.agent_requests.pilot import (
    PILOT_ACK_SCHEMA_VERSION,
    PILOT_REQUEST_SCHEMA_VERSION,
    pilot_acks_dir,
    pilot_request_rejection_path,
    pilot_requests_dir,
)
from tabular_harness.services.agent_requests.pilot import (
    process_pilot_tool_requests as process_pilot_tool_requests_impl,
)
from tabular_harness.services.agent_requests.pipelines import (
    PIPELINE_ACK_SCHEMA_VERSION,
    PIPELINE_REQUEST_SCHEMA_VERSION,
    PipelineToolValidationError,
    ensure_prediction_pipeline_smoke_python,
    execute_pipeline_registration_request,
    normalize_pipeline_manifest,
    pipeline_acks_dir,
    pipeline_metric_reproduction_summary,
    pipeline_requests_dir,
    pipeline_tool_error_payload,
    pipeline_tool_issue,
    prediction_pipeline_requirements_hash,
    require_manifest_column_name,
    require_nonempty_string,
    resolve_workspace_relative_path,
    resolve_workspace_relative_path_allowing_symlink_target,
    smoke_validate_prediction_pipeline,
    smoke_value_for_manifest_dtype,
    validate_pipeline_requirements_file,
    write_pipeline_tool_ack,
)
from tabular_harness.services.agent_requests.pipelines import (
    process_pipeline_tool_requests as process_pipeline_tool_requests_impl,
)
from tabular_harness.services.agent_requests.research import (
    RESEARCH_REQUEST_SCHEMA_VERSION,
    research_acks_dir,
    research_request_rejection_path,
    research_requests_dir,
)
from tabular_harness.services.agent_requests.research import (
    process_research_tool_requests as process_research_tool_requests_impl,
)
from tabular_harness.services.agent_requests.research_plan import (
    RESEARCH_PLAN_ACK_SCHEMA_VERSION,
    RESEARCH_PLAN_REQUEST_SCHEMA_VERSION,
    research_plan_acks_dir,
    research_plan_request_failure_attention_key,
    research_plan_requests_dir,
)
from tabular_harness.services.agent_requests.research_plan import (
    process_research_plan_tool_requests as process_research_plan_tool_requests_impl,
)
from tabular_harness.services.agent_session_chat import (
    agent_session_attention_chat_turn_exists,
    agent_session_notebook_registration_event_exists,
    annotate_agent_chat_turn_with_source_event,
    attach_notebook_artifacts_to_current_research_plan,
    attach_registered_session_notebooks_to_current_research_plan,
    attention_chat_message,
    chat_update_actions_from_research_plan_evidence,
    chat_update_message_from_text,
    latest_agent_session_notebook_registration_event,
    maybe_defer_agent_session_notebook_registration,
    maybe_register_chat_update_from_workspace_output,
    notebook_artifact_has_declared_context,
    notebook_runtime_failure_retry_due,
    reconcile_project_notebook_chat_links,
    reconcile_project_notebook_context_requests,
    reconcile_project_notebook_quality_requests,
    register_agent_session_attention_chat_turn,
    register_agent_session_notebook_chat_turn,
    register_agent_session_notebook_chat_turn_from_registration_event,
    register_agent_session_notebook_source_output,
    register_pending_agent_session_notebooks,
    register_research_registration_chat_turn,
    request_context_for_auto_registered_notebooks,
    request_quality_repair_for_session_notebooks,
)
from tabular_harness.services.agent_session_inbox import (
    append_user_instruction_to_workspace_inbox,
    build_default_goal_text,
    data_framing_request_path,
    latest_research_plan_contract_request_event,
    latest_user_instruction_path,
    notebook_context_request_path,
    notebook_quality_repair_path,
    notebook_request_rejection_path,
    notebook_runtime_failure_path,
    progress_request_path,
    research_plan_artifact_rejection_path,
    research_plan_contract_issue_hash,
    research_plan_contract_request_path,
    research_plan_current_work_request_path,
    research_plan_request_rejection_path,
    session_output_rejection_path,
    task_spec_request_path,
    user_instructions_inbox_path,
    write_notebook_context_request_to_workspace_inbox,
    write_notebook_quality_repair_to_workspace_inbox,
    write_notebook_request_rejection_to_workspace_inbox,
    write_notebook_runtime_failure_to_workspace_inbox,
    write_progress_request_to_workspace_inbox,
    write_research_plan_artifact_rejection_to_workspace_inbox,
    write_research_plan_contract_request_to_workspace_inbox,
    write_research_plan_current_work_request_to_workspace_inbox,
    write_research_plan_request_rejection_to_workspace_inbox,
    write_session_output_rejection_to_workspace_inbox,
)
from tabular_harness.services.agent_session_results import (
    experiment_acks_dir,
    experiment_requests_dir,
    ingest_registered_session_experiment_artifacts,
    process_experiment_result_requests,
)
from tabular_harness.services.agent_supervisor import (
    ACTIVE_SESSION_STATUSES,
    MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS,
    MAIN_AUTONOMOUS_SESSION_TYPE,
    RETRY_BACKOFF_SECONDS,
    STALE_PROCESS_TERM_GRACE_SECONDS,
    SUPERVISOR_LEASE_TTL_SECONDS,
    TERMINAL_SESSION_STATUSES,
    acquire_supervisor_lease,
    acquire_supervisor_slot,
    active_main_session,
    append_supervisor_lease_lost_event,
    clear_stale_stored_runner_pid,
    consecutive_runner_failure_count,
    default_supervisor_lease_owner_id,
    latest_main_session,
    mark_user_instructions_delivered,
    pid_is_alive,
    pid_matches_agent_codex_process,
    project_session_still_registered,
    release_supervisor_lease,
    release_supervisor_slot,
    renew_supervisor_lease,
    retry_delay_seconds,
    start_supervisor_lease_heartbeat,
    stop_main_session,
    supervisor_lease_active,
    supervisor_lease_lost_event_is_set,
    supervisor_slot_active,
    terminate_stale_codex_process,
)
from tabular_harness.services.agent_task_spec_nudge import (
    maybe_request_data_framing_update,
    maybe_request_task_spec_update,
)
from tabular_harness.services.agent_transcript import (
    _TRANSCRIPT_EVENT_NEXT_INDEX,
    StreamFileTailer,
    append_codex_stream_line,
    append_codex_stream_lines,
    append_runner_stream_to_workspace,
    append_session_event,
    codex_jsonl_event_type,
    publish_raw_codex_transcript_snapshot,
    reserve_transcript_event_indexes,
    session_to_dict,
    transcript_event_to_dict,
)
from tabular_harness.services.agent_workspace import (
    CODEX_RAW_TRANSCRIPT_FILENAME,
    CODEX_STDERR_LOG_FILENAME,
    build_session_context,
    latest_project_response_locale,
    prepare_session_workspace,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    research_plan_revision_context,
    session_workspace_path,
)
from tabular_harness.services.agent_workspace_outputs import (
    ingest_session_workspace_outputs_impl,
    latest_session_artifact_for_workspace_path,
)
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.dataset_profile import profile_dataset_artifact
from tabular_harness.services.deliverable_expectations import (
    fulfill_run_model_diagnostics_notebook_expectations,
    maybe_write_open_deliverable_expectation_observation,
)
from tabular_harness.services.jobs import TERMINAL_STATUSES as TERMINAL_JOB_STATUSES
from tabular_harness.services.jobs import mark_job_succeeded
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.research_plan_timeline import (
    research_plan_contract_validation_summary,
    research_plan_evidence_links,
)
from tabular_harness.services.research_plans import (
    PLAN_CURRENT_STATUSES,
    ResearchPlanValidationError,
    attach_research_plan_artifact,
    commit_research_plan_artifact_revision,
    ensure_harness_initial_research_plan_revision,
    latest_research_plan_current_work,
    latest_research_plan_revision,
    research_plan_artifact_is_native_marimo_source,
    research_plan_revision_document,
    research_plan_source_is_marimo_notebook,
)

SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS = 30
STREAM_EVENT_FLUSH_INTERVAL_SECONDS = 0.5
STREAM_EVENT_FLUSH_MAX_LINES = 24
NATIVE_NOTEBOOK_ASSET_TYPES = {"analysis_notebook", "marimo_notebook"}
PROGRESS_UPDATE_NUDGE_AFTER_SECONDS = 180
PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS = 300
RESEARCH_PLAN_CURRENT_WORK_NUDGE_MIN_INTERVAL_SECONDS = 300
RESEARCH_PLAN_CURRENT_WORK_STALE_AFTER_CODEX_OUTPUT_SECONDS = 120
NOTEBOOK_RUNTIME_RETRY_AFTER_SECONDS = 5 * 60

def start_or_resume_main_session(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    goal_text: str | None,
    autonomy_mode: str,
    runner_kind: str = "codex_cli",
    created_by: str | None = None,
) -> AgentSession:
    existing = active_main_session(db, project.id)
    if existing is not None:
        append_session_event(
            db,
            existing,
            source="tablex_sidecar",
            event_type="session_resume_requested",
            role="harness",
            title="Resume requested",
            content="An active Codex session is already running for this project, so supervision will continue from the current state.",
            payload={"project_id": project.id, "autonomy_mode": autonomy_mode},
        )
        existing.status = "running"
        existing.updated_at = utc_now()
        return existing

    stopped = latest_main_session(db, project.id)
    if stopped is not None and stopped.status in {"stopped", "completed"}:
        append_session_event(
            db,
            stopped,
            source="tablex_sidecar",
            event_type="session_resumed_after_power_on",
            role="harness",
            title="Full Auto resumed",
            content="The existing main Codex session was resumed so Raw transcript and workspace history stay continuous.",
            payload={"project_id": project.id, "autonomy_mode": autonomy_mode},
        )
        stopped.status = "between_turns"
        stopped.autonomy_mode = autonomy_mode
        stopped.runner_kind = runner_kind
        stopped.pid = None
        stopped.ended_at = None
        stopped.started_at = stopped.started_at or utc_now()
        stopped.updated_at = utc_now()
        return stopped

    goal = goal_text or build_default_goal_text(db, project)
    session = AgentSession(
        id=new_id("ags"),
        project_id=project.id,
        org_id=project.org_id,
        session_type=MAIN_AUTONOMOUS_SESSION_TYPE,
        status="starting",
        autonomy_mode=autonomy_mode,
        runner_kind=runner_kind,
        goal_text=goal,
        workspace_path=str(session_workspace_path(store, project.id, new_id("session_workspace"))),
        created_by=created_by or "local-user",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.workspace_path = str(session_workspace_path(store, project.id, session.id))
    db.add(session)
    db.flush()
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="session_created",
        role="harness",
        title="Full Auto started",
        content="The analysis has started from the current project state.",
        payload={"project_id": project.id, "runner_kind": runner_kind, "autonomy_mode": autonomy_mode},
    )
    return session


def maybe_request_research_plan_contract_revision(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    locale: str | None = None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES:
        return None
    revision = latest_research_plan_revision(db, project_id=project.id)
    if revision is None:
        return None
    payload, source = research_plan_revision_context(revision)
    validation = research_plan_contract_validation_summary(db, project_id=project.id, payload=payload)
    if validation.get("status") != "needs_revision":
        return None
    issue_hash = research_plan_contract_issue_hash(validation)
    existing_event = latest_research_plan_contract_request_event(db, session_id=session.id, issue_hash=issue_hash)
    if existing_event is not None:
        return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="research_plan_contract_revision_requested",
        role="harness",
        title="ResearchPlan revision requested",
        content="Tablex asked Codex to re-commit the ResearchPlan through the validated request channel.",
        payload={
            "locale": locale,
            "issue_hash": issue_hash,
            "source": source,
            "validation": validation,
        },
        update_heartbeat=False,
    )
    write_research_plan_contract_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        validation=validation,
    )
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=f"research_plan_contract_needs_revision:{issue_hash}",
        status="needs_attention",
        message_kind="research_plan_contract_needs_revision",
        details={
            "issue_hash": issue_hash,
            "error_count": validation.get("error_count", 0),
            "warning_count": validation.get("warning_count", 0),
            "issue_count": validation.get("issue_count", 0),
            "top_issue_codes": [issue.get("code") for issue in validation.get("issues", [])[:6] if isinstance(issue, dict)],
        },
    )
    return event


def latest_codex_transcript_output_at(db: Session, *, session_id: str) -> datetime | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.source.in_(["codex_cli", "codex_cli_stderr"]),
            AgentTranscriptEvent.event_type != "process_exited",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    return event.created_at if event is not None else None


def latest_codex_chat_update_at(db: Session, *, project_id: str, session_id: str) -> datetime | None:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") == "main_codex_session_chat_update" and metadata.get("agent_session_id") == session_id:
            return artifact.created_at
    return None


def latest_progress_update_nudge_at(db: Session, *, session_id: str) -> datetime | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.source == "tablex_sidecar",
            AgentTranscriptEvent.event_type == "progress_update_requested",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    return event.created_at if event is not None else None


def latest_research_plan_current_work_nudge_at(db: Session, *, session_id: str) -> datetime | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.source == "tablex_sidecar",
            AgentTranscriptEvent.event_type == "research_plan_current_work_requested",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    return event.created_at if event is not None else None


def research_plan_current_work_refresh_reason(
    db: Session,
    *,
    session: AgentSession,
    now: datetime | None = None,
) -> tuple[ResearchPlanRevision | None, str | None, str | None]:
    revision = latest_research_plan_revision(db, project_id=session.project_id)
    if revision is None:
        return None, None, None
    if research_plan_revision_has_no_runnable_blocks(revision):
        return revision, None, None
    current = latest_research_plan_current_work(db, project_id=session.project_id)
    if current is None or current.revision_id != revision.id or not current.node_id.strip():
        return revision, "missing", current.node_id if current is not None else None
    latest_output = latest_codex_transcript_output_at(db, session_id=session.id)
    if latest_output is None:
        return revision, None, current.node_id
    observed_at = now or utc_now()
    current_updated_at = current.updated_at
    if current_updated_at.tzinfo is None:
        current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
    if latest_output.tzinfo is None:
        latest_output = latest_output.replace(tzinfo=timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    stale_after_seconds = RESEARCH_PLAN_CURRENT_WORK_STALE_AFTER_CODEX_OUTPUT_SECONDS
    if (
        latest_output.astimezone(timezone.utc) - current_updated_at.astimezone(timezone.utc)
    ).total_seconds() >= stale_after_seconds and (
        observed_at.astimezone(timezone.utc) - current_updated_at.astimezone(timezone.utc)
    ).total_seconds() >= stale_after_seconds:
        return revision, "stale_after_codex_output", current.node_id
    return revision, None, current.node_id


def research_plan_revision_has_no_open_blocks(revision: ResearchPlanRevision) -> bool:
    document = research_plan_revision_document(revision)
    blocks = document.get("timeline_blocks") if isinstance(document, dict) else None
    if not isinstance(blocks, list) or not blocks:
        return False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        status = str(block.get("status") or "").strip().lower()
        if status and status not in {"done", "complete", "completed"}:
            return False
    return True


def research_plan_revision_has_no_runnable_blocks(revision: ResearchPlanRevision) -> bool:
    document = research_plan_revision_document(revision)
    blocks = document.get("timeline_blocks") if isinstance(document, dict) else None
    if not isinstance(blocks, list) or not blocks:
        return False
    non_runnable_statuses = {"done", "complete", "completed", "skipped", "waiting", "blocked"}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        status = str(block.get("status") or "").strip().lower()
        if status not in non_runnable_statuses:
            return False
    return True


def pending_main_session_user_instruction_exists(db: Session, *, session: AgentSession) -> bool:
    delivered_event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session.id,
            AgentTranscriptEvent.event_type == "user_instructions_delivered_to_codex",
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    delivered_index = -1
    if delivered_event is not None:
        payload = loads_json(delivered_event.payload_json, {})
        value = payload.get("last_user_event_index")
        delivered_index = int(value) if isinstance(value, int) else -1
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session.id,
            AgentTranscriptEvent.source == "user",
            AgentTranscriptEvent.event_type == "user_instruction",
            AgentTranscriptEvent.event_index > delivered_index,
        )
        .order_by(AgentTranscriptEvent.event_index.asc())
        .limit(1)
    )
    return event is not None


def latest_request_or_rejection_artifact_at(db: Session, *, project_id: str) -> datetime | None:
    artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type.in_(
                [
                    "dataset_snapshot",
                    "uploaded_supporting_table",
                    "research_findings_report",
                    "prediction_pipeline",
                    "pilot_prediction_batch",
                    "pilot_outcome_batch",
                ]
            ),
        )
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    return artifact.created_at if artifact is not None else None


COMPLETED_PLAN_NON_ACTIONABLE_INBOX_TYPES = {
    "progress_request",
    "research_plan_current_work_request",
}


def processed_workspace_inbox_filenames(session: AgentSession) -> set[str]:
    if not session.workspace_path:
        return set()
    processed_path = inbox_processed_path(Path(session.workspace_path))
    if not processed_path.exists():
        return set()
    processed: set[str] = set()
    try:
        lines = processed_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.endswith(".json") and " " not in text and "{" not in text:
            processed.add(text)
            continue
        try:
            payload = loads_json(text, {})
        except Exception:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("entry"), str):
            processed.add(str(payload["entry"]))
    return processed


def unprocessed_actionable_workspace_inbox_exists(session: AgentSession) -> bool:
    if not session.workspace_path:
        return False
    workspace = Path(session.workspace_path)
    processed = processed_workspace_inbox_filenames(session)
    for entry in list_inbox_entries(workspace):
        filename = str(entry.get("_filename") or "")
        if not filename or filename in processed:
            continue
        entry_kind = str(entry.get("kind") or "")
        entry_type = str(entry.get("type") or "")
        if entry_type in COMPLETED_PLAN_NON_ACTIONABLE_INBOX_TYPES:
            continue
        if entry_kind in {"request", "rejection", "observation", "user_instruction"}:
            return True
    return False


def main_session_should_pause_after_completed_plan(db: Session, *, project: Project, session: AgentSession) -> bool:
    if project.current_phase != "AUTONOMOUS_LOOP":
        return False
    revision = latest_research_plan_revision(db, project_id=project.id)
    if revision is None or not research_plan_revision_has_no_runnable_blocks(revision):
        return False
    if pending_main_session_user_instruction_exists(db, session=session):
        return False
    if unprocessed_actionable_workspace_inbox_exists(session):
        return False
    latest_state_change = latest_request_or_rejection_artifact_at(db, project_id=project.id)
    latest_chat = latest_codex_chat_update_at(db, project_id=project.id, session_id=session.id)
    if latest_state_change is not None and latest_chat is not None:
        state_change_at = latest_state_change.replace(tzinfo=timezone.utc) if latest_state_change.tzinfo is None else latest_state_change
        chat_at = latest_chat.replace(tzinfo=timezone.utc) if latest_chat.tzinfo is None else latest_chat
        if state_change_at > chat_at:
            return False
    return True


def pause_main_session_after_completed_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> None:
    revision = latest_research_plan_revision(db, project_id=project.id)
    session.status = "completed"
    session.pid = None
    session.ended_at = utc_now()
    session.updated_at = utc_now()
    project.current_phase = "IDLE"
    project.updated_at = utc_now()
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="session_completed_waiting_for_input",
        role="harness",
        title="Full Auto completed available work",
        content="Full Auto completed the available reversible work and is waiting for new data or user direction.",
        payload={
            "project_id": project.id,
            "research_plan_revision_id": revision.id if revision is not None else None,
            "research_plan_revision_index": revision.revision_index if revision is not None else None,
        },
        update_heartbeat=False,
    )
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=f"completed_waiting_for_input:{revision.id if revision is not None else session.id}",
        status="ready",
        message_kind="completed_waiting_for_input",
        details={
            "research_plan_revision_id": revision.id if revision is not None else None,
            "research_plan_revision_index": revision.revision_index if revision is not None else None,
        },
    )


def pause_main_session_after_completed_plan_safely(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
) -> bool:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return False
            if not main_session_should_pause_after_completed_plan(db, project=project, session=session):
                return False
            pause_main_session_after_completed_plan(db, store=store, project=project, session=session)
            db.commit()
            return True
    except Exception:
        return False


def maybe_request_research_plan_current_work_update(
    db: Session,
    *,
    session: AgentSession,
    locale: str | None,
    now: datetime | None = None,
    min_interval_seconds: int = RESEARCH_PLAN_CURRENT_WORK_NUDGE_MIN_INTERVAL_SECONDS,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES:
        return None
    revision, reason, current_node_id = research_plan_current_work_refresh_reason(db, session=session, now=now)
    if revision is None or reason is None:
        return None
    observed_at = now or utc_now()
    latest_nudge = latest_research_plan_current_work_nudge_at(db, session_id=session.id)
    if latest_nudge is not None:
        if latest_nudge.tzinfo is None:
            latest_nudge = latest_nudge.replace(tzinfo=timezone.utc)
        if (observed_at.astimezone(timezone.utc) - latest_nudge.astimezone(timezone.utc)).total_seconds() < min_interval_seconds:
            return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="research_plan_current_work_requested",
        role="harness",
        title="ResearchPlan current work requested",
        content="Tablex asked Codex to declare the current ResearchPlan node without interrupting the current work.",
        payload={
            "locale": locale,
            "research_plan_revision_id": revision.id,
            "research_plan_revision_index": revision.revision_index,
            "min_interval_seconds": min_interval_seconds,
            "reason": reason,
            "current_node_id": current_node_id,
        },
        update_heartbeat=False,
    )
    write_research_plan_current_work_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        revision=revision,
        reason=reason,
        current_node_id=current_node_id,
    )
    return event


def maybe_request_codex_progress_update(
    db: Session,
    *,
    session: AgentSession,
    locale: str | None,
    now: datetime | None = None,
    stale_after_seconds: int = PROGRESS_UPDATE_NUDGE_AFTER_SECONDS,
    min_interval_seconds: int = PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS,
    trigger: str = "stale_progress_update",
    user_message: str | None = None,
) -> AgentTranscriptEvent | None:
    if not session.workspace_path or session.status not in ACTIVE_SESSION_STATUSES:
        return None
    project = db.get(Project, session.project_id)
    if project is not None and main_session_should_pause_after_completed_plan(db, project=project, session=session):
        return None
    observed_at = now or utc_now()
    reference = latest_codex_chat_update_at(db, project_id=session.project_id, session_id=session.id)
    if reference is None:
        reference = session.started_at or session.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if (observed_at.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds() < stale_after_seconds:
        return None
    latest_output = latest_codex_transcript_output_at(db, session_id=session.id)
    if latest_output is not None and latest_output.tzinfo is None:
        latest_output = latest_output.replace(tzinfo=timezone.utc)
    if trigger != "user_chat_message":
        if latest_output is None:
            return None
        if latest_output.astimezone(timezone.utc) <= reference.astimezone(timezone.utc):
            return None
    latest_nudge = latest_progress_update_nudge_at(db, session_id=session.id)
    if latest_nudge is not None:
        if latest_nudge.tzinfo is None:
            latest_nudge = latest_nudge.replace(tzinfo=timezone.utc)
        if (observed_at.astimezone(timezone.utc) - latest_nudge.astimezone(timezone.utc)).total_seconds() < min_interval_seconds:
            return None
        if (
            trigger != "user_chat_message"
            and latest_output is not None
            and latest_output.astimezone(timezone.utc) <= latest_nudge.astimezone(timezone.utc)
        ):
            return None
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="progress_update_requested",
        role="harness",
        title="Progress update requested",
        content="Tablex asked Codex to refresh the progress update without interrupting the current work.",
        payload={
            "locale": locale,
            "trigger": trigger,
            "stale_after_seconds": stale_after_seconds,
            "min_interval_seconds": min_interval_seconds,
            "latest_chat_update_at": reference.isoformat(),
            "latest_codex_output_at": latest_output.isoformat() if latest_output is not None else None,
            "user_message_excerpt": user_message.strip()[:1200]
            if isinstance(user_message, str) and user_message.strip()
            else None,
        },
        update_heartbeat=False,
    )
    write_progress_request_to_workspace_inbox(
        session,
        event=event,
        locale=locale,
        trigger=trigger,
        user_message=user_message,
    )
    return event


def maybe_request_codex_progress_update_safely(
    session_factory: sessionmaker[Session],
    *,
    project_id: str,
    session_id: str,
    store: LocalArtifactStore | None = None,
) -> None:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
            locale = latest_project_response_locale(db, project)
            maybe_request_research_plan_current_work_update(
                db,
                session=session,
                locale=locale,
                min_interval_seconds=RESEARCH_PLAN_CURRENT_WORK_NUDGE_MIN_INTERVAL_SECONDS,
            )
            maybe_request_data_framing_update(
                db,
                project=project,
                session=session,
                locale=locale,
            )
            maybe_request_task_spec_update(
                db,
                project=project,
                session=session,
                locale=locale,
            )
            progress_event = maybe_request_codex_progress_update(
                db,
                session=session,
                locale=locale,
                stale_after_seconds=PROGRESS_UPDATE_NUDGE_AFTER_SECONDS,
                min_interval_seconds=PROGRESS_UPDATE_NUDGE_MIN_INTERVAL_SECONDS,
            )
            if progress_event is not None and store is not None:
                register_agent_session_attention_chat_turn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=f"progress_update_requested:{session.id}",
                    status="running",
                    message_kind="progress_update_requested",
                    details=loads_json(progress_event.payload_json, {}),
                )
            db.commit()
    except Exception:
        return


SupervisorRunner = Callable[..., None]


def start_main_agent_session_supervisor_thread(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    session_id: str,
    agent_model: str | None = None,
    lease_owner_id: str | None = None,
    supervisor_runner: SupervisorRunner | None = None,
    turn_timeout_seconds: int = MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    turn_start_silence_timeout_seconds: int = MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS,
) -> threading.Thread | None:
    if not acquire_supervisor_slot(session_id):
        return None
    runner = supervisor_runner or run_main_agent_session_supervisor
    if supervisor_runner is not None and supervisor_runner is not run_main_agent_session_supervisor:
        try:
            runner(
                session_factory,
                store,
                project_id=project_id,
                session_id=session_id,
                agent_model=agent_model,
                slot_acquired=True,
            )
        finally:
            release_supervisor_slot(session_id)
        return None

    def target() -> None:
        try:
            runner(
                session_factory,
                store,
                project_id=project_id,
                session_id=session_id,
                agent_model=agent_model,
                lease_owner_id=lease_owner_id,
                turn_timeout_seconds=turn_timeout_seconds,
                turn_start_silence_timeout_seconds=turn_start_silence_timeout_seconds,
                slot_acquired=True,
            )
        finally:
            release_supervisor_slot(session_id)

    thread = threading.Thread(
        target=target,
        name=f"tablex-agent-session-{session_id}",
        daemon=True,
    )
    thread.start()
    return thread


def start_active_main_session_supervisors(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    agent_model: str | None = None,
    lease_owner_id: str | None = None,
    supervisor_runner: SupervisorRunner | None = None,
    turn_timeout_seconds: int = MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    turn_start_silence_timeout_seconds: int = MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS,
) -> list[threading.Thread]:
    launch_specs: list[tuple[str, str]] = []
    with session_factory() as db:
        projects = list(
            db.scalars(
                select(Project).where(
                    Project.current_phase == "AUTONOMOUS_LOOP",
                    Project.autonomy_mode == "full_auto",
                )
            ).all()
        )
        for project in projects:
            session = active_main_session(db, project.id)
            if session is None:
                session = start_or_resume_main_session(
                    db,
                    store=store,
                    project=project,
                    goal_text=None,
                    autonomy_mode="full_auto",
                    runner_kind="codex_cli",
                    created_by="tablex-startup-supervisor",
                )
            elif session.pid is not None:
                previous_pid = session.pid
                if pid_is_alive(previous_pid):
                    if supervisor_slot_active(session.id) or supervisor_lease_active(db, session.id):
                        continue
                    session.status = "between_turns"
                    session.last_error = "Server restarted while Codex was active; Tablex will continue the work."
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="startup_stale_runner_detected",
                        role="harness",
                        title="Startup will recover Full Auto",
                        content="Tablex restarted and will recover the active autonomous session.",
                        payload={"previous_pid": previous_pid, "process_alive": True},
                    )
                else:
                    session.pid = None
                    session.status = "between_turns"
                    session.last_error = "Cleared a stale Codex PID from before startup; Tablex will continue the work."
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="startup_dead_runner_pid_cleared",
                        role="harness",
                        title="Startup cleared stale Codex PID",
                        content="Tablex found a stored Codex PID that is no longer alive and will continue the work.",
                        payload={"previous_pid": previous_pid, "process_alive": False},
                    )
            launch_specs.append((project.id, session.id))
        db.commit()
    threads: list[threading.Thread] = []
    for project_id, session_id in launch_specs:
        thread = start_main_agent_session_supervisor_thread(
            session_factory,
            store,
            project_id=project_id,
            session_id=session_id,
            agent_model=agent_model,
            lease_owner_id=lease_owner_id,
            supervisor_runner=supervisor_runner,
            turn_timeout_seconds=turn_timeout_seconds,
            turn_start_silence_timeout_seconds=turn_start_silence_timeout_seconds,
        )
        if thread is not None:
            threads.append(thread)
    return threads


def run_main_agent_session_supervisor(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    session_id: str,
    agent_model: str | None = None,
    lease_owner_id: str | None = None,
    max_turns: int = 100_000,
    turn_timeout_seconds: int = MAIN_AGENT_IDLE_TIMEOUT_SECONDS,
    turn_start_silence_timeout_seconds: int = MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS,
    slot_acquired: bool = False,
) -> None:
    if not slot_acquired and not acquire_supervisor_slot(session_id):
        return
    owner_id = lease_owner_id or default_supervisor_lease_owner_id(session_id)
    if not acquire_supervisor_lease(session_factory, session_id=session_id, owner_id=owner_id):
        release_supervisor_slot(session_id)
        return
    lease_stop_event, lease_lost_event, lease_thread = start_supervisor_lease_heartbeat(
        session_factory,
        session_id=session_id,
        owner_id=owner_id,
    )
    try:
        for _ in range(max_turns):
            if supervisor_lease_lost_event_is_set(session_factory, session_id=session_id, event=lease_lost_event):
                return
            with session_factory() as db:
                project = db.get(Project, project_id)
                session = db.get(AgentSession, session_id)
                if project is None or session is None:
                    return
                if lease_lost_event.is_set():
                    append_supervisor_lease_lost_event(db, session=session, owner_id=owner_id)
                    db.commit()
                    return
                if clear_stale_stored_runner_pid(db, session=session):
                    db.commit()
                    if lease_lost_event.wait(1):
                        continue
                    continue
                if session.status in TERMINAL_SESSION_STATUSES:
                    db.commit()
                    return
                if project.current_phase != "AUTONOMOUS_LOOP":
                    session.status = "stopped"
                    session.pid = None
                    session.ended_at = utc_now()
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="session_stopped",
                        role="harness",
                        title="Full Auto stopped",
                        content="Full Auto is off. The analysis will not continue until the project is started again.",
                        payload={"project_phase": project.current_phase if project else None},
                    )
                    db.commit()
                    return
                workspace = prepare_session_workspace(db, store=store, project=project, session=session)
                contract_request_event = maybe_request_research_plan_contract_revision(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    locale=latest_project_response_locale(db, project),
                )
                if contract_request_event is None and main_session_should_pause_after_completed_plan(
                    db,
                    project=project,
                    session=session,
                ):
                    pause_main_session_after_completed_plan(db, store=store, project=project, session=session)
                    db.commit()
                    return
                turn_prompt = build_turn_prompt(db, project=project, session=session)
                if lease_lost_event.is_set():
                    append_supervisor_lease_lost_event(db, session=session, owner_id=owner_id)
                    db.commit()
                    return
                session.status = "running"
                session.started_at = session.started_at or utc_now()
                session.updated_at = utc_now()
                session.last_heartbeat_at = utc_now()
                session.last_error = None
                db.commit()

            exit_code = run_codex_cli_turn_streaming(
                session_factory,
                store=store,
                project_id=project_id,
                session_id=session_id,
                workspace=workspace,
                prompt=turn_prompt.text,
                delivered_user_event_indexes=turn_prompt.delivered_user_event_indexes,
                agent_model=agent_model,
                timeout_seconds=turn_timeout_seconds,
                turn_start_silence_timeout_seconds=turn_start_silence_timeout_seconds,
                cancel_event=lease_lost_event,
            )
            if supervisor_lease_lost_event_is_set(session_factory, session_id=session_id, event=lease_lost_event):
                return
            with session_factory() as db:
                project = db.get(Project, project_id)
                session = db.get(AgentSession, session_id)
                if project is None or session is None:
                    return
                ingest_session_workspace_outputs(db, store=store, project=project, session=session, workspace=Path(session.workspace_path or workspace))
                if main_session_should_pause_after_completed_plan(db, project=project, session=session):
                    pause_main_session_after_completed_plan(db, store=store, project=project, session=session)
                    db.commit()
                    return
                if session.status in TERMINAL_SESSION_STATUSES:
                    db.commit()
                    return
                if project.current_phase != "AUTONOMOUS_LOOP":
                    session.status = "stopped"
                    session.pid = None
                    session.ended_at = utc_now()
                    db.commit()
                    return
                if exit_code is None:
                    session.status = "waiting_for_runner"
                    session.pid = None
                    session.last_error = "Codex CLI is not available."
                    retry_delay = retry_delay_seconds(consecutive_runner_failure_count(db, session.id))
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="runner_retry_scheduled",
                        role="harness",
                        title="Codex runner retry scheduled",
                        content="Codex CLI is unavailable. Tablex will preserve the work state and retry after a cooldown.",
                        payload={"retry_delay_seconds": retry_delay, "failure_kind": "runner_unavailable"},
                    )
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key="runner_unavailable",
                        status="waiting",
                        message_kind="runner_unavailable",
                        details={"retry_delay_seconds": retry_delay, "failure_kind": "runner_unavailable"},
                    )
                    db.commit()
                    if lease_lost_event.wait(retry_delay):
                        continue
                    continue
                if exit_code != 0:
                    session.status = "between_turns"
                    session.pid = None
                    retry_delay = retry_delay_seconds(consecutive_runner_failure_count(db, session.id))
                    session.last_error = (
                        f"Codex turn exited with code {exit_code}; supervisor will retry in {retry_delay}s."
                    )
                    append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="turn_recovery_scheduled",
                        role="harness",
                        title="Codex turn returned non-zero; continuing session",
                        content="Full Auto remains on. Tablex will continue the work after a cooldown instead of leaving the project stopped.",
                        payload={"exit_code": exit_code, "retry_delay_seconds": retry_delay},
                    )
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key=f"turn_recovery:{exit_code}",
                        status="waiting",
                        message_kind="turn_recovery",
                        details={"exit_code": exit_code, "retry_delay_seconds": retry_delay},
                    )
                    db.commit()
                    if lease_lost_event.wait(retry_delay):
                        continue
                    continue
                session.status = "between_turns"
                session.pid = None
                session.turn_index += 1
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="turn_completed_supervisor_continue",
                    role="harness",
                    title="Codex turn completed; supervisor will continue",
                    content="Full Auto is still on. Tablex keeps the work state active and asks Codex to continue from the transcript and project state.",
                    payload={"turn_index": session.turn_index},
                )
                db.commit()
            if lease_lost_event.wait(2):
                continue
    finally:
        lease_stop_event.set()
        lease_thread.join(timeout=2)
        release_supervisor_lease(session_factory, session_id=session_id, owner_id=owner_id)
        release_supervisor_slot(session_id)


def run_codex_cli_turn_streaming(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
    workspace: Path,
    prompt: str,
    delivered_user_event_indexes: tuple[int, ...],
    agent_model: str | None,
    timeout_seconds: int,
    turn_start_silence_timeout_seconds: int = MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> int | None:
    if shutil.which("codex") is None:
        with session_factory() as db:
            session = db.get(AgentSession, session_id)
            if session is not None:
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="runner_unavailable",
                    role="harness",
                    title="Codex CLI is not available",
                    content="Tablex cannot start Codex because the codex binary is not on PATH.",
                    payload={},
                )
                db.commit()
        return None

    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return 1
        turn_index = session.turn_index
        last_message_path = workspace / ".tablex" / f"codex_last_message_turn_{turn_index}.md"
        settings = get_settings()
        config_args = codex_harness_config_args(
            network_enabled=settings.agent_session_network_enabled,
            web_search_enabled=settings.agent_session_web_search_enabled,
        )
        if session.codex_thread_id:
            cmd = [
                "codex",
                "exec",
                *config_args,
                "--cd",
                str(workspace),
                "--sandbox",
                "workspace-write",
                "resume",
                session.codex_thread_id,
                "--json",
                "--output-last-message",
                str(last_message_path),
                "--skip-git-repo-check",
                "-",
            ]
        else:
            cmd = [
                "codex",
                "exec",
                *config_args,
                "--cd",
                str(workspace),
                "--sandbox",
                "workspace-write",
                "--json",
                "--output-last-message",
                str(last_message_path),
                "--skip-git-repo-check",
                "-",
        ]
        if agent_model and agent_model not in {"codex-default", "default"}:
            cmd[2:2] = ["--model", agent_model]
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="codex_command",
            role="harness",
            title="Starting Codex",
            content="Codex is starting from the current project workspace.",
            payload={"command": " ".join(cmd[:-1] + ["-"]), "workspace": str(workspace)},
        )
        db.commit()

    raw_stdout_path = raw_codex_transcript_path(workspace)
    raw_stderr_path = raw_codex_stderr_path(workspace)
    raw_stdout_path.parent.mkdir(parents=True, exist_ok=True)
    raw_stdout_path.touch(exist_ok=True)
    raw_stderr_path.touch(exist_ok=True)
    stdout_offset = raw_stdout_path.stat().st_size
    stderr_offset = raw_stderr_path.stat().st_size
    stdout_writer = raw_stdout_path.open("a", encoding="utf-8", buffering=1)
    stderr_writer = raw_stderr_path.open("a", encoding="utf-8", buffering=1)
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(workspace),
            stdin=subprocess.PIPE,
            stdout=stdout_writer,
            stderr=stderr_writer,
            text=True,
            bufsize=1,
            env=safe_env(workspace),
            start_new_session=True,
        )
        with session_factory() as db:
            session = db.get(AgentSession, session_id)
            if session is not None:
                session.pid = process.pid
                session.status = "running"
                session.last_heartbeat_at = utc_now()
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="process_started",
                    role="harness",
                    title="Codex started",
                    content=f"Codex process pid={process.pid} is running.",
                    payload={
                        "pid": process.pid,
                        "stdout_path": str(raw_stdout_path),
                        "stderr_path": str(raw_stderr_path),
                        "stdout_mode": "workspace_file_tail",
                    },
                )
                db.commit()
        if process.stdin is not None:
            process.stdin.write(prompt)
            process.stdin.close()
        maybe_request_codex_progress_update_safely(
            session_factory,
            project_id=project_id,
            session_id=session_id,
            store=store,
        )

        stream_tailers = {
            "stdout": StreamFileTailer(raw_stdout_path, offset=stdout_offset),
            "stderr": StreamFileTailer(raw_stderr_path, offset=stderr_offset),
        }
    except Exception:
        stdout_writer.close()
        stderr_writer.close()
        raise

    start = time.monotonic()
    last_output_at = start
    last_workspace_ingest = 0.0
    last_stream_event_flush = start
    pending_stream_events: list[tuple[str, str]] = []
    timeout_sent = False
    cancel_sent = False
    terminated_at: float | None = None
    timeout_kind: str | None = None
    thread_started_at: float | None = None
    item_seen_after_thread_start = False

    try:
        while True:
            now = time.monotonic()
            if now - last_workspace_ingest >= 10:
                ingest_session_workspace_outputs_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                    workspace=workspace,
                    allow_notebook_auto_registration=False,
                )
                if pause_main_session_after_completed_plan_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                ):
                    if process.poll() is None and not cancel_sent:
                        process.terminate()
                        append_process_cancelled_event(
                            session_factory,
                            session_id=session_id,
                            reason="completed_plan_waiting_for_input",
                        )
                        cancel_sent = True
                        terminated_at = time.monotonic()
                    last_workspace_ingest = now
                    continue
                maybe_request_codex_progress_update_safely(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                    store=store,
                )
                last_workspace_ingest = now
            new_lines: list[tuple[str, str]] = []
            for stream_name, tailer in stream_tailers.items():
                new_lines.extend((stream_name, line) for line in tailer.read_completed_lines())
            if new_lines:
                last_output_at = time.monotonic()
                pending_stream_events.extend(new_lines)
                for stream_name, line in new_lines:
                    if stream_name != "stdout":
                        continue
                    event_type = codex_jsonl_event_type(line)
                    if event_type == "thread.started":
                        thread_started_at = time.monotonic()
                        item_seen_after_thread_start = False
                    elif event_type.startswith("item."):
                        item_seen_after_thread_start = True
            now = time.monotonic()
            if cancel_event is not None and cancel_event.is_set() and process.poll() is None and not cancel_sent:
                process.terminate()
                append_process_cancelled_event(
                    session_factory,
                    session_id=session_id,
                    reason="supervisor_lease_lost",
                )
                cancel_sent = True
                terminated_at = now
            turn_start_silence = (
                thread_started_at is not None
                and not item_seen_after_thread_start
                and now - thread_started_at > turn_start_silence_timeout_seconds
            )
            idle_timeout = now - last_output_at > timeout_seconds
            if (turn_start_silence or idle_timeout) and process.poll() is None and not timeout_sent:
                timeout_kind = "turn_start_silence" if turn_start_silence else "idle"
                observed_timeout_seconds = (
                    turn_start_silence_timeout_seconds if turn_start_silence else timeout_seconds
                )
                process.terminate()
                append_process_timeout_event(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                    timeout_seconds=observed_timeout_seconds,
                    timeout_kind=timeout_kind,
                )
                timeout_sent = True
                terminated_at = now
            if terminated_at is not None and now - terminated_at > 15 and process.poll() is None:
                process.kill()
                append_process_killed_event(
                    session_factory,
                    session_id=session_id,
                    timeout_seconds=timeout_seconds,
                    timeout_kind=timeout_kind or "idle",
                )
                terminated_at = None
            now = time.monotonic()
            if pending_stream_events and (
                len(pending_stream_events) >= STREAM_EVENT_FLUSH_MAX_LINES
                or now - last_stream_event_flush >= STREAM_EVENT_FLUSH_INTERVAL_SECONDS
            ):
                append_codex_stream_lines(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                    lines=pending_stream_events,
                )
                pending_stream_events = []
                last_stream_event_flush = now
            if now - last_workspace_ingest >= 10:
                ingest_session_workspace_outputs_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                    workspace=workspace,
                    allow_notebook_auto_registration=False,
                )
                if pause_main_session_after_completed_plan_safely(
                    session_factory,
                    store=store,
                    project_id=project_id,
                    session_id=session_id,
                ):
                    if process.poll() is None and not cancel_sent:
                        process.terminate()
                        append_process_cancelled_event(
                            session_factory,
                            session_id=session_id,
                            reason="completed_plan_waiting_for_input",
                        )
                        cancel_sent = True
                        terminated_at = time.monotonic()
                    last_workspace_ingest = now
                    continue
                maybe_request_codex_progress_update_safely(
                    session_factory,
                    project_id=project_id,
                    session_id=session_id,
                    store=store,
                )
                last_workspace_ingest = now
            if process.poll() is not None:
                for stream_name, tailer in stream_tailers.items():
                    pending_stream_events.extend((stream_name, line) for line in tailer.drain_remaining_lines())
                break
            time.sleep(0.5)
    finally:
        stdout_writer.close()
        stderr_writer.close()
    if pending_stream_events:
        append_codex_stream_lines(
            session_factory,
            project_id=project_id,
            session_id=session_id,
            lines=pending_stream_events,
        )
    try:
        return_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        append_process_killed_event(
            session_factory,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            timeout_kind=timeout_kind or "idle",
        )
        return_code = process.wait(timeout=5)
    if return_code == 0:
        mark_user_instructions_delivered(
            session_factory,
            session_id=session_id,
            delivered_user_event_indexes=delivered_user_event_indexes,
        )
    publish_raw_codex_transcript_snapshot(workspace)
    ingest_session_workspace_outputs_safely(
        session_factory,
        store=store,
        project_id=project_id,
        session_id=session_id,
        workspace=workspace,
        allow_notebook_auto_registration=True,
    )
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            session.pid = None
            append_session_event(
                db,
                session,
                source="codex_cli",
                event_type="process_exited",
                role="runner",
                title="Codex process exited",
                content=f"Codex CLI exited with code {return_code}.",
                payload={"exit_code": return_code},
            )
            db.commit()
    maybe_request_codex_progress_update_safely(
        session_factory,
        project_id=project_id,
        session_id=session_id,
        store=store,
    )
    return return_code


def append_process_timeout_event(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
    timeout_seconds: int,
    timeout_kind: str = "idle",
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        project = db.get(Project, project_id)
        if session is None or project is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_timeout",
            role="harness",
            title="Codex turn timed out",
            content="The current Codex CLI process produced no output for the idle timeout. The supervisor will continue if Full Auto remains on.",
            payload={"idle_timeout_seconds": timeout_seconds, "timeout_kind": timeout_kind},
        )
        register_agent_session_attention_chat_turn(
            db,
            store=store,
            project=project,
            session=session,
            attention_key=f"process_timeout:{timeout_kind}:{timeout_seconds}",
            status="waiting",
            message_kind="turn_start_silence" if timeout_kind == "turn_start_silence" else "process_timeout",
            details={"idle_timeout_seconds": timeout_seconds, "timeout_kind": timeout_kind},
        )
        db.commit()


def append_process_cancelled_event(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    reason: str,
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_cancelled",
            role="harness",
            title="Codex process cancelled",
            content="The current Codex CLI process was cancelled because this supervisor should no longer drive the session.",
            payload={"reason": reason},
            update_heartbeat=False,
        )
        db.commit()


def append_process_killed_event(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    timeout_seconds: int,
    timeout_kind: str = "idle",
) -> None:
    with session_factory() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        append_session_event(
            db,
            session,
            source="tablex_sidecar",
            event_type="process_killed_after_timeout",
            role="harness",
            title="Codex process killed after idle timeout",
            content="The Codex process did not exit after the idle timeout termination request, so Tablex killed it and will continue the work if Full Auto remains on.",
            payload={"idle_timeout_seconds": timeout_seconds, "timeout_kind": timeout_kind},
        )
        db.commit()


def process_research_plan_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_research_plan_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        latest_artifact_for_workspace_path_fn=latest_session_artifact_for_workspace_path,
        write_rejection_fn=write_research_plan_request_rejection_to_workspace_inbox,
        append_session_event_fn=append_session_event,
        register_attention_fn=register_agent_session_attention_chat_turn,
    )


def process_research_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_research_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
        register_attention_fn=register_agent_session_attention_chat_turn,
        register_research_chat_fn=register_research_registration_chat_turn,
    )


def process_data_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_data_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
    )


def process_evaluation_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_evaluation_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
    )



def process_pipeline_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_pipeline_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
    )


def process_model_diagnostics_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_model_diagnostics_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
        register_attention_fn=register_agent_session_attention_chat_turn,
    )


def process_pilot_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_pilot_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
        register_attention_fn=register_agent_session_attention_chat_turn,
    )


def process_deliverable_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    del store
    process_deliverable_tool_requests_impl(
        db,
        project=project,
        session=session,
        workspace=workspace,
        append_session_event_fn=append_session_event,
    )


def process_notebook_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
) -> None:
    process_notebook_tool_requests_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        execute_registration_fn=execute_notebook_registration_request,
        write_rejection_fn=write_notebook_request_rejection_to_workspace_inbox,
        append_session_event_fn=append_session_event,
        register_attention_fn=register_agent_session_attention_chat_turn,
    )


def execute_notebook_registration_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    notebook_artifact = notebook_artifact_from_request(
        db,
        project=project,
        workspace=workspace,
        payload=payload,
        resolve_workspace_artifact_fn=latest_session_artifact_for_workspace_path,
    )
    context_links = apply_notebook_request_metadata(
        db,
        project=project,
        notebook_artifact=notebook_artifact,
        payload=payload,
    )
    if context_links.get("notebook_kind") == "model_diagnostics":
        run_ids = []
        run_id = context_links.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            run_ids.append(run_id)
        related_run_ids = context_links.get("related_run_ids")
        if isinstance(related_run_ids, list):
            run_ids.extend(item for item in related_run_ids if isinstance(item, str))
        fulfill_run_model_diagnostics_notebook_expectations(
            db,
            project=project,
            run_ids=run_ids,
            notebook_artifact_id=notebook_artifact.id,
        )
    node_id = str(payload.get("research_plan_node_id") or "").strip() or None
    revision_id = str(payload.get("revision_id") or "").strip() or None
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=notebook_artifact,
        node_id=node_id,
        revision_id=revision_id,
        strict=bool(node_id),
    )
    chat_artifact = register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=notebook_artifact,
        status=notebook_registration_chat_status(notebook_artifact),
        linked_plan_node_id=linked_plan_node_id,
    )
    visible_surfaces = notebook_registration_visible_surfaces(
        notebook_artifact=notebook_artifact,
        chat_artifact_id=chat_artifact.id if chat_artifact is not None else None,
        linked_plan_node_id=linked_plan_node_id,
        dataset_snapshot_id=context_links.get("dataset_snapshot_id"),
        run_id=context_links.get("run_id"),
        model_version_id=context_links.get("model_version_id"),
        related_run_ids=context_links.get("related_run_ids") if isinstance(context_links.get("related_run_ids"), list) else None,
    )
    return {
        "notebook_artifact_id": notebook_artifact.id,
        "research_plan_node_id": linked_plan_node_id,
        "chat_artifact_id": chat_artifact.id if chat_artifact is not None else None,
        "visible_surfaces": visible_surfaces,
        "notebook_quality": notebook_quality_feedback_from_metadata(notebook_artifact),
        **context_links,
    }


def ingest_session_workspace_outputs(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    allow_notebook_auto_registration: bool = True,
) -> None:
    ingest_session_workspace_outputs_impl(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        allow_notebook_auto_registration=allow_notebook_auto_registration,
        project_session_still_registered_fn=project_session_still_registered,
        process_data_tool_requests_fn=process_data_tool_requests,
        process_evaluation_tool_requests_fn=process_evaluation_tool_requests,
        process_research_plan_tool_requests_fn=process_research_plan_tool_requests,
        process_research_tool_requests_fn=process_research_tool_requests,
        maybe_request_research_plan_contract_revision_fn=maybe_request_research_plan_contract_revision,
        process_notebook_tool_requests_fn=process_notebook_tool_requests,
        process_experiment_result_requests_fn=process_experiment_result_requests,
        process_model_diagnostics_tool_requests_fn=process_model_diagnostics_tool_requests,
        process_pipeline_tool_requests_fn=process_pipeline_tool_requests,
        process_pilot_tool_requests_fn=process_pilot_tool_requests,
        process_deliverable_tool_requests_fn=process_deliverable_tool_requests,
        maybe_write_open_deliverable_expectation_observation_fn=maybe_write_open_deliverable_expectation_observation,
        ingest_registered_session_experiment_artifacts_fn=ingest_registered_session_experiment_artifacts,
    )


def ingest_session_workspace_outputs_safely(
    session_factory: sessionmaker[Session],
    *,
    store: LocalArtifactStore,
    project_id: str,
    session_id: str,
    workspace: Path,
    allow_notebook_auto_registration: bool = True,
) -> None:
    try:
        with session_factory() as db:
            project = db.get(Project, project_id)
            session = db.get(AgentSession, session_id)
            if project is None or session is None:
                return
            ingest_session_workspace_outputs(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                allow_notebook_auto_registration=allow_notebook_auto_registration,
            )
            db.commit()
    except Exception as exc:
        try:
            with session_factory() as db:
                session = db.get(AgentSession, session_id)
                if session is None:
                    return
                append_session_event(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="workspace_ingest_failed",
                    role="harness",
                    title="Workspace output ingest failed",
                    content=str(exc)[:1200],
                    payload={"error_type": type(exc).__name__},
                    update_heartbeat=False,
                )
                db.commit()
        except Exception:
            return
