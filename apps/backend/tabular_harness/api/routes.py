from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import signal
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import websockets
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
)
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask

from tabular_harness.api.deps import get_artifact_store, get_session
from tabular_harness.core.config import get_settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    AgentSupervisorLease,
    AgentTranscriptEvent,
    Answer,
    Artifact,
    Asset,
    AssetReference,
    AssetVersion,
    Assumption,
    AssumptionEvidenceLink,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Idea,
    Insight,
    Job,
    LineageEdge,
    ModelVersion,
    PilotDeployment,
    PilotOutcomeBatch,
    PilotPredictionBatch,
    Project,
    Question,
    Report,
    ResearchBrief,
    ResearchPlan,
    ResearchPlanCurrentWork,
    ResearchPlanRevision,
    SemanticCatalog,
    SplitManifest,
    User,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.schemas import (
    AdaptiveStrategyBriefRead,
    AgentActivityRead,
    AgentChatCreate,
    AgentChatHistoryTurnRead,
    AgentChatRead,
    AgentConsoleMessageCreate,
    AgentConsoleMessageRead,
    AgentRawTranscriptRead,
    AgentSessionRead,
    AgentTaskPlanCreate,
    AgentTranscriptEventRead,
    AnswerRead,
    ArtifactPreviewRead,
    ArtifactRead,
    AssetCreate,
    AssetRead,
    AssetReferenceCreate,
    AssetReferenceRead,
    AssetVersionRead,
    AssumptionRead,
    AssumptionReviewQueueRead,
    AuthLoginCreate,
    AuthRegisterCreate,
    AuthStatusRead,
    AutonomyStartCreate,
    AutonomyStopCreate,
    AvatarCandidateCreate,
    BenchmarkDatasetRead,
    BenchmarkFixtureRequest,
    BenchmarkFixtureResponse,
    BenchmarkImportReadinessRead,
    BenchmarkImportRequest,
    BenchmarkLocalStatusRead,
    BenchmarkPublicDownloadRequest,
    BenchmarkSourceCardRead,
    DatasetSnapshotRead,
    DatasetUploadResponse,
    DataUnderstandingNotebookCreate,
    DecisionReportCurrentRead,
    EvaluationCandidateRead,
    EvaluationSpecRead,
    EvidenceCreate,
    IdeaRead,
    InsightRead,
    JobCreate,
    JobRead,
    KaggleSelectiveDownloadRequest,
    LeaderboardMetricPreferenceCreate,
    ModelCandidatesRunCreate,
    ModelValidationRead,
    ModelVersionRead,
    PortalIdeaCreate,
    PortalIdeaRead,
    PortalOverviewRead,
    ProjectCreate,
    ProjectGuidanceRead,
    ProjectOverview,
    ProjectPrimaryDatasetUpdate,
    ProjectRead,
    ProjectUpdate,
    QuestionAnswerCreate,
    QuestionRead,
    ReportCreate,
    ReportRead,
    ResearchBriefCreate,
    ResearchBriefRead,
    ResearchPlanArtifactAttachCreate,
    ResearchPlanCurrentWorkCreate,
    ResearchPlanHumanAttentionCreate,
    ResearchPlanRevisionCommitCreate,
    ResultReadoutRead,
    SemanticCatalogRead,
    SplitManifestRead,
    TranslationCreate,
    UserRead,
    UserSettingsUpdate,
    VisualizationSpecRead,
)
from tabular_harness.services.adaptive_strategy import (
    build_adaptive_strategy_brief,
)
from tabular_harness.services.agent_chat_status import agent_chat_wait_state
from tabular_harness.services.agent_requests.data import (
    record_user_confirmed_task_spec_for_project_edit,
)
from tabular_harness.services.agent_session_results import (
    experiment_model_id_from_params,
    experiment_result_signature,
)
from tabular_harness.services.agent_sessions import (
    active_main_session,
    append_session_event,
    append_user_instruction_to_workspace_inbox,
    attention_chat_message,
    chat_update_actions_from_research_plan_evidence,
    chat_update_message_from_text,
    latest_codex_chat_update_at,
    latest_codex_transcript_output_at,
    latest_main_session,
    latest_project_response_locale,
    maybe_request_codex_progress_update,
    notebook_artifact_has_declared_context,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    run_main_agent_session_supervisor,
    session_to_dict,
    start_main_agent_session_supervisor_thread,
    start_or_resume_main_session,
    stop_main_session,
    supervisor_slot_active,
    transcript_event_to_dict,
    write_notebook_runtime_failure_to_workspace_inbox,
)
from tabular_harness.services.agent_task_results import list_agent_task_result_summaries
from tabular_harness.services.analysis_notebooks import (
    build_project_analysis_story,
    build_project_notebook_index,
    marimo_notebook_source_hash_for_artifact,
)
from tabular_harness.services.approach import (
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
from tabular_harness.services.asset_library import (
    asset_reference_to_dict,
    asset_to_dict,
    asset_version_to_dict,
    create_asset_reference,
    create_library_asset,
    equip_default_project_skills,
    seed_default_assets,
)
from tabular_harness.services.assumption_review import build_assumption_review_queue
from tabular_harness.services.auth import (
    authenticate_password,
    create_auth_session,
    create_user,
    revoke_session_token,
    update_user_settings,
    user_for_session_token,
    user_to_dict,
)
from tabular_harness.services.autonomy import (
    queue_autonomous_session_continuation,
    run_autonomous_loop_tick,
)
from tabular_harness.services.baseline import (
    normalize_model_candidate_name,
)
from tabular_harness.services.benchmarks import (
    benchmark_source_card,
    benchmark_to_dict,
    generate_benchmark_fixture,
    get_benchmark_dataset,
    infer_relationships,
    inspect_benchmark_local_files,
    list_benchmark_datasets,
    profile_table_file,
    raw_benchmark_dataset,
    resolve_benchmark_root,
    table_name_from_path,
)
from tabular_harness.services.dataset_profile import profile_dataset_artifact
from tabular_harness.services.decision_reporting import current_decision_report_payload
from tabular_harness.services.deliverable_expectations import deliverable_expectations_for_run_ids
from tabular_harness.services.evaluation import (
    approve_spec,
    candidate_to_dict,
    create_evaluation_approval_review,
    promote_candidate_to_spec,
    spec_to_dict,
    write_spec_artifact,
)
from tabular_harness.services.jobs import (
    TERMINAL_STATUSES,
    approve_job,
    create_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    reap_stale_running_jobs,
    retry_job,
)
from tabular_harness.services.jobs import (
    cancel_job as cancel_job_service,
)
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.marimo_sessions import (
    NATIVE_MARIMO_OPEN_READY_TIMEOUT_SECONDS,
    native_marimo_session,
    native_marimo_target_url,
    start_or_get_native_marimo_session,
    stop_native_marimo_session,
    stop_native_marimo_session_for_artifact,
    stop_native_marimo_sessions_for_project,
    wait_for_native_marimo_session_ready,
)
from tabular_harness.services.metric_preferences import (
    BUILTIN_METRIC_OPTIONS,
    latest_metric_preference,
    leaderboard_sort_key_for_metric,
    normalize_metric_name,
    record_metric_preference,
)
from tabular_harness.services.metric_preferences import (
    metric_name as preferred_metric_name,
)
from tabular_harness.services.metric_preferences import (
    metric_value as preferred_metric_value,
)
from tabular_harness.services.model_diagnostics_artifacts import (
    artifact_ref as model_diagnostics_artifact_ref,
)
from tabular_harness.services.model_diagnostics_artifacts import (
    latest_run_artifact,
    load_json_artifact,
)
from tabular_harness.services.notebook_authoring import create_notebook_authoring_brief
from tabular_harness.services.portal import (
    active_job_ids_for_activity,
    build_portal_overview,
    build_project_turn_state,
    create_portal_idea,
    heartbeat_waiting_child_ids,
    is_agentish_job,
    list_portal_ideas,
    running_codex_processes_for_project,
    worker_events_from_job,
)
from tabular_harness.services.project_guidance import (
    build_project_guidance,
)
from tabular_harness.services.relational_evidence import (
    MAX_SCHEMA_HINT_BYTES,
    create_relational_schema_hint,
)
from tabular_harness.services.research_plan_timeline import build_research_plan_timeline_response
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    attach_research_plan_artifact,
    commit_research_plan_revision,
    latest_research_plan_current_work,
    record_harness_dataset_upload_in_research_plan,
    record_harness_objective_in_research_plan,
    request_research_plan_human_attention,
    research_plan_artifact_is_native_marimo_source,
    research_plan_current_work_payload,
    set_research_plan_current_work,
)
from tabular_harness.services.result_readout import build_result_readout
from tabular_harness.services.storage_management import artifact_gc_plan, storage_usage_report
from tabular_harness.worker.jobs import create_default_worker

router = APIRouter()
LOGGER = logging.getLogger(__name__)
INTERACTIVE_WORKER_JOB_TYPES = {"agent_chat_turn"}
NOTEBOOK_NATIVE_MARIMO_ANCHOR = "notebook-native-marimo-top"
LEGACY_NOTEBOOK_ANCHORS = {"notebook-preview-top"}
NOTEBOOK_NAVIGATION_ANCHORS = {*LEGACY_NOTEBOOK_ANCHORS, NOTEBOOK_NATIVE_MARIMO_ANCHOR}
STATIC_NOTEBOOK_HTML_ASSET_TYPES = {"notebook_html", "notebook_execution_html", "notebook_evidence_html"}
MAIN_SESSION_CHAT_WAITING_STATUS = "waiting_for_agent"
POWER_STOP_PRESERVED_JOB_TYPES = {"upload_data_bundle", "select_primary_table"}
AUTONOMY_STOP_PROCESS_TERM_GRACE_SECONDS = 2.0


def pid_alive_for_autonomy_stop(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_codex_process_for_autonomy_stop(pid: int) -> dict[str, Any]:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"pid": pid, "status": "not_found", "terminated": False, "kill_escalated": False}
    except PermissionError:
        return {"pid": pid, "status": "permission_denied", "terminated": False, "kill_escalated": False}
    except OSError as exc:
        return {
            "pid": pid,
            "status": "terminate_failed",
            "terminated": False,
            "kill_escalated": False,
            "error_type": type(exc).__name__,
        }

    deadline = time.monotonic() + AUTONOMY_STOP_PROCESS_TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not pid_alive_for_autonomy_stop(pid):
            return {"pid": pid, "status": "terminated", "terminated": True, "kill_escalated": False}
        time.sleep(0.05)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return {"pid": pid, "status": "terminated", "terminated": True, "kill_escalated": False}
    except PermissionError:
        return {"pid": pid, "status": "kill_permission_denied", "terminated": False, "kill_escalated": True}
    except OSError as exc:
        return {
            "pid": pid,
            "status": "kill_failed",
            "terminated": False,
            "kill_escalated": True,
            "error_type": type(exc).__name__,
        }

    if pid_alive_for_autonomy_stop(pid):
        return {"pid": pid, "status": "still_running", "terminated": False, "kill_escalated": True}
    return {"pid": pid, "status": "killed", "terminated": True, "kill_escalated": True}


def cleanup_project_codex_processes_for_autonomy_stop(project_id: str) -> dict[str, Any]:
    observed = running_codex_processes_for_project(project_id)
    results: list[dict[str, Any]] = []
    seen_pids: set[int] = set()
    for process in observed:
        raw_pid = process.get("pid")
        if not isinstance(raw_pid, int) or raw_pid in seen_pids:
            continue
        seen_pids.add(raw_pid)
        result = terminate_codex_process_for_autonomy_stop(raw_pid)
        command = process.get("command")
        if isinstance(command, str) and command:
            result["command"] = command
        results.append(result)
    return {
        "schema_version": "project_codex_process_cleanup.v1",
        "project_id": project_id,
        "observed_count": len(seen_pids),
        "terminated_count": sum(1 for result in results if result.get("terminated") is True),
        "remaining_count": sum(1 for result in results if result.get("terminated") is not True),
        "processes": results,
    }


def set_data_understanding_phase_without_turning_agent_off(project: Project) -> None:
    if project.current_phase == "AUTONOMOUS_LOOP":
        return
    project.current_phase = "UNDERSTANDING_REVIEW"


def sqlite_database_is_locked(exc: OperationalError) -> bool:
    return "database is locked" in str(getattr(exc, "orig", exc)).lower()


def raise_metadata_db_busy(exc: OperationalError) -> None:
    if sqlite_database_is_locked(exc):
        raise HTTPException(
            status_code=503,
            detail=(
                "Metadata database is busy. Tablex is finishing another local write; "
                "retry in a moment or restart the local backend if this persists."
            ),
        ) from exc
    raise exc


def auth_status_payload(request: Request, db: Session, user: User | None) -> dict[str, Any]:
    settings = request.app.state.settings
    user_count = int(db.scalar(select(func.count()).select_from(User)) or 0)
    return {
        "auth_enabled": bool(settings.auth_enabled),
        "authenticated": bool(user) if settings.auth_enabled else True,
        "password_auth_enabled": True,
        "google_auth_enabled": bool(settings.google_auth_enabled),
        "bootstrap_required": bool(settings.auth_enabled and user_count == 0),
        "user": user_to_dict(user) if user else None,
    }


def require_auth_user(request: Request, db: Session) -> User:
    settings = request.app.state.settings
    user = user_for_session_token(db, request.cookies.get(settings.auth_cookie_name))
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def request_actor_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    return str(user_id) if user_id else "local-user"


def set_auth_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        secure=bool(settings.auth_cookie_secure),
        samesite="lax",
        max_age=max(1, int(settings.auth_session_days)) * 24 * 60 * 60,
        path="/",
    )


@router.get("/health")
@router.get("/healthz")
@router.get("/api/health")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/config")
def app_config(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "app_display_name": str(settings.app_display_name),
        "architecture_name": "Tabular-first Prediction Meta-Harness",
        "auth_enabled": bool(settings.auth_enabled),
        "password_auth_enabled": True,
        "google_auth_enabled": bool(settings.google_auth_enabled),
        "api_agent_session_supervisor_enabled": bool(settings.api_agent_session_supervisor_enabled),
        "local_worker_enabled": bool(settings.local_worker_enabled),
    }


@router.get("/api/admin/storage/usage")
def admin_storage_usage(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return storage_usage_report(request.app.state.settings, db)


@router.post("/api/admin/storage/gc")
def admin_storage_gc(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    dry_run: bool = Query(default=True),
    retention: int | None = Query(default=None, ge=1, le=100),
) -> dict[str, Any]:
    plan = artifact_gc_plan(db, settings=request.app.state.settings, dry_run=dry_run, retention=retention)
    report_artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type="storage_gc_report",
        name="storage_gc_report",
        filename="storage_gc_report.json",
        payload=plan,
        metadata={
            "source": "admin_storage_gc",
            "dry_run": dry_run,
            "retention": plan["retention"],
        },
        created_by="tablex",
    )
    db.commit()
    return {**plan, "report_artifact_id": report_artifact.id}


@router.get("/api/auth/status", response_model=AuthStatusRead)
def auth_status(request: Request, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    settings = request.app.state.settings
    user = user_for_session_token(db, request.cookies.get(settings.auth_cookie_name))
    return auth_status_payload(request, db, user)


@router.post("/api/auth/bootstrap", response_model=AuthStatusRead)
def bootstrap_auth_user(
    payload: AuthRegisterCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Authentication is disabled.")
    existing_count = int(db.scalar(select(func.count()).select_from(User)) or 0)
    if existing_count > 0:
        raise HTTPException(status_code=409, detail="Bootstrap user already exists.")
    try:
        user = create_user(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            is_admin=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = create_auth_session(
        db,
        user=user,
        session_days=settings.auth_session_days,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    set_auth_cookie(response, request, token.token)
    return auth_status_payload(request, db, user)


@router.post("/api/auth/login", response_model=AuthStatusRead)
def login(
    payload: AuthLoginCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(status_code=400, detail="Authentication is disabled.")
    user = authenticate_password(db, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_auth_session(
        db,
        user=user,
        session_days=settings.auth_session_days,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    set_auth_cookie(response, request, token.token)
    return auth_status_payload(request, db, user)


@router.post("/api/auth/logout", response_model=AuthStatusRead)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    settings = request.app.state.settings
    revoke_session_token(db, request.cookies.get(settings.auth_cookie_name))
    response.delete_cookie(settings.auth_cookie_name, path="/")
    return auth_status_payload(request, db, None)


@router.get("/api/auth/me", response_model=UserRead)
def current_user(request: Request, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    return user_to_dict(require_auth_user(request, db))


@router.patch("/api/auth/me/settings", response_model=UserRead)
def update_current_user_settings(
    payload: UserSettingsUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    user = require_auth_user(request, db)
    update_user_settings(user, payload.settings)
    return user_to_dict(user)


@router.post("/api/user/avatar-candidates", response_model=JobRead)
def generate_avatar_candidates(
    payload: AvatarCandidateCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    job = create_job(
        db,
        job_type="generate_user_avatar_candidates",
        project_id=None,
        input_payload={"prompt": payload.prompt, "count": payload.count},
        context={"source": "user_settings_avatar"},
        policy={
            "execution": "queued_worker",
            "runner": "CodexCliRunner",
            "network": "disabled_until_runner_policy_allows",
            "secret_access": "forbidden",
            "artifact_contract": "avatar_candidates.v1",
        },
        priority=80,
        created_by=request_actor_id(request),
    )
    return job_to_dict(job)


@router.get("/api/benchmarks", response_model=list[BenchmarkDatasetRead])
def list_benchmarks(request: Request) -> list[dict[str, Any]]:
    return list_benchmark_datasets(request.app.state.settings)


@router.get("/api/benchmarks/{benchmark_id}", response_model=BenchmarkDatasetRead)
def get_benchmark(benchmark_id: str, request: Request) -> dict[str, Any]:
    try:
        return get_benchmark_dataset(benchmark_id, request.app.state.settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc


@router.get("/api/benchmarks/{benchmark_id}/source-card", response_model=BenchmarkSourceCardRead)
def get_benchmark_source_card(
    benchmark_id: str,
    request: Request,
    local_path: str | None = None,
) -> dict[str, Any]:
    try:
        benchmark = raw_benchmark_dataset(benchmark_id)
        return benchmark_source_card(benchmark, settings=request.app.state.settings, local_path=local_path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/benchmarks/{benchmark_id}/import-readiness", response_model=BenchmarkImportReadinessRead)
def get_benchmark_import_readiness(
    benchmark_id: str,
    request: Request,
    local_path: str | None = None,
) -> dict[str, Any]:
    try:
        benchmark = raw_benchmark_dataset(benchmark_id)
        card = benchmark_source_card(benchmark, settings=request.app.state.settings, local_path=local_path)
        return cast(dict[str, Any], card["import_readiness"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/benchmarks/{benchmark_id}/local-status", response_model=BenchmarkLocalStatusRead)
def benchmark_local_status(
    benchmark_id: str,
    request: Request,
    local_path: str | None = None,
) -> dict[str, Any]:
    try:
        benchmark = raw_benchmark_dataset(benchmark_id)
        root = resolve_benchmark_root(request.app.state.settings, benchmark_id, local_path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return inspect_benchmark_local_files(benchmark, root)


@router.post("/api/benchmarks/{benchmark_id}/fixtures/generate", response_model=BenchmarkFixtureResponse)
def generate_benchmark_fixture_endpoint(
    benchmark_id: str,
    payload: BenchmarkFixtureRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return generate_benchmark_fixture(
            request.app.state.settings,
            benchmark_id,
            overwrite=payload.overwrite,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/benchmarks/{benchmark_id}/public-download", response_model=JobRead)
def download_public_benchmark_endpoint(
    benchmark_id: str,
    payload: BenchmarkPublicDownloadRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="download_public_benchmark_archive",
        project_id=None,
        input_payload={
            "benchmark_id": benchmark_id,
            "overwrite": payload.overwrite,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "network": "enabled_for_catalog_public_archive_only",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/benchmarks/{benchmark_id}/kaggle/probe", response_model=JobRead)
def probe_kaggle_benchmark_endpoint(
    benchmark_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="probe_kaggle_benchmark_access",
        project_id=None,
        input_payload={"benchmark_id": benchmark_id},
        policy={
            "network": "enabled_for_kaggle_credential_probe_only",
            "secret_access": "harness_process_only",
            "connector_credentials": "not_materialized",
            "agent_runner_access": False,
            "agent_task_contract_access": False,
            "artifact_contains_secret_values": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/benchmarks/{benchmark_id}/kaggle/inventory", response_model=JobRead)
def fetch_kaggle_inventory_endpoint(
    benchmark_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="fetch_kaggle_competition_inventory",
        project_id=None,
        input_payload={"benchmark_id": benchmark_id},
        policy={
            "network": "enabled_for_kaggle_inventory_only",
            "secret_access": "harness_process_only",
            "connector_credentials": "not_materialized",
            "agent_runner_access": False,
            "agent_task_contract_access": False,
            "artifact_contains_secret_values": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.get("/api/benchmarks/{benchmark_id}/kaggle/inventory/latest", response_model=ArtifactRead)
def get_latest_kaggle_inventory_artifact(
    benchmark_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    artifact = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id.is_(None),
            Artifact.asset_type == "kaggle_file_inventory",
            Artifact.name == f"kaggle_file_inventory_{benchmark_id}",
        )
        .order_by(Artifact.created_at.desc())
        .limit(1)
    ).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Kaggle inventory artifact not found")
    return artifact_to_dict(artifact)


@router.post("/api/benchmarks/{benchmark_id}/kaggle/download", response_model=JobRead)
def download_kaggle_selected_files_endpoint(
    benchmark_id: str,
    payload: KaggleSelectiveDownloadRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="download_kaggle_selected_files",
        project_id=None,
        input_payload={
            "benchmark_id": benchmark_id,
            "selected_files": payload.selected_files,
            "include_required": payload.include_required,
            "include_recommended": payload.include_recommended,
            "include_holdout": payload.include_holdout,
            "overwrite": payload.overwrite,
            "max_total_bytes": payload.max_total_bytes,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "network": "enabled_for_kaggle_selected_download_only",
            "secret_access": "harness_process_only",
            "connector_credentials": "not_materialized",
            "agent_runner_access": False,
            "agent_task_contract_access": False,
            "artifact_contains_secret_values": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.get("/api/portal/overview", response_model=PortalOverviewRead)
def portal_overview(db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    return build_portal_overview(db)


@router.get("/api/portal/ideas", response_model=list[PortalIdeaRead])
def portal_ideas(db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    return list_portal_ideas(db)


@router.post("/api/portal/ideas", response_model=PortalIdeaRead)
def create_portal_idea_endpoint(
    payload: PortalIdeaCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    return create_portal_idea(db, store=store, text=payload.text)


@router.get("/api/projects", response_model=list[ProjectRead])
def list_projects(db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [project_to_dict(project) for project in projects]


@router.post("/api/projects", response_model=ProjectRead)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = Project(
        id=new_id("p"),
        name=payload.name,
        description=payload.description,
        task_type=payload.task_type,
        target_column=payload.target_column,
        autonomy_mode=payload.autonomy_mode or "approval_based",
        current_phase="DRAFT",
        created_by=request_actor_id(request),
    )
    db.add(project)
    db.flush()
    equip_default_project_skills(db, store, project_id=project.id)
    return project_to_dict(project)


@router.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return project_to_dict(project)


@router.patch("/api/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    data = payload.model_dump(exclude_unset=True)
    previous_autonomy_mode = project.autonomy_mode
    previous_phase = project.current_phase
    locale = data.pop("locale", None)
    for key, value in data.items():
        if key == "autonomy_mode" and value is None:
            continue
        setattr(project, key, value)
    if "target_column" in data:
        record_user_confirmed_task_spec_for_project_edit(
            db,
            store=store,
            project=project,
            target_column=project.target_column,
            table_ref=project.primary_dataset_snapshot_id,
        )
        record_harness_objective_in_research_plan(
            db,
            project_id=project.id,
            objective_label=project.target_column,
        )
    stopped_session = None
    if (
        previous_autonomy_mode == "full_auto"
        and project.autonomy_mode == "approval_based"
        and previous_phase == "AUTONOMOUS_LOOP"
    ):
        stopped_session = stop_main_session(db, project)
    project.updated_at = utc_now()
    session = None
    should_touch_main_agent_session = project.current_phase == "AUTONOMOUS_LOOP" or previous_phase == "AUTONOMOUS_LOOP"
    if should_touch_main_agent_session:
        session = ensure_project_full_auto_agent_session(
            db,
            store=store,
            project=project,
            created_by=request_actor_id(request),
        )
        if session is not None and request.app.state.settings.api_agent_session_supervisor_enabled:
            start_main_agent_session_supervisor_thread(
                request.app.state.session_factory,
                store,
                project_id=project_id,
                session_id=session.id,
                supervisor_runner=run_main_agent_session_supervisor,
                turn_timeout_seconds=request.app.state.settings.agent_idle_timeout_seconds,
                turn_start_silence_timeout_seconds=request.app.state.settings.agent_turn_start_silence_timeout_seconds,
            )
    if (
        "autonomy_mode" in data
        and project.autonomy_mode in {"approval_based", "full_auto"}
        and project.autonomy_mode != previous_autonomy_mode
    ):
        record_autonomy_mode_change_chat_turn(
            db,
            store,
            project=project,
            previous_mode=previous_autonomy_mode,
            next_mode=project.autonomy_mode,
            locale=locale if isinstance(locale, str) else None,
            stopped_session_id=stopped_session.id if stopped_session is not None else None,
        )
    db.flush()
    return project_to_dict(project)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    org_id = project.org_id
    stop_main_session(db, project, record_event=False)
    stopped_marimo_sessions = stop_native_marimo_sessions_for_project(project_id)
    for job in db.scalars(select(Job).where(Job.project_id == project_id)).all():
        cancel_job_service(job, cancelled_by=request_actor_id(request))
    delete_project_rows(db, project_id)
    db.delete(project)
    db.flush()
    db.commit()
    cleanup = schedule_project_artifact_cleanup(request.app.state.settings, org_id=org_id, project_id=project_id)
    return {
        "schema_version": "project_delete.v1",
        "project_id": project_id,
        "deleted": True,
        "stopped_marimo_sessions": stopped_marimo_sessions,
        "artifact_cleanup": cleanup,
    }


def record_autonomy_control_chat_turn(
    db: Session,
    store: LocalArtifactStore,
    *,
    project: Project,
    job: Job,
    user_message: str,
    assistant_message: str,
    output: dict[str, Any],
    locale: str | None,
) -> Artifact:
    worker_events = output.get("worker_events") if isinstance(output.get("worker_events"), list) else []
    token_usage_value = output.get("token_usage")
    token_usage = token_usage_value if isinstance(token_usage_value, dict) else {}
    created_job_ids = output.get("created_job_ids") if isinstance(output.get("created_job_ids"), list) else []
    response_locale = locale or "en-US"
    payload = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "intent": {
            "type": "agent_loop_control",
            "source": "autonomy_power_button",
            "routing_policy": "explicit_ui_control_not_natural_language_routing",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "source": "autonomy_control",
            "response_locale": response_locale,
            "created_job_ids": created_job_ids,
            "status": output.get("status"),
        },
        "response_composer": {
            "mode": "autonomy_control_event",
            "status": "persisted",
        },
        "worker_events": worker_events,
        "token_usage": token_usage,
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent Activity"},
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_loop_control_{job.id}",
        filename="agent_chat_turn.json",
        payload=payload,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "intent_type": "agent_loop_control",
            "action_count": 0,
            "token_usage_source": token_usage.get("source") if isinstance(token_usage.get("source"), str) else None,
            "response_locale": response_locale,
            "response_composer_mode": "autonomy_control_event",
        },
    )


def record_autonomy_mode_change_chat_turn(
    db: Session,
    store: LocalArtifactStore,
    *,
    project: Project,
    previous_mode: str,
    next_mode: str,
    locale: str | None,
    stopped_session_id: str | None,
) -> Artifact:
    japanese = locale_is_japanese(locale)
    if japanese:
        user_message = "フルオート" if next_mode == "full_auto" else "承認ベース"
        assistant_message = (
            "フルオートに切り替えました。電源がONのときは、現在のProject状態を読み直して自律実行を続けます。"
            if next_mode == "full_auto"
            else (
                "承認ベースに切り替えました。以降は判断が必要な場面で人間の確認を待ちます。"
                + (" 実行中のフルオートセッションは停止しました。" if stopped_session_id else "")
            )
        )
    else:
        user_message = "Full Auto" if next_mode == "full_auto" else "Approval Based"
        assistant_message = (
            "Switched to Full Auto. When power is on, the agent will reread the current project state and continue autonomously."
            if next_mode == "full_auto"
            else (
                "Switched to Approval Based. I will wait for human confirmation at decision points that need review."
                + (" The running Full Auto session was stopped." if stopped_session_id else "")
            )
        )
    payload = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "intent": {
            "type": "autonomy_mode_change",
            "source": "autonomy_mode_toggle",
            "routing_policy": "explicit_ui_control_not_natural_language_routing",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "source": "autonomy_mode_change",
            "response_locale": locale or "en-US",
            "previous_mode": previous_mode,
            "next_mode": next_mode,
            "stopped_agent_session_id": stopped_session_id,
        },
        "response_composer": {
            "mode": "explicit_ui_control",
            "status": "persisted",
        },
        "worker_events": [],
        "token_usage": {"source": "explicit_ui_control", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"},
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"autonomy_mode_change_{new_id('mode')}",
        filename="agent_chat_turn.json",
        payload=payload,
        metadata={
            "project_id": project.id,
            "intent_type": "autonomy_mode_change",
            "previous_mode": previous_mode,
            "next_mode": next_mode,
            "response_locale": locale or "en-US",
            "stopped_agent_session_id": stopped_session_id,
            "response_composer_mode": "explicit_ui_control",
        },
    )


def queued_autonomy_start_output(project: Project, job: Job, *, locale: str | None) -> dict[str, Any]:
    japanese = locale_is_japanese(locale)
    assistant_message = (
        "Full Autoを起動しました。データ理解、評価設計、実験準備をバックグラウンドで進めます。"
        "進行はAgent ActivityとこのWorkspaceに表示します。"
        if japanese
        else "Full Auto is starting. Data understanding, evaluation design, and experiment preparation will continue in the background. Progress will appear in Agent Activity and this workspace."
    )
    return {
        "schema_version": "autonomous_loop_start_queued.v1",
        "project_id": project.id,
        "status": "queued",
        "assistant_message": assistant_message,
        "created_job_ids": [job.id],
        "worker_events": [
            {
                "worker_id": "full-auto-loop",
                "display_name": "Full Auto Agent",
                "status": "queued",
                "headline": "Full Auto is starting",
                "detail": "The local backend accepted the Agent loop and will run it outside the Start request.",
                "job_id": job.id,
                "project_id": project.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": True,
                "token_usage": {
                    "source": "autonomous_start_event",
                    "is_estimate": True,
                    "series": [
                        {"step": "accepted", "tokens": 24},
                        {"step": "queued", "tokens": 32},
                    ],
                },
            }
        ],
        "token_usage": {
            "source": "autonomous_start_event",
            "is_estimate": True,
            "series": [
                {"step": "accepted", "tokens": 24},
                {"step": "queued", "tokens": 32},
            ],
        },
    }


def queued_agent_session_start_output(
    project: Project,
    session: AgentSession,
    job: Job,
    *,
    locale: str | None,
) -> dict[str, Any]:
    japanese = locale_is_japanese(locale)
    is_resume = bool(session.started_at or session.turn_index > 0 or session.codex_thread_id)
    if is_resume:
        assistant_message = (
            "フルオートを再開しました。これまでの作業と最新のProject状態を読み直して、続きから進めます。"
            "進行中の内容はこのチャットとアクティビティに表示します。"
            if japanese
            else "Full Auto resumed. I will reread the previous work and current project state, then continue from there. Progress will appear in this chat and Activity."
        )
    else:
        assistant_message = (
            "フルオートを開始しました。データの確認、目的の整理、評価設計、分析ノートブック作成へ順に進めます。"
            "進行中の内容はこのチャットとアクティビティに表示します。"
            if japanese
            else "Full Auto started. I will work through data review, objective framing, evaluation design, and analysis notebooks. Progress will appear in this chat and Activity."
        )
    return {
        "schema_version": "agent_session_start.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "status": "resumed" if is_resume else "started",
        "assistant_message": assistant_message,
        "created_job_ids": [],
        "worker_events": [
            {
                "worker_id": "main-agent-session",
                "display_name": "自律分析" if japanese else "Autonomous Analyst",
                "status": session.status,
                "headline": (
                    "Analysis is resuming"
                    if is_resume and not japanese
                    else "Analysis is starting"
                    if not japanese
                    else "分析を再開しています"
                    if is_resume
                    else "分析を開始しています"
                ),
                "detail": (
                    "Rereading the current project state and continuing from the previous work."
                    if is_resume and not japanese
                    else "Preparing the project context and beginning the next analysis step."
                    if not japanese
                    else "プロジェクトの状況とこれまでの作業を確認し、続きから進めています。"
                    if is_resume
                    else "プロジェクトの状況を確認し、次の分析ステップを開始しています。"
                ),
                "job_id": job.id,
                "job_type": job.job_type,
                "project_id": project.id,
                "agent_session_id": session.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": utc_now().isoformat(),
                "active": True,
                "token_usage": {
                    "source": "agent_session_transcript_pending",
                    "is_estimate": True,
                    "series": [
                        {"step": "session_created", "tokens": 32},
                        {"step": "codex_starting", "tokens": 48},
                    ],
                },
            }
        ],
        "token_usage": {
            "source": "agent_session_transcript_pending",
            "is_estimate": True,
            "series": [
                {"step": "session_created", "tokens": 32},
                {"step": "codex_starting", "tokens": 48},
            ],
        },
    }


def mark_autonomy_start_output_running(job: Job, project: Project, *, locale: str | None) -> None:
    output = loads_json(job.output_json, {})
    now = utc_now().isoformat()
    japanese = locale_is_japanese(locale)
    title = "Full Autoが動いています" if japanese else "Full Auto is running"
    summary = (
        "現在のプロジェクト状態を読み込み、データ理解、評価設計、実験準備を進めています。"
        if japanese
        else "Reading the current project state and advancing data understanding, evaluation design, and experiment preparation."
    )
    output["status"] = "running"
    output["human_description"] = {"title": title, "summary": summary, "source": "autonomy_start_runtime"}
    token_usage = {
        "source": "autonomous_start_event",
        "is_estimate": True,
        "series": [
            {"step": "accepted", "tokens": 24},
            {"step": "queued", "tokens": 32},
            {"step": "running", "tokens": 48},
        ],
    }
    output["token_usage"] = token_usage
    events = output.get("worker_events") if isinstance(output.get("worker_events"), list) else []
    if not events:
        events = [{"worker_id": "full-auto-loop", "display_name": "Full Auto Agent"}]
    event = events[0] if isinstance(events[0], dict) else {}
    event.update(
        {
            "worker_id": str(event.get("worker_id") or "full-auto-loop"),
            "display_name": str(event.get("display_name") or "Full Auto Agent"),
            "status": "running",
            "headline": title,
            "detail": summary,
            "job_id": job.id,
            "project_id": project.id,
            "target_tab": "Home",
            "target_anchor": "agent-workspace",
            "created_at": str(event.get("created_at") or job.created_at.isoformat()),
            "updated_at": now,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "active": True,
            "human_description": {"title": title, "summary": summary, "source": "autonomy_start_runtime"},
            "token_usage": token_usage,
        }
    )
    output["worker_events"] = [event, *[item for item in events[1:] if isinstance(item, dict)]]
    job.output_json = dumps_json(output)
    job.updated_at = utc_now()


def run_autonomy_start_job_background(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    with session_factory() as db:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
        if job is None or project is None:
            return
        try:
            mark_job_running(job)
            mark_autonomy_start_output_running(job, project, locale=payload.get("locale") if isinstance(payload.get("locale"), str) else None)
            db.commit()
            runner_mode = str(payload.get("runner_mode") or "harness_only")
            autonomy_mode = str(payload.get("autonomy_mode") or project.autonomy_mode or "full_auto")
            locale = payload.get("locale") if isinstance(payload.get("locale"), str) else None
            agent_model = payload.get("agent_model") if isinstance(payload.get("agent_model"), str) else None
            utility_model = payload.get("utility_model") if isinstance(payload.get("utility_model"), str) else None
            output = run_autonomous_loop_tick(
                db,
                store=store,
                project=project,
                job=job,
                runner_mode=runner_mode,
                autonomy_mode=autonomy_mode,
                locale=locale,
                agent_model=agent_model,
                utility_model=utility_model,
            )
            continuation_job = queue_autonomous_session_continuation(
                db,
                project=project,
                reason="start_tick_completed",
                parent_job_id=job.id,
                runner_mode=runner_mode,
                locale=locale,
                run_after_seconds=10,
            )
            if continuation_job is not None:
                output["session_continuation_job_id"] = continuation_job.id
            assistant_message = str(output.get("assistant_message") or "Agent loop started.")
            created_job_ids = output.get("created_job_ids") if isinstance(output.get("created_job_ids"), list) else []
            if created_job_ids:
                if locale_is_japanese(locale):
                    assistant_message = (
                        f"{assistant_message}\n\n"
                        "右側の Agent Activity に、次に進むための待機中ジョブを表示します。"
                        "Waiting のカードはまだ実行中ではなく、実行が始まった時点で Running に変わります。"
                    )
                else:
                    assistant_message = (
                        f"{assistant_message}\n\n"
                        "Agent Activity now shows the queued follow-up work. Cards marked Waiting are not running yet; "
                        "they switch to Running when execution starts."
                )
                output["assistant_message"] = assistant_message
            db.refresh(job)
            if job.status == "cancelled":
                db.commit()
                return
            artifact = record_autonomy_control_chat_turn(
                db,
                store,
                project=project,
                job=job,
                user_message="Agent loopを開始" if locale_is_japanese(locale) else "Start agent loop",
                assistant_message=assistant_message,
                output=output,
                locale=locale,
            )
            output["agent_chat_turn_artifact_id"] = artifact.id
            db.refresh(job)
            if job.status == "cancelled":
                db.commit()
                return
            mark_job_succeeded(job, output)
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                mark_job_failed(job, str(exc))
                db.commit()
    run_project_autonomy_worker_pump_background(session_factory, store, project_id=project_id, max_jobs=6)


def start_autonomy_start_job_thread(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    job_id: str,
    payload: dict[str, Any],
) -> threading.Thread:
    thread = threading.Thread(
        target=run_autonomy_start_job_background,
        kwargs={
            "session_factory": session_factory,
            "store": store,
            "project_id": project_id,
            "job_id": job_id,
            "payload": payload,
        },
        name=f"tablex-autonomy-start-{job_id}",
        daemon=True,
    )
    thread.start()
    return thread


def run_project_autonomy_worker_pump_background(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    project_id: str,
    max_jobs: int = 6,
) -> None:
    worker = create_default_worker(worker_id="local-autonomy-pump", store=store, include_stub_handlers=False)
    for _ in range(max_jobs):
        with session_factory() as db:
            project = db.get(Project, project_id)
            if project is None or project.current_phase != "AUTONOMOUS_LOOP" or project.autonomy_mode != "full_auto":
                return
            job = worker.run_next_job(db, project_id=project_id)
            if job is None:
                return


def ensure_project_full_auto_agent_session(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    created_by: str | None = None,
) -> AgentSession | None:
    if project.current_phase != "AUTONOMOUS_LOOP" or project.autonomy_mode != "full_auto":
        return None
    record_harness_objective_in_research_plan(
        db,
        project_id=project.id,
        objective_label=project.target_column,
    )
    existing = active_main_session(db, project.id)
    if existing is not None:
        if supervisor_slot_active(existing.id):
            return None
        observed_processes = running_codex_processes_for_project(project.id)
        if observed_processes and not supervisor_slot_active(existing.id):
            already_recorded = existing.last_error == (
                "A Codex process is visible but no supervisor is attached; Tablex will recover the session."
            )
            existing.status = "between_turns"
            existing.last_error = "A Codex process is visible but no supervisor is attached; Tablex will recover the session."
            existing.updated_at = utc_now()
            if not already_recorded:
                append_session_event(
                    db,
                    existing,
                    source="tablex_sidecar",
                    event_type="unattached_runner_process_detected",
                    role="harness",
                    title="Unattached Codex process detected",
                    content="Tablex observed a Codex process without active supervision and will recover the work state.",
                    payload={"project_id": project.id, "process_count": len(observed_processes)},
                )
            return existing
        if existing.pid is not None or existing.status == "running":
            already_recorded = existing.last_error == (
                "No live Codex process was observed; the supervisor will continue the work."
            )
            existing.pid = None
            existing.status = "between_turns"
            existing.last_error = "No live Codex process was observed; the supervisor will continue the work."
            existing.updated_at = utc_now()
            if not already_recorded:
                append_session_event(
                    db,
                    existing,
                    source="tablex_sidecar",
                    event_type="stale_runner_pid_cleared",
                    role="harness",
                    title="Stale Codex process reference cleared",
                    content="Tablex observed Full Auto without a live Codex process and will continue the work.",
                    payload={"project_id": project.id},
                )
        return existing
    return start_or_resume_main_session(
        db,
        store=store,
        project=project,
        goal_text=None,
        autonomy_mode="full_auto",
        runner_kind="codex_cli",
        created_by=created_by or "tablex-session-watchdog",
    )


@router.post("/api/projects/{project_id}/autonomy/start", response_model=JobRead)
def start_project_autonomy(
    project_id: str,
    payload: AutonomyStartCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    job: Job | None = None
    try:
        project = require_project(db, project_id)
        if payload.autonomy_mode == "full_auto":
            project.autonomy_mode = "full_auto"
            project.current_phase = "AUTONOMOUS_LOOP"
            project.updated_at = utc_now()
            session = start_or_resume_main_session(
                db,
                store=store,
                project=project,
                goal_text=None,
                autonomy_mode="full_auto",
                runner_kind="codex_cli",
                created_by=request_actor_id(request),
            )
            job = create_job(
                db,
                job_type="start_autonomous_loop",
                project_id=project_id,
                input_payload={
                    "runner_mode": "codex_cli_if_available"
                    if payload.runner_mode == "harness_only"
                    else payload.runner_mode,
                    "requested_runner_mode": payload.runner_mode,
                    "autonomy_mode": payload.autonomy_mode,
                    "locale": payload.locale,
                    "agent_model": payload.agent_model,
                    "utility_model": payload.utility_model,
                    "agent_session_id": session.id,
                },
                policy={
                    "secret_access": "forbidden",
                    "connector_credentials": "not_materialized",
                    "production_write": "forbidden",
                    "runner_mode": "codex_cli_if_available"
                    if payload.runner_mode == "harness_only"
                    else payload.runner_mode,
                    "requested_runner_mode": payload.runner_mode,
                    "autonomy_mode": payload.autonomy_mode,
                    "control_record_only": True,
                    "main_execution_state": "agent_session",
                },
            )
            output = queued_agent_session_start_output(project, session, job, locale=payload.locale)
            assistant_message = str(output["assistant_message"])
            job.output_json = dumps_json(output)
            mark_job_succeeded(job, output)
            artifact = record_autonomy_control_chat_turn(
                db,
                store,
                project=project,
                job=job,
                user_message="Agent loopを開始" if locale_is_japanese(payload.locale) else "Start agent loop",
                assistant_message=assistant_message,
                output=output,
                locale=payload.locale,
            )
            output["agent_chat_turn_artifact_id"] = artifact.id
            job.output_json = dumps_json(output)
            db.commit()
            if request.app.state.settings.api_agent_session_supervisor_enabled:
                start_main_agent_session_supervisor_thread(
                    request.app.state.session_factory,
                    store,
                    project_id=project_id,
                    session_id=session.id,
                    agent_model=payload.agent_model,
                    supervisor_runner=run_main_agent_session_supervisor,
                    turn_timeout_seconds=request.app.state.settings.agent_idle_timeout_seconds,
                    turn_start_silence_timeout_seconds=request.app.state.settings.agent_turn_start_silence_timeout_seconds,
                )
            return job_to_dict(job)
        job = create_job(
            db,
            job_type="start_autonomous_loop",
            project_id=project_id,
            input_payload={
                "runner_mode": payload.runner_mode,
                "autonomy_mode": payload.autonomy_mode,
                "locale": payload.locale,
                "agent_model": payload.agent_model,
                "utility_model": payload.utility_model,
            },
            policy={
                "secret_access": "forbidden",
                "connector_credentials": "not_materialized",
                "production_write": "forbidden",
                "evaluation_spec_mutation": "non_destructive_initial_adoption_only",
                "runner_mode": payload.runner_mode,
                "autonomy_mode": payload.autonomy_mode,
                "response_locale": payload.locale,
                "agent_model": payload.agent_model,
                "utility_model": payload.utility_model,
            },
        )
        project.autonomy_mode = payload.autonomy_mode
        project.current_phase = "AUTONOMOUS_LOOP"
        project.updated_at = utc_now()
        output = queued_autonomy_start_output(project, job, locale=payload.locale)
        assistant_message = str(output["assistant_message"])
        job.output_json = dumps_json(output)
        job.updated_at = utc_now()
        artifact = record_autonomy_control_chat_turn(
            db,
            store,
            project=project,
            job=job,
            user_message="Agent loopを開始" if locale_is_japanese(payload.locale) else "Start agent loop",
            assistant_message=assistant_message,
            output=output,
            locale=payload.locale,
        )
        output["agent_chat_turn_artifact_id"] = artifact.id
        job.output_json = dumps_json(output)
        db.commit()
        start_autonomy_start_job_thread(
            request.app.state.session_factory,
            store,
            project_id=project_id,
            job_id=job.id,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        if job is not None:
            mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OperationalError as exc:
        db.rollback()
        raise_metadata_db_busy(exc)
    assert job is not None
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/autonomy/stop", response_model=JobRead)
def stop_project_autonomy(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    payload: AutonomyStopCreate | None = None,
) -> dict[str, Any]:
    job: Job | None = None
    try:
        project = require_project(db, project_id)
        locale = payload.locale if payload is not None else None
        japanese = locale_is_japanese(locale)
        job = create_job(
            db,
            job_type="stop_autonomous_loop",
            project_id=project_id,
            input_payload={"requested_state": "off"},
            policy={
                "secret_access": "forbidden",
                "connector_credentials": "not_materialized",
                "production_write": "forbidden",
                "action": "stop_autonomous_activity",
            },
        )
        mark_job_running(job)
        active_jobs = db.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.id != job.id,
                ~Job.status.in_(TERMINAL_STATUSES),
                ~Job.job_type.in_(POWER_STOP_PRESERVED_JOB_TYPES),
            )
        ).all()
        cancelled_ids: list[str] = []
        for active_job in active_jobs:
            cancel_job_service(active_job, cancelled_by="tablex-autonomy-power")
            cancelled_ids.append(active_job.id)
        stopped_session = stop_main_session(db, project)
        codex_process_cleanup = cleanup_project_codex_processes_for_autonomy_stop(project_id)
        project.current_phase = "IDLE"
        project.updated_at = utc_now()
        assistant_message = (
            "Agent loopを停止しました。実行中または待機中の作業は可能な範囲でキャンセルしました。再開すると、最新のProject状態を読み直して続きから動きます。"
            if japanese
            else "Autonomous activity is stopped. Active or queued work was cancelled where possible. When restarted, the loop will reread the latest project state before continuing."
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": "autonomous_loop_stop.v1",
                "project_id": project_id,
                "response_locale": locale or "en-US",
                "assistant_message": assistant_message,
                "cancelled_job_ids": cancelled_ids,
                "stopped_agent_session_id": stopped_session.id if stopped_session is not None else None,
                "codex_process_cleanup": codex_process_cleanup,
                "worker_events": [
                    {
                        "worker_id": "full-auto-loop",
                        "display_name": "Full Auto Agent",
                        "status": "cancelled",
                        "headline": "Autonomous activity stopped.",
                        "detail": (
                            f"{len(cancelled_ids)}件の実行中または待機中の作業を停止しました。"
                            if japanese
                            else f"Stopped {len(cancelled_ids)} active or queued work item(s)."
                        ),
                        "job_id": job.id,
                        "project_id": project_id,
                        "target_tab": "Home",
                        "target_anchor": "agent-workspace",
                        "created_at": job.created_at.isoformat(),
                        "updated_at": utc_now().isoformat(),
                        "active": False,
                        "token_usage": {
                            "source": "autonomous_stop_event",
                            "is_estimate": True,
                            "series": [
                                {"step": "stop", "tokens": 24},
                                {"step": "cancel", "tokens": 24 + len(cancelled_ids) * 8},
                            ],
                        },
                    }
                ],
            },
        )
        artifact = record_autonomy_control_chat_turn(
            db,
            store,
            project=project,
            job=job,
            user_message="Agent loopを停止" if japanese else "Stop agent loop",
            assistant_message=assistant_message,
            output=loads_json(job.output_json, {}),
            locale=locale,
        )
        output = loads_json(job.output_json, {})
        output["agent_chat_turn_artifact_id"] = artifact.id
        job.output_json = dumps_json(output)
    except OperationalError as exc:
        db.rollback()
        raise_metadata_db_busy(exc)
    assert job is not None
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    project.status = "archived"
    project.updated_at = utc_now()
    return project_to_dict(project)


@router.get("/api/projects/{project_id}/overview", response_model=ProjectOverview)
def project_overview(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    latest_dataset = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )
    recent_artifacts = latest_artifact_rows(db, project_id, limit=8)
    recent_jobs = db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(8)
    ).all()
    high_risk = db.scalars(
        select(Assumption)
        .where(Assumption.project_id == project_id, Assumption.risk_level.in_(["high", "blocking", "deployment_blocking"]))
        .order_by(Assumption.updated_at.desc())
        .limit(8)
    ).all()
    counts = {
        "datasets": count_rows(db, DatasetSnapshot, project_id),
        "artifacts": count_latest_artifacts(db, project_id),
        "artifact_versions": count_rows(db, Artifact, project_id),
        "questions": count_rows(db, Question, project_id),
        "assumptions": count_rows(db, Assumption, project_id),
        "evaluation_candidates": count_rows(db, EvaluationCandidate, project_id),
        "evaluation_specs": count_rows(db, EvaluationSpec, project_id),
        "experiment_runs": count_rows(db, ExperimentRun, project_id),
        "model_versions": count_rows(db, ModelVersion, project_id),
        "jobs": count_rows(db, Job, project_id),
        "research_briefs": count_rows(db, ResearchBrief, project_id),
        "ideas": count_rows(db, Idea, project_id),
        "reports": count_rows(db, Report, project_id),
        "visualizations": count_rows(db, VisualizationSpec, project_id),
        "insights": count_rows(db, Insight, project_id),
    }
    return {
        "project": project_to_dict(project),
        "counts": counts,
        "next_actions": next_actions(project, counts),
        "latest_dataset_snapshot_id": latest_dataset.id if latest_dataset else None,
        "high_risk_assumptions": [assumption_to_dict(db, item) for item in high_risk],
        "recent_artifacts": [artifact_to_dict(item) for item in recent_artifacts],
        "recent_jobs": [job_to_dict(item) for item in recent_jobs],
    }


@router.get("/api/projects/{project_id}/guidance", response_model=ProjectGuidanceRead)
def project_guidance(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_project_guidance(db, project)


@router.post("/api/projects/{project_id}/guidance/snapshot", response_model=JobRead)
def save_project_guided_journey_snapshot(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="save_guided_journey_snapshot",
        project_id=project_id,
        input_payload={},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/guidance/decision-brief", response_model=JobRead)
def save_project_autonomous_decision_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="save_autonomous_decision_brief",
        project_id=project_id,
        input_payload={},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/guidance/snapshots/compare", response_model=JobRead)
def compare_project_guided_journey_snapshots(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="compare_guided_journey_snapshots",
        project_id=project_id,
        input_payload={},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/datasets/upload", response_model=DatasetUploadResponse)
def upload_dataset(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    file: Annotated[UploadFile, File()],
    target_column: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".parquet"}:
        raise HTTPException(status_code=400, detail="Only CSV and Parquet uploads are supported")

    effective_target = target_column or project.target_column
    if target_column and target_column != project.target_column:
        project.target_column = target_column
    version = next_artifact_version(db, project_id, "dataset_snapshot", "uploaded_dataset")
    artifact_dir, stored, content_hash = store.store_stream(
        org_id="local-org",
        project_id=project_id,
        asset_type="dataset_snapshot",
        name="uploaded_dataset",
        version=version,
        filename=file.filename or f"dataset{suffix}",
        stream=file.file,
        metadata={"project_id": project_id, "source_filename": file.filename},
    )
    dataset_artifact = register_artifact(
        db,
        project_id=project_id,
        asset_type="dataset_snapshot",
        name="uploaded_dataset",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "primary_path": str(stored.path),
            "source_filename": file.filename,
            "project_id": project_id,
        },
        version=version,
    )
    job = create_job(
        db,
        job_type="profile_dataset",
        project_id=project_id,
        input_payload={"artifact_id": dataset_artifact.id, "target_column": effective_target},
    )
    try:
        mark_job_running(job)
        dataset = profile_dataset_artifact(db, store, project, dataset_artifact, effective_target)
        project.primary_dataset_snapshot_id = dataset.id
        set_data_understanding_phase_without_turning_agent_off(project)
        project.updated_at = utc_now()
        record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project_id,
            artifact_ids=[dataset_artifact.id],
            dataset_snapshot_id=dataset.id,
            primary_artifact_id=dataset_artifact.id,
        )
        record_harness_objective_in_research_plan(
            db,
            project_id=project_id,
            objective_label=project.target_column,
        )
        mark_job_succeeded(job, {"dataset_snapshot_id": dataset.id})
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return {
        "dataset_snapshot": dataset_to_dict(dataset, primary_dataset_snapshot_id=project.primary_dataset_snapshot_id),
        "artifact": artifact_to_dict(dataset_artifact),
        "profile_job_id": job.id,
    }


TABLE_UPLOAD_SUFFIXES = {".csv", ".parquet"}
RELATIONAL_HINT_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".json"}
MAX_COLUMN_HINT_BYTES = 128 * 1024


@router.post("/api/projects/{project_id}/datasets/upload-bundle", response_model=JobRead)
def upload_dataset_bundle(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    files: Annotated[list[UploadFile], File()],
    target_column: Annotated[str | None, Form()] = None,
    primary_filename: Annotated[str | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    locale: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one CSV, Parquet, ER image, PDF, SVG, or JSON file")

    table_uploads = [file for file in files if Path(file.filename or "").suffix.lower() in TABLE_UPLOAD_SUFFIXES]
    hint_uploads = [file for file in files if Path(file.filename or "").suffix.lower() in RELATIONAL_HINT_UPLOAD_SUFFIXES]
    unsupported = [
        file.filename or "unnamed"
        for file in files
        if Path(file.filename or "").suffix.lower()
        not in (TABLE_UPLOAD_SUFFIXES | RELATIONAL_HINT_UPLOAD_SUFFIXES)
    ]
    if unsupported:
        raise HTTPException(status_code=400, detail=f"Unsupported upload file(s): {', '.join(unsupported[:8])}")
    if not table_uploads and not hint_uploads:
        raise HTTPException(status_code=400, detail="No supported files were uploaded")

    requested_primary = primary_filename.strip() if primary_filename else None
    if requested_primary and requested_primary not in {file.filename for file in table_uploads}:
        raise HTTPException(status_code=400, detail="primary_filename must match one uploaded CSV or Parquet file")

    job = create_job(
        db,
        job_type="upload_data_bundle",
        project_id=project_id,
        input_payload={
            "file_count": len(files),
            "table_file_count": len(table_uploads),
            "relational_hint_file_count": len(hint_uploads),
            "primary_filename": requested_primary,
            "target_column": target_column,
            "note_present": bool(note and note.strip()),
            "response_locale": locale,
        },
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "purpose": "store_user_supplied_table_bundle_and_relational_evidence",
        },
    )
    try:
        staged_table_artifacts = stage_upload_bundle_files(
            db,
            store=store,
            project=project,
            job=job,
            uploads=table_uploads,
            stage_kind="table",
        )
        staged_hint_artifacts = stage_upload_bundle_files(
            db,
            store=store,
            project=project,
            job=job,
            uploads=hint_uploads,
            stage_kind="relational_hint",
        )
        job.input_json = dumps_json(
            {
                "file_count": len(files),
                "table_file_count": len(table_uploads),
                "relational_hint_file_count": len(hint_uploads),
                "primary_filename": requested_primary,
                "target_column": target_column,
                "note": note,
                "note_present": bool(note and note.strip()),
                "response_locale": locale,
                "staged_table_artifact_ids": [artifact.id for artifact in staged_table_artifacts],
                "staged_relational_hint_artifact_ids": [artifact.id for artifact in staged_hint_artifacts],
            }
        )
        job.output_json = dumps_json(
            {
                "schema_version": "upload_data_bundle_staging.v1",
                "status": "queued_for_ingest",
                "progress_stage": "queued_for_ingest",
                "progress_percent": 5,
                "staged_table_artifact_ids": [artifact.id for artifact in staged_table_artifacts],
                "staged_relational_hint_artifact_ids": [artifact.id for artifact in staged_hint_artifacts],
                "assistant_message": (
                    "ファイルを受け取りました。Tablexがデータbundleの取り込みとprofileを続けています。"
                    if locale_is_japanese(locale)
                    else "Files were received. Tablex is importing and profiling the data bundle."
                ),
            }
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return job_to_dict(job)


def quick_table_column_names(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open("rb") as handle:
                sample = handle.read(MAX_COLUMN_HINT_BYTES)
            if not sample:
                return []
            text = sample.decode("utf-8-sig", errors="replace")
            first_line = text.splitlines()[0] if text.splitlines() else ""
            return [item.strip() for item in next(csv.reader([first_line]), []) if item.strip()]
        if suffix == ".parquet":
            try:
                import pyarrow.parquet as pq  # type: ignore[import-not-found]
            except Exception:
                return []
            return [str(name).strip() for name in pq.read_schema(path).names if str(name).strip()]
    except Exception:
        return []
    return []


def artifact_metadata_column_names(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("column_names")
    if not isinstance(raw, list):
        raw = metadata.get("columns")
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))


def generated_csv_column_names(columns: list[str]) -> bool:
    if not columns:
        return False
    return all(column == f"column{index}" for index, column in enumerate(columns))


def generated_csv_column_placeholder(column: str) -> bool:
    return column.startswith("column") and column.removeprefix("column").isdigit()


def metadata_columns_should_override_profile(profile_columns: list[str], metadata_columns: list[str]) -> bool:
    if not profile_columns or not metadata_columns:
        return False
    if generated_csv_column_names(profile_columns):
        return True
    non_generated = [column for column in profile_columns if not generated_csv_column_placeholder(column)]
    return len(non_generated) < len(profile_columns) and non_generated == metadata_columns


def stage_upload_bundle_files(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    uploads: list[UploadFile],
    stage_kind: str,
) -> list[Artifact]:
    staged: list[Artifact] = []
    used_names: set[str] = set()
    for index, upload in enumerate(uploads):
        suffix = Path(upload.filename or "").suffix.lower()
        base_name = uploaded_table_name(upload.filename or f"{stage_kind}_{index + 1}{suffix}", used_names)
        artifact_name = f"upload_bundle_{job.id}_{stage_kind}_{base_name}"
        version = next_artifact_version(db, project.id, "upload_staging_file", artifact_name)
        metadata = {
            "project_id": project.id,
            "job_id": job.id,
            "source_filename": upload.filename,
            "content_type": upload.content_type,
            "upload_stage_kind": stage_kind,
            "original_index": index,
        }
        artifact_dir, stored, content_hash = store.store_stream(
            org_id="local-org",
            project_id=project.id,
            asset_type="upload_staging_file",
            name=artifact_name,
            version=version,
            filename=upload.filename or f"{base_name}{suffix}",
            stream=upload.file,
            metadata=metadata,
        )
        artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="upload_staging_file",
            name=artifact_name,
            uri=str(artifact_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={**metadata, "primary_path": str(stored.path)},
            version=version,
        )
        staged.append(artifact)
        column_names = quick_table_column_names(stored.path)
        if column_names:
            update_artifact_metadata(
                artifact,
                {"column_names": column_names, "column_count": len(column_names)},
            )
    return staged


def ingest_uploaded_data_bundle(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    table_uploads: list[UploadFile],
    hint_uploads: list[UploadFile],
    target_column: str | None,
    primary_filename: str | None,
    note: str | None,
    response_locale: str | None = None,
    progress_callback: Callable[[str, int, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    def progress(stage: str, percent: int, detail: dict[str, Any] | None = None) -> None:
        if progress_callback is not None:
            progress_callback(stage, percent, detail)

    effective_target = target_column or project.target_column
    if target_column and target_column != project.target_column:
        project.target_column = target_column

    selected_primary = select_uploaded_primary_table(table_uploads, primary_filename)
    used_table_names: set[str] = set()
    table_records: list[dict[str, Any]] = []
    dataset_records: list[DatasetSnapshot] = []
    dataset: DatasetSnapshot | None = None
    dataset_artifact: Artifact | None = None
    notebook_artifact_ids: list[str] = []
    notebook_warning: str | None = None

    progress(
        "storing_tables",
        15,
        {"table_file_count": len(table_uploads), "relational_hint_file_count": len(hint_uploads)},
    )
    for index, upload in enumerate(table_uploads):
        is_primary = upload is selected_primary
        suffix = Path(upload.filename or "").suffix.lower()
        table_name = uploaded_table_name(upload.filename or f"table_{index + 1}{suffix}", used_table_names)
        asset_type = "dataset_snapshot" if is_primary else "uploaded_supporting_table"
        artifact_name = "uploaded_dataset" if is_primary else f"uploaded_{table_name}"
        version = next_artifact_version(db, project.id, asset_type, artifact_name)
        artifact_dir, stored, content_hash = store.store_stream(
            org_id="local-org",
            project_id=project.id,
            asset_type=asset_type,
            name=artifact_name,
            version=version,
            filename=upload.filename or f"{table_name}{suffix}",
            stream=upload.file,
            metadata={
                "project_id": project.id,
                "source_filename": upload.filename,
                "table_name": table_name,
                "bundle_role": "primary_table" if is_primary else "supporting_table",
                "job_id": job.id,
            },
        )
        artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type=asset_type,
            name=artifact_name,
            uri=str(artifact_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={
                "primary_path": str(stored.path),
                "source_filename": upload.filename,
                "project_id": project.id,
                "table_name": table_name,
                "bundle_role": "primary_table" if is_primary else "supporting_table",
                "job_id": job.id,
            },
            version=version,
        )
        column_names = quick_table_column_names(stored.path)
        if column_names:
            update_artifact_metadata(
                artifact,
                {"column_names": column_names, "column_count": len(column_names)},
            )
        table_profile = profile_table_file(
            path=stored.path,
            root=stored.path.parent,
            role="primary_table" if is_primary else "supporting_table",
            is_primary=is_primary,
            target_column=effective_target,
            primary_table={},
        )
        table_profile["artifact_id"] = artifact.id
        table_profile["source_filename"] = upload.filename
        table_dataset: DatasetSnapshot | None = None
        if is_primary:
            progress(
                "profiling_tables",
                25,
                {"current_table": upload.filename, "table_index": index + 1, "table_file_count": len(table_uploads)},
            )
            dataset_artifact = artifact
            dataset = profile_dataset_artifact(
                db,
                store,
                project,
                artifact,
                effective_target,
                source_type="user_upload_bundle",
                source_ref=upload.filename,
            )
            project.primary_dataset_snapshot_id = dataset.id
            table_dataset = dataset
        else:
            table_dataset = create_lightweight_dataset_snapshot_from_table_profile(
                db,
                project=project,
                artifact=artifact,
                table_profile=table_profile,
                source_type="user_upload_bundle_table",
                source_ref=upload.filename,
            )
        if table_dataset is not None:
            dataset_records.append(table_dataset)
            table_profile["dataset_snapshot_id"] = table_dataset.id
        progress(
            "profiling_tables",
            30 + math.floor(((index + 1) / max(1, len(table_uploads))) * 30),
            {"current_table": upload.filename, "table_index": index + 1, "table_file_count": len(table_uploads)},
        )
        table_records.append(
            {
                "artifact": artifact,
                "stored_path": stored.path,
                "profile": table_profile,
                "is_primary": is_primary,
                "table_name": table_name,
                "dataset": table_dataset,
            }
        )

    if hint_uploads:
        progress("processing_schema_hints", 62, {"relational_hint_file_count": len(hint_uploads)})
    hint_results = []
    for upload in hint_uploads:
        result = create_relational_schema_hint(
            db,
            store=store,
            project=project,
            filename=upload.filename or "relational_schema_hint",
            content_type=upload.content_type,
            data=upload.file.read(MAX_SCHEMA_HINT_BYTES + 1),
            note=note,
        )
        hint_results.append(result)

    relational_catalog_artifact: Artifact | None = None
    manifest_artifact: Artifact | None = None
    if table_records:
        progress("building_catalog", 70, {"table_count": len(table_records), "relational_hint_count": len(hint_results)})
        relational_catalog = build_uploaded_relational_catalog(
            project=project,
            dataset=dataset,
            table_records=table_records,
            hint_results=hint_results,
            target_column=effective_target,
        )
        relational_catalog_artifact = store_and_register_json(
            db,
            store,
            project_id=project.id,
            asset_type="relational_catalog",
            name=f"relational_catalog_uploaded_{new_id('relcat')}",
            filename="relational_catalog.json",
            payload=relational_catalog,
            metadata={
                "project_id": project.id,
                "dataset_snapshot_id": dataset.id if dataset else None,
                "source_kind": "user_uploaded_bundle",
                "table_count": relational_catalog["table_count"],
                "relationship_count": len(relational_catalog["relationships"]),
                "primary_file": relational_catalog["primary_table"].get("selected_path"),
                "aggregate_merge_policy": "runner_defined_with_harness_guardrails",
            },
        )
        for record in table_records:
            artifact = cast(Artifact, record["artifact"])
            update_artifact_metadata(
                artifact,
                {
                    "relational_catalog_artifact_id": relational_catalog_artifact.id,
                    "relational_table_role": "primary_table" if record["is_primary"] else "supporting_table",
                },
            )
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact.id,
                to_asset_type="artifact",
                to_asset_id=relational_catalog_artifact.id,
                relation_type="cataloged_by",
            )
        for result in hint_results:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=result.artifact.id,
                to_asset_type="artifact",
                to_asset_id=relational_catalog_artifact.id,
                relation_type="provides_schema_hint",
            )
        if dataset:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="dataset_snapshot",
                from_asset_id=dataset.id,
                to_asset_type="artifact",
                to_asset_id=relational_catalog_artifact.id,
                relation_type="profiles_table_bundle",
            )
        manifest = build_uploaded_bundle_manifest(
            project=project,
            dataset=dataset,
            dataset_artifact=dataset_artifact,
            table_records=table_records,
            hint_results=hint_results,
            relational_catalog_artifact=relational_catalog_artifact,
            target_column=effective_target,
        )
        manifest_artifact = store_and_register_json(
            db,
            store,
            project_id=project.id,
            asset_type="relational_table_bundle_manifest",
            name=f"relational_table_bundle_{new_id('rtb')}",
            filename="relational_table_bundle_manifest.json",
            payload=manifest,
            metadata={
                "project_id": project.id,
                "dataset_snapshot_id": dataset.id if dataset else None,
                "relational_catalog_artifact_id": relational_catalog_artifact.id,
                "table_count": len(table_records),
                "supporting_table_count": len([record for record in table_records if not record["is_primary"]]),
                "aggregate_merge_policy": "runner_defined_with_harness_guardrails",
            },
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=relational_catalog_artifact.id,
            to_asset_type="artifact",
            to_asset_id=manifest_artifact.id,
            relation_type="summarized_by",
        )

    if dataset is not None:
        try:
            progress("preparing_notebook_context", 86, {"dataset_snapshot_id": dataset.id})
            authoring_result = create_notebook_authoring_brief(
                db,
                store=store,
                project=project,
                objective=(
                    "Author the project data-understanding marimo notebook from current artifacts and equipped Skills. "
                    "Do not use harness-authored notebook prose."
                ),
                response_locale=response_locale,
            )
            notebook_artifact_ids = [authoring_result.brief_artifact.id, authoring_result.report_artifact.id]
            notebook_warning = "awaiting_agent_authored_notebook"
            notebook_artifact = None
            notebook_report_artifact = None
            notebook_manifest_artifact = None
        except ValueError as exc:
            notebook_warning = str(exc)
            notebook_artifact = None
            notebook_report_artifact = None
            notebook_manifest_artifact = None
    else:
        notebook_artifact = None
        notebook_report_artifact = None
        notebook_manifest_artifact = None

    progress(
        "finalizing",
        94,
        {
            "dataset_snapshot_id": dataset.id if dataset else None,
            "dataset_snapshot_ids": [item.id for item in dataset_records],
            "table_count": len(table_records),
        },
    )
    set_data_understanding_phase_without_turning_agent_off(project)
    project.updated_at = utc_now()
    artifact_ids = [
        artifact.id
        for artifact in [
            dataset_artifact,
            relational_catalog_artifact,
            manifest_artifact,
            *[db.get(Artifact, artifact_id) for artifact_id in notebook_artifact_ids],
            *[cast(Artifact, record["artifact"]) for record in table_records if not record["is_primary"]],
            *[result.artifact for result in hint_results],
            *[result.report_artifact for result in hint_results],
        ]
        if artifact is not None
    ]
    if artifact_ids:
        record_harness_dataset_upload_in_research_plan(
            db,
            project_id=project.id,
            artifact_ids=artifact_ids,
            dataset_snapshot_id=dataset.id if dataset else None,
            primary_artifact_id=dataset_artifact.id if dataset_artifact else None,
        )
        record_harness_objective_in_research_plan(
            db,
            project_id=project.id,
            objective_label=project.target_column,
        )
    return {
        "schema_version": "upload_data_bundle.v1",
        "dataset_snapshot_id": dataset.id if dataset else None,
        "primary_dataset_snapshot_id": dataset.id if dataset else None,
        "dataset_snapshot_ids": [item.id for item in dataset_records],
        "dataset_artifact_id": dataset_artifact.id if dataset_artifact else None,
        "artifact_id": dataset_artifact.id if dataset_artifact else (hint_results[0].artifact.id if hint_results else None),
        "artifact_ids": artifact_ids,
        "table_file_count": len(table_uploads),
        "supporting_table_artifact_ids": [
            cast(Artifact, record["artifact"]).id for record in table_records if not record["is_primary"]
        ],
        "relational_hint_artifact_ids": [result.artifact.id for result in hint_results],
        "relational_hint_report_artifact_ids": [result.report_artifact.id for result in hint_results],
        "relational_catalog_artifact_id": relational_catalog_artifact.id if relational_catalog_artifact else None,
        "relational_table_bundle_manifest_artifact_id": manifest_artifact.id if manifest_artifact else None,
        "analysis_notebook_artifact_ids": [],
        "analysis_notebook_artifact_id": notebook_artifact.id if notebook_artifact else None,
        "notebook_report_artifact_id": notebook_report_artifact.id if notebook_report_artifact else None,
        "notebook_run_manifest_artifact_id": notebook_manifest_artifact.id if notebook_manifest_artifact else None,
        "notebook_kind": "data_understanding" if notebook_artifact else None,
        "notebook_authoring_brief_artifact_ids": notebook_artifact_ids,
        "notebook_warning": notebook_warning,
        "assistant_message": upload_bundle_assistant_message(
            project=project,
            table_count=len(table_uploads),
            hint_count=len(hint_uploads),
            target_column=effective_target,
            notebook_artifact_ids=notebook_artifact_ids,
            notebook_warning=notebook_warning,
            response_locale=response_locale,
        ),
        "aggregate_merge_policy": "Codex runner may design, implement, compare, and reject aggregate/merge strategies inside harness guardrails.",
        "runner_context": {
            "fixed_recipe_required": False,
            "supporting_tables_available": bool([record for record in table_records if not record["is_primary"]]),
            "must_respect_split_manifest": True,
            "must_not_use_validation_or_test_targets_for_feature_generation": True,
            "connector_credentials_materialized": False,
        },
    }


def upload_bundle_assistant_message(
    *,
    project: Project,
    table_count: int,
    hint_count: int,
    target_column: str | None,
    notebook_artifact_ids: list[str],
    notebook_warning: str | None,
    response_locale: str | None = None,
) -> str:
    japanese = locale_is_japanese(response_locale)
    if japanese:
        target_line = f"現在の目的/ターゲットは `{target_column}` です。" if target_column else (
            "目的/ターゲットは未設定です。Full Autoでは、Codexがアップロード済みデータを見てタスク形状を整理できます。"
        )
        notebook_line = (
            "Notebook作成の文脈を準備しました。Notebook本体はAgentが作成した後に表示されます。"
            if notebook_artifact_ids
            else "Notebook作成は、Agentがテーブル構造と目的の文脈を整理した後に始まります。"
        )
        return (
            f"{table_count}件のテーブルファイル"
            f"{f'と{hint_count}件のER/schema hint' if hint_count else ''}を取り込みました。\n\n"
            f"{target_line}\n\n"
            f"{notebook_line}"
        )
    target_line = f"Objective/target is currently `{target_column}`." if target_column else (
        "Objective/target is still open. Full Auto can ask Codex to review possible task shapes from the uploaded data."
    )
    notebook_line = (
        "Notebook authoring context is ready. The notebook itself will appear after the agent writes it."
        if notebook_artifact_ids
        else "Notebook authoring will start after the agent has enough table and objective context."
    )
    return (
        f"Uploaded {table_count} table file(s)"
        f"{f' and {hint_count} ER/schema hint file(s)' if hint_count else ''}.\n\n"
        f"{target_line}\n\n"
        f"{notebook_line}"
    )


def select_uploaded_primary_table(table_uploads: list[UploadFile], primary_filename: str | None) -> UploadFile | None:
    if not table_uploads:
        return None
    if primary_filename:
        for upload in table_uploads:
            if upload.filename == primary_filename:
                return upload
    return None


def create_lightweight_dataset_snapshot_from_table_profile(
    db: Session,
    *,
    project: Project,
    artifact: Artifact,
    table_profile: dict[str, Any],
    source_type: str,
    source_ref: str | None,
) -> DatasetSnapshot:
    schema_payload = table_profile.get("columns") if isinstance(table_profile.get("columns"), list) else []
    schema_hash = table_profile.get("schema_hash")
    if not isinstance(schema_hash, str) or not schema_hash.strip():
        schema_hash = hashlib.sha256(dumps_json(schema_payload).encode("utf-8")).hexdigest()
    row_count = table_profile.get("row_count")
    column_count = table_profile.get("column_count")
    dataset = DatasetSnapshot(
        id=new_id("ds"),
        project_id=project.id,
        artifact_id=artifact.id,
        source_type=source_type,
        source_ref=source_ref,
        row_count=int(row_count) if isinstance(row_count, int) else None,
        column_count=int(column_count) if isinstance(column_count, int) else None,
        schema_hash=schema_hash,
        data_hash=artifact.content_hash,
    )
    db.add(dataset)
    db.flush()
    raw_columns = table_profile.get("column_profiles")
    profile_column_names: list[str] = []
    if isinstance(raw_columns, list):
        for item in raw_columns:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                profile_column_names.append(name.strip())
    metadata_columns = artifact_metadata_column_names(loads_json(artifact.metadata_json, {}))
    semantic_columns: list[dict[str, Any]] = []
    if metadata_columns_should_override_profile(profile_column_names, metadata_columns):
        semantic_columns = [{"column_name": name, "physical_type": ""} for name in metadata_columns]
    elif isinstance(raw_columns, list):
        for item in raw_columns:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            semantic_columns.append(
                {
                    "column_name": name.strip(),
                    "physical_type": str(item.get("physical_type") or ""),
                }
            )
    if semantic_columns:
        catalog = SemanticCatalog(
            id=new_id("scat"),
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            artifact_id=None,
            columns_json=dumps_json(semantic_columns),
        )
        db.add(catalog)
    update_artifact_metadata(
        artifact,
        {
            "dataset_snapshot_id": dataset.id,
            "dataset_snapshot_source_type": source_type,
        },
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="records_table_artifact",
    )
    return dataset


def uploaded_table_name(filename: str, used: set[str]) -> str:
    base = table_name_from_path(filename)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_uploaded_relational_catalog(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    table_records: list[dict[str, Any]],
    hint_results: list[Any],
    target_column: str | None,
) -> dict[str, Any]:
    table_profiles = [cast(dict[str, Any], record["profile"]) for record in table_records]
    primary_profile = next((profile for profile in table_profiles if profile.get("is_primary")), None)
    primary_table_hint = (
        {
            "path": primary_profile.get("path"),
            "table_name": primary_profile.get("table_name"),
            "target_column": target_column,
            "entity_id_column": first_key_candidate(primary_profile),
        }
        if primary_profile is not None
        else {}
    )
    relationships = infer_relationships(table_profiles, primary_table_hint)
    relationships.extend(additional_shared_column_relationships(table_profiles, relationships))
    target_locations = [
        {"table": table["table_name"], "path": table["path"]}
        for table in table_profiles
        if target_column and target_column in table.get("columns", [])
    ]
    hint_summaries = [
        {
            "artifact_id": result.artifact.id,
            "report_artifact_id": result.report_artifact.id,
            "media_kind": result.summary.get("media_kind"),
            "content_type": result.summary.get("content_type"),
            "parsed_table_count": result.summary.get("parsed_table_count"),
            "parsed_relationship_count": result.summary.get("parsed_relationship_count"),
        }
        for result in hint_results
    ]
    return {
        "schema_version": "relational_catalog.v1",
        "source_kind": "user_uploaded_bundle",
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id if dataset else None,
        "primary_table": {
            "table_name": primary_profile.get("table_name") if primary_profile else None,
            "selected_path": primary_profile.get("path") if primary_profile else None,
            "target_column": target_column,
            "artifact_id": primary_profile.get("artifact_id") if primary_profile else None,
            "entity_id_column": primary_table_hint.get("entity_id_column"),
            "selected": primary_profile is not None,
        },
        "table_count": len(table_profiles),
        "table_limit": len(table_profiles),
        "table_discovery_truncated": False,
        "tables": table_profiles,
        "relationships": relationships,
        "target_locations": target_locations,
        "schema_hints": hint_summaries,
        "evaluation_guidance": {
            "primary_table_only_dataset_snapshot": True,
            "multi_table_features_are_runner_defined": True,
            "aggregate_merge_strategy": "open_ended_agent_designed",
            "fixed_recipe_required": False,
            "respect_split_manifest": True,
            "notes": [
                "Uploaded supporting tables are first-class artifacts for runner context.",
                "Codex may design arbitrary aggregate and merge strategies after inspecting evidence.",
                "The harness owns evaluation, leakage guardrails, lineage, and artifact registration.",
            ],
        },
        "risk_notes": uploaded_relational_risk_notes(
            table_profiles,
            target_locations,
            relationship_count=len(relationships),
        ),
        "agent_context_notes": [
            "Treat this catalog as evidence and workspace inventory, not as a mandatory feature recipe.",
            "Aggregate and merge choices are deliberately runner-defined; compare alternatives and reject unsafe joins.",
            "Fit joins, encoders, aggregations, TF-IDF, lag, and rolling features inside the training folds defined by SplitManifest.",
            "Do not pass secrets or connector credentials to the runner; uploaded table artifacts are the available data boundary.",
        ],
    }


def build_uploaded_bundle_manifest(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    dataset_artifact: Artifact | None,
    table_records: list[dict[str, Any]],
    hint_results: list[Any],
    relational_catalog_artifact: Artifact,
    target_column: str | None,
) -> dict[str, Any]:
    table_refs = [
        {
            "role": "primary_table" if record["is_primary"] else "supporting_table",
            "table_name": record["table_name"],
            "artifact_id": cast(Artifact, record["artifact"]).id,
            "dataset_snapshot_id": cast(DatasetSnapshot, record["dataset"]).id
            if record.get("dataset") is not None
            else None,
            "asset_type": cast(Artifact, record["artifact"]).asset_type,
            "download_url": f"/api/artifacts/{cast(Artifact, record['artifact']).id}/download",
            "preview_url": f"/api/artifacts/{cast(Artifact, record['artifact']).id}/preview",
            "source_filename": cast(dict[str, Any], record["profile"]).get("source_filename"),
        }
        for record in table_records
    ]
    return {
        "schema_version": "relational_table_bundle_manifest.v1",
        "source_kind": "user_uploaded_bundle",
        "project": {"id": project.id, "name": project.name, "target_column": target_column},
        "dataset_snapshot_id": dataset.id if dataset else None,
        "primary_dataset_artifact_id": dataset_artifact.id if dataset_artifact else None,
        "relational_catalog_artifact_id": relational_catalog_artifact.id,
        "tables": table_refs,
        "schema_hints": [
            {
                "artifact_id": result.artifact.id,
                "report_artifact_id": result.report_artifact.id,
                "preview_url": f"/api/artifacts/{result.artifact.id}/preview",
                "download_url": f"/api/artifacts/{result.artifact.id}/download",
            }
            for result in hint_results
        ],
        "runner_contract": {
            "aggregate_merge_policy": "runner_defined_with_harness_guardrails",
            "codex_may_design_custom_joins": True,
            "codex_may_write_project_specific_feature_code": True,
            "codex_may_reject_catalog_edges": True,
            "codex_must_respect_evaluation_spec_and_split_manifest": True,
            "codex_must_record_feature_recipe_and_lineage": True,
            "validation_and_test_targets_for_feature_generation": "forbidden",
            "connector_credentials": "never_materialized_to_agent",
        },
        "human_intent": {
            "why_this_exists": "One intake bundle gives the runner enough evidence to explore multi-table data science without hard-coding a single aggregate recipe.",
            "expected_next_actions": [
                "Deepen data understanding across tables.",
                "Draft candidate join and aggregation strategies with leakage checks.",
                "Compare primary-table-only and relational approaches under the same EvaluationSpec.",
            ],
        },
    }


def first_key_candidate(profile: dict[str, Any]) -> str | None:
    candidates = profile.get("key_candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("column"):
            return str(candidate["column"])
    return None


def additional_shared_column_relationships(
    table_profiles: list[dict[str, Any]], existing_relationships: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {
        (
            str(relationship.get("left_table")),
            str(relationship.get("right_table")),
            str(relationship.get("left_column")).lower(),
            str(relationship.get("right_column")).lower(),
        )
        for relationship in existing_relationships
    }
    added: list[dict[str, Any]] = []
    for left_index, left in enumerate(table_profiles):
        left_columns = {str(column).lower(): str(column) for column in left.get("columns", [])}
        for right in table_profiles[left_index + 1 :]:
            right_columns = {str(column).lower(): str(column) for column in right.get("columns", [])}
            for lower_name in sorted(set(left_columns) & set(right_columns)):
                if not likely_join_key_name(lower_name):
                    continue
                key = (
                    str(left.get("table_name")),
                    str(right.get("table_name")),
                    left_columns[lower_name].lower(),
                    right_columns[lower_name].lower(),
                )
                if key in seen:
                    continue
                added.append(
                    {
                        "left_table": left.get("table_name"),
                        "right_table": right.get("table_name"),
                        "left_column": left_columns[lower_name],
                        "right_column": right_columns[lower_name],
                        "relation_type": "shared_column_name",
                        "confidence": 0.48,
                        "evidence": "matching key-like column name; runner must confirm cardinality and timing before use",
                    }
                )
                seen.add(key)
                if len(added) >= 100:
                    return added
    return added


def likely_join_key_name(lower_name: str) -> bool:
    return (
        lower_name == "id"
        or lower_name.endswith("_id")
        or lower_name.startswith("id_")
        or lower_name.startswith("sk_")
        or "customer" in lower_name
        or "user" in lower_name
        or "account" in lower_name
        or "case" in lower_name
        or "transaction" in lower_name
    )


def uploaded_relational_risk_notes(
    table_profiles: list[dict[str, Any]],
    target_locations: list[dict[str, Any]],
    *,
    relationship_count: int,
) -> list[str]:
    notes: list[str] = []
    failed = [str(table.get("path")) for table in table_profiles if table.get("status") == "failed"]
    if failed:
        notes.append(f"Some uploaded tables failed lightweight profiling: {', '.join(failed[:5])}.")
    if len(target_locations) > 1:
        notes.append("Target-like column appears in multiple tables; confirm no post-outcome leakage before relational features.")
    if len(table_profiles) > 1 and relationship_count == 0:
        notes.append("Relationship edges are inferred only from names and profiles; uploaded ER hints or user confirmation should guide joins.")
    if not any(table.get("is_primary") and table.get("time_candidates") for table in table_profiles):
        notes.append("No primary-table time column was confirmed; time-aware validation may require user or runner investigation.")
    return notes


def update_artifact_metadata(artifact: Artifact, updates: dict[str, Any]) -> None:
    metadata = loads_json(artifact.metadata_json, {})
    metadata.update(updates)
    artifact.metadata_json = dumps_json(metadata)


@router.post("/api/datasets/{dataset_id}/eda-review", response_model=JobRead)
def run_dataset_eda_review(
    dataset_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    dataset = db.get(DatasetSnapshot, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="DatasetSnapshot not found")
    job = create_job(
        db,
        job_type="run_eda_review",
        project_id=dataset.project_id,
        input_payload={"dataset_snapshot_id": dataset.id},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "harness_controlled_duckdb_analysis",
            "executes_user_code": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/notebook-authoring/brief", response_model=JobRead)
def create_notebook_authoring_brief_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_notebook_authoring_brief",
        project_id=project_id,
        input_payload={"objective": "Prepare source-backed guidance for on-the-fly Codex notebook authoring."},
        policy={
            "external_network_access": "not_executed_by_endpoint",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "authoring_brief_only",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/relational/schema-hints/upload", response_model=JobRead)
def upload_relational_schema_hint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    file: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    require_project(db, project_id)
    data = file.file.read(MAX_SCHEMA_HINT_BYTES + 1)
    if len(data) > MAX_SCHEMA_HINT_BYTES:
        raise HTTPException(status_code=400, detail="Uploaded ER diagram file is too large. Limit is 25 MB.")
    source_filename = file.filename or "relational_schema_hint"
    version = next_artifact_version(db, project_id, "relational_schema_hint_upload", "staged_schema_hint_upload")
    artifact_dir, stored, content_hash = store.store_stream(
        org_id="local-org",
        project_id=project_id,
        asset_type="relational_schema_hint_upload",
        name="staged_schema_hint_upload",
        version=version,
        filename=source_filename,
        stream=io.BytesIO(data),
        metadata={
            "project_id": project_id,
            "source_filename": source_filename,
            "content_type": file.content_type,
            "purpose": "staged_for_worker_schema_hint_processing",
        },
    )
    staging_artifact = register_artifact(
        db,
        project_id=project_id,
        asset_type="relational_schema_hint_upload",
        name="staged_schema_hint_upload",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "project_id": project_id,
            "source_filename": source_filename,
            "content_type": file.content_type,
            "primary_path": str(stored.path),
            "purpose": "staged_for_worker_schema_hint_processing",
        },
        version=version,
    )
    job = create_job(
        db,
        job_type="upload_relational_schema_hint",
        project_id=project_id,
        input_payload={
            "filename": source_filename,
            "content_type": file.content_type,
            "note": note,
            "note_present": bool(note and note.strip()),
            "staging_artifact_id": staging_artifact.id,
        },
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "purpose": "store_user_supplied_er_diagram_evidence",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/import", response_model=JobRead)
def import_benchmark_dataset(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkImportRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="import_benchmark_dataset",
        project_id=project_id,
        input_payload={
            "benchmark_id": benchmark_id,
            "local_path": payload.local_path,
            "primary_file": payload.primary_file,
            "target_column": payload.target_column,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "user_managed_outside_tablex",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/scenario-pack", response_model=JobRead)
def create_project_benchmark_scenario_pack(
    project_id: str,
    benchmark_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="create_benchmark_scenario_pack",
        project_id=project_id,
        input_payload={
            "benchmark_id": benchmark_id,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/collection-plan", response_model=JobRead)
def create_project_benchmark_collection_plan(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_benchmark_collection_plan",
        project_id=project_id,
        input_payload={
            "project_id": project_id,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-plan", response_model=JobRead)
def create_project_relational_feature_plan(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_relational_feature_plan",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-recipe/build", response_model=JobRead)
def build_project_relational_feature_recipe(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="build_relational_feature_recipe",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
            "model_training": "not_performed_preview_only",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-scenarios/diagnose", response_model=JobRead)
def diagnose_project_relational_feature_scenarios(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="diagnose_relational_feature_scenarios",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
            "model_training": "not_performed_diagnostics_only",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/evidence-pack", response_model=JobRead)
def create_project_benchmark_evidence_pack(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_benchmark_evidence_pack",
        project_id=project_id,
        input_payload={
            "project_id": project_id,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/fixture-smoke", response_model=JobRead)
def run_benchmark_fixture_smoke(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkFixtureRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        raw_benchmark_dataset(benchmark_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="run_benchmark_fixture_smoke",
        project_id=project_id,
        input_payload={
            "benchmark_id": benchmark_id,
            "overwrite": payload.overwrite,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_required_for_fixture",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/public-workflow", response_model=JobRead)
def run_public_benchmark_workflow(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkPublicDownloadRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    benchmark = raw_benchmark_dataset(benchmark_id)
    benchmark_payload = benchmark_to_dict(benchmark, settings=request.app.state.settings, include_status=False)
    access = benchmark_payload.get("access") if isinstance(benchmark_payload.get("access"), dict) else {}
    if (
        access.get("requires_account")
        or access.get("requires_secret")
        or not access.get("supports_direct_download")
    ):
        raise HTTPException(
            status_code=400,
            detail="Public benchmark workflow requires a credential-free direct download source.",
        )
    job = create_job(
        db,
        job_type="run_public_benchmark_workflow",
        project_id=project_id,
        input_payload={
            "benchmark_id": benchmark_id,
            "overwrite": payload.overwrite,
            "data_dir": str(request.app.state.settings.data_dir),
            "artifact_root": str(request.app.state.settings.artifact_root),
        },
        policy={
            "execution": "queued_worker",
            "network": "enabled_for_catalog_public_archive_or_direct_file_only",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "catalog_credential_free_sources_only",
        },
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/datasets", response_model=list[DatasetSnapshotRead])
def list_project_datasets(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    project = require_project(db, project_id)
    datasets = db.scalars(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    ).all()
    primary_id = project.primary_dataset_snapshot_id
    ordered = sorted(
        datasets,
        key=lambda item: (item.id != primary_id, -(item.created_at.timestamp() if item.created_at else 0)),
    )
    return [dataset_to_dict(item, primary_dataset_snapshot_id=primary_id) for item in ordered]


@router.post("/api/projects/{project_id}/datasets/primary", response_model=DatasetSnapshotRead)
@router.post("/api/projects/{project_id}/primary-dataset", response_model=DatasetSnapshotRead)
def set_project_primary_dataset(
    project_id: str,
    payload: ProjectPrimaryDatasetUpdate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = resolve_project_primary_dataset_update(db, store=store, project=project, payload=payload)
    project.primary_dataset_snapshot_id = dataset.id
    if payload.target_column is not None:
        project.target_column = payload.target_column.strip() or None
        record_user_confirmed_task_spec_for_project_edit(
            db,
            store=store,
            project=project,
            target_column=project.target_column,
            table_ref=dataset.id,
        )
    set_data_understanding_phase_without_turning_agent_off(project)
    project.updated_at = utc_now()
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is not None:
        update_artifact_metadata(
            artifact,
            {
                "selected_as_primary_dataset_snapshot_id": dataset.id,
                "selected_as_project_primary_at": utc_now().isoformat(),
            },
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
    db.flush()
    return dataset_to_dict(dataset, primary_dataset_snapshot_id=project.primary_dataset_snapshot_id)


@router.post("/api/projects/{project_id}/datasets/primary/select", response_model=JobRead)
def queue_project_primary_dataset_selection(
    project_id: str,
    payload: ProjectPrimaryDatasetUpdate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    validate_project_primary_dataset_selection(db, project=project, payload=payload)
    job = create_job(
        db,
        job_type="select_primary_table",
        project_id=project.id,
        input_payload=payload.model_dump(exclude_unset=True),
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "purpose": "profile_and_select_user_chosen_primary_table",
        },
    )
    japanese = locale_is_japanese(payload.locale)
    job.output_json = dumps_json(
        {
            "schema_version": "select_primary_table_progress.v1",
            "status": "queued",
            "progress_stage": "queued",
            "progress_percent": 0,
            "assistant_message": (
                "主表の変更を受け付けました。Tablexがテーブル構造を確認して反映します。"
                if japanese
                else "Primary table change was queued. Tablex will inspect the table structure and apply it."
            ),
        }
    )
    return job_to_dict(job)


def resolve_project_primary_dataset_update(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    payload: ProjectPrimaryDatasetUpdate,
) -> DatasetSnapshot:
    if bool(payload.dataset_snapshot_id) == bool(payload.artifact_id):
        raise HTTPException(status_code=400, detail="Provide exactly one of dataset_snapshot_id or artifact_id")
    if payload.dataset_snapshot_id:
        dataset = db.get(DatasetSnapshot, payload.dataset_snapshot_id)
        if dataset is None or dataset.project_id != project.id:
            raise HTTPException(status_code=404, detail="DatasetSnapshot not found for this project")
        return dataset
    artifact = db.get(Artifact, payload.artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise HTTPException(status_code=404, detail="Table artifact not found for this project")
    if artifact.asset_type not in {"dataset_snapshot", "uploaded_supporting_table"}:
        raise HTTPException(status_code=400, detail="Primary table must be an uploaded table artifact")
    path = artifact_primary_path(artifact)
    if path.suffix.lower() not in TABLE_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail="Primary table artifact must be CSV or Parquet")
    existing = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id, DatasetSnapshot.artifact_id == artifact.id)
        .order_by(DatasetSnapshot.created_at.desc())
    )
    if existing is not None:
        return existing
    metadata = loads_json(artifact.metadata_json, {})
    return profile_dataset_artifact(
        db,
        store,
        project,
        artifact,
        payload.target_column if payload.target_column is not None else project.target_column,
        source_type="user_selected_primary_table",
        source_ref=str(metadata.get("source_filename") or metadata.get("table_name") or artifact.name),
    )


def validate_project_primary_dataset_selection(
    db: Session,
    *,
    project: Project,
    payload: ProjectPrimaryDatasetUpdate,
) -> None:
    if bool(payload.dataset_snapshot_id) == bool(payload.artifact_id):
        raise HTTPException(status_code=400, detail="Provide exactly one of dataset_snapshot_id or artifact_id")
    if payload.dataset_snapshot_id:
        dataset = db.get(DatasetSnapshot, payload.dataset_snapshot_id)
        if dataset is None or dataset.project_id != project.id:
            raise HTTPException(status_code=404, detail="DatasetSnapshot not found for this project")
        return
    artifact = db.get(Artifact, payload.artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise HTTPException(status_code=404, detail="Table artifact not found for this project")
    if artifact.asset_type not in {"dataset_snapshot", "uploaded_supporting_table"}:
        raise HTTPException(status_code=400, detail="Primary table must be an uploaded table artifact")
    path = artifact_primary_path(artifact)
    if path.suffix.lower() not in TABLE_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail="Primary table artifact must be CSV or Parquet")


@router.get("/api/datasets/{dataset_id}", response_model=DatasetSnapshotRead)
def get_dataset(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    project = require_project(db, dataset.project_id)
    return dataset_to_dict(dataset, primary_dataset_snapshot_id=project.primary_dataset_snapshot_id)


@router.get("/api/datasets/{dataset_id}/schema", response_model=SemanticCatalogRead)
def get_dataset_schema(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        raise HTTPException(status_code=404, detail="Semantic catalog not found")
    return semantic_catalog_to_dict(catalog)


@router.get("/api/projects/{project_id}/data/columns")
def project_data_columns(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    datasets = db.scalars(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id)
        .order_by(DatasetSnapshot.created_at.desc())
    ).all()
    def column_name(column: Any) -> str | None:
        if isinstance(column, str):
            return column.strip() or None
        if not isinstance(column, dict):
            return None
        for key in ("name", "column_name", "id"):
            value = column.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def column_detail(column: Any) -> dict[str, Any] | None:
        name = column_name(column)
        if not name:
            return None
        if not isinstance(column, dict):
            return {"name": name}
        detail = {"name": name}
        for key in ("physical_type", "missing_count", "missing_rate", "unique_count"):
            value = column.get(key)
            if isinstance(value, str) and value.strip():
                detail[key] = value.strip()
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                detail[key] = value
        return detail

    def columns_from_artifact_file(artifact: Artifact) -> list[str]:
        metadata = loads_json(artifact.metadata_json, {})
        metadata_columns = artifact_metadata_column_names(metadata)
        try:
            path = artifact_primary_path(artifact)
        except Exception:
            return metadata_columns
        file_columns = quick_table_column_names(path)
        if metadata_columns_should_override_profile(metadata_columns, file_columns):
            return file_columns
        return metadata_columns or file_columns

    def column_details_from_names(columns: list[str]) -> list[dict[str, Any]]:
        return [{"name": column} for column in columns]

    def columns_from_dataset_file(dataset: DatasetSnapshot) -> list[str]:
        artifact = db.get(Artifact, dataset.artifact_id)
        if artifact is None:
            return []
        return columns_from_artifact_file(artifact)

    tables: list[dict[str, Any]] = []
    dataset_artifact_ids: set[str] = set()
    for dataset in datasets:
        dataset_artifact_ids.add(dataset.artifact_id)
        catalog = db.scalar(
            select(SemanticCatalog)
            .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
            .order_by(SemanticCatalog.created_at.desc())
            .limit(1)
        )
        raw_columns = loads_json(catalog.columns_json, []) if catalog is not None else []
        columns = [name for item in raw_columns if (name := column_name(item))]
        column_details = [detail for item in raw_columns if (detail := column_detail(item))]
        file_columns = columns_from_dataset_file(dataset)
        if not columns or metadata_columns_should_override_profile(columns, file_columns):
            columns = file_columns
            column_details = column_details_from_names(columns)
        tables.append(
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_id": dataset.artifact_id,
                "source_ref": dataset.source_ref,
                "row_count": dataset.row_count,
                "column_count": dataset.column_count,
                "is_primary": dataset.id == project.primary_dataset_snapshot_id,
                "columns": list(dict.fromkeys(columns)),
                "column_details": column_details,
            }
        )
    supporting_table_artifacts = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project.id,
            Artifact.asset_type == "uploaded_supporting_table",
        )
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in supporting_table_artifacts:
        if artifact.id in dataset_artifact_ids:
            continue
        metadata = loads_json(artifact.metadata_json, {})
        columns = columns_from_artifact_file(artifact)
        source_ref = metadata.get("source_filename") or metadata.get("table_name") or artifact.name
        tables.append(
            {
                "dataset_snapshot_id": f"artifact:{artifact.id}",
                "artifact_id": artifact.id,
                "source_ref": str(source_ref) if source_ref else artifact.name,
                "row_count": None,
                "column_count": len(columns) if columns else None,
                "is_primary": False,
                "columns": list(dict.fromkeys(columns)),
                "column_details": column_details_from_names(list(dict.fromkeys(columns))),
            }
        )
    registered_source_refs = {str(item.get("source_ref")) for item in tables if item.get("source_ref")}
    active_upload_jobs = db.scalars(
        select(Job)
        .where(
            Job.project_id == project.id,
            Job.job_type == "upload_data_bundle",
            Job.status.notin_(["succeeded", "failed", "cancelled", "timed_out"]),
        )
        .order_by(Job.created_at.desc())
        .limit(8)
    ).all()
    staged_table_artifact_ids: list[str] = []
    staged_primary_filenames: set[str] = set()
    for job in active_upload_jobs:
        for payload in (loads_json(job.input_json, {}), loads_json(job.output_json, {})):
            staged_table_artifact_ids.extend(
                str(item)
                for item in payload.get("staged_table_artifact_ids", [])
                if isinstance(item, str) and item.strip()
            )
        job_input = loads_json(job.input_json, {})
        primary_filename = job_input.get("primary_filename")
        if isinstance(primary_filename, str) and primary_filename.strip():
            staged_primary_filenames.add(primary_filename.strip())
    if staged_table_artifact_ids:
        staged_artifacts = db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.id.in_(list(dict.fromkeys(staged_table_artifact_ids))))
            .order_by(Artifact.created_at.desc())
        ).all()
        for artifact in staged_artifacts:
            metadata = loads_json(artifact.metadata_json, {})
            if metadata.get("upload_stage_kind") != "table":
                continue
            columns = columns_from_artifact_file(artifact)
            if not columns:
                continue
            source_ref = str(metadata.get("source_filename") or artifact.name)
            if source_ref in registered_source_refs:
                continue
            tables.append(
                {
                    "dataset_snapshot_id": f"staged:{artifact.id}",
                    "artifact_id": artifact.id,
                    "source_ref": source_ref,
                    "row_count": None,
                    "column_count": len(columns),
                    "is_primary": source_ref in staged_primary_filenames,
                    "columns": list(dict.fromkeys(columns)),
                    "column_details": column_details_from_names(list(dict.fromkeys(columns))),
                }
            )
    tables.sort(key=lambda item: (not item["is_primary"], item["source_ref"] or item["dataset_snapshot_id"]))
    return {"schema_version": "project_column_catalog.v1", "project_id": project.id, "tables": tables}


@router.get("/api/datasets/{dataset_id}/sample")
def get_dataset_sample(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    profile = latest_profile_for_dataset(db, dataset)
    return {"rows": profile.get("sample_rows", [])}


@router.post("/api/datasets/{dataset_id}/quality/run", response_model=JobRead)
def run_dataset_quality(
    dataset_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    project = require_project(db, dataset.project_id)
    job = create_job(
        db,
        job_type="analyze_data_quality",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/datasets/{dataset_id}/quality/latest", response_model=ArtifactRead)
def latest_dataset_quality(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == dataset.project_id, Artifact.asset_type == "data_quality_gate")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("dataset_snapshot_id") == dataset.id:
            return artifact_to_dict(artifact)
    raise HTTPException(status_code=404, detail="Data quality gate not found")


@router.post("/api/datasets/{dataset_id}/profile", response_model=JobRead)
def rerun_profile(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    project = require_project(db, dataset.project_id)
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    job = create_job(
        db,
        job_type="profile_dataset",
        project_id=project.id,
        input_payload={
            "dataset_snapshot_id": dataset.id,
            "artifact_id": artifact.id,
            "target_column": project.target_column,
            "source_type": dataset.source_type,
            "source_ref": dataset.source_ref,
        },
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/understanding/run", response_model=JobRead)
def run_understanding(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before running understanding")
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    job = create_job(
        db,
        job_type="profile_dataset",
        project_id=project_id,
        input_payload={
            "dataset_snapshot_id": dataset.id,
            "artifact_id": artifact.id,
            "target_column": project.target_column,
            "source_type": dataset.source_type,
            "source_ref": dataset.source_ref,
        },
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/understanding/latest")
def latest_understanding(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    require_project(db, project_id)
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type.in_(["eda_profile", "understanding_report"]))
        .order_by(Artifact.created_at.desc())
    ).all()
    report = next((item for item in artifacts if item.asset_type == "understanding_report"), None)
    profile = next((item for item in artifacts if item.asset_type == "eda_profile"), None)
    return {
        "profile_artifact": artifact_to_dict(profile) if profile else None,
        "report_artifact": artifact_to_dict(report) if report else None,
        "markdown": artifact_primary_path(report).read_text(encoding="utf-8") if report else None,
    }


@router.get("/api/projects/{project_id}/questions", response_model=list[QuestionRead])
def list_questions(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    questions = db.scalars(
        select(Question).where(Question.project_id == project_id).order_by(Question.priority.desc(), Question.created_at)
    ).all()
    return [question_to_dict(item) for item in questions]


@router.post("/api/questions/{question_id}/answer", response_model=AnswerRead)
def answer_question(
    question_id: str,
    payload: QuestionAnswerCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    answer = Answer(
        id=new_id("ans"),
        question_id=question.id,
        answer_value=payload.answer_value,
        answer_text=payload.answer_text,
    )
    db.add(answer)
    question.status = "answered"

    evidence = Evidence(
        id=new_id("ev"),
        project_id=question.project_id,
        evidence_type="user_answer",
        summary=f"Answer to question `{question.id}`: {payload.answer_value}",
        strength="decisive",
        metadata_json=dumps_json(
            {
                "question_id": question.id,
                "topic": question.topic,
                "answer_text": payload.answer_text,
            }
        ),
    )
    db.add(evidence)

    if question.related_assumption_id:
        assumption = db.get(Assumption, question.related_assumption_id)
        if assumption is not None:
            assumption.status = "confirmed"
            assumption.confidence = max(assumption.confidence, 0.9)
            assumption.updated_at = utc_now()
            db.add(
                AssumptionEvidenceLink(
                    id=new_id("ael"),
                    assumption_id=assumption.id,
                    evidence_id=evidence.id,
                    effect="supports",
                    weight=1.0,
                )
            )
    db.flush()
    return answer_to_dict(answer)


@router.get("/api/projects/{project_id}/assumptions", response_model=list[AssumptionRead])
def list_assumptions(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    assumptions = db.scalars(
        select(Assumption).where(Assumption.project_id == project_id).order_by(Assumption.risk_level.desc(), Assumption.created_at)
    ).all()
    return [assumption_to_dict(db, item) for item in assumptions]


@router.get("/api/projects/{project_id}/assumptions/review-queue", response_model=AssumptionReviewQueueRead)
def assumption_review_queue(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_assumption_review_queue(db, project)


@router.post("/api/projects/{project_id}/assumptions/infer", response_model=JobRead)
def infer_assumptions(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="infer_assumptions",
        project_id=project_id,
        input_payload={"apply_unanswered_fallbacks": True},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/evidence")
def create_evidence(project_id: str, payload: EvidenceCreate, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    require_project(db, project_id)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project_id,
        evidence_type=payload.evidence_type,
        summary=payload.summary,
        strength=payload.strength,
        source_artifact_id=payload.source_artifact_id,
        metadata_json=dumps_json(payload.metadata),
    )
    db.add(evidence)
    db.flush()
    return evidence_to_dict(evidence)


@router.post("/api/assumptions/{assumption_id}/confirm", response_model=AssumptionRead)
def confirm_assumption(assumption_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    assumption = require_assumption(db, assumption_id)
    assumption.status = "confirmed"
    assumption.confidence = max(assumption.confidence, 0.9)
    assumption.updated_at = utc_now()
    return assumption_to_dict(db, assumption)


@router.post("/api/assumptions/{assumption_id}/reject", response_model=AssumptionRead)
def reject_assumption(assumption_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    assumption = require_assumption(db, assumption_id)
    assumption.status = "challenged"
    assumption.confidence = min(assumption.confidence, 0.35)
    assumption.updated_at = utc_now()
    return assumption_to_dict(db, assumption)


@router.get("/api/assumptions/{assumption_id}/evidence")
def list_assumption_evidence(assumption_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    assumption = require_assumption(db, assumption_id)
    links = db.scalars(select(AssumptionEvidenceLink).where(AssumptionEvidenceLink.assumption_id == assumption.id)).all()
    if not links:
        return []
    evidence = db.scalars(select(Evidence).where(Evidence.id.in_([link.evidence_id for link in links]))).all()
    return [evidence_to_dict(item) for item in evidence]


@router.post("/api/projects/{project_id}/evaluation/design", response_model=JobRead)
def design_evaluation(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before designing evaluation")
    job = create_job(
        db,
        job_type="design_evaluation_candidates",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/evaluation/compare", response_model=JobRead)
def compare_evaluation_scenarios(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before comparing evaluation scenarios")
    job = create_job(
        db,
        job_type="compare_evaluation_scenarios",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/evaluation/candidates", response_model=list[EvaluationCandidateRead])
def list_evaluation_candidates(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    candidates = db.scalars(
        select(EvaluationCandidate).where(EvaluationCandidate.project_id == project_id).order_by(EvaluationCandidate.created_at.desc())
    ).all()
    return [candidate_to_dict(item) for item in candidates]


@router.post("/api/evaluation-candidates/{candidate_id}/promote", response_model=EvaluationSpecRead)
def promote_evaluation_candidate(candidate_id: str, db: Annotated[Session, Depends(get_session)], store: Annotated[LocalArtifactStore, Depends(get_artifact_store)]) -> dict[str, Any]:
    candidate = db.get(EvaluationCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="EvaluationCandidate not found")
    spec = promote_candidate_to_spec(db, store=store, candidate=candidate)
    return spec_to_dict(spec)


@router.get("/api/projects/{project_id}/evaluation/specs", response_model=list[EvaluationSpecRead])
def list_evaluation_specs(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    specs = db.scalars(
        select(EvaluationSpec).where(EvaluationSpec.project_id == project_id).order_by(EvaluationSpec.created_at.desc())
    ).all()
    return [spec_to_dict(item) for item in specs]


@router.get("/api/evaluation-specs/{spec_id}", response_model=EvaluationSpecRead)
def get_evaluation_spec(spec_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    return spec_to_dict(spec)


@router.post("/api/evaluation-specs/{spec_id}/approval-review", response_model=JobRead)
def review_evaluation_spec_approval(
    spec_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    job = create_job(
        db,
        job_type="review_evaluation_approval",
        project_id=spec.project_id,
        input_payload={"evaluation_spec_id": spec.id, "approval_intent": False},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.post("/api/evaluation-specs/{spec_id}/approve", response_model=EvaluationSpecRead)
def approve_evaluation_spec(
    spec_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    job = create_job(
        db,
        job_type="review_evaluation_approval",
        project_id=spec.project_id,
        input_payload={"evaluation_spec_id": spec.id, "approval_intent": True},
    )
    try:
        mark_job_running(job)
        result = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=True)
        decision = result.payload["decision_support"]
        if result.blocked:
            mark_job_failed(
                job,
                "Evaluation approval is blocked by required questions or deployment-blocking assumptions",
                {
                    "evaluation_spec_id": spec.id,
                    "artifact_id": result.artifact.id,
                    "review_status": decision["review_status"],
                    "blocked": decision["blocked"],
                    "blocker_count": decision["blocker_count"],
                },
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Evaluation approval is blocked by required questions or deployment-blocking assumptions",
                    "artifact_id": result.artifact.id,
                    "blockers": result.payload["blockers"],
                },
            )
        approve_spec(spec)
        approved_artifact = write_spec_artifact(db, store, spec)
        create_lineage_edge(
            db,
            project_id=spec.project_id,
            from_asset_type="artifact",
            from_asset_id=result.artifact.id,
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
        mark_job_succeeded(
            job,
            {
                "evaluation_spec_id": spec.id,
                "approval_review_artifact_id": result.artifact.id,
                "evaluation_spec_artifact_id": approved_artifact.id,
                "review_status": decision["review_status"],
                "warning_count": decision["warning_count"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return spec_to_dict(spec)


@router.post("/api/evaluation-specs/{spec_id}/generate-split", response_model=JobRead)
def generate_split(spec_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    job = create_job(
        db,
        job_type="build_split_manifest",
        project_id=spec.project_id,
        input_payload={"evaluation_spec_id": spec.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/split-manifests/{split_id}", response_model=SplitManifestRead)
def get_split_manifest(split_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    split = db.get(SplitManifest, split_id)
    if split is None:
        raise HTTPException(status_code=404, detail="SplitManifest not found")
    return split_to_dict(split)


@router.get("/api/projects/{project_id}/approach/strategy-brief", response_model=AdaptiveStrategyBriefRead)
def get_project_strategy_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    locale: str | None = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
    response_locale = (
        locale.strip()
        if isinstance(locale, str) and locale.strip()
        else explicit_project_response_locale(db, project)
    )
    return build_adaptive_strategy_brief(db, project=project, locale=response_locale)


@router.post("/api/projects/{project_id}/approach/strategy-brief", response_model=JobRead)
def create_project_strategy_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_project(db, project_id)
    input_payload = payload if isinstance(payload, dict) else {}
    job = create_job(
        db,
        job_type="create_adaptive_strategy_brief",
        project_id=project_id,
        input_payload=input_payload,
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-plan", response_model=JobRead)
def generate_project_research_plan(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    spec = latest_approved_spec(db, project_id)
    job = create_job(
        db,
        job_type="plan_research",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id if dataset else None, "evaluation_spec_id": spec.id if spec else None},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/agent-task-plan", response_model=JobRead)
def plan_project_agent_task_endpoint(
    project_id: str,
    payload: AgentTaskPlanCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="plan_agent_task",
        project_id=project_id,
        input_payload={"objective": payload.objective, "task_type": payload.task_type},
        policy={
            "network": "disabled_until_runner_policy_allows",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/agent-chat", response_model=AgentChatRead)
def create_agent_chat_turn(
    project_id: str,
    payload: AgentChatCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    sidecar_only = is_sidecar_chat_request(payload.message)
    session = active_main_session(db, project_id)
    if session is None and not sidecar_only:
        latest_session = latest_main_session(db, project_id)
        if latest_session is not None and latest_session.status == "completed" and project.autonomy_mode == "full_auto":
            latest_session.status = "between_turns"
            latest_session.pid = None
            latest_session.ended_at = None
            latest_session.updated_at = utc_now()
            project.current_phase = "AUTONOMOUS_LOOP"
            project.updated_at = utc_now()
            session = latest_session
        elif (
            project.autonomy_mode == "full_auto"
            and (latest_session is None or latest_session.status != "stopped")
        ):
            session = start_or_resume_main_session(
                db,
                store=store,
                project=project,
                goal_text=None,
                autonomy_mode="full_auto",
                runner_kind="codex_cli",
                created_by=request_actor_id(request),
            )
            project.current_phase = "AUTONOMOUS_LOOP"
            project.updated_at = utc_now()
    if session is not None and not sidecar_only:
        event = append_session_event(
            db,
            session,
            source="user",
            event_type="user_instruction",
            role="user",
            title="User instruction",
            content=payload.message,
            payload={
                "locale": payload.locale,
                "agent_model": payload.agent_model,
                "utility_model": payload.utility_model,
                "delivery": "queued_for_main_agent_session",
            },
        )
        append_user_instruction_to_workspace_inbox(
            session,
            event=event,
            message=payload.message,
            locale=payload.locale,
        )
        progress_event = maybe_request_codex_progress_update(
            db,
            session=session,
            locale=payload.locale,
            stale_after_seconds=0,
            min_interval_seconds=0,
            trigger="user_chat_message",
            user_message=payload.message,
        )
        job = create_job(
            db,
            job_type="agent_chat_turn",
            project_id=project_id,
            input_payload={
                "message": payload.message,
                "locale": payload.locale,
                "agent_model": payload.agent_model,
                "utility_model": payload.utility_model,
                "delivered_agent_session_id": session.id,
                "agent_transcript_event_id": event.id,
                "agent_transcript_event_index": event.event_index,
                "progress_update_requested_event_id": progress_event.id if progress_event is not None else None,
            },
            policy={
                "network": "codex_response_composer_policy",
                "secret_access": "forbidden",
                "connector_credentials": "not_materialized",
                "runner_execution": "codex_response_composer",
                "response_composer": "codex_cli_if_available",
                "sidecar_only": False,
                "response_locale": payload.locale,
                "agent_model": payload.agent_model,
                "utility_model": payload.utility_model,
                "delivered_to_running_codex_session": True,
                "response_completion_source": "main_codex_session_chat_update",
            },
            priority=90,
        )
        job.status = MAIN_SESSION_CHAT_WAITING_STATUS
        job.updated_at = utc_now()
        should_wake_main_session = (
            project.current_phase == "AUTONOMOUS_LOOP"
            and session.status in {"starting", "between_turns", "waiting_for_runner"}
            and not supervisor_slot_active(session.id)
        )
        response = queued_main_session_chat_response(
            db=db,
            project=project,
            session=session,
            event=event,
            job=job,
            message=payload.message,
            locale=payload.locale,
            progress_event=progress_event,
        )
        db.commit()
        if should_wake_main_session and request.app.state.settings.api_agent_session_supervisor_enabled:
            start_main_agent_session_supervisor_thread(
                request.app.state.session_factory,
                store,
                project_id=project_id,
                session_id=session.id,
                supervisor_runner=run_main_agent_session_supervisor,
                turn_timeout_seconds=request.app.state.settings.agent_idle_timeout_seconds,
                turn_start_silence_timeout_seconds=request.app.state.settings.agent_turn_start_silence_timeout_seconds,
            )
        return response
    job = create_job(
        db,
        job_type="agent_chat_turn",
        project_id=project_id,
        input_payload={
            "message": payload.message,
            "locale": payload.locale,
            "agent_model": payload.agent_model,
            "utility_model": payload.utility_model,
        },
        policy={
            "network": "codex_response_composer_policy",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "runner_execution": "codex_response_composer",
            "response_composer": "codex_cli_if_available",
            "sidecar_only": sidecar_only,
            "response_locale": payload.locale,
            "agent_model": payload.agent_model,
            "utility_model": payload.utility_model,
        },
        priority=80,
    )
    wait_state = agent_chat_wait_state(
        job,
        delivered_to_running_codex=False,
        locale=payload.locale,
    )
    return {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": payload.message,
        "assistant_message": wait_state["assistant_message"],
        "intent": {
            "type": "agent_conversation",
            "confidence": None,
            "summary": "Queued for Codex-authored response composition.",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_chat_queued.v1",
            "response_locale": payload.locale,
            "job_id": job.id,
            "wait_state": wait_state["brief"],
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "queued_worker",
            "status": "queued",
        },
        "worker_events": [
            {
                "worker_id": "agent-chat",
                "display_name": "Agent Chat",
                "status": "queued",
                "headline": wait_state["headline"],
                "detail": wait_state["detail"],
                "job_id": job.id,
                "project_id": project.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
                "active": True,
                "token_usage": {"source": "pending_response", "is_estimate": True, "series": []},
            }
        ],
        "token_usage": {"source": "pending_response", "is_estimate": True, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent Chat"},
        "artifact_id": f"pending_{job.id}",
        "job": job_to_dict(job),
    }


def is_sidecar_chat_request(message: str) -> bool:
    return message.strip().lower() == "/btw"


@router.post("/api/projects/{project_id}/agent-session/console-message", response_model=AgentConsoleMessageRead)
def send_agent_console_message(
    project_id: str,
    payload: AgentConsoleMessageCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    if session is None:
        raise HTTPException(status_code=409, detail="Start Full Auto before using the Codex Console.")
    if session.status == "stopped":
        raise HTTPException(status_code=409, detail="The agent power is off. Start Full Auto before sending console input.")
    if session.status in {"failed", "gave_up"}:
        raise HTTPException(status_code=409, detail=f"The main session is {session.status}; start Full Auto before sending console input.")
    woke_session = False
    if session.status == "completed":
        session.status = "between_turns"
        session.pid = None
        session.ended_at = None
        session.updated_at = utc_now()
        project.current_phase = "AUTONOMOUS_LOOP"
        project.autonomy_mode = "full_auto"
        project.updated_at = utc_now()
        woke_session = True
    message = payload.message.strip()
    event = append_session_event(
        db,
        session,
        source="user",
        event_type="user_instruction",
        role="user",
        title="Console instruction",
        content=message,
        payload={
            "locale": payload.locale,
            "channel": "console",
            "delivery": "direct_console_to_main_agent_session",
        },
    )
    append_user_instruction_to_workspace_inbox(
        session,
        event=event,
        message=message,
        locale=payload.locale,
        channel="console",
    )
    maybe_request_codex_progress_update(
        db,
        session=session,
        locale=payload.locale,
        stale_after_seconds=0,
        min_interval_seconds=0,
        trigger="console_message",
        user_message=message,
    )
    should_wake_main_session = (
        project.current_phase == "AUTONOMOUS_LOOP"
        and session.status in {"starting", "between_turns", "waiting_for_runner"}
        and not supervisor_slot_active(session.id)
    )
    db.commit()
    if should_wake_main_session and request.app.state.settings.api_agent_session_supervisor_enabled:
        start_main_agent_session_supervisor_thread(
            request.app.state.session_factory,
            store,
            project_id=project_id,
            session_id=session.id,
            supervisor_runner=run_main_agent_session_supervisor,
            turn_timeout_seconds=request.app.state.settings.agent_idle_timeout_seconds,
            turn_start_silence_timeout_seconds=request.app.state.settings.agent_turn_start_silence_timeout_seconds,
        )
    return {
        "schema_version": "agent_console_message.v1",
        "project_id": project.id,
        "session_id": session.id,
        "status": session.status,
        "delivered": True,
        "woke_session": woke_session,
        "transcript_event_id": event.id,
        "transcript_event_index": event.event_index,
        "inbox_delivery": "workspace_inbox_and_transcript",
        "message": message,
    }


def queued_main_session_chat_response(
    *,
    db: Session,
    project: Project,
    session: AgentSession,
    event: AgentTranscriptEvent,
    job: Job,
    message: str,
    locale: str | None,
    progress_event: AgentTranscriptEvent | None = None,
) -> dict[str, Any]:
    wait_state = agent_chat_wait_state(
        job,
        delivered_to_running_codex=True,
        locale=locale,
        response_worker_status=job.status,
    )
    assistant_message = wait_state["assistant_message"]
    return {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": message,
        "assistant_message": assistant_message,
        "intent": {
            "type": "agent_conversation",
            "source": "main_agent_session_inbox",
            "routing_policy": "delivered_to_running_codex_session_and_composed_as_async_chat_response",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_chat_main_session_delivery.v1",
            "response_locale": locale,
            "agent_session_id": session.id,
            "agent_session_observation": agent_session_observation_for_chat_wait(db=db, session=session),
            "agent_transcript_event_id": event.id,
            "agent_transcript_event_index": event.event_index,
            "delivery": "workspace_inbox_and_transcript",
            "progress_update_requested_event_id": progress_event.id if progress_event is not None else None,
            "job_id": job.id,
            "status": job.status,
            "wait_state": wait_state["brief"],
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session",
            "status": job.status,
        },
        "worker_events": [
            {
                "worker_id": "agent-chat",
                "display_name": "Agent Chat",
                "status": job.status,
                "headline": wait_state["headline"],
                "detail": wait_state["detail"],
                "job_id": job.id,
                "project_id": project.id,
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
                "active": True,
                "token_usage": {"source": "pending_response", "is_estimate": True, "series": []},
            }
        ],
        "token_usage": {"source": "pending_response", "is_estimate": True, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent Chat"},
        "artifact_id": f"pending_{job.id}",
        "job": job_to_dict(job),
    }


def agent_session_observation_for_chat_wait(db: Session, session: AgentSession) -> dict[str, Any]:
    now = utc_now()
    raw_observation = raw_transcript_observation_for_session(session)
    last_codex_output_at = latest_codex_output_timestamp(
        latest_codex_transcript_output_at(db, session_id=session.id),
        raw_observation,
    )
    last_chat_update_at = latest_codex_chat_update_at(db, project_id=session.project_id, session_id=session.id)
    latest_codex_message = latest_codex_message_observation_for_session(db, session=session)
    return {
        "schema_version": "agent_session_chat_wait_observation.v1",
        "agent_session_id": session.id,
        "status": session.status,
        "turn_index": session.turn_index,
        "has_process": session.pid is not None,
        "last_error": session.last_error,
        "last_heartbeat_at": session.last_heartbeat_at.isoformat() if session.last_heartbeat_at else None,
        "last_heartbeat_seconds_ago": seconds_since_timestamp(session.last_heartbeat_at, now=now),
        "last_codex_output_at": last_codex_output_at.isoformat() if last_codex_output_at else None,
        "last_codex_output_seconds_ago": seconds_since_timestamp(last_codex_output_at, now=now),
        "latest_codex_message": latest_codex_message,
        "last_chat_update_at": last_chat_update_at.isoformat() if last_chat_update_at else None,
        "last_chat_update_seconds_ago": seconds_since_timestamp(last_chat_update_at, now=now),
        "raw_transcript": raw_observation,
    }


def latest_codex_output_timestamp(db_output_at: datetime | None, raw_observation: dict[str, Any]) -> datetime | None:
    raw_output_at = datetime_from_iso_or_none(raw_observation.get("updated_at"))
    candidates = [item for item in (utc_datetime_or_none(db_output_at), raw_output_at) if item is not None]
    if not candidates:
        return None
    return max(candidates)


def latest_codex_message_observation_for_session(
    db: Session,
    *,
    session: AgentSession,
    limit: int = 360,
) -> dict[str, Any] | None:
    db_candidate: dict[str, Any] | None = None
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.source == "codex_cli",
                AgentTranscriptEvent.title == "Codex message",
                AgentTranscriptEvent.content.is_not(None),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(20)
        ).all()
    )
    for event in events:
        content = (event.content or "").strip()
        if not content or content.startswith("usage:"):
            continue
        db_candidate = {
            "source": "agent_transcript_event",
            "event_index": event.event_index,
            "created_at": event.created_at.isoformat(),
            "content": compact_activity_summary(content, limit=limit),
        }
        break
    raw_candidate = latest_codex_message_observation_from_raw_transcript(session, limit=limit)
    if db_candidate and raw_candidate:
        db_created_at = datetime_from_iso_or_none(db_candidate.get("created_at"))
        raw_created_at = datetime_from_iso_or_none(raw_candidate.get("created_at"))
        if db_created_at is not None and raw_created_at is not None and raw_created_at > db_created_at:
            return raw_candidate
        return db_candidate
    return db_candidate or raw_candidate


def latest_codex_message_observation_from_raw_transcript(
    session: AgentSession,
    *,
    limit: int = 360,
) -> dict[str, Any] | None:
    if not session.workspace_path:
        return None
    stdout_path = raw_codex_transcript_path(Path(session.workspace_path))
    _line_count, _tail, tail_lines, updated_at = tail_text_file(stdout_path, limit=80)
    for line in reversed(tail_lines):
        parsed = line.get("parsed")
        if not isinstance(parsed, dict):
            continue
        content = codex_agent_message_content_from_event(parsed)
        if not content or content.startswith("usage:"):
            continue
        created_at = codex_event_timestamp(parsed) or updated_at
        return {
            "source": "raw_transcript_file",
            "line_number": line.get("line_number"),
            "created_at": created_at,
            "content": compact_activity_summary(content, limit=limit),
        }
    return None


def codex_agent_message_content_from_event(event: dict[str, Any]) -> str | None:
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "agent_message":
        return None
    for key in ("text", "output", "summary", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def codex_event_timestamp(event: dict[str, Any]) -> str | None:
    for key in ("timestamp", "time", "created_at", "createdAt"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def datetime_from_iso_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return utc_datetime_or_none(parsed)


def utc_datetime_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_agent_chat_navigation_actions(
    actions: list[Any],
    *,
    db: Session | None = None,
    project_id: str | None = None,
    japanese: bool = False,
) -> list[Any]:
    normalized: list[Any] = []
    for action in actions:
        if not isinstance(action, dict):
            normalized.append(action)
            continue
        normalized_action = normalize_agent_chat_navigation_focus(action)
        if db is not None and project_id is not None:
            normalized_action = normalize_agent_chat_notebook_action_artifact(
                db,
                project_id=project_id,
                action=normalized_action,
                japanese=japanese,
            )
        normalized.append(normalized_action)
    return normalized


def normalize_agent_chat_navigation_focus(focus: dict[str, Any]) -> dict[str, Any]:
    target_anchor = focus.get("target_anchor")
    if isinstance(target_anchor, str) and target_anchor in NOTEBOOK_NAVIGATION_ANCHORS:
        return {**focus, "target_tab": "Notebooks", "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR}
    return focus


def normalize_agent_chat_notebook_action_artifact(
    db: Session,
    *,
    project_id: str,
    action: dict[str, Any],
    japanese: bool = False,
) -> dict[str, Any]:
    if action.get("target_tab") != "Notebooks":
        return action
    artifact_ids: list[str] = []
    if isinstance(action.get("artifact_id"), str) and action["artifact_id"].strip():
        artifact_ids.append(action["artifact_id"].strip())
    raw_artifact_ids = action.get("artifact_ids")
    if isinstance(raw_artifact_ids, list):
        artifact_ids.extend(item.strip() for item in raw_artifact_ids if isinstance(item, str) and item.strip())
    notebook_artifact = first_native_notebook_artifact_for_action(db, project_id=project_id, artifact_ids=artifact_ids)
    detail = (
        "保存されたmarimo sourceをnative marimoで開きます。"
        if japanese
        else "Open the saved marimo source with native marimo."
    )
    if action.get("status") not in {None, "ready"}:
        detail = (
            "失敗は隠さず、marimo sourceの修正対象として扱います。"
            if japanese
            else "The failure is exposed as a marimo source issue to fix."
        )
    if notebook_artifact is None:
        if action.get("status") not in {None, "ready"}:
            return {
                **action,
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "detail": detail,
            }
        return action
    return {
        **action,
        "artifact_id": notebook_artifact.id,
        "artifact_ids": [notebook_artifact.id],
        "target_tab": "Notebooks",
        "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
        "detail": detail,
    }


def first_native_notebook_artifact_for_action(
    db: Session,
    *,
    project_id: str,
    artifact_ids: list[str],
) -> Artifact | None:
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            continue
        if research_plan_artifact_is_native_marimo_source(artifact):
            return artifact
    return None


def normalize_agent_chat_notebook_update_message(
    payload: dict[str, Any],
    assistant_message: str,
    *,
    japanese: bool,
) -> str:
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "notebook_artifact_update":
        return assistant_message
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    has_legacy_preview_reference = any(
        isinstance(brief.get(key), str) and bool(str(brief.get(key) or "").strip())
        for key in ("html_artifact_id", "preview_artifact_id")
    )
    status = str(brief.get("status") or intent.get("status") or "").strip()
    if not has_legacy_preview_reference and status != "preview_failed":
        return assistant_message
    if status == "preview_failed":
        return (
            "分析ノートブックのソースは保存されていますが、marimoで開くには修正が必要です。"
            if japanese
            else "The analysis notebook source is saved, but it needs a fix before marimo can open it."
        )
    return (
        "分析ノートブックを保存しました。ここからmarimoで開けます。"
        if japanese
        else "The analysis notebook is saved and can be opened from here with marimo."
    )


def normalize_agent_chat_attention_message(
    payload: dict[str, Any],
    assistant_message: str,
    *,
    japanese: bool,
) -> str:
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "agent_attention_event":
        return assistant_message
    message_kind = str(intent.get("message_kind") or "").strip()
    if not message_kind:
        return assistant_message
    if message_kind == "research_plan_human_attention_requested" and assistant_message.strip():
        return assistant_message
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    details = brief.get("details") if isinstance(brief.get("details"), dict) else {}
    return attention_chat_message(message_kind, details=details, japanese=japanese)


def normalize_agent_chat_experiment_registration_message(
    payload: dict[str, Any],
    assistant_message: str,
    *,
    japanese: bool,
) -> str:
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "experiment_results_registration_failed":
        return assistant_message
    if japanese:
        return (
            "モデル評価結果はまだLeaderboardに反映していません。"
            "表示中の順位表はそのまま保持し、分析は続いています。"
        )
    return (
        "The model evaluation results have not been added to the Leaderboard yet. "
        "The visible ranking is unchanged, and the analysis is continuing."
    )


def normalize_agent_chat_native_marimo_runtime_message(
    payload: dict[str, Any],
    assistant_message: str,
    *,
    japanese: bool,
) -> str:
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") not in {"native_marimo_runtime_failed", "native_marimo_open_failed"}:
        return assistant_message
    if intent.get("type") == "native_marimo_open_failed" and japanese:
        return (
            "このNotebookをmarimoで開けませんでした。Notebook sourceは保存済みです。"
            "未完成の表示にはせず、Notebook/runtimeの修正対象として扱います。"
        )
    if intent.get("type") == "native_marimo_open_failed":
        return (
            "This notebook could not be opened in marimo. The notebook source is still saved. "
            "It is treated as a notebook/runtime repair target rather than shown as finished."
        )
    if japanese:
        return (
            "Notebookはnative marimoで開きましたが、実行中にエラーが出ています。"
            "このNotebook sourceを修正対象として扱い、Codexに修正できる形で詳細を渡しています。"
        )
    return (
        "The notebook opened in native marimo, but it hit a runtime error. "
        "The source notebook is marked for repair, and Codex has the details it needs to fix it."
    )


def normalize_agent_chat_worker_events(
    payload: dict[str, Any],
    *,
    japanese: bool,
) -> list[Any]:
    worker_events = payload.get("worker_events") if isinstance(payload.get("worker_events"), list) else []
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") not in {"native_marimo_runtime_failed", "native_marimo_open_failed"}:
        return worker_events
    detail = (
        "Notebook sourceの修正が必要です。詳細はRawと修正対象briefに保存しています。"
        if japanese
        else "The notebook source needs a repair. Details are saved in Raw and the repair brief."
    )
    title = "Notebookを開けません" if japanese else "Notebook open failed"
    normalized: list[Any] = []
    for event in worker_events:
        if not isinstance(event, dict):
            normalized.append(event)
            continue
        human_description = event.get("human_description") if isinstance(event.get("human_description"), dict) else {}
        normalized.append(
            {
                **event,
                "detail": detail,
                "human_description": {
                    **human_description,
                    "title": human_description.get("title") or title,
                    "summary": detail,
                },
            }
        )
    return normalized


def normalize_agent_chat_response_brief(payload: dict[str, Any]) -> dict[str, Any] | None:
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else None
    if brief is None:
        return None
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "notebook_artifact_update":
        return brief
    normalized = {
        key: value
        for key, value in brief.items()
        if key not in {"html_artifact_id", "preview_artifact_id"}
    }
    notebook_artifact_id = normalized.get("notebook_artifact_id")
    if isinstance(notebook_artifact_id, str) and notebook_artifact_id.strip():
        normalized.setdefault("source_artifact_id", notebook_artifact_id)
    return normalized


@router.get("/api/projects/{project_id}/agent-chat/history", response_model=list[AgentChatHistoryTurnRead])
def list_agent_chat_history(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    project = require_project(db, project_id)
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    plan_actions, plan_next_focus = chat_update_actions_from_research_plan_evidence(
        db,
        project=project,
        japanese=japanese,
    )
    registered_output_actions, registered_output_next_focus = chat_update_actions_from_registered_output_evidence(
        db,
        project=project,
        japanese=japanese,
    )
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(60)
        ).all()
    )
    turns: list[dict[str, Any]] = []
    main_session_update_turns: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    for artifact in reversed(artifacts):
        path = artifact_primary_path(artifact)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = normalize_agent_chat_history_payload(artifact, payload, japanese=japanese)
        if not isinstance(payload, dict) or payload.get("schema_version") != "agent_chat_turn.v1":
            continue
        if agent_attention_event_is_resolved(db, project_id=project_id, payload=payload):
            continue
        metadata = loads_json(artifact.metadata_json, {})
        assistant_message = str(payload.get("assistant_message") or "")
        intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
        if intent.get("type") == "autonomous_agent_progress_report":
            assistant_message = chat_update_message_from_text(assistant_message)
        assistant_message = normalize_agent_chat_notebook_update_message(
            payload,
            assistant_message,
            japanese=japanese,
        )
        assistant_message = normalize_agent_chat_attention_message(
            payload,
            assistant_message,
            japanese=japanese,
        )
        assistant_message = normalize_agent_chat_experiment_registration_message(
            payload,
            assistant_message,
            japanese=japanese,
        )
        assistant_message = normalize_agent_chat_native_marimo_runtime_message(
            payload,
            assistant_message,
            japanese=japanese,
        )
        if isinstance(metadata.get("job_id"), str):
            seen_job_ids.add(metadata["job_id"])
        actions = normalize_agent_chat_navigation_actions(
            payload.get("actions") if isinstance(payload.get("actions"), list) else [],
            db=db,
            project_id=project_id,
            japanese=japanese,
        )
        next_focus = normalize_agent_chat_navigation_focus(
            payload.get("next_focus") if isinstance(payload.get("next_focus"), dict) else {}
        )
        next_focus = normalize_agent_chat_notebook_action_artifact(
            db,
            project_id=project_id,
            action=next_focus,
            japanese=japanese,
        )
        turn = {
            "schema_version": "agent_chat_turn.v1",
            "project_id": project_id,
            "user_message": str(payload.get("user_message") or ""),
            "assistant_message": assistant_message,
            "intent": intent,
            "actions": actions,
            "action_summary": payload.get("action_summary") if isinstance(payload.get("action_summary"), dict) else {},
            "response_brief": normalize_agent_chat_response_brief(payload),
            "response_composer": payload.get("response_composer") if isinstance(payload.get("response_composer"), dict) else None,
            "worker_events": normalize_agent_chat_worker_events(payload, japanese=japanese),
            "token_usage": payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {},
            "next_focus": next_focus,
            "artifact_id": artifact.id,
            "job_id": metadata.get("job_id") if isinstance(metadata.get("job_id"), str) else None,
            "created_at": artifact.created_at.isoformat(),
        }
        if metadata.get("source") == "main_codex_session_chat_update" and isinstance(metadata.get("agent_session_id"), str):
            turn["agent_session_id"] = metadata["agent_session_id"]
            if plan_actions:
                turn["actions"] = plan_actions
                response_brief = turn["response_brief"] if isinstance(turn["response_brief"], dict) else {}
                turn["response_brief"] = {
                    **response_brief,
                    "linked_action_count": len(plan_actions),
                    "linked_action_source": "research_plan_completion_evidence",
                    "linked_actions_refreshed_for_display": True,
                }
                turn["next_focus"] = plan_next_focus
            main_session_update_turns.append(turn)
        else:
            turns.append(turn)
    control_jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.job_type.in_(["start_autonomous_loop", "stop_autonomous_loop"]),
            )
            .order_by(Job.created_at.desc())
            .limit(30)
        ).all()
    )
    for job in reversed(control_jobs):
        if job.id in seen_job_ids:
            continue
        output = loads_json(job.output_json, {})
        assistant_message = output.get("assistant_message")
        if not isinstance(assistant_message, str) or not assistant_message.strip():
            continue
        response_locale = output.get("response_locale") if isinstance(output.get("response_locale"), str) else "en-US"
        started = job.job_type == "start_autonomous_loop"
        user_message = "Agent loopを開始" if locale_is_japanese(response_locale) and started else "Start agent loop"
        if not started:
            user_message = "Agent loopを停止" if locale_is_japanese(response_locale) else "Stop agent loop"
        turns.append(
            {
                "schema_version": "agent_chat_turn.v1",
                "project_id": project_id,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "intent": {
                    "type": "agent_loop_control",
                    "source": "autonomy_power_button",
                    "routing_policy": "explicit_ui_control_not_natural_language_routing",
                },
                "actions": [],
                "action_summary": {},
                "response_brief": {
                    "source": "autonomy_control_backfill",
                    "response_locale": response_locale,
                    "created_job_ids": output.get("created_job_ids") if isinstance(output.get("created_job_ids"), list) else [],
                    "status": output.get("status"),
                },
                "response_composer": {
                    "mode": "autonomy_control_backfill",
                    "status": "reconstructed_from_job_output",
                },
                "worker_events": output.get("worker_events") if isinstance(output.get("worker_events"), list) else [],
                "token_usage": output.get("token_usage") if isinstance(output.get("token_usage"), dict) else {},
                "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent Activity"},
                "artifact_id": f"job_history_{job.id}",
                "job_id": job.id,
                "created_at": job.created_at.isoformat(),
            }
        )
    chat_jobs = list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project_id, Job.job_type == "agent_chat_turn")
            .order_by(Job.created_at.desc())
            .limit(30)
        ).all()
    )
    paired_update_ids: set[str] = set()
    for job in reversed(chat_jobs):
        if job.id in seen_job_ids:
            continue
        payload = loads_json(job.input_json, {})
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        paired_update = matching_main_session_update_for_chat_job(
            job,
            payload,
            main_session_update_turns,
            already_paired_update_ids=paired_update_ids,
        )
        if paired_update is not None:
            turns.append(agent_chat_turn_from_main_session_update(db, project_id, job, payload, paired_update))
            progress_artifact_id = paired_update.get("artifact_id")
            if isinstance(progress_artifact_id, str):
                paired_update_ids.add(progress_artifact_id)
        else:
            turns.append(pending_agent_chat_turn_from_job(db, project_id, job, payload))
    latest_unlinked_update = next((turn for turn in reversed(main_session_update_turns) if not turn.get("actions")), None)
    linked_actions = merge_agent_chat_actions(plan_actions, registered_output_actions, limit=3)
    linked_next_focus = registered_output_next_focus or plan_next_focus
    if latest_unlinked_update is not None and linked_actions:
        latest_unlinked_update["actions"] = linked_actions
        response_brief = latest_unlinked_update["response_brief"] if isinstance(latest_unlinked_update["response_brief"], dict) else {}
        latest_unlinked_update["response_brief"] = {
            **response_brief,
            "linked_action_count": len(linked_actions),
            "linked_action_source": "registered_output_evidence",
        }
        latest_unlinked_update["next_focus"] = linked_next_focus
    paired_update_ids.update({
        str(turn.get("paired_progress_artifact_id"))
        for turn in turns
        if isinstance(turn.get("paired_progress_artifact_id"), str)
    })
    turns.extend(
        turn for turn in main_session_update_turns if isinstance(turn.get("artifact_id"), str) and turn["artifact_id"] not in paired_update_ids
    )
    return compact_agent_chat_history_turns(turns, locale=response_locale, db=db, project_id=project_id)


def normalize_agent_chat_history_payload(artifact: Artifact, payload: Any, *, japanese: bool) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") == "agent_chat_turn.v1":
        return payload
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    if brief.get("schema_version") != "experiment_results_registered.v1":
        return None
    run_ids = [str(item) for item in brief.get("run_ids", []) if isinstance(item, str) and item.strip()]
    assistant_message = str(payload.get("assistant_message") or "").strip()
    if not assistant_message:
        assistant_message = (
            f"{len(run_ids)}件のモデル評価をLeaderboardに登録しました。"
            if japanese
            else f"Registered {len(run_ids)} model evaluation(s) on the leaderboard."
        )
    return {
        "schema_version": "agent_chat_turn.v1",
        "project_id": artifact.project_id or str(brief.get("project_id") or ""),
        "user_message": str(payload.get("user_message") or ""),
        "assistant_message": assistant_message,
        "intent": {
            "type": "experiment_results_registered",
            "source": "main_agent_session_workspace",
            "status": "ready",
        },
        "actions": payload.get("actions") if isinstance(payload.get("actions"), list) else [],
        "action_summary": payload.get("action_summary") if isinstance(payload.get("action_summary"), dict) else {},
        "response_brief": brief,
        "response_composer": payload.get("response_composer")
        if isinstance(payload.get("response_composer"), dict)
        else {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": payload.get("worker_events") if isinstance(payload.get("worker_events"), list) else [],
        "token_usage": payload.get("token_usage")
        if isinstance(payload.get("token_usage"), dict)
        else {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": payload.get("next_focus")
        if isinstance(payload.get("next_focus"), dict)
        else {
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "label": "リーダーボード" if japanese else "Leaderboard",
        },
    }


def merge_agent_chat_actions(*action_groups: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for group in action_groups:
        for action in group:
            if not isinstance(action, dict):
                continue
            key = (
                str(action.get("target_tab") or ""),
                str(action.get("target_anchor") or ""),
                str(action.get("artifact_id") or ""),
                str(action.get("label") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(action)
            if len(merged) >= limit:
                return merged
    return merged


def chat_update_actions_from_registered_output_evidence(
    db: Session,
    *,
    project: Project,
    japanese: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    actions: list[dict[str, Any]] = []
    latest_notebooks = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project.id,
                Artifact.asset_type.in_(("analysis_notebook", "marimo_notebook")),
            )
            .order_by(Artifact.created_at.desc(), Artifact.version.desc())
            .limit(12)
        ).all()
    )
    notebook_ids: list[str] = []
    for artifact in latest_notebooks:
        if research_plan_artifact_is_native_marimo_source(artifact):
            notebook_ids.append(artifact.id)
        if len(notebook_ids) >= 3:
            break
    if notebook_ids:
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "ノートブックを開く" if japanese else "Open notebooks",
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "artifact_id": notebook_ids[0],
                "artifact_ids": notebook_ids,
                "detail": (
                    "登録済みのmarimo notebookをnative marimoで開きます。"
                    if japanese
                    else "Open the registered marimo notebooks with native marimo."
                ),
            }
        )
    run_count = db.scalar(
        select(func.count())
        .select_from(ExperimentRun)
        .where(ExperimentRun.project_id == project.id, ExperimentRun.status == "succeeded")
    )
    if int(run_count or 0) > 0:
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "リーダーボードを見る" if japanese else "Open leaderboard",
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
                "detail": (
                    f"登録済みのモデル評価 {int(run_count or 0)} 件を順位表で確認できます。"
                    if japanese
                    else f"Review {int(run_count or 0)} registered model evaluation(s) in the ranked table."
                ),
            }
        )
    latest_research = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project.id, Artifact.asset_type == "research_findings_report")
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    if latest_research is not None:
        metadata = loads_json(latest_research.metadata_json, {})
        topic = metadata.get("topic") if isinstance(metadata.get("topic"), str) else None
        actions.append(
            {
                "type": "open_artifact",
                "status": "ready",
                "label": "保存済みの関連調査を開く" if japanese else "Open saved related research",
                "target_tab": "Assets",
                "target_anchor": "assets-artifact-preview",
                "artifact_id": latest_research.id,
                "artifact_ids": [latest_research.id],
                "detail": (
                    f"登録済みの従来知見調査を確認できます。{topic}"
                    if japanese and topic
                    else "登録済みの従来知見調査を確認できます。"
                    if japanese
                    else f"Open the registered prior-knowledge research. {topic}"
                    if topic
                    else "Open the registered prior-knowledge research."
                ),
            }
        )
    if not actions:
        return [], None
    next_focus = actions[-1]
    return actions, {
        "target_tab": next_focus.get("target_tab"),
        "target_anchor": next_focus.get("target_anchor"),
        "artifact_id": next_focus.get("artifact_id"),
        "artifact_ids": next_focus.get("artifact_ids", []),
        "label": next_focus.get("label"),
    }


def matching_main_session_update_for_chat_job(
    job: Job,
    payload: dict[str, Any],
    updates: list[dict[str, Any]],
    *,
    already_paired_update_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    delivered_session_id = payload.get("delivered_agent_session_id")
    if not isinstance(delivered_session_id, str) or not delivered_session_id.strip():
        return None
    paired = already_paired_update_ids or set()
    output = loads_json(job.output_json, {})
    progress_artifact_id = output.get("progress_artifact_id")
    if isinstance(progress_artifact_id, str) and progress_artifact_id.strip() and progress_artifact_id not in paired:
        for update in updates:
            if update.get("agent_session_id") == delivered_session_id and update.get("artifact_id") == progress_artifact_id:
                return update
        return None
    candidates = [
        update
        for update in updates
        if update.get("agent_session_id") == delivered_session_id
        and agent_chat_update_is_not_older_than_job(update, job)
        and (not isinstance(update.get("artifact_id"), str) or update["artifact_id"] not in paired)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda update: parse_api_datetime(update.get("created_at")) or datetime.max.replace(tzinfo=timezone.utc),
    )[0]


def agent_chat_update_is_not_older_than_job(update: dict[str, Any], job: Job) -> bool:
    update_created_at = parse_api_datetime(update.get("created_at"))
    job_created_at = parse_api_datetime(job.created_at)
    if update_created_at is None or job_created_at is None:
        return False
    return update_created_at >= job_created_at


def agent_chat_turn_from_main_session_update(
    db: Session,
    project_id: str,
    job: Job,
    payload: dict[str, Any],
    update_turn: dict[str, Any],
) -> dict[str, Any]:
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else "en-US"
    delivered_session_id = payload.get("delivered_agent_session_id")
    delivered_session = db.get(AgentSession, delivered_session_id) if isinstance(delivered_session_id, str) else None
    return {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project_id,
        "user_message": str(payload["message"]),
        "assistant_message": str(update_turn.get("assistant_message") or ""),
        "intent": {
            "type": "agent_conversation",
            "source": "main_codex_session_chat_update",
            "routing_policy": "codex_authored_human_update_paired_to_user_instruction",
        },
        "actions": update_turn.get("actions") if isinstance(update_turn.get("actions"), list) else [],
        "action_summary": update_turn.get("action_summary") if isinstance(update_turn.get("action_summary"), dict) else {},
        "response_brief": {
            "schema_version": "agent_chat_main_session_update_pair.v1",
            "response_locale": locale,
            "job_id": job.id,
            "job_status": job.status,
            "delivered_agent_session_id": delivered_session_id if isinstance(delivered_session_id, str) else None,
            "agent_transcript_event_id": payload.get("agent_transcript_event_id")
            if isinstance(payload.get("agent_transcript_event_id"), str)
            else None,
            "agent_transcript_event_index": payload.get("agent_transcript_event_index")
            if isinstance(payload.get("agent_transcript_event_index"), int)
            else None,
            "progress_update_requested_event_id": payload.get("progress_update_requested_event_id")
            if isinstance(payload.get("progress_update_requested_event_id"), str)
            else None,
            "progress_artifact_id": update_turn.get("artifact_id") if isinstance(update_turn.get("artifact_id"), str) else None,
            "agent_session_observation": agent_session_observation_for_chat_wait(db=db, session=delivered_session)
            if delivered_session is not None
            else None,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session",
            "status": "codex_authored",
        },
        "worker_events": update_turn.get("worker_events") if isinstance(update_turn.get("worker_events"), list) else [],
        "token_usage": update_turn.get("token_usage")
        if isinstance(update_turn.get("token_usage"), dict)
        else {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
        "next_focus": update_turn.get("next_focus")
        if isinstance(update_turn.get("next_focus"), dict)
        else {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"},
        "artifact_id": f"job_answered_by_{update_turn.get('artifact_id')}",
        "job_id": job.id,
        "paired_progress_artifact_id": update_turn.get("artifact_id") if isinstance(update_turn.get("artifact_id"), str) else None,
        "created_at": str(update_turn.get("created_at") or job.created_at.isoformat()),
    }


def pending_agent_chat_turn_from_job(db: Session, project_id: str, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    output = loads_json(job.output_json, {})
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else "en-US"
    japanese = locale_is_japanese(locale)
    delivered_session_id = payload.get("delivered_agent_session_id")
    delivered_to_running_codex = isinstance(delivered_session_id, str) and bool(delivered_session_id.strip())
    delivered_session = db.get(AgentSession, delivered_session_id) if delivered_to_running_codex else None
    wait_state = agent_chat_wait_state(
        job,
        delivered_to_running_codex=delivered_to_running_codex,
        locale=locale,
    )
    if job.status in {"failed", "cancelled", "timed_out"}:
        error_message = job.error_message or str(output.get("error_message") or "")
        assistant_message = (
            f"応答生成が完了しませんでした: {error_message}" if japanese else f"Response did not complete: {error_message}"
        )
    else:
        assistant_message = wait_state["assistant_message"]
    return {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project_id,
        "user_message": str(payload["message"]),
        "assistant_message": assistant_message,
        "intent": {
            "type": "agent_conversation",
            "source": "main_agent_session_inbox" if delivered_to_running_codex else "agent_chat_turn_job",
        },
        "actions": [],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_chat_job_status.v1",
            "response_locale": locale,
            "job_id": job.id,
            "status": job.status,
            "error_message": job.error_message,
            "delivered_agent_session_id": delivered_session_id if delivered_to_running_codex else None,
            "agent_session_observation": agent_session_observation_for_chat_wait(db=db, session=delivered_session)
            if delivered_session is not None
            else None,
            "agent_transcript_event_id": payload.get("agent_transcript_event_id")
            if isinstance(payload.get("agent_transcript_event_id"), str)
            else None,
            "agent_transcript_event_index": payload.get("agent_transcript_event_index")
            if isinstance(payload.get("agent_transcript_event_index"), int)
            else None,
            "progress_update_requested_event_id": payload.get("progress_update_requested_event_id")
            if isinstance(payload.get("progress_update_requested_event_id"), str)
            else None,
            "wait_state": wait_state["brief"],
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session" if delivered_to_running_codex else "queued_worker",
            "status": job.status,
        },
        "worker_events": output.get("worker_events") if isinstance(output.get("worker_events"), list) else [],
        "token_usage": output.get("token_usage")
        if isinstance(output.get("token_usage"), dict)
        else {"source": "pending_response", "is_estimate": True, "series": []},
        "next_focus": {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent Chat"},
        "artifact_id": f"job_pending_{job.id}",
        "job_id": job.id,
        "created_at": job.created_at.isoformat(),
    }


def compact_agent_chat_history_turns(
    turns: list[dict[str, Any]],
    *,
    locale: str = "en-US",
    max_turns: int = 60,
    max_autonomous_progress_turns: int = 12,
    db: Session | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    ordered = dedupe_consecutive_identical_agent_chat_turns(
        dedupe_repeated_experiment_registration_failure_turns(
            dedupe_repeated_experiment_registration_turns(
                coalesce_adjacent_notebook_update_turns(
                    sorted(turns, key=lambda turn: str(turn.get("created_at") or "")),
                    locale=locale,
                    db=db,
                    project_id=project_id,
                )
            )
        )
    )
    selected_reversed: list[dict[str, Any]] = []
    progress_count = 0
    for turn in reversed(ordered):
        intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
        is_autonomous_progress = intent.get("type") == "autonomous_agent_progress_report"
        if is_autonomous_progress:
            if progress_count >= max_autonomous_progress_turns:
                continue
            progress_count += 1
        selected_reversed.append(turn)
        if len(selected_reversed) >= max_turns:
            break
    return list(reversed(selected_reversed))


def agent_attention_event_is_resolved(db: Session, *, project_id: str, payload: dict[str, Any]) -> bool:
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    if intent.get("type") != "agent_attention_event":
        return False
    if intent.get("message_kind") != "notebook_context_registration_needed":
        return False
    brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
    details = brief.get("details") if isinstance(brief.get("details"), dict) else {}
    notebook_artifact_ids = [
        item.strip()
        for item in details.get("notebook_artifact_ids", [])
        if isinstance(item, str) and item.strip()
    ]
    if not notebook_artifact_ids:
        return False
    for artifact_id in notebook_artifact_ids:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            return False
        if not notebook_artifact_has_declared_context(db, artifact=artifact, include_sibling_versions=True):
            return False
    return True


def coalesce_adjacent_notebook_update_turns(
    turns: list[dict[str, Any]],
    *,
    locale: str,
    db: Session | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_kind: str | None = None

    def flush_pending() -> None:
        nonlocal pending, pending_kind
        if not pending:
            return
        if len(pending) > 1 and pending_kind == "notebook_update":
            compacted.append(group_notebook_update_turns(pending, locale=locale, db=db, project_id=project_id))
        elif len(pending) > 1 and pending_kind == "native_marimo_runtime_failed":
            compacted.append(group_native_marimo_runtime_failure_turns(pending, locale=locale))
        elif len(pending) > 1 and pending_kind == "experiment_registration":
            compacted.extend(dedupe_experiment_registration_turns(pending))
        elif len(pending) > 1 and pending_kind == "experiment_registration_failure":
            compacted.extend(dedupe_repeated_experiment_registration_failure_turns(pending))
        else:
            compacted.append(pending[0])
        pending = []
        pending_kind = None

    for turn in turns:
        turn_kind = agent_chat_turn_compaction_kind(turn)
        if turn_kind:
            if pending_kind is not None and pending_kind != turn_kind:
                flush_pending()
            pending_kind = turn_kind
            pending.append(turn)
            continue
        flush_pending()
        compacted.append(turn)
    flush_pending()
    return compacted


def agent_chat_turn_compaction_kind(turn: dict[str, Any]) -> str | None:
    if agent_chat_turn_is_notebook_update(turn):
        return "notebook_update"
    if agent_chat_turn_is_native_marimo_runtime_failure(turn):
        return "native_marimo_runtime_failed"
    if agent_chat_turn_is_experiment_registration(turn):
        return "experiment_registration"
    if agent_chat_turn_is_experiment_registration_failure(turn):
        return "experiment_registration_failure"
    return None


def agent_chat_turn_is_notebook_update(turn: dict[str, Any]) -> bool:
    intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
    if intent.get("type") != "notebook_artifact_update":
        return False
    brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
    return isinstance(brief.get("notebook_artifact_id"), str) and bool(brief.get("notebook_artifact_id"))


def agent_chat_turn_is_native_marimo_runtime_failure(turn: dict[str, Any]) -> bool:
    intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
    if intent.get("type") != "native_marimo_runtime_failed":
        return False
    brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
    return isinstance(brief.get("notebook_artifact_id"), str) and bool(brief.get("notebook_artifact_id"))


def agent_chat_turn_is_experiment_registration(turn: dict[str, Any]) -> bool:
    intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
    return intent.get("type") == "experiment_results_registered"


def agent_chat_turn_is_experiment_registration_failure(turn: dict[str, Any]) -> bool:
    intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
    return intent.get("type") == "experiment_results_registration_failed"


def agent_chat_identical_assistant_turn_key(turn: dict[str, Any]) -> str | None:
    user_message = str(turn.get("user_message") or "").strip()
    assistant_message = str(turn.get("assistant_message") or "").strip()
    if user_message or not assistant_message:
        return None
    intent = turn.get("intent") if isinstance(turn.get("intent"), dict) else {}
    actions = turn.get("actions") if isinstance(turn.get("actions"), list) else []
    action_key = [
        {
            "type": str(action.get("type") or ""),
            "status": str(action.get("status") or ""),
            "label": str(action.get("label") or ""),
            "target_tab": str(action.get("target_tab") or ""),
            "target_anchor": str(action.get("target_anchor") or ""),
            "artifact_id": str(action.get("artifact_id") or ""),
            "run_id": str(action.get("run_id") or ""),
        }
        for action in actions
        if isinstance(action, dict)
    ]
    return json.dumps(
        {
            "assistant_message": assistant_message,
            "intent_type": str(intent.get("type") or ""),
            "intent_status": str(intent.get("status") or ""),
            "message_kind": str(intent.get("message_kind") or ""),
            "actions": action_key,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def dedupe_consecutive_identical_agent_chat_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    previous_key: str | None = None
    previous_index: int | None = None
    for turn in turns:
        key = agent_chat_identical_assistant_turn_key(turn)
        if key is not None and key == previous_key and previous_index is not None:
            previous_turn = deduped[previous_index]
            latest = dict(turn)
            previous_actions = previous_turn.get("actions") if isinstance(previous_turn.get("actions"), list) else []
            latest_actions = latest.get("actions") if isinstance(latest.get("actions"), list) else []
            latest["actions"] = merge_agent_chat_actions(latest_actions, previous_actions, limit=6)
            deduped[previous_index] = latest
            continue
        deduped.append(turn)
        if key is None:
            previous_key = None
            previous_index = None
        else:
            previous_key = key
            previous_index = len(deduped) - 1
    return deduped


def experiment_registration_turn_key(turn: dict[str, Any]) -> str:
    brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
    run_ids = brief.get("run_ids")
    if not isinstance(run_ids, list):
        surfaces = turn.get("visible_surfaces") if isinstance(turn.get("visible_surfaces"), dict) else {}
        leaderboard = surfaces.get("leaderboard") if isinstance(surfaces.get("leaderboard"), dict) else {}
        run_ids = leaderboard.get("run_ids")
    cleaned_run_ids = sorted({str(item).strip() for item in run_ids if isinstance(item, str) and item.strip()}) if isinstance(run_ids, list) else []
    if cleaned_run_ids:
        return json.dumps(
            {
                "run_ids": cleaned_run_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    result_set_fingerprint = brief.get("result_set_fingerprint")
    if isinstance(result_set_fingerprint, str) and result_set_fingerprint.strip():
        return f"result-set:{result_set_fingerprint.strip()}"
    fingerprint = brief.get("notification_fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return f"notification:{fingerprint.strip()}"
    return "message:" + str(turn.get("assistant_message") or "").strip()


def dedupe_experiment_registration_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    for turn in turns:
        key = experiment_registration_turn_key(turn)
        if key not in by_key:
            order.append(key)
        by_key[key] = turn
    return [by_key[key] for key in order]


def dedupe_repeated_experiment_registration_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_index_by_key: dict[str, int] = {}
    merged_actions_by_key: dict[str, list[dict[str, Any]]] = {}
    latest_turn_by_key: dict[str, dict[str, Any]] = {}
    for index, turn in enumerate(turns):
        if not agent_chat_turn_is_experiment_registration(turn):
            continue
        key = experiment_registration_turn_key(turn)
        actions = turn.get("actions") if isinstance(turn.get("actions"), list) else []
        merged_actions_by_key[key] = merge_agent_chat_actions(
            actions,
            merged_actions_by_key.get(key, []),
            limit=6,
        )
        latest_index_by_key[key] = index
        latest_turn_by_key[key] = turn

    if not latest_index_by_key:
        return turns

    deduped: list[dict[str, Any]] = []
    for index, turn in enumerate(turns):
        if not agent_chat_turn_is_experiment_registration(turn):
            deduped.append(turn)
            continue
        key = experiment_registration_turn_key(turn)
        if latest_index_by_key.get(key) != index:
            continue
        latest = dict(latest_turn_by_key[key])
        latest["actions"] = merged_actions_by_key.get(key, latest.get("actions", []))
        deduped.append(latest)
    return deduped


def experiment_registration_failure_turn_key(turn: dict[str, Any]) -> str:
    brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
    fingerprint = brief.get("failure_fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return f"failure:{fingerprint.strip()}"
    operation = brief.get("operation")
    error_type = brief.get("error_type")
    error_message = brief.get("error_message")
    if all(isinstance(value, str) and value.strip() for value in [operation, error_type, error_message]):
        payload = {
            "operation": str(operation),
            "error_type": str(error_type),
            "error_message": str(error_message),
        }
        return "failure:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    return "message:" + str(turn.get("assistant_message") or "").strip()


def dedupe_repeated_experiment_registration_failure_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_index_by_key: dict[str, int] = {}
    latest_turn_by_key: dict[str, dict[str, Any]] = {}
    for index, turn in enumerate(turns):
        if not agent_chat_turn_is_experiment_registration_failure(turn):
            continue
        key = experiment_registration_failure_turn_key(turn)
        latest_index_by_key[key] = index
        latest_turn_by_key[key] = turn
    if not latest_index_by_key:
        return turns
    deduped: list[dict[str, Any]] = []
    for index, turn in enumerate(turns):
        if not agent_chat_turn_is_experiment_registration_failure(turn):
            deduped.append(turn)
            continue
        key = experiment_registration_failure_turn_key(turn)
        if latest_index_by_key.get(key) == index:
            deduped.append(latest_turn_by_key[key])
    return deduped


def group_notebook_update_turns(
    turns: list[dict[str, Any]],
    *,
    locale: str,
    db: Session | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    first = turns[0]
    last = turns[-1]
    japanese = locale_is_japanese(locale)
    action_order: list[str] = []
    actions_by_key: dict[str, dict[str, Any]] = {}
    notebook_artifact_ids: list[str] = []
    seen_action_keys: set[str] = set()
    source_artifact_ids: list[str] = []
    source_event_indexes: list[int] = []
    for turn in turns:
        artifact_id = turn.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip():
            source_artifact_ids.append(artifact_id)
        brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
        notebook_artifact_id = brief.get("notebook_artifact_id")
        if isinstance(notebook_artifact_id, str) and notebook_artifact_id.strip() and notebook_artifact_id not in notebook_artifact_ids:
            notebook_artifact_ids.append(notebook_artifact_id)
        source_event = brief.get("source_transcript_event") if isinstance(brief.get("source_transcript_event"), dict) else {}
        event_index = source_event.get("event_index")
        if isinstance(event_index, int):
            source_event_indexes.append(event_index)
        for action in turn.get("actions") if isinstance(turn.get("actions"), list) else []:
            if not isinstance(action, dict):
                continue
            action_key = str(action.get("artifact_id") or action.get("label") or len(action_order))
            if action_key not in seen_action_keys:
                seen_action_keys.add(action_key)
                action_order.append(action_key)
            actions_by_key[action_key] = action
    actions = [actions_by_key[key] for key in action_order if key in actions_by_key]
    notebook_artifact_ids = representative_notebook_artifact_ids(
        db,
        project_id=project_id,
        artifact_ids=notebook_artifact_ids,
    )
    if db is not None and project_id and notebook_artifact_ids:
        allowed_artifact_ids = set(notebook_artifact_ids)
        actions = [
            action
            for action in actions
            if not isinstance(action.get("artifact_id"), str) or action.get("artifact_id") in allowed_artifact_ids
        ]
    count = len(notebook_artifact_ids) or len(turns)
    if count == 1 and len(turns) > 1:
        assistant_message = (
            "分析ノートブックを更新しました。最新版をここからmarimoで開けます。"
            if japanese
            else "The analysis notebook was updated. Open the latest version from here with marimo."
        )
    else:
        assistant_message = (
            f"分析ノートブック{count}件の最新版をここからmarimoで開けます。"
            if japanese
            else f"The latest version of {count} analysis notebook(s) can be opened from here with marimo."
        )
    grouped = {
        **last,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            **(last.get("intent") if isinstance(last.get("intent"), dict) else {}),
            "type": "notebook_artifact_update",
            "grouped": True,
            "grouped_turn_count": len(turns),
        },
        "actions": actions,
        "response_brief": {
            "schema_version": "notebook_artifact_update_group.v1",
            "status": "source_saved",
            "grouped_turn_count": len(turns),
            "notebook_count": count,
            "notebook_artifact_ids": notebook_artifact_ids,
            "source_artifact_ids": source_artifact_ids,
            "source_transcript_event_indexes": source_event_indexes,
        },
        "artifact_id": f"notebook_update_group_{source_artifact_ids[0] if source_artifact_ids else 'first'}_{source_artifact_ids[-1] if source_artifact_ids else 'last'}",
        "created_at": last.get("created_at") or first.get("created_at"),
    }
    if actions:
        grouped["next_focus"] = actions[-1]
    return grouped


def group_native_marimo_runtime_failure_turns(
    turns: list[dict[str, Any]],
    *,
    locale: str,
) -> dict[str, Any]:
    first = turns[0]
    last = turns[-1]
    japanese = locale_is_japanese(locale)
    notebook_artifact_ids: list[str] = []
    source_artifact_ids: list[str] = []
    actions: list[dict[str, Any]] = []
    seen_action_keys: set[str] = set()
    latest_error_summary = ""
    for turn in turns:
        artifact_id = turn.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip():
            source_artifact_ids.append(artifact_id)
        brief = turn.get("response_brief") if isinstance(turn.get("response_brief"), dict) else {}
        notebook_artifact_id = brief.get("notebook_artifact_id")
        if isinstance(notebook_artifact_id, str) and notebook_artifact_id.strip() and notebook_artifact_id not in notebook_artifact_ids:
            notebook_artifact_ids.append(notebook_artifact_id)
        error_summary = brief.get("error_summary")
        if isinstance(error_summary, str) and error_summary.strip():
            latest_error_summary = error_summary.strip()
        for action in turn.get("actions") if isinstance(turn.get("actions"), list) else []:
            if not isinstance(action, dict):
                continue
            action_key = str(action.get("artifact_id") or action.get("label") or len(actions))
            if action_key in seen_action_keys:
                continue
            seen_action_keys.add(action_key)
            actions.append(action)
    if len(notebook_artifact_ids) == 1:
        assistant_message = (
            "同じNotebookでruntime errorが続いています。最新版をここから確認できます。"
            if japanese
            else "The same notebook is still reporting runtime errors. Open the latest failure from here."
        )
    else:
        count = len(notebook_artifact_ids) or len(turns)
        assistant_message = (
            f"Notebook {count}件でruntime errorが出ています。ここから修正対象を確認できます。"
            if japanese
            else f"{count} notebook(s) are reporting runtime errors. Open the repair targets from here."
        )
    if latest_error_summary:
        assistant_message = f"{assistant_message}\n\n{latest_error_summary}"
    grouped = {
        **last,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            **(last.get("intent") if isinstance(last.get("intent"), dict) else {}),
            "type": "native_marimo_runtime_failed",
            "grouped": True,
            "grouped_turn_count": len(turns),
        },
        "actions": actions,
        "response_brief": {
            "schema_version": "native_marimo_runtime_failed_group.v1",
            "status": "needs_attention",
            "grouped_turn_count": len(turns),
            "notebook_count": len(notebook_artifact_ids) or len(turns),
            "notebook_artifact_ids": notebook_artifact_ids,
            "source_artifact_ids": source_artifact_ids,
            "error_summary": latest_error_summary,
        },
        "artifact_id": f"native_marimo_runtime_failure_group_{source_artifact_ids[0] if source_artifact_ids else 'first'}_{source_artifact_ids[-1] if source_artifact_ids else 'last'}",
        "created_at": last.get("created_at") or first.get("created_at"),
    }
    if actions:
        grouped["next_focus"] = actions[-1]
    return grouped


def representative_notebook_artifact_ids(
    db: Session | None,
    *,
    project_id: str | None,
    artifact_ids: list[str],
) -> list[str]:
    if db is None or not project_id or not artifact_ids:
        return artifact_ids
    artifacts = {
        artifact.id: artifact
        for artifact in db.scalars(
            select(Artifact).where(Artifact.project_id == project_id, Artifact.id.in_(artifact_ids))
        ).all()
    }
    if not artifacts:
        return artifact_ids
    grouped: dict[tuple[str, str], Artifact] = {}
    order: list[tuple[str, str]] = []
    for artifact_id in artifact_ids:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            continue
        key = (artifact.asset_type, artifact.name)
        if key not in grouped:
            order.append(key)
            grouped[key] = artifact
            continue
        current = grouped[key]
        if (artifact.version, artifact.created_at, artifact.id) >= (current.version, current.created_at, current.id):
            grouped[key] = artifact
    representatives = [grouped[key].id for key in order if key in grouped]
    return representatives or artifact_ids


@router.get("/api/projects/{project_id}/research-plan/timeline")
def get_research_plan_timeline(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    locale: str | None = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
    record_harness_objective_in_research_plan(
        db,
        project_id=project.id,
        objective_label=project.target_column,
    )
    db.flush()
    response_locale = (
        locale.strip()
        if isinstance(locale, str) and locale.strip()
        else explicit_project_response_locale(db, project)
    )
    return build_research_plan_timeline_response(db, project_id=project_id, locale=response_locale)


@router.post("/api/projects/{project_id}/research-plan/revisions")
def commit_project_research_plan_revision(
    project_id: str,
    payload: ResearchPlanRevisionCommitCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    if payload.source_artifact_id is not None:
        source_artifact = db.get(Artifact, payload.source_artifact_id)
        if source_artifact is None or source_artifact.project_id != project_id:
            raise HTTPException(status_code=400, detail="source_artifact_id does not belong to this project")
    try:
        result = commit_research_plan_revision(
            db,
            project_id=project_id,
            document=payload.document,
            author_type=payload.author_type,
            author_id=payload.author_id,
            reason=payload.reason,
            source_artifact_id=payload.source_artifact_id,
            parent_revision_id=payload.parent_revision_id,
            metadata=payload.metadata,
            strict_validation=True,
        )
    except ResearchPlanValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": "research_plan_tool_error.v1",
                "status": "failed",
                "message": str(exc),
                "issues": exc.issues,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "schema_version": "research_plan_revision_commit.v1",
        "project_id": project_id,
        "research_plan_id": result.plan.id,
        "revision_id": result.revision.id,
        "revision_index": result.revision.revision_index,
        "created": result.created,
        "active_revision_id": result.plan.active_revision_id,
    }


@router.post("/api/projects/{project_id}/research-plan/current-work")
def set_project_research_plan_current_work(
    project_id: str,
    payload: ResearchPlanCurrentWorkCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        current = set_research_plan_current_work(
            db,
            project_id=project_id,
            node_id=payload.node_id,
            summary=payload.summary,
            status=payload.status,
            expected_outputs=payload.expected_outputs,
            revision_id=payload.revision_id,
            updated_by_type=payload.updated_by_type,
            updated_by=payload.updated_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "schema_version": "research_plan_current_work.v1",
        "project_id": project_id,
        "current_work": research_plan_current_work_payload(current),
    }


@router.post("/api/projects/{project_id}/research-plan/artifacts")
def attach_project_research_plan_artifact(
    project_id: str,
    payload: ResearchPlanArtifactAttachCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        edge = attach_research_plan_artifact(
            db,
            project_id=project_id,
            node_id=payload.node_id,
            artifact_id=payload.artifact_id,
            role=payload.role,
            revision_id=payload.revision_id,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "schema_version": "research_plan_artifact_link.v1",
        "project_id": project_id,
        "link": {
            "id": edge.id,
            "from_asset_type": edge.from_asset_type,
            "from_asset_id": edge.from_asset_id,
            "to_asset_type": edge.to_asset_type,
            "to_asset_id": edge.to_asset_id,
            "relation_type": edge.relation_type,
            "metadata": loads_json(edge.metadata_json, {}),
            "created_at": edge.created_at.isoformat(),
        },
    }


@router.post("/api/projects/{project_id}/research-plan/human-attention")
def request_project_research_plan_human_attention(
    project_id: str,
    payload: ResearchPlanHumanAttentionCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        question = request_research_plan_human_attention(
            db,
            project_id=project_id,
            question=payload.question,
            why_it_matters=payload.why_it_matters,
            node_id=payload.node_id,
            provisional_assumption=payload.provisional_assumption,
            impact_if_wrong=payload.impact_if_wrong,
            urgency=payload.urgency,
            fallback_policy=payload.fallback_policy,
            blocks_next_phase=payload.blocks_next_phase,
            revision_id=payload.revision_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "schema_version": "research_plan_human_attention.v1",
        "project_id": project_id,
        "question": question_to_dict(question),
    }


def explicit_project_response_locale(db: Session, project: Project) -> str | None:
    if project.created_by and db.get(User, project.created_by) is not None:
        return latest_project_response_locale(db, project)
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
        if isinstance(payload.get("locale"), str) and payload["locale"].strip():
            return latest_project_response_locale(db, project)
    return None


@router.get("/api/projects/{project_id}/agent-session/current", response_model=AgentSessionRead | None)
def get_current_agent_session(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any] | None:
    require_project(db, project_id)
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    if session is None:
        return None
    payload = session_to_dict(session)
    observed_processes = running_codex_processes_for_project(project_id)
    payload["observed_codex_process_count"] = len(observed_processes)
    payload["observed_codex_processes"] = observed_processes[:3]
    payload["pid_is_observed_codex_process"] = bool(
        session.pid is not None and any(process.get("pid") == session.pid for process in observed_processes)
    )
    if observed_processes:
        payload["observed_runner_state"] = "running"
    elif session.status in {"starting", "running", "between_turns", "waiting_for_runner"}:
        payload["observed_runner_state"] = "supervisor_should_continue"
    else:
        payload["observed_runner_state"] = session.status
    return payload


@router.get("/api/projects/{project_id}/agent-session/transcript", response_model=list[AgentTranscriptEventRead])
def list_agent_session_transcript(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    limit: int = 300,
    since_index: int | None = None,
) -> list[dict[str, Any]]:
    require_project(db, project_id)
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    if session is None:
        return []
    bounded_limit = max(1, min(limit, 1000))
    if since_index is not None:
        events = list(
            db.scalars(
                select(AgentTranscriptEvent)
                .where(
                    AgentTranscriptEvent.session_id == session.id,
                    AgentTranscriptEvent.event_index > since_index,
                )
                .order_by(AgentTranscriptEvent.event_index.asc())
                .limit(bounded_limit)
            ).all()
        )
        return [transcript_event_to_dict(event) for event in events]
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(AgentTranscriptEvent.session_id == session.id)
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(bounded_limit)
        ).all()
    )
    return [transcript_event_to_dict(event) for event in reversed(events)]


RAW_TRANSCRIPT_LINE_CHAR_LIMIT = 12_000
RAW_TRANSCRIPT_PARSED_STRING_LIMIT = 4_000
RAW_TRANSCRIPT_TAIL_CHUNK_SIZE = 64 * 1024


def parsed_jsonl_line(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def clipped_raw_transcript_text(text: str, *, max_chars: int = RAW_TRANSCRIPT_LINE_CHAR_LIMIT) -> tuple[str, bool, int]:
    original_length = len(text)
    if original_length <= max_chars:
        return text, False, original_length
    suffix = f"... [truncated {original_length - max_chars} chars; open raw transcript artifact for full line]"
    return f"{text[:max_chars]}{suffix}", True, original_length


def clipped_raw_transcript_value(value: Any, *, max_string_chars: int = RAW_TRANSCRIPT_PARSED_STRING_LIMIT) -> Any:
    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        return f"{value[:max_string_chars]}... [truncated {len(value) - max_string_chars} chars]"
    if isinstance(value, list):
        return [clipped_raw_transcript_value(item, max_string_chars=max_string_chars) for item in value[:80]]
    if isinstance(value, dict):
        return {
            str(key): clipped_raw_transcript_value(item, max_string_chars=max_string_chars)
            for key, item in list(value.items())[:80]
        }
    return value


def raw_transcript_line_to_dict(line_number: int, line: str) -> dict[str, Any]:
    clipped, truncated, original_length = clipped_raw_transcript_text(line)
    parsed = parsed_jsonl_line(line)
    return {
        "line_number": line_number,
        "text": clipped,
        "parsed": clipped_raw_transcript_value(parsed) if parsed is not None else None,
        "truncated": truncated,
        "original_length": original_length,
    }


def tail_text_file(path: Path, *, limit: int) -> tuple[int, list[str], list[dict[str, Any]], str | None]:
    if not path.exists():
        return 0, [], [], None
    try:
        stat = path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        if stat.st_size == 0:
            return 0, [], [], updated_at
        newline_count = 0
        tail_buffer = b""
        with path.open("rb") as handle:
            handle.seek(stat.st_size - 1)
            ends_with_newline = handle.read(1) == b"\n"
            remaining = stat.st_size
            while remaining > 0:
                read_size = min(RAW_TRANSCRIPT_TAIL_CHUNK_SIZE, remaining)
                remaining -= read_size
                handle.seek(remaining)
                chunk = handle.read(read_size)
                newline_count += chunk.count(b"\n")
                tail_buffer = chunk + tail_buffer
                if tail_buffer.count(b"\n") > limit:
                    tail_lines = tail_buffer.splitlines()
                    tail_buffer = b"\n".join(tail_lines[-limit:])
        count = newline_count if ends_with_newline else newline_count + 1
    except OSError:
        return 0, [], [], None
    tail_line_bytes = tail_buffer.splitlines()[-limit:]
    tail_lines = [line.decode("utf-8", errors="replace") for line in tail_line_bytes]
    start_line_number = max(1, count - len(tail_lines) + 1)
    numbered_lines = [
        raw_transcript_line_to_dict(start_line_number + offset, line)
        for offset, line in enumerate(tail_lines)
    ]
    text_lines = [line["text"] for line in numbered_lines]
    return count, text_lines, numbered_lines, updated_at


def raw_transcript_observation_for_session(session: AgentSession | None) -> dict[str, Any]:
    if session is None or not session.workspace_path:
        return {
            "session_id": None,
            "stdout_line_count": 0,
            "stderr_line_count": 0,
            "updated_at": None,
        }
    workspace = Path(session.workspace_path)
    stdout_count, _stdout_tail, _stdout_tail_lines, stdout_updated_at = tail_text_file(
        raw_codex_transcript_path(workspace), limit=1
    )
    stderr_count, _stderr_tail, _stderr_tail_lines, stderr_updated_at = tail_text_file(
        raw_codex_stderr_path(workspace), limit=1
    )
    return {
        "session_id": session.id,
        "stdout_line_count": stdout_count,
        "stderr_line_count": stderr_count,
        "updated_at": max((item for item in (stdout_updated_at, stderr_updated_at) if item), default=None),
    }


@router.get("/api/projects/{project_id}/agent-session/raw-transcript", response_model=AgentRawTranscriptRead)
def get_agent_session_raw_transcript(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    limit: int = 80,
) -> dict[str, Any]:
    require_project(db, project_id)
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    if session is None or not session.workspace_path:
        return {
            "session_id": None,
            "stdout_path": None,
            "stderr_path": None,
            "stdout_download_url": None,
            "stderr_download_url": None,
            "stdout_line_count": 0,
            "stderr_line_count": 0,
            "stdout_tail": [],
            "stderr_tail": [],
            "stdout_tail_lines": [],
            "stderr_tail_lines": [],
            "updated_at": None,
        }
    bounded_limit = max(1, min(limit, 500))
    workspace = Path(session.workspace_path)
    stdout_path = raw_codex_transcript_path(workspace)
    stderr_path = raw_codex_stderr_path(workspace)
    stdout_count, stdout_tail, stdout_tail_lines, stdout_updated_at = tail_text_file(stdout_path, limit=bounded_limit)
    stderr_count, stderr_tail, stderr_tail_lines, stderr_updated_at = tail_text_file(stderr_path, limit=bounded_limit)
    return {
        "session_id": session.id,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_download_url": f"/api/projects/{project_id}/agent-session/raw-transcript/stdout/download",
        "stderr_download_url": f"/api/projects/{project_id}/agent-session/raw-transcript/stderr/download",
        "stdout_line_count": stdout_count,
        "stderr_line_count": stderr_count,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "stdout_tail_lines": stdout_tail_lines,
        "stderr_tail_lines": stderr_tail_lines,
        "updated_at": max((item for item in (stdout_updated_at, stderr_updated_at) if item), default=None),
    }


@router.get("/api/projects/{project_id}/agent-session/raw-transcript/{stream_name}/download")
def download_agent_session_raw_transcript(
    project_id: str,
    stream_name: str,
    db: Annotated[Session, Depends(get_session)],
):
    require_project(db, project_id)
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    if session is None or not session.workspace_path:
        raise HTTPException(status_code=404, detail="AgentSession raw transcript is not available.")
    workspace = Path(session.workspace_path)
    if stream_name == "stdout":
        path = raw_codex_transcript_path(workspace)
        filename = "codex_raw_transcript.jsonl"
    elif stream_name == "stderr":
        path = raw_codex_stderr_path(workspace)
        filename = "codex_stderr.log"
    else:
        raise HTTPException(status_code=404, detail="Raw transcript stream must be stdout or stderr.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw transcript file not found.")
    return FileResponse(path=path, filename=filename, media_type="text/plain")


@router.post("/api/agent-task-contracts/{artifact_id}/prepare-workspace", response_model=JobRead)
def prepare_planned_agent_workspace_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="Codex work request artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Codex work request artifact is not project-scoped")
    project = require_project(db, contract_artifact.project_id)
    job = create_job(
        db,
        job_type="prepare_planned_agent_workspace",
        project_id=project.id,
        input_payload={"agent_task_contract_artifact_id": contract_artifact.id},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/readiness-review", response_model=JobRead)
def review_agent_task_readiness_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="Codex work request artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Codex work request artifact is not project-scoped")
    project = require_project(db, contract_artifact.project_id)
    job = create_job(
        db,
        job_type="review_agent_task_readiness",
        project_id=project.id,
        input_payload={"agent_task_contract_artifact_id": contract_artifact.id},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/run-local-stub", response_model=JobRead)
def run_planned_agent_task_stub_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="Codex work request artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Codex work request artifact is not project-scoped")
    project = require_project(db, contract_artifact.project_id)
    job = create_job(
        db,
        job_type="run_planned_agent_task_stub",
        project_id=project.id,
        input_payload={"agent_task_contract_artifact_id": contract_artifact.id},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "runner": "local_stub",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/run-codex", response_model=JobRead)
def run_planned_agent_task_codex_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="Codex work request artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Codex work request artifact is not project-scoped")
    project = require_project(db, contract_artifact.project_id)
    job = create_job(
        db,
        job_type="run_planned_agent_task_codex",
        project_id=project.id,
        input_payload={"agent_task_contract_artifact_id": contract_artifact.id},
        policy={
            "network": "harness_only",
            "secret_access": "forbidden_to_task",
            "connector_credentials": "not_materialized",
            "runner": "codex_cli",
            "approval_mode": "endpoint_invocation",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/agent-task-results")
def list_project_agent_task_results(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    project = require_project(db, project_id)
    return list_agent_task_result_summaries(db, project=project)


@router.post("/api/projects/{project_id}/approach/research-source-pack", response_model=JobRead)
def generate_project_research_source_pack(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    spec = latest_approved_spec(db, project_id)
    job = create_job(
        db,
        job_type="create_research_source_pack",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id if dataset else None, "evaluation_spec_id": spec.id if spec else None},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/research-source-packs/{artifact_id}/run-local-stub", response_model=JobRead)
def run_research_source_pack_stub_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    source_pack_artifact = db.get(Artifact, artifact_id)
    if source_pack_artifact is None:
        raise HTTPException(status_code=404, detail="Research Source Pack artifact not found")
    if source_pack_artifact.asset_type != "research_source_pack":
        raise HTTPException(status_code=400, detail="Artifact is not a research_source_pack")
    if source_pack_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Research Source Pack artifact is not project-scoped")
    project = require_project(db, source_pack_artifact.project_id)
    job = create_job(
        db,
        job_type="run_research_source_pack_stub",
        project_id=project.id,
        input_payload={"research_source_pack_artifact_id": source_pack_artifact.id},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "runner": "local_stub_research_runner",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-synthesis", response_model=JobRead)
def create_project_research_synthesis(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_research_synthesis",
        project_id=project_id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-briefs", response_model=JobRead)
def generate_project_research_brief(
    project_id: str,
    payload: ResearchBriefCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    spec = latest_approved_spec(db, project_id)
    job = create_job(
        db,
        job_type="generate_research_brief",
        project_id=project_id,
        input_payload={
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": spec.id if spec else None,
            "question": payload.question,
        },
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/approach/research-briefs", response_model=list[ResearchBriefRead])
def list_project_research_briefs(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    briefs = db.scalars(
        select(ResearchBrief).where(ResearchBrief.project_id == project_id).order_by(ResearchBrief.created_at.desc())
    ).all()
    return [research_brief_to_dict(item) for item in briefs]


@router.post("/api/projects/{project_id}/approach/ideas/generate", response_model=JobRead)
def generate_project_approach_ideas(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    spec = latest_approved_spec(db, project_id)
    brief = latest_research_brief(db, project_id)
    job = create_job(
        db,
        job_type="generate_approach_candidates",
        project_id=project_id,
        input_payload={
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": spec.id if spec else None,
            "research_brief_id": brief.id if brief else None,
        },
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/approach/ideas", response_model=list[IdeaRead])
def list_project_ideas(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    ideas = db.scalars(select(Idea).where(Idea.project_id == project_id).order_by(Idea.priority.desc(), Idea.created_at.desc())).all()
    return [idea_to_dict(item) for item in ideas]


@router.post("/api/ideas/{idea_id}/prepare-agent-context", response_model=JobRead)
def prepare_idea_agent_context(
    idea_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    project = require_project(db, idea.project_id)
    job = create_job(
        db,
        job_type="prepare_agent_context",
        project_id=project.id,
        input_payload={"idea_id": idea.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/ideas/{idea_id}/context-packs", response_model=list[ArtifactRead])
def list_idea_agent_context_packs(idea_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == idea.project_id, Artifact.asset_type == "agent_context_pack")
        .order_by(Artifact.created_at.desc())
    ).all()
    return [artifact_to_dict(artifact) for artifact in artifacts if loads_json(artifact.metadata_json, {}).get("idea_id") == idea.id]


@router.post("/api/ideas/{idea_id}/experiment-plan", response_model=JobRead)
def create_idea_experiment_plan(
    idea_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    project = require_project(db, idea.project_id)
    job = create_job(
        db,
        job_type="create_experiment_plan",
        project_id=project.id,
        input_payload={"idea_id": idea.id},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/ideas/{idea_id}/experiment-plans", response_model=list[ArtifactRead])
def list_idea_experiment_plans(idea_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == idea.project_id, Artifact.asset_type == "experiment_plan")
        .order_by(Artifact.created_at.desc())
    ).all()
    return [artifact_to_dict(artifact) for artifact in artifacts if loads_json(artifact.metadata_json, {}).get("idea_id") == idea.id]


@router.post("/api/ideas/{idea_id}/run-agent-task", response_model=JobRead)
def run_idea_agent_task(
    idea_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    project = require_project(db, idea.project_id)
    job = create_job(
        db,
        job_type="run_agent_task",
        project_id=project.id,
        input_payload={"idea_id": idea.id, "task_contract": loads_json(idea.agent_task_contract_json, {})},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "approval_mode": "endpoint_invocation",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/reports/draft", response_model=JobRead)
def draft_report_endpoint(
    project_id: str,
    payload: ReportCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="draft_project_report",
        project_id=project_id,
        input_payload={"title": payload.title, "report_type": payload.report_type},
        policy={"execution": "queued_worker", "network": "disabled", "secret_access": "forbidden"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/reports", response_model=list[ReportRead])
def list_project_reports(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    reports = db.scalars(select(Report).where(Report.project_id == project_id).order_by(Report.created_at.desc())).all()
    return [report_to_dict(item) for item in reports]


@router.get("/api/projects/{project_id}/decision-report/current", response_model=DecisionReportCurrentRead)
def current_decision_report_endpoint(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return current_decision_report_payload(db, project=project)


@router.get("/api/projects/{project_id}/results/readout", response_model=ResultReadoutRead)
def result_readout_endpoint(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_result_readout(db, project=project)


@router.post("/api/projects/{project_id}/results/notebook-evidence", response_model=JobRead)
def prepare_result_notebook_evidence_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="prepare_result_notebook_evidence",
        project_id=project_id,
        input_payload={"triggered_by": "result_readout"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "prepare_native_marimo_source_context",
            "executes_notebook_code": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/decision-report/generate", response_model=JobRead)
def generate_decision_report_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="generate_decision_report",
        project_id=project_id,
        input_payload={},
        policy={
            "execution": "queued_worker",
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
        },
    )
    return job_to_dict(job)


@router.get("/api/reports/{report_id}/preview", response_model=ArtifactPreviewRead)
def preview_report(report_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    artifact = db.get(Artifact, report.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return artifact_preview_to_dict(artifact, path, limit_bytes=artifact_preview_limit_bytes(artifact, path), db=db)


@router.get("/api/reports/{report_id}/download")
def download_report(report_id: str, db: Annotated[Session, Depends(get_session)]) -> FileResponse:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    artifact = db.get(Artifact, report.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path=path, filename=path.name)


@router.post("/api/reports/{report_id}/translate", response_model=JobRead)
def translate_report_endpoint(
    report_id: str,
    payload: TranslationCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    artifact = db.get(Artifact, report.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Report artifact not found")
    job = create_translation_job(
        db,
        project_id=report.project_id,
        source_type="report",
        source_id=report.id,
        source_artifact_id=artifact.id,
        payload=payload,
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/visualizations/generate", response_model=JobRead)
def generate_visualization_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_visualization_spec",
        project_id=project_id,
        input_payload={},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/visualizations", response_model=list[VisualizationSpecRead])
def list_project_visualizations(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    visualizations = db.scalars(
        select(VisualizationSpec).where(VisualizationSpec.project_id == project_id).order_by(VisualizationSpec.created_at.desc())
    ).all()
    return [visualization_to_dict(item) for item in visualizations]


@router.post("/api/projects/{project_id}/insights/generate", response_model=JobRead)
def generate_insights_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="generate_insights",
        project_id=project_id,
        input_payload={},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/decision-dashboard/generate", response_model=JobRead)
def generate_decision_dashboard_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="generate_decision_dashboard",
        project_id=project_id,
        input_payload={},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/analysis-notebooks/data-understanding", response_model=JobRead)
def generate_data_understanding_notebook_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    payload: DataUnderstandingNotebookCreate | None = None,
) -> dict[str, Any]:
    require_project(db, project_id)
    response_locale = payload.locale if payload else None
    job = create_job(
        db,
        job_type="prepare_data_understanding_notebook_authoring",
        project_id=project_id,
        input_payload={"notebook_kind": "data_understanding", "response_locale": response_locale},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "execution_mode": "prepare_authoring_context_only",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/analysis-notebooks")
def list_project_analysis_notebooks(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_project_notebook_index(db, project)


@router.get("/api/projects/{project_id}/analysis-story")
def current_project_analysis_story(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_project_analysis_story(db, project)


@router.post("/api/analysis-notebooks/{artifact_id}/execution-plan", response_model=JobRead)
def plan_analysis_notebook_execution_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    notebook_artifact = db.get(Artifact, artifact_id)
    if notebook_artifact is None:
        raise HTTPException(status_code=404, detail="Analysis notebook artifact not found")
    if notebook_artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        raise HTTPException(status_code=400, detail="Artifact is not a native marimo notebook source artifact")
    if notebook_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Analysis notebook artifact must be project-scoped")
    require_project(db, notebook_artifact.project_id)
    job = create_job(
        db,
        job_type="plan_notebook_execution",
        project_id=notebook_artifact.project_id,
        input_payload={"analysis_notebook_artifact_id": notebook_artifact.id},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "plan_only",
            "executes_notebook_code": False,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/analysis-notebooks/{artifact_id}/marimo-session")
def start_native_marimo_session_endpoint(
    artifact_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    restart: bool = Query(False),
    wait_ready: bool = Query(True),
) -> dict[str, Any]:
    notebook_artifact = db.get(Artifact, artifact_id)
    if notebook_artifact is None:
        raise HTTPException(status_code=404, detail="Analysis notebook artifact not found")
    if notebook_artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        raise HTTPException(status_code=400, detail="Artifact is not a marimo source notebook")
    if notebook_artifact.project_id is not None:
        require_project(db, notebook_artifact.project_id)
    if restart:
        stop_native_marimo_session_for_artifact(notebook_artifact.id)
    try:
        session = start_or_get_native_marimo_session(
            artifact=notebook_artifact,
            settings=request.app.state.settings,
        )
        if wait_ready and hasattr(session, "is_alive"):
            wait_for_native_marimo_session_ready(
                session,
                timeout_seconds=NATIVE_MARIMO_OPEN_READY_TIMEOUT_SECONDS,
            )
    except (FileNotFoundError, RuntimeError, TimeoutError, ValueError) as exc:
        if notebook_artifact.project_id is not None:
            project = require_project(db, notebook_artifact.project_id)
            record_native_marimo_open_failure_chat_turn(
                db,
                store=store,
                project=project,
                notebook_artifact=notebook_artifact,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return session.to_dict()


@router.get("/api/marimo-sessions/{session_id}")
def get_native_marimo_session_endpoint(
    session_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    session = native_marimo_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Native marimo session is not running")
    payload = session.to_dict()
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    error_excerpt = runtime.get("error_excerpt") if isinstance(runtime, dict) else None
    if isinstance(error_excerpt, str) and error_excerpt.strip() and session.project_id is not None:
        notebook_artifact = db.get(Artifact, session.artifact_id)
        project = db.get(Project, session.project_id)
        if notebook_artifact is not None and project is not None:
            if payload.get("status") == "failed":
                artifact = record_native_marimo_open_failure_chat_turn(
                    db,
                    store=store,
                    project=project,
                    notebook_artifact=notebook_artifact,
                    error_type="RuntimeError",
                    error_message=error_excerpt,
                )
            else:
                artifact = record_native_marimo_runtime_failure_chat_turn(
                    db,
                    store=store,
                    project=project,
                    notebook_artifact=notebook_artifact,
                    error_message=error_excerpt,
                )
            if artifact is not None:
                db.commit()
    return payload


@router.delete("/api/marimo-sessions/{session_id}")
def stop_native_marimo_session_endpoint(session_id: str) -> dict[str, Any]:
    stopped = stop_native_marimo_session(session_id)
    return {"schema_version": "native_marimo_session_stop.v1", "session_id": session_id, "stopped": stopped}


def record_native_marimo_runtime_failure_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    notebook_artifact: Artifact,
    error_message: str,
) -> Artifact | None:
    error_summary = summarize_runtime_error_for_chat(error_message)
    notebook_source_hash = marimo_notebook_source_hash_for_artifact(notebook_artifact)
    source_hash_key = notebook_source_hash[:16] if notebook_source_hash is not None else "unknown_source"
    digest = hashlib.sha1(f"{notebook_artifact.id}:runtime:{source_hash_key}:{error_message}".encode()).hexdigest()[:12]
    source_key = f"native_marimo_runtime_failure:{notebook_artifact.id}:{source_hash_key}:{digest}"
    if native_marimo_failure_chat_turn_exists(
        db,
        project=project,
        source="native_marimo_runtime_failure",
        source_key=source_key,
    ):
        return None

    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is not None and session.workspace_path:
        write_notebook_runtime_failure_to_workspace_inbox(
            Path(session.workspace_path),
            notebook_artifact=notebook_artifact,
            error_message=f"RuntimeError: {error_message}",
        )

    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    if japanese:
        assistant_message = (
            "Notebookはnative marimoで開きましたが、実行中にruntime errorが出ています。"
            "このNotebook sourceを修正対象として扱い、Codexに修正できる形で詳細を渡しています。"
        )
        action_label = "Notebookを修正対象として開く"
        action_detail = "native marimoでruntime errorを確認できます。"
        next_label = "Notebook"
    else:
        assistant_message = (
            "The notebook opened in native marimo, but marimo reported runtime errors. "
            "Treat this notebook source as the repair target; Codex has the details it needs to fix it."
        )
        action_label = "Open notebook for repair"
        action_detail = "Open the native marimo notebook and inspect the runtime error."
        next_label = "Notebook"

    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "native_marimo_runtime_failed",
            "source": "native_marimo_session",
            "status": "needs_attention",
        },
        "actions": [
            {
                "type": "open_artifact",
                "status": "needs_attention",
                "label": action_label,
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "detail": action_detail,
                "artifact_id": notebook_artifact.id,
                "artifact_ids": [notebook_artifact.id],
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "native_marimo_runtime_failed.v1",
            "agent_session_id": session.id if session is not None else None,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_source_hash": notebook_source_hash,
            "error_type": "RuntimeError",
            "error_message": error_message[:4000],
            "error_summary": error_summary,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "harness_observation",
            "status": "harness_fact",
        },
        "worker_events": [
            {
                "worker_id": f"native-marimo-runtime-{notebook_artifact.id}",
                "display_name": "marimo Notebook",
                "status": "needs_attention",
                "headline": "Notebook runtime error" if not japanese else "Notebook runtime error",
                "detail": error_summary,
                "job_type": "native_marimo_session",
                "project_id": project.id,
                "project_name": project.name,
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "artifact_id": notebook_artifact.id,
                "artifact_ids": [notebook_artifact.id],
                "active": False,
                "human_description": {
                    "source": "native_marimo_session",
                    "title": "Notebook runtime error",
                    "summary": error_summary,
                },
                "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
            }
        ],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {
            "target_tab": "Notebooks",
            "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
            "artifact_id": notebook_artifact.id,
            "artifact_ids": [notebook_artifact.id],
            "label": next_label,
        },
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"native_marimo_runtime_failure_{notebook_artifact.id}_{digest}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id if session is not None else None,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_source_hash": notebook_source_hash,
            "source": "native_marimo_runtime_failure",
            "source_key": source_key,
            "status": "failed",
        },
    )


def summarize_runtime_error_for_chat(error_message: str, *, limit: int = 900) -> str:
    stripped = error_message.strip()
    if len(stripped) <= limit:
        return stripped
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    first_line = lines[0] if lines else stripped[:limit]
    terminal_line = next(
        (
            line
            for line in reversed(lines)
            if line != "..." and not line.startswith("[E ")
        ),
        lines[-1] if lines else stripped[-limit:],
    )
    summary = first_line if terminal_line == first_line else f"{first_line}\n...\n{terminal_line}"
    if len(summary) <= limit:
        return summary
    return f"{summary[: max(0, limit - 4)].rstrip()}\n..."


def record_native_marimo_open_failure_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    notebook_artifact: Artifact,
    error_type: str,
    error_message: str,
) -> Artifact | None:
    digest = hashlib.sha1(f"{notebook_artifact.id}:{error_type}:{error_message}".encode()).hexdigest()[:12]
    source_key = f"native_marimo_open_failure:{notebook_artifact.id}:{digest}"
    if native_marimo_failure_chat_turn_exists(
        db,
        project=project,
        source="native_marimo_open_failure",
        source_key=source_key,
    ):
        return None

    session = active_main_session(db, project.id) or latest_main_session(db, project.id)
    if session is not None and session.workspace_path:
        write_notebook_runtime_failure_to_workspace_inbox(
            Path(session.workspace_path),
            notebook_artifact=notebook_artifact,
            error_message=f"{error_type}: {error_message}",
        )

    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    if japanese:
        assistant_message = (
            "このNotebookをmarimoで開けませんでした。Notebook sourceは保存済みです。"
            "未完成の表示にはせず、Notebook/runtimeの修正対象として扱います。"
        )
        action_label = "Notebookを開く"
        action_detail = "native marimoで再度開きます。失敗する場合は修正対象として扱います。"
        next_label = "Notebook"
    else:
        assistant_message = (
            "This notebook could not be opened in marimo. The notebook source is still saved. "
            "It is treated as a notebook/runtime repair target rather than shown as finished."
        )
        action_label = "Open notebook"
        action_detail = "Try opening the native marimo notebook again. If it still fails, it remains marked for repair."
        next_label = "Notebook"

    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "native_marimo_open_failed",
            "source": "native_marimo_session",
            "status": "needs_attention",
        },
        "actions": [
            {
                "type": "open_artifact",
                "status": "needs_attention",
                "label": action_label,
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "detail": action_detail,
                "artifact_id": notebook_artifact.id,
                "artifact_ids": [notebook_artifact.id],
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "native_marimo_open_failed.v1",
            "agent_session_id": session.id if session is not None else None,
            "notebook_artifact_id": notebook_artifact.id,
            "error_type": error_type,
            "error_message": error_message[:1200],
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "harness_observation",
            "status": "harness_fact",
        },
        "worker_events": [
            {
                "worker_id": f"native-marimo-{notebook_artifact.id}",
                "display_name": "marimo Notebook",
                "status": "needs_attention",
                "headline": "Notebookを開けません" if japanese else "Notebook open failed",
                "detail": (
                    "Notebook sourceの修正が必要です。詳細はRawと修正対象briefに保存しています。"
                    if japanese
                    else "The notebook source needs a repair. Details are saved in Raw and the repair brief."
                ),
                "job_type": "native_marimo_session",
                "project_id": project.id,
                "project_name": project.name,
                "target_tab": "Notebooks",
                "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
                "artifact_id": notebook_artifact.id,
                "artifact_ids": [notebook_artifact.id],
                "active": False,
                "human_description": {
                    "source": "native_marimo_session",
                    "title": "Notebookを開けません" if japanese else "Notebook open failed",
                    "summary": (
                        "Notebook sourceの修正が必要です。"
                        if japanese
                        else "The notebook source needs a repair."
                    ),
                },
                "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
            }
        ],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {
            "target_tab": "Notebooks",
            "target_anchor": NOTEBOOK_NATIVE_MARIMO_ANCHOR,
            "artifact_id": notebook_artifact.id,
            "artifact_ids": [notebook_artifact.id],
            "label": next_label,
        },
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"native_marimo_open_failure_{notebook_artifact.id}_{digest}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id if session is not None else None,
            "notebook_artifact_id": notebook_artifact.id,
            "source": "native_marimo_open_failure",
            "source_key": source_key,
            "status": "failed",
        },
    )


def native_marimo_failure_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    source: str,
    source_key: str,
) -> bool:
    recent = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
        .order_by(Artifact.created_at.desc())
        .limit(100)
    ).all()
    for artifact in recent:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") == source and metadata.get("source_key") == source_key:
            return True
    return False


@router.api_route(
    "/api/marimo-sessions/{session_id}/proxy",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/api/marimo-sessions/{session_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_native_marimo_http(
    session_id: str,
    request: Request,
    path: str = "",
) -> Response:
    session = native_marimo_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Native marimo session is not running")
    if session.to_dict().get("status") != "running":
        raise HTTPException(status_code=503, detail="Native marimo session is not ready")
    target_url = native_marimo_target_url(session, path, request.url.query)
    request_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower()
        not in {
            "host",
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
    }
    async with httpx.AsyncClient(follow_redirects=False, timeout=None) as client:
        proxied = await client.request(
            request.method,
            target_url,
            content=await request.body(),
            headers=request_headers,
        )
    response_headers = {
        key: value
        for key, value in proxied.headers.items()
        if key.lower()
        not in {
            "content-encoding",
            "content-length",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
    }
    return Response(
        content=proxied.content,
        status_code=proxied.status_code,
        headers=response_headers,
        media_type=proxied.headers.get("content-type"),
    )


@router.websocket("/api/marimo-sessions/{session_id}/proxy/{path:path}")
async def proxy_native_marimo_websocket(websocket: WebSocket, session_id: str, path: str = "") -> None:
    session = native_marimo_session(session_id)
    if session is None or session.to_dict().get("status") != "running":
        await websocket.close(code=4404)
        return
    await websocket.accept()
    target_url = native_marimo_target_url(session, path, websocket.scope.get("query_string", b"").decode("utf-8"))
    target_url = target_url.replace("http://", "ws://", 1)
    try:
        async with websockets.connect(target_url) as marimo_socket:
            async def client_to_marimo() -> None:
                while True:
                    message = await websocket.receive()
                    if "text" in message:
                        await marimo_socket.send(message["text"])
                    elif "bytes" in message:
                        await marimo_socket.send(message["bytes"])
                    elif message.get("type") == "websocket.disconnect":
                        await marimo_socket.close()
                        break

            async def marimo_to_client() -> None:
                async for message in marimo_socket:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            await asyncio.gather(client_to_marimo(), marimo_to_client())
    except Exception:
        await websocket.close()


@router.get("/api/projects/{project_id}/insights", response_model=list[InsightRead])
def list_project_insights(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    insights = db.scalars(select(Insight).where(Insight.project_id == project_id).order_by(Insight.created_at.desc())).all()
    return [insight_to_dict(item) for item in insights]


@router.post("/api/projects/{project_id}/baseline/run", response_model=JobRead)
def run_baseline_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    spec = latest_approved_spec(db, project_id)
    if spec is None:
        raise HTTPException(status_code=400, detail="Approve an EvaluationSpec before running baseline")
    split = latest_split_for_spec(db, spec.id)
    if split is None:
        raise HTTPException(status_code=400, detail="Generate a SplitManifest before running baseline")
    job = create_job(
        db,
        job_type="run_baseline",
        project_id=project_id,
        input_payload={"evaluation_spec_id": spec.id, "split_manifest_id": split.id},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/model-candidates/run", response_model=JobRead)
def run_model_candidates_endpoint(
    project_id: str,
    payload: ModelCandidatesRunCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    spec = latest_approved_spec(db, project_id)
    if spec is None:
        raise HTTPException(status_code=400, detail="Approve an EvaluationSpec before training model candidates")
    split = latest_split_for_spec(db, spec.id)
    if split is None:
        raise HTTPException(status_code=400, detail="Generate a SplitManifest before training model candidates")
    normalized_models: list[str] = []
    unsupported_models: list[str] = []
    for model in payload.models:
        normalized = normalize_model_candidate_name(model)
        if normalized is None:
            unsupported_models.append(model)
            continue
        if normalized not in normalized_models:
            normalized_models.append(normalized)
    if not normalized_models:
        raise HTTPException(status_code=400, detail=f"No supported model candidates requested: {unsupported_models}")
    job = create_job(
        db,
        job_type="train_model_candidates",
        project_id=project_id,
        input_payload={
            "requested_models": payload.models,
            "normalized_models": normalized_models,
            "unsupported_models": unsupported_models,
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
        },
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "dependency_changes": "approval_required_when_missing",
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/baseline/strategy-plan", response_model=JobRead)
def plan_baseline_strategy_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    spec = latest_approved_spec(db, project_id)
    if spec is None:
        raise HTTPException(status_code=400, detail="Approve an EvaluationSpec before planning baseline strategy")
    split = latest_split_for_spec(db, spec.id)
    if split is None:
        raise HTTPException(status_code=400, detail="Generate a SplitManifest before planning baseline strategy")
    job = create_job(
        db,
        job_type="plan_baseline_strategy",
        project_id=project_id,
        input_payload={"evaluation_spec_id": spec.id, "split_manifest_id": split.id},
        policy={
            "execution": "queued_worker",
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "dependency_changes": "approval_required_when_missing",
        },
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/runs")
def list_runs(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    require_project(db, project_id)
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project_id).order_by(ExperimentRun.started_at.desc())).all()
    return [
        {
            "id": run.id,
            "project_id": run.project_id,
            "dataset_snapshot_id": run.dataset_snapshot_id,
            "evaluation_spec_id": run.evaluation_spec_id,
            "split_manifest_id": run.split_manifest_id,
            "model_version_id": run.model_version_id,
            "runner_type": run.runner_type,
            "status": run.status,
            "metrics": loads_json(run.metrics_json, {}),
            "summary_md": run.summary_md,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        }
        for run in runs
    ]


@router.post("/api/projects/{project_id}/experiments/compare", response_model=JobRead)
def compare_project_experiments_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    job = create_job(
        db,
        job_type="compare_experiments",
        project_id=project_id,
        input_payload={},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/report", response_model=JobRead)
def draft_run_report_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(
        db,
        job_type="draft_run_report",
        project_id=run.project_id,
        input_payload={"run_id": run.id},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/diagnostics", response_model=JobRead)
def analyze_run_diagnostics_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(
        db,
        job_type="analyze_evaluation_diagnostics",
        project_id=run.project_id,
        input_payload={"run_id": run.id},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/model-diagnostics-artifacts", response_model=JobRead)
def materialize_model_diagnostics_artifacts_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(
        db,
        job_type="materialize_model_diagnostics_artifacts",
        project_id=run.project_id,
        input_payload={"run_id": run.id},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "evaluation_spec_modified": False,
            "split_manifest_required": True,
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/analysis-notebook", response_model=JobRead)
def generate_run_analysis_notebook_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    require_project(db, run.project_id)
    job = create_job(
        db,
        job_type="prepare_model_diagnostics_notebook_authoring",
        project_id=run.project_id,
        input_payload={"run_id": run.id, "notebook_kind": "model_diagnostics"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "execution_mode": "prepare_authoring_context_only",
            "execution": "queued_worker",
        },
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/leaderboard")
def leaderboard(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    project = require_project(db, project_id)
    runs = db.scalars(
        select(ExperimentRun).where(ExperimentRun.project_id == project_id, ExperimentRun.status == "succeeded")
    ).all()
    unique_runs: list[ExperimentRun] = []
    seen_result_signatures: set[str] = set()
    for run in runs:
        metrics = loads_json(run.metrics_json, {})
        params = loads_json(run.params_json, {})
        signature = experiment_result_signature(metrics, model_id=experiment_model_id_from_params(params))
        if signature in seen_result_signatures:
            continue
        seen_result_signatures.add(signature)
        unique_runs.append(run)
    runs = unique_runs
    metric_preference = latest_metric_preference(db, project_id)
    display_metric = metric_preference
    if display_metric is None:
        approved_spec = db.scalar(
            select(EvaluationSpec)
            .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
            .order_by(EvaluationSpec.created_at.desc())
        )
        if approved_spec is not None:
            display_metric = approved_spec.primary_metric
        elif runs:
            first_metrics = loads_json(runs[0].metrics_json, {})
            display_metric = preferred_metric_name(first_metrics, None)
        else:
            display_metric = str(BUILTIN_METRIC_OPTIONS[0]["name"])
    if display_metric is None:
        display_metric = str(BUILTIN_METRIC_OPTIONS[0]["name"])
    sorted_runs = sorted(runs, key=lambda run: leaderboard_sort_key_for_metric(run, display_metric))
    notebook_index = build_project_notebook_index(db, project)
    deliverable_expectations_by_run = deliverable_expectations_for_run_ids(
        db,
        project_id=project_id,
        run_ids=[run.id for run in sorted_runs],
    )
    return [
        {
            "rank": index + 1,
            "run_id": run.id,
            "status": run.status,
            "runner_type": run.runner_type,
            "model_id": model_id or None,
            "model_label": leaderboard_model_label(params, model_id=model_id) or None,
            "model_description": leaderboard_model_description(params, summary_md=run.summary_md, model_id=model_id),
            "features_used": leaderboard_features_used(params),
            "feature_summary": leaderboard_feature_summary(params, metrics),
            "summary_md": run.summary_md,
            "primary_metric_name": metrics.get("primary_metric_name"),
            "primary_metric_value": metrics.get("primary_metric_value"),
            "display_metric_name": display_metric,
            "display_metric_value": display_metric_value,
            "display_metric_available": display_metric_value is not None,
            "display_metric_source": "metric_preference" if metric_preference else "run_primary_metric",
            "metrics": metrics,
            "evaluation_spec_id": run.evaluation_spec_id,
            "split_manifest_id": run.split_manifest_id,
            "evaluation_grade": leaderboard_evaluation_grade(db, run),
            "evaluation_grade_reason": leaderboard_evaluation_grade_reason(db, run),
            "model_version_id": run.model_version_id,
            "pipeline_artifact_id": (
                pipeline_artifact.id
                if (pipeline_artifact := experiment_run_pipeline_artifact(db, run, params=params)) is not None
                else None
            ),
            "deliverable_expectations": deliverable_expectations_by_run.get(run.id, []),
            "model_diagnostics": leaderboard_model_diagnostics(db, run),
            "related_notebook_artifact_ids": leaderboard_related_notebook_artifact_ids(
                notebook_index,
                run_id=run.id,
                model_version_id=run.model_version_id,
            ),
            "related_notebooks": leaderboard_related_notebooks(
                notebook_index,
                run_id=run.id,
                model_version_id=run.model_version_id,
            ),
        }
        for index, run in enumerate(sorted_runs)
        for metrics in [loads_json(run.metrics_json, {})]
        for params in [loads_json(run.params_json, {})]
        for model_id in [leaderboard_model_id(params, metrics)]
        for display_metric_value in [preferred_metric_value(metrics, display_metric)]
    ]


def leaderboard_evaluation_grade(db: Session, run: ExperimentRun) -> str:
    if run.split_manifest_id is None or run.evaluation_spec_id is None:
        return "provisional"
    split = db.get(SplitManifest, run.split_manifest_id)
    if split is None or split.project_id != run.project_id:
        return "provisional"
    if split.evaluation_spec_id != run.evaluation_spec_id:
        return "provisional"
    spec = db.get(EvaluationSpec, run.evaluation_spec_id)
    if spec is None or spec.project_id != run.project_id or spec.status != "approved":
        return "provisional"
    return "formal"


def leaderboard_evaluation_grade_reason(db: Session, run: ExperimentRun) -> str:
    if run.split_manifest_id is None:
        return "missing_split_manifest"
    if run.evaluation_spec_id is None:
        return "missing_evaluation_spec"
    split = db.get(SplitManifest, run.split_manifest_id)
    if split is None or split.project_id != run.project_id:
        return "split_manifest_not_found"
    if split.evaluation_spec_id != run.evaluation_spec_id:
        return "split_manifest_does_not_match_evaluation_spec"
    spec = db.get(EvaluationSpec, run.evaluation_spec_id)
    if spec is None or spec.project_id != run.project_id:
        return "evaluation_spec_not_found"
    if spec.status != "approved":
        return "evaluation_spec_not_approved"
    return "approved_evaluation_spec_and_split_manifest"


def leaderboard_model_diagnostics(db: Session, run: ExperimentRun) -> dict[str, Any]:
    artifact_by_key = {
        "model_diagnostics_artifact_pack": latest_run_artifact(db, run, "model_diagnostics_artifact_pack"),
        "native_feature_importance": latest_run_artifact(db, run, "feature_importance"),
        "permutation_importance": latest_run_artifact(db, run, "permutation_importance"),
        "partial_dependence": latest_run_artifact(db, run, "partial_dependence"),
        "shap": latest_run_artifact(db, run, "shap_summary"),
        "report": latest_run_artifact(db, run, "model_diagnostics_artifact_report"),
    }
    pack_payload = load_json_artifact(artifact_by_key["model_diagnostics_artifact_pack"])
    availability = pack_payload.get("availability") if isinstance(pack_payload, dict) and isinstance(pack_payload.get("availability"), dict) else {}
    standard_checks = {
        "permutation_importance": diagnostic_check_status(
            availability.get("permutation_importance"),
            artifact_by_key["permutation_importance"],
        ),
        "native_feature_importance": diagnostic_check_status(
            availability.get("native_feature_importance"),
            artifact_by_key["native_feature_importance"],
        ),
        "partial_dependence": diagnostic_check_status(
            availability.get("partial_dependence"),
            artifact_by_key["partial_dependence"],
        ),
        "shap": diagnostic_check_status(availability.get("shap"), artifact_by_key["shap"]),
    }
    ready_count = sum(1 for item in standard_checks.values() if item["status"] == "ready")
    if artifact_by_key["model_diagnostics_artifact_pack"] is not None:
        status = "ready" if ready_count else "registered"
    elif any(artifact is not None for artifact in artifact_by_key.values()):
        status = "partial"
    else:
        status = "missing"
    return {
        "schema_version": "leaderboard_model_diagnostics.v1",
        "status": status,
        "standard_checks": standard_checks,
        "availability": availability,
        "artifact_refs": {
            key: model_diagnostics_artifact_ref(artifact)
            for key, artifact in artifact_by_key.items()
            if artifact is not None
        },
    }


def diagnostic_check_status(raw_status: Any, artifact: Artifact | None) -> dict[str, Any]:
    status = str(raw_status or ("ready" if artifact is not None else "missing")).strip()
    if not status:
        status = "missing"
    return {
        "status": status,
        "artifact_id": artifact.id if artifact is not None else None,
    }


@router.get("/api/experiment-runs/{run_id}/pipeline-bundle")
def download_experiment_run_pipeline_bundle(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    require_project(db, run.project_id)
    artifact = experiment_run_pipeline_artifact(db, run, params=loads_json(run.params_json, {}))
    if artifact is None:
        raise HTTPException(status_code=404, detail="Prediction pipeline bundle is not registered for this run")
    path = artifact_primary_path(artifact)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Prediction pipeline bundle file not found")
    response_path = clean_pipeline_bundle_for_download(path)
    background = None
    if response_path != path:
        background = BackgroundTask(lambda target=response_path: target.unlink(missing_ok=True))
    return FileResponse(path=response_path, filename=path.name, media_type="application/zip", background=background)


def clean_pipeline_bundle_for_download(path: Path) -> Path:
    if not zipfile.is_zipfile(path):
        return path
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        if all(pipeline_archive_member_is_downloadable(name) for name in names):
            return path
        handle = tempfile.NamedTemporaryFile(prefix="tablex-pipeline-bundle-", suffix=".zip", delete=False)
        clean_path = Path(handle.name)
        handle.close()
        try:
            with zipfile.ZipFile(clean_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    if not pipeline_archive_member_is_downloadable(info.filename):
                        continue
                    target.writestr(info, source.read(info.filename))
        except Exception:
            clean_path.unlink(missing_ok=True)
            raise
        return clean_path


def pipeline_archive_member_is_downloadable(name: str) -> bool:
    parts = [part for part in Path(name).parts if part not in {"", "."}]
    if any(part in {".tablex_smoke", "__pycache__"} for part in parts):
        return False
    if name.endswith((".pyc", ".pyo")):
        return False
    return True


@router.post("/api/projects/{project_id}/pipelines/{artifact_id}/predict", response_model=JobRead)
def run_prediction_pipeline_endpoint(
    project_id: str,
    artifact_id: str,
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project.id:
        raise HTTPException(status_code=404, detail="Prediction pipeline artifact not found")
    if artifact.asset_type != "prediction_pipeline":
        raise HTTPException(status_code=400, detail="Artifact is not a prediction pipeline")
    dataset_snapshot_id = payload.get("dataset_snapshot_id")
    input_artifact_id = payload.get("input_artifact_id")
    history_artifact_id = payload.get("history_artifact_id")
    if not isinstance(dataset_snapshot_id, str) and not isinstance(input_artifact_id, str):
        raise HTTPException(status_code=400, detail="dataset_snapshot_id or input_artifact_id is required")
    job = create_job(
        db,
        job_type="run_prediction_pipeline",
        project_id=project.id,
        input_payload={
            "pipeline_artifact_id": artifact.id,
            "dataset_snapshot_id": dataset_snapshot_id if isinstance(dataset_snapshot_id, str) else None,
            "input_artifact_id": input_artifact_id if isinstance(input_artifact_id, str) else None,
            "history_artifact_id": history_artifact_id if isinstance(history_artifact_id, str) else None,
            "timeout_seconds": payload.get("timeout_seconds") if isinstance(payload.get("timeout_seconds"), int) else 300,
        },
        policy={
            "execution": "queued_worker",
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
        },
    )
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/pilot-deployments")
def create_pilot_deployment_endpoint(
    project_id: str,
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    pipeline_artifact_id = payload.get("pipeline_artifact_id")
    if not isinstance(pipeline_artifact_id, str) or not pipeline_artifact_id.strip():
        raise HTTPException(status_code=400, detail="pipeline_artifact_id is required")
    pipeline_artifact = db.get(Artifact, pipeline_artifact_id)
    if pipeline_artifact is None or pipeline_artifact.project_id != project.id:
        raise HTTPException(status_code=404, detail="Prediction pipeline artifact not found")
    if pipeline_artifact.asset_type != "prediction_pipeline":
        raise HTTPException(status_code=400, detail="Artifact is not a prediction pipeline")
    deployment = PilotDeployment(
        id=new_id("pdep"),
        project_id=project.id,
        pipeline_artifact_id=pipeline_artifact.id,
        model_version_id=payload.get("model_version_id") if isinstance(payload.get("model_version_id"), str) else None,
        experiment_run_id=payload.get("experiment_run_id") if isinstance(payload.get("experiment_run_id"), str) else None,
        status="active",
        notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
    )
    db.add(deployment)
    db.flush()
    return pilot_deployment_to_dict(deployment)


@router.get("/api/projects/{project_id}/pilot-deployments")
def list_pilot_deployments_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    deployments = db.scalars(
        select(PilotDeployment)
        .where(PilotDeployment.project_id == project.id)
        .order_by(PilotDeployment.started_at.desc())
    ).all()
    deployment_ids = [deployment.id for deployment in deployments]
    prediction_batches = (
        db.scalars(
            select(PilotPredictionBatch)
            .where(PilotPredictionBatch.deployment_id.in_(deployment_ids))
            .order_by(PilotPredictionBatch.created_at.desc())
        ).all()
        if deployment_ids
        else []
    )
    outcome_batches = (
        db.scalars(
            select(PilotOutcomeBatch)
            .where(PilotOutcomeBatch.deployment_id.in_(deployment_ids))
            .order_by(PilotOutcomeBatch.ingested_at.desc())
        ).all()
        if deployment_ids
        else []
    )
    scoring_reports = (
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "pilot_scoring_report")
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    validation_audits = (
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "validation_scheme_audit")
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    reports_by_deployment: dict[str, list[dict[str, Any]]] = {deployment.id: [] for deployment in deployments}
    for artifact in scoring_reports:
        metadata = loads_json(artifact.metadata_json, {})
        deployment_id = metadata.get("deployment_id")
        if isinstance(deployment_id, str) and deployment_id in reports_by_deployment:
            reports_by_deployment[deployment_id].append(pilot_scoring_report_to_dict(artifact))
    audits_by_deployment: dict[str, list[dict[str, Any]]] = {deployment.id: [] for deployment in deployments}
    for artifact in validation_audits:
        metadata = loads_json(artifact.metadata_json, {})
        deployment_id = metadata.get("deployment_id")
        if isinstance(deployment_id, str) and deployment_id in audits_by_deployment:
            audits_by_deployment[deployment_id].append(pilot_validation_audit_to_dict(artifact))
    predictions_by_deployment: dict[str, list[dict[str, Any]]] = {deployment.id: [] for deployment in deployments}
    for batch in prediction_batches:
        predictions_by_deployment.setdefault(batch.deployment_id, []).append(pilot_prediction_batch_to_dict(batch))
    outcomes_by_deployment: dict[str, list[dict[str, Any]]] = {deployment.id: [] for deployment in deployments}
    for batch in outcome_batches:
        outcomes_by_deployment.setdefault(batch.deployment_id, []).append(pilot_outcome_batch_to_dict(batch))
    return {
        "schema_version": "pilot_deployment_index.v1",
        "project_id": project.id,
        "deployments": [
            {
                **pilot_deployment_to_dict(deployment),
                "prediction_batches": predictions_by_deployment.get(deployment.id, []),
                "outcome_batches": outcomes_by_deployment.get(deployment.id, []),
                "scoring_reports": reports_by_deployment.get(deployment.id, []),
                "validation_audits": audits_by_deployment.get(deployment.id, []),
            }
            for deployment in deployments
        ],
    }


@router.post("/api/pilot-deployments/{deployment_id}/predict", response_model=JobRead)
def run_pilot_prediction_endpoint(
    deployment_id: str,
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    deployment = db.get(PilotDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Pilot deployment not found")
    require_project(db, deployment.project_id)
    dataset_snapshot_id = payload.get("dataset_snapshot_id")
    input_artifact_id = payload.get("input_artifact_id")
    history_artifact_id = payload.get("history_artifact_id")
    if not isinstance(dataset_snapshot_id, str) and not isinstance(input_artifact_id, str):
        raise HTTPException(status_code=400, detail="dataset_snapshot_id or input_artifact_id is required")
    job = create_job(
        db,
        job_type="run_prediction_pipeline",
        project_id=deployment.project_id,
        input_payload={
            "deployment_id": deployment.id,
            "pipeline_artifact_id": deployment.pipeline_artifact_id,
            "dataset_snapshot_id": dataset_snapshot_id if isinstance(dataset_snapshot_id, str) else None,
            "input_artifact_id": input_artifact_id if isinstance(input_artifact_id, str) else None,
            "history_artifact_id": history_artifact_id if isinstance(history_artifact_id, str) else None,
            "as_of": payload.get("as_of") if isinstance(payload.get("as_of"), str) else utc_now().isoformat(),
            "timeout_seconds": payload.get("timeout_seconds") if isinstance(payload.get("timeout_seconds"), int) else 300,
        },
        policy={
            "execution": "queued_worker",
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
        },
    )
    return job_to_dict(job)


@router.post("/api/pilot-deployments/{deployment_id}/outcomes", response_model=JobRead)
def register_pilot_outcomes_endpoint(
    deployment_id: str,
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    deployment = db.get(PilotDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Pilot deployment not found")
    project = require_project(db, deployment.project_id)
    outcomes_artifact_id = payload.get("outcomes_artifact_id")
    if not isinstance(outcomes_artifact_id, str) or not outcomes_artifact_id.strip():
        raise HTTPException(status_code=400, detail="outcomes_artifact_id is required")
    outcomes_artifact = db.get(Artifact, outcomes_artifact_id.strip())
    if outcomes_artifact is None or outcomes_artifact.project_id != project.id:
        raise HTTPException(status_code=404, detail="Outcome artifact not found")
    requested_join_keys = payload.get("join_keys")
    if requested_join_keys is not None and not isinstance(requested_join_keys, list):
        raise HTTPException(status_code=400, detail="join_keys must be an array when provided")
    join_keys = [
        item.strip()
        for item in (requested_join_keys or [])
        if isinstance(item, str) and item.strip()
    ]
    outcome_batch = PilotOutcomeBatch(
        id=new_id("pout"),
        deployment_id=deployment.id,
        outcomes_artifact_id=outcomes_artifact.id,
        join_keys_json=dumps_json(join_keys),
    )
    db.add(outcome_batch)
    db.flush()
    job = create_job(
        db,
        job_type="score_pilot_outcomes",
        project_id=project.id,
        input_payload={
            "deployment_id": deployment.id,
            "outcome_batch_id": outcome_batch.id,
            "prediction_batch_id": payload.get("prediction_batch_id")
            if isinstance(payload.get("prediction_batch_id"), str)
            else None,
            "join_keys": join_keys,
            "prediction_column": payload.get("prediction_column")
            if isinstance(payload.get("prediction_column"), str)
            else None,
            "actual_column": payload.get("actual_column") if isinstance(payload.get("actual_column"), str) else None,
            "observed_at_column": payload.get("observed_at_column")
            if isinstance(payload.get("observed_at_column"), str)
            else None,
        },
        policy={
            "execution": "queued_worker",
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
        },
    )
    return job_to_dict(job)


def pilot_deployment_to_dict(deployment: PilotDeployment) -> dict[str, Any]:
    return {
        "id": deployment.id,
        "project_id": deployment.project_id,
        "pipeline_artifact_id": deployment.pipeline_artifact_id,
        "model_version_id": deployment.model_version_id,
        "experiment_run_id": deployment.experiment_run_id,
        "status": deployment.status,
        "started_at": deployment.started_at.isoformat(),
        "notes": deployment.notes,
    }


def pilot_prediction_batch_to_dict(batch: PilotPredictionBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "deployment_id": batch.deployment_id,
        "as_of": batch.as_of.isoformat(),
        "input_artifact_id": batch.input_artifact_id,
        "predictions_artifact_id": batch.predictions_artifact_id,
        "row_count": batch.row_count,
        "created_at": batch.created_at.isoformat(),
    }


def pilot_outcome_batch_to_dict(batch: PilotOutcomeBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "deployment_id": batch.deployment_id,
        "outcomes_artifact_id": batch.outcomes_artifact_id,
        "join_keys": loads_json(batch.join_keys_json, []),
        "matched_rows": batch.matched_rows,
        "ingested_at": batch.ingested_at.isoformat(),
    }


def pilot_scoring_report_to_dict(artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    preview: dict[str, Any] = {}
    try:
        preview = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except Exception:
        preview = {}
    return {
        "artifact": artifact_to_dict(artifact),
        "deployment_id": metadata.get("deployment_id"),
        "prediction_batch_id": metadata.get("prediction_batch_id"),
        "outcome_batch_id": metadata.get("outcome_batch_id"),
        "metrics": preview.get("metrics") if isinstance(preview.get("metrics"), dict) else {},
        "matched_rows": preview.get("matched_rows"),
        "metric_count": preview.get("metric_count"),
        "as_of_violations": preview.get("as_of_violations") if isinstance(preview.get("as_of_violations"), dict) else {},
    }


def pilot_validation_audit_to_dict(artifact: Artifact) -> dict[str, Any]:
    metadata = loads_json(artifact.metadata_json, {})
    preview: dict[str, Any] = {}
    try:
        preview = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except Exception:
        preview = {}
    preview_report_ids = preview.get("scoring_report_artifact_ids")
    metadata_report_ids = metadata.get("scoring_report_artifact_ids")
    scoring_report_artifact_ids = preview_report_ids if isinstance(preview_report_ids, list) else metadata_report_ids
    return {
        "artifact": artifact_to_dict(artifact),
        "deployment_id": metadata.get("deployment_id"),
        "scheme_verdict": preview.get("scheme_verdict") if isinstance(preview.get("scheme_verdict"), str) else metadata.get("scheme_verdict"),
        "next_iteration_focus": preview.get("next_iteration_focus")
        if isinstance(preview.get("next_iteration_focus"), str)
        else None,
        "gap_decomposition": preview.get("gap_decomposition") if isinstance(preview.get("gap_decomposition"), list) else [],
        "scoring_report_artifact_ids": scoring_report_artifact_ids if isinstance(scoring_report_artifact_ids, list) else [],
    }


def leaderboard_related_notebook_artifact_ids(
    notebook_index: dict[str, Any],
    *,
    run_id: str,
    model_version_id: str | None,
) -> list[str]:
    return [
        str(item["artifact_id"])
        for item in leaderboard_related_notebooks(
            notebook_index,
            run_id=run_id,
            model_version_id=model_version_id,
        )
        if item.get("openable") is True
    ]


def leaderboard_related_notebooks(
    notebook_index: dict[str, Any],
    *,
    run_id: str,
    model_version_id: str | None,
) -> list[dict[str, Any]]:
    items = notebook_index.get("items") if isinstance(notebook_index, dict) else None
    if not isinstance(items, list):
        return []
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        related_run_ids = item.get("related_run_ids")
        matches_run = item.get("run_id") == run_id or (
            isinstance(related_run_ids, list) and run_id in related_run_ids
        )
        matches_model = bool(model_version_id and item.get("model_version_id") == model_version_id)
        if not matches_run and not matches_model:
            continue
        artifact_ids = item.get("artifact_ids")
        if not isinstance(artifact_ids, dict):
            continue
        notebook_artifact_id = artifact_ids.get("notebook")
        if not isinstance(notebook_artifact_id, str) or not notebook_artifact_id or notebook_artifact_id in seen:
            continue
        seen.add(notebook_artifact_id)
        coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
        native_marimo_status = str(coverage.get("native_marimo_status") or "")
        status = str(item.get("status") or "")
        output.append(
            {
                "artifact_id": notebook_artifact_id,
                "title": item.get("title"),
                "notebook_kind": item.get("notebook_kind"),
                "status": status,
                "native_marimo_status": native_marimo_status,
                "needs_attention": status == "needs_attention" or native_marimo_status == "runtime_error",
                "openable": True,
                "run_id": item.get("run_id"),
                "model_version_id": item.get("model_version_id"),
                "related_run_ids": related_run_ids if isinstance(related_run_ids, list) else [],
                "recommendation_score": item.get("recommendation_score"),
            }
        )
    return sorted(output, key=lambda item: leaderboard_related_notebook_sort_key(item, run_id=run_id, model_version_id=model_version_id))


def leaderboard_related_notebook_sort_key(
    item: dict[str, Any],
    *,
    run_id: str,
    model_version_id: str | None,
) -> tuple[int, int, int, int, float]:
    status = str(item.get("status") or "")
    native_marimo_status = str(item.get("native_marimo_status") or "")
    needs_attention = status == "needs_attention" or native_marimo_status == "runtime_error"
    notebook_kind = str(item.get("notebook_kind") or "")
    if notebook_kind in {"model_diagnostics", "model_comparison"}:
        kind_rank = 0
    elif notebook_kind == "data_understanding":
        kind_rank = 2
    else:
        kind_rank = 1
    related_run_ids = item.get("related_run_ids")
    if item.get("run_id") == run_id:
        run_rank = 0
    elif isinstance(related_run_ids, list) and run_id in related_run_ids:
        run_rank = 1
    elif model_version_id and item.get("model_version_id") == model_version_id:
        run_rank = 1
    else:
        run_rank = 2
    recommendation_score = item.get("recommendation_score")
    score = float(recommendation_score) if isinstance(recommendation_score, (int, float)) else 0.0
    created_at = str(item.get("created_at") or "")
    return (1 if needs_attention else 0, kind_rank, run_rank, 0 if created_at else 1, -score)


def leaderboard_model_id(params: dict[str, Any], metrics: dict[str, Any]) -> str:
    model_id = experiment_model_id_from_params(params)
    if model_id:
        return model_id
    for key in ("baseline_type", "model_id", "model_type", "estimator", "algorithm"):
        value = metrics.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def leaderboard_model_label(params: dict[str, Any], *, model_id: str) -> str:
    for key in ("model_label", "display_name", "title", "label", "model_name"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = params.get("raw")
    if isinstance(raw, dict):
        for key in ("model_label", "display_name", "title", "label", "model_name"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return model_id


def leaderboard_model_description(params: dict[str, Any], *, summary_md: str | None, model_id: str) -> str:
    for source in (params, params.get("raw") if isinstance(params.get("raw"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("model_description", "description", "summary", "interpretation"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(summary_md, str) and summary_md.strip() and summary_md.strip() != model_id:
        return summary_md.strip()
    return ""


def leaderboard_feature_summary(params: dict[str, Any], metrics: dict[str, Any]) -> str | None:
    for source in (params, params.get("raw") if isinstance(params.get("raw"), dict) else {}):
        if not isinstance(source, dict):
            continue
        value = source.get("feature_summary")
        if isinstance(value, str) and value.strip():
            return value.strip()
        features = source.get("features_used")
        if isinstance(features, list) and features:
            text_features = [str(feature).strip() for feature in features if str(feature).strip()]
            if text_features:
                return ", ".join(text_features[:6]) + ("…" if len(text_features) > 6 else "")
        structured_parts = [
            ("feature policy", source.get("feature_policy")),
            ("split", source.get("split")),
            ("fold", source.get("fold")),
        ]
        summary_parts = [
            f"{label}: {pretty_structured_value(value)}"
            for label, value in structured_parts
            if isinstance(value, str) and value.strip()
        ]
        if summary_parts:
            return " / ".join(summary_parts)
    feature_count = metrics.get("feature_count")
    if isinstance(feature_count, int | float) and not isinstance(feature_count, bool):
        return f"{int(feature_count)} features"
    return None


def leaderboard_features_used(params: dict[str, Any]) -> list[str]:
    for source in (params, params.get("raw") if isinstance(params.get("raw"), dict) else {}):
        if not isinstance(source, dict):
            continue
        features = source.get("features_used")
        if isinstance(features, list):
            text_features = [str(feature).strip() for feature in features if str(feature).strip()]
            if text_features:
                return text_features
    return []


def experiment_run_pipeline_artifact(db: Session, run: ExperimentRun, *, params: dict[str, Any]) -> Artifact | None:
    candidate_ids: list[str] = []
    for source in (params, params.get("raw") if isinstance(params.get("raw"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("pipeline_artifact_id", "prediction_pipeline_artifact_id", "pipeline_bundle_artifact_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                candidate_ids.append(value.strip())
    for artifact_id in dict.fromkeys(candidate_ids):
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None and artifact.project_id == run.project_id and artifact.asset_type == "prediction_pipeline":
            return artifact

    linked_edges = db.scalars(
        select(LineageEdge)
        .where(
            LineageEdge.project_id == run.project_id,
            LineageEdge.from_asset_type == "experiment_run",
            LineageEdge.from_asset_id == run.id,
            LineageEdge.to_asset_type == "artifact",
            LineageEdge.relation_type.in_(
                [
                    "materializes_prediction_pipeline",
                    "registered_prediction_pipeline",
                    "prediction_pipeline",
                ]
            ),
        )
        .order_by(LineageEdge.created_at.desc())
    ).all()
    for edge in linked_edges:
        artifact = db.get(Artifact, edge.to_asset_id)
        if artifact is not None and artifact.project_id == run.project_id and artifact.asset_type == "prediction_pipeline":
            return artifact

    project_pipelines = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == run.project_id, Artifact.asset_type == "prediction_pipeline")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in project_pipelines:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("experiment_run_id") == run.id or metadata.get("run_id") == run.id:
            return artifact
        run_ids = metadata.get("experiment_run_ids")
        if isinstance(run_ids, list) and run.id in run_ids:
            return artifact
    return None


def pretty_structured_value(value: str) -> str:
    return value.strip().replace("__", " / ").replace("_", " ")


@router.post("/api/projects/{project_id}/leaderboard/metric")
def set_leaderboard_metric(
    project_id: str,
    payload: LeaderboardMetricPreferenceCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    metric = normalize_metric_name(payload.metric)
    artifact = record_metric_preference(db, store=store, project=project, metric=metric, source="leaderboard_dropdown")
    return {
        "schema_version": "leaderboard_metric_preference.v1",
        "project_id": project.id,
        "metric": metric,
        "artifact_id": artifact.id,
    }


@router.get("/api/projects/{project_id}/model-versions", response_model=list[ModelVersionRead])
def list_model_versions(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    model_versions = db.scalars(
        select(ModelVersion).where(ModelVersion.project_id == project_id).order_by(ModelVersion.created_at.desc())
    ).all()
    return [model_version_to_dict(item) for item in model_versions]


@router.get("/api/model-versions/{model_version_id}", response_model=ModelVersionRead)
def get_model_version(model_version_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    model_version = db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    return model_version_to_dict(model_version)


@router.post("/api/model-versions/{model_version_id}/validate", response_model=JobRead)
def validate_model_version(
    model_version_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    model_version = db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    job = create_job(
        db,
        job_type="validate_model_package",
        project_id=model_version.project_id,
        input_payload={"model_version_id": model_version.id},
        policy={"execution": "queued_worker"},
    )
    return job_to_dict(job)


@router.get("/api/model-versions/{model_version_id}/validations", response_model=list[ModelValidationRead])
def list_model_version_validations(
    model_version_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> list[dict[str, Any]]:
    model_version = db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    jobs = db.scalars(
        select(Job)
        .where(Job.project_id == model_version.project_id, Job.job_type == "validate_model_package")
        .order_by(Job.created_at.desc())
    ).all()
    validation_jobs = []
    for job in jobs:
        job_input = loads_json(job.input_json, {})
        job_output = loads_json(job.output_json, {})
        if job_input.get("model_version_id") == model_version_id or job_output.get("model_version_id") == model_version_id:
            validation_jobs.append(job)
    return [model_validation_to_dict(db, item, model_version_id) for item in validation_jobs]


@router.get("/api/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_artifacts(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    limit: int | None = None,
    asset_type: str | None = None,
    latest_only: bool = True,
) -> list[dict[str, Any]]:
    require_project(db, project_id)
    if latest_only:
        artifacts = latest_artifact_rows(db, project_id, limit=limit, asset_type=asset_type)
    else:
        query = select(Artifact).where(Artifact.project_id == project_id)
        if asset_type:
            query = query.where(Artifact.asset_type == asset_type)
        query = query.order_by(Artifact.created_at.desc())
        if limit is not None:
            query = query.limit(max(1, min(limit, 5000)))
        artifacts = db.scalars(query).all()
    return [artifact_to_dict(item) for item in artifacts if item.asset_type not in STATIC_NOTEBOOK_HTML_ASSET_TYPES]


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    reject_static_notebook_html_artifact(artifact)
    return artifact_to_dict(artifact)


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> FileResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    reject_static_notebook_html_artifact(artifact)
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path=path, filename=path.name)


def reject_static_notebook_html_artifact(artifact: Artifact) -> None:
    if artifact.asset_type in STATIC_NOTEBOOK_HTML_ASSET_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Static HTML notebook snapshots are not Tablex artifacts. Save and open the native marimo Python source instead.",
        )


def reject_non_native_notebook_preview(artifact: Artifact) -> None:
    if artifact.asset_type in STATIC_NOTEBOOK_HTML_ASSET_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Static HTML notebook snapshots are not notebook artifacts. Open the native marimo source notebook instead.",
        )
    if artifact.asset_type not in {"analysis_notebook", "marimo_notebook"}:
        return
    if research_plan_artifact_is_native_marimo_source(artifact):
        return
    raise HTTPException(
        status_code=400,
        detail="Analysis notebook preview requires a native marimo Python source. Static HTML notebook snapshots are not previewed.",
    )


@router.get("/api/artifacts/{artifact_id}/inline-preview")
def inline_preview_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    reject_non_native_notebook_preview(artifact)
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    suffix = path.suffix.lower()
    media_types = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    if suffix in {".html", ".htm"}:
        try:
            html = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="HTML artifact is not valid UTF-8.") from exc
        return HTMLResponse(content=inline_local_html_assets(artifact, path, html), media_type="text/html")
    media_type = media_types.get(suffix)
    if media_type is None:
        raise HTTPException(status_code=400, detail="Inline preview is only available for HTML, SVG, images, and PDF artifacts.")
    return FileResponse(path=path, media_type=media_type)


@router.get("/api/artifacts/{artifact_id}/preview", response_model=ArtifactPreviewRead)
def preview_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    reject_non_native_notebook_preview(artifact)
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return artifact_preview_to_dict(artifact, path, limit_bytes=artifact_preview_limit_bytes(artifact, path), db=db)


@router.post("/api/artifacts/{artifact_id}/translate", response_model=JobRead)
def translate_artifact_endpoint(
    artifact_id: str,
    payload: TranslationCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    job = create_translation_job(
        db,
        project_id=artifact.project_id,
        source_type="artifact",
        source_id=artifact.id,
        source_artifact_id=artifact.id,
        payload=payload,
    )
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/lineage")
def list_lineage(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    edges = db.scalars(select(LineageEdge).where(LineageEdge.project_id == project_id).order_by(LineageEdge.created_at)).all()
    return [
        {
            "id": edge.id,
            "from_asset_type": edge.from_asset_type,
            "from_asset_id": edge.from_asset_id,
            "to_asset_type": edge.to_asset_type,
            "to_asset_id": edge.to_asset_id,
            "relation_type": edge.relation_type,
            "metadata": loads_json(edge.metadata_json, {}),
            "created_at": edge.created_at.isoformat(),
        }
        for edge in edges
    ]


@router.get("/api/projects/{project_id}/jobs", response_model=list[JobRead])
def list_project_jobs(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    if reap_stale_running_jobs(db):
        db.commit()
    jobs = db.scalars(select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())).all()
    return [job_to_dict(item) for item in jobs]


@router.get("/api/projects/{project_id}/agent-activity", response_model=AgentActivityRead)
def get_project_agent_activity(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    if reap_stale_running_jobs(db):
        db.commit()
    recovered_session = ensure_project_full_auto_agent_session(
        db,
        store=store,
        project=project,
        created_by=request_actor_id(request),
    )
    if recovered_session is not None:
        db.flush()
        db.commit()
        if (
            request.app.state.settings.api_agent_session_supervisor_enabled
            and not supervisor_slot_active(recovered_session.id)
        ):
            start_main_agent_session_supervisor_thread(
                request.app.state.session_factory,
                store,
                project_id=project_id,
                session_id=recovered_session.id,
                supervisor_runner=run_main_agent_session_supervisor,
                turn_timeout_seconds=request.app.state.settings.agent_idle_timeout_seconds,
                turn_start_silence_timeout_seconds=request.app.state.settings.agent_turn_start_silence_timeout_seconds,
            )
    jobs = list(
        db.scalars(
            select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(30)
        ).all()
    )
    project_agent_powered_on = project.current_phase == "AUTONOMOUS_LOOP"
    observable_when_powered_off = {"starting", "running", "approval_required", "waiting_for_agent"}
    active_job_ids = active_job_ids_for_activity(jobs)
    if not project_agent_powered_on:
        active_job_ids = {
            job.id
            for job in jobs
            if job.id in active_job_ids and (not is_agentish_job(job.job_type) or job.status in observable_when_powered_off)
        }
    heartbeat_waiting_on_active_ids = {
        job.id
        for job in jobs
        if job.job_type == "continue_autonomous_session"
        and any(child_id in active_job_ids for child_id in heartbeat_waiting_child_ids(job))
    }
    workers = [
        event
        for job in jobs
        for event in worker_events_from_job(job, project_name=project.name, active_job_ids=active_job_ids)
    ]
    workers.extend(recent_agent_chat_worker_events(db, project_id=project_id, project_name=project.name))
    if not project_agent_powered_on:
        workers = [
            worker
            for worker in workers
            if (
                not is_agentish_job(str(worker.get("job_type") or ""))
                or str(worker.get("status") or "") in observable_when_powered_off
                or str(worker.get("job_id") or "") in heartbeat_waiting_on_active_ids
            )
        ]
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    raw_observation = raw_transcript_observation_for_session(session)
    session_has_process = False
    if session is not None:
        session_processes = running_codex_processes_for_project(project_id)
        session_has_process = bool(session_processes)
        last_codex_output_at = latest_codex_transcript_output_at(db, session_id=session.id)
        heartbeat_age_seconds = seconds_since_timestamp(last_codex_output_at, now=utc_now())
        response_locale = latest_project_response_locale(db, project)
        heartbeat_phrase = heartbeat_phrase_for_locale(heartbeat_age_seconds, locale=response_locale)
        running_quietly = session_has_process and heartbeat_age_seconds is not None and heartbeat_age_seconds >= 120
        retry_state = latest_agent_session_retry_state(db, session.id)
        retry_state_payload = agent_session_retry_state_payload(retry_state)
        live_session_statuses = {"starting", "running", "between_turns", "waiting_for_runner"}
        stale_live_status_while_powered_off = (
            not project_agent_powered_on
            and not session_has_process
            and session.status in live_session_statuses
        )
        session_display_status = (
            "stopped"
            if stale_live_status_while_powered_off
            else "running"
            if session.status == "running" and session_has_process
            else "between_turns"
            if session.status == "running"
            else session.status
        )
        session_active = session_has_process or (
            project_agent_powered_on and session.status in {"starting", "between_turns", "waiting_for_runner"}
        )
        retry_delay = retry_state.get("retry_delay_seconds") if retry_state else None
        japanese = locale_is_japanese(response_locale)
        retry_detail = (
            (
                f"分析エージェントをまだ起動できません。作業状態を保持し、約{int(retry_delay)}秒後に再開します。"
                if japanese
                else f"The analysis agent is not ready yet; work will resume in about {retry_delay}s."
            )
            if isinstance(retry_delay, int | float)
            else (
                "分析エージェントをまだ起動できません。作業状態を保持して再開します。"
                if japanese
                else "The analysis agent is not ready yet; the work state is preserved."
            )
        )
        include_current_work_focus = (
            project.current_phase == "AUTONOMOUS_LOOP"
            and session.status in {"starting", "running", "between_turns", "waiting_for_runner"}
        )
        current_focus = latest_agent_session_activity_focus(
            db,
            project_id=project_id,
            session_id=session.id,
            include_current_work=include_current_work_focus,
        )
        current_summary = current_focus.get("summary") if current_focus else None
        current_target_tab = current_focus.get("target_tab") if current_focus else None
        current_target_anchor = current_focus.get("target_anchor") if current_focus else None
        current_artifact_id = current_focus.get("artifact_id") if current_focus else None
        current_artifact_ids = current_focus.get("artifact_ids") if current_focus else []
        display_name = "自律分析" if japanese else "Autonomous Analyst"
        running_detail = "CodexがProject workspaceで作業中です。" if japanese else "Codex is running in the project workspace now."
        preparing_detail = (
            "次の作業を準備しています。"
            if japanese
            else "Full Auto is preparing the next step."
        )
        fallback_detail = (
            "コンテキスト準備、分析、または次の実行開始待ちです。"
            if japanese
            else "Preparing context, running analysis, or waiting for the next execution slot."
        )
        progress_wait_detail = (
            "Projectはまだアクティブです。次のstepが始まるとここに進捗が出ます。"
            if japanese
            else "The project is still active. Progress will appear here when the next step starts."
        )
        powered_off_detail = "Agent loopはOFFです。" if japanese else "The agent loop is off."
        powered_off_process_detail = (
            "Agent loopはOFFですが、停止処理中の作業がまだ残っています。"
            if japanese
            else "The agent loop is off, but stopped work is still settling."
        )
        running_headline = "静かに作業中" if japanese else "Codex is running quietly"
        working_headline = "Codexが作業中" if japanese else "Codex is working"
        retry_headline = "再開待ち" if japanese else "Waiting to resume"
        continue_headline = "次の作業を準備中" if japanese else "Preparing the next step"
        powered_off_headline = "Agent loopはOFF" if japanese else "Agent loop is off"
        powered_off_process_headline = (
            "停止処理を確認中"
            if japanese
            else "Stop is still settling"
        )
        headline = (
            powered_off_process_headline
            if not project_agent_powered_on and session_has_process
            else powered_off_headline
            if not project_agent_powered_on
            else
            running_headline
            if running_quietly
            else working_headline
            if session_has_process
            else retry_headline
            if session.status == "waiting_for_runner"
            else continue_headline
        )
        if not project_agent_powered_on and session_has_process:
            session_detail = f"{powered_off_process_detail}{heartbeat_phrase}"
        elif not project_agent_powered_on:
            session_detail = powered_off_detail
        elif session_has_process:
            session_detail = f"{current_summary or running_detail}{heartbeat_phrase}"
        elif session.status == "waiting_for_runner":
            session_detail = retry_detail
        elif session.status == "running":
            session_detail = current_summary or preparing_detail
        else:
            session_detail = (
                current_summary
                or session.last_error
                or fallback_detail
            )
        if session_has_process:
            maybe_request_codex_progress_update(
                db,
                session=session,
                locale=response_locale,
            )
        include_session_worker = project_agent_powered_on or session_has_process or session_display_status not in {
            "stopped",
            "cancelled",
        }
        if include_session_worker:
            workers.insert(
                0,
                {
                    "worker_id": "main-agent-session",
                    "display_name": display_name,
                    "status": session_display_status,
                    "headline": headline,
                    "detail": session_detail,
                    "job_id": None,
                    "job_type": "agent_session",
                    "project_id": project_id,
                    "project_name": project.name,
                    "agent_session_id": session.id,
                    "target_tab": current_target_tab or "Home",
                    "target_anchor": current_target_anchor or "agent-workspace",
                    "artifact_id": current_artifact_id,
                    "artifact_ids": current_artifact_ids if isinstance(current_artifact_ids, list) else [],
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "started_at": session.started_at.isoformat() if session.started_at else None,
                    "run_after": None,
                    "active": session_active,
                    "last_output_at": last_codex_output_at.isoformat() if last_codex_output_at else None,
                    "last_output_seconds_ago": heartbeat_age_seconds,
                    "raw_transcript": raw_observation,
                    "retry_state": retry_state_payload,
                    "human_description": {
                        "source": "agent_session",
                        "title": display_name,
                        "summary": current_summary or session_detail,
                    },
                    "token_usage": {
                        "source": "codex_cli_transcript",
                        "is_estimate": True,
                        "series": [
                            {"step": "session", "tokens": max(32, session.turn_index * 32)},
                            {"step": session.status, "tokens": max(64, session.turn_index * 64)},
                        ],
                    },
                },
            )
    if session is not None:
        workers = suppress_resolved_agent_availability_workers(workers, session_id=session.id)
    workers = merge_activity_workers(workers)
    active_workers = [worker for worker in workers if worker.get("active")]
    turn_state = build_project_turn_state(project, jobs, workers, active_job_ids=active_job_ids)
    visible_workers = visible_activity_workers(workers, now=utc_now())
    if (
        project_agent_powered_on
        and session is not None
        and session.status in {"starting", "running", "between_turns", "waiting_for_runner"}
    ):
        observed_processes = list(turn_state.get("codex_processes") or [])
        session_has_process = bool(observed_processes)
        last_codex_output_at = latest_codex_transcript_output_at(db, session_id=session.id)
        heartbeat_age_seconds = seconds_since_timestamp(last_codex_output_at, now=utc_now())
        heartbeat_phrase = heartbeat_phrase_for_locale(heartbeat_age_seconds, locale=response_locale)
        running_quietly = session_has_process and heartbeat_age_seconds is not None and heartbeat_age_seconds >= 120
        if session_has_process:
            turn_detail = f"{current_summary or running_detail}{heartbeat_phrase}"
        elif session.status == "waiting_for_runner":
            turn_detail = session_detail
        elif session.status == "running":
            turn_detail = current_summary or preparing_detail
        else:
            turn_detail = (
                current_summary
                or session.last_error
                or progress_wait_detail
            )
        turn_state = {
            **turn_state,
            "state": "agent_running" if session_has_process else "agent_scheduled",
            "owner": "agent",
            "label": headline,
            "detail": turn_detail,
            "input_attention": False,
            "confidence": "observed",
            "agent_session_id": session.id,
            "active_job_id": None,
            "active_job_type": "agent_session",
            "last_output_at": last_codex_output_at.isoformat() if last_codex_output_at else None,
            "last_output_seconds_ago": heartbeat_age_seconds,
            "raw_transcript": raw_observation,
            "retry_state": retry_state_payload,
        }
    return {
        "schema_version": "agent_activity.v1",
        "project_id": project_id,
        "generated_at": utc_now().isoformat(),
        "active_count": len(active_workers),
        "turn_state": turn_state,
        "workers": visible_workers[:20],
    }


def suppress_resolved_agent_availability_workers(workers: list[dict[str, Any]], *, session_id: str) -> list[dict[str, Any]]:
    availability_prefix = f"agent-availability-{session_id}-"
    return [
        worker
        for worker in workers
        if not (
            str(worker.get("worker_id") or "").startswith(availability_prefix)
            and str(worker.get("status") or "") == "recovering"
        )
    ]


def recent_agent_chat_worker_events(
    db: Session,
    *,
    project_id: str,
    project_name: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    worker_events: list[dict[str, Any]] = []
    for artifact in artifacts:
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except (OSError, TypeError, ValueError) as exc:
            worker_events.append(
                {
                    "worker_id": f"chat-artifact-read-issue-{artifact.id}",
                    "display_name": "Agent Chat artifact needs repair",
                    "status": "failed",
                    "headline": "Saved chat turn could not be read",
                    "detail": f"Artifact {artifact.id} is saved but its agent_chat_turn JSON could not be parsed.",
                    "job_id": None,
                    "job_type": "artifact_read_issue",
                    "project_id": project_id,
                    "project_name": project_name,
                    "target_tab": "Assets",
                    "target_anchor": "assets-artifact-preview",
                    "artifact_id": artifact.id,
                    "artifact_ids": [artifact.id],
                    "created_at": artifact.created_at.isoformat(),
                    "updated_at": artifact.created_at.isoformat(),
                    "started_at": None,
                    "run_after": None,
                    "active": False,
                    "human_description": {
                        "source": "artifact_read_issue",
                        "title": "Saved chat turn could not be read",
                        "summary": f"Artifact {artifact.id} is saved but its agent_chat_turn JSON could not be parsed.",
                        "detail": str(exc),
                    },
                    "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
                    "source_chat_artifact_id": artifact.id,
                }
            )
            continue
        events = payload.get("worker_events")
        if not isinstance(events, list):
            continue
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            normalized = normalize_agent_chat_worker_event(
                event,
                db=db,
                project_id=project_id,
                project_name=project_name,
                source_artifact=artifact,
                index=index,
            )
            if normalized is not None:
                worker_events.append(normalized)
    return worker_events


def normalize_agent_chat_worker_event(
    event: dict[str, Any],
    *,
    db: Session,
    project_id: str,
    project_name: str,
    source_artifact: Artifact,
    index: int,
) -> dict[str, Any] | None:
    worker_id = str(event.get("worker_id") or f"chat-worker-{source_artifact.id}-{index}").strip()
    display_name = str(event.get("display_name") or event.get("headline") or "Agent update").strip()
    status = str(event.get("status") or "succeeded").strip()
    if not worker_id or not display_name:
        return None
    job_id = str(event.get("job_id")).strip() if isinstance(event.get("job_id"), str) else None
    job_status: str | None = None
    if job_id:
        job = db.get(Job, job_id)
        if job is not None and job.project_id == project_id:
            job_status = job.status
    if job_status in TERMINAL_STATUSES:
        status = job_status
        active = False
    else:
        active = bool(event.get("active")) if isinstance(event.get("active"), bool) else status in {"running", "approval_required"}
    timestamp = source_artifact.created_at.isoformat()
    token_usage = event.get("token_usage") if isinstance(event.get("token_usage"), dict) else {}
    if not token_usage:
        token_usage = {"source": "not_applicable", "is_estimate": False, "series": []}
    return {
        "worker_id": worker_id,
        "display_name": display_name,
        "status": status,
        "headline": str(event.get("headline") or display_name),
        "detail": str(event.get("detail") or ""),
        "job_id": job_id,
        "job_type": str(event.get("job_type") or "agent_chat_turn"),
        "project_id": project_id,
        "project_name": project_name,
        "target_tab": event.get("target_tab") if isinstance(event.get("target_tab"), str) else None,
        "target_anchor": event.get("target_anchor") if isinstance(event.get("target_anchor"), str) else None,
        "artifact_id": event.get("artifact_id") if isinstance(event.get("artifact_id"), str) else None,
        "artifact_ids": [item for item in event.get("artifact_ids", []) if isinstance(item, str)]
        if isinstance(event.get("artifact_ids"), list)
        else [],
        "created_at": str(event.get("created_at") or timestamp),
        "updated_at": str(event.get("updated_at") or timestamp),
        "started_at": event.get("started_at") if isinstance(event.get("started_at"), str) else None,
        "run_after": event.get("run_after") if isinstance(event.get("run_after"), str) else None,
        "active": active,
        "human_description": event.get("human_description") if isinstance(event.get("human_description"), dict) else None,
        "token_usage": token_usage,
        "source_chat_artifact_id": source_artifact.id,
    }


def seconds_since_timestamp(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds()))


def latest_agent_session_activity_focus(
    db: Session,
    *,
    project_id: str,
    session_id: str,
    limit: int = 280,
    include_current_work: bool = True,
) -> dict[str, Any] | None:
    accepted_chat_sources = {
        "main_codex_session_chat_update",
        "main_agent_session_attention",
        "main_agent_session_experiment_registration",
        "main_agent_session_notebook_update",
        "main_agent_session_research_registration",
        "native_marimo_open_failure",
        "native_marimo_runtime_failure",
    }
    project = db.get(Project, project_id)
    response_locale = latest_project_response_locale(db, project) if project is not None else "en-US"
    japanese = locale_is_japanese(response_locale)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(30)
        ).all()
    )
    for artifact in chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") not in accepted_chat_sources or metadata.get("agent_session_id") != session_id:
            continue
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except (OSError, TypeError, ValueError):
            continue
        message = payload.get("assistant_message")
        if isinstance(message, str) and message.strip():
            normalized_message = normalize_agent_chat_notebook_update_message(
                payload,
                message,
                japanese=japanese,
            )
            normalized_message = normalize_agent_chat_attention_message(
                payload,
                normalized_message,
                japanese=japanese,
            )
            normalized_message = normalize_agent_chat_experiment_registration_message(
                payload,
                normalized_message,
                japanese=japanese,
            )
            normalized_message = normalize_agent_chat_native_marimo_runtime_message(
                payload,
                normalized_message,
                japanese=japanese,
            )
            target = activity_target_from_chat_payload(db, project_id=project_id, payload=payload, japanese=japanese)
            candidates.append(
                (
                    utc_datetime_or_none(artifact.created_at) or artifact.created_at,
                    {"summary": compact_activity_summary(normalized_message, limit=limit), **target},
                )
            )

    current_work = latest_research_plan_current_work(db, project_id=project_id) if include_current_work else None
    current_work_payload = research_plan_current_work_payload(current_work)
    if current_work_payload is not None:
        current_summary = human_activity_summary_or_none(str(current_work_payload.get("summary") or ""))
        current_node = str(current_work_payload.get("node_id") or "").strip()
        current_status = str(current_work_payload.get("status") or "").strip()
        if current_summary:
            summary_parts = [current_summary]
            if current_node and current_status:
                summary_parts.append(f"{current_node} · {current_status}")
            updated_at = getattr(current_work, "updated_at", None)
            candidates.append(
                (
                    utc_datetime_or_none(updated_at) or utc_now(),
                    {
                        "summary": compact_activity_summary(" — ".join(summary_parts), limit=limit),
                        "target_tab": "Home",
                        "target_anchor": "research-plan",
                        "artifact_id": None,
                        "artifact_ids": [],
                    },
                )
            )

    research_plan_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type.in_(
                    ("research_plan_request_succeeded", "research_plan_request_failed")
                ),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(5)
        ).all()
    )
    for event in research_plan_events:
        payload = loads_json(event.payload_json, {})
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        revision_id = str(result.get("revision_id") or "").strip()
        current_work_result = result.get("current_work") if isinstance(result.get("current_work"), dict) else {}
        node_id = str(result.get("node_id") or current_work_result.get("node_id") or "").strip()
        if event.event_type == "research_plan_request_failed":
            if japanese:
                summary = "作業計画の表示はまだ更新していません。分析は続いています。"
            else:
                summary = "The visible work plan has not been updated yet. The analysis is still running."
            candidates.append(
                (
                    utc_datetime_or_none(event.created_at) or event.created_at,
                    {
                        "summary": compact_activity_summary(summary, limit=limit),
                        "target_tab": "Home",
                        "target_anchor": "research-plan",
                        "artifact_id": None,
                        "artifact_ids": [],
                    },
                )
            )
            continue
        if japanese:
            summary = "Research Planを更新しました。"
            if node_id:
                summary += f" 現在地: {node_id}"
        else:
            summary = "The Research Plan was updated."
            if node_id:
                summary += f" Current node: {node_id}"
        candidates.append(
            (
                utc_datetime_or_none(event.created_at) or event.created_at,
                {
                    "summary": compact_activity_summary(summary, limit=limit),
                    "target_tab": "Home",
                    "target_anchor": "research-plan",
                    "artifact_id": None,
                    "artifact_ids": [],
                    "research_plan_revision_id": revision_id or None,
                },
            )
        )

    experiment_result_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type.in_(
                    ("experiment_result_request_succeeded", "experiment_result_request_failed")
                ),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(5)
        ).all()
    )
    for event in experiment_result_events:
        payload = loads_json(event.payload_json, {})
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        registered_run_ids = [
            item for item in result.get("registered_run_ids", []) if isinstance(item, str) and item.strip()
        ] if isinstance(result.get("registered_run_ids"), list) else []
        if event.event_type == "experiment_result_request_succeeded":
            if japanese:
                summary = f"モデル評価結果をLeaderboardに登録しました。{len(registered_run_ids)}件のrunを比較できます。"
            else:
                summary = f"Experiment results were registered on the Leaderboard. {len(registered_run_ids)} run(s) are comparable."
            candidates.append(
                (
                    utc_datetime_or_none(event.created_at) or event.created_at,
                    {
                        "summary": compact_activity_summary(summary, limit=limit),
                        "target_tab": "Leaderboard",
                        "target_anchor": "result-readout",
                        "artifact_id": None,
                        "artifact_ids": [],
                        "run_ids": registered_run_ids,
                    },
                )
            )
            continue
        if japanese:
            summary = "モデル評価結果はまだLeaderboardに反映していません。表示中の順位表はそのまま保持し、分析は続いています。"
        else:
            summary = "The model evaluation results have not been added to the Leaderboard yet. The visible ranking is unchanged, and the analysis is continuing."
        candidates.append(
            (
                utc_datetime_or_none(event.created_at) or event.created_at,
                {
                    "summary": compact_activity_summary(summary, limit=limit),
                    "target_tab": "Home",
                    "target_anchor": "agent-workspace",
                    "artifact_id": None,
                    "artifact_ids": [],
                },
            )
        )

    notebook_request_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type.in_(("notebook_request_succeeded", "notebook_request_failed")),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(5)
        ).all()
    )
    for event in notebook_request_events:
        payload = loads_json(event.payload_json, {})
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        notebook_artifact_id = str(result.get("notebook_artifact_id") or event.artifact_id or "").strip()
        plan_node_id = str(result.get("research_plan_node_id") or "").strip()
        if event.event_type == "notebook_request_succeeded":
            if japanese:
                summary = "marimo notebookを登録しました。Tablex内のnative marimo viewerで開けます。"
                if plan_node_id:
                    summary += f" ResearchPlan: {plan_node_id}"
            else:
                summary = "A marimo notebook was registered and can be opened in the native Tablex viewer."
                if plan_node_id:
                    summary += f" ResearchPlan: {plan_node_id}"
            candidates.append(
                (
                    utc_datetime_or_none(event.created_at) or event.created_at,
                    {
                        "summary": compact_activity_summary(summary, limit=limit),
                        "target_tab": "Notebooks",
                        "target_anchor": "notebook-native-marimo-top",
                        "artifact_id": notebook_artifact_id or None,
                        "artifact_ids": [notebook_artifact_id] if notebook_artifact_id else [],
                    },
                )
            )
            continue
        if japanese:
            summary = "marimo notebookはまだ登録していません。未完成のNotebookとしては表示せず、分析は続いています。"
        else:
            summary = "The marimo notebook has not been registered yet. It is not shown as complete, and the analysis is continuing."
        candidates.append(
            (
                utc_datetime_or_none(event.created_at) or event.created_at,
                {
                    "summary": compact_activity_summary(summary, limit=limit),
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": None,
                    "artifact_ids": [],
                },
            )
        )

    pilot_observation_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "tablex_sidecar",
                AgentTranscriptEvent.event_type == "pilot_observation_available",
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(5)
        ).all()
    )
    for event in pilot_observation_events:
        payload = loads_json(event.payload_json, {})
        report_artifact_id = str(payload.get("pilot_scoring_report_artifact_id") or event.artifact_id or "").strip()
        matched_rows = payload.get("matched_rows")
        metric_count = payload.get("metric_count")
        if japanese:
            summary = "仮運用の観察結果が届きました。Codexがvalidation schemeの監査と次の改善サイクルに使えます。"
            if isinstance(metric_count, int) and isinstance(matched_rows, int):
                summary += f" 突合 {matched_rows}行 / scoring {metric_count}行。"
        else:
            summary = "A pilot observation is available. Codex can use it to audit the validation scheme and continue the next improvement cycle."
            if isinstance(metric_count, int) and isinstance(matched_rows, int):
                summary += f" Matched {matched_rows} row(s); scored {metric_count} row(s)."
        candidates.append(
            (
                utc_datetime_or_none(event.created_at) or event.created_at,
                {
                    "summary": compact_activity_summary(summary, limit=limit),
                    "target_tab": "Leaderboard",
                    "target_anchor": "pilot",
                    "artifact_id": report_artifact_id or None,
                    "artifact_ids": [report_artifact_id] if report_artifact_id else [],
                },
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def latest_agent_session_activity_summary(db: Session, *, project_id: str, session_id: str, limit: int = 280) -> str | None:
    focus = latest_agent_session_activity_focus(db, project_id=project_id, session_id=session_id, limit=limit)
    return focus.get("summary") if focus else None


def human_activity_summary_or_none(message: str) -> str | None:
    text = message.strip()
    if not text:
        return None
    lowered = text.lower()
    command_prefixes = (
        "/bin/bash",
        "bash ",
        "python ",
        "python3 ",
        ".tablex/bin/python",
        "$ ",
    )
    if lowered.startswith(command_prefixes):
        return None
    if text.startswith("{") and '"schema_version"' in text:
        return None
    if "schema_version" in lowered and "operation" in lowered and ".tablex/requests" in lowered:
        return None
    if lowered.startswith("usage:"):
        return None
    return text


def activity_target_from_chat_payload(
    db: Session,
    *,
    project_id: str,
    payload: dict[str, Any],
    japanese: bool = False,
) -> dict[str, Any]:
    actions = payload.get("actions")
    if isinstance(actions, list):
        normalized_actions = normalize_agent_chat_navigation_actions(
            actions,
            db=db,
            project_id=project_id,
            japanese=japanese,
        )
        for action in normalized_actions:
            if not isinstance(action, dict):
                continue
            target_tab = action.get("target_tab")
            if not isinstance(target_tab, str) or not target_tab.strip():
                continue
            target_anchor = action.get("target_anchor")
            artifact_id = action.get("artifact_id")
            artifact_ids = action.get("artifact_ids")
            normalized_anchor = normalize_agent_chat_navigation_focus(
                {
                    "target_tab": target_tab.strip(),
                    "target_anchor": target_anchor.strip() if isinstance(target_anchor, str) and target_anchor.strip() else None,
                }
            ).get("target_anchor")
            return {
                "target_tab": target_tab.strip(),
                "target_anchor": normalized_anchor if isinstance(normalized_anchor, str) and normalized_anchor.strip() else None,
                "artifact_id": artifact_id.strip() if isinstance(artifact_id, str) and artifact_id.strip() else None,
                "artifact_ids": [item for item in artifact_ids if isinstance(item, str) and item.strip()]
                if isinstance(artifact_ids, list)
                else [],
            }
    next_focus = payload.get("next_focus")
    if isinstance(next_focus, dict):
        next_focus = normalize_agent_chat_navigation_focus(next_focus)
        next_focus = normalize_agent_chat_notebook_action_artifact(
            db,
            project_id=project_id,
            action=next_focus,
            japanese=japanese,
        )
        target_tab = next_focus.get("target_tab")
        if isinstance(target_tab, str) and target_tab.strip():
            target_anchor = next_focus.get("target_anchor")
            artifact_id = next_focus.get("artifact_id")
            artifact_ids = next_focus.get("artifact_ids")
            normalized_anchor = normalize_agent_chat_navigation_focus(
                {
                    "target_tab": target_tab.strip(),
                    "target_anchor": target_anchor.strip() if isinstance(target_anchor, str) and target_anchor.strip() else None,
                }
            ).get("target_anchor")
            return {
                "target_tab": target_tab.strip(),
                "target_anchor": normalized_anchor if isinstance(normalized_anchor, str) and normalized_anchor.strip() else None,
                "artifact_id": artifact_id.strip() if isinstance(artifact_id, str) and artifact_id.strip() else None,
                "artifact_ids": [item for item in artifact_ids if isinstance(item, str) and item.strip()]
                if isinstance(artifact_ids, list)
                else [],
            }
    return {"target_tab": None, "target_anchor": None, "artifact_id": None, "artifact_ids": []}


def compact_activity_summary(message: str, *, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", message).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 0)].rstrip() + "…"


def format_elapsed_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    return f"{hours}h {remaining_minutes}m" if remaining_minutes else f"{hours}h"


def heartbeat_phrase_for_locale(seconds: int | None, *, locale: str | None) -> str:
    if seconds is None:
        return ""
    if locale_is_japanese(locale):
        return f" 最終出力は{format_elapsed_seconds_ja(seconds)}前です。"
    return f" Last observed output was {format_elapsed_seconds(seconds)} ago."


def format_elapsed_seconds_ja(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    return f"{hours}時間{remaining_minutes}分" if remaining_minutes else f"{hours}時間"


def latest_agent_session_retry_state(db: Session, session_id: str) -> dict[str, Any] | None:
    event = db.scalar(
        select(AgentTranscriptEvent)
        .where(
            AgentTranscriptEvent.session_id == session_id,
            AgentTranscriptEvent.event_type.in_(
                [
                    "runner_retry_scheduled",
                    "turn_recovery_scheduled",
                    "process_timeout",
                    "process_killed_after_timeout",
                ]
            ),
        )
        .order_by(AgentTranscriptEvent.event_index.desc())
        .limit(1)
    )
    if event is None:
        return None
    payload = loads_json(event.payload_json, {})
    payload["event_type"] = event.event_type
    payload["event_index"] = event.event_index
    payload["created_at"] = event.created_at.isoformat()
    return payload


def agent_session_retry_state_payload(retry_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not retry_state:
        return None
    payload: dict[str, Any] = {}
    for key in (
        "event_type",
        "event_index",
        "created_at",
        "retry_delay_seconds",
        "failure_kind",
        "exit_code",
        "idle_timeout_seconds",
    ):
        value = retry_state.get(key)
        if value is not None:
            payload[key] = value
    return payload or None


def visible_activity_workers(workers: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for worker in workers:
        if worker.get("active"):
            visible.append(worker)
            continue
        status = str(worker.get("status") or "")
        if status in {"starting", "running", "approval_required", "between_turns", "waiting_for_runner"}:
            visible.append(worker)
            continue
        updated_at = parse_worker_event_time(worker.get("updated_at") or worker.get("created_at"))
        if updated_at is not None and (now - updated_at).total_seconds() <= 15:
            visible.append(worker)
    return limit_terminal_data_intake_activity_workers(visible, limit=5)


def limit_terminal_data_intake_activity_workers(workers: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    terminal_data_intake_count = 0
    for worker in workers:
        job_type = str(worker.get("job_type") or "")
        status = str(worker.get("status") or "")
        if job_type in {"upload_data_bundle", "import_benchmark_dataset"} and status in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        }:
            terminal_data_intake_count += 1
            if terminal_data_intake_count > limit:
                continue
        visible.append(worker)
    return visible


def merge_activity_workers(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for worker in workers:
        identity = activity_worker_identity(worker)
        existing = merged.get(identity)
        merged[identity] = merge_activity_worker(existing, worker) if existing is not None else worker
    return list(merged.values())


def activity_worker_identity(worker: dict[str, Any]) -> str:
    session_id = worker.get("agent_session_id")
    if isinstance(session_id, str) and session_id.strip():
        return f"session:{session_id.strip()}"
    job_id = worker.get("job_id")
    worker_id = worker.get("worker_id")
    if isinstance(job_id, str) and job_id.strip():
        if isinstance(worker_id, str) and worker_id.strip():
            return f"job:{job_id.strip()}:worker:{worker_id.strip()}"
        return f"job:{job_id.strip()}"
    return f"worker:{str(worker_id or '').strip()}:{worker.get('created_at') or worker.get('updated_at') or 'event'}"


def merge_activity_worker(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    primary, secondary = preferred_activity_worker(left, right), left
    if primary is left:
        secondary = right
    merged = {**secondary, **primary}
    for key in ("project_name", "human_description", "raw_transcript", "retry_state", "started_at", "run_after"):
        if merged.get(key) is None and secondary.get(key) is not None:
            merged[key] = secondary[key]
    primary_token_usage = primary.get("token_usage")
    secondary_token_usage = secondary.get("token_usage")
    if (
        isinstance(primary_token_usage, dict)
        and isinstance(secondary_token_usage, dict)
        and primary_token_usage.get("is_estimate") is True
        and secondary_token_usage.get("is_estimate") is False
    ):
        merged["token_usage"] = secondary_token_usage
    return merged


def preferred_activity_worker(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rank = activity_worker_status_rank(left.get("status"))
    right_rank = activity_worker_status_rank(right.get("status"))
    if left_rank != right_rank:
        return left if left_rank < right_rank else right
    if bool(left.get("active")) != bool(right.get("active")):
        return left if left.get("active") else right
    left_token_usage = left.get("token_usage")
    right_token_usage = right.get("token_usage")
    left_estimate = not isinstance(left_token_usage, dict) or left_token_usage.get("is_estimate") is not False
    right_estimate = not isinstance(right_token_usage, dict) or right_token_usage.get("is_estimate") is not False
    if left_estimate != right_estimate:
        return right if left_estimate else left
    left_description_score = activity_worker_description_score(left)
    right_description_score = activity_worker_description_score(right)
    if left_description_score != right_description_score:
        return left if left_description_score > right_description_score else right
    left_time = parse_worker_event_time(left.get("updated_at") or left.get("created_at"))
    right_time = parse_worker_event_time(right.get("updated_at") or right.get("created_at"))
    if left_time is not None and right_time is not None and left_time != right_time:
        return left if left_time > right_time else right
    return right


def activity_worker_status_rank(status: Any) -> int:
    status_text = str(status or "")
    if status_text == "running":
        return 0
    if status_text == "approval_required":
        return 1
    if status_text in {"starting", "between_turns", "waiting_for_runner", "waiting_for_agent"}:
        return 2
    if status_text == "queued":
        return 3
    return 4


def activity_worker_description_score(worker: dict[str, Any]) -> int:
    score = 0
    for key in ("headline", "detail", "display_name"):
        if isinstance(worker.get(key), str) and worker[key].strip():
            score += 1
    description = worker.get("human_description")
    if isinstance(description, dict):
        if isinstance(description.get("title"), str) and description["title"].strip():
            score += 1
        if isinstance(description.get("summary"), str) and description["summary"].strip():
            score += 1
    return score


def parse_worker_event_time(value: Any) -> datetime | None:
    return parse_api_datetime(value)


def parse_api_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@router.post("/api/jobs", response_model=JobRead)
def enqueue_job(
    payload: JobCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    if payload.project_id:
        require_project(db, payload.project_id)
    job = create_job(
        db,
        job_type=payload.job_type,
        project_id=payload.project_id,
        input_payload=payload.input,
        context=payload.context,
        policy=payload.policy,
        dependency_job_ids=payload.dependency_job_ids,
        priority=payload.priority,
        max_attempts=payload.max_attempts,
        approval_required=payload.approval_required,
        created_by=request_actor_id(request),
    )
    return job_to_dict(job)


@router.get("/api/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_dict(job)


@router.get("/api/jobs/{job_id}/artifacts")
def get_job_artifacts(job_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    output = loads_json(job.output_json, {})
    artifact_ids = collect_output_artifact_ids(output)
    artifacts_by_id = {
        artifact.id: artifact
        for artifact in db.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all()
    } if artifact_ids else {}
    artifacts = [artifacts_by_id[artifact_id] for artifact_id in artifact_ids if artifact_id in artifacts_by_id]
    return {
        "job": job_to_dict(job),
        "summary": summarize_job_output(output),
        "artifact_ids": artifact_ids,
        "missing_artifact_ids": [artifact_id for artifact_id in artifact_ids if artifact_id not in artifacts_by_id],
        "artifacts": [artifact_to_dict(artifact) for artifact in artifacts],
    }


@router.post("/api/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancel_job_service(job, cancelled_by=request_actor_id(request))
    return job_to_dict(job)


@router.post("/api/jobs/{job_id}/approve", response_model=JobRead)
def approve_job_endpoint(
    job_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    approve_job(job, approved_by=request_actor_id(request))
    return job_to_dict(job)


@router.post("/api/jobs/{job_id}/retry", response_model=JobRead)
def retry_job_endpoint(job_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        retry_job(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/worker/run-once", response_model=JobRead | None)
def run_worker_once(
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    include_long_running: Annotated[
        bool,
        Query(
            description=(
                "When false, the interactive endpoint only runs lightweight jobs that are safe to execute inside "
                "the request. Long-running worker jobs should be picked up by the daemon or an explicit test harness."
            )
        ),
    ] = False,
) -> dict[str, Any] | None:
    worker = create_default_worker(store=store, include_stub_handlers=False)
    job = worker.run_next_job(db, job_types=None if include_long_running else INTERACTIVE_WORKER_JOB_TYPES)
    if job is None:
        return None
    return job_to_dict(job)


@router.post("/api/jobs/{job_id}/run", response_model=JobRead)
def run_job_now(
    job_id: str,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "approval_required":
        raise HTTPException(status_code=400, detail="Job requires approval before it can run")
    if job.status != "queued":
        return job_to_dict(job)
    job.priority = max(job.priority, 90)
    job.updated_at = utc_now()
    return job_to_dict(job)


@router.post("/api/assets/seed-defaults", response_model=list[AssetRead])
def seed_assets_endpoint(
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> list[dict[str, Any]]:
    assets = seed_default_assets(db, store)
    return [asset_to_dict(asset) for asset in assets]


@router.get("/api/assets", response_model=list[AssetRead])
def list_assets(
    db: Annotated[Session, Depends(get_session)],
    asset_type: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Asset).order_by(Asset.asset_type, Asset.name)
    if asset_type:
        stmt = select(Asset).where(Asset.asset_type == asset_type).order_by(Asset.name)
    assets = db.scalars(stmt).all()
    return [asset_to_dict(asset) for asset in assets]


@router.post("/api/assets", response_model=AssetRead)
def create_asset_endpoint(
    payload: AssetCreate,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    asset_payload = payload.model_dump()
    asset_payload["owner_user_id"] = request_actor_id(request)
    asset = create_library_asset(db, store=store, payload=asset_payload)
    return asset_to_dict(asset)


@router.get("/api/assets/{asset_id}/versions", response_model=list[AssetVersionRead])
def list_asset_versions(asset_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    versions = db.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset_id).order_by(AssetVersion.created_at.desc())).all()
    return [asset_version_to_dict(version) for version in versions]


@router.get("/api/projects/{project_id}/asset-references", response_model=list[AssetReferenceRead])
def list_project_asset_references(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    references = db.scalars(
        select(AssetReference).where(AssetReference.source_type == "project", AssetReference.source_id == project_id)
    ).all()
    return [expanded_asset_reference_to_dict(db, reference) for reference in references]


@router.post("/api/projects/{project_id}/asset-references", response_model=AssetReferenceRead)
def create_project_asset_reference(
    project_id: str,
    payload: AssetReferenceCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    require_project(db, project_id)
    try:
        reference = create_asset_reference(
            db,
            source_type="project",
            source_id=project_id,
            target_asset_id=payload.target_asset_id,
            target_asset_version_id=payload.target_asset_version_id,
            relation_type=payload.relation_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    create_lineage_edge(
        db,
        project_id=project_id,
        from_asset_type="project",
        from_asset_id=project_id,
        to_asset_type="library_asset",
        to_asset_id=payload.target_asset_id,
        relation_type=payload.relation_type,
    )
    return expanded_asset_reference_to_dict(db, reference)


@router.get("/api/ideas/{idea_id}/asset-references", response_model=list[AssetReferenceRead])
def list_idea_asset_references(idea_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    references = db.scalars(
        select(AssetReference).where(AssetReference.source_type == "idea", AssetReference.source_id == idea_id)
    ).all()
    return [expanded_asset_reference_to_dict(db, reference) for reference in references]


@router.post("/api/ideas/{idea_id}/asset-references", response_model=AssetReferenceRead)
def create_idea_asset_reference(
    idea_id: str,
    payload: AssetReferenceCreate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    try:
        reference = create_asset_reference(
            db,
            source_type="idea",
            source_id=idea_id,
            target_asset_id=payload.target_asset_id,
            target_asset_version_id=payload.target_asset_version_id,
            relation_type=payload.relation_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    create_lineage_edge(
        db,
        project_id=idea.project_id,
        from_asset_type="idea",
        from_asset_id=idea_id,
        to_asset_type="library_asset",
        to_asset_id=payload.target_asset_id,
        relation_type=payload.relation_type,
    )
    return expanded_asset_reference_to_dict(db, reference)


def latest_benchmark_import_local_status(db: Session, project_id: str, benchmark_id: str) -> dict[str, Any] | None:
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
        payload = json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    local_status = payload.get("local_status")
    return cast(dict[str, Any], local_status) if isinstance(local_status, dict) else None


def store_and_register_json(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    filename: str,
    payload: Any,
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project_id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_json(
        org_id="local-org",
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        payload=payload,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
    )


def store_and_register_text(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    filename: str,
    text: str,
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project_id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_text(
        org_id="local-org",
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        text=text,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
    )


def delete_project_rows(db: Session, project_id: str) -> None:
    artifact_ids = select(Artifact.id).where(Artifact.project_id == project_id)
    question_ids = select(Question.id).where(Question.project_id == project_id)
    assumption_ids = select(Assumption.id).where(Assumption.project_id == project_id)
    evidence_ids = select(Evidence.id).where(Evidence.project_id == project_id)
    agent_session_ids = select(AgentSession.id).where(AgentSession.project_id == project_id)
    asset_version_ids = [
        item
        for item in db.scalars(
            select(AssetVersion.id).where(
                (AssetVersion.created_from_project_id == project_id)
                | (AssetVersion.artifact_id.in_(artifact_ids))
            )
        ).all()
    ]
    affected_asset_ids = (
        [
            item
            for item in db.scalars(
                select(AssetVersion.asset_id).where(AssetVersion.id.in_(asset_version_ids))
            ).all()
        ]
        if asset_version_ids
        else []
    )

    db.execute(delete(AssetReference).where(AssetReference.source_id == project_id))
    if asset_version_ids:
        db.execute(delete(AssetReference).where(AssetReference.target_asset_version_id.in_(asset_version_ids)))
        db.execute(delete(AssetVersion).where(AssetVersion.id.in_(asset_version_ids)))
        for asset_id in set(affected_asset_ids):
            asset = db.get(Asset, asset_id)
            if asset is None:
                continue
            latest_version = db.scalar(
                select(AssetVersion)
                .where(AssetVersion.asset_id == asset_id)
                .order_by(AssetVersion.created_at.desc())
            )
            asset.latest_version_id = latest_version.id if latest_version is not None else None
            if latest_version is None:
                asset.status = "deleted"
    db.execute(delete(AgentSupervisorLease).where(AgentSupervisorLease.session_id.in_(agent_session_ids)))
    db.execute(delete(AgentTranscriptEvent).where(AgentTranscriptEvent.project_id == project_id))
    db.execute(delete(AgentSession).where(AgentSession.project_id == project_id))
    db.execute(delete(Job).where(Job.project_id == project_id))
    db.execute(delete(ResearchPlanCurrentWork).where(ResearchPlanCurrentWork.project_id == project_id))
    db.execute(
        update(ResearchPlanRevision)
        .where(ResearchPlanRevision.project_id == project_id)
        .values(parent_revision_id=None, source_artifact_id=None)
    )
    db.execute(delete(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project_id))
    db.execute(delete(ResearchPlan).where(ResearchPlan.project_id == project_id))
    db.execute(delete(LineageEdge).where(LineageEdge.project_id == project_id))
    db.execute(delete(Idea).where(Idea.project_id == project_id))
    db.execute(delete(ResearchBrief).where(ResearchBrief.project_id == project_id))
    db.execute(delete(ModelVersion).where(ModelVersion.project_id == project_id))
    db.execute(delete(ExperimentRun).where(ExperimentRun.project_id == project_id))
    db.execute(delete(SplitManifest).where(SplitManifest.project_id == project_id))
    db.execute(delete(EvaluationSpec).where(EvaluationSpec.project_id == project_id))
    db.execute(delete(EvaluationCandidate).where(EvaluationCandidate.project_id == project_id))
    db.execute(delete(Insight).where(Insight.project_id == project_id))
    db.execute(delete(VisualizationSpec).where(VisualizationSpec.project_id == project_id))
    db.execute(delete(Report).where(Report.project_id == project_id))
    db.execute(delete(AssumptionEvidenceLink).where(AssumptionEvidenceLink.assumption_id.in_(assumption_ids)))
    db.execute(delete(AssumptionEvidenceLink).where(AssumptionEvidenceLink.evidence_id.in_(evidence_ids)))
    db.execute(delete(Answer).where(Answer.question_id.in_(question_ids)))
    db.execute(delete(Question).where(Question.project_id == project_id))
    db.execute(delete(Assumption).where(Assumption.project_id == project_id))
    db.execute(delete(Evidence).where(Evidence.project_id == project_id))
    db.execute(delete(SemanticCatalog).where(SemanticCatalog.project_id == project_id))
    db.execute(delete(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id))
    db.execute(delete(Artifact).where(Artifact.project_id == project_id))


def schedule_project_artifact_cleanup(settings: Any, *, org_id: str, project_id: str) -> dict[str, Any]:
    targets = project_artifact_cleanup_targets(settings, org_id=org_id, project_id=project_id)
    thread = threading.Thread(
        target=remove_project_artifact_roots,
        kwargs={"settings": settings, "targets": targets},
        name=f"tablex-project-artifact-cleanup-{project_id}",
        daemon=True,
    )
    try:
        thread.start()
    except RuntimeError as exc:
        LOGGER.exception("Failed to schedule artifact cleanup for deleted project %s.", project_id)
        return {
            "status": "failed_to_schedule",
            "target_count": len(targets),
            "error": str(exc),
        }
    return {
        "status": "scheduled",
        "target_count": len(targets),
    }


def project_artifact_cleanup_targets(settings: Any, *, org_id: str, project_id: str) -> list[Path]:
    return [
        settings.artifact_root / org_id / project_id,
        settings.artifact_root / "agent_sessions" / project_id,
        settings.artifact_root / "_workspaces" / project_id,
    ]


def remove_project_artifact_roots(settings: Any, *, targets: list[Path]) -> None:
    allowed_roots = [
        settings.artifact_root.resolve(),
    ]
    seen: set[Path] = set()
    for candidate in targets:
        try:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            remove_path_if_under_allowed_roots(resolved, allowed_roots)
        except OSError:
            LOGGER.exception("Failed to remove project artifact path %s.", candidate)


def remove_project_artifact_directories(settings: Any, project: Project, artifact_dirs: list[Path]) -> None:
    del artifact_dirs
    targets = project_artifact_cleanup_targets(settings, org_id=project.org_id, project_id=project.id)
    remove_project_artifact_roots(settings, targets=targets)


def remove_path_if_under_allowed_roots(path: Path, allowed_roots: list[Path]) -> None:
    resolved = path.resolve()
    if not any(path_is_under(resolved, root) for root in allowed_roots):
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
    elif resolved.exists():
        resolved.unlink(missing_ok=True)


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_dataset(db: Session, dataset_id: str) -> DatasetSnapshot:
    dataset = db.get(DatasetSnapshot, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="DatasetSnapshot not found")
    return dataset


def require_assumption(db: Session, assumption_id: str) -> Assumption:
    assumption = db.get(Assumption, assumption_id)
    if assumption is None:
        raise HTTPException(status_code=404, detail="Assumption not found")
    return assumption


def require_eval_spec(db: Session, spec_id: str) -> EvaluationSpec:
    spec = db.get(EvaluationSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="EvaluationSpec not found")
    return spec


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    project = db.get(Project, project_id)
    if project is not None and project.primary_dataset_snapshot_id:
        primary = db.get(DatasetSnapshot, project.primary_dataset_snapshot_id)
        if primary is not None and primary.project_id == project_id:
            return primary
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
        select(SplitManifest)
        .where(SplitManifest.evaluation_spec_id == spec_id)
        .order_by(SplitManifest.created_at.desc())
    )


def latest_research_brief(db: Session, project_id: str) -> ResearchBrief | None:
    return db.scalar(
        select(ResearchBrief).where(ResearchBrief.project_id == project_id).order_by(ResearchBrief.created_at.desc())
    )


def latest_profile_for_dataset(db: Session, dataset: DatasetSnapshot) -> dict[str, Any]:
    artifact = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == dataset.project_id, Artifact.asset_type == "eda_profile")
        .order_by(Artifact.created_at.desc())
    )
    if artifact is None:
        return {}
    return cast(
        dict[str, Any],
        json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")),
    )


def count_rows(db: Session, model: type[Any], project_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.project_id == project_id)) or 0)


def count_latest_artifacts(db: Session, project_id: str, asset_type: str | None = None) -> int:
    subquery = select(Artifact.asset_type, Artifact.name).where(Artifact.project_id == project_id)
    if asset_type:
        subquery = subquery.where(Artifact.asset_type == asset_type)
    grouped = subquery.group_by(Artifact.asset_type, Artifact.name).subquery()
    return int(db.scalar(select(func.count()).select_from(grouped)) or 0)


def latest_artifact_rows(
    db: Session,
    project_id: str,
    *,
    limit: int | None = None,
    asset_type: str | None = None,
) -> list[Artifact]:
    latest_versions = (
        select(
            Artifact.asset_type.label("asset_type"),
            Artifact.name.label("name"),
            func.max(Artifact.version).label("version"),
        )
        .where(Artifact.project_id == project_id)
        .group_by(Artifact.asset_type, Artifact.name)
    )
    if asset_type:
        latest_versions = latest_versions.where(Artifact.asset_type == asset_type)
    latest_versions_subquery = latest_versions.subquery()
    query = (
        select(Artifact)
        .join(
            latest_versions_subquery,
            and_(
                Artifact.asset_type == latest_versions_subquery.c.asset_type,
                Artifact.name == latest_versions_subquery.c.name,
                Artifact.version == latest_versions_subquery.c.version,
            ),
        )
        .where(Artifact.project_id == project_id)
        .order_by(Artifact.created_at.desc())
    )
    if limit is not None:
        query = query.limit(max(1, min(limit, 5000)))
    return list(db.scalars(query).all())


def leaderboard_sort_key(run: ExperimentRun) -> tuple[int, float]:
    metrics = loads_json(run.metrics_json, {})
    metric_name = metrics.get("primary_metric_name")
    metric_value = metrics.get("primary_metric_value")
    if metric_value is None:
        return (1, 0.0)
    value = float(metric_value)
    if metric_name in {"rmse", "mae", "log_loss"}:
        return (0, value)
    return (0, -value)


def next_actions(project: Project, counts: dict[str, int]) -> list[str]:
    actions: list[str] = []
    if counts["datasets"] == 0:
        actions.append("Upload a CSV or Parquet dataset.")
    if counts["questions"] > 0 and counts["assumptions"] > 0:
        actions.append("Review open questions and high-risk assumptions.")
    if counts["evaluation_candidates"] == 0 and counts["datasets"] > 0:
        actions.append("Design evaluation candidates.")
    if counts["evaluation_specs"] == 0 and counts["evaluation_candidates"] > 0:
        actions.append("Promote and approve an EvaluationSpec.")
    if not actions:
        actions.append("Run the next job from the project tabs.")
    return actions


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "org_id": project.org_id,
        "name": project.name,
        "description": project.description,
        "task_type": project.task_type,
        "target_column": project.target_column,
        "primary_dataset_snapshot_id": project.primary_dataset_snapshot_id,
        "current_phase": project.current_phase,
        "status": project.status,
        "autonomy_mode": project.autonomy_mode,
        "created_by": project.created_by,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def dataset_to_dict(dataset: DatasetSnapshot, *, primary_dataset_snapshot_id: str | None = None) -> dict[str, Any]:
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
        "is_primary": dataset.id == primary_dataset_snapshot_id,
        "created_at": dataset.created_at.isoformat(),
    }


def semantic_catalog_to_dict(catalog: SemanticCatalog) -> dict[str, Any]:
    return {
        "id": catalog.id,
        "project_id": catalog.project_id,
        "dataset_snapshot_id": catalog.dataset_snapshot_id,
        "artifact_id": catalog.artifact_id,
        "columns": loads_json(catalog.columns_json, []),
        "created_at": catalog.created_at.isoformat(),
    }


def question_to_dict(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "project_id": question.project_id,
        "question_set_id": question.question_set_id,
        "topic": question.topic,
        "question": question.question,
        "why_it_matters": question.why_it_matters,
        "default_assumption": question.default_assumption,
        "impact_if_wrong": question.impact_if_wrong,
        "choices": loads_json(question.choices_json, []),
        "status": question.status,
        "priority": question.priority,
        "risk_level": question.risk_level,
        "value_of_answer": question.value_of_answer,
        "can_proceed_without_answer": question.can_proceed_without_answer,
        "fallback_policy": question.fallback_policy,
        "related_assumption_id": question.related_assumption_id,
        "blocks_next_phase": question.blocks_next_phase,
        "created_at": question.created_at.isoformat(),
    }


def answer_to_dict(answer: Answer) -> dict[str, Any]:
    return {
        "id": answer.id,
        "question_id": answer.question_id,
        "answered_by": answer.answered_by,
        "answer_value": answer.answer_value,
        "answer_text": answer.answer_text,
        "created_at": answer.created_at.isoformat(),
    }


def assumption_to_dict(db: Session, assumption: Assumption) -> dict[str, Any]:
    links = db.scalars(select(AssumptionEvidenceLink).where(AssumptionEvidenceLink.assumption_id == assumption.id)).all()
    evidence: list[dict[str, Any]] = []
    if links:
        evidence_records = db.scalars(select(Evidence).where(Evidence.id.in_([link.evidence_id for link in links]))).all()
        evidence = [evidence_to_dict(item) for item in evidence_records]
    return {
        "id": assumption.id,
        "project_id": assumption.project_id,
        "topic": assumption.topic,
        "subject_type": assumption.subject_type,
        "subject_ref": assumption.subject_ref,
        "statement": assumption.statement,
        "status": assumption.status,
        "confidence": assumption.confidence,
        "risk_level": assumption.risk_level,
        "fallback_policy": assumption.fallback_policy,
        "requires_user_confirmation": assumption.requires_user_confirmation,
        "evidence": evidence,
        "created_at": assumption.created_at.isoformat(),
        "updated_at": assumption.updated_at.isoformat(),
    }


def evidence_to_dict(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "project_id": evidence.project_id,
        "evidence_type": evidence.evidence_type,
        "summary": evidence.summary,
        "strength": evidence.strength,
        "source_artifact_id": evidence.source_artifact_id,
        "metadata": loads_json(evidence.metadata_json, {}),
        "created_at": evidence.created_at.isoformat(),
    }


def split_to_dict(split: SplitManifest) -> dict[str, Any]:
    return {
        "id": split.id,
        "project_id": split.project_id,
        "evaluation_spec_id": split.evaluation_spec_id,
        "artifact_id": split.artifact_id,
        "train_count": split.train_count,
        "valid_count": split.valid_count,
        "test_count": split.test_count,
        "summary": loads_json(split.summary_json, {}),
        "created_at": split.created_at.isoformat(),
    }


def model_version_to_dict(model_version: ModelVersion) -> dict[str, Any]:
    return {
        "id": model_version.id,
        "project_id": model_version.project_id,
        "experiment_run_id": model_version.experiment_run_id,
        "dataset_snapshot_id": model_version.dataset_snapshot_id,
        "evaluation_spec_id": model_version.evaluation_spec_id,
        "split_manifest_id": model_version.split_manifest_id,
        "artifact_id": model_version.artifact_id,
        "name": model_version.name,
        "version": model_version.version,
        "model_family": model_version.model_family,
        "model_type": model_version.model_type,
        "task_type": model_version.task_type,
        "target_column": model_version.target_column,
        "primary_metric_name": model_version.primary_metric_name,
        "primary_metric_value": model_version.primary_metric_value,
        "metrics": loads_json(model_version.metrics_json, {}),
        "params": loads_json(model_version.params_json, {}),
        "status": model_version.status,
        "created_at": model_version.created_at.isoformat(),
    }


def research_brief_to_dict(brief: ResearchBrief) -> dict[str, Any]:
    return {
        "id": brief.id,
        "project_id": brief.project_id,
        "dataset_snapshot_id": brief.dataset_snapshot_id,
        "evaluation_spec_id": brief.evaluation_spec_id,
        "title": brief.title,
        "question": brief.question,
        "summary_md": brief.summary_md,
        "sources": loads_json(brief.sources_json, []),
        "key_findings": loads_json(brief.key_findings_json, []),
        "recommended_approaches": loads_json(brief.recommended_approaches_json, []),
        "artifact_id": brief.artifact_id,
        "status": brief.status,
        "created_by_type": brief.created_by_type,
        "created_at": brief.created_at.isoformat(),
    }


def idea_to_dict(idea: Idea) -> dict[str, Any]:
    return {
        "id": idea.id,
        "project_id": idea.project_id,
        "dataset_snapshot_id": idea.dataset_snapshot_id,
        "evaluation_spec_id": idea.evaluation_spec_id,
        "research_brief_id": idea.research_brief_id,
        "title": idea.title,
        "hypothesis": idea.hypothesis,
        "approach_type": idea.approach_type,
        "rationale_md": idea.rationale_md,
        "feature_strategy": loads_json(idea.feature_strategy_json, {}),
        "modeling_strategy": loads_json(idea.modeling_strategy_json, {}),
        "evaluation_notes_md": idea.evaluation_notes_md,
        "expected_artifacts": loads_json(idea.expected_artifacts_json, []),
        "agent_task_contract": loads_json(idea.agent_task_contract_json, {}),
        "confidence": idea.confidence,
        "risk_level": idea.risk_level,
        "status": idea.status,
        "priority": idea.priority,
        "artifact_id": idea.artifact_id,
        "created_by_type": idea.created_by_type,
        "created_at": idea.created_at.isoformat(),
        "updated_at": idea.updated_at.isoformat(),
    }


def report_to_dict(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "project_id": report.project_id,
        "report_type": report.report_type,
        "title": report.title,
        "summary": report.summary,
        "artifact_id": report.artifact_id,
        "source_asset_ids": normalize_source_asset_refs(loads_json(report.source_asset_ids_json, [])),
        "status": report.status,
        "created_by_type": report.created_by_type,
        "created_at": report.created_at.isoformat(),
    }


def normalize_source_asset_refs(raw_refs: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if not isinstance(raw_refs, list):
        return refs
    for ref in raw_refs:
        if isinstance(ref, dict):
            asset_type = ref.get("asset_type") or ref.get("type") or "artifact"
            asset_id = ref.get("asset_id") or ref.get("id")
        elif isinstance(ref, str):
            asset_type = "artifact"
            asset_id = ref
        else:
            continue
        if asset_id:
            refs.append({"asset_type": str(asset_type), "asset_id": str(asset_id)})
    return refs


def visualization_to_dict(visualization: VisualizationSpec) -> dict[str, Any]:
    return {
        "id": visualization.id,
        "project_id": visualization.project_id,
        "title": visualization.title,
        "chart_type": visualization.chart_type,
        "spec": loads_json(visualization.spec_json, {}),
        "source_artifact_id": visualization.source_artifact_id,
        "artifact_id": visualization.artifact_id,
        "status": visualization.status,
        "created_by_type": visualization.created_by_type,
        "created_at": visualization.created_at.isoformat(),
    }


def insight_to_dict(insight: Insight) -> dict[str, Any]:
    return {
        "id": insight.id,
        "project_id": insight.project_id,
        "insight_type": insight.insight_type,
        "title": insight.title,
        "summary": insight.summary,
        "severity": insight.severity,
        "confidence": insight.confidence,
        "status": insight.status,
        "source_asset_ids": loads_json(insight.source_asset_ids_json, []),
        "evidence_ids": loads_json(insight.evidence_ids_json, []),
        "artifact_id": insight.artifact_id,
        "created_by_type": insight.created_by_type,
        "created_at": insight.created_at.isoformat(),
    }


def expanded_asset_reference_to_dict(db: Session, reference: AssetReference) -> dict[str, Any]:
    asset = db.get(Asset, reference.target_asset_id)
    version = db.get(AssetVersion, reference.target_asset_version_id)
    return asset_reference_to_dict(reference, asset=asset, version=version)


def model_validation_to_dict(db: Session, job: Job, model_version_id: str) -> dict[str, Any]:
    output = loads_json(job.output_json, {})
    metrics = output.get("metrics") if isinstance(output.get("metrics"), dict) else {}
    artifact_ids = output.get("artifact_ids") if isinstance(output.get("artifact_ids"), list) else []
    artifacts: list[Artifact] = []
    if artifact_ids:
        artifacts = list(
            db.scalars(
                select(Artifact).where(Artifact.id.in_([str(artifact_id) for artifact_id in artifact_ids]))
            ).all()
        )
    validation_status = metrics.get("validation_status") if isinstance(metrics.get("validation_status"), str) else None
    max_delta = metrics.get("max_abs_metric_delta")
    return {
        "job": job_to_dict(job),
        "model_version_id": model_version_id,
        "validation_status": validation_status,
        "max_abs_metric_delta": float(max_delta) if isinstance(max_delta, int | float) else None,
        "metrics": metrics,
        "artifacts": [artifact_to_dict(artifact) for artifact in artifacts],
        "created_at": job.created_at.isoformat(),
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }


def artifact_preview_limit_bytes(artifact: Artifact, path: Path) -> int:
    if path.suffix.lower() in {".html", ".htm"}:
        return 5_000_000
    if artifact.asset_type == "relational_catalog":
        return 500_000
    return 20_000


def artifact_preview_to_dict(
    artifact: Artifact,
    path: Path,
    limit_bytes: int = 20_000,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    suffix = path.suffix.lower()
    visual_suffixes = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    text_suffixes = {
        ".csv",
        ".html",
        ".htm",
        ".json",
        ".md",
        ".py",
        ".svg",
        ".txt",
        ".yaml",
        ".yml",
        ".tsv",
        ".log",
    }
    base = {
        "id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "filename": path.name,
        "size_bytes": artifact.size_bytes,
        "lineage": artifact_preview_lineage(db, artifact) if db is not None else {"inputs": [], "outputs": []},
    }
    if artifact.asset_type == "research_findings_report" and suffix == ".json":
        try:
            payload = loads_json(path.read_text(encoding="utf-8"), {})
        except (OSError, UnicodeDecodeError, ValueError):
            payload = {}
        rich_preview = research_findings_rich_markdown_preview(db, payload) if isinstance(payload, dict) else None
        if rich_preview:
            return {
                **base,
                "content_type": "md",
                "preview_available": True,
                "preview": rich_preview,
                "truncated": False,
                "reason": None,
            }
        preview = research_findings_markdown_preview(payload) if isinstance(payload, dict) else None
        if preview:
            return {
                **base,
                "content_type": "md",
                "preview_available": True,
                "preview": preview,
                "truncated": False,
                "reason": None,
            }
    if artifact.asset_type == "pilot_scoring_report" and suffix == ".json":
        try:
            payload = loads_json(path.read_text(encoding="utf-8"), {})
        except (OSError, UnicodeDecodeError, ValueError):
            payload = {}
        preview = pilot_scoring_markdown_preview(payload) if isinstance(payload, dict) else None
        if preview:
            return {
                **base,
                "content_type": "md",
                "preview_available": True,
                "preview": preview,
                "truncated": False,
                "reason": None,
            }
    if artifact.asset_type == "validation_scheme_audit" and suffix == ".json":
        try:
            payload = loads_json(path.read_text(encoding="utf-8"), {})
        except (OSError, UnicodeDecodeError, ValueError):
            payload = {}
        preview = validation_scheme_audit_markdown_preview(payload) if isinstance(payload, dict) else None
        if preview:
            return {
                **base,
                "content_type": "md",
                "preview_available": True,
                "preview": preview,
                "truncated": False,
                "reason": None,
            }
    if suffix in visual_suffixes:
        return {
            **base,
            "content_type": visual_suffixes[suffix],
            "preview_available": True,
            "preview": f"/api/artifacts/{artifact.id}/download",
            "truncated": False,
            "reason": None,
        }
    if suffix not in text_suffixes:
        return {
            **base,
            "content_type": "binary",
            "preview_available": False,
            "preview": None,
            "truncated": False,
            "reason": (
                "Preview is only available for text, JSON, Markdown, HTML, Python, delimited text, images, and PDF artifacts."
            ),
        }

    raw = path.open("rb").read(limit_bytes + 1)
    truncated = len(raw) > limit_bytes
    if truncated:
        raw = raw[:limit_bytes]
    try:
        preview = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            **base,
            "content_type": "binary",
            "preview_available": False,
            "preview": None,
            "truncated": truncated,
            "reason": "Artifact is not valid UTF-8 text.",
        }
    if suffix == ".json" and not truncated:
        try:
            preview = json.dumps(json.loads(preview), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    content_type = (
        "text/html"
        if suffix in {".html", ".htm"}
        else "image/svg+xml"
        if suffix == ".svg"
        else suffix.removeprefix(".") or "text"
    )
    if content_type == "text/html" and not truncated:
        preview = inline_local_html_assets(artifact, path, preview)
    return {
        **base,
        "content_type": content_type,
        "preview_available": True,
        "preview": preview,
        "truncated": truncated,
        "reason": None,
    }


def artifact_preview_lineage(db: Session, artifact: Artifact) -> dict[str, list[dict[str, Any]]]:
    edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == artifact.project_id,
                (
                    (LineageEdge.to_asset_type == "artifact") & (LineageEdge.to_asset_id == artifact.id)
                    | ((LineageEdge.from_asset_type == "artifact") & (LineageEdge.from_asset_id == artifact.id))
                ),
            )
            .order_by(LineageEdge.created_at.desc())
            .limit(30)
        ).all()
    )
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for edge in edges:
        if edge.to_asset_type == "artifact" and edge.to_asset_id == artifact.id:
            inputs.append(artifact_lineage_endpoint_dict(db, edge, direction="input"))
        elif edge.from_asset_type == "artifact" and edge.from_asset_id == artifact.id:
            outputs.append(artifact_lineage_endpoint_dict(db, edge, direction="output"))
    return {"inputs": inputs[:10], "outputs": outputs[:10]}


def artifact_lineage_endpoint_dict(db: Session, edge: LineageEdge, *, direction: str) -> dict[str, Any]:
    if direction == "input":
        asset_type = edge.from_asset_type
        asset_id = edge.from_asset_id
    else:
        asset_type = edge.to_asset_type
        asset_id = edge.to_asset_id
    label = asset_id
    endpoint_asset_type = asset_type
    if asset_type == "artifact":
        linked_artifact = db.get(Artifact, asset_id)
        if linked_artifact is not None:
            label = linked_artifact.name
            endpoint_asset_type = linked_artifact.asset_type
    return {
        "edge_id": edge.id,
        "relation_type": edge.relation_type,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "label": label,
        "endpoint_asset_type": endpoint_asset_type,
        "created_at": edge.created_at.isoformat(),
    }


def research_findings_rich_markdown_preview(db: Session | None, payload: dict[str, Any]) -> str | None:
    if db is None:
        return None
    artifact_id = str(payload.get("rich_report_artifact_id") or "").strip()
    if not artifact_id:
        return None
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        return None
    try:
        path = artifact_primary_path(artifact)
        markdown = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    metadata = loads_json(artifact.metadata_json, {})
    references = metadata.get("figure_references")
    if not isinstance(references, list):
        return markdown
    replacements = {
        str(item.get("markdown_reference") or ""): f"/api/artifacts/{item.get('artifact_id')}/download"
        for item in references
        if isinstance(item, dict)
        and isinstance(item.get("markdown_reference"), str)
        and item.get("markdown_reference")
        and isinstance(item.get("artifact_id"), str)
        and item.get("artifact_id")
    }
    if not replacements:
        return markdown

    def replace(match: re.Match[str]) -> str:
        reference = match.group(1).strip()
        replacement = replacements.get(reference)
        if not replacement:
            return match.group(0)
        return match.group(0).replace(f"({reference}", f"({replacement}", 1)

    return re.sub(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", replace, markdown)


def research_findings_markdown_preview(payload: dict[str, Any]) -> str | None:
    topic = str(payload.get("topic") or "").strip()
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    no_findings = payload.get("no_findings") if isinstance(payload.get("no_findings"), dict) else None
    if not topic and not sources and not findings and no_findings is None:
        return None
    lines = ["# Research findings"]
    if topic:
        lines.extend(["", f"**Topic:** {topic}"])
    if no_findings is not None:
        rationale = str(no_findings.get("rationale") or "").strip()
        queries = [str(item).strip() for item in no_findings.get("searched_queries", []) if isinstance(item, str) and item.strip()] if isinstance(no_findings.get("searched_queries"), list) else []
        lines.extend(["", "## No findings recorded"])
        if rationale:
            lines.append(rationale)
        if queries:
            lines.extend(["", "Searched queries:"])
            lines.extend(f"- {query}" for query in queries)
        return "\n".join(lines).strip() + "\n"
    if sources:
        lines.extend(["", "## Sources"])
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            title = str(source.get("title") or f"Source {index + 1}").strip()
            url = str(source.get("url") or "").strip()
            source_type = str(source.get("source_type") or "").strip()
            retrieved_at = str(source.get("retrieved_at") or "").strip()
            label = f"[{index}] {title}"
            if url:
                label = f"[{index}] [{title}]({url})"
            suffix_parts = [part for part in (source_type, retrieved_at) if part]
            lines.append(f"- {label}{' — ' + ' · '.join(suffix_parts) if suffix_parts else ''}")
            key_claims = source.get("key_claims") if isinstance(source.get("key_claims"), list) else []
            for claim in key_claims:
                if isinstance(claim, str) and claim.strip():
                    lines.append(f"  - {claim.strip()}")
            reliability_notes = str(source.get("reliability_notes") or "").strip()
            if reliability_notes:
                lines.append(f"  - Reliability notes: {reliability_notes}")
    if findings:
        lines.extend(["", "## Findings"])
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            claim = str(finding.get("claim") or f"Finding {index}").strip()
            lines.append(f"{index}. {claim}")
            source_indexes = finding.get("source_indexes") if isinstance(finding.get("source_indexes"), list) else []
            if source_indexes:
                lines.append(f"   - Sources: {', '.join(str(item) for item in source_indexes)}")
            implication = str(finding.get("implication_for_project") or "").strip()
            if implication:
                lines.append(f"   - Project implication: {implication}")
            action = str(finding.get("recommended_action") or "").strip()
            if action:
                lines.append(f"   - Recommended action: {action}")
    return "\n".join(lines).strip() + "\n"


def pilot_scoring_markdown_preview(payload: dict[str, Any]) -> str | None:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    matched_rows = payload.get("matched_rows")
    metric_count = payload.get("metric_count")
    as_of_violations = payload.get("as_of_violations") if isinstance(payload.get("as_of_violations"), dict) else {}
    period = payload.get("period") if isinstance(payload.get("period"), dict) else {}
    if not metrics and matched_rows is None and metric_count is None and not as_of_violations and not period:
        return None
    lines = ["# Pilot scoring report"]
    summary_parts: list[str] = []
    if isinstance(matched_rows, int | float):
        summary_parts.append(f"{matched_rows:g} matched rows")
    if isinstance(metric_count, int | float):
        summary_parts.append(f"{metric_count:g} metrics")
    if summary_parts:
        lines.extend(["", " · ".join(summary_parts)])
    if metrics:
        lines.extend(["", "## Metrics"])
        for name, value in metrics.items():
            if isinstance(value, int | float):
                lines.append(f"- {name}: {value:g}")
            elif isinstance(value, str) and value.strip():
                lines.append(f"- {name}: {value.strip()}")
    violation_count = as_of_violations.get("count")
    if isinstance(violation_count, int | float):
        lines.extend(["", "## As-of checks", f"- Violations: {violation_count:g}"])
    if period:
        start = str(period.get("start") or "").strip()
        end = str(period.get("end") or "").strip()
        if start or end:
            lines.extend(["", "## Period", f"- Start: {start or '-'}", f"- End: {end or '-'}"])
    return "\n".join(lines).strip() + "\n"


def validation_scheme_audit_markdown_preview(payload: dict[str, Any]) -> str | None:
    verdict = str(payload.get("scheme_verdict") or "").strip()
    next_focus = str(payload.get("next_iteration_focus") or "").strip()
    gap_decomposition = payload.get("gap_decomposition") if isinstance(payload.get("gap_decomposition"), list) else []
    hypotheses = payload.get("hypotheses") if isinstance(payload.get("hypotheses"), list) else []
    if not verdict and not next_focus and not gap_decomposition and not hypotheses:
        return None
    lines = ["# Validation scheme audit"]
    if verdict:
        lines.extend(["", f"**Verdict:** {verdict.replace('_', ' ')}"])
    if next_focus:
        lines.extend(["", "## Next iteration focus", next_focus])
    if gap_decomposition:
        lines.extend(["", "## Gap decomposition"])
        for index, item in enumerate(gap_decomposition, start=1):
            if not isinstance(item, dict):
                continue
            component = str(item.get("component") or f"component {index}").strip().replace("_", " ")
            lines.append(f"{index}. {component}")
            for label, key in (("Evidence", "evidence"), ("Magnitude", "magnitude"), ("Confidence", "confidence")):
                value = str(item.get(key) or "").strip()
                if value:
                    lines.append(f"   - {label}: {value}")
    if hypotheses:
        lines.extend(["", "## Hypotheses"])
        for index, item in enumerate(hypotheses, start=1):
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement") or f"Hypothesis {index}").strip()
            lines.append(f"{index}. {statement}")
            for label, key in (("Test plan", "test_plan"), ("Expected evidence", "expected_evidence")):
                value = str(item.get(key) or "").strip()
                if value:
                    lines.append(f"   - {label}: {value}")
    return "\n".join(lines).strip() + "\n"


def inline_local_html_assets(artifact: Artifact, path: Path, html: str, max_preview_bytes: int = 5_000_000) -> str:
    base_dirs = html_asset_base_dirs(artifact, path)
    current_size = len(html.encode("utf-8"))

    def replace_src(match: re.Match[str]) -> str:
        nonlocal current_size
        prefix, src, suffix = match.groups()
        if not src or src.startswith(("#", "data:", "http://", "https://", "mailto:", "/", "blob:")):
            return match.group(0)
        asset_path = resolve_local_html_asset(src, base_dirs)
        if asset_path is None:
            return match.group(0)
        mime_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
        try:
            raw = asset_path.read_bytes()
        except OSError:
            return match.group(0)
        encoded = base64.b64encode(raw).decode("ascii")
        data_uri = f"data:{mime_type};base64,{encoded}"
        projected_size = current_size - len(src.encode("utf-8")) + len(data_uri)
        if projected_size > max_preview_bytes:
            return match.group(0)
        current_size = projected_size
        return f"{prefix}{data_uri}{suffix}"

    inlined = re.sub(r'(<(?:img|source)\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', replace_src, html, flags=re.IGNORECASE)
    return inject_inline_preview_reader_style(inlined)


def inject_inline_preview_reader_style(html: str) -> str:
    if "tablex-inline-preview-reader-style" in html:
        return html
    style = """<style id="tablex-inline-preview-reader-style">
html,body{background:#fff!important;color:#1f2933!important;color-scheme:light!important;min-height:100%;}
body{box-sizing:border-box;}
*,*:before,*:after{box-sizing:inherit;}
@media (prefers-color-scheme: dark){
  html,body{background:#fff!important;color:#1f2933!important;color-scheme:light!important;}
  :root{--ink:#10183f;--muted:#53617d;--line:#dbe3f3;--panel:#ffffff;--wash:#f4f9fb;}
}
</style>"""
    if re.search(r"</head\s*>", html, flags=re.IGNORECASE):
        return re.sub(r"</head\s*>", f"{style}</head>", html, count=1, flags=re.IGNORECASE)
    return f"{style}{html}"


def html_asset_base_dirs(artifact: Artifact, path: Path) -> list[Path]:
    metadata = loads_json(artifact.metadata_json, {})
    dirs = [path.parent, path.parent.parent]
    project_id = metadata.get("project_id") or artifact.project_id
    session_id = metadata.get("agent_session_id")
    if isinstance(project_id, str) and isinstance(session_id, str):
        workspace_root = get_settings().artifact_root / "agent_sessions" / project_id / session_id
        workspace_relative_path = metadata.get("workspace_relative_path")
        if isinstance(workspace_relative_path, str) and workspace_relative_path:
            dirs.append((workspace_root / workspace_relative_path).parent)
        dirs.extend([workspace_root / "reports", workspace_root])
    deduped: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        key = str(directory)
        if key not in seen:
            seen.add(key)
            deduped.append(directory)
    return deduped


def resolve_local_html_asset(src: str, base_dirs: list[Path]) -> Path | None:
    for base_dir in base_dirs:
        candidate = (base_dir / src).resolve()
        try:
            candidate.relative_to(base_dir.resolve())
        except ValueError:
            if not any(candidate.is_relative_to(parent.resolve()) for parent in base_dirs):
                continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def create_translation_job(
    db: Session,
    *,
    project_id: str | None,
    source_type: str,
    source_id: str,
    source_artifact_id: str,
    payload: TranslationCreate,
) -> Job:
    return create_job(
        db,
        job_type="translate_tier3_content",
        project_id=project_id,
        input_payload={
            "source_type": source_type,
            "source_id": source_id,
            "source_artifact_id": source_artifact_id,
            "source_locale": payload.source_locale,
            "target_locale": payload.target_locale,
        },
        policy={
            "execution": "queued_worker",
            "runner": "CodexCliRunner",
            "network": "disabled_until_runner_policy_allows",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "source_of_truth": "original_english_artifact",
        },
    )


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "job_type": job.job_type,
        "status": job.status,
        "priority": job.priority,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "input": loads_json(job.input_json, {}),
        "output": loads_json(job.output_json, {}),
        "context": loads_json(job.context_json, {}),
        "policy": loads_json(job.policy_json, {}),
        "dependency_job_ids": loads_json(job.dependency_job_ids_json, []),
        "error_message": job.error_message,
        "approval_required": job.approval_required,
        "approved_by": job.approved_by,
        "approved_at": job.approved_at.isoformat() if job.approved_at else None,
        "cancelled_by": job.cancelled_by,
        "run_after": job.run_after.isoformat() if job.run_after else None,
        "locked_by": job.locked_by,
        "locked_at": job.locked_at.isoformat() if job.locked_at else None,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
    }


def collect_output_artifact_ids(value: Any) -> list[str]:
    collected: list[str] = []

    def visit(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                visit(child_value, str(child_key))
            return
        if isinstance(node, list):
            if key and (key == "artifact_ids" or key.endswith("_artifact_ids")):
                for item in node:
                    if isinstance(item, str):
                        collected.append(item)
                return
            for item in node:
                visit(item, key)
            return
        if isinstance(node, str) and key and (key == "artifact_id" or key.endswith("_artifact_id")):
            collected.append(node)

    visit(value)
    return list(dict.fromkeys(collected))


def summarize_job_output(output: dict[str, Any]) -> dict[str, Any]:
    metrics = output.get("metrics") if isinstance(output.get("metrics"), dict) else {}
    primary_metric_name = metrics.get("primary_metric_name") if isinstance(metrics, dict) else None
    primary_metric_value = metrics.get("primary_metric_value") if isinstance(metrics, dict) else None
    return {
        "benchmark_id": output.get("benchmark_id"),
        "dataset_snapshot_id": output.get("dataset_snapshot_id"),
        "evaluation_spec_id": output.get("evaluation_spec_id"),
        "split_manifest_id": output.get("split_manifest_id"),
        "experiment_run_id": output.get("experiment_run_id"),
        "model_version_id": output.get("model_version_id"),
        "run_report_id": output.get("run_report_id"),
        "decision_report_id": output.get("decision_report_id"),
        "benchmark_count": output.get("benchmark_count"),
        "benchmark_collection_plan_artifact_id": output.get("benchmark_collection_plan_artifact_id"),
        "benchmark_collection_report_id": output.get("benchmark_collection_report_id"),
        "benchmark_collection_report_artifact_id": output.get("benchmark_collection_report_artifact_id"),
        "benchmark_evidence_pack_artifact_id": output.get("benchmark_evidence_pack_artifact_id"),
        "benchmark_evidence_report_id": output.get("benchmark_evidence_report_id"),
        "kaggle_probe_artifact_id": output.get("kaggle_probe_artifact_id"),
        "kaggle_inventory_artifact_id": output.get("kaggle_inventory_artifact_id"),
        "kaggle_download_manifest_artifact_id": output.get("kaggle_download_manifest_artifact_id"),
        "probe_status": output.get("probe_status"),
        "inventory_status": output.get("inventory_status"),
        "download_status": output.get("download_status"),
        "credential_available": output.get("credential_available"),
        "can_access_competition_files": output.get("can_access_competition_files"),
        "http_status": output.get("http_status"),
        "file_count": output.get("file_count"),
        "downloaded_count": output.get("downloaded_count"),
        "downloaded_bytes": output.get("downloaded_bytes"),
        "local_ready": output.get("local_ready"),
        "required_missing_count": output.get("required_missing_count"),
        "task_id": output.get("task_id"),
        "agent_task_contract_artifact_id": output.get("agent_task_contract_artifact_id"),
        "agent_workspace_manifest_artifact_id": output.get("agent_workspace_manifest_artifact_id"),
        "agent_metrics_artifact_id": output.get("agent_metrics_artifact_id"),
        "agent_feature_recipe_artifact_id": output.get("agent_feature_recipe_artifact_id"),
        "approach_decision_trace_artifact_id": output.get("approach_decision_trace_artifact_id"),
        "relational_context_source_count": output.get("relational_context_source_count"),
        "relational_context_summary_artifact_id": output.get("relational_context_summary_artifact_id"),
        "source_citation_manifest_artifact_id": output.get("source_citation_manifest_artifact_id"),
        "citation_audit_report_id": output.get("citation_audit_report_id"),
        "citation_audit_report_artifact_id": output.get("citation_audit_report_artifact_id"),
        "citation_evidence_id": output.get("citation_evidence_id"),
        "citation_visualization_id": output.get("citation_visualization_id"),
        "relational_feature_plan_artifact_id": output.get("relational_feature_plan_artifact_id"),
        "relational_feature_report_id": output.get("relational_feature_report_id"),
        "relational_feature_report_artifact_id": output.get("relational_feature_report_artifact_id"),
        "relational_feature_recipe_artifact_id": output.get("relational_feature_recipe_artifact_id"),
        "relational_feature_preview_artifact_id": output.get("relational_feature_preview_artifact_id"),
        "relational_feature_preview_profile_artifact_id": output.get(
            "relational_feature_preview_profile_artifact_id"
        ),
        "relational_feature_recipe_report_id": output.get("relational_feature_recipe_report_id"),
        "relational_feature_recipe_report_artifact_id": output.get(
            "relational_feature_recipe_report_artifact_id"
        ),
        "relational_feature_scenario_diagnostics_artifact_id": output.get(
            "relational_feature_scenario_diagnostics_artifact_id"
        ),
        "relational_feature_scenario_report_id": output.get("relational_feature_scenario_report_id"),
        "relational_feature_scenario_report_artifact_id": output.get(
            "relational_feature_scenario_report_artifact_id"
        ),
        "research_run_manifest_artifact_id": output.get("research_run_manifest_artifact_id"),
        "research_findings_report_id": output.get("research_findings_report_id"),
        "research_findings_report_artifact_id": output.get("research_findings_report_artifact_id"),
        "research_source_pack_artifact_id": output.get("research_source_pack_artifact_id"),
        "research_source_report_id": output.get("research_source_report_id"),
        "research_finding_synthesis_artifact_id": output.get("research_finding_synthesis_artifact_id"),
        "research_finding_synthesis_report_id": output.get("research_finding_synthesis_report_id"),
        "research_finding_synthesis_report_artifact_id": output.get(
            "research_finding_synthesis_report_artifact_id"
        ),
        "finding_count": output.get("finding_count"),
        "citation_count": output.get("citation_count"),
        "external_network_accessed": output.get("external_network_accessed"),
        "has_only_stub_findings": output.get("has_only_stub_findings"),
        "recommended_approach_count": output.get("recommended_approach_count"),
        "research_query_count": output.get("research_query_count"),
        "project_source_count": output.get("project_source_count"),
        "library_source_count": output.get("library_source_count"),
        "credentialed_count": output.get("credentialed_count"),
        "public_direct_count": output.get("public_direct_count"),
        "fixture_available_count": output.get("fixture_available_count"),
        "local_ready_count": output.get("local_ready_count"),
        "multitable_count": output.get("multitable_count"),
        "time_series_count": output.get("time_series_count"),
        "table_count": output.get("table_count"),
        "supporting_table_count": output.get("supporting_table_count"),
        "relationship_count": output.get("relationship_count"),
        "aggregation_candidate_count": output.get("aggregation_candidate_count"),
        "generated_feature_count": output.get("generated_feature_count"),
        "usable_feature_count": output.get("usable_feature_count"),
        "constant_feature_count": output.get("constant_feature_count"),
        "high_missing_feature_count": output.get("high_missing_feature_count"),
        "executed_step_count": output.get("executed_step_count"),
        "deferred_step_count": output.get("deferred_step_count"),
        "scenario_count": output.get("scenario_count"),
        "preview_row_count": output.get("preview_row_count"),
        "high_risk_count": output.get("high_risk_count"),
        "recommended_asset_count": output.get("recommended_asset_count"),
        "materialized_context_count": output.get("materialized_context_count"),
        "materialized_relational_context_count": output.get("materialized_relational_context_count"),
        "materialized_library_asset_count": output.get("materialized_library_asset_count"),
        "skipped_source_count": output.get("skipped_source_count"),
        "readiness_status": output.get("readiness_status"),
        "blocker_count": output.get("blocker_count"),
        "warning_count": output.get("warning_count"),
        "agent_status": output.get("agent_status"),
        "evidence_id": output.get("evidence_id"),
        "requires_human_review": output.get("requires_human_review"),
        "primary_metric_name": primary_metric_name,
        "primary_metric_value": primary_metric_value,
        "artifact_count": len(collect_output_artifact_ids(output)),
    }
