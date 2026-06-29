from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.api.deps import get_artifact_store, get_session
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
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
    VisualizationSpec,
    utc_now,
)
from tabular_harness.schemas import (
    AdaptiveStrategyBriefRead,
    AgentActivityRead,
    AgentChatCreate,
    AgentChatRead,
    AgentTaskPlanCreate,
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
    DecisionReportCurrentRead,
    EvaluationCandidateRead,
    EvaluationSpecRead,
    EvidenceCreate,
    IdeaRead,
    InsightRead,
    JobCreate,
    JobRead,
    KaggleSelectiveDownloadRequest,
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
    VisualizationSpecRead,
)
from tabular_harness.services.adaptive_strategy import (
    build_adaptive_strategy_brief,
    create_adaptive_strategy_brief,
)
from tabular_harness.services.agent_chat import handle_agent_chat_turn
from tabular_harness.services.agent_context import prepare_idea_agent_context_pack
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import review_agent_task_readiness
from tabular_harness.services.agent_task_results import list_agent_task_result_summaries
from tabular_harness.services.agent_tasks import run_idea_agent_task_stub
from tabular_harness.services.analysis_notebooks import (
    build_project_analysis_story,
    build_project_notebook_index,
    create_data_understanding_notebook,
    create_model_diagnostics_notebook,
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
    seed_default_assets,
)
from tabular_harness.services.assumption_review import build_assumption_review_queue
from tabular_harness.services.baseline import (
    create_baseline_strategy_plan,
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
    inspect_benchmark_local_files,
    list_benchmark_datasets,
    raw_benchmark_dataset,
    relative_path,
    resolve_benchmark_root,
    select_primary_file,
    store_benchmark_supporting_table_artifacts,
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
    build_portal_overview,
    create_portal_idea,
    list_portal_ideas,
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


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/config")
def app_config(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "app_display_name": str(settings.app_display_name),
        "architecture_name": "Tabular-first Prediction Meta-Harness",
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
def create_project(payload: ProjectCreate, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = Project(
        id=new_id("p"),
        name=payload.name,
        description=payload.description,
        task_type=payload.task_type,
        target_column=payload.target_column,
        current_phase="DRAFT",
    )
    db.add(project)
    db.flush()
    return project_to_dict(project)


@router.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    project = require_project(db, project_id)
    return project_to_dict(project)


@router.patch("/api/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    project = require_project(db, project_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(project, key, value)
    project.updated_at = utc_now()
    db.flush()
    return project_to_dict(project)


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
    recent_artifacts = db.scalars(
        select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc()).limit(8)
    ).all()
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
        "artifacts": count_rows(db, Artifact, project_id),
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
    job = create_job(
        db,
        job_type="agent_chat_turn",
        project_id=project_id,
        input_payload={"message": payload.message},
        policy={
            "network": "disabled",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "runner_execution": "not_started_by_chat_endpoint",
        },
    )
    try:
        mark_job_running(job)
        result = handle_agent_chat_turn(
            db,
            store=store,
            project=project,
            job=job,
            message=payload.message,
        )
        mark_job_succeeded(
            job,
            {
                "schema_version": result.response["schema_version"],
                "agent_chat_turn_artifact_id": result.artifact.id,
                "artifact_id": result.artifact.id,
                "artifact_ids": [result.artifact.id],
                "intent_type": result.response["intent"]["type"],
                "action_count": len(result.response["actions"]),
                "assistant_message": result.response["assistant_message"],
                "worker_events": result.response["worker_events"],
                "token_usage": result.response["token_usage"],
                "agent_task_contract_artifact_id": result.planned_agent_task.artifact.id
                if result.planned_agent_task
                else None,
            },
        )
        response = dict(result.response)
        response["job"] = job_to_dict(job)
        return response
    except ValueError as exc:
        mark_job_failed(job, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    return artifact_preview_to_dict(artifact, path)


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
) -> dict[str, Any]:
    project = require_project(db, project_id)
    job = create_job(
        db,
        job_type="generate_data_understanding_notebook",
        project_id=project_id,
        input_payload={"notebook_kind": "data_understanding"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "execution_mode": "generate_artifacts_only",
        },
    )
    try:
        mark_job_running(job)
        result = create_data_understanding_notebook(db, store=store, project=project)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.notebook["schema_version"],
                "notebook_kind": result.notebook["notebook_kind"],
                "analysis_notebook_artifact_id": result.notebook_artifact.id,
                "notebook_html_artifact_id": result.html_artifact.id,
                "notebook_run_manifest_artifact_id": result.manifest_artifact.id,
                "notebook_report_id": result.report.id,
                "notebook_report_artifact_id": result.report_artifact.id,
                "artifact_ids": result.artifact_ids,
                "execution_status": "generated_not_executed",
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
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
            "execution_mode": "safe_static_capture",
            "executes_notebook_code": False,
            "python_compile_only": True,
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


@router.post("/api/runs/{run_id}/analysis-notebook", response_model=JobRead)
def generate_run_analysis_notebook_endpoint(
    run_id: str,
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ExperimentRun not found")
    job = create_job(
        db,
        job_type="generate_model_diagnostics_notebook",
        project_id=run.project_id,
        input_payload={"run_id": run.id, "notebook_kind": "model_diagnostics"},
        policy={
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "execution_mode": "generate_artifacts_only",
        },
    )
    try:
        mark_job_running(job)
        result = create_model_diagnostics_notebook(db, store=store, run=run)
        mark_job_succeeded(
            job,
            {
                "schema_version": result.notebook["schema_version"],
                "notebook_kind": result.notebook["notebook_kind"],
                "run_id": run.id,
                "model_version_id": result.notebook.get("model_version_id"),
                "analysis_notebook_artifact_id": result.notebook_artifact.id,
                "notebook_html_artifact_id": result.html_artifact.id,
                "notebook_run_manifest_artifact_id": result.manifest_artifact.id,
                "notebook_report_id": result.report.id,
                "notebook_report_artifact_id": result.report_artifact.id,
                "visualization_id": result.visualization.id,
                "visualization_artifact_id": result.visualization_artifact.id,
                "artifact_ids": result.artifact_ids,
                "execution_status": "generated_not_executed",
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
    sorted_runs = sorted(runs, key=leaderboard_sort_key)
    return [
        {
            "rank": index + 1,
            "run_id": run.id,
            "status": run.status,
            "runner_type": run.runner_type,
            "primary_metric_name": loads_json(run.metrics_json, {}).get("primary_metric_name"),
            "primary_metric_value": loads_json(run.metrics_json, {}).get("primary_metric_value"),
            "metrics": loads_json(run.metrics_json, {}),
            "evaluation_spec_id": run.evaluation_spec_id,
            "split_manifest_id": run.split_manifest_id,
            "model_version_id": run.model_version_id,
        }
        for index, run in enumerate(sorted_runs)
    ]


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
def list_artifacts(project_id: str, db: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    require_project(db, project_id)
    artifacts = db.scalars(select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc())).all()
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


@router.get("/api/artifacts/{artifact_id}/preview", response_model=ArtifactPreviewRead)
def preview_artifact(artifact_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = artifact_primary_path(artifact)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    limit_bytes = 500_000 if artifact.asset_type == "relational_catalog" else 20_000
    return artifact_preview_to_dict(artifact, path, limit_bytes=limit_bytes)


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
def get_project_agent_activity(project_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    require_project(db, project_id)
    jobs = list(
        db.scalars(
            select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(30)
        ).all()
    )
    workers = [event for job in jobs for event in worker_events_from_job(job)]
    active_workers = [worker for worker in workers if worker.get("active")]
    return {
        "schema_version": "agent_activity.v1",
        "project_id": project_id,
        "generated_at": utc_now().isoformat(),
        "active_count": len(active_workers),
        "workers": workers[:20],
    }


@router.post("/api/jobs", response_model=JobRead)
def enqueue_job(payload: JobCreate, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
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
def cancel_job(job_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancel_job_service(job)
    return job_to_dict(job)


@router.post("/api/jobs/{job_id}/approve", response_model=JobRead)
def approve_job_endpoint(job_id: str, db: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    approve_job(job)
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
def run_worker_once(db: Annotated[Session, Depends(get_session)]) -> dict[str, Any] | None:
    worker = create_default_worker()
    job = worker.run_next_job(db)
    if job is None:
        return None
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
    db: Annotated[Session, Depends(get_session)],
    store: Annotated[LocalArtifactStore, Depends(get_artifact_store)],
) -> dict[str, Any]:
    asset = create_library_asset(db, store=store, payload=payload.model_dump())
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
        "source_asset_ids": loads_json(report.source_asset_ids_json, []),
        "status": report.status,
        "created_by_type": report.created_by_type,
        "created_at": report.created_at.isoformat(),
    }


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
    return {
        **base,
        "content_type": content_type,
        "preview_available": True,
        "preview": preview,
        "truncated": truncated,
        "reason": None,
    }


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
