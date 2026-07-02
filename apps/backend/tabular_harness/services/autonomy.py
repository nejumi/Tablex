from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Answer,
    Artifact,
    Assumption,
    AssumptionEvidenceLink,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Insight,
    Job,
    Project,
    Question,
    ResearchBrief,
    SemanticCatalog,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.adaptive_strategy import create_adaptive_strategy_brief
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import (
    readiness_hard_blockers_for_runner,
    review_agent_task_readiness,
)
from tabular_harness.services.analysis_notebooks import create_data_understanding_notebook
from tabular_harness.services.approach import (
    create_decision_dashboard,
    create_research_plan,
    generate_approach_candidates,
    generate_research_brief,
    store_text_artifact,
)
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.baseline import (
    ModelDependencyRequiredError,
    create_baseline_strategy_plan,
    run_baseline,
    run_model_candidate,
)
from tabular_harness.services.data_quality import analyze_dataset_quality
from tabular_harness.services.diagnostics import analyze_run_diagnostics
from tabular_harness.services.eda_review import create_dataset_eda_review
from tabular_harness.services.evaluation import (
    approve_spec,
    create_default_evaluation_candidates,
    create_evaluation_approval_review,
    generate_split_manifest,
    load_profile_for_dataset,
    promote_candidate_to_spec,
    write_spec_artifact,
)
from tabular_harness.services.experiment_lifecycle import draft_run_report
from tabular_harness.services.jobs import create_job
from tabular_harness.services.planned_agent_execution import run_planned_agent_task_codex_cli
from tabular_harness.services.planned_agent_workspace import (
    prepare_workspace_from_contract_artifact,
)
from tabular_harness.services.reporting import generate_project_insights
from tabular_harness.services.result_notebook_evidence import prepare_result_notebook_evidence

RUNNER_MODE_HARNESS_ONLY = "harness_only"
RUNNER_MODE_CODEX_CLI = "codex_cli"
RUNNER_MODE_CODEX_IF_AVAILABLE = "codex_cli_if_available"
RUNNER_MODES = {RUNNER_MODE_HARNESS_ONLY, RUNNER_MODE_CODEX_CLI, RUNNER_MODE_CODEX_IF_AVAILABLE}
DEFAULT_SYNC_TRAINING_ROW_LIMIT = 50_000
DEFAULT_SYNC_SPLIT_ROW_LIMIT = 200_000
AUTONOMOUS_CONTINUATION_JOB_TYPE = "continue_autonomous_session"
ACTIVE_AUTONOMOUS_JOB_STATUSES = {"queued", "running", "approval_required"}
AUTONOMOUS_CHILD_JOB_TYPES = {
    "build_split_manifest",
    "run_baseline",
    "train_model_candidates",
    "run_planned_agent_task_codex",
}


@dataclass
class AutonomousStep:
    label: str
    status: str
    detail: str
    artifact_ids: list[str] = field(default_factory=list)
    entity_ids: dict[str, str | list[str]] = field(default_factory=dict)
    boundary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "artifact_ids": self.artifact_ids,
            "entity_ids": self.entity_ids,
        }
        if self.boundary:
            payload["boundary"] = self.boundary
        return payload


@dataclass
class AutonomousLoopState:
    project: Project
    job: Job
    steps: list[AutonomousStep] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    created_job_ids: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    interventions: list[dict[str, Any]] = field(default_factory=list)
    runner_result: dict[str, Any] | None = None

    def record(
        self,
        label: str,
        status: str,
        detail: str,
        *,
        artifact_ids: list[str] | None = None,
        entity_ids: dict[str, str | list[str]] | None = None,
        boundary: str | None = None,
    ) -> None:
        artifact_ids = artifact_ids or []
        self.steps.append(
            AutonomousStep(
                label=label,
                status=status,
                detail=detail,
                artifact_ids=artifact_ids,
                entity_ids=entity_ids or {},
                boundary=boundary,
            )
        )
        for artifact_id in artifact_ids:
            if artifact_id not in self.artifact_ids:
                self.artifact_ids.append(artifact_id)
        if boundary and boundary not in self.boundaries:
            self.boundaries.append(boundary)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def add_intervention(self, payload: dict[str, Any]) -> None:
        self.interventions.append(payload)


def run_autonomous_loop_tick(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    runner_mode: str = RUNNER_MODE_HARNESS_ONLY,
    autonomy_mode: str = "full_auto",
    locale: str | None = None,
    agent_model: str | None = None,
    utility_model: str | None = None,
) -> dict[str, Any]:
    if runner_mode not in RUNNER_MODES:
        raise ValueError(f"Unsupported autonomy runner mode: {runner_mode}")
    if autonomy_mode not in {"approval_based", "full_auto"}:
        raise ValueError(f"Unsupported autonomy mode: {autonomy_mode}")

    project.autonomy_mode = autonomy_mode
    project.current_phase = "AUTONOMOUS_LOOP"
    project.updated_at = utc_now()

    state = AutonomousLoopState(project=project, job=job)
    dataset = select_autonomy_dataset(db, project.id, target_column=project.target_column)
    approved_spec = latest_approved_spec(db, project.id)
    split = latest_split_for_spec(db, approved_spec.id) if approved_spec else None

    run_strategy_and_research(db, store=store, project=project, job=job, state=state, dataset=dataset, spec=approved_spec)

    if dataset is None:
        return finalize_autonomous_tick(
            db,
            store=store,
            state=state,
            status="waiting_for_data",
            next_human_boundary="Upload or import a dataset. Full Auto will continue from data understanding after data exists.",
            locale=locale,
            agent_model=agent_model,
            utility_model=utility_model,
        )

    run_data_understanding_stack(
        db,
        store=store,
        project=project,
        dataset=dataset,
        state=state,
        response_locale=locale,
    )
    if not project.target_column:
        question = get_or_create_target_question(
            db,
            project=project,
            blocks_next_phase=autonomy_mode != "full_auto",
        )
        state.add_intervention(
            target_intervention_payload(
                question=question,
                mode=autonomy_mode,
                continued=autonomy_mode == "full_auto",
            )
        )
        state.record(
            "target_definition",
            "delegated_to_codex" if autonomy_mode == "full_auto" else "needs_approval",
            (
                "Full Auto is handing target definition to Codex with the current profile, catalog, "
                "artifacts, and uncertainty context. The harness will not guess the target from names or statistics."
            )
            if autonomy_mode == "full_auto"
            else "Approval Based mode recorded the target-definition question before evaluation-sensitive work.",
            entity_ids={"question_id": question.id},
            boundary=(
                "Codex target-definition proposal is needed before evaluation and model training can become comparable."
                if autonomy_mode == "full_auto"
                else "Confirm, revise, or construct the prediction target."
            ),
        )
        run_runner_handoff(
            db,
            store=store,
            project=project,
            job=job,
            state=state,
            runner_mode=runner_mode,
            task_type="target_definition_review",
            queue_if_available=True,
        )
        if project.target_column:
            dataset = select_autonomy_dataset(db, project.id, target_column=project.target_column)
    if project.target_column:
        approved_spec, split = run_evaluation_stack(
            db,
            store=store,
            project=project,
            dataset=dataset,
            state=state,
            approved_spec=approved_spec,
            split=split,
            auto_approve=autonomy_mode == "full_auto",
        )
    else:
        approved_spec, split = None, None
        state.record(
            "evaluation_spec",
            "deferred",
            "Evaluation design is deferred because no usable provisional or confirmed target is available yet.",
            boundary="Target construction or target confirmation is required before EvaluationSpec adoption.",
        )
    run_idea_and_insight_stack(
        db,
        store=store,
        project=project,
        dataset=dataset,
        state=state,
        spec=approved_spec,
    )
    run_experiment_stack(
        db,
        store=store,
        project=project,
        state=state,
        spec=approved_spec,
        split=split,
        queue_training=True,
    )
    if project.target_column:
        run_runner_handoff(
            db,
            store=store,
            project=project,
            job=job,
            state=state,
            runner_mode=runner_mode,
            task_type="autonomous_session",
            queue_if_available=True,
        )

    next_boundary = next_boundary_for_state(project, approved_spec, split, state)
    return finalize_autonomous_tick(
        db,
        store=store,
        state=state,
        status="advanced",
        next_human_boundary=next_boundary,
        locale=locale,
        agent_model=agent_model,
        utility_model=utility_model,
    )


