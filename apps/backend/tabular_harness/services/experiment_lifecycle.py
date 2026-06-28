from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Idea,
    Insight,
    Job,
    Project,
    Report,
    ResearchBrief,
    SplitManifest,
    utc_now,
)
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.reporting import best_leaderboard_run, persist_visualization_spec


@dataclass(frozen=True)
class ExperimentPlanResult:
    plan: dict[str, Any]
    artifact: Artifact
    evidence_id: str
    insight_id: str


@dataclass(frozen=True)
class ExperimentComparisonResult:
    comparison: dict[str, Any]
    artifact_ids: list[str]
    visualization_id: str | None
    report_id: str
    evidence_id: str
    insight_id: str


@dataclass(frozen=True)
class RunReportResult:
    report: Report
    artifact: Artifact
    evidence_id: str
    insight_id: str


LOWER_IS_BETTER = {"rmse", "mae", "mse", "log_loss", "mean_absolute_error", "root_mean_squared_error"}


def create_experiment_plan_for_idea(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    idea: Idea,
    job: Job | None = None,
) -> ExperimentPlanResult:
    dataset = db.get(DatasetSnapshot, idea.dataset_snapshot_id) if idea.dataset_snapshot_id else latest_dataset(db, project.id)
    evaluation_spec = (
        db.get(EvaluationSpec, idea.evaluation_spec_id) if idea.evaluation_spec_id else latest_approved_spec(db, project.id)
    )
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    research_brief = db.get(ResearchBrief, idea.research_brief_id) if idea.research_brief_id else latest_research_brief(db, project.id)
    context_pack = latest_artifact_for_idea(db, project.id, idea.id, "agent_context_pack")
    quality_gate = latest_project_artifact(db, project.id, "data_quality_gate")
    recent_diagnostics = latest_project_artifact(db, project.id, "evaluation_diagnostics")
    plan = build_experiment_plan(
        project=project,
        idea=idea,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        research_brief=research_brief,
        context_pack=context_pack,
        quality_gate=quality_gate,
        recent_diagnostics=recent_diagnostics,
        job=job,
    )
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="experiment_plan",
        name=f"experiment_plan_{idea.id}_{new_id('xpart')}",
        filename="experiment_plan.json",
        payload=plan,
        metadata={
            "project_id": project.id,
            "idea_id": idea.id,
            "plan_id": plan["id"],
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
            "job_id": job.id if job else None,
        },
    )
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="experiment_plan",
        summary=experiment_plan_summary(plan),
        strength="medium",
        source_artifact_id=artifact.id,
        metadata_json=dumps_json({"idea_id": idea.id, "plan_id": plan["id"], "job_id": job.id if job else None}),
    )
    db.add(evidence)
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="experiment_plan",
        title=f"Experiment plan ready: {idea.title}",
        summary=evidence.summary,
        severity="warning" if plan["readiness"]["blocking_items"] else "info",
        confidence=0.76,
        status="open",
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "idea", "asset_id": idea.id},
                *(
                    [{"asset_type": "evaluation_spec", "asset_id": evaluation_spec.id}]
                    if evaluation_spec is not None
                    else []
                ),
                *(
                    [{"asset_type": "split_manifest", "asset_id": split_manifest.id}]
                    if split_manifest is not None
                    else []
                ),
            ]
        ),
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    idea.status = "experiment_plan_ready"
    idea.updated_at = utc_now()
    db.flush()

    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="idea",
        from_asset_id=idea.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="plans",
    )
    for source_type, source_id in plan_source_edges(
        research_brief=research_brief,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        context_pack=context_pack,
        quality_gate=quality_gate,
        recent_diagnostics=recent_diagnostics,
        job=job,
    ):
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type=source_type,
            from_asset_id=source_id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="insight",
        from_asset_id=insight.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    return ExperimentPlanResult(plan=plan, artifact=artifact, evidence_id=evidence.id, insight_id=insight.id)


