from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Job, Project, utc_now

JOB_TYPES = {
    "profile_dataset",
    "infer_assumptions",
    "design_evaluation_candidates",
    "compare_evaluation_scenarios",
    "review_evaluation_approval",
    "build_split_manifest",
    "run_benchmark_fixture_smoke",
    "create_benchmark_collection_plan",
    "create_benchmark_evidence_pack",
    "create_relational_feature_plan",
    "build_relational_feature_recipe",
    "diagnose_relational_feature_scenarios",
    "upload_relational_schema_hint",
    "upload_data_bundle",
    "run_public_benchmark_workflow",
    "run_baseline",
    "train_model_candidates",
    "plan_baseline_strategy",
    "create_adaptive_strategy_brief",
    "save_guided_journey_snapshot",
    "save_autonomous_decision_brief",
    "compare_guided_journey_snapshots",
    "start_autonomous_loop",
    "continue_autonomous_session",
    "stop_autonomous_loop",
    "run_agent_task",
    "agent_chat_turn",
    "run_planned_agent_task_codex",
    "run_planned_agent_task_stub",
    "validate_model_package",
    "plan_agent_task",
    "plan_research",
    "create_research_source_pack",
    "run_research_source_pack_stub",
    "create_research_synthesis",
    "generate_research_brief",
    "generate_approach_candidates",
    "draft_project_report",
    "create_visualization_spec",
    "generate_insights",
    "generate_decision_dashboard",
    "generate_decision_report",
    "run_eda_review",
    "create_notebook_authoring_brief",
    "prepare_data_understanding_notebook_authoring",
    "prepare_model_diagnostics_notebook_authoring",
    "generate_data_understanding_notebook",
    "generate_model_diagnostics_notebook",
    "materialize_model_diagnostics_artifacts",
    "plan_notebook_execution",
    "capture_notebook_execution",
    "prepare_result_notebook_evidence",
    "prepare_agent_context",
    "prepare_planned_agent_workspace",
    "review_agent_task_readiness",
    "analyze_evaluation_diagnostics",
    "create_experiment_plan",
    "compare_experiments",
    "draft_run_report",
    "post_run_reading_workflow",
    "analyze_data_quality",
    "probe_kaggle_benchmark_access",
    "fetch_kaggle_competition_inventory",
    "download_kaggle_selected_files",
    "download_public_benchmark_archive",
    "import_benchmark_dataset",
    "create_benchmark_scenario_pack",
    "translate_tier3_content",
}

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
RUNNABLE_STATUSES = {"queued"}
APPROVAL_REQUIRED_JOB_TYPES = {"run_agent_task"}


def create_job(
    db: Session,
    *,
    job_type: str,
    project_id: str | None,
    input_payload: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    dependency_job_ids: list[str] | None = None,
    priority: int = 50,
    max_attempts: int = 1,
    approval_required: bool = False,
    run_after: datetime | None = None,
    created_by: str | None = None,
) -> Job:
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unsupported job type: {job_type}")
    effective_policy = policy or {}
    requires_approval = approval_required or job_requires_approval(job_type, effective_policy)
    job = Job(
        id=new_id("job"),
        project_id=project_id,
        job_type=job_type,
        status="approval_required" if requires_approval else "queued",
        priority=priority,
        max_attempts=max_attempts,
        input_json=dumps_json(input_payload or {}),
        output_json="{}",
        context_json=dumps_json(context or {}),
        policy_json=dumps_json(effective_policy),
        dependency_job_ids_json=dumps_json(dependency_job_ids or []),
        approval_required=requires_approval,
        run_after=run_after,
        created_by=created_by or project_owner_id(db, project_id),
    )
    db.add(job)
    db.flush()
    return job


def project_owner_id(db: Session, project_id: str | None) -> str:
    if not project_id:
        return "local-user"
    project = db.get(Project, project_id)
    return project.created_by if project is not None and project.created_by else "local-user"


def mark_job_running(job: Job) -> None:
    job.status = "running"
    job.attempt_count += 1
    job.error_message = None
    job.started_at = utc_now()
    job.updated_at = utc_now()


def mark_job_succeeded(job: Job, output: dict[str, Any] | None = None) -> None:
    job.status = "succeeded"
    job.output_json = dumps_json(output or {})
    job.locked_by = None
    job.locked_at = None
    job.ended_at = utc_now()
    job.updated_at = utc_now()


def mark_job_failed(job: Job, error_message: str, output: dict[str, Any] | None = None) -> None:
    job.status = "failed"
    job.error_message = error_message
    job.output_json = dumps_json(output or {})
    job.locked_by = None
    job.locked_at = None
    job.ended_at = utc_now()
    job.updated_at = utc_now()


def approve_job(job: Job, *, approved_by: str = "local-user") -> None:
    if job.status != "approval_required":
        return
    job.status = "queued"
    job.approved_by = approved_by
    job.approved_at = utc_now()
    job.updated_at = utc_now()


def cancel_job(job: Job, *, cancelled_by: str = "local-user") -> None:
    if job.status in TERMINAL_STATUSES:
        return
    job.status = "cancelled"
    job.cancelled_by = cancelled_by
    job.locked_by = None
    job.locked_at = None
    job.ended_at = utc_now()
    job.updated_at = utc_now()


def retry_job(job: Job) -> None:
    if job.status not in {"failed", "cancelled", "timed_out"}:
        raise ValueError("Only failed, cancelled, or timed_out jobs can be retried")
    if job.attempt_count >= job.max_attempts:
        raise ValueError("Job has reached max_attempts")
    job.status = "queued"
    job.error_message = None
    job.output_json = "{}"
    job.locked_by = None
    job.locked_at = None
    job.ended_at = None
    job.updated_at = utc_now()


def acquire_next_job(
    db: Session,
    *,
    worker_id: str,
    job_types: set[str] | None = None,
    project_id: str | None = None,
) -> Job | None:
    now = utc_now()
    stmt = select(Job).where(Job.status.in_(RUNNABLE_STATUSES)).order_by(Job.priority.desc(), Job.created_at)
    if job_types:
        stmt = stmt.where(Job.job_type.in_(job_types))
    if project_id is not None:
        stmt = stmt.where(Job.project_id == project_id)
    candidates = db.scalars(stmt.limit(50)).all()
    for job in candidates:
        run_after = job.run_after
        if run_after is not None and run_after.tzinfo is None:
            run_after = run_after.replace(tzinfo=timezone.utc)
        if run_after and run_after > now:
            continue
        if not dependencies_satisfied(db, job):
            continue
        job.locked_by = worker_id
        job.locked_at = now
        job.updated_at = now
        db.flush()
        return job
    return None


def dependencies_satisfied(db: Session, job: Job) -> bool:
    dependency_ids = loads_json(job.dependency_job_ids_json, [])
    if not dependency_ids:
        return True
    dependencies = db.scalars(select(Job).where(Job.id.in_([str(item) for item in dependency_ids]))).all()
    statuses = {dependency.id: dependency.status for dependency in dependencies}
    return all(statuses.get(str(job_id)) == "succeeded" for job_id in dependency_ids)


def job_requires_approval(job_type: str, policy: dict[str, Any]) -> bool:
    if job_type in APPROVAL_REQUIRED_JOB_TYPES:
        return True
    if policy.get("network") in {"restricted", "full"}:
        return True
    if policy.get("allow_external_network") is True:
        return True
    if policy.get("allow_production_write") is True:
        return True
    return False