def queue_autonomous_session_continuation(
    db: Session,
    *,
    project: Project,
    reason: str,
    parent_job_id: str | None = None,
    exclude_job_id: str | None = None,
    runner_mode: str = RUNNER_MODE_CODEX_IF_AVAILABLE,
    locale: str | None = None,
    run_after_seconds: int = 10,
) -> Job | None:
    if project.autonomy_mode != "full_auto" or project.current_phase != "AUTONOMOUS_LOOP":
        return None
    existing = db.scalar(
        select(Job)
        .where(
            Job.project_id == project.id,
            Job.job_type == AUTONOMOUS_CONTINUATION_JOB_TYPE,
            Job.status.in_(ACTIVE_AUTONOMOUS_JOB_STATUSES),
        )
        .order_by(Job.created_at.desc())
    )
    if existing is not None and existing.id != exclude_job_id:
        return existing
    active_child_ids = active_autonomous_child_job_ids(db, project.id)
    summary = (
        "Resume the main Full Auto session after the current child work settles. "
        "This is a heartbeat for the long-running agent thread, not a micro-task replacement for Codex."
    )
    if active_child_ids:
        summary = (
            f"Wait for {len(active_child_ids)} active child worker(s), then resume the main Full Auto session. "
            "The child workers may train models, build splits, or run a broad Codex session."
        )
    return create_job(
        db,
        job_type=AUTONOMOUS_CONTINUATION_JOB_TYPE,
        project_id=project.id,
        input_payload={
            "runner_mode": runner_mode,
            "autonomy_mode": "full_auto",
            "locale": locale,
            "reason": reason,
            "parent_job_id": parent_job_id,
            "active_child_job_ids_at_schedule_time": active_child_ids,
        },
        context={
            "human_description": {
                "source": "autonomous_session_heartbeat",
                "title": "Continue the main Full Auto session",
                "summary": summary,
            }
        },
        policy={
            "network": "harness_only",
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "queued_by": "autonomous_session_heartbeat",
            "parent_job_id": parent_job_id,
        },
        priority=45,
        run_after=utc_now() + timedelta(seconds=max(run_after_seconds, 0)),
    )


def active_autonomous_child_job_ids(db: Session, project_id: str, *, exclude_job_id: str | None = None) -> list[str]:
    stmt = (
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.status.in_(ACTIVE_AUTONOMOUS_JOB_STATUSES),
            Job.job_type.in_(AUTONOMOUS_CHILD_JOB_TYPES),
        )
        .order_by(Job.priority.desc(), Job.created_at)
    )
    jobs = db.scalars(stmt).all()
    return [job.id for job in jobs if job.id != exclude_job_id]


def run_strategy_and_research(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    state: AutonomousLoopState,
    dataset: DatasetSnapshot | None,
    spec: EvaluationSpec | None,
) -> None:
    try:
        strategy = create_adaptive_strategy_brief(db, store=store, project=project, job=job)
        state.record(
            "strategy_brief",
            "created",
            "Created an adaptive strategy brief that keeps approach selection open-ended for Codex.",
            artifact_ids=strategy.artifact_ids,
            entity_ids={"report_id": strategy.report.id, "visualization_id": strategy.visualization.id},
        )
    except ValueError as exc:
        state.warn(f"Strategy brief skipped: {exc}")

    try:
        research_plan = create_research_plan(db, store=store, project=project, dataset=dataset, evaluation_spec=spec)
        state.record(
            "research_plan",
            "created",
            "Created a controlled ResearchPlan with Skill/library and source-policy context for the runner.",
            artifact_ids=[research_plan.artifact.id],
        )
    except ValueError as exc:
        state.warn(f"ResearchPlan skipped: {exc}")


def run_data_understanding_stack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
    state: AutonomousLoopState,
    response_locale: str | None = None,
) -> None:
    existing_quality = latest_project_artifact(db, project.id, "data_quality_gate")
    if existing_quality is not None:
        state.record(
            "data_quality",
            "reused",
            "Reused the latest data quality artifact instead of recomputing it during Agent loop start.",
            artifact_ids=[existing_quality.id],
        )
    else:
        try:
            quality = analyze_dataset_quality(db, store=store, project=project, dataset=dataset)
            state.record(
                "data_quality",
                "created",
                "Ran data quality analysis and materialized assumptions, questions, evidence, and an insight.",
                artifact_ids=quality.artifact_ids,
                entity_ids={
                    "insight_id": quality.insight_id,
                    "evidence_ids": quality.evidence_ids,
                    "assumption_ids": quality.assumption_ids,
                    "question_ids": quality.question_ids,
                },
            )
        except ValueError as exc:
            state.warn(f"Data quality analysis skipped: {exc}")

    existing_eda = latest_project_artifact(db, project.id, "eda_review_bundle")
    if existing_eda is not None:
        state.record(
            "eda_review",
            "reused",
            "Reused the latest EDA review bundle instead of recomputing it during Agent loop start.",
            artifact_ids=[existing_eda.id],
        )
    else:
        try:
            eda = create_dataset_eda_review(db, store=store, dataset=dataset)
            state.record(
                "eda_review",
                "created",
                "Created a deeper EDA review with findings, figures, HTML, report, evidence, and Codex follow-up prompts.",
                artifact_ids=eda.artifact_ids,
                entity_ids={"report_id": eda.report.id, "insight_id": eda.insight.id, "evidence_id": eda.evidence.id},
            )
        except ValueError as exc:
            state.warn(f"EDA review skipped: {exc}")

    existing_notebook = latest_project_artifact(db, project.id, "analysis_notebook")
    if existing_notebook is not None:
        state.record(
            "data_understanding_notebook",
            "reused",
            "Reused the latest analysis notebook artifact instead of regenerating it during Agent loop start.",
            artifact_ids=[existing_notebook.id],
        )
        return

    try:
        notebook = create_data_understanding_notebook(
            db,
            store=store,
            project=project,
            response_locale=response_locale,
        )
        state.record(
            "data_understanding_notebook",
            "created",
            "Generated a Data Understanding notebook artifact bundle for the in-product analysis story.",
            artifact_ids=notebook.artifact_ids,
        )
    except ValueError as exc:
        state.warn(f"Data Understanding notebook skipped: {exc}")