def compare_project_experiments(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> ExperimentComparisonResult:
    runs = list(
        db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id).order_by(ExperimentRun.started_at.desc())).all()
    )
    comparison = build_experiment_comparison(db, project=project, runs=runs)
    comparison_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="experiment_comparison",
        name=f"experiment_comparison_{new_id('xcmpart')}",
        filename="experiment_comparison.json",
        payload=comparison,
        metadata={
            "project_id": project.id,
            "best_run_id": comparison["decision"]["best_run_id"],
            "run_count": len(comparison["runs"]),
        },
    )
    report_md = render_experiment_comparison_report(project, comparison)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="experiment_comparison_report",
        name=f"experiment_comparison_report_{new_id('xcmprpt')}",
        filename="experiment_comparison.md",
        text=report_md,
        metadata={"project_id": project.id, "comparison_artifact_id": comparison_artifact.id},
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="experiment_comparison",
        title=f"{project.name} Experiment Comparison",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [{"asset_type": "experiment_run", "asset_id": row["run_id"]} for row in comparison["runs"][:12]]
        ),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_id: str | None = None
    visualization_artifact: Artifact | None = None
    if comparison["runs"]:
        visualization_spec = build_comparison_visualization_spec(comparison)
        visualization, visualization_artifact = persist_visualization_spec(
            db,
            store=store,
            project=project,
            spec=visualization_spec,
            source_artifact_id=comparison_artifact.id,
        )
        visualization_id = visualization.id
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="experiment_comparison",
        summary=comparison["decision"]["recommendation"],
        strength="medium" if comparison["runs"] else "weak",
        source_artifact_id=comparison_artifact.id,
        metadata_json=dumps_json({"best_run_id": comparison["decision"]["best_run_id"], "run_count": len(comparison["runs"])}),
    )
    db.add(evidence)
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="experiment_comparison",
        title="Experiment comparison ready",
        summary=evidence.summary,
        severity="info" if comparison["decision"]["best_run_id"] else "warning",
        confidence=0.78 if comparison["decision"]["best_run_id"] else 0.56,
        status="open",
        source_asset_ids_json=report.source_asset_ids_json,
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=comparison_artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    db.flush()

    artifact_ids = [comparison_artifact.id, report_artifact.id]
    if visualization_artifact is not None:
        artifact_ids.append(visualization_artifact.id)
    for run_row in comparison["runs"]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=str(run_row["run_id"]),
            to_asset_type="artifact",
            to_asset_id=comparison_artifact.id,
            relation_type="compared_in",
        )
    derived_artifacts = [report_artifact]
    if visualization_artifact is not None:
        derived_artifacts.append(visualization_artifact)
    for artifact in derived_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=comparison_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="materializes",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="insight",
        from_asset_id=insight.id,
        to_asset_type="artifact",
        to_asset_id=comparison_artifact.id,
        relation_type="materializes",
    )
    return ExperimentComparisonResult(
        comparison=comparison,
        artifact_ids=artifact_ids,
        visualization_id=visualization_id,
        report_id=report.id,
        evidence_id=evidence.id,
        insight_id=insight.id,
    )


