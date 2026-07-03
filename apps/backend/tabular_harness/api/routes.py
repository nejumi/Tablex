from __future__ import annotations

import base64
import json
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import and_, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.api.deps import get_artifact_store, get_session
from tabular_harness.core.config import get_settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
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
    Project,
    Question,
    Report,
    ResearchBrief,
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
    AvatarCandidateResponse,
    BenchmarkDatasetRead,
    BenchmarkFixtureRequest,
    BenchmarkFixtureResponse,
    BenchmarkImportReadinessRead,
    BenchmarkImportRequest,
    BenchmarkImportResponse,
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
    ProjectRead,
    ProjectUpdate,
    QuestionAnswerCreate,
    QuestionRead,
    ReportCreate,
    ReportRead,
    ResearchBriefCreate,
    ResearchBriefRead,
    ResultReadoutRead,
    SemanticCatalogRead,
    SplitManifestRead,
    TranslationCreate,
    TranslationRead,
    UserRead,
    UserSettingsUpdate,
    VisualizationSpecRead,
)
from tabular_harness.services.adaptive_strategy import (
    build_adaptive_strategy_brief,
    create_adaptive_strategy_brief,
)
from tabular_harness.services.agent_chat_status import agent_chat_wait_state
from tabular_harness.services.agent_context import prepare_idea_agent_context_pack
from tabular_harness.services.agent_sessions import (
    active_main_session,
    append_session_event,
    append_user_instruction_to_workspace_inbox,
    chat_update_message_from_text,
    latest_codex_transcript_output_at,
    latest_main_session,
    latest_project_response_locale,
    maybe_request_codex_progress_update,
    maybe_request_research_plan_locale_refresh,
    raw_codex_stderr_path,
    raw_codex_transcript_path,
    run_main_agent_session_supervisor,
    session_to_dict,
    start_main_agent_session_supervisor_thread,
    start_or_resume_main_session,
    stop_main_session,
    supervisor_slot_active,
    transcript_event_to_dict,
)
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import review_agent_task_readiness
from tabular_harness.services.agent_task_results import list_agent_task_result_summaries
from tabular_harness.services.agent_tasks import run_idea_agent_task_stub
from tabular_harness.services.analysis_notebooks import (
    build_project_analysis_story,
    build_project_notebook_index,
    create_notebook_execution_capture,
    create_notebook_execution_plan,
)
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
from tabular_harness.services.avatar_generation import (
    AvatarGenerationError,
    generate_user_avatar_candidates,
)
from tabular_harness.services.baseline import (
    create_baseline_strategy_plan,
    normalize_model_candidate_name,
)
from tabular_harness.services.baseline import run_baseline as run_baseline_service
from tabular_harness.services.benchmark_collection import create_benchmark_collection_plan
from tabular_harness.services.benchmark_evidence import create_benchmark_evidence_pack
from tabular_harness.services.benchmarks import (
    benchmark_import_readiness,
    benchmark_source_card,
    benchmark_to_dict,
    build_import_manifest,
    build_relational_catalog,
    create_benchmark_scenario_pack,
    default_benchmark_root,
    download_public_benchmark_archive,
    generate_benchmark_fixture,
    get_benchmark_dataset,
    infer_relationships,
    inspect_benchmark_local_files,
    list_benchmark_datasets,
    profile_table_file,
    raw_benchmark_dataset,
    relative_path,
    resolve_benchmark_root,
    select_primary_file,
    store_benchmark_supporting_table_artifacts,
    table_name_from_path,
    validate_required_files,
)
from tabular_harness.services.data_quality import analyze_dataset_quality
from tabular_harness.services.decision_reporting import (
    create_decision_report_v1,
    current_decision_report_payload,
)
from tabular_harness.services.diagnostics import analyze_run_diagnostics
from tabular_harness.services.eda_review import create_dataset_eda_review
from tabular_harness.services.evaluation import (
    approve_spec,
    candidate_to_dict,
    create_default_evaluation_candidates,
    create_evaluation_approval_review,
    create_evaluation_scenario_comparison,
    generate_split_manifest,
    promote_candidate_to_spec,
    spec_to_dict,
    write_spec_artifact,
)
from tabular_harness.services.experiment_lifecycle import (
    compare_project_experiments,
    create_experiment_plan_for_idea,
    draft_run_report,
)
from tabular_harness.services.jobs import (
    approve_job,
    create_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    retry_job,
)
from tabular_harness.services.jobs import (
    cancel_job as cancel_job_service,
)
from tabular_harness.services.kaggle_probe import (
    download_kaggle_selected_files,
    fetch_kaggle_competition_inventory,
    probe_kaggle_benchmark_access,
)
from tabular_harness.services.locales import locale_is_japanese
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
    prepare_workspace_from_contract_artifact,
)
from tabular_harness.services.portal import (
    active_job_ids_for_activity,
    build_portal_overview,
    build_project_turn_state,
    create_portal_idea,
    list_portal_ideas,
    running_codex_processes_for_project,
    worker_events_from_job,
)
from tabular_harness.services.profiler import profile_tabular_file
from tabular_harness.services.project_guidance import (
    build_project_guidance,
    create_autonomous_decision_brief,
    create_guided_journey_comparison,
    create_guided_journey_snapshot,
)
from tabular_harness.services.relational_evidence import (
    MAX_SCHEMA_HINT_BYTES,
    create_relational_schema_hint,
)
from tabular_harness.services.relational_feature_diagnostics import (
    diagnose_relational_feature_scenarios,
)
from tabular_harness.services.relational_feature_planning import create_relational_feature_plan
from tabular_harness.services.relational_feature_recipe import build_relational_feature_recipe
from tabular_harness.services.reporting import (
    create_project_visualization_dashboard,
    generate_project_insights,
)
from tabular_harness.services.research_plan_timeline import build_research_plan_timeline_response
from tabular_harness.services.research_runner import run_research_source_pack_local_stub
from tabular_harness.services.research_sources import create_research_source_pack
from tabular_harness.services.research_synthesis import create_research_finding_synthesis
from tabular_harness.services.result_notebook_evidence import (
    prepare_result_notebook_evidence,
    result_notebook_evidence_job_output,
)
from tabular_harness.services.result_readout import build_result_readout
from tabular_harness.services.translation import TranslationResult
from tabular_harness.services.translation import translate_artifact as translate_artifact_service
from tabular_harness.worker.jobs import create_default_worker

router = APIRouter()
INTERACTIVE_WORKER_JOB_TYPES = {"agent_chat_turn"}
MAIN_SESSION_CHAT_DELIVERY_RUN_AFTER = timedelta(days=3650)


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
    }


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