def get_or_create_target_question(
    db: Session,
    *,
    project: Project,
    blocks_next_phase: bool,
) -> Question:
    existing = db.scalar(
        select(Question)
        .where(Question.project_id == project.id, Question.topic == "target_definition", Question.status == "open")
        .order_by(Question.created_at.desc())
    )
    if existing is not None:
        existing.blocks_next_phase = blocks_next_phase
        existing.can_proceed_without_answer = not blocks_next_phase
        existing.fallback_policy = "block_until_answered" if blocks_next_phase else "infer_and_continue"
        return existing
    question = Question(
        id=new_id("q"),
        project_id=project.id,
        question_set_id=new_id("qs"),
        topic="target_definition",
        question="What prediction target, target construction, or prediction objective should Codex pursue for this project?",
        why_it_matters=(
            "The target defines row semantics, leakage boundaries, evaluation metrics, and what model performance means."
        ),
        default_assumption=(
            "Full Auto will ask Codex to infer or design the target from the current data understanding, "
            "semantic catalog, relational context, and user-provided project goal. The harness must not infer "
            "the target with column-name or profile heuristics."
        ),
        impact_if_wrong="Evaluation and model comparisons may optimize the wrong business question.",
        choices_json=dumps_json(["describe_target", "construct_target", "let_codex_infer", "approval_required"]),
        status="open",
        priority=95,
        risk_level="high",
        value_of_answer="high",
        can_proceed_without_answer=not blocks_next_phase,
        fallback_policy="block_until_answered" if blocks_next_phase else "infer_and_continue",
        blocks_next_phase=blocks_next_phase,
    )
    db.add(question)
    return question


def target_intervention_payload(
    *,
    question: Question,
    mode: str,
    continued: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "autonomy_intervention.v1",
        "kind": "target_definition",
        "mode": mode,
        "continued": continued,
        "question_id": question.id,
        "title": "Target definition is being handed to Codex",
        "message": (
            "Codex will reason over the current data understanding and propose the prediction target or target-construction plan. "
            "Tablex records this as an intervention point, but Full Auto keeps moving unless you catch it."
        ),
        "default_action": "continue_with_assumption" if continued else "wait_for_answer",
        "target_column": None,
        "dataset_snapshot_id": None,
        "source_ref": None,
        "risk_level": "high",
        "confidence": 0.0,
        "fallback_policy": "infer_and_continue" if continued else "block_until_answered",
    }


def append_assumption_review_intervention(db: Session, state: AutonomousLoopState) -> None:
    if state.project.autonomy_mode != "full_auto":
        return
    if state.interventions:
        return
    assumption = db.scalar(
        select(Assumption)
        .where(
            Assumption.project_id == state.project.id,
            Assumption.status.in_(["adopted", "inferred", "provisional", "open"]),
            (
                (Assumption.requires_user_confirmation.is_(True))
                | (Assumption.risk_level.in_(["high", "blocking", "deployment_blocking"]))
            ),
        )
        .order_by(Assumption.updated_at.desc(), Assumption.created_at.desc())
    )
    if assumption is None:
        return
    state.add_intervention(
        {
            "schema_version": "autonomy_intervention.v1",
            "kind": "assumption_review",
            "mode": state.project.autonomy_mode,
            "continued": True,
            "assumption_id": assumption.id,
            "title": "Review the assumption Full Auto is carrying",
            "message": assumption.statement,
            "default_action": "continue_with_assumption",
            "target_column": None,
            "dataset_snapshot_id": None,
            "source_ref": assumption.subject_ref,
            "risk_level": assumption.risk_level,
            "confidence": assumption.confidence,
            "fallback_policy": assumption.fallback_policy,
        }
    )


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def run_evaluation_stack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
    state: AutonomousLoopState,
    approved_spec: EvaluationSpec | None,
    split: SplitManifest | None,
    auto_approve: bool,
) -> tuple[EvaluationSpec | None, SplitManifest | None]:
    candidates = create_default_evaluation_candidates(db, store=store, project=project, dataset=dataset)
    state.record(
        "evaluation_candidates",
        "created" if candidates else "unchanged",
        f"Prepared {len(candidates)} evaluation candidate(s), including the primary candidate and alternatives.",
        entity_ids={"evaluation_candidate_ids": [candidate.id for candidate in candidates]},
    )

    if approved_spec is None and candidates:
        primary = primary_candidate(candidates)
        spec = promote_candidate_to_spec(db, store=store, candidate=primary)
        review = create_evaluation_approval_review(db, store=store, spec=spec, approval_intent=True)
        state.record(
            "evaluation_review",
            "created",
            "Reviewed the primary evaluation candidate before autonomous adoption.",
            artifact_ids=[review.artifact.id],
            entity_ids={"evaluation_spec_id": spec.id},
        )
        if not auto_approve:
            state.record(
                "evaluation_spec",
                "blocked",
                "Approval Based mode prepared the EvaluationSpec review but did not adopt it automatically.",
                entity_ids={"evaluation_spec_id": spec.id},
                boundary="Human approval is required before EvaluationSpec adoption and model training.",
            )
            return None, None
        if review.blocked:
            state.record(
                "evaluation_blockers",
                "preserved",
                "Full Auto preserved EvaluationSpec blockers as review evidence and continued with explicit assumptions.",
                artifact_ids=[review.artifact.id],
                entity_ids={"evaluation_spec_id": spec.id},
            )
        approve_spec(spec)
        approved_artifact = write_spec_artifact(db, store, spec)
        state.record(
            "evaluation_spec",
            "approved",
            "Adopted the primary EvaluationSpec for Full Auto and preserved the approval review as evidence.",
            artifact_ids=[approved_artifact.id],
            entity_ids={"evaluation_spec_id": spec.id},
        )
        approved_spec = spec

    if approved_spec is not None and split is None:
        if should_queue_split_generation(dataset):
            split_job = create_job(
                db,
                job_type="build_split_manifest",
                project_id=project.id,
                input_payload={"evaluation_spec_id": approved_spec.id},
                context={
                    "human_description": {
                        "source": "autonomous_loop_plan",
                        "title": "Build the SplitManifest",
                        "summary": (
                            "Generate the approved split for a large dataset outside the Start request, then continue "
                            "model training after the manifest exists."
                        ),
                    }
                },
                policy={
                    "network": "disabled",
                    "secret_access": "forbidden",
                    "connector_credentials": "not_materialized",
                    "queued_by": "autonomous_loop",
                    "evaluation_spec_id": approved_spec.id,
                },
                priority=72,
            )
            state.created_job_ids.append(split_job.id)
            state.record(
                "split_manifest",
                "queued",
                "Queued SplitManifest generation instead of blocking the Start request on a large dataset.",
                entity_ids={"job_id": split_job.id, "evaluation_spec_id": approved_spec.id},
            )
            return approved_spec, None
        split = generate_split_manifest(db, store=store, spec=approved_spec)
        state.record(
            "split_manifest",
            "created",
            "Generated a SplitManifest; later experiments must use this manifest instead of ad-hoc splits.",
            artifact_ids=[split.artifact_id],
            entity_ids={"split_manifest_id": split.id},
        )

    return approved_spec, split