def draft_run_report(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> RunReportResult:
    project = db.get(Project, run.project_id)
    if project is None:
        raise ValueError("Project not found")
    diagnostics_artifact = latest_diagnostics_for_run(db, run.project_id, run.id)
    diagnostics = load_artifact_json(diagnostics_artifact)
    plan_artifact = latest_artifact_for_idea(db, run.project_id, run.idea_id, "experiment_plan") if run.idea_id else None
    run_report = build_run_report_payload(
        project=project,
        run=run,
        diagnostics=diagnostics,
        diagnostics_artifact=diagnostics_artifact,
        plan_artifact=plan_artifact,
    )
    report_md = render_run_report(project=project, run=run, payload=run_report)
    artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="run_report",
        name=f"run_report_{run.id}_{new_id('runrpt')}",
        filename="run_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "run_id": run.id,
            "diagnostics_artifact_id": diagnostics_artifact.id if diagnostics_artifact else None,
            "plan_artifact_id": plan_artifact.id if plan_artifact else None,
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="run_report",
        title=f"Run Report: {run.id}",
        summary=first_sentence(report_md),
        artifact_id=artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "experiment_run", "asset_id": run.id},
                *(
                    [{"asset_type": "artifact", "asset_id": diagnostics_artifact.id}]
                    if diagnostics_artifact is not None
                    else []
                ),
                *([{"asset_type": "artifact", "asset_id": plan_artifact.id}] if plan_artifact is not None else []),
            ]
        ),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="run_report",
        summary=run_report["summary"],
        strength="medium",
        source_artifact_id=artifact.id,
        source_run_id=run.id,
        metadata_json=dumps_json({"run_id": run.id, "report_type": "run_report"}),
    )
    db.add(evidence)
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="run_report",
        title=f"Run report drafted for {run.id}",
        summary=run_report["summary"],
        severity=run_report["severity"],
        confidence=0.75,
        status="open",
        source_asset_ids_json=report.source_asset_ids_json,
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="experiment_run",
        from_asset_id=run.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    if diagnostics_artifact:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=diagnostics_artifact.id,
            to_asset_type="report",
            to_asset_id=report.id,
            relation_type="informs",
        )
    if plan_artifact:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=plan_artifact.id,
            to_asset_type="report",
            to_asset_id=report.id,
            relation_type="informs",
        )
    return RunReportResult(report=report, artifact=artifact, evidence_id=evidence.id, insight_id=insight.id)


def build_experiment_plan(
    *,
    project: Project,
    idea: Idea,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    research_brief: ResearchBrief | None,
    context_pack: Artifact | None,
    quality_gate: Artifact | None,
    recent_diagnostics: Artifact | None,
    job: Job | None,
) -> dict[str, Any]:
    feature_strategy = loads_json(idea.feature_strategy_json, {})
    modeling_strategy = loads_json(idea.modeling_strategy_json, {})
    contract = loads_json(idea.agent_task_contract_json, {})
    blocking_items = []
    if dataset is None:
        blocking_items.append("DatasetSnapshot is missing.")
    if evaluation_spec is None:
        blocking_items.append("Approved EvaluationSpec is missing.")
    if split_manifest is None:
        blocking_items.append("SplitManifest is missing.")
    if not project.target_column:
        blocking_items.append("Target column is not set.")
    return {
        "schema_version": "experiment_plan.v1",
        "id": new_id("xplan"),
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "idea": {
            "id": idea.id,
            "title": idea.title,
            "approach_type": idea.approach_type,
            "hypothesis": idea.hypothesis,
            "risk_level": idea.risk_level,
            "confidence": idea.confidence,
        },
        "readiness": {
            "status": "ready_for_runner" if not blocking_items else "needs_inputs",
            "blocking_items": blocking_items,
            "non_blocking_warnings": plan_warnings(idea, recent_diagnostics),
        },
        "research_governance": {
            "research_brief_id": research_brief.id if research_brief else None,
            "source_policy": "Project artifacts and locked library assets first; controlled web/literature research only when runner policy allows it.",
            "citation_requirement": "External claims must return source metadata and become Evidence or source-summary artifacts.",
            "sources": loads_json(research_brief.sources_json, []) if research_brief else [],
            "key_findings": loads_json(research_brief.key_findings_json, []) if research_brief else [],
        },
        "evaluation_lock": evaluation_lock_payload(evaluation_spec, split_manifest),
        "approach_selection": {
            "selection_policy": "Runner may choose implementation details after inspecting evidence, but must preserve evaluation and safety contracts.",
            "feature_strategy": feature_strategy,
            "modeling_strategy": modeling_strategy,
            "scenario_comparisons": scenario_comparisons_for_idea(idea, feature_strategy, modeling_strategy),
            "acceptance_criteria": acceptance_criteria(evaluation_spec),
        },
        "runner_contract": {
            "agent_task_contract": contract,
            "context_pack_artifact_id": context_pack.id if context_pack else None,
            "quality_gate_artifact_id": quality_gate.id if quality_gate else None,
            "workspace_policy": {
                "secret_access": "forbidden",
                "connector_credentials": "never passed to runner",
                "production_write": "forbidden",
                "split_manifest_required": True,
            },
            "job_id": job.id if job else None,
        },
        "expected_artifacts": [
            "agent_result",
            "feature_recipe",
            "experiment_metrics",
            "prediction_output",
            "evaluation_diagnostics",
            "run_report",
            "visualization_spec",
        ],
        "review_questions": review_questions_for_plan(project, idea, evaluation_spec, split_manifest),
        "next_steps": [
            "Prepare or refresh AgentContextPack if the plan references stale artifacts.",
            "Run the selected AgentRunner under approval policy.",
            "Persist prediction outputs, metrics, diagnostics, and run report before comparing with other runs.",
        ],
        "created_by_type": "system",
    }


