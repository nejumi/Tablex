from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings, get_settings
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Job,
    ModelVersion,
    Project,
    Question,
    ResearchBrief,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.adaptive_strategy import create_adaptive_strategy_brief
from tabular_harness.services.agent_chat import handle_agent_chat_turn
from tabular_harness.services.agent_context import prepare_idea_agent_context_pack
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import review_agent_task_readiness
from tabular_harness.services.agent_tasks import run_idea_agent_task_stub
from tabular_harness.services.analysis_notebooks import (
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
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    create_baseline_strategy_plan,
    normalize_model_candidate_name,
    run_baseline,
    run_model_candidate,
)
from tabular_harness.services.benchmarks import (
    benchmark_import_readiness,
    build_import_manifest,
    build_relational_catalog,
    create_benchmark_scenario_pack,
    default_benchmark_root,
    download_public_benchmark_archive,
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
from tabular_harness.worker.runner import JobHandler, SyncWorker

INITIAL_JOB_TYPES = tuple(sorted(JOB_TYPES))


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
    project.current_phase = "UNDERSTANDING_REVIEW"
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
    project.current_phase = "UNDERSTANDING_REVIEW"
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
                target_anchor="notebooks",
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
            "Author the project data-understanding marimo notebook from current artifacts and equipped Skills. "
            "Do not use harness-authored notebook prose."
        ),
        response_locale=response_locale,
    )
    return {
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
        "worker_events": [
            project_worker_event(
                job,
                project,
                status="succeeded",
                headline="Data-understanding notebook context prepared",
                detail="Registered the Codex authoring brief; the notebook itself remains Codex-authored.",
                target_tab="Assets",
                target_anchor="notebooks",
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


def capture_notebook_execution_handler(db: Session, job: Job, store: LocalArtifactStore) -> dict[str, Any]:
    notebook_artifact = notebook_artifact_for_job(db, job, "capture_notebook_execution")
    result = create_notebook_execution_capture(db, store=store, notebook_artifact=notebook_artifact)
    return {
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
        "worker_events": [
            notebook_worker_event(
                job,
                notebook_artifact,
                status="succeeded",
                headline="Notebook execution captured",
                detail="Registered the notebook execution manifest, report, preview HTML, and source snapshot.",
            )
        ],
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
    return {
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
        "worker_events": [
            run_worker_event(
                job,
                run,
                status="succeeded",
                headline="Model diagnostics notebook context prepared",
                detail="Registered the Codex authoring brief for this run's diagnostics notebook.",
                target_tab="Assets",
                target_anchor="notebooks",
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
    if artifact.asset_type != "analysis_notebook":
        raise ValueError(f"{job_type} requires an analysis_notebook artifact")
    if artifact.project_id is None:
        raise ValueError(f"{job_type} requires a project-scoped analysis_notebook artifact")
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
        "worker_id": "notebook-execution",
        "display_name": "Notebook Worker",
        "status": status,
        "headline": headline,
        "detail": detail,
        "job_id": job.id,
        "project_id": notebook_artifact.project_id,
        "target_tab": "Assets",
        "target_anchor": "notebooks",
        "created_at": job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": status in {"queued", "running"},
        "token_usage": {
            "source": "notebook_execution_estimate",
            "is_estimate": True,
            "series": [
                {"step": "validate notebook", "tokens": 40},
                {"step": "capture preview", "tokens": 120},
                {"step": "register artifacts", "tokens": 80},
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
                "target_tab": "Leaderboard" if successes else "Experiments",
                "target_anchor": "result-readout" if successes else None,
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
    handlers["download_public_benchmark_archive"] = download_public_benchmark_archive_handler
    handlers["run_public_benchmark_workflow"] = run_public_benchmark_workflow_handler
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
    handlers["capture_notebook_execution"] = capture_notebook_execution_handler
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
    handlers["prepare_model_diagnostics_notebook_authoring"] = prepare_model_diagnostics_notebook_authoring_handler
    handlers["plan_baseline_strategy"] = plan_baseline_strategy_handler
    handlers["run_baseline"] = run_baseline_handler
    handlers["build_split_manifest"] = build_split_manifest_handler
    handlers["train_model_candidates"] = train_model_candidates_handler
    handlers["prepare_planned_agent_workspace"] = prepare_planned_agent_workspace_handler
    handlers["review_agent_task_readiness"] = review_agent_task_readiness_handler
    handlers["run_planned_agent_task_stub"] = run_planned_agent_task_stub_handler
    handlers["run_planned_agent_task_codex"] = run_planned_agent_task_codex_handler
    handlers["continue_autonomous_session"] = continue_autonomous_session_handler
    handlers["agent_chat_turn"] = agent_chat_turn_handler
    return handlers


def create_default_worker(
    worker_id: str = "local-worker", store: LocalArtifactStore | None = None, include_stub_handlers: bool = False
) -> SyncWorker:
    artifact_store = store or LocalArtifactStore(get_settings().artifact_root)
    handlers = default_handlers() if include_stub_handlers else concrete_handlers()
    return SyncWorker(handlers=handlers, store=artifact_store, worker_id=worker_id)