def run_idea_and_insight_stack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
    state: AutonomousLoopState,
    spec: EvaluationSpec | None,
) -> None:
    try:
        brief = generate_research_brief(
            db,
            store=store,
            project=project,
            dataset=dataset,
            evaluation_spec=spec,
            question=None,
        )
        state.record(
            "research_brief",
            "created",
            "Synthesized an approach research brief from current evidence and controlled source policy.",
            artifact_ids=[brief.artifact.id],
            entity_ids={"research_brief_id": brief.brief.id},
        )
    except ValueError as exc:
        state.warn(f"Research brief skipped: {exc}")
        brief = None

    try:
        ideas = generate_approach_candidates(
            db,
            store=store,
            project=project,
            research_brief=brief.brief if brief else latest_research_brief(db, project.id),
            dataset=dataset,
            evaluation_spec=spec,
        )
        state.record(
            "approach_ideas",
            "created",
            "Created evidence-backed approach Ideas. They are advisory hypotheses, not a closed model menu.",
            artifact_ids=ideas.artifact_ids,
            entity_ids={"idea_ids": [idea.id for idea in ideas.ideas]},
        )
    except ValueError as exc:
        state.warn(f"Approach idea generation skipped: {exc}")

    try:
        insights = generate_project_insights(db, store=store, project=project)
        state.record(
            "insights",
            "created",
            "Updated the project insight set so new findings and improvement ideas are visible in Insight.",
            artifact_ids=[insights.artifact.id],
            entity_ids={"insight_ids": [insight.id for insight in insights.insights]},
        )
    except ValueError as exc:
        state.warn(f"Insight generation skipped: {exc}")


def run_experiment_stack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    state: AutonomousLoopState,
    spec: EvaluationSpec | None,
    split: SplitManifest | None,
    queue_training: bool = True,
) -> None:
    if spec is None or split is None:
        state.record(
            "experiment_loop",
            "deferred",
            "Training is deferred until an approved EvaluationSpec and SplitManifest exist.",
            boundary="Evaluation context is required before model training.",
        )
        return
    if not project.target_column:
        state.record(
            "experiment_loop",
            "deferred",
            "Training is deferred because the target is not selected or derived yet.",
            boundary="Target definition is required before model training.",
        )
        return

    try:
        strategy = create_baseline_strategy_plan(
            db,
            store=store,
            project=project,
            evaluation_spec=spec,
            split_manifest=split,
        )
        state.record(
            "baseline_strategy",
            "created",
            "Created a flexible baseline strategy plan from profile, evaluation, split, and library context.",
            artifact_ids=[strategy.artifact.id],
        )
    except ValueError as exc:
        state.warn(f"Baseline strategy skipped: {exc}")

    if queue_training or should_queue_experiment_training(db, project):
        active_training_ids = active_training_job_ids(db, project.id)
        if active_training_ids:
            state.record(
                "experiment_loop",
                "active",
                "Training is already active for this project; Full Auto will return to the main session after worker output lands.",
                entity_ids={"job_ids": active_training_ids, "evaluation_spec_id": spec.id, "split_manifest_id": split.id},
            )
            return
        existing_run_ids = experiment_run_ids_for_split(db, project=project, spec=spec, split=split)
        if existing_run_ids:
            state.record(
                "experiment_loop",
                "observed",
                "Comparable experiment runs already exist for the approved EvaluationSpec and SplitManifest.",
                entity_ids={
                    "experiment_run_ids": existing_run_ids[:8],
                    "evaluation_spec_id": spec.id,
                    "split_manifest_id": split.id,
                },
            )
            return
        queue_experiment_training_jobs(
            db,
            project=project,
            state=state,
            spec=spec,
            split=split,
        )
        return

    successful_runs: list[ExperimentRun] = []
    try:
        baseline = run_baseline(db, store=store, project=project, evaluation_spec=spec, split_manifest=split)
        successful_runs.append(baseline.run)
        state.record(
            "baseline_run",
            "succeeded",
            f"Ran the adaptive local baseline and registered run `{baseline.run.id}`.",
            artifact_ids=baseline.artifact_ids,
            entity_ids={"experiment_run_id": baseline.run.id},
        )
    except ValueError as exc:
        state.warn(f"Baseline run skipped: {exc}")

    for model_name in ["xgboost", "logistic_regression", "lightgbm"]:
        try:
            result = run_model_candidate(
                db,
                store=store,
                project=project,
                evaluation_spec=spec,
                split_manifest=split,
                model_candidate=model_name,
            )
        except ModelDependencyRequiredError as exc:
            state.record(
                f"model_candidate_{model_name}",
                "dependency_required",
                str(exc),
                boundary=f"Install approval required for `{exc.install_spec}` before this candidate can run.",
            )
            continue
        except ValueError as exc:
            state.warn(f"{model_name} candidate skipped: {exc}")
            continue
        successful_runs.append(result.run)
        state.record(
            f"model_candidate_{model_name}",
            "succeeded",
            f"Ran `{model_name}` under the approved split and registered run `{result.run.id}`.",
            artifact_ids=result.artifact_ids,
            entity_ids={"experiment_run_id": result.run.id},
        )

    for run in successful_runs[:3]:
        try:
            diagnostics = analyze_run_diagnostics(db, store=store, run=run)
            report = draft_run_report(db, store=store, run=run)
            state.record(
                f"run_diagnostics_{run.id}",
                "created",
                "Created diagnostics and a run report for a completed run.",
                artifact_ids=[*diagnostics.artifact_ids, report.artifact.id],
                entity_ids={"experiment_run_id": run.id, "report_id": report.report.id},
            )
        except ValueError as exc:
            state.warn(f"Run diagnostics skipped for {run.id}: {exc}")

    if successful_runs:
        try:
            evidence = prepare_result_notebook_evidence(db, store=store, project=project)
            state.record(
                "result_notebook_evidence",
                "created",
                "Prepared notebook evidence for the current top leaderboard run.",
                artifact_ids=evidence.artifact_ids,
            )
        except ValueError as exc:
            state.warn(f"Result notebook evidence skipped: {exc}")

    try:
        dashboard = create_decision_dashboard(db, store=store, project=project)
        state.record(
            "decision_dashboard",
            "created",
            "Updated the decision dashboard/report from the latest data, assumptions, evaluation, runs, and insights.",
            artifact_ids=dashboard.artifact_ids,
            entity_ids={"report_id": dashboard.report.id},
        )
    except ValueError as exc:
        state.warn(f"Decision dashboard skipped: {exc}")


def should_queue_experiment_training(db: Session, project: Project) -> bool:
    limit = sync_training_row_limit()
    if limit < 0:
        return False
    dataset = latest_dataset(db, project.id)
    if dataset is None:
        return False
    return bool(dataset.row_count and dataset.row_count > limit)


def should_queue_split_generation(dataset: DatasetSnapshot) -> bool:
    limit = sync_split_row_limit()
    if limit < 0:
        return False
    return bool(dataset.row_count and dataset.row_count > limit)