def build_experiment_comparison(db: Session, *, project: Project, runs: list[ExperimentRun]) -> dict[str, Any]:
    succeeded = [run for run in runs if run.status == "succeeded"]
    best_run = best_leaderboard_run(succeeded)
    best_metric = primary_metric(best_run) if best_run else None
    rows = []
    for rank, run in enumerate(sorted(succeeded, key=run_sort_key), start=1):
        metric = primary_metric(run)
        diagnostics_artifact = latest_diagnostics_for_run(db, project.id, run.id)
        diagnostics = load_artifact_json(diagnostics_artifact)
        rows.append(
            {
                "rank": rank,
                "run_id": run.id,
                "runner_type": run.runner_type,
                "idea_id": run.idea_id,
                "model_version_id": run.model_version_id,
                "evaluation_spec_id": run.evaluation_spec_id,
                "split_manifest_id": run.split_manifest_id,
                "primary_metric_name": metric["name"],
                "primary_metric_value": metric["value"],
                "delta_from_best": metric_delta(metric, best_metric),
                "diagnostics_artifact_id": diagnostics_artifact.id if diagnostics_artifact else None,
                "diagnostics_summary": compact_diagnostics_summary(diagnostics),
                "status": run.status,
            }
        )
    return {
        "schema_version": "experiment_comparison.v1",
        "project_id": project.id,
        "runs": rows,
        "decision": {
            "best_run_id": best_run.id if best_run else None,
            "recommendation": comparison_recommendation(rows),
            "deployment_blockers": comparison_blockers(rows),
        },
        "governance": {
            "evaluation_owned_by_harness": True,
            "external_tracker_dependency": False,
            "requires_diagnostics_for_decision": True,
        },
    }


def build_run_report_payload(
    *,
    project: Project,
    run: ExperimentRun,
    diagnostics: dict[str, Any],
    diagnostics_artifact: Artifact | None,
    plan_artifact: Artifact | None,
) -> dict[str, Any]:
    metrics = loads_json(run.metrics_json, {})
    summary = (
        f"Run {run.id} completed with {metrics.get('primary_metric_name', 'metric')}="
        f"{metrics.get('primary_metric_value', '-')}; diagnostics are "
        f"{'available' if diagnostics else 'not yet available'}."
    )
    severity = "warning" if not diagnostics_artifact else "info"
    sanity = diagnostics.get("sanity_checks", {}) if diagnostics else {}
    if sanity and (
        not sanity.get("prediction_count_matches_split", True)
        or not sanity.get("all_predictions_joined_to_valid_rows", True)
    ):
        severity = "warning"
    return {
        "schema_version": "run_report.v1",
        "project_id": project.id,
        "run_id": run.id,
        "summary": summary,
        "severity": severity,
        "metrics": metrics,
        "diagnostics_artifact_id": diagnostics_artifact.id if diagnostics_artifact else None,
        "plan_artifact_id": plan_artifact.id if plan_artifact else None,
        "diagnostics_summary": compact_diagnostics_summary(diagnostics),
        "recommended_next_actions": run_report_next_actions(run, diagnostics),
    }