@router.post("/api/user/avatar-candidates", response_model=AvatarCandidateResponse)
def generate_avatar_candidates(payload: AvatarCandidateCreate) -> dict[str, Any]:
    try:
        candidates = generate_user_avatar_candidates(
            prompt=payload.prompt,
            count=payload.count,
            user="tablex-user-avatar",
        )
    except AvatarGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {
        "candidates": [
            {
                "id": candidate.id,
                "data_url": candidate.data_url,
                "model": candidate.model,
                "revised_prompt": candidate.revised_prompt,
            }
            for candidate in candidates
        ]
    }


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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    job = create_job(
        db,
        job_type="download_public_benchmark_archive",
        project_id=None,
        input_payload={"benchmark_id": benchmark_id, "overwrite": payload.overwrite},
        policy={
            "network": "enabled_for_catalog_public_archive_only",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        manifest = download_public_benchmark_archive(
            request.app.state.settings,
            benchmark_id,
            overwrite=payload.overwrite,
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
        mark_job_succeeded(
            job,
            {
                "benchmark_id": benchmark_id,
                "artifact_id": artifact.id,
                "schema_version": manifest["schema_version"],
                "download_url": manifest["download_url"],
                "root_path": manifest["root_path"],
                "extracted_file_count": len(manifest["extracted_files"]),
                "skipped_file_count": len(manifest["skipped_files"]),
                "local_ready": manifest["local_status"]["ready"],
            },
        )
    except KeyError as exc:
        mark_job_failed(job, "Benchmark dataset not found")
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        message = f"Autonomous loop start failed: {exc}"
        mark_job_failed(job, message)
        raise HTTPException(status_code=500, detail=message) from exc
    return job_to_dict(job)


@router.post("/api/benchmarks/{benchmark_id}/kaggle/probe", response_model=JobRead)
def probe_kaggle_benchmark_endpoint(
    benchmark_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
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
        },
    )
    try:
        mark_job_running(job)
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
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except KeyError as exc:
        mark_job_failed(job, "Benchmark dataset not found")
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return job_to_dict(job)


@router.post("/api/benchmarks/{benchmark_id}/kaggle/inventory", response_model=JobRead)
def fetch_kaggle_inventory_endpoint(
    benchmark_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
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
        },
    )
    try:
        mark_job_running(job)
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
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except KeyError as exc:
        mark_job_failed(job, "Benchmark dataset not found")
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
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
        },
        policy={
            "network": "enabled_for_kaggle_selected_download_only",
            "secret_access": "harness_process_only",
            "connector_credentials": "not_materialized",
            "agent_runner_access": False,
            "agent_task_contract_access": False,
            "artifact_contains_secret_values": False,
        },
    )
    try:
        mark_job_running(job)
        benchmark = raw_benchmark_dataset(benchmark_id)
        root = default_benchmark_root(request.app.state.settings, benchmark_id)
        manifest = download_kaggle_selected_files(
            benchmark,
            root=root,
            selected_files=payload.selected_files,
            include_required=payload.include_required,
            include_recommended=payload.include_recommended,
            include_holdout=payload.include_holdout,
            overwrite=payload.overwrite,
            max_total_bytes=payload.max_total_bytes,
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
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except KeyError as exc:
        mark_job_failed(job, "Benchmark dataset not found")
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    stopped_session = None
    if (
        previous_autonomy_mode == "full_auto"
        and project.autonomy_mode == "approval_based"
        and previous_phase == "AUTONOMOUS_LOOP"
    ):
        stopped_session = stop_main_session(db, project)
    project.updated_at = utc_now()
    session = ensure_project_full_auto_agent_session(
        db,
        store=store,
        project=project,
        created_by=request_actor_id(request),
    )
    if session is not None:
        start_main_agent_session_supervisor_thread(
            request.app.state.session_factory,
            store,
            project_id=project_id,
            session_id=session.id,
            supervisor_runner=run_main_agent_session_supervisor,
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
                        "Waiting のカードはまだ実行中ではなく、local worker が拾った時点で Running に変わります。"
                    )
                else:
                    assistant_message = (
                        f"{assistant_message}\n\n"
                        "Agent Activity now shows the queued follow-up work. Cards marked Waiting are not running yet; "
                        "they switch to Running when the local worker picks them up."
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
                    content="Tablex observed a Codex process without an attached supervisor and will recover the same AgentSession.",
                    payload={"project_id": project.id, "process_count": len(observed_processes)},
                )
            return existing
        if existing.pid is not None or existing.status == "running":
            already_recorded = existing.last_error == (
                "No live Codex process was observed; the supervisor will resume the same AgentSession."
            )
            existing.pid = None
            existing.status = "between_turns"
            existing.last_error = "No live Codex process was observed; the supervisor will resume the same AgentSession."
            existing.updated_at = utc_now()
            if not already_recorded:
                append_session_event(
                    db,
                    existing,
                    source="tablex_sidecar",
                    event_type="stale_runner_pid_cleared",
                    role="harness",
                    title="Stale Codex process reference cleared",
                    content="Tablex observed Full Auto without a live Codex process and will resume the same AgentSession.",
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
    background_tasks: BackgroundTasks,
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
            start_main_agent_session_supervisor_thread(
                request.app.state.session_factory,
                store,
                project_id=project_id,
                session_id=session.id,
                agent_model=payload.agent_model,
                supervisor_runner=run_main_agent_session_supervisor,
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
        background_tasks.add_task(
            run_autonomy_start_job_background,
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
        cancellable_job_types = {
            "start_autonomous_loop",
            "run_agent_task",
            "run_planned_agent_task_codex",
            "run_planned_agent_task_stub",
            "train_model_candidates",
            "run_baseline",
            "plan_agent_task",
        }
        active_statuses = {"queued", "running", "approval_required"}
        active_jobs = db.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.id != job.id,
                Job.status.in_(active_statuses),
                Job.job_type.in_(cancellable_job_types),
            )
        ).all()
        cancelled_ids: list[str] = []
        for active_job in active_jobs:
            cancel_job_service(active_job, cancelled_by="tablex-autonomy-power")
            cancelled_ids.append(active_job.id)
        stopped_session = stop_main_session(db, project)
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
                "worker_events": [
                    {
                        "worker_id": "full-auto-loop",
                        "display_name": "Full Auto Agent",
                        "status": "cancelled",
                        "headline": "Autonomous activity stopped.",
                        "detail": f"Stopped {len(cancelled_ids)} active or queued runner/model job(s).",
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="save_guided_journey_snapshot",
        project_id=project_id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        result = create_guided_journey_snapshot(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/guidance/decision-brief", response_model=JobRead)
def save_project_autonomous_decision_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="save_autonomous_decision_brief",
        project_id=project_id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        result = create_autonomous_decision_brief(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.brief["schema_version"],
                "autonomous_decision_brief_artifact_id": result.artifact.id,
                "autonomous_decision_brief_report_id": result.report.id,
                "autonomous_decision_brief_report_artifact_id": result.report_artifact.id,
                "artifact_id": result.artifact.id,
                "artifact_ids": result.artifact_ids,
                "focus_key": result.brief["focus_key"],
                "target_tab": result.brief["target_tab"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/guidance/snapshots/compare", response_model=JobRead)
def compare_project_guided_journey_snapshots(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="compare_guided_journey_snapshots",
        project_id=project_id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        result = create_guided_journey_comparison(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        project.current_phase = "UNDERSTANDING_REVIEW"
        project.updated_at = utc_now()
        mark_job_succeeded(job, {"dataset_snapshot_id": dataset.id})
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return {
        "dataset_snapshot": dataset_to_dict(dataset),
        "artifact": artifact_to_dict(dataset_artifact),
        "profile_job_id": job.id,
    }


TABLE_UPLOAD_SUFFIXES = {".csv", ".parquet"}
RELATIONAL_HINT_UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".json"}


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
        mark_job_running(job)
        output = ingest_uploaded_data_bundle(
            db,
            store=store,
            project=project,
            job=job,
            table_uploads=table_uploads,
            hint_uploads=hint_uploads,
            target_column=target_column,
            primary_filename=requested_primary,
            note=note,
            response_locale=locale,
        )
        mark_job_succeeded(job, output)
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return job_to_dict(job)


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
) -> dict[str, Any]:
    effective_target = target_column or project.target_column
    if target_column and target_column != project.target_column:
        project.target_column = target_column

    selected_primary = select_uploaded_primary_table(table_uploads, primary_filename)
    used_table_names: set[str] = set()
    table_records: list[dict[str, Any]] = []
    dataset: DatasetSnapshot | None = None
    dataset_artifact: Artifact | None = None
    notebook_artifact_ids: list[str] = []
    notebook_warning: str | None = None

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
        if is_primary:
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
        table_records.append(
            {
                "artifact": artifact,
                "stored_path": stored.path,
                "profile": table_profile,
                "is_primary": is_primary,
                "table_name": table_name,
            }
        )

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
            notebook_html_artifact = None
            notebook_report_artifact = None
            notebook_manifest_artifact = None
        except ValueError as exc:
            notebook_warning = str(exc)
            notebook_artifact = None
            notebook_html_artifact = None
            notebook_report_artifact = None
            notebook_manifest_artifact = None
    else:
        notebook_artifact = None
        notebook_html_artifact = None
        notebook_report_artifact = None
        notebook_manifest_artifact = None

    project.current_phase = "UNDERSTANDING_REVIEW"
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
    return {
        "schema_version": "upload_data_bundle.v1",
        "dataset_snapshot_id": dataset.id if dataset else None,
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
        "notebook_html_artifact_id": notebook_html_artifact.id if notebook_html_artifact else None,
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
) -> str:
    target_line = f"Objective/target is currently `{target_column}`." if target_column else (
        "Objective/target is still open. Full Auto can ask Codex to review possible task shapes from the uploaded data."
    )
    notebook_line = "Notebook authoring context is ready. The notebook itself will appear after the agent writes it."
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
    return table_uploads[0]


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
    primary_profile = next((profile for profile in table_profiles if profile.get("is_primary")), table_profiles[0])
    primary_table_hint = {
        "path": primary_profile.get("path"),
        "table_name": primary_profile.get("table_name"),
        "target_column": target_column,
        "entity_id_column": first_key_candidate(primary_profile),
    }
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
            "table_name": primary_profile.get("table_name"),
            "selected_path": primary_profile.get("path"),
            "target_column": target_column,
            "artifact_id": primary_profile.get("artifact_id"),
            "entity_id_column": primary_table_hint["entity_id_column"],
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
        },
    )
    try:
        mark_job_running(job)
        result = create_dataset_eda_review(db, store=store, dataset=dataset)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.review["schema_version"],
                "dataset_snapshot_id": dataset.id,
                "eda_review_bundle_artifact_id": result.bundle_artifact.id,
                "eda_review_html_artifact_id": result.html_artifact.id,
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/notebook-authoring/brief", response_model=JobRead)
def create_notebook_authoring_brief_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
        },
    )
    try:
        mark_job_running(job)
        result = create_notebook_authoring_brief(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.brief["schema_version"],
                "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
                "notebook_authoring_report_id": result.report.id,
                "notebook_authoring_report_artifact_id": result.report_artifact.id,
                "source_card_count": len(result.brief["source_inspirations"]),
                "principle_count": len(result.brief["authoring_principles"]),
                "context_artifact_count": len(result.brief["context_artifacts"]),
                "artifact_id": result.brief_artifact.id,
                "artifact_ids": result.artifact_ids,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/relational/schema-hints/upload", response_model=JobRead)
def upload_relational_schema_hint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    file: Annotated[UploadFile, File()],
    note: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="upload_relational_schema_hint",
        project_id=project_id,
        input_payload={
            "filename": file.filename,
            "content_type": file.content_type,
            "note_present": bool(note and note.strip()),
        },
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "purpose": "store_user_supplied_er_diagram_evidence",
        },
    )
    try:
        mark_job_running(job)
        result = create_relational_schema_hint(
            db,
            store=store,
            project=project,
            filename=file.filename or "relational_schema_hint",
            content_type=file.content_type,
            data=file.file.read(MAX_SCHEMA_HINT_BYTES + 1),
            note=note,
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": result.summary["schema_version"],
                "relational_schema_hint_artifact_id": result.artifact.id,
                "relational_schema_hint_report_artifact_id": result.report_artifact.id,
                "report_id": result.report.id,
                "evidence_id": result.evidence.id,
                "artifact_id": result.artifact.id,
                "artifact_ids": [result.artifact.id, result.report_artifact.id],
                "content_type": result.summary["content_type"],
                "media_kind": result.summary["media_kind"],
                "parsed_table_count": result.summary["parsed_table_count"],
                "parsed_relationship_count": result.summary["parsed_relationship_count"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/import", response_model=BenchmarkImportResponse)
def import_benchmark_dataset(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkImportRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    settings = request.app.state.settings
    try:
        benchmark = raw_benchmark_dataset(benchmark_id)
        root = resolve_benchmark_root(settings, benchmark_id, payload.local_path)
        local_status = validate_required_files(benchmark, root)
        primary_file = select_primary_file(benchmark, root, payload.primary_file)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    catalog_target = (benchmark.get("primary_table") or {}).get("target_column")
    effective_target = payload.target_column or catalog_target or project.target_column
    if effective_target and effective_target != project.target_column:
        project.target_column = str(effective_target)

    primary_relative_path = relative_path(root, primary_file)
    job = create_job(
        db,
        job_type="import_benchmark_dataset",
        project_id=project_id,
        input_payload={
            "benchmark_id": benchmark_id,
            "local_path": str(root),
            "primary_file": primary_relative_path,
            "target_column": effective_target,
        },
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "user_managed_outside_tablex",
        },
    )
    try:
        mark_job_running(job)
        version = next_artifact_version(db, project_id, "dataset_snapshot", f"benchmark_{benchmark_id}")
        artifact_dir, stored, content_hash = store.store_existing_file(
            org_id="local-org",
            project_id=project_id,
            asset_type="dataset_snapshot",
            name=f"benchmark_{benchmark_id}",
            version=version,
            source_path=primary_file,
            filename=primary_file.name,
            metadata={
                "project_id": project_id,
                "source_type": "benchmark_catalog",
                "benchmark_id": benchmark_id,
                "benchmark_name": benchmark.get("name"),
                "source_url": benchmark.get("source_url"),
                "primary_file": primary_relative_path,
            },
        )
        dataset_artifact = register_artifact(
            db,
            project_id=project_id,
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
                "project_id": project_id,
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
        import_manifest_artifact = store_and_register_json(
            db,
            store,
            project_id=project_id,
            asset_type="benchmark_import_manifest",
            name=f"benchmark_import_{benchmark_id}",
            filename="benchmark_import_manifest.json",
            payload=import_manifest,
            metadata={
                "project_id": project_id,
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
        relational_catalog_artifact = store_and_register_json(
            db,
            store,
            project_id=project_id,
            asset_type="relational_catalog",
            name=f"relational_catalog_{benchmark_id}",
            filename="relational_catalog.json",
            payload=relational_catalog,
            metadata={
                "project_id": project_id,
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
            project_id=project_id,
            benchmark=benchmark,
            root=root,
            primary_file=primary_file,
            relational_catalog_artifact=relational_catalog_artifact,
        )
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="artifact",
            from_asset_id=import_manifest_artifact.id,
            to_asset_type="dataset_snapshot",
            to_asset_id=dataset.id,
            relation_type="describes_source",
        )
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=relational_catalog_artifact.id,
            relation_type="profiles_table_bundle",
        )
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="artifact",
            from_asset_id=import_manifest_artifact.id,
            to_asset_type="artifact",
            to_asset_id=relational_catalog_artifact.id,
            relation_type="summarizes_bundle",
        )
        project.current_phase = "UNDERSTANDING_REVIEW"
        project.updated_at = utc_now()
        mark_job_succeeded(
            job,
            {
                "benchmark_id": benchmark_id,
                "dataset_snapshot_id": dataset.id,
                "artifact_id": dataset_artifact.id,
                "import_manifest_artifact_id": import_manifest_artifact.id,
                "relational_catalog_artifact_id": relational_catalog_artifact.id,
                "primary_file": primary_relative_path,
                "target_column": effective_target,
                "table_count": relational_catalog["table_count"],
                "relationship_count": len(relational_catalog["relationships"]),
                "supporting_table_artifact_ids": [artifact.id for artifact in supporting_tables.artifacts],
                "skipped_supporting_tables": supporting_tables.skipped,
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise

    benchmark_payload = benchmark_to_dict(benchmark, settings=settings, include_status=True)
    benchmark_payload["local_status"] = local_status
    return {
        "benchmark": benchmark_payload,
        "dataset_snapshot": dataset_to_dict(dataset),
        "artifact": artifact_to_dict(dataset_artifact),
        "import_manifest_artifact": artifact_to_dict(import_manifest_artifact),
        "relational_catalog_artifact": artifact_to_dict(relational_catalog_artifact),
        "supporting_table_artifacts": [artifact_to_dict(artifact) for artifact in supporting_tables.artifacts],
        "skipped_supporting_tables": supporting_tables.skipped,
        "profile_job_id": job.id,
        "primary_file": primary_relative_path,
    }


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/scenario-pack", response_model=JobRead)
def create_project_benchmark_scenario_pack(
    project_id: str,
    benchmark_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    settings = request.app.state.settings
    try:
        benchmark = raw_benchmark_dataset(benchmark_id)
        root = default_benchmark_root(settings, benchmark_id)
        local_status = latest_benchmark_import_local_status(db, project_id, benchmark_id) or inspect_benchmark_local_files(
            benchmark, root
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Benchmark dataset not found") from exc
    job = create_job(
        db,
        job_type="create_benchmark_scenario_pack",
        project_id=project_id,
        input_payload={"benchmark_id": benchmark_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    try:
        mark_job_running(job)
        result = create_benchmark_scenario_pack(
            db,
            store=store,
            project=project,
            benchmark=benchmark,
            local_status=local_status,
        )
        mark_job_succeeded(
            job,
            {
                "benchmark_id": benchmark_id,
                "schema_version": result.pack["schema_version"],
                "scenario_kind": result.pack["scenario"]["kind"],
                "benchmark_scenario_pack_artifact_id": result.pack_artifact.id,
                "benchmark_scenario_report_artifact_id": result.report_artifact.id,
                "dataset_snapshot_id": result.pack["dataset"].get("dataset_snapshot_id"),
                "supporting_table_artifact_count": len(result.pack["supporting_table_artifacts"]),
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/collection-plan", response_model=JobRead)
def create_project_benchmark_collection_plan(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_benchmark_collection_plan",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    try:
        mark_job_running(job)
        result = create_benchmark_collection_plan(
            db,
            store=store,
            project=project,
            settings=request.app.state.settings,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
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
                "artifact_ids": result.artifact_ids,
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-plan", response_model=JobRead)
def create_project_relational_feature_plan(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_relational_feature_plan",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    try:
        mark_job_running(job)
        result = create_relational_feature_plan(db, store=store, project=project, job=job)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.plan["schema_version"],
                "benchmark_id": result.plan["source_summary"].get("benchmark_id"),
                "relational_feature_plan_artifact_id": result.plan_artifact.id,
                "relational_feature_report_id": result.report.id,
                "relational_feature_report_artifact_id": result.report_artifact.id,
                "visualization_id": result.visualization.id,
                "visualization_artifact_id": result.visualization_artifact.id,
                "evidence_id": result.evidence.id,
                "artifact_ids": result.artifact_ids,
                "table_count": result.plan["table_coverage"]["table_count"],
                "supporting_table_count": result.plan["table_coverage"]["supporting_table_count"],
                "relationship_count": result.plan["table_coverage"]["relationship_count"],
                "aggregation_candidate_count": len(result.plan["aggregation_candidates"]),
                "high_risk_count": len(
                    [item for item in result.plan["risk_register"] if item["risk_level"] == "high"]
                ),
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-recipe/build", response_model=JobRead)
def build_project_relational_feature_recipe(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="build_relational_feature_recipe",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
            "model_training": "not_performed_preview_only",
        },
    )
    try:
        mark_job_running(job)
        result = build_relational_feature_recipe(db, store=store, project=project, job=job)
        mark_job_succeeded(
            job,
            {
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
                "artifact_ids": result.artifact_ids,
                "generated_feature_count": len(result.preview_profile["generated_feature_columns"]),
                "executed_step_count": len(result.recipe["steps"]),
                "deferred_step_count": len(result.recipe["deferred_steps"]),
                "preview_row_count": result.preview_profile["preview_row_count"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/features/relational-scenarios/diagnose", response_model=JobRead)
def diagnose_project_relational_feature_scenarios(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="diagnose_relational_feature_scenarios",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
            "model_training": "not_performed_diagnostics_only",
        },
    )
    try:
        mark_job_running(job)
        result = diagnose_relational_feature_scenarios(db, store=store, project=project, job=job)
        summary = result.diagnostics["preview_summary"]
        deferred = result.diagnostics["deferred_reason_summary"]
        mark_job_succeeded(
            job,
            {
                "schema_version": result.diagnostics["schema_version"],
                "benchmark_id": result.diagnostics["source_summary"].get("benchmark_id"),
                "relational_feature_scenario_diagnostics_artifact_id": result.diagnostics_artifact.id,
                "relational_feature_scenario_report_id": result.report.id,
                "relational_feature_scenario_report_artifact_id": result.report_artifact.id,
                "visualization_id": result.visualization.id,
                "visualization_artifact_id": result.visualization_artifact.id,
                "evidence_id": result.evidence.id,
                "artifact_ids": result.artifact_ids,
                "generated_feature_count": summary["generated_feature_count"],
                "usable_feature_count": summary["usable_feature_count"],
                "constant_feature_count": summary["constant_feature_count"],
                "high_missing_feature_count": summary["high_missing_feature_count"],
                "deferred_step_count": deferred["total_deferred_step_count"],
                "scenario_count": len(result.diagnostics["scenario_comparison"]),
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/evidence-pack", response_model=JobRead)
def create_project_benchmark_evidence_pack(
    project_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_benchmark_evidence_pack",
        project_id=project_id,
        input_payload={"project_id": project_id},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_performed",
        },
    )
    try:
        mark_job_running(job)
        result = create_benchmark_evidence_pack(
            db,
            store=store,
            project=project,
            settings=request.app.state.settings,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
                "benchmark_count": result.pack["benchmark_count"],
                "benchmark_ids": [entry["benchmark_id"] for entry in result.pack["benchmarks"]],
                "benchmark_evidence_pack_artifact_id": result.pack_artifact.id,
                "benchmark_evidence_report_id": result.report.id,
                "benchmark_evidence_report_artifact_id": result.report_artifact.id,
                "visualization_id": result.visualization.id,
                "visualization_artifact_id": result.visualization_artifact.id,
                "evidence_id": result.evidence.id,
                "artifact_ids": result.artifact_ids,
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/fixture-smoke", response_model=JobRead)
def run_benchmark_fixture_smoke(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkFixtureRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="run_benchmark_fixture_smoke",
        project_id=project_id,
        input_payload={"benchmark_id": benchmark_id, "overwrite": payload.overwrite},
        policy={
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "not_required_for_fixture",
        },
    )
    try:
        mark_job_running(job)
        fixture = generate_benchmark_fixture(
            request.app.state.settings,
            benchmark_id,
            overwrite=payload.overwrite,
        )
        if not fixture["fixture_matches_expected"]:
            raise ValueError(
                "Existing benchmark files do not match the Tablex fixture. "
                "Use overwrite=true to replace fixture files, or run normal benchmark import manually."
            )
        import_result = import_benchmark_dataset(
            project_id,
            benchmark_id,
            BenchmarkImportRequest(target_column=None),
            request,
            db,
            store,
        )
        dataset_id = import_result["dataset_snapshot"]["id"]
        dataset = db.get(DatasetSnapshot, dataset_id)
        if dataset is None:
            raise ValueError("Fixture import did not produce a DatasetSnapshot")
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
        supporting_artifact_ids = [item["id"] for item in import_result.get("supporting_table_artifacts", [])]
        supporting_artifacts = (
            list(db.scalars(select(Artifact).where(Artifact.id.in_(supporting_artifact_ids))).all())
            if supporting_artifact_ids
            else []
        )
        scenario = create_benchmark_scenario_pack(
            db,
            store=store,
            project=project,
            benchmark=raw_benchmark_dataset(benchmark_id),
            local_status=fixture["local_status"],
            fixture=fixture,
            dataset=dataset,
            supporting_table_artifacts=supporting_artifacts,
            skipped_supporting_tables=import_result.get("skipped_supporting_tables", []),
        )
        artifact_ids = [
            import_result["artifact"]["id"],
            import_result["import_manifest_artifact"]["id"],
            import_result["relational_catalog_artifact"]["id"],
            *supporting_artifact_ids,
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
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except HTTPException as exc:
        mark_job_failed(job, str(exc.detail))
        raise
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/benchmarks/{benchmark_id}/public-workflow", response_model=JobRead)
def run_public_benchmark_workflow(
    project_id: str,
    benchmark_id: str,
    payload: BenchmarkPublicDownloadRequest,
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="run_public_benchmark_workflow",
        project_id=project_id,
        input_payload={"benchmark_id": benchmark_id, "overwrite": payload.overwrite},
        policy={
            "network": "enabled_for_catalog_public_archive_or_direct_file_only",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "external_download": "catalog_credential_free_sources_only",
        },
    )
    try:
        mark_job_running(job)
        download_manifest = download_public_benchmark_archive(
            request.app.state.settings,
            benchmark_id,
            overwrite=payload.overwrite,
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
        import_result = import_benchmark_dataset(
            project_id,
            benchmark_id,
            BenchmarkImportRequest(target_column=None),
            request,
            db,
            store,
        )
        dataset_id = import_result["dataset_snapshot"]["id"]
        dataset = db.get(DatasetSnapshot, dataset_id)
        if dataset is None:
            raise ValueError("Public benchmark workflow did not produce a DatasetSnapshot")

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
        baseline = run_baseline_service(
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

        supporting_artifact_ids = [item["id"] for item in import_result.get("supporting_table_artifacts", [])]
        supporting_artifacts = (
            list(db.scalars(select(Artifact).where(Artifact.id.in_(supporting_artifact_ids))).all())
            if supporting_artifact_ids
            else []
        )
        scenario = create_benchmark_scenario_pack(
            db,
            store=store,
            project=project,
            benchmark=raw_benchmark_dataset(benchmark_id),
            local_status=download_manifest["local_status"],
            dataset=dataset,
            supporting_table_artifacts=supporting_artifacts,
            skipped_supporting_tables=import_result.get("skipped_supporting_tables", []),
        )
        artifact_ids = list(
            dict.fromkeys(
                [
                    download_artifact.id,
                    import_result["artifact"]["id"],
                    import_result["import_manifest_artifact"]["id"],
                    import_result["relational_catalog_artifact"]["id"],
                    *supporting_artifact_ids,
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
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except HTTPException as exc:
        mark_job_failed(job, str(exc.detail))
        raise
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/datasets", response_model=list[DatasetSnapshotRead])
def list_project_datasets(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    datasets = db.scalars(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    ).all()
    return [dataset_to_dict(item) for item in datasets]


@router.get("/api/datasets/{dataset_id}", response_model=DatasetSnapshotRead)
def get_dataset(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    return dataset_to_dict(dataset)


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


@router.get("/api/datasets/{dataset_id}/sample")
def get_dataset_sample(dataset_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    profile = latest_profile_for_dataset(db, dataset)
    return {"rows": profile.get("sample_rows", [])}


@router.post("/api/datasets/{dataset_id}/quality/run", response_model=JobRead)
def run_dataset_quality(
    dataset_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    project = require_project(db, dataset.project_id)
    job = create_job(
        db,
        job_type="analyze_data_quality",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id},
    )
    try:
        mark_job_running(job)
        result = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
        mark_job_succeeded(
            job,
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_ids": result.artifact_ids,
                "gate": result.gate,
                "evidence_ids": result.evidence_ids,
                "assumption_ids": result.assumption_ids,
                "question_ids": result.question_ids,
                "insight_id": result.insight_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
def rerun_profile(dataset_id: str, db: Annotated[Session, Depends(get_session)], store: Annotated[LocalArtifactStore, Depends(get_artifact_store)]) -> dict[str, Any]:
    dataset = require_dataset(db, dataset_id)
    project = require_project(db, dataset.project_id)
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    job = create_job(
        db,
        job_type="profile_dataset",
        project_id=project.id,
        input_payload={"dataset_snapshot_id": dataset.id, "artifact_id": artifact.id},
    )
    try:
        mark_job_running(job)
        profile_dataset_artifact(db, store, project, artifact, project.target_column)
        mark_job_succeeded(job, {"dataset_snapshot_id": dataset.id})
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/understanding/run", response_model=JobRead)
def run_understanding(project_id: str, db: Annotated[Session, Depends(get_session)], store: Annotated[LocalArtifactStore, Depends(get_artifact_store)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before running understanding")
    artifact = db.get(Artifact, dataset.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    job = create_job(db, job_type="profile_dataset", project_id=project_id, input_payload={"dataset_snapshot_id": dataset.id})
    try:
        mark_job_running(job)
        profile_dataset_artifact(db, store, project, artifact, project.target_column)
        mark_job_succeeded(job, {"dataset_snapshot_id": dataset.id})
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
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
    job = create_job(db, job_type="infer_assumptions", project_id=project_id, input_payload={"apply_unanswered_fallbacks": True})
    mark_job_running(job)
    unresolved = db.scalars(select(Question).where(Question.project_id == project_id, Question.status == "open")).all()
    mark_job_succeeded(job, {"unanswered_questions": len(unresolved), "policy": "fallbacks_already_materialized_in_assumptions"})
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
def design_evaluation(project_id: str, db: Annotated[Session, Depends(get_session)], store: Annotated[LocalArtifactStore, Depends(get_artifact_store)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before designing evaluation")
    job = create_job(db, job_type="design_evaluation_candidates", project_id=project_id, input_payload={"dataset_snapshot_id": dataset.id})
    try:
        mark_job_running(job)
        candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
        mark_job_succeeded(job, {"evaluation_candidate_ids": [candidate.id for candidate in candidates]})
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/evaluation/compare", response_model=JobRead)
def compare_evaluation_scenarios(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    if dataset is None:
        raise HTTPException(status_code=400, detail="Upload a dataset before comparing evaluation scenarios")
    job = create_job(
        db,
        job_type="compare_evaluation_scenarios",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id},
    )
    try:
        mark_job_running(job)
        candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
        artifact = create_evaluation_scenario_comparison(
            db,
            store=store,
            project=project,
            dataset=dataset,
            candidates=list(candidates),
        )
        metadata = loads_json(artifact.metadata_json, {})
        mark_job_succeeded(
            job,
            {
                "dataset_snapshot_id": dataset.id,
                "artifact_id": artifact.id,
                "candidate_count": len(candidates),
                "recommended_candidate_id": metadata.get("recommended_candidate_id"),
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    job = create_job(
        db,
        job_type="review_evaluation_approval",
        project_id=spec.project_id,
        input_payload={"evaluation_spec_id": spec.id, "approval_intent": False},
    )
    try:
        mark_job_running(job)
        result = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=False)
        decision = result.payload["decision_support"]
        mark_job_succeeded(
            job,
            {
                "evaluation_spec_id": spec.id,
                "artifact_id": result.artifact.id,
                "review_status": decision["review_status"],
                "blocked": decision["blocked"],
                "blocker_count": decision["blocker_count"],
                "warning_count": decision["warning_count"],
            },
        )
    except Exception as exc:
        mark_job_failed(job, str(exc))
        raise
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


@router.post("/api/evaluation-specs/{spec_id}/generate-split", response_model=SplitManifestRead)
def generate_split(spec_id: str, db: Annotated[Session, Depends(get_session)], store: Annotated[LocalArtifactStore, Depends(get_artifact_store)]) -> dict[str, Any]:
    spec = require_eval_spec(db, spec_id)
    job = create_job(db, job_type="build_split_manifest", project_id=spec.project_id, input_payload={"evaluation_spec_id": spec.id})
    try:
        mark_job_running(job)
        split = generate_split_manifest(db, store=store, spec=spec)
        mark_job_succeeded(job, {"split_manifest_id": split.id})
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return split_to_dict(split)


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
) -> dict[str, Any]:
    project = require_project(db, project_id)
    return build_adaptive_strategy_brief(db, project=project)


@router.post("/api/projects/{project_id}/approach/strategy-brief", response_model=JobRead)
def create_project_strategy_brief(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_adaptive_strategy_brief",
        project_id=project_id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        result = create_adaptive_strategy_brief(db, store=store, project=project, job=job)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.brief["schema_version"],
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-plan", response_model=JobRead)
def generate_project_research_plan(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
    try:
        mark_job_running(job)
        result = create_research_plan(
            db,
            store=store,
            project=project,
            dataset=dataset,
            evaluation_spec=spec,
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": result.plan["schema_version"],
                "artifact_id": result.artifact.id,
                "query_count": len(result.plan.get("query_plan", [])),
                "recommended_asset_count": len(result.plan.get("skill_plan", {}).get("recommended_references", [])),
                "network_default": result.plan["source_policy"]["network_default"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/agent-task-plan", response_model=JobRead)
def plan_project_agent_task_endpoint(
    project_id: str,
    payload: AgentTaskPlanCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
    try:
        mark_job_running(job)
        result = plan_project_agent_task(
            db,
            store=store,
            project=project,
            job=job,
            objective=payload.objective,
            task_type=payload.task_type,
        )
        inputs = cast(dict[str, Any], result.contract["inputs"])
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/agent-chat", response_model=AgentChatRead)
def create_agent_chat_turn(
    project_id: str,
    payload: AgentChatCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    session = active_main_session(db, project_id)
    sidecar_only = is_sidecar_chat_request(payload.message)
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
            run_after=utc_now() + MAIN_SESSION_CHAT_DELIVERY_RUN_AFTER,
        )
        response = queued_main_session_chat_response(
            project=project,
            session=session,
            event=event,
            job=job,
            message=payload.message,
            locale=payload.locale,
            progress_event=progress_event,
        )
        db.commit()
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


def queued_main_session_chat_response(
    *,
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
            "mode": "queued_worker",
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


@router.get("/api/projects/{project_id}/agent-chat/history", response_model=list[AgentChatHistoryTurnRead])
def list_agent_chat_history(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
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
        if not isinstance(payload, dict) or payload.get("schema_version") != "agent_chat_turn.v1":
            continue
        metadata = loads_json(artifact.metadata_json, {})
        assistant_message = str(payload.get("assistant_message") or "")
        intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
        if intent.get("type") == "autonomous_agent_progress_report":
            assistant_message = chat_update_message_from_text(assistant_message)
        if isinstance(metadata.get("job_id"), str):
            seen_job_ids.add(metadata["job_id"])
        turn = {
            "schema_version": "agent_chat_turn.v1",
            "project_id": project_id,
            "user_message": str(payload.get("user_message") or ""),
            "assistant_message": assistant_message,
            "intent": intent,
            "actions": payload.get("actions") if isinstance(payload.get("actions"), list) else [],
            "action_summary": payload.get("action_summary") if isinstance(payload.get("action_summary"), dict) else {},
            "response_brief": payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else None,
            "response_composer": payload.get("response_composer") if isinstance(payload.get("response_composer"), dict) else None,
            "worker_events": payload.get("worker_events") if isinstance(payload.get("worker_events"), list) else [],
            "token_usage": payload.get("token_usage") if isinstance(payload.get("token_usage"), dict) else {},
            "next_focus": payload.get("next_focus") if isinstance(payload.get("next_focus"), dict) else {},
            "artifact_id": artifact.id,
            "job_id": metadata.get("job_id") if isinstance(metadata.get("job_id"), str) else None,
            "created_at": artifact.created_at.isoformat(),
        }
        if metadata.get("source") == "main_codex_session_chat_update" and isinstance(metadata.get("agent_session_id"), str):
            turn["agent_session_id"] = metadata["agent_session_id"]
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
            turns.append(agent_chat_turn_from_main_session_update(project_id, job, payload, paired_update))
            progress_artifact_id = paired_update.get("artifact_id")
            if isinstance(progress_artifact_id, str):
                paired_update_ids.add(progress_artifact_id)
        else:
            turns.append(pending_agent_chat_turn_from_job(project_id, job, payload))
    paired_update_ids.update({
        str(turn.get("paired_progress_artifact_id"))
        for turn in turns
        if isinstance(turn.get("paired_progress_artifact_id"), str)
    })
    turns.extend(
        turn for turn in main_session_update_turns if isinstance(turn.get("artifact_id"), str) and turn["artifact_id"] not in paired_update_ids
    )
    return compact_agent_chat_history_turns(turns)


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
    project_id: str,
    job: Job,
    payload: dict[str, Any],
    update_turn: dict[str, Any],
) -> dict[str, Any]:
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else "en-US"
    delivered_session_id = payload.get("delivered_agent_session_id")
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


def pending_agent_chat_turn_from_job(project_id: str, job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    output = loads_json(job.output_json, {})
    locale = payload.get("locale") if isinstance(payload.get("locale"), str) else "en-US"
    japanese = locale_is_japanese(locale)
    delivered_session_id = payload.get("delivered_agent_session_id")
    delivered_to_running_codex = isinstance(delivered_session_id, str) and bool(delivered_session_id.strip())
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
            "source": "agent_chat_turn_job",
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
            "mode": "queued_worker",
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
    max_turns: int = 60,
    max_autonomous_progress_turns: int = 12,
) -> list[dict[str, Any]]:
    ordered = sorted(turns, key=lambda turn: str(turn.get("created_at") or ""))
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


@router.get("/api/projects/{project_id}/research-plan/timeline")
def get_research_plan_timeline(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    locale: str | None = None,
) -> dict[str, Any]:
    require_project(db, project_id)
    response = build_research_plan_timeline_response(db, project_id=project_id, locale=locale)
    localization = response.get("localization") if isinstance(response, dict) else None
    missing_count = 0
    if isinstance(localization, dict):
        missing_count = int(localization.get("missing_block_count") or 0) + int(
            localization.get("missing_subtask_count") or 0
        )
    if missing_count:
        session = active_main_session(db, project_id)
        artifact_id = response.get("source_artifact_id") if isinstance(response, dict) else None
        artifact = db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
        if session is not None and artifact is not None:
            maybe_request_research_plan_locale_refresh(db, session=session, artifact=artifact, locale=locale)
            db.commit()
    return response


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
        "stdout_line_count": stdout_count,
        "stderr_line_count": stderr_count,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "stdout_tail_lines": stdout_tail_lines,
        "stderr_tail_lines": stderr_tail_lines,
        "updated_at": max((item for item in (stdout_updated_at, stderr_updated_at) if item), default=None),
    }


@router.post("/api/agent-task-contracts/{artifact_id}/prepare-workspace", response_model=JobRead)
def prepare_planned_agent_workspace_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="AgentTaskContract artifact is not project-scoped")
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
            "execution": "not_started",
        },
    )
    try:
        mark_job_running(job)
        result = prepare_workspace_from_contract_artifact(
            db,
            store=store,
            project=project,
            contract_artifact=contract_artifact,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/readiness-review", response_model=JobRead)
def review_agent_task_readiness_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="AgentTaskContract artifact is not project-scoped")
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
            "execution": "not_started",
        },
    )
    try:
        mark_job_running(job)
        result = review_agent_task_readiness(
            db,
            store=store,
            project=project,
            contract_artifact=contract_artifact,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/run-local-stub", response_model=JobRead)
def run_planned_agent_task_stub_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="AgentTaskContract artifact is not project-scoped")
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
        },
    )
    try:
        mark_job_running(job)
        result = run_planned_agent_task_local_stub(
            db,
            store=store,
            project=project,
            contract_artifact=contract_artifact,
            job=job,
        )
        mark_job_succeeded(job, planned_agent_execution_job_output(contract_artifact, result))
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/agent-task-contracts/{artifact_id}/run-codex", response_model=JobRead)
def run_planned_agent_task_codex_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    contract_artifact = db.get(Artifact, artifact_id)
    if contract_artifact is None:
        raise HTTPException(status_code=404, detail="AgentTaskContract artifact not found")
    if contract_artifact.asset_type != "agent_task_contract":
        raise HTTPException(status_code=400, detail="Artifact is not an agent_task_contract")
    if contract_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="AgentTaskContract artifact is not project-scoped")
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
        },
    )
    try:
        mark_job_running(job)
        result = run_planned_agent_task_codex_cli(
            db,
            store=store,
            project=project,
            contract_artifact=contract_artifact,
            job=job,
        )
        output = planned_agent_execution_job_output(contract_artifact, result)
        if result.agent_result.status == "failed":
            mark_job_failed(job, result.agent_result.failure_reason or result.agent_result.final_message, output)
        else:
            mark_job_succeeded(job, output)
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
        },
    )
    try:
        mark_job_running(job)
        result = create_research_source_pack(
            db,
            store=store,
            project=project,
            dataset=dataset,
            evaluation_spec=spec,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/research-source-packs/{artifact_id}/run-local-stub", response_model=JobRead)
def run_research_source_pack_stub_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
        },
    )
    try:
        mark_job_running(job)
        result = run_research_source_pack_local_stub(
            db,
            store=store,
            project=project,
            source_pack_artifact=source_pack_artifact,
            job=job,
        )
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-synthesis", response_model=JobRead)
def create_project_research_synthesis(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="create_research_synthesis",
        project_id=project.id,
        input_payload={},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
        },
    )
    try:
        mark_job_running(job)
        result = create_research_finding_synthesis(db, store=store, project=project, job=job)
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/approach/research-briefs", response_model=JobRead)
def generate_project_research_brief(
    project_id: str,
    payload: ResearchBriefCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    dataset = latest_dataset(db, project_id)
    spec = latest_approved_spec(db, project_id)
    job = create_job(
        db,
        job_type="generate_research_brief",
        project_id=project_id,
        input_payload={"dataset_snapshot_id": dataset.id if dataset else None, "evaluation_spec_id": spec.id if spec else None},
    )
    try:
        mark_job_running(job)
        result = generate_research_brief(
            db,
            store=store,
            project=project,
            dataset=dataset,
            evaluation_spec=spec,
            question=payload.question,
        )
        mark_job_succeeded(job, {"research_brief_id": result.brief.id, "artifact_id": result.artifact.id})
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
    )
    try:
        mark_job_running(job)
        result = generate_approach_candidates(
            db,
            store=store,
            project=project,
            research_brief=brief,
            dataset=dataset,
            evaluation_spec=spec,
        )
        mark_job_succeeded(
            job,
            {"idea_ids": [idea.id for idea in result.ideas], "artifact_ids": result.artifact_ids},
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
    )
    try:
        mark_job_running(job)
        result = prepare_idea_agent_context_pack(db, store=store, project=project, idea=idea, job=job)
        mark_job_succeeded(
            job,
            {
                "idea_id": idea.id,
                "context_pack_id": result.context_pack["id"],
                "artifact_id": result.artifact.id,
                "schema_version": result.context_pack["schema_version"],
                "asset_recommendation_count": len(result.context_pack["asset_recommendations"]),
                "materialized_library_asset_count": len(result.context_pack["materialized_library_assets"]),
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
    )
    try:
        mark_job_running(job)
        result = create_experiment_plan_for_idea(db, store=store, project=project, idea=idea, job=job)
        mark_job_succeeded(
            job,
            {
                "idea_id": idea.id,
                "plan_id": result.plan["id"],
                "artifact_id": result.artifact.id,
                "evidence_id": result.evidence_id,
                "insight_id": result.insight_id,
                "readiness": result.plan["readiness"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
    )
    try:
        mark_job_running(job)
        result = run_idea_agent_task_stub(db, store=store, project=project, idea=idea, job=job)
        mark_job_succeeded(
            job,
            {
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
                "source_citation_manifest_artifact_id": (
                    result.experiment_ingestion.citation_manifest_artifact_id
                ),
                "citation_audit_report_id": result.experiment_ingestion.citation_audit_report_id,
                "citation_audit_report_artifact_id": (
                    result.experiment_ingestion.citation_audit_report_artifact_id
                ),
                "citation_evidence_id": result.experiment_ingestion.citation_evidence_id,
                "citation_visualization_id": result.experiment_ingestion.citation_visualization_id,
                "citation_visualization_artifact_id": (
                    result.experiment_ingestion.citation_visualization_artifact_id
                ),
                "visualization_ids": result.experiment_ingestion.visualization_ids,
                "requires_human_review": result.agent_result.requires_human_review,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/reports/draft", response_model=JobRead)
def draft_report_endpoint(
    project_id: str,
    payload: ReportCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="draft_project_report",
        project_id=project_id,
        input_payload={"title": payload.title, "report_type": payload.report_type},
    )
    try:
        mark_job_running(job)
        result = draft_project_report(
            db,
            store=store,
            project=project,
            title=payload.title,
            report_type=payload.report_type,
        )
        mark_job_succeeded(job, {"report_id": result.report.id, "artifact_id": result.artifact.id})
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="prepare_result_notebook_evidence",
        project_id=project_id,
        input_payload={"triggered_by": "result_readout"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "generate_and_safe_static_capture",
            "executes_notebook_code": False,
        },
    )
    try:
        mark_job_running(job)
        result = prepare_result_notebook_evidence(db, store=store, project=project)
        mark_job_succeeded(job, result_notebook_evidence_job_output(result))
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/decision-report/generate", response_model=JobRead)
def generate_decision_report_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(db, job_type="generate_decision_report", project_id=project_id, input_payload={})
    try:
        mark_job_running(job)
        result = create_decision_report_v1(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
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
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    return artifact_preview_to_dict(artifact, path, limit_bytes=artifact_preview_limit_bytes(artifact, path))


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


@router.post("/api/reports/{report_id}/translate", response_model=TranslationRead)
def translate_report_endpoint(
    report_id: str,
    payload: TranslationCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
    try:
        mark_job_running(job)
        result = translate_artifact_service(
            db,
            store=store,
            artifact=artifact,
            source_report=report,
            source_locale=payload.source_locale,
            target_locale=payload.target_locale,
            job_id=job.id,
        )
        mark_translation_job_succeeded(job, result)
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return translation_result_to_dict(
        result,
        source_type="report",
        source_id=report.id,
        source_artifact_id=artifact.id,
        source_locale=payload.source_locale,
        target_locale=payload.target_locale,
        job=job,
    )


@router.post("/api/projects/{project_id}/visualizations/generate", response_model=JobRead)
def generate_visualization_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(db, job_type="create_visualization_spec", project_id=project_id, input_payload={})
    try:
        mark_job_running(job)
        result = create_project_visualization_dashboard(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "visualization_id": result.visualizations[0].id if result.visualizations else None,
                "visualization_ids": [visualization.id for visualization in result.visualizations],
                "artifact_ids": result.artifact_ids,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(db, job_type="generate_insights", project_id=project_id, input_payload={})
    try:
        mark_job_running(job)
        result = generate_project_insights(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "insight_ids": [insight.id for insight in result.insights],
                "artifact_id": result.artifact.id,
                "evidence_ids": result.evidence_ids,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/decision-dashboard/generate", response_model=JobRead)
def generate_decision_dashboard_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(db, job_type="generate_decision_dashboard", project_id=project_id, input_payload={})
    try:
        mark_job_running(job)
        result = create_decision_dashboard(db, store=store, project=project)
        dashboard_metadata = loads_json(result.dashboard_artifact.metadata_json, {})
        mark_job_succeeded(
            job,
            {
                "schema_version": result.dashboard["schema_version"],
                "readiness_status": dashboard_metadata.get("readiness_status"),
                "report_id": result.report.id,
                "decision_dashboard_artifact_id": result.dashboard_artifact.id,
                "decision_report_artifact_id": result.report_artifact.id,
                "visualization_ids": [visualization.id for visualization in result.visualizations],
                "artifact_ids": result.artifact_ids,
                "next_action_count": len(result.dashboard["next_actions"]),
                "risk_count": len(result.dashboard["risk_register"]),
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/projects/{project_id}/analysis-notebooks/data-understanding", response_model=JobRead)
def generate_data_understanding_notebook_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
    payload: DataUnderstandingNotebookCreate | None = None,
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
        },
    )
    try:
        mark_job_running(job)
        result = create_notebook_authoring_brief(
            db,
            store=store,
            project=project,
            objective=(
                "Author the project data-understanding marimo notebook from current artifacts and equipped Skills. "
                "Do not use harness-authored notebook prose."
            ),
            response_locale=response_locale,
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": "notebook_authoring_preparation.v1",
                "notebook_kind": "data_understanding",
                "response_locale": response_locale,
                "analysis_notebook_artifact_id": None,
                "notebook_html_artifact_id": None,
                "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
                "notebook_authoring_report_artifact_id": result.report_artifact.id,
                "notebook_run_manifest_artifact_id": None,
                "notebook_report_id": None,
                "notebook_report_artifact_id": None,
                "artifact_ids": result.artifact_ids,
                "execution_status": "awaiting_agent_authored_notebook",
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    notebook_artifact = db.get(Artifact, artifact_id)
    if notebook_artifact is None:
        raise HTTPException(status_code=404, detail="Analysis notebook artifact not found")
    if notebook_artifact.asset_type != "analysis_notebook":
        raise HTTPException(status_code=400, detail="Artifact is not an analysis_notebook")
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
        },
    )
    try:
        mark_job_running(job)
        result = create_notebook_execution_plan(db, store=store, notebook_artifact=notebook_artifact)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.plan["schema_version"],
                "task_id": result.contract["task_id"],
                "task_type": result.contract["task_type"],
                "notebook_kind": result.plan["notebook_kind"],
                "analysis_notebook_artifact_id": notebook_artifact.id,
                "agent_task_contract_artifact_id": result.contract_artifact.id,
                "notebook_execution_plan_artifact_id": result.plan_artifact.id,
                "artifact_ids": result.artifact_ids,
                "execution_status": "planned_not_executed",
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/analysis-notebooks/{artifact_id}/execution-capture", response_model=JobRead)
def capture_analysis_notebook_execution_endpoint(
    artifact_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    notebook_artifact = db.get(Artifact, artifact_id)
    if notebook_artifact is None:
        raise HTTPException(status_code=404, detail="Analysis notebook artifact not found")
    if notebook_artifact.asset_type != "analysis_notebook":
        raise HTTPException(status_code=400, detail="Artifact is not an analysis_notebook")
    if notebook_artifact.project_id is None:
        raise HTTPException(status_code=400, detail="Analysis notebook artifact must be project-scoped")
    require_project(db, notebook_artifact.project_id)
    job = create_job(
        db,
        job_type="capture_notebook_execution",
        project_id=notebook_artifact.project_id,
        input_payload={"analysis_notebook_artifact_id": notebook_artifact.id},
        policy={
            "external_network_access": "not_granted_by_harness",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "marimo_html_export_with_static_compile_precheck",
            "executes_notebook_code": True,
            "python_compile_only": False,
        },
    )
    try:
        mark_job_running(job)
        result = create_notebook_execution_capture(db, store=store, notebook_artifact=notebook_artifact)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.manifest["schema_version"],
                "notebook_kind": result.manifest["notebook_kind"],
                "analysis_notebook_artifact_id": notebook_artifact.id,
                "notebook_execution_manifest_artifact_id": result.manifest_artifact.id,
                "notebook_execution_report_id": result.report.id,
                "notebook_execution_report_artifact_id": result.report_artifact.id,
                "notebook_execution_html_artifact_id": result.html_artifact.id,
                "notebook_figure_manifest_artifact_id": result.figure_manifest_artifact.id,
                "notebook_execution_source_artifact_id": result.source_artifact.id,
                "notebook_evidence_bundle_artifact_id": result.evidence_bundle_artifact.id
                if result.evidence_bundle_artifact
                else None,
                "notebook_evidence_html_artifact_id": result.evidence_html_artifact.id
                if result.evidence_html_artifact
                else None,
                "notebook_evidence_figure_artifact_ids": [artifact.id for artifact in result.figure_artifacts],
                "notebook_execution_plan_artifact_id": result.plan_artifact.id,
                "agent_task_contract_artifact_id": result.contract_artifact.id,
                "artifact_ids": result.artifact_ids,
                "execution_status": result.manifest["execution_status"],
                "capture_mode": result.manifest["capture_mode"],
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/insights", response_model=list[InsightRead])
def list_project_insights(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    insights = db.scalars(select(Insight).where(Insight.project_id == project_id).order_by(Insight.created_at.desc())).all()
    return [insight_to_dict(item) for item in insights]


@router.post("/api/projects/{project_id}/baseline/run", response_model=JobRead)
def run_baseline_endpoint(
    project_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
    )
    try:
        mark_job_running(job)
        result = run_baseline_service(
            db,
            store=store,
            project=project,
            evaluation_spec=spec,
            split_manifest=split,
        )
        mark_job_succeeded(
            job,
            {
                "experiment_run_id": result.run.id,
                "model_version_id": result.model_version_id,
                "artifact_ids": result.artifact_ids,
                "metrics": result.metrics,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
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
    )
    try:
        mark_job_running(job)
        result = create_baseline_strategy_plan(
            db,
            store=store,
            project=project,
            evaluation_spec=spec,
            split_manifest=split,
        )
        mark_job_succeeded(
            job,
            {
                "baseline_strategy_plan_artifact_id": result.artifact.id,
                "strategy_count": len(result.plan.get("candidate_strategies", [])),
                "next_agent_task_count": len(result.plan.get("next_agent_tasks", [])),
                "selected_baseline_type": result.plan["selected_execution"].get("baseline_type"),
                "strategy_mode": result.plan.get("context", {}).get("strategy_mode"),
                "planning_source": result.plan.get("context", {}).get("current_baseline_plan", {}).get("planning_source"),
                "resource_guard_level": result.plan.get("context", {})
                .get("current_baseline_plan", {})
                .get("resource_guard", {})
                .get("level"),
                "matched_asset_count": result.plan.get("context", {})
                .get("library_context", {})
                .get("matched_asset_count"),
                "reporting_visualization_count": len(
                    result.plan.get("reporting_plan", {}).get("visualization_specs", [])
                ),
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/runs")
def list_runs(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(db, job_type="compare_experiments", project_id=project_id, input_payload={})
    try:
        mark_job_running(job)
        result = compare_project_experiments(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "artifact_ids": result.artifact_ids,
                "comparison": result.comparison,
                "visualization_id": result.visualization_id,
                "report_id": result.report_id,
                "evidence_id": result.evidence_id,
                "insight_id": result.insight_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/report", response_model=JobRead)
def draft_run_report_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(db, job_type="draft_run_report", project_id=run.project_id, input_payload={"run_id": run.id})
    try:
        mark_job_running(job)
        result = draft_run_report(db, store=store, run=run)
        mark_job_succeeded(
            job,
            {
                "run_id": run.id,
                "report_id": result.report.id,
                "artifact_id": result.artifact.id,
                "evidence_id": result.evidence_id,
                "insight_id": result.insight_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/diagnostics", response_model=JobRead)
def analyze_run_diagnostics_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(
        db,
        job_type="analyze_evaluation_diagnostics",
        project_id=run.project_id,
        input_payload={"run_id": run.id},
    )
    try:
        mark_job_running(job)
        result = analyze_run_diagnostics(db, store=store, run=run)
        mark_job_succeeded(
            job,
            {
                "run_id": run.id,
                "artifact_ids": result.artifact_ids,
                "diagnostics": result.diagnostics,
                "insight_id": result.insight_id,
                "evidence_id": result.evidence_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/model-diagnostics-artifacts", response_model=JobRead)
def materialize_model_diagnostics_artifacts_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
        },
    )
    try:
        mark_job_running(job)
        result = materialize_model_diagnostics_artifacts(db, store=store, run=run)
        mark_job_succeeded(
            job,
            {
                "run_id": run.id,
                "model_version_id": run.model_version_id,
                "artifact_ids": result.artifact_ids,
                "model_diagnostics_artifact_pack_id": result.artifact_ids[2],
                "model_diagnostics_report_artifact_id": result.artifact_ids[3],
                "feature_importance_artifact_id": result.artifact_ids[0],
                "permutation_importance_artifact_id": result.artifact_ids[1],
                "visualization_artifact_id": result.artifact_ids[4],
                "availability": result.diagnostics.get("availability", {}),
                "insight_id": result.insight_id,
                "evidence_id": result.evidence_id,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.post("/api/runs/{run_id}/analysis-notebook", response_model=JobRead)
def generate_run_analysis_notebook_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    project = require_project(db, run.project_id)
    job = create_job(
        db,
        job_type="prepare_model_diagnostics_notebook_authoring",
        project_id=run.project_id,
        input_payload={"run_id": run.id, "notebook_kind": "model_diagnostics"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "execution_mode": "prepare_authoring_context_only",
        },
    )
    try:
        mark_job_running(job)
        result = create_notebook_authoring_brief(
            db,
            store=store,
            project=project,
            objective=f"Author the model-diagnostics marimo notebook for ExperimentRun {run.id}.",
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": "notebook_authoring_preparation.v1",
                "notebook_kind": "model_diagnostics",
                "run_id": run.id,
                "model_version_id": run.model_version_id,
                "analysis_notebook_artifact_id": None,
                "notebook_html_artifact_id": None,
                "notebook_run_manifest_artifact_id": None,
                "notebook_report_id": None,
                "notebook_report_artifact_id": None,
                "visualization_id": None,
                "visualization_artifact_id": None,
                "notebook_authoring_brief_artifact_id": result.brief_artifact.id,
                "notebook_authoring_report_artifact_id": result.report_artifact.id,
                "artifact_ids": result.artifact_ids,
                "execution_status": "awaiting_agent_authored_notebook",
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job_to_dict(job)


@router.get("/api/projects/{project_id}/leaderboard")
def leaderboard(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    runs = db.scalars(
        select(ExperimentRun).where(ExperimentRun.project_id == project_id, ExperimentRun.status == "succeeded")
    ).all()
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
    return [
        {
            "rank": index + 1,
            "run_id": run.id,
            "status": run.status,
            "runner_type": run.runner_type,
            "primary_metric_name": metrics.get("primary_metric_name"),
            "primary_metric_value": metrics.get("primary_metric_value"),
            "display_metric_name": display_metric,
            "display_metric_value": display_metric_value,
            "display_metric_available": display_metric_value is not None,
            "display_metric_source": "metric_preference" if metric_preference else "run_primary_metric",
            "metrics": metrics,
            "evaluation_spec_id": run.evaluation_spec_id,
            "split_manifest_id": run.split_manifest_id,
            "model_version_id": run.model_version_id,
        }
        for index, run in enumerate(sorted_runs)
        for metrics in [loads_json(run.metrics_json, {})]
        for display_metric_value in [preferred_metric_value(metrics, display_metric)]
    ]


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
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    model_version = db.get(ModelVersion, model_version_id)
    if model_version is None:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    job = create_job(
        db,
        job_type="validate_model_package",
        project_id=model_version.project_id,
        input_payload={"model_version_id": model_version.id},
    )
    try:
        mark_job_running(job)
        result = validate_model_version_package(db, store=store, model_version=model_version)
        mark_job_succeeded(
            job,
            {
                "model_version_id": result.model_version.id,
                "artifact_ids": result.artifact_ids,
                "metrics": result.metrics,
            },
        )
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    return [artifact_to_dict(item) for item in artifacts]


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact_to_dict(artifact)


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> FileResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return FileResponse(path=path, filename=path.name)


@router.get("/api/artifacts/{artifact_id}/inline-preview")
def inline_preview_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
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
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    return artifact_preview_to_dict(artifact, path, limit_bytes=artifact_preview_limit_bytes(artifact, path))


@router.post("/api/artifacts/{artifact_id}/translate", response_model=TranslationRead)
def translate_artifact_endpoint(
    artifact_id: str,
    payload: TranslationCreate,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
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
    try:
        mark_job_running(job)
        result = translate_artifact_service(
            db,
            store=store,
            artifact=artifact,
            source_locale=payload.source_locale,
            target_locale=payload.target_locale,
            job_id=job.id,
        )
        mark_translation_job_succeeded(job, result)
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return translation_result_to_dict(
        result,
        source_type="artifact",
        source_id=artifact.id,
        source_artifact_id=artifact.id,
        source_locale=payload.source_locale,
        target_locale=payload.target_locale,
        job=job,
    )


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
    recovered_session = ensure_project_full_auto_agent_session(
        db,
        store=store,
        project=project,
        created_by=request_actor_id(request),
    )
    if recovered_session is not None:
        db.flush()
        db.commit()
        if not supervisor_slot_active(recovered_session.id):
            start_main_agent_session_supervisor_thread(
                request.app.state.session_factory,
                store,
                project_id=project_id,
                session_id=recovered_session.id,
                supervisor_runner=run_main_agent_session_supervisor,
            )
    jobs = list(
        db.scalars(
            select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(30)
        ).all()
    )
    active_job_ids = active_job_ids_for_activity(jobs)
    workers = [
        event
        for job in jobs
        for event in worker_events_from_job(job, project_name=project.name, active_job_ids=active_job_ids)
    ]
    session = active_main_session(db, project_id) or latest_main_session(db, project_id)
    raw_observation = raw_transcript_observation_for_session(session)
    if session is not None:
        session_processes = running_codex_processes_for_project(project_id)
        session_has_process = bool(session_processes)
        last_codex_output_at = latest_codex_transcript_output_at(db, session_id=session.id)
        heartbeat_age_seconds = seconds_since_timestamp(last_codex_output_at, now=utc_now())
        response_locale = latest_project_response_locale(db, project)
        heartbeat_phrase = heartbeat_phrase_for_locale(heartbeat_age_seconds, locale=response_locale)
        running_quietly = session_has_process and heartbeat_age_seconds is not None and heartbeat_age_seconds >= 120
        retry_state = latest_agent_session_retry_state(db, session.id)
        session_display_status = (
            "running"
            if session.status == "running" and session_has_process
            else "between_turns"
            if session.status == "running"
            else session.status
        )
        session_active = session_has_process or session.status in {"starting", "between_turns", "waiting_for_runner"}
        retry_delay = retry_state.get("retry_delay_seconds") if retry_state else None
        japanese = locale_is_japanese(response_locale)
        retry_detail = (
            (
                f"Codex runnerをまだ使えません。同じセッションを約{int(retry_delay)}秒後に再試行します。"
                if japanese
                else f"Codex runner is not ready; Tablex will retry this same session in about {retry_delay}s."
            )
            if isinstance(retry_delay, int | float)
            else (
                "Codex runnerをまだ使えません。同じセッションを継続して再試行します。"
                if japanese
                else "Codex runner is not ready; Tablex will keep retrying this same session."
            )
        )
        current_focus = latest_agent_session_activity_summary(db, project_id=project_id, session_id=session.id)
        display_name = "自律分析" if japanese else "Autonomous Analyst"
        running_detail = "CodexがProject workspaceで作業中です。" if japanese else "Codex is running in the project workspace now."
        preparing_detail = (
            "実行中のCodex processはまだ観測されていません。Full Autoは次のturnを準備しています。"
            if japanese
            else "No live Codex process is observed yet. Full Auto is preparing the next turn."
        )
        fallback_detail = (
            "コンテキスト準備、分析、または次のworker待ちです。"
            if japanese
            else "Preparing context, running analysis, or waiting for the next available worker."
        )
        progress_wait_detail = (
            "Projectはまだアクティブです。次のstepが始まるとここに進捗が出ます。"
            if japanese
            else "The project is still active. Progress will appear here when the next step starts."
        )
        running_headline = "静かに作業中" if japanese else "Codex is running quietly"
        working_headline = "Codexが作業中" if japanese else "Codex is working"
        retry_headline = "Codex runnerを再試行予定" if japanese else "Codex runner retry scheduled"
        continue_headline = "Full Autoは継続します" if japanese else "Full Auto will continue"
        headline = (
            running_headline
            if running_quietly
            else working_headline
            if session_has_process
            else retry_headline
            if session.status == "waiting_for_runner"
            else continue_headline
        )
        if session_has_process:
            session_detail = f"{current_focus or running_detail}{heartbeat_phrase}"
        elif session.status == "waiting_for_runner":
            session_detail = retry_detail
        elif session.status == "running":
            session_detail = preparing_detail
        else:
            session_detail = (
                current_focus
                or session.last_error
                or fallback_detail
            )
        if session_has_process:
            maybe_request_codex_progress_update(
                db,
                session=session,
                locale=response_locale,
            )
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
                "target_tab": "Home",
                "target_anchor": "agent-workspace",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "run_after": None,
                "active": session_active,
                "last_output_at": last_codex_output_at.isoformat() if last_codex_output_at else None,
                "last_output_seconds_ago": heartbeat_age_seconds,
                "raw_transcript": raw_observation,
                "human_description": {
                    "source": "agent_session",
                    "title": display_name,
                    "summary": current_focus or session_detail,
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
    active_workers = [worker for worker in workers if worker.get("active")]
    turn_state = build_project_turn_state(project, jobs, workers, active_job_ids=active_job_ids)
    visible_workers = visible_activity_workers(workers, now=utc_now())
    if session is not None and session.status in {"starting", "running", "between_turns", "waiting_for_runner"}:
        observed_processes = list(turn_state.get("codex_processes") or [])
        session_has_process = bool(observed_processes)
        last_codex_output_at = latest_codex_transcript_output_at(db, session_id=session.id)
        heartbeat_age_seconds = seconds_since_timestamp(last_codex_output_at, now=utc_now())
        heartbeat_phrase = heartbeat_phrase_for_locale(heartbeat_age_seconds, locale=response_locale)
        running_quietly = session_has_process and heartbeat_age_seconds is not None and heartbeat_age_seconds >= 120
        if session_has_process:
            turn_detail = f"{current_focus or running_detail}{heartbeat_phrase}"
        elif session.status == "waiting_for_runner":
            turn_detail = session_detail
        elif session.status == "running":
            turn_detail = preparing_detail
        else:
            turn_detail = (
                current_focus
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
        }
    return {
        "schema_version": "agent_activity.v1",
        "project_id": project_id,
        "generated_at": utc_now().isoformat(),
        "active_count": len(active_workers),
        "turn_state": turn_state,
        "workers": visible_workers[:20],
    }


def seconds_since_timestamp(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds()))


def latest_agent_session_activity_summary(db: Session, *, project_id: str, session_id: str, limit: int = 280) -> str | None:
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
        if metadata.get("source") != "main_codex_session_chat_update" or metadata.get("agent_session_id") != session_id:
            continue
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except OSError:
            continue
        message = payload.get("assistant_message")
        if isinstance(message, str) and message.strip():
            return compact_activity_summary(message, limit=limit)

    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session_id,
                AgentTranscriptEvent.source == "codex_cli",
                AgentTranscriptEvent.content.is_not(None),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(20)
        ).all()
    )
    for event in events:
        if event.content and event.content.strip() and not event.content.strip().startswith("usage:"):
            return compact_activity_summary(event.content, limit=limit)
    return None


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
    return visible


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


def profile_dataset_artifact(
    db: Session,
    store: LocalArtifactStore,
    project: Project,
    dataset_artifact: Artifact,
    target_column: str | None,
    source_type: str = "upload",
    source_ref: str | None = None,
) -> DatasetSnapshot:
    source_path = artifact_primary_path(dataset_artifact)
    result = profile_tabular_file(source_path, project.id, target_column)
    artifact_metadata = loads_json(dataset_artifact.metadata_json, {})
    dataset = DatasetSnapshot(
        id=new_id("ds"),
        project_id=project.id,
        artifact_id=dataset_artifact.id,
        source_type=source_type,
        source_ref=source_ref if source_ref is not None else artifact_metadata.get("source_filename"),
        row_count=result.row_count,
        column_count=result.column_count,
        schema_hash=result.schema_hash,
        data_hash=dataset_artifact.content_hash,
    )
    db.add(dataset)
    db.flush()

    profile_metadata = {
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "profile_mode": result.profile.get("profile_mode"),
        "column_stat_scope": result.profile.get("column_stat_scope"),
        "sample_row_count": (result.profile.get("profile_sample") or {}).get("sample_row_count"),
        "deep_profile_recommended": (result.profile.get("deferred_deep_profile") or {}).get("recommended"),
        "deferred_column_count": (result.profile.get("deferred_deep_profile") or {}).get("deferred_column_count"),
    }
    profile_artifact = store_and_register_json(
        db,
        store,
        project_id=project.id,
        asset_type="eda_profile",
        name="profile",
        filename="profile.json",
        payload=result.profile,
        metadata=profile_metadata,
    )
    understanding_artifact = store_and_register_text(
        db,
        store,
        project_id=project.id,
        asset_type="understanding_report",
        name="understanding",
        filename="understanding.md",
        text=result.understanding_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "profile_mode": result.profile.get("profile_mode"),
            "deep_profile_recommended": (result.profile.get("deferred_deep_profile") or {}).get("recommended"),
        },
    )
    semantic_artifact = store_and_register_json(
        db,
        store,
        project_id=project.id,
        asset_type="semantic_catalog",
        name="semantic_catalog",
        filename="semantic_catalog.json",
        payload=result.semantic_catalog,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_and_register_json(
        db,
        store,
        project_id=project.id,
        asset_type="question_set",
        name="questions",
        filename="questions.json",
        payload=result.questions,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_and_register_json(
        db,
        store,
        project_id=project.id,
        asset_type="assumption_set",
        name="assumptions",
        filename="assumptions.json",
        payload=result.assumptions,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_and_register_json(
        db,
        store,
        project_id=project.id,
        asset_type="evidence_set",
        name="evidence",
        filename="evidence.json",
        payload=result.evidence,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )

    catalog = SemanticCatalog(
        id=new_id("scat"),
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        artifact_id=semantic_artifact.id,
        columns_json=dumps_json(result.semantic_catalog),
    )
    db.add(catalog)
    evidence_records = []
    for item in result.evidence:
        evidence = Evidence(
            id=item["id"],
            project_id=project.id,
            evidence_type=item["evidence_type"],
            summary=item["summary"],
            strength=item["strength"],
            source_artifact_id=profile_artifact.id,
            metadata_json=dumps_json(item.get("metadata") or {}),
        )
        db.add(evidence)
        evidence_records.append(evidence)
    assumption_records = []
    for item in result.assumptions:
        assumption = Assumption(
            id=item["id"],
            project_id=project.id,
            topic=item["topic"],
            subject_type=item.get("subject_type"),
            subject_ref=item.get("subject_ref"),
            statement=item["statement"],
            status=item["status"],
            confidence=float(item["confidence"]),
            risk_level=item["risk_level"],
            fallback_policy=item["fallback_policy"],
            requires_user_confirmation=bool(item.get("requires_user_confirmation")),
            created_by_type="system",
        )
        db.add(assumption)
        assumption_records.append(assumption)
    for item in result.questions:
        question = Question(
            id=item["id"],
            project_id=project.id,
            question_set_id=item["question_set_id"],
            topic=item.get("topic"),
            question=item["question"],
            why_it_matters=item["why_it_matters"],
            default_assumption=item.get("default_assumption"),
            impact_if_wrong=item.get("impact_if_wrong"),
            choices_json=dumps_json(item.get("choices") or []),
            priority=int(item.get("priority") or 50),
            risk_level=item["risk_level"],
            value_of_answer=item["value_of_answer"],
            can_proceed_without_answer=bool(item["can_proceed_without_answer"]),
            fallback_policy=item["fallback_policy"],
            related_assumption_id=item.get("related_assumption_id"),
            blocks_next_phase=bool(item.get("blocks_next_phase")),
        )
        db.add(question)
    db.flush()
    if evidence_records:
        for assumption in assumption_records:
            db.add(
                AssumptionEvidenceLink(
                    id=new_id("ael"),
                    assumption_id=assumption.id,
                    evidence_id=evidence_records[0].id,
                    effect="supports",
                    weight=1.0,
                )
            )
    for artifact in [dataset_artifact, profile_artifact, understanding_artifact, semantic_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    return dataset


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
        "current_phase": project.current_phase,
        "status": project.status,
        "autonomy_mode": project.autonomy_mode,
        "created_by": project.created_by,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def dataset_to_dict(dataset: DatasetSnapshot) -> dict[str, Any]:
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
    if artifact.asset_type in {
        "notebook_html",
        "notebook_execution_html",
        "notebook_evidence_html",
        "eda_review_html",
    }:
        return 5_000_000
    if artifact.asset_type == "relational_catalog":
        return 500_000
    return 20_000


def artifact_preview_to_dict(artifact: Artifact, path: Path, limit_bytes: int = 20_000) -> dict[str, Any]:
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

    return re.sub(r'(<(?:img|source)\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', replace_src, html, flags=re.IGNORECASE)


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
            "runner": "CodexCliRunner",
            "network": "disabled_until_runner_policy_allows",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "source_of_truth": "original_english_artifact",
        },
    )


def mark_translation_job_succeeded(job: Job, result: TranslationResult) -> None:
    mark_job_succeeded(
        job,
        {
            "translated_artifact_id": result.translated_artifact.id,
            "translated_report_id": result.translated_report.id if result.translated_report else None,
            "codex_translation_contract_artifact_id": result.contract_artifact.id,
            "provider_status": result.provider_status,
            "translation_status": result.translation_status,
            "artifact_ids": [result.contract_artifact.id, result.translated_artifact.id],
        },
    )


def translation_result_to_dict(
    result: TranslationResult,
    *,
    source_type: str,
    source_id: str,
    source_artifact_id: str,
    source_locale: str,
    target_locale: str,
    job: Job,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_artifact_id": source_artifact_id,
        "source_locale": source_locale,
        "target_locale": target_locale,
        "provider_status": result.provider_status,
        "translation_status": result.translation_status,
        "artifact": artifact_to_dict(result.translated_artifact),
        "report": report_to_dict(result.translated_report) if result.translated_report else None,
        "preview": result.preview,
        "job": job_to_dict(job),
    }


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