def sync_training_row_limit() -> int:
    raw = os.getenv("TABLEX_AUTONOMY_SYNC_TRAINING_ROW_LIMIT", str(DEFAULT_SYNC_TRAINING_ROW_LIMIT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_SYNC_TRAINING_ROW_LIMIT


def sync_split_row_limit() -> int:
    raw = os.getenv("TABLEX_AUTONOMY_SYNC_SPLIT_ROW_LIMIT", str(DEFAULT_SYNC_SPLIT_ROW_LIMIT)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_SYNC_SPLIT_ROW_LIMIT


def queue_experiment_training_jobs(
    db: Session,
    *,
    project: Project,
    state: AutonomousLoopState,
    spec: EvaluationSpec,
    split: SplitManifest,
) -> None:
    common_policy = {
        "network": "disabled",
        "secret_access": "forbidden",
        "connector_credentials": "not_materialized",
        "evaluation_spec_id": spec.id,
        "split_manifest_id": split.id,
        "queued_by": "autonomous_loop",
    }
    baseline_job = create_job(
        db,
        job_type="run_baseline",
        project_id=project.id,
        input_payload={"evaluation_spec_id": spec.id, "split_manifest_id": split.id},
        context={
            "human_description": {
                "source": "autonomous_loop_plan",
                "title": "Train the adaptive baseline",
                "summary": (
                    "Use the approved EvaluationSpec and SplitManifest to train the current adaptive tabular baseline, "
                    "then publish comparable run evidence for the Leaderboard."
                ),
            }
        },
        policy=common_policy,
        priority=70,
    )
    model_job = create_job(
        db,
        job_type="train_model_candidates",
        project_id=project.id,
        input_payload={
            "requested_models": ["xgboost", "logistic_regression", "lightgbm"],
            "normalized_models": ["xgboost", "logistic_regression", "lightgbm"],
            "unsupported_models": [],
            "evaluation_spec_id": spec.id,
            "split_manifest_id": split.id,
        },
        context={
            "human_description": {
                "source": "autonomous_loop_plan",
                "title": "Train candidate models",
                "summary": (
                    "Train the requested candidate family set for the same split and metric surface: "
                    "XGBoost, LogisticRegression, and LightGBM where dependencies are available."
                ),
            }
        },
        policy=common_policy,
        priority=65,
    )
    state.created_job_ids.extend([baseline_job.id, model_job.id])
    state.record(
        "experiment_loop",
        "queued",
        "Queued model training instead of blocking the Start request. Training Worker activity will track progress.",
        entity_ids={"job_ids": [baseline_job.id, model_job.id], "evaluation_spec_id": spec.id, "split_manifest_id": split.id},
    )
    state.record(
        "baseline_run",
        "queued",
        "Queued the adaptive local baseline under the approved EvaluationSpec and SplitManifest.",
        entity_ids={"job_id": baseline_job.id},
    )
    state.record(
        "model_candidates",
        "queued",
        "Queued XGBoost, LogisticRegression, and LightGBM candidate training for the local worker.",
        entity_ids={"job_id": model_job.id},
    )


def active_training_job_ids(db: Session, project_id: str) -> list[str]:
    jobs = db.scalars(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.status.in_(ACTIVE_AUTONOMOUS_JOB_STATUSES),
            Job.job_type.in_(["run_baseline", "train_model_candidates"]),
        )
        .order_by(Job.priority.desc(), Job.created_at)
    ).all()
    return [job.id for job in jobs]


def experiment_run_ids_for_split(
    db: Session,
    *,
    project: Project,
    spec: EvaluationSpec,
    split: SplitManifest,
) -> list[str]:
    runs = db.scalars(
        select(ExperimentRun)
        .where(
            ExperimentRun.project_id == project.id,
            ExperimentRun.evaluation_spec_id == spec.id,
            ExperimentRun.split_manifest_id == split.id,
            ExperimentRun.status == "succeeded",
        )
        .order_by(ExperimentRun.ended_at.desc())
    ).all()
    return [run.id for run in runs]


def run_runner_handoff(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    state: AutonomousLoopState,
    runner_mode: str,
    task_type: str | None = None,
    queue_if_available: bool = True,
) -> None:
    objective = autonomous_agent_objective(project)
    task_type = task_type or ("target_definition_review" if not project.target_column else "implement_prediction_approach")
    plan = plan_project_agent_task(
        db,
        store=store,
        project=project,
        job=job,
        objective=objective,
        task_type=task_type,
    )
    state.record(
        "agent_task_contract",
        "created",
        "Created an AgentTaskContract for Codex to reason from the current project evidence.",
        artifact_ids=[plan.artifact.id],
        entity_ids={"task_id": plan.contract["task_id"], "task_type": task_type},
    )

    try:
        workspace = prepare_workspace_from_contract_artifact(
            db,
            store=store,
            project=project,
            contract_artifact=plan.artifact,
            job=job,
        )
        state.record(
            "agent_workspace",
            "created",
            "Materialized the runner workspace with harness context, library assets, schemas, and safety policy.",
            artifact_ids=[workspace.artifact.id],
            entity_ids={"task_id": workspace.manifest["task_id"]},
        )
    except ValueError as exc:
        state.record(
            "agent_workspace",
            "blocked",
            f"Could not materialize runner workspace: {exc}",
            boundary="Runner workspace must be prepared before Codex execution.",
        )
        return

    try:
        readiness = review_agent_task_readiness(
            db,
            store=store,
            project=project,
            contract_artifact=plan.artifact,
            job=job,
        )
        hard_blockers = readiness_hard_blockers_for_runner(readiness.review, task_type=task_type)
        readiness_status = (
            "ready_with_constraints"
            if task_type == "autonomous_session" and readiness.review["blocker_count"] > 0 and not hard_blockers
            else readiness.review["status"]
        )
        state.record(
            "agent_readiness",
            readiness_status,
            (
                f"Reviewed runner readiness: {readiness.review['blocker_count']} blocker(s), "
                f"{readiness.review['warning_count']} warning(s)."
                if readiness_status != "ready_with_constraints"
                else (
                    f"Reviewed runner readiness: {readiness.review['blocker_count']} unresolved constraint(s), "
                    f"{readiness.review['warning_count']} warning(s). Full Auto will pass them to Codex instead of stopping."
                )
            ),
            artifact_ids=readiness.artifact_ids,
        )
        if hard_blockers:
            state.record(
                "codex_execution",
                "blocked",
                "Codex execution is blocked only by hard safety constraints; Full Auto preserved the contract and workspace.",
                boundary="Fix runner safety constraints before executing Codex.",
                entity_ids={"hard_blocker_check_ids": [str(item.get("check_id")) for item in hard_blockers]},
            )
            return
    except ValueError as exc:
        state.record(
            "agent_readiness",
            "blocked",
            f"Runner readiness review failed: {exc}",
            boundary="Runner readiness must pass before Codex execution.",
        )
        return

    if runner_mode == RUNNER_MODE_HARNESS_ONLY:
        state.record(
            "codex_execution",
            "armed",
            "Codex execution was armed but not launched because the request used harness_only runner mode.",
            boundary="Switch runner mode to codex_cli to execute the prepared workspace.",
        )
        return

    if runner_mode == RUNNER_MODE_CODEX_IF_AVAILABLE and shutil.which("codex") is None:
        state.record(
            "codex_execution",
            "blocked",
            "Codex CLI was not found on PATH; the workspace remains ready for a later runner.",
            boundary="Install or expose Codex CLI before runner execution.",
        )
        return

    if runner_mode == RUNNER_MODE_CODEX_IF_AVAILABLE and not queue_if_available:
        state.record(
            "codex_execution",
            "armed",
            "Prepared the Codex runner workspace without queuing a long-running worker job during Start.",
            artifact_ids=[plan.artifact.id],
            boundary="A later runner cycle can execute this workspace; Full Auto continued with harness-owned assumptions and evidence.",
        )
        return

    if runner_mode == RUNNER_MODE_CODEX_IF_AVAILABLE:
        active_codex_job = active_codex_session_job(db, project.id)
        if active_codex_job is not None:
            state.record(
                "codex_execution",
                "active",
                "A main Codex session is already queued or running; Full Auto will not fragment the thread with another runner job.",
                entity_ids={"job_id": active_codex_job.id, "agent_task_contract_artifact_id": plan.artifact.id},
            )
            return
        title = "Continue the main Codex session" if task_type == "autonomous_session" else "Run Codex on the prepared agent task"
        summary = (
            "Resume the long-running autonomous data-science thread in the controlled workspace, then return "
            "artifacts, findings, code/report outputs, and next-session recommendations to the harness."
            if task_type == "autonomous_session"
            else (
                "Execute the prepared AgentTaskContract in the controlled workspace, then return artifacts, "
                "findings, and next recommendations to the harness."
            )
        )
        codex_job = create_job(
            db,
            job_type="run_planned_agent_task_codex",
            project_id=project.id,
            input_payload={"agent_task_contract_artifact_id": plan.artifact.id},
            context={
                "human_description": {
                    "source": "agent_task_contract",
                    "title": title,
                    "summary": summary,
                },
                "agent_task_contract_artifact_id": plan.artifact.id,
            },
            policy={
                "network": "harness_only",
                "secret_access": "forbidden_to_task",
                "connector_credentials": "not_materialized",
                "runner": "codex_cli",
                "approval_mode": "autonomous_loop",
            },
            priority=75,
        )
        state.created_job_ids.append(codex_job.id)
        state.record(
            "codex_execution",
            "queued",
            "Queued Codex execution so the Start request can return immediately while Agent Activity tracks the runner.",
            entity_ids={"job_id": codex_job.id, "agent_task_contract_artifact_id": plan.artifact.id},
        )
        return

    try:
        result = run_planned_agent_task_codex_cli(
            db,
            store=store,
            project=project,
            contract_artifact=plan.artifact,
            job=job,
            timeout_seconds=1800,
        )
    except ValueError as exc:
        state.record(
            "codex_execution",
            "blocked",
            f"Codex execution did not run: {exc}",
            boundary="Resolve runner readiness or Codex execution blocker.",
        )
        return
    experiment_run_id = experiment_run_id_from_runner_result(result.experiment_ingestion)
    state.runner_result = {
        "status": result.agent_result.status,
        "final_message": result.agent_result.final_message,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "workspace_artifact_id": result.workspace_artifact_id,
        "readiness_status": result.readiness_status,
        "experiment_run_id": experiment_run_id,
    }
    if task_type == "target_definition_review":
        ingest_codex_target_definition_proposal(
            db,
            project=project,
            state=state,
            agent_result=result.agent_result,
            source_artifact_id=result.artifact_ids[0] if result.artifact_ids else None,
        )
    state.record(
        "codex_execution",
        result.agent_result.status,
        result.agent_result.final_message,
        artifact_ids=result.artifact_ids,
        entity_ids={
            "report_id": result.report_id,
            "evidence_id": result.evidence_id,
            "experiment_run_id": experiment_run_id or "",
        },
    )


def active_codex_session_job(db: Session, project_id: str) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.job_type == "run_planned_agent_task_codex",
            Job.status.in_(ACTIVE_AUTONOMOUS_JOB_STATUSES),
        )
        .order_by(Job.created_at.desc())
    )


