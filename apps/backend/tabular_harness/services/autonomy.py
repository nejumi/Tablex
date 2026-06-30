from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    ExperimentRun,
    Insight,
    Job,
    Project,
    ResearchBrief,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.adaptive_strategy import create_adaptive_strategy_brief
from tabular_harness.services.agent_task_planner import plan_project_agent_task
from tabular_harness.services.agent_task_readiness import review_agent_task_readiness
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
    promote_candidate_to_spec,
    write_spec_artifact,
)
from tabular_harness.services.experiment_lifecycle import draft_run_report
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
    dataset = latest_dataset(db, project.id)
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

    run_data_understanding_stack(db, store=store, project=project, dataset=dataset, state=state)
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
    )
    run_runner_handoff(
        db,
        store=store,
        project=project,
        job=job,
        state=state,
        runner_mode=runner_mode,
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
) -> None:
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

    try:
        notebook = create_data_understanding_notebook(db, store=store, project=project)
        state.record(
            "data_understanding_notebook",
            "created",
            "Generated a Data Understanding notebook artifact bundle for the in-product analysis story.",
            artifact_ids=notebook.artifact_ids,
        )
    except ValueError as exc:
        state.warn(f"Data Understanding notebook skipped: {exc}")


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
                "evaluation_spec",
                "blocked",
                "EvaluationSpec adoption is blocked by required questions or deployment-facing assumptions.",
                entity_ids={"evaluation_spec_id": spec.id},
                boundary="Evaluation adoption needs human review before training.",
            )
            return None, None
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


def run_runner_handoff(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    state: AutonomousLoopState,
    runner_mode: str,
) -> None:
    objective = autonomous_agent_objective(project)
    plan = plan_project_agent_task(
        db,
        store=store,
        project=project,
        job=job,
        objective=objective,
        task_type="implement_prediction_approach",
    )
    state.record(
        "agent_task_contract",
        "created",
        "Created an open-ended AgentTaskContract. Codex may accept, reject, revise, or replace suggested approaches.",
        artifact_ids=[plan.artifact.id],
        entity_ids={"task_id": plan.contract["task_id"]},
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
        state.record(
            "agent_readiness",
            readiness.review["status"],
            f"Reviewed runner readiness: {readiness.review['blocker_count']} blocker(s), {readiness.review['warning_count']} warning(s).",
            artifact_ids=readiness.artifact_ids,
        )
        if readiness.review["blocker_count"] > 0:
            state.record(
                "codex_execution",
                "blocked",
                "Codex execution is blocked by readiness checks; Full Auto still preserved the contract and workspace.",
                boundary="Resolve runner readiness blockers before executing Codex.",
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
    state.runner_result = {
        "status": result.agent_result.status,
        "final_message": result.agent_result.final_message,
        "report_id": result.report_id,
        "evidence_id": result.evidence_id,
        "workspace_artifact_id": result.workspace_artifact_id,
        "readiness_status": result.readiness_status,
        "experiment_run_id": result.experiment_ingestion.run.id if result.experiment_ingestion.run else None,
    }
    state.record(
        "codex_execution",
        result.agent_result.status,
        result.agent_result.final_message,
        artifact_ids=result.artifact_ids,
        entity_ids={
            "report_id": result.report_id,
            "evidence_id": result.evidence_id,
            "experiment_run_id": result.experiment_ingestion.run.id if result.experiment_ingestion.run else "",
        },
    )


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
        summary=first_completed_sentence(reflection_md),
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
    completed = [step for step in state.steps if step.status in {"created", "approved", "succeeded"}]
    blocked = [step for step in state.steps if step.status in {"blocked", "deferred", "dependency_required", "armed"}]
    mode_label = "Full Auto" if state.project.autonomy_mode == "full_auto" else "Approval Based"
    if locale and locale.lower().startswith("ja"):
        lines = [
            f"{mode_label}のAgent loopを開始し、今できる範囲まで進めました。完了した具体ステップは{len(completed)}件、保持したboundaryは{len(state.boundaries)}件です。reflection artifactも残しました。",
        ]
        if completed:
            lines.append("完了: " + "、".join(step.label for step in completed[:8]) + ("..." if len(completed) > 8 else ""))
        if blocked:
            lines.append("後で確認が必要: " + "、".join(f"{step.label} ({step.status})" for step in blocked[:5]))
        if state.runner_result:
            lines.append(f"Runner結果: {state.runner_result.get('status')} - {state.runner_result.get('final_message')}")
        lines.append(f"次の人間の確認点: {next_human_boundary}")
        if status == "waiting_for_data":
            lines.append("黙って止まったわけではありません。データ投入前に作れる戦略・調査コンテキストを作成しました。")
        return "\n".join(lines)
    lines = [
        f"{mode_label} started and advanced the agent loop. I completed {len(completed)} concrete step(s), preserved {len(state.boundaries)} boundary item(s), and wrote a reflection artifact.",
    ]
    if completed:
        lines.append("Done: " + ", ".join(step.label for step in completed[:8]) + ("..." if len(completed) > 8 else ""))
    if blocked:
        lines.append("Needs attention later: " + ", ".join(f"{step.label} ({step.status})" for step in blocked[:5]))
    if state.runner_result:
        lines.append(f"Runner result: {state.runner_result.get('status')} - {state.runner_result.get('final_message')}")
    lines.append(f"Next human boundary: {next_human_boundary}")
    if status == "waiting_for_data":
        lines.append("I did not stop silently; I created the strategy/research context that is possible before data exists.")
    return "\n".join(lines)


def worker_event_for_state(
    state: AutonomousLoopState,
    *,
    status: str,
    next_human_boundary: str,
) -> dict[str, Any]:
    succeeded = sum(1 for step in state.steps if step.status in {"created", "approved", "succeeded"})
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
    if not project.target_column:
        return "Confirm or derive the prediction target; until then model training remains blocked."
    if spec is None:
        return "Review the proposed EvaluationSpec candidates because automatic approval was blocked."
    if split is None:
        return "Generate or inspect the SplitManifest before comparing model runs."
    codex_step = next((step for step in reversed(state.steps) if step.label == "codex_execution"), None)
    if codex_step and codex_step.status in {"blocked", "armed"}:
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