def render_run_report(*, project: Project, run: ExperimentRun, payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    lines = [
        "# Run Report",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Run: {run.id}",
        f"- Runner: {run.runner_type}",
        f"- Status: {run.status}",
        f"- EvaluationSpec: {run.evaluation_spec_id or '-'}",
        f"- SplitManifest: {run.split_manifest_id or '-'}",
        f"- ModelVersion: {run.model_version_id or '-'}",
        f"- Primary metric: {metrics.get('primary_metric_name', '-')}={metrics.get('primary_metric_value', '-')}",
        "",
        "## Summary",
        "",
        payload["summary"],
        "",
        "## Diagnostics",
        "",
    ]
    diagnostics = payload["diagnostics_summary"]
    if diagnostics:
        for key, value in diagnostics.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Diagnostics have not been generated for this run yet.")
    lines.extend(["", "## Recommended Next Actions", ""])
    lines.extend([f"- {item}" for item in payload["recommended_next_actions"]])
    return "\n".join(lines).strip() + "\n"


def render_experiment_comparison_report(project: Project, comparison: dict[str, Any]) -> str:
    lines = [
        "# Experiment Comparison",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Best run: {comparison['decision']['best_run_id'] or '-'}",
        "",
        "## Recommendation",
        "",
        comparison["decision"]["recommendation"],
        "",
        "## Runs",
        "",
    ]
    if comparison["runs"]:
        for row in comparison["runs"]:
            lines.append(
                f"- #{row['rank']} {row['run_id']}: {row['primary_metric_name']}={row['primary_metric_value']} "
                f"delta={row['delta_from_best']} diagnostics={row['diagnostics_artifact_id'] or '-'}"
            )
    else:
        lines.append("- No successful runs are available.")
    lines.extend(["", "## Deployment Blockers", ""])
    blockers = comparison["decision"]["deployment_blockers"]
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- No comparison-level blocker recorded."])
    return "\n".join(lines).strip() + "\n"


def build_comparison_visualization_spec(comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Experiment Comparison",
        "chart_type": "experiment_comparison_bar",
        "data": comparison["runs"],
        "encoding": {
            "x": "run_id",
            "y": "primary_metric_value",
            "color": "runner_type",
            "tooltip": ["rank", "run_id", "primary_metric_name", "delta_from_best", "diagnostics_artifact_id"],
        },
        "empty_state": "Run experiments before comparing them.",
    }


def evaluation_lock_payload(
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> dict[str, Any]:
    if evaluation_spec is None:
        return {"status": "missing", "evaluation_spec_id": None, "split_manifest_id": None}
    return {
        "status": "ready" if split_manifest else "missing_split_manifest",
        "evaluation_spec_id": evaluation_spec.id,
        "split_type": evaluation_spec.split_type,
        "primary_metric": evaluation_spec.primary_metric,
        "secondary_metrics": loads_json(evaluation_spec.secondary_metrics_json, []),
        "excluded_columns": loads_json(evaluation_spec.excluded_columns_json, []),
        "time_column": evaluation_spec.time_column,
        "group_column": evaluation_spec.group_column,
        "stratify_column": evaluation_spec.stratify_column,
        "split_manifest_id": split_manifest.id if split_manifest else None,
        "split_summary": loads_json(split_manifest.summary_json, {}) if split_manifest else {},
        "destructive_changes_allowed": False,
    }


def scenario_comparisons_for_idea(
    idea: Idea,
    feature_strategy: dict[str, Any],
    modeling_strategy: dict[str, Any],
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = [
        {
            "scenario_id": "sanity_floor",
            "purpose": "Verify the task beats a simple non-informative or linear floor before deeper modeling.",
            "required": True,
        },
        {
            "scenario_id": "primary_candidate",
            "purpose": "Implement the chosen approach with runner-justified preprocessing and model family choices.",
            "required": True,
        },
        {
            "scenario_id": "leakage_guarded",
            "purpose": "Exclude leakage-suspect or prediction-time-unavailable fields until confirmed.",
            "required": True,
        },
    ]
    strategy_text = json.dumps({"feature_strategy": feature_strategy, "modeling_strategy": modeling_strategy, "type": idea.approach_type})
    if "text" in strategy_text or "text" in idea.approach_type:
        scenarios.append(
            {
                "scenario_id": "text_incremental_value",
                "purpose": "Compare with and without text-derived features under the same SplitManifest.",
                "required": False,
            }
        )
    if "time" in strategy_text or "time" in idea.approach_type:
        scenarios.append(
            {
                "scenario_id": "causal_time_features",
                "purpose": "Compare calendar-only, lag, and rolling-statistic variants generated without future information.",
                "required": False,
            }
        )
    return scenarios


def acceptance_criteria(evaluation_spec: EvaluationSpec | None) -> list[str]:
    metric = evaluation_spec.primary_metric if evaluation_spec else "primary metric"
    return [
        f"Report {metric} on the harness SplitManifest validation rows.",
        "Register prediction_output, metrics, feature_recipe, diagnostics, visualization_spec, and report artifacts.",
        "Explain why the selected model and preprocessing are appropriate for this dataset and evaluation design.",
        "Document unresolved assumptions and whether they affect deployment or only research iteration.",
    ]


def review_questions_for_plan(
    project: Project,
    idea: Idea,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> list[dict[str, Any]]:
    questions = [
        {
            "topic": "prediction-time availability",
            "question": "Are all proposed feature sources available at prediction time?",
            "fallback_policy": "exclude_until_confirmed",
            "risk_level": "high",
        },
        {
            "topic": "approach flexibility",
            "question": "Should the runner perform controlled web/literature research before finalizing the modeling family?",
            "fallback_policy": "infer_and_continue",
            "risk_level": "medium",
        },
    ]
    if project.target_column is None:
        questions.append(
            {
                "topic": "target",
                "question": "What target column should this project optimize?",
                "fallback_policy": "block_until_answered",
                "risk_level": "blocking",
            }
        )
    if evaluation_spec is None or split_manifest is None:
        questions.append(
            {
                "topic": "evaluation",
                "question": "Which approved EvaluationSpec and SplitManifest should constrain this experiment?",
                "fallback_policy": "block_until_answered",
                "risk_level": "blocking",
            }
        )
    if "time" in idea.approach_type:
        questions.append(
            {
                "topic": "time_features",
                "question": "What is the deployment timestamp and permitted historical window for lag/rolling features?",
                "fallback_policy": "scenario_compare",
                "risk_level": "high",
            }
        )
    return questions


def plan_warnings(idea: Idea, recent_diagnostics: Artifact | None) -> list[str]:
    warnings = []
    if recent_diagnostics is None:
        warnings.append("No evaluation diagnostics artifact is available yet; compare run errors after the first execution.")
    if idea.risk_level in {"high", "blocking", "deployment_blocking"}:
        warnings.append(f"Idea risk level is {idea.risk_level}; require explicit review before deployment-oriented decisions.")
    return warnings


def experiment_plan_summary(plan: dict[str, Any]) -> str:
    readiness = plan["readiness"]
    if readiness["blocking_items"]:
        return f"Experiment plan {plan['id']} needs inputs: {', '.join(readiness['blocking_items'])}"
    return (
        f"Experiment plan {plan['id']} is ready for runner execution with "
        f"{len(plan['approach_selection']['scenario_comparisons'])} scenario checks."
    )


def plan_source_edges(
    *,
    research_brief: ResearchBrief | None,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    context_pack: Artifact | None,
    quality_gate: Artifact | None,
    recent_diagnostics: Artifact | None,
    job: Job | None,
) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    if research_brief:
        edges.append(("research_brief", research_brief.id))
    if dataset:
        edges.append(("dataset_snapshot", dataset.id))
    if evaluation_spec:
        edges.append(("evaluation_spec", evaluation_spec.id))
    if split_manifest:
        edges.append(("split_manifest", split_manifest.id))
    if context_pack:
        edges.append(("artifact", context_pack.id))
    if quality_gate:
        edges.append(("artifact", quality_gate.id))
    if recent_diagnostics:
        edges.append(("artifact", recent_diagnostics.id))
    if job:
        edges.append(("job", job.id))
    return edges


def primary_metric(run: ExperimentRun | None) -> dict[str, Any]:
    if run is None:
        return {"name": None, "value": None}
    metrics = loads_json(run.metrics_json, {})
    value = metrics.get("primary_metric_value")
    return {
        "name": metrics.get("primary_metric_name"),
        "value": float(value) if isinstance(value, int | float) else None,
    }


def metric_delta(metric: dict[str, Any], best_metric: dict[str, Any] | None) -> float | None:
    value = metric.get("value")
    best_value = best_metric.get("value") if best_metric else None
    if not isinstance(value, int | float) or not isinstance(best_value, int | float):
        return None
    return float(value) - float(best_value)


def run_sort_key(run: ExperimentRun) -> tuple[int, float]:
    metric = primary_metric(run)
    value = metric["value"]
    if not isinstance(value, int | float):
        return (1, 0.0)
    if metric["name"] in LOWER_IS_BETTER:
        return (0, float(value))
    return (0, -float(value))


def compact_diagnostics_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    if not diagnostics:
        return {}
    summary = diagnostics.get("summary", {})
    sanity = diagnostics.get("sanity_checks", {})
    return {
        "task_kind": diagnostics.get("task_kind"),
        "summary": summary,
        "slice_count": len(diagnostics.get("slice_metrics", [])),
        "worst_example_count": len(diagnostics.get("worst_examples", [])),
        "prediction_count_matches_split": sanity.get("prediction_count_matches_split"),
        "all_predictions_joined_to_valid_rows": sanity.get("all_predictions_joined_to_valid_rows"),
    }


def comparison_recommendation(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No successful runs are available; run a baseline or agent experiment before choosing an approach."
    best = rows[0]
    if not best.get("diagnostics_artifact_id"):
        return f"Run {best['run_id']} is currently best by primary metric, but diagnostics should be generated before decision use."
    return f"Run {best['run_id']} is currently best by primary metric and has diagnostics available for review."


def comparison_blockers(rows: list[dict[str, Any]]) -> list[str]:
    blockers = []
    if not rows:
        blockers.append("No successful ExperimentRun exists.")
    if rows and not all(row.get("diagnostics_artifact_id") for row in rows):
        blockers.append("One or more successful runs do not have evaluation diagnostics artifacts.")
    for row in rows:
        diagnostics_summary = row.get("diagnostics_summary")
        if not isinstance(diagnostics_summary, dict):
            continue
        if diagnostics_summary.get("prediction_count_matches_split") is False:
            blockers.append(f"Run {row['run_id']} prediction count does not match SplitManifest.")
        if diagnostics_summary.get("all_predictions_joined_to_valid_rows") is False:
            blockers.append(f"Run {row['run_id']} has predictions that do not join to validation rows.")
    return blockers


def run_report_next_actions(run: ExperimentRun, diagnostics: dict[str, Any]) -> list[str]:
    actions = []
    if not diagnostics:
        actions.append("Generate evaluation diagnostics for this run.")
    else:
        summary = compact_diagnostics_summary(diagnostics)
        if summary.get("prediction_count_matches_split") is False:
            actions.append("Investigate prediction row coverage before comparing this run.")
        if summary.get("slice_count", 0) == 0:
            actions.append("Add or confirm low-cardinality slice columns for deeper error analysis.")
        if summary.get("worst_example_count", 0) > 0:
            actions.append("Review worst examples and decide whether they indicate data issues, missing features, or acceptable noise.")
    if run.model_version_id:
        actions.append("Replay-validate the linked ModelVersion before relying on the package artifact.")
    return actions or ["Compare this run against alternatives and decide whether another agent iteration is warranted."]


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


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def latest_artifact_for_idea(db: Session, project_id: str, idea_id: str | None, asset_type: str) -> Artifact | None:
    if idea_id is None:
        return None
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("idea_id") == idea_id:
            return artifact
    return None


def latest_diagnostics_for_run(db: Session, project_id: str, run_id: str) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "evaluation_diagnostics")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("run_id") == run_id:
            return artifact
    return None


def load_artifact_json(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}