def experiment_run_id_from_runner_result(experiment_ingestion: Any) -> str | None:
    experiment_run_id = getattr(experiment_ingestion, "experiment_run_id", None)
    if isinstance(experiment_run_id, str):
        return experiment_run_id
    run = getattr(experiment_ingestion, "run", None)
    run_id = getattr(run, "id", None)
    return run_id if isinstance(run_id, str) else None


def ingest_codex_target_definition_proposal(
    db: Session,
    *,
    project: Project,
    state: AutonomousLoopState,
    agent_result: Any,
    source_artifact_id: str | None,
) -> None:
    if agent_result.status != "succeeded":
        status = "gave_up" if agent_result.status == "gave_up" else "not_completed"
        reason = getattr(agent_result, "give_up_reason", None) or getattr(agent_result, "failure_reason", None)
        state.record(
            "target_definition_proposal",
            status,
            reason or "Codex did not complete the objective-definition review.",
            boundary=(
                "Codex gave up on objective definition; inspect required_next_inputs and provide missing evidence."
                if status == "gave_up"
                else "Rerun Codex objective-definition review before adopting EvaluationSpec."
            ),
        )
        return
    proposal = agent_result.outputs.get("target_definition_proposal") if isinstance(agent_result.outputs, dict) else None
    if not isinstance(proposal, dict):
        state.record(
            "target_definition_proposal",
            "not_completed",
            "Codex completed, but did not return `outputs.target_definition_proposal`.",
            boundary="Objective-definition review must return the proposal object before harness adoption.",
        )
        return
    recommended = proposal.get("recommended_target")
    if not isinstance(recommended, dict):
        state.record(
            "target_definition_proposal",
            "not_completed",
            "Codex objective proposal is missing `recommended_target`.",
            boundary="Objective-definition review must include a recommended objective before harness adoption.",
        )
        return
    target_kind = str(recommended.get("kind") or "")
    column_name = recommended.get("column_name")
    rationale = str(recommended.get("rationale") or proposal.get("rationale") or "Codex proposed this target from project evidence.")
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="codex_target_definition_proposal",
        summary=rationale[:500],
        strength=str(recommended.get("evidence_strength") or "medium"),
        source_artifact_id=source_artifact_id,
        metadata_json=dumps_json(proposal),
    )
    db.add(evidence)

    if target_kind != "existing_column" or not isinstance(column_name, str) or not column_name:
        state.record(
            "target_definition_proposal",
            "proposed",
            "Codex proposed a target that requires target construction before EvaluationSpec adoption.",
            artifact_ids=[source_artifact_id] if source_artifact_id else [],
            entity_ids={"evidence_id": evidence.id, "target_kind": target_kind or "unspecified"},
            boundary="Materialize or approve the Codex target-construction proposal before evaluation.",
        )
        return

    if column_name not in latest_semantic_column_names(db, project.id):
        state.record(
            "target_definition_proposal",
            "blocked",
            "Codex proposed an existing-column target, but the column was not found in the current SemanticCatalog.",
            artifact_ids=[source_artifact_id] if source_artifact_id else [],
            entity_ids={"evidence_id": evidence.id, "proposed_column": column_name},
            boundary="Regenerate semantic catalog or ask Codex to revise the target proposal.",
        )
        return

    project.target_column = column_name
    task_type = recommended.get("task_type") or proposal.get("task_type")
    if isinstance(task_type, str) and task_type:
        project.task_type = task_type
    project.updated_at = utc_now()
    assumption = Assumption(
        id=new_id("asm"),
        project_id=project.id,
        topic="target_definition",
        subject_type="column",
        subject_ref=column_name,
        statement=str(recommended.get("statement") or f"`{column_name}` is the Codex-proposed prediction target."),
        status="adopted",
        confidence=clamp_confidence(recommended.get("confidence")),
        risk_level=normalize_risk_level(recommended.get("risk_level")),
        fallback_policy="infer_and_continue",
        requires_user_confirmation=True,
        created_by_type="agent_runner",
        created_by="codex",
    )
    db.add(assumption)
    db.flush()
    db.add(
        AssumptionEvidenceLink(
            id=new_id("ael"),
            assumption_id=assumption.id,
            evidence_id=evidence.id,
            effect="supports",
            weight=0.9,
        )
    )
    for question in db.scalars(
        select(Question)
        .where(Question.project_id == project.id, Question.topic == "target_definition", Question.status == "open")
        .order_by(Question.priority.desc(), Question.created_at)
    ).all():
        question.status = "answered"
        db.add(
            Answer(
                id=new_id("ans"),
                question_id=question.id,
                answered_by="codex_agent",
                answer_value=column_name,
                answer_text=rationale,
            )
        )
    state.record(
        "target_definition_proposal",
        "adopted",
        "Accepted Codex's structured target-definition proposal and recorded it as an auditable assumption.",
        artifact_ids=[source_artifact_id] if source_artifact_id else [],
        entity_ids={"evidence_id": evidence.id, "assumption_id": assumption.id, "target_column": column_name},
    )


def latest_semantic_column_names(db: Session, project_id: str) -> set[str]:
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.project_id == project_id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        return set()
    columns = loads_json(catalog.columns_json, [])
    names: set[str] = set()
    for column in columns:
        if not isinstance(column, dict):
            continue
        raw_name = column.get("name") or column.get("column_name")
        if isinstance(raw_name, str):
            names.add(raw_name)
    return names


def clamp_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return 0.5


def normalize_risk_level(value: object) -> str:
    risk = str(value or "medium")
    return risk if risk in {"low", "medium", "high", "blocking", "deployment_blocking"} else "medium"


def finalize_autonomous_tick(
    db: Session,
    *,
    store: LocalArtifactStore,
    state: AutonomousLoopState,
    status: str,
    next_human_boundary: str,
    locale: str | None = None,
    agent_model: str | None = None,
    utility_model: str | None = None,
) -> dict[str, Any]:
    append_assumption_review_intervention(db, state)
    reflection_md = render_autonomous_reflection(state, status=status, next_human_boundary=next_human_boundary)
    reflection_artifact = store_text_artifact(
        db,
        store,
        project_id=state.project.id,
        asset_type="autonomous_reflection",
        name=f"autonomous_reflection_{state.job.id}",
        filename="autonomous_reflection.md",
        text=reflection_md,
        metadata={
            "project_id": state.project.id,
            "job_id": state.job.id,
            "status": status,
            "step_count": len(state.steps),
            "boundary_count": len(state.boundaries),
        },
    )
    state.record(
        "reflection",
        "created",
        "Wrote the autonomous loop reflection and next intervention boundary.",
        artifact_ids=[reflection_artifact.id],
    )
    insight = Insight(
        id=new_id("ins"),
        project_id=state.project.id,
        insight_type="autonomous_loop_reflection",
        title="Full Auto loop advanced",
        summary=autonomous_reflection_summary(state, status=status, next_human_boundary=next_human_boundary),
        severity="info" if status != "blocked" else "warning",
        confidence=0.78,
        status="open",
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": reflection_artifact.id}]),
        evidence_ids_json="[]",
        artifact_id=reflection_artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    create_lineage_edge(
        db,
        project_id=state.project.id,
        from_asset_type="job",
        from_asset_id=state.job.id,
        to_asset_type="artifact",
        to_asset_id=reflection_artifact.id,
        relation_type="produces",
    )
    db.flush()

    output = {
        "schema_version": "autonomous_loop_tick.v1",
        "project_id": state.project.id,
        "mode": state.project.autonomy_mode,
        "response_locale": locale or "en-US",
        "model_preferences": {
            "agent_model": agent_model,
            "utility_model": utility_model,
            "routing": {
                "agent_model": "autonomous planning, runner handoff, notebook/modeling strategy",
                "utility_model": "short status summaries, translation, and chat compression",
            },
        },
        "status": status,
        "assistant_message": render_assistant_message(state, status=status, next_human_boundary=next_human_boundary, locale=locale),
        "steps": [step.to_dict() for step in state.steps],
        "step_count": len(state.steps),
        "artifact_ids": state.artifact_ids,
        "created_job_ids": state.created_job_ids,
        "interventions": state.interventions,
        "boundaries": state.boundaries,
        "warnings": state.warnings,
        "runner_result": state.runner_result,
        "reflection_artifact_id": reflection_artifact.id,
        "insight_id": insight.id,
        "next_human_boundary": next_human_boundary,
        "worker_events": [worker_event_for_state(state, status=status, next_human_boundary=next_human_boundary)],
        "token_usage": token_usage_for_state(state),
    }
    return output


def autonomous_reflection_summary(
    state: AutonomousLoopState,
    *,
    status: str,
    next_human_boundary: str,
) -> str:
    completed_steps = [step for step in state.steps if step.status in {"adopted", "created", "completed", "approved", "succeeded"}]
    if completed_steps:
        labels = ", ".join(step.label.replace("_", " ") for step in completed_steps[:3])
        return (
            f"Full Auto completed {len(completed_steps)} step(s): {labels}. "
            f"Next boundary: {next_human_boundary}"
        )
    if state.boundaries:
        return f"Full Auto paused at {len(state.boundaries)} boundary item(s). Next boundary: {next_human_boundary}"
    return f"Full Auto recorded a reflection with status {status}. Next boundary: {next_human_boundary}"


def render_autonomous_reflection(
    state: AutonomousLoopState,
    *,
    status: str,
    next_human_boundary: str,
) -> str:
    lines = [
        "# Autonomous Loop Reflection",
        "",
        f"- Project: {state.project.name} ({state.project.id})",
        f"- Job: {state.job.id}",
        f"- Status: {status}",
        f"- Generated at: {utc_now().isoformat()}",
        "",
        "## What I Actually Did",
    ]
    lines.extend([f"- {step.label}: {step.status} - {step.detail}" for step in state.steps])
    lines.extend(
        [
            "",
            "## Current Hypotheses",
            "- The best next approach should be chosen from current evidence, not a fixed AutoML menu.",
            "- Evaluation, target definition, and split discipline are the hard boundaries; model family is not.",
            "- Any runner recommendation should emit an approach decision trace explaining accepted and rejected paths.",
            "",
            "## Human Intervention Boundary",
            f"- {next_human_boundary}",
        ]
    )
    if state.boundaries:
        lines.extend(["", "## Preserved Boundaries"])
        lines.extend([f"- {boundary}" for boundary in state.boundaries])
    if state.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {warning}" for warning in state.warnings])
    lines.extend(
        [
            "",
            "## Next Autonomous Move",
            "- Continue from the latest reflection, inspect newly created artifacts, revise assumptions, and choose the next action from evidence.",
            "- If a runner workspace is ready, Codex may execute, revise the plan, or request a narrower artifact before training.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_assistant_message(
    state: AutonomousLoopState,
    *,
    status: str,
    next_human_boundary: str,
    locale: str | None = None,
) -> str:
    blocked = [step for step in state.steps if step.status in {"blocked", "deferred", "dependency_required", "armed"}]
    mode_label = "Full Auto" if state.project.autonomy_mode == "full_auto" else "Approval Based"
    run_steps = [step for step in state.steps if step.label in {"baseline_run", "model_candidate_xgboost", "model_candidate_logistic_regression", "model_candidate_lightgbm"} and step.status == "succeeded"]
    evaluation_ready = any(step.label == "evaluation_spec" and step.status == "approved" for step in state.steps)
    split_ready = any(step.label == "split_manifest" and step.status == "created" for step in state.steps)
    codex_step = next((step for step in reversed(state.steps) if step.label == "codex_execution"), None)
    if locale and locale.lower().startswith("ja"):
        if status == "waiting_for_data":
            return (
                f"{mode_label}を起動しました。まだデータがないので、モデルや評価は走らせず、"
                "データが届いたらすぐ進めるための戦略・調査コンテキストだけを用意しました。"
                "CSV/Parquetをアップロードすると、データ理解から自律的に続けます。"
            )
        if state.project.target_column:
            lines = [f"{mode_label}を起動しました。データ理解、ターゲット定義、評価設計、実験の順に進めています。"]
            lines.append(f"現在のプロジェクト設定では `{state.project.target_column}` をターゲットとして扱っています。")
        else:
            lines = [f"{mode_label}を起動しました。データ理解を進め、ターゲット判断はCodex runnerに渡しました。"]
            lines.append("ハーネス側では列名ルールで代替せず、Codexの構造化提案を受け取ってから評価設計に進みます。")
        if evaluation_ready and split_ready:
            lines.append("評価設計とSplitManifestは準備済みです。以後のrunは同じ評価条件で比較できます。")
        elif evaluation_ready:
            lines.append("評価設計は採用済みです。SplitManifestの確認が次の実行境界です。")
        if run_steps:
            lines.append(f"モデル実験は {len(run_steps)} 件走りました。結果はLeaderboardで同じ指標・同じsplitの順位として見られます。")
        if codex_step and codex_step.status == "armed":
            lines.append("Codex runner用のworkspaceは準備しました。runner modeの都合で実行は保留していますが、ハーネス側の成果物は残っています。")
        elif codex_step and codex_step.status == "blocked":
            lines.append("Codex runner実行だけはreadinessまたはCLI環境で止まっています。データ理解・評価・ローカル実験は別に進めています。")
        if state.runner_result:
            lines.append(f"Runner結果: {state.runner_result.get('status')} - {state.runner_result.get('final_message')}")
        if blocked and not run_steps and not state.project.target_column:
            lines.append(f"必要な介入: {next_human_boundary}")
        else:
            lines.append(f"次に見るなら: {next_human_boundary}")
        return "\n".join(lines)
    if status == "waiting_for_data":
        return (
            f"{mode_label} started. There is no dataset yet, so I prepared the strategy and research context "
            "that can safely exist before data. Upload CSV/Parquet and I will continue from data understanding."
        )
    if state.project.target_column:
        lines = [f"{mode_label} started. I moved through data understanding, target definition, evaluation design, and experiment setup."]
        lines.append(f"The project is currently configured to use `{state.project.target_column}` as the target.")
    else:
        lines = [f"{mode_label} started. I advanced data understanding and handed target definition to the Codex runner."]
        lines.append("The harness did not substitute column-name rules; evaluation waits for a structured Codex proposal that the harness can validate and record.")
    if evaluation_ready and split_ready:
        lines.append("EvaluationSpec and SplitManifest are ready, so future runs are comparable.")
    elif evaluation_ready:
        lines.append("EvaluationSpec is adopted; SplitManifest is the next execution boundary.")
    if run_steps:
        lines.append(f"I ran {len(run_steps)} model experiment(s). Check Leaderboard for the comparable ranking.")
    if codex_step and codex_step.status == "armed":
        lines.append("The Codex runner workspace is prepared; execution is armed but not launched in the current runner mode.")
    elif codex_step and codex_step.status == "blocked":
        lines.append("Only Codex runner execution is blocked by readiness or CLI availability; harness-side analysis and local experiments still advanced.")
    if state.runner_result:
        lines.append(f"Runner result: {state.runner_result.get('status')} - {state.runner_result.get('final_message')}")
    if blocked and not run_steps and not state.project.target_column:
        lines.append(f"Human intervention needed: {next_human_boundary}")
    else:
        lines.append(f"Next useful surface: {next_human_boundary}")
    return "\n".join(lines)


def worker_event_for_state(
    state: AutonomousLoopState,
    *,
    status: str,
    next_human_boundary: str,
) -> dict[str, Any]:
    succeeded = sum(1 for step in state.steps if step.status in {"adopted", "created", "approved", "succeeded"})
    blocked = sum(1 for step in state.steps if step.status in {"blocked", "deferred", "dependency_required", "armed"})
    display_status = "succeeded" if status in {"advanced", "waiting_for_data"} else status
    return {
        "worker_id": "full-auto-loop",
        "display_name": "Full Auto Agent",
        "status": display_status,
        "headline": f"Advanced {succeeded} step(s); {blocked} boundary item(s).",
        "detail": next_human_boundary,
        "job_id": state.job.id,
        "project_id": state.project.id,
        "target_tab": "Home",
        "target_anchor": "agent-workspace",
        "created_at": state.job.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "active": False,
        "token_usage": token_usage_for_state(state),
    }


def token_usage_for_state(state: AutonomousLoopState) -> dict[str, Any]:
    base = max(80, len(state.steps) * 45)
    return {
        "source": "autonomous_loop_progress_estimate",
        "is_estimate": True,
        "series": [
            {"step": "plan", "tokens": base},
            {"step": "evidence", "tokens": base + len(state.artifact_ids) * 12},
            {"step": "runner", "tokens": base + (180 if state.runner_result else 60)},
            {"step": "reflection", "tokens": base + len(state.boundaries) * 20},
        ],
    }


def next_boundary_for_state(
    project: Project,
    spec: EvaluationSpec | None,
    split: SplitManifest | None,
    state: AutonomousLoopState,
) -> str:
    codex_step = next((step for step in reversed(state.steps) if step.label == "codex_execution"), None)
    if not project.target_column:
        if codex_step and codex_step.status in {"blocked", "armed"}:
            return codex_step.boundary or "Run the prepared Codex target-definition review workspace."
        return "Review the Codex target-definition proposal, or let Full Auto continue with the next target review pass."
    if spec is None:
        return "Review the proposed EvaluationSpec candidates because automatic approval was blocked."
    if split is None:
        return "Generate or inspect the SplitManifest before comparing model runs."
    if codex_step and codex_step.status == "blocked":
        return codex_step.boundary or "Launch the prepared Codex runner workspace when ready."
    return "Review the leaderboard and autonomous reflection, then let Full Auto continue the next improvement cycle."


def autonomous_agent_objective(project: Project) -> str:
    target = project.target_column or "not yet fixed; infer candidates and ask only high-value questions"
    return (
        f"Act as the autonomous data science engine for Tablex project `{project.name}`. "
        f"Target context: {target}. Inspect the harness-provided artifacts, assumptions, evaluation context, "
        "research/Skill hints, notebooks, and runner workspace. Choose the next project-specific approach from evidence. "
        "Do not treat harness suggestions as a fixed recipe: accept, modify, reject, or replace them with a better plan. "
        "Produce artifact-backed code, metrics, reports, visualizations, citations, and an approach decision trace. "
        "Respect EvaluationSpec and SplitManifest, do not read secrets or connector credentials, and record uncertainty as "
        "assumptions with fallback policies instead of stopping."
    )


def primary_candidate(candidates: list[EvaluationCandidate]) -> EvaluationCandidate:
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.status == "primary_candidate" or candidate.scenario_id == "primary"
        ),
        candidates[0],
    )


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def select_autonomy_dataset(db: Session, project_id: str, *, target_column: str | None) -> DatasetSnapshot | None:
    datasets = list(
        db.scalars(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project_id)
            .order_by(DatasetSnapshot.created_at.desc())
        ).all()
    )
    if not datasets:
        return None
    if target_column:
        matching_datasets: list[DatasetSnapshot] = []
        for dataset in datasets:
            profile = load_profile_for_dataset(db, dataset)
            columns = profile.get("columns")
            if isinstance(columns, list) and any(isinstance(column, dict) and column.get("name") == target_column for column in columns):
                matching_datasets.append(dataset)
        if matching_datasets:
            return max(matching_datasets, key=lambda item: ((item.column_count or 0), (item.row_count or 0), item.created_at))
    return datasets[0]


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
        select(ResearchBrief)
        .where(ResearchBrief.project_id == project_id)
        .order_by(ResearchBrief.created_at.desc())
    )


def first_completed_sentence(markdown: str) -> str:
    for line in markdown.splitlines():
        cleaned = line.strip().lstrip("- ").strip()
        if cleaned and not cleaned.startswith("#"):
            return cleaned[:500]
    return "Full Auto loop advanced and wrote an autonomous reflection."
