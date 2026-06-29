from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    Assumption,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Insight,
    ModelVersion,
    Project,
    Question,
    Report,
    ResearchBrief,
    SemanticCatalog,
    SplitManifest,
    VisualizationSpec,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)


@dataclass(frozen=True)
class ResearchBriefResult:
    brief: ResearchBrief
    artifact: Artifact


@dataclass(frozen=True)
class ResearchPlanResult:
    plan: dict[str, Any]
    artifact: Artifact


@dataclass(frozen=True)
class IdeaGenerationResult:
    ideas: list[Idea]
    artifact_ids: list[str]


@dataclass(frozen=True)
class ReportResult:
    report: Report
    artifact: Artifact


@dataclass(frozen=True)
class VisualizationResult:
    visualization: VisualizationSpec
    artifact: Artifact


@dataclass(frozen=True)
class DecisionDashboardResult:
    dashboard: dict[str, Any]
    report: Report
    dashboard_artifact: Artifact
    report_artifact: Artifact
    visualizations: list[VisualizationSpec]
    artifact_ids: list[str]


def generate_research_brief(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    question: str | None = None,
) -> ResearchBriefResult:
    semantic_columns = latest_semantic_columns(db, dataset)
    profile = summarize_columns(semantic_columns)
    research_question = question or (
        "Which prediction approaches should be considered for this tabular task, given the dataset semantics, "
        "evaluation constraints, leakage risks, and available artifact context?"
    )
    research_plan_artifact = latest_project_artifact(db, project.id, "research_plan")
    research_synthesis_artifact = latest_project_artifact(db, project.id, "research_finding_synthesis")
    relational_feature_plan_artifact = latest_project_artifact(db, project.id, "relational_feature_plan")
    relational_feature_recipe_artifact = latest_project_artifact(db, project.id, "relational_feature_recipe")
    relational_feature_diagnostics_artifact = latest_project_artifact(
        db, project.id, "relational_feature_scenario_diagnostics"
    )
    sources = build_research_sources(
        project,
        dataset,
        evaluation_spec,
        research_plan_artifact,
        research_synthesis_artifact,
        relational_feature_plan_artifact,
        relational_feature_recipe_artifact,
        relational_feature_diagnostics_artifact,
    )
    key_findings = build_key_findings(project, dataset, evaluation_spec, profile)
    recommended_approaches = build_recommended_approaches(project, profile)
    title = "Approach Research Brief"
    summary_md = render_research_brief(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        question=research_question,
        sources=sources,
        key_findings=key_findings,
        recommended_approaches=recommended_approaches,
        profile=profile,
    )
    brief_id = new_id("rb")
    artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_brief",
        name=f"research_brief_{brief_id}",
        filename="research_brief.md",
        text=summary_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "research_plan_artifact_id": research_plan_artifact.id if research_plan_artifact else None,
            "research_finding_synthesis_artifact_id": research_synthesis_artifact.id
            if research_synthesis_artifact
            else None,
            "relational_feature_plan_artifact_id": relational_feature_plan_artifact.id
            if relational_feature_plan_artifact
            else None,
            "relational_feature_recipe_artifact_id": relational_feature_recipe_artifact.id
            if relational_feature_recipe_artifact
            else None,
            "relational_feature_scenario_diagnostics_artifact_id": relational_feature_diagnostics_artifact.id
            if relational_feature_diagnostics_artifact
            else None,
            "question": research_question,
        },
    )
    brief = ResearchBrief(
        id=brief_id,
        project_id=project.id,
        dataset_snapshot_id=dataset.id if dataset else None,
        evaluation_spec_id=evaluation_spec.id if evaluation_spec else None,
        title=title,
        question=research_question,
        summary_md=summary_md,
        sources_json=dumps_json(sources),
        key_findings_json=dumps_json(key_findings),
        recommended_approaches_json=dumps_json(recommended_approaches),
        artifact_id=artifact.id,
        status="ready",
        created_by_type="system",
    )
    db.add(brief)
    db.flush()
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="research_brief",
            to_asset_id=brief.id,
            relation_type="informs",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="research_brief",
            to_asset_id=brief.id,
            relation_type="constrains",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="research_brief",
        from_asset_id=brief.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    return ResearchBriefResult(brief=brief, artifact=artifact)


def create_research_plan(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
) -> ResearchPlanResult:
    context_artifacts = {
        "data_quality_gate": latest_project_artifact(db, project.id, "data_quality_gate"),
        "relational_catalog": latest_project_artifact(db, project.id, "relational_catalog"),
        "relational_feature_plan": latest_project_artifact(db, project.id, "relational_feature_plan"),
        "relational_feature_recipe": latest_project_artifact(db, project.id, "relational_feature_recipe"),
        "relational_feature_scenario_diagnostics": latest_project_artifact(
            db, project.id, "relational_feature_scenario_diagnostics"
        ),
        "evaluation_scenario_comparison": latest_project_artifact(db, project.id, "evaluation_scenario_comparison"),
        "evaluation_approval_review": latest_project_artifact(db, project.id, "evaluation_approval_review"),
        "evaluation_diagnostics": latest_project_artifact(db, project.id, "evaluation_diagnostics"),
        "baseline_strategy_plan": latest_project_artifact(db, project.id, "baseline_strategy_plan"),
        "benchmark_scenario_pack": latest_project_artifact(db, project.id, "benchmark_scenario_pack"),
        "decision_dashboard": latest_project_artifact(db, project.id, "decision_dashboard"),
    }
    profile = summarize_columns(latest_semantic_columns(db, dataset))
    library_assets = list(
        db.scalars(select(Asset).where(Asset.status == "active").order_by(Asset.asset_type, Asset.name).limit(24)).all()
    )
    asset_context = [research_asset_context(asset) for asset in library_assets]
    query_plan = build_research_query_plan(
        project=project,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        profile=profile,
        context_artifacts=context_artifacts,
    )
    recommended_references = recommend_research_assets(asset_context, profile, context_artifacts)
    missing_asset_suggestions = missing_research_asset_suggestions(asset_context, profile, context_artifacts)
    plan: dict[str, Any] = {
        "schema_version": "research_plan.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "dataset": {
            "dataset_snapshot_id": dataset.id if dataset else None,
            "row_count": dataset.row_count if dataset else None,
            "column_count": dataset.column_count if dataset else None,
            "source_type": dataset.source_type if dataset else None,
            "source_ref": dataset.source_ref if dataset else None,
        },
        "evaluation": {
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_type": evaluation_spec.split_type if evaluation_spec else None,
            "primary_metric": evaluation_spec.primary_metric if evaluation_spec else None,
            "status": evaluation_spec.status if evaluation_spec else "missing",
        },
        "context_artifacts": {
            key: research_artifact_context(value) for key, value in context_artifacts.items()
        },
        "dataset_signals": profile,
        "source_policy": {
            "allowed_source_types": [
                "project_artifacts",
                "cross_project_asset_library",
                "controlled_web_search",
                "literature_search",
                "benchmark_context",
            ],
            "network_default": "disabled_until_runner_policy_allows",
            "credential_policy": {
                "secret_access": "forbidden",
                "connector_credentials": "never_materialized_for_agent",
                "kaggle_credentials": "user_managed_outside_tablex",
            },
            "citation_requirement": "External claims must return citation metadata as Evidence or source-summary artifacts.",
            "ui_completeness_requirement": "Reports must be understandable in Tablex without external dashboards.",
        },
        "query_plan": query_plan,
        "skill_plan": {
            "available_assets": asset_context,
            "recommended_references": recommended_references,
            "missing_asset_suggestions": missing_asset_suggestions,
        },
        "expected_evidence": [
            {
                "evidence_type": "source_summary",
                "strength": "medium",
                "required_fields": ["title", "url_or_doi", "retrieved_at", "claim", "relevance"],
            },
            {
                "evidence_type": "project_artifact",
                "strength": "strong",
                "required_fields": ["artifact_id", "claim", "lineage_relation"],
            },
        ],
        "reporting_requirements": [
            "Summarize why each selected approach fits the current data and EvaluationSpec.",
            "Separate benchmark fixture smoke results from real benchmark score claims.",
            "Report unresolved assumptions, fallback policies, and whether they block deployment.",
            "Include visualization specifications for leaderboard, slice diagnostics, and error or calibration summaries when relevant.",
        ],
        "agent_handoff": {
            "may_execute_external_search": False,
            "future_runner": "controlled_research_runner",
            "required_before_agent_code": [
                "approved EvaluationSpec",
                "SplitManifest when implementation starts",
                "DataQualityGate review",
                "source policy approval if network search is enabled",
            ],
        },
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_plan",
        name=f"research_plan_{new_id('rplan')}",
        filename="research_plan.json",
        payload=plan,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "query_count": len(query_plan),
            "recommended_asset_count": len(recommended_references),
            "network_default": "disabled_until_runner_policy_allows",
        },
    )
    create_research_plan_lineage(
        db,
        project=project,
        artifact=artifact,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        context_artifacts=context_artifacts,
        library_assets=library_assets,
    )
    return ResearchPlanResult(plan=plan, artifact=artifact)


def generate_approach_candidates(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    research_brief: ResearchBrief | None,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
) -> IdeaGenerationResult:
    if research_brief:
        recommended = loads_json(research_brief.recommended_approaches_json, [])
    else:
        profile = summarize_columns(latest_semantic_columns(db, dataset))
        recommended = build_recommended_approaches(project, profile)
    research_plan_artifact = latest_project_artifact(db, project.id, "research_plan")
    research_synthesis_artifact = latest_project_artifact(db, project.id, "research_finding_synthesis")
    relational_feature_plan_artifact = latest_project_artifact(db, project.id, "relational_feature_plan")
    relational_feature_recipe_artifact = latest_project_artifact(db, project.id, "relational_feature_recipe")
    relational_feature_diagnostics_artifact = latest_project_artifact(
        db, project.id, "relational_feature_scenario_diagnostics"
    )
    ideas: list[Idea] = []
    artifact_ids: list[str] = []
    for index, approach in enumerate(recommended[:5], start=1):
        idea_id = new_id("idea")
        agent_task_contract = build_agent_task_contract(
            idea_id=idea_id,
            project=project,
            dataset=dataset,
            evaluation_spec=evaluation_spec,
            approach=approach,
            research_brief=research_brief,
            research_plan_artifact=research_plan_artifact,
            research_synthesis_artifact=research_synthesis_artifact,
            relational_feature_plan_artifact=relational_feature_plan_artifact,
            relational_feature_recipe_artifact=relational_feature_recipe_artifact,
            relational_feature_diagnostics_artifact=relational_feature_diagnostics_artifact,
        )
        payload = {
            "schema_version": "approach_candidate.v1",
            "id": idea_id,
            "title": approach["title"],
            "hypothesis": approach["hypothesis"],
            "approach_type": approach["approach_type"],
            "rationale_md": approach["rationale_md"],
            "feature_strategy": approach["feature_strategy"],
            "modeling_strategy": approach["modeling_strategy"],
            "evaluation_notes_md": approach["evaluation_notes_md"],
            "agent_task_contract": agent_task_contract,
        }
        artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="approach_candidate",
            name=f"approach_candidate_{idea_id}",
            filename="approach_candidate.json",
            payload=payload,
            metadata={
                "project_id": project.id,
                "idea_id": idea_id,
                "research_brief_id": research_brief.id if research_brief else None,
                "research_plan_artifact_id": research_plan_artifact.id if research_plan_artifact else None,
                "research_finding_synthesis_artifact_id": research_synthesis_artifact.id
                if research_synthesis_artifact
                else None,
                "relational_feature_plan_artifact_id": relational_feature_plan_artifact.id
                if relational_feature_plan_artifact
                else None,
                "relational_feature_recipe_artifact_id": relational_feature_recipe_artifact.id
                if relational_feature_recipe_artifact
                else None,
                "relational_feature_scenario_diagnostics_artifact_id": relational_feature_diagnostics_artifact.id
                if relational_feature_diagnostics_artifact
                else None,
            },
        )
        idea = Idea(
            id=idea_id,
            project_id=project.id,
            dataset_snapshot_id=dataset.id if dataset else None,
            evaluation_spec_id=evaluation_spec.id if evaluation_spec else None,
            research_brief_id=research_brief.id if research_brief else None,
            title=str(approach["title"]),
            hypothesis=str(approach["hypothesis"]),
            approach_type=str(approach["approach_type"]),
            rationale_md=str(approach["rationale_md"]),
            feature_strategy_json=dumps_json(approach["feature_strategy"]),
            modeling_strategy_json=dumps_json(approach["modeling_strategy"]),
            evaluation_notes_md=str(approach["evaluation_notes_md"]),
            expected_artifacts_json=dumps_json(
                ["experiment_plan", "feature_recipe", "run_report", "metrics", "visualization_spec"]
            ),
            agent_task_contract_json=dumps_json(agent_task_contract),
            confidence=float(approach.get("confidence", 0.55)),
            risk_level=str(approach.get("risk_level", "medium")),
            status="proposed",
            priority=100 - index * 10,
            artifact_id=artifact.id,
            created_by_type="system",
        )
        db.add(idea)
        db.flush()
        if research_brief:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="research_brief",
                from_asset_id=research_brief.id,
                to_asset_type="idea",
                to_asset_id=idea.id,
                relation_type="proposes",
            )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="idea",
            from_asset_id=idea.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="materializes",
        )
        ideas.append(idea)
        artifact_ids.append(artifact.id)
    return IdeaGenerationResult(ideas=ideas, artifact_ids=artifact_ids)


def draft_project_report(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    title: str | None = None,
    report_type: str = "project_summary",
) -> ReportResult:
    datasets = db.scalars(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc())
    ).all()
    assumptions = db.scalars(
        select(Assumption).where(Assumption.project_id == project.id).order_by(Assumption.updated_at.desc())
    ).all()
    ideas = db.scalars(select(Idea).where(Idea.project_id == project.id).order_by(Idea.priority.desc())).all()
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all()
    model_versions = db.scalars(select(ModelVersion).where(ModelVersion.project_id == project.id)).all()
    insights = db.scalars(select(Insight).where(Insight.project_id == project.id).order_by(Insight.created_at.desc())).all()
    visualizations = db.scalars(
        select(VisualizationSpec).where(VisualizationSpec.project_id == project.id).order_by(VisualizationSpec.created_at.desc())
    ).all()
    artifacts = list(
        db.scalars(select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.created_at.desc())).all()
    )
    artifact_by_type = latest_artifacts_by_type(artifacts)
    relational_context = decision_relational_context(artifact_by_type)
    reports_title = title or f"{project.name} Project Report"
    markdown = render_project_report(
        project=project,
        datasets=list(datasets),
        assumptions=list(assumptions),
        ideas=list(ideas),
        runs=list(runs),
        model_versions=list(model_versions),
        insights=list(insights),
        visualizations=list(visualizations),
        relational_context=relational_context,
    )
    artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="report",
        name=f"report_{new_id('rptart')}",
        filename="project_report.md",
        text=markdown,
        metadata={"project_id": project.id, "report_type": report_type},
    )
    source_asset_ids = build_report_source_assets(
        datasets=list(datasets),
        ideas=list(ideas),
        runs=list(runs),
        artifacts=[
            artifact
            for artifact in artifact_by_type.values()
            if artifact.asset_type
            in {
                "relational_feature_plan",
                "relational_feature_recipe",
                "relational_feature_scenario_diagnostics",
            }
        ],
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type=report_type,
        title=reports_title,
        summary=first_sentence(markdown),
        artifact_id=artifact.id,
        source_asset_ids_json=dumps_json(source_asset_ids),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarizes",
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
    return ReportResult(report=report, artifact=artifact)


def create_visualization_spec(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> VisualizationResult:
    runs = db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all()
    metric_rows = []
    for run in runs:
        metrics = loads_json(run.metrics_json, {})
        metric_rows.append(
            {
                "run_id": run.id,
                "runner_type": run.runner_type,
                "status": run.status,
                "primary_metric_name": metrics.get("primary_metric_name"),
                "primary_metric_value": metrics.get("primary_metric_value"),
                "model_version_id": run.model_version_id,
            }
        )
    spec = {
        "schema_version": "visualization_spec.v1",
        "title": "Leaderboard Primary Metric",
        "chart_type": "leaderboard_bar",
        "data": metric_rows,
        "encoding": {
            "x": "run_id",
            "y": "primary_metric_value",
            "color": "runner_type",
            "tooltip": ["run_id", "status", "primary_metric_name", "model_version_id"],
        },
        "empty_state": "Run experiments before comparing leaderboard metrics.",
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"visualization_spec_{new_id('vizart')}",
        filename="leaderboard_visualization.json",
        payload=spec,
        metadata={"project_id": project.id, "chart_type": "leaderboard_bar"},
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title="Leaderboard Primary Metric",
        chart_type="leaderboard_bar",
        spec_json=dumps_json(spec),
        source_artifact_id=None,
        artifact_id=artifact.id,
        status="draft",
        created_by_type="system",
    )
    db.add(visualization)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarizes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="visualization_spec",
        from_asset_id=visualization.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="materializes",
    )
    return VisualizationResult(visualization=visualization, artifact=artifact)


def create_decision_dashboard(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> DecisionDashboardResult:
    datasets = list(
        db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.created_at.desc())
        ).all()
    )
    assumptions = list(
        db.scalars(select(Assumption).where(Assumption.project_id == project.id).order_by(Assumption.updated_at.desc())).all()
    )
    questions = list(
        db.scalars(select(Question).where(Question.project_id == project.id).order_by(Question.created_at.desc())).all()
    )
    evaluation_specs = list(
        db.scalars(select(EvaluationSpec).where(EvaluationSpec.project_id == project.id).order_by(EvaluationSpec.created_at.desc())).all()
    )
    split_manifests = list(
        db.scalars(select(SplitManifest).where(SplitManifest.project_id == project.id).order_by(SplitManifest.created_at.desc())).all()
    )
    runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
    model_versions = list(db.scalars(select(ModelVersion).where(ModelVersion.project_id == project.id)).all())
    insights = list(
        db.scalars(select(Insight).where(Insight.project_id == project.id).order_by(Insight.created_at.desc())).all()
    )
    artifacts = list(
        db.scalars(select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.created_at.desc())).all()
    )
    artifact_by_type = latest_artifacts_by_type(artifacts)
    relational_context = decision_relational_context(artifact_by_type)
    approved_spec = next((spec for spec in evaluation_specs if spec.status == "approved"), None)
    high_risk_assumptions = [
        assumption
        for assumption in assumptions
        if assumption.risk_level in {"high", "blocking", "deployment_blocking"} or assumption.status in {"challenged", "needs_review"}
    ]
    open_questions = [question for question in questions if question.status == "open"]
    readiness_stages = decision_readiness_stages(
        datasets=datasets,
        approved_spec=approved_spec,
        split_manifests=split_manifests,
        runs=runs,
        model_versions=model_versions,
        high_risk_assumptions=high_risk_assumptions,
        open_questions=open_questions,
        artifacts_by_type=artifact_by_type,
        relational_context=relational_context,
    )
    artifact_completeness = decision_artifact_completeness(artifact_by_type)
    risk_register = decision_risk_register(
        assumptions=high_risk_assumptions,
        open_questions=open_questions,
        artifacts_by_type=artifact_by_type,
        relational_context=relational_context,
    )
    next_actions = decision_next_actions(readiness_stages, artifact_completeness, risk_register)
    visualization_specs = decision_visualization_specs(
        readiness_stages=readiness_stages,
        artifact_completeness=artifact_completeness,
        risk_register=risk_register,
    )
    dashboard: dict[str, Any] = {
        "schema_version": "decision_dashboard.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "summary": {
            "dataset_count": len(datasets),
            "approved_evaluation_spec_id": approved_spec.id if approved_spec else None,
            "split_manifest_count": len(split_manifests),
            "experiment_run_count": len(runs),
            "model_version_count": len(model_versions),
            "insight_count": len(insights),
            "high_risk_assumption_count": len(high_risk_assumptions),
            "open_question_count": len(open_questions),
        },
        "readiness_stages": readiness_stages,
        "artifact_completeness": artifact_completeness,
        "risk_register": risk_register,
        "next_actions": next_actions,
        "unresolved_assumptions": [
            {
                "id": assumption.id,
                "statement": assumption.statement,
                "risk_level": assumption.risk_level,
                "status": assumption.status,
                "fallback_policy": assumption.fallback_policy,
                "confidence": assumption.confidence,
            }
            for assumption in high_risk_assumptions[:12]
        ],
        "open_questions": [
            {
                "id": question.id,
                "topic": question.topic,
                "question": question.question,
                "risk_level": question.risk_level,
                "fallback_policy": question.fallback_policy,
            }
            for question in open_questions[:12]
        ],
        "benchmark_context": decision_benchmark_context(artifact_by_type),
        "relational_context": relational_context,
        "visualization_specs": visualization_specs,
        "artifact_refs": {
            asset_type: decision_artifact_ref(artifact) for asset_type, artifact in artifact_by_type.items()
        },
    }
    dashboard_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="decision_dashboard",
        name=f"decision_dashboard_{new_id('dash')}",
        filename="decision_dashboard.json",
        payload=dashboard,
        metadata={
            "project_id": project.id,
            "readiness_status": overall_readiness_status(readiness_stages),
            "high_risk_assumption_count": len(high_risk_assumptions),
            "open_question_count": len(open_questions),
        },
    )
    report_md = render_decision_report(dashboard)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="decision_report",
        name=f"decision_report_{new_id('drptart')}",
        filename="decision_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "report_type": "decision_report",
            "decision_dashboard_artifact_id": dashboard_artifact.id,
            "readiness_status": overall_readiness_status(readiness_stages),
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="decision_report",
        title=f"{project.name} Decision Report",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(decision_source_assets(dashboard)),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualizations = persist_decision_visualizations(
        db,
        store=store,
        project=project,
        dashboard_artifact=dashboard_artifact,
        visualization_specs=visualization_specs,
    )
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="artifact",
        to_asset_id=dashboard_artifact.id,
        relation_type="summarizes_decision_state",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=dashboard_artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
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
    for artifact in artifact_by_type.values():
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=dashboard_artifact.id,
            relation_type="informs",
        )
    artifact_ids = [dashboard_artifact.id, report_artifact.id, *[visualization.artifact_id for visualization in visualizations]]
    return DecisionDashboardResult(
        dashboard=dashboard,
        report=report,
        dashboard_artifact=dashboard_artifact,
        report_artifact=report_artifact,
        visualizations=visualizations,
        artifact_ids=artifact_ids,
    )


def latest_artifacts_by_type(artifacts: list[Artifact]) -> dict[str, Artifact]:
    by_type: dict[str, Artifact] = {}
    for artifact in artifacts:
        by_type.setdefault(artifact.asset_type, artifact)
    return by_type


def decision_readiness_stages(
    *,
    datasets: list[DatasetSnapshot],
    approved_spec: EvaluationSpec | None,
    split_manifests: list[SplitManifest],
    runs: list[ExperimentRun],
    model_versions: list[ModelVersion],
    high_risk_assumptions: list[Assumption],
    open_questions: list[Question],
    artifacts_by_type: dict[str, Artifact],
    relational_context: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        stage("Data", bool(datasets), len(datasets), "Latest DatasetSnapshot is available." if datasets else "Upload or import data."),
        stage(
            "Quality",
            "data_quality_gate" in artifacts_by_type,
            1 if "data_quality_gate" in artifacts_by_type else 0,
            "DataQualityGate exists." if "data_quality_gate" in artifacts_by_type else "Run data quality analysis.",
        ),
        stage(
            "Assumptions",
            not high_risk_assumptions and not any(question.fallback_policy == "block_until_answered" for question in open_questions),
            len(high_risk_assumptions) + len(open_questions),
            "No blocking assumptions/questions." if not high_risk_assumptions else "Review high-risk assumptions and open questions.",
        ),
        stage(
            "Evaluation",
            bool(approved_spec and split_manifests),
            len(split_manifests),
            "Approved EvaluationSpec and SplitManifest exist." if approved_spec and split_manifests else "Approve EvaluationSpec and generate SplitManifest.",
        ),
        stage(
            "Research",
            "research_plan" in artifacts_by_type,
            1 if "research_plan" in artifacts_by_type else 0,
            "ResearchPlan exists." if "research_plan" in artifacts_by_type else "Generate controlled ResearchPlan.",
        ),
        stage(
            "Relational",
            relational_context["status"] in {"ready_for_agent_review", "ready_with_deferred_risks"},
            int(relational_context.get("usable_feature_count") or 0),
            relational_context["detail"],
        ),
        stage(
            "Strategy",
            "baseline_strategy_plan" in artifacts_by_type or "experiment_plan" in artifacts_by_type,
            int("baseline_strategy_plan" in artifacts_by_type) + int("experiment_plan" in artifacts_by_type),
            "Strategy artifacts exist." if "baseline_strategy_plan" in artifacts_by_type else "Create baseline or experiment strategy plan.",
        ),
        stage(
            "Experiments",
            bool(runs and model_versions),
            len(runs),
            "Runs and ModelVersions exist." if runs and model_versions else "Run baseline or agent task.",
        ),
        stage(
            "Reporting",
            "decision_report" in artifacts_by_type or "report" in artifacts_by_type,
            int("decision_report" in artifacts_by_type) + int("report" in artifacts_by_type),
            "Reports exist." if "decision_report" in artifacts_by_type or "report" in artifacts_by_type else "Generate decision report.",
        ),
    ]


def stage(name: str, ready: bool, count: int, detail: str) -> dict[str, Any]:
    return {
        "stage": name,
        "status": "ready" if ready else "needs_attention",
        "count": count,
        "detail": detail,
    }


def decision_artifact_completeness(artifacts_by_type: dict[str, Artifact]) -> list[dict[str, Any]]:
    required = [
        ("dataset_snapshot", "Data imported or uploaded"),
        ("semantic_catalog", "Semantic catalog generated"),
        ("data_quality_gate", "Quality and leakage gate"),
        ("evaluation_scenario_comparison", "Evaluation scenario comparison"),
        ("evaluation_approval_review", "Evaluation approval review"),
        ("evaluation_spec", "Approved evaluation spec artifact"),
        ("split_manifest", "Split manifest"),
        ("research_plan", "Controlled research plan"),
        ("baseline_strategy_plan", "Baseline strategy plan"),
        ("relational_feature_plan", "Relational feature plan"),
        ("relational_feature_recipe", "Relational feature recipe preview"),
        ("relational_feature_scenario_diagnostics", "Relational feature scenario diagnostics"),
        ("benchmark_scenario_pack", "Benchmark scenario pack when benchmark data is used"),
        ("experiment_run", "Experiment run record artifact when available"),
        ("evaluation_diagnostics", "Evaluation diagnostics after a run"),
        ("insight_set", "Generated insight set"),
        ("visualization_spec", "Portable visualization specs"),
        ("decision_report", "Decision report"),
    ]
    return [
        {
            "asset_type": asset_type,
            "label": label,
            "status": "available" if asset_type in artifacts_by_type else "missing",
            "artifact_id": artifacts_by_type[asset_type].id if asset_type in artifacts_by_type else None,
        }
        for asset_type, label in required
    ]


def decision_risk_register(
    *,
    assumptions: list[Assumption],
    open_questions: list[Question],
    artifacts_by_type: dict[str, Artifact],
    relational_context: dict[str, Any],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for assumption in assumptions[:10]:
        risks.append(
            {
                "risk_type": "assumption",
                "id": assumption.id,
                "severity": assumption.risk_level,
                "summary": assumption.statement,
                "status": assumption.status,
                "fallback_policy": assumption.fallback_policy,
            }
        )
    for question in open_questions[:10]:
        risks.append(
            {
                "risk_type": "open_question",
                "id": question.id,
                "severity": question.risk_level,
                "summary": question.question,
                "status": question.status,
                "fallback_policy": question.fallback_policy,
            }
        )
    quality_metadata = artifact_metadata(artifacts_by_type.get("data_quality_gate"))
    severity = quality_metadata.get("severity")
    if severity in {"warning", "fail", "blocked"}:
        risks.append(
            {
                "risk_type": "data_quality",
                "id": artifacts_by_type["data_quality_gate"].id,
                "severity": severity,
                "summary": "DataQualityGate has warnings or blockers; inspect leakage, missingness, identity, and temporal findings.",
                "status": "needs_review",
                "fallback_policy": "scenario_compare",
            }
        )
    benchmark = artifacts_by_type.get("benchmark_scenario_pack")
    if benchmark:
        risks.append(
            {
                "risk_type": "benchmark_fixture_policy",
                "id": benchmark.id,
                "severity": "medium",
                "summary": "Fixture results validate workflow only and must not be reported as benchmark performance.",
                "status": "active",
                "fallback_policy": "require_before_deployment",
            }
        )
    if relational_context["status"] == "ready_with_deferred_risks":
        risks.append(
            {
                "risk_type": "relational_features",
                "id": relational_context.get("diagnostics_artifact_id"),
                "severity": "medium",
                "summary": "Relational diagnostics found usable preview features but also deferred safety checks.",
                "status": "needs_review",
                "fallback_policy": "scenario_compare",
            }
        )
    elif relational_context["status"] == "needs_feature_review":
        risks.append(
            {
                "risk_type": "relational_features",
                "id": relational_context.get("diagnostics_artifact_id"),
                "severity": "medium",
                "summary": "Relational recipe diagnostics did not identify usable preview features under current heuristics.",
                "status": "needs_review",
                "fallback_policy": "exclude_until_confirmed",
            }
        )
    return risks


def decision_next_actions(
    readiness_stages: list[dict[str, Any]],
    artifact_completeness: list[dict[str, Any]],
    risk_register: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in artifact_completeness:
        if item["status"] == "missing" and item["asset_type"] in {
            "data_quality_gate",
            "evaluation_scenario_comparison",
            "split_manifest",
            "research_plan",
            "baseline_strategy_plan",
        }:
            actions.append(
                {
                    "priority": 90 - len(actions) * 5,
                    "action": f"Create {item['label']}",
                    "reason": f"`{item['asset_type']}` is missing from the project artifact set.",
                }
            )
    if risk_register:
        actions.insert(
            0,
            {
                "priority": 95,
                "action": "Review high-risk assumptions, open questions, and quality warnings",
                "reason": "Decision readiness depends on explicitly managed risks.",
            },
        )
    if all(stage_item["status"] == "ready" for stage_item in readiness_stages):
        actions.append(
            {
                "priority": 40,
                "action": "Prepare a human decision review",
                "reason": "Core stages are ready; summarize tradeoffs before deployment or deeper agent work.",
            }
        )
    return actions[:8]


def decision_benchmark_context(artifacts_by_type: dict[str, Artifact]) -> dict[str, Any]:
    pack_artifact = artifacts_by_type.get("benchmark_scenario_pack")
    if pack_artifact is None:
        return {"status": "not_present", "fixture_policy": "No benchmark scenario pack is attached."}
    metadata = artifact_metadata(pack_artifact)
    return {
        "status": "available",
        "benchmark_id": metadata.get("benchmark_id"),
        "scenario_kind": metadata.get("scenario_kind"),
        "artifact_id": pack_artifact.id,
        "fixture_policy": "Fixture results are product smoke checks, not benchmark performance claims.",
        "preview_url": f"/api/artifacts/{pack_artifact.id}/preview",
    }


def decision_relational_context(artifacts_by_type: dict[str, Artifact]) -> dict[str, Any]:
    plan = artifacts_by_type.get("relational_feature_plan")
    recipe = artifacts_by_type.get("relational_feature_recipe")
    diagnostics = artifacts_by_type.get("relational_feature_scenario_diagnostics")
    if plan is None:
        return {
            "status": "needs_plan",
            "detail": "Create a relational feature plan when multi-table context exists.",
        }
    plan_metadata = artifact_metadata(plan)
    recipe_metadata = artifact_metadata(recipe)
    diagnostics_metadata = artifact_metadata(diagnostics)
    diagnostics_payload = artifact_json_payload(diagnostics)
    usable_count = int(diagnostics_metadata.get("usable_feature_count") or 0)
    deferred_count = int(diagnostics_metadata.get("deferred_step_count") or 0)
    if diagnostics is None:
        status = "needs_diagnostics" if recipe else "needs_recipe"
    elif usable_count > 0 and deferred_count == 0:
        status = "ready_for_agent_review"
    elif usable_count > 0:
        status = "ready_with_deferred_risks"
    else:
        status = "needs_feature_review"
    details = {
        "needs_recipe": "Build a preview-only relational feature recipe.",
        "needs_diagnostics": "Diagnose relational feature scenarios before runner implementation.",
        "ready_for_agent_review": "Relational preview features are ready for controlled AgentTask review.",
        "ready_with_deferred_risks": "Relational preview features exist, but deferred safety checks need review.",
        "needs_feature_review": "Relational diagnostics did not identify usable preview features under current heuristics.",
    }
    return {
        "status": status,
        "detail": details.get(status, "Review relational feature state."),
        "plan_artifact_id": plan.id,
        "recipe_artifact_id": recipe.id if recipe else None,
        "diagnostics_artifact_id": diagnostics.id if diagnostics else None,
        "aggregation_candidate_count": plan_metadata.get("aggregation_candidate_count"),
        "generated_feature_count": recipe_metadata.get("generated_feature_count"),
        "usable_feature_count": diagnostics_metadata.get("usable_feature_count"),
        "constant_feature_count": diagnostics_metadata.get("constant_feature_count"),
        "high_missing_feature_count": diagnostics_metadata.get("high_missing_feature_count"),
        "deferred_step_count": diagnostics_metadata.get("deferred_step_count"),
        "scenario_count": diagnostics_metadata.get("scenario_count"),
        "scenario_comparison": diagnostics_payload.get("scenario_comparison")
        if isinstance(diagnostics_payload.get("scenario_comparison"), list)
        else [],
    }


def artifact_json_payload(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def decision_visualization_specs(
    *,
    readiness_stages: list[dict[str, Any]],
    artifact_completeness: list[dict[str, Any]],
    risk_register: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    risk_counts: dict[str, int] = {}
    for risk in risk_register:
        severity = str(risk.get("severity") or "unknown")
        risk_counts[severity] = risk_counts.get(severity, 0) + 1
    return [
        {
            "schema_version": "visualization_spec.v1",
            "title": "Decision Readiness Stages",
            "chart_type": "stage_status",
            "data": readiness_stages,
            "encoding": {"stage": "stage", "status": "status", "count": "count", "detail": "detail"},
            "empty_state": "Run workflow steps to populate decision readiness stages.",
        },
        {
            "schema_version": "visualization_spec.v1",
            "title": "Decision Artifact Completeness",
            "chart_type": "category_bars",
            "data": [
                {"label": item["asset_type"], "count": 1 if item["status"] == "available" else 0}
                for item in artifact_completeness
            ],
            "encoding": {"x": "label", "y": "count"},
            "empty_state": "Artifacts will appear as the project workflow progresses.",
        },
        {
            "schema_version": "visualization_spec.v1",
            "title": "Decision Risk Summary",
            "chart_type": "category_bars",
            "data": [{"label": severity, "count": count} for severity, count in sorted(risk_counts.items())],
            "encoding": {"x": "label", "y": "count"},
            "empty_state": "No decision risks are currently registered.",
        },
    ]


def persist_decision_visualizations(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dashboard_artifact: Artifact,
    visualization_specs: list[dict[str, Any]],
) -> list[VisualizationSpec]:
    visualizations: list[VisualizationSpec] = []
    for spec in visualization_specs:
        artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="visualization_spec",
            name=f"decision_visualization_{new_id('vizart')}",
            filename="decision_visualization.json",
            payload=spec,
            metadata={
                "project_id": project.id,
                "chart_type": spec["chart_type"],
                "decision_dashboard_artifact_id": dashboard_artifact.id,
            },
        )
        visualization = VisualizationSpec(
            id=new_id("viz"),
            project_id=project.id,
            title=str(spec["title"]),
            chart_type=str(spec["chart_type"]),
            spec_json=dumps_json(spec),
            source_artifact_id=dashboard_artifact.id,
            artifact_id=artifact.id,
            status="draft",
            created_by_type="system",
        )
        db.add(visualization)
        visualizations.append(visualization)
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=dashboard_artifact.id,
            to_asset_type="visualization_spec",
            to_asset_id=visualization.id,
            relation_type="visualizes",
        )
    return visualizations


def decision_artifact_ref(artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def overall_readiness_status(readiness_stages: list[dict[str, Any]]) -> str:
    if all(item["status"] == "ready" for item in readiness_stages):
        return "ready"
    if any(item["stage"] in {"Data", "Evaluation"} and item["status"] != "ready" for item in readiness_stages):
        return "blocked"
    return "needs_attention"


def decision_source_assets(dashboard: dict[str, Any]) -> list[dict[str, str]]:
    refs = dashboard.get("artifact_refs", {})
    if not isinstance(refs, dict):
        return []
    source_assets = []
    for value in refs.values():
        if isinstance(value, dict) and value.get("artifact_id") and value.get("asset_type"):
            source_assets.append({"asset_type": str(value["asset_type"]), "asset_id": str(value["artifact_id"])})
    return source_assets[:20]


def render_decision_report(dashboard: dict[str, Any]) -> str:
    lines = [
        f"# {dashboard['project']['name']} Decision Report",
        "",
        "## Summary",
        "",
    ]
    for key, value in dashboard["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Readiness Stages", ""])
    for item in dashboard["readiness_stages"]:
        lines.append(f"- {item['stage']}: {item['status']} ({item['detail']})")
    lines.extend(["", "## Next Actions", ""])
    if dashboard["next_actions"]:
        for action in dashboard["next_actions"]:
            lines.append(f"- P{action['priority']}: {action['action']} - {action['reason']}")
    else:
        lines.append("- No immediate next action was generated.")
    lines.extend(["", "## Risks", ""])
    if dashboard["risk_register"]:
        for risk in dashboard["risk_register"][:12]:
            lines.append(f"- {risk['severity']} {risk['risk_type']}: {risk['summary']}")
    else:
        lines.append("- No high-priority decision risks are currently registered.")
    lines.extend(["", "## Artifact Completeness", ""])
    for item in dashboard["artifact_completeness"]:
        lines.append(f"- {item['asset_type']}: {item['status']}")
    benchmark = dashboard["benchmark_context"]
    lines.extend(
        [
            "",
            "## Benchmark Context",
            "",
            f"- Status: {benchmark.get('status')}",
            f"- Benchmark: {benchmark.get('benchmark_id') or '-'}",
            f"- Scenario: {benchmark.get('scenario_kind') or '-'}",
            f"- Fixture policy: {benchmark.get('fixture_policy')}",
        ]
    )
    relational = dashboard["relational_context"]
    lines.extend(
        [
            "",
            "## Relational Feature Context",
            "",
            f"- Status: {relational.get('status')}",
            f"- Detail: {relational.get('detail')}",
            f"- Aggregation candidates: {relational.get('aggregation_candidate_count') or '-'}",
            f"- Generated preview features: {relational.get('generated_feature_count') or '-'}",
            f"- Usable preview features: {relational.get('usable_feature_count') or '-'}",
            f"- Deferred steps: {relational.get('deferred_step_count') or '-'}",
        ]
    )
    scenarios = relational.get("scenario_comparison")
    if isinstance(scenarios, list) and scenarios:
        lines.extend(["", "Relational scenarios:"])
        for scenario in scenarios[:4]:
            if isinstance(scenario, dict):
                lines.append(f"- {scenario.get('scenario')}: {scenario.get('status')} ({scenario.get('risk_level')})")
    return "\n".join(lines).strip() + "\n"


def latest_semantic_columns(db: Session, dataset: DatasetSnapshot | None) -> list[dict[str, Any]]:
    if dataset is None:
        return []
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        return []
    return cast(list[dict[str, Any]], loads_json(catalog.columns_json, []))


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def summarize_columns(columns: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_counts: dict[str, int] = {}
    roles: dict[str, int] = {}
    leakage_columns = []
    for column in columns:
        semantic_type = str(column.get("semantic_type") or "unknown")
        role = str(column.get("role") or "feature")
        semantic_counts[semantic_type] = semantic_counts.get(semantic_type, 0) + 1
        roles[role] = roles.get(role, 0) + 1
        if column.get("is_leakage_suspect"):
            leakage_columns.append(str(column.get("column_name")))
    return {
        "column_count": len(columns),
        "semantic_counts": semantic_counts,
        "roles": roles,
        "has_text": semantic_counts.get("text", 0) > 0,
        "has_datetime": semantic_counts.get("datetime", 0) > 0,
        "has_group": roles.get("group", 0) > 0,
        "leakage_columns": leakage_columns,
    }


def build_research_sources(
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    research_plan_artifact: Artifact | None = None,
    research_synthesis_artifact: Artifact | None = None,
    relational_feature_plan_artifact: Artifact | None = None,
    relational_feature_recipe_artifact: Artifact | None = None,
    relational_feature_diagnostics_artifact: Artifact | None = None,
) -> list[dict[str, Any]]:
    sources = [
        {
            "source_type": "project_context",
            "title": "Project metadata",
            "ref": project.id,
            "summary": "Task type, target column, current phase, and local harness context.",
        },
        {
            "source_type": "skill_placeholder",
            "title": "Tabular modeling and evaluation skills",
            "ref": "future_skill_library:tabular_modeling",
            "summary": "Future AgentRunner tasks may attach reusable Skills for feature engineering, modeling, diagnostics, and reporting.",
        },
        {
            "source_type": "external_research_placeholder",
            "title": "Timely literature and web research",
            "ref": "future_agent_research:web_search",
            "summary": "Future Codex runner may perform controlled web or literature search and return citations as Evidence.",
        },
    ]
    if dataset:
        sources.append(
            {
                "source_type": "dataset_snapshot",
                "title": "Latest DatasetSnapshot",
                "ref": dataset.id,
                "summary": f"{dataset.row_count or 'unknown'} rows and {dataset.column_count or 'unknown'} columns.",
            }
        )
    if evaluation_spec:
        sources.append(
            {
                "source_type": "evaluation_spec",
                "title": "Approved EvaluationSpec",
                "ref": evaluation_spec.id,
                "summary": f"{evaluation_spec.split_type} split with primary metric {evaluation_spec.primary_metric}.",
            }
        )
    if research_plan_artifact:
        sources.append(
            {
                "source_type": "research_plan",
                "title": "Controlled ResearchPlan",
                "ref": research_plan_artifact.id,
                "summary": "Harness-owned plan for Skill use, controlled web/literature queries, evidence expectations, and reporting outputs.",
            }
        )
    if research_synthesis_artifact:
        metadata = loads_json(research_synthesis_artifact.metadata_json, {})
        sources.append(
            {
                "source_type": "research_finding_synthesis",
                "title": "Research Finding Synthesis",
                "ref": research_synthesis_artifact.id,
                "summary": (
                    "Synthesized runner findings, citation audit, follow-up requirements, and AgentTask handoff "
                    f"context. Findings: {metadata.get('finding_count', 'unknown')}; "
                    f"citations: {metadata.get('citation_count', 'unknown')}."
                ),
            }
        )
    if relational_feature_plan_artifact:
        metadata = loads_json(relational_feature_plan_artifact.metadata_json, {})
        sources.append(
            {
                "source_type": "relational_feature_plan",
                "title": "Relational Feature Plan",
                "ref": relational_feature_plan_artifact.id,
                "summary": (
                    "Train-fold-safe relational feature planning context. "
                    f"Aggregation candidates: {metadata.get('aggregation_candidate_count', 'unknown')}; "
                    f"high risks: {metadata.get('high_risk_count', 'unknown')}."
                ),
            }
        )
    if relational_feature_recipe_artifact:
        metadata = loads_json(relational_feature_recipe_artifact.metadata_json, {})
        sources.append(
            {
                "source_type": "relational_feature_recipe",
                "title": "Relational Feature Recipe Preview",
                "ref": relational_feature_recipe_artifact.id,
                "summary": (
                    "Preview-only relational FeatureRecipe context with executed and deferred aggregation steps. "
                    f"Generated features: {metadata.get('generated_feature_count', 'unknown')}; "
                    f"deferred steps: {metadata.get('deferred_step_count', 'unknown')}."
                ),
            }
        )
    if relational_feature_diagnostics_artifact:
        metadata = loads_json(relational_feature_diagnostics_artifact.metadata_json, {})
        sources.append(
            {
                "source_type": "relational_feature_scenario_diagnostics",
                "title": "Relational Feature Scenario Diagnostics",
                "ref": relational_feature_diagnostics_artifact.id,
                "summary": (
                    "Preview scenario diagnostics for relational features, split readiness, and deferred safety checks. "
                    f"Usable features: {metadata.get('usable_feature_count', 'unknown')}; "
                    f"scenarios: {metadata.get('scenario_count', 'unknown')}."
                ),
            }
        )
    return sources


def build_research_query_plan(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    profile: dict[str, Any],
    context_artifacts: dict[str, Artifact | None],
) -> list[dict[str, Any]]:
    task_label = project.task_type or "tabular prediction"
    target_label = project.target_column or "target"
    queries = [
        {
            "query_id": "tabular_modeling_current_practice",
            "query": f"{task_label} tabular machine learning gradient boosting baseline evaluation leakage",
            "purpose": "Identify current high-signal modeling families and evaluation pitfalls for the task.",
            "priority": 90,
            "expected_evidence": "source_summary",
        },
        {
            "query_id": "metric_and_validation_design",
            "query": f"{task_label} {target_label} validation split metric calibration imbalanced tabular",
            "purpose": "Check metric and validation choices against known task risks.",
            "priority": 85,
            "expected_evidence": "source_summary",
        },
    ]
    relational_metadata = artifact_metadata(context_artifacts.get("relational_catalog"))
    if int(relational_metadata.get("table_count") or 0) > 1:
        queries.append(
            {
                "query_id": "relational_tabular_feature_aggregation",
                "query": "multi table tabular prediction feature aggregation leakage entity split",
                "purpose": "Support relational FeatureRecipe and AgentTask planning without fixed joins.",
                "priority": 82,
                "expected_evidence": "source_summary",
            }
        )
    if profile.get("has_text"):
        queries.append(
            {
                "query_id": "text_tabular_features",
                "query": "tabular prediction text features tf-idf leakage train fold validation",
                "purpose": "Decide whether and how to compare text-derived features.",
                "priority": 74,
                "expected_evidence": "source_summary",
            }
        )
    if profile.get("has_datetime") or (evaluation_spec and evaluation_spec.split_type == "time"):
        queries.append(
            {
                "query_id": "time_aware_tabular_features",
                "query": "time aware tabular features lag rolling statistics leakage validation",
                "purpose": "Plan causal temporal feature generation and validation windows.",
                "priority": 78,
                "expected_evidence": "source_summary",
            }
        )
    if dataset and dataset.source_type == "benchmark_catalog":
        queries.append(
            {
                "query_id": "benchmark_context",
                "query": f"{dataset.source_ref or 'benchmark'} common approaches leakage validation",
                "purpose": "Collect benchmark-specific cautions without treating leaderboard recipes as fixed policy.",
                "priority": 70,
                "expected_evidence": "source_summary",
            }
        )
    return queries


def research_artifact_context(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": artifact_metadata(artifact),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def artifact_metadata(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    return cast(dict[str, Any], loads_json(artifact.metadata_json, {}))


def research_asset_context(asset: Asset) -> dict[str, Any]:
    return {
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "description": asset.description,
        "tags": loads_json(asset.tags_json, []),
        "semantic_tags": loads_json(asset.semantic_tags_json, []),
        "latest_version_id": asset.latest_version_id,
    }


def recommend_research_assets(
    asset_context: list[dict[str, Any]],
    profile: dict[str, Any],
    context_artifacts: dict[str, Artifact | None],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    relational_metadata = artifact_metadata(context_artifacts.get("relational_catalog"))
    has_relational_context = int(relational_metadata.get("table_count") or 0) > 1
    for asset in asset_context:
        semantic_tags = {str(tag) for tag in asset.get("semantic_tags", [])}
        asset_type = str(asset.get("asset_type"))
        reason = None
        if "decision_dashboard" in semantic_tags and context_artifacts.get("decision_dashboard"):
            reason = "DecisionDashboard exists, so decision reporting and readiness visualization assets are relevant."
        elif "evaluation_diagnostics" in semantic_tags and context_artifacts.get("evaluation_diagnostics"):
            reason = "Evaluation diagnostics exist and should be interpreted for reportable model evidence."
        elif "relational_features" in semantic_tags and (
            has_relational_context or context_artifacts.get("benchmark_scenario_pack")
        ):
            reason = "Relational or benchmark scenario context is available."
        elif "time_features" in semantic_tags and profile.get("has_datetime"):
            reason = "Datetime signals are present and need causal temporal feature controls."
        elif "text_features" in semantic_tags and profile.get("has_text"):
            reason = "Text-like columns are present."
        elif {"gradient_boosting", "xgboost", "tabular_modeling"} & semantic_tags:
            reason = "Strong tabular baseline planning should consider mixed-type gradient boosting when evaluation is ready."
        elif "controlled_research" in semantic_tags:
            reason = "Use to guide controlled research and source-backed approach selection."
        elif "split_manifest" in semantic_tags and context_artifacts.get("evaluation_scenario_comparison"):
            reason = "Use to compare feature scenarios under stable evaluation constraints."
        elif "leakage_control" in semantic_tags:
            reason = "Leakage and prediction-time availability controls are always relevant."
        elif asset_type == "skill":
            reason = "General Skill asset available for runner planning under harness policy."
        if reason:
            recommendations.append(
                {
                    "asset_id": asset["asset_id"],
                    "asset_type": asset_type,
                    "latest_version_id": asset.get("latest_version_id"),
                    "name": asset.get("name"),
                    "reason": reason,
                }
            )
    return recommendations[:12]


def missing_research_asset_suggestions(
    asset_context: list[dict[str, Any]],
    profile: dict[str, Any],
    context_artifacts: dict[str, Artifact | None],
) -> list[dict[str, Any]]:
    semantic_tags = {str(tag) for asset in asset_context for tag in asset.get("semantic_tags", [])}
    suggestions: list[dict[str, Any]] = []
    if profile.get("has_datetime") and "time_features" not in semantic_tags:
        suggestions.append(
            {
                "asset_type": "feature_recipe",
                "name": "causal_time_lag_rolling_features",
                "reason": "Datetime signals exist but no time-feature Skill/FeatureRecipe is registered.",
            }
        )
    relational_metadata = artifact_metadata(context_artifacts.get("relational_catalog"))
    if int(relational_metadata.get("table_count") or 0) > 1 and "relational_features" not in semantic_tags:
        suggestions.append(
            {
                "asset_type": "feature_recipe",
                "name": "relational_aggregation_recipe",
                "reason": "RelationalCatalog has supporting tables but no relational aggregation asset is registered.",
            }
        )
    if "controlled_research" not in semantic_tags:
        suggestions.append(
            {
                "asset_type": "skill",
                "name": "controlled_literature_review",
                "reason": "No Skill is registered for source-backed controlled research.",
            }
        )
    return suggestions


def create_research_plan_lineage(
    db: Session,
    *,
    project: Project,
    artifact: Artifact,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    context_artifacts: dict[str, Artifact | None],
    library_assets: list[Asset],
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="plans_research",
    )
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="informs",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="constrains",
        )
    for context_artifact in context_artifacts.values():
        if context_artifact:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=context_artifact.id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="informs",
            )
    for asset in library_assets[:12]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="asset",
            from_asset_id=asset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="suggested_for_research",
        )


def build_key_findings(
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    profile: dict[str, Any],
) -> list[str]:
    findings = [
        "Harness-owned EvaluationSpec and SplitManifest must constrain every approach before model comparison.",
        "Approach selection should be treated as an evidence-backed proposal, not a fixed built-in recipe.",
        "Feature generation must exclude validation/test targets and prediction-time unavailable columns.",
    ]
    if not project.target_column:
        findings.append("Target column is not set; approach implementation should remain planning-only until target is confirmed.")
    if dataset:
        findings.append(f"Latest dataset snapshot has {dataset.row_count or 'unknown'} rows and {dataset.column_count or 'unknown'} columns.")
    if evaluation_spec:
        findings.append(f"Primary evaluation currently uses {evaluation_spec.split_type} split and {evaluation_spec.primary_metric}.")
    if profile.get("has_text"):
        findings.append("Text-like columns exist, so text encoders or text feature extraction should be considered.")
    if profile.get("has_datetime"):
        findings.append("Datetime columns exist, so time-aware validation and temporal features may be relevant.")
    if profile.get("has_group"):
        findings.append("Group-like identifiers exist, so group leakage and grouped validation should be checked.")
    if profile.get("leakage_columns"):
        findings.append("Leakage-suspect columns must be excluded or confirmed before use.")
    return findings


def build_recommended_approaches(project: Project, profile: dict[str, Any]) -> list[dict[str, Any]]:
    approaches = [
        {
            "title": "Research-backed gradient boosting approach",
            "approach_type": "tabular_gradient_boosting",
            "hypothesis": "A dataset-specific gradient boosting pipeline with explicit leakage controls can provide a strong first candidate.",
            "rationale_md": "Use the approved evaluation design, inspect schema semantics, choose preprocessing from evidence, and compare against sanity floors. This is not a hard-coded baseline; the agent must justify preprocessing and modeling choices.",
            "feature_strategy": {
                "numeric": "impute and scale only if model family requires it",
                "categorical": "choose ordinal, one-hot, target-safe encoding, or native categorical support based on cardinality and model choice",
                "text": "use only if text columns are prediction-time available",
                "leakage_control": "exclude leakage-suspect columns until confirmed",
            },
            "modeling_strategy": {
                "families_to_consider": ["tree_boosting", "linear_sanity_model", "dummy_sanity_floor"],
                "selection_policy": "choose after dataset review and source-backed reasoning",
            },
            "evaluation_notes_md": "Respect the approved EvaluationSpec and SplitManifest. Report metric deltas, calibration/error slices when applicable, and failure modes.",
            "confidence": 0.68,
            "risk_level": "medium",
        },
        {
            "title": "Interpretable diagnostic model and error-slicing approach",
            "approach_type": "diagnostic_interpretable",
            "hypothesis": "A transparent model plus error slices can expose leakage, target definition issues, and weak segments before deeper modeling.",
            "rationale_md": "Evaluation-first workflows need sanity checks and diagnostics that explain when the task is ill-posed or when features are unavailable at prediction time.",
            "feature_strategy": {
                "numeric": "simple robust preprocessing",
                "categorical": "low-cardinality encodings only",
                "diagnostics": "slice metrics by high-risk columns when allowed",
            },
            "modeling_strategy": {
                "families_to_consider": ["regularized_linear_model", "decision_tree_sanity_model"],
                "selection_policy": "prefer debuggability over raw score",
            },
            "evaluation_notes_md": "Use this as a debugging companion even if it is not the leaderboard winner.",
            "confidence": 0.64,
            "risk_level": "low",
        },
    ]
    if profile.get("has_text"):
        approaches.append(
            {
                "title": "Text-enhanced tabular approach",
                "approach_type": "text_enhanced_tabular",
                "hypothesis": "Prediction-time available text fields may add signal when encoded and evaluated with leakage controls.",
                "rationale_md": "Text columns should be transformed only within the training fold and compared against a no-text scenario to quantify incremental value.",
                "feature_strategy": {
                    "text": "compare TF-IDF, hashing, or task-appropriate embedding features inside the split",
                    "scenario_compare": ["without_text", "with_text"],
                },
                "modeling_strategy": {
                    "families_to_consider": ["linear_text_tabular", "tree_boosting_with_text_features"],
                    "selection_policy": "use incremental validation lift and error analysis",
                },
                "evaluation_notes_md": "Do not generate text features from target, validation labels, or future information.",
                "confidence": 0.58,
                "risk_level": "medium",
            }
        )
    if profile.get("has_datetime"):
        approaches.append(
            {
                "title": "Time-aware feature and validation approach",
                "approach_type": "time_aware_tabular",
                "hypothesis": "Temporal covariates, lag features, rolling summaries, and calendar effects may improve performance when generated causally.",
                "rationale_md": "Temporal features are useful only when the split and feature windows reflect deployment timing. The agent should compare scenarios and document leakage boundaries.",
                "feature_strategy": {
                    "time": "derive calendar features, lags, and rolling statistics only from historical rows",
                    "scenario_compare": ["calendar_only", "lag_rolling", "no_time_features"],
                },
                "modeling_strategy": {
                    "families_to_consider": ["tree_boosting", "regularized_regression"],
                    "selection_policy": "prefer causal features validated by time split",
                },
                "evaluation_notes_md": "Require time-aware split or explicit justification before accepting temporal features.",
                "confidence": 0.56,
                "risk_level": "high",
            }
        )
    return approaches


def build_agent_task_contract(
    *,
    idea_id: str,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    approach: dict[str, Any],
    research_brief: ResearchBrief | None,
    research_plan_artifact: Artifact | None = None,
    research_synthesis_artifact: Artifact | None = None,
    relational_feature_plan_artifact: Artifact | None = None,
    relational_feature_recipe_artifact: Artifact | None = None,
    relational_feature_diagnostics_artifact: Artifact | None = None,
) -> dict[str, Any]:
    research_contract_inputs = research_plan_contract_inputs(research_plan_artifact)
    research_synthesis_inputs = research_synthesis_contract_inputs(research_synthesis_artifact)
    relational_plan_inputs = relational_feature_plan_contract_inputs(relational_feature_plan_artifact)
    relational_recipe_inputs = relational_feature_recipe_contract_inputs(relational_feature_recipe_artifact)
    relational_diagnostics_inputs = relational_feature_scenario_diagnostics_contract_inputs(
        relational_feature_diagnostics_artifact
    )
    return {
        "task_id": f"agt_{idea_id}",
        "task_type": "implement_prediction_approach",
        "project_id": project.id,
        "objective": (
            f"Investigate and implement the proposed approach `{approach['title']}` only within the controlled "
            "workspace, respecting harness-owned evaluation, artifact, and lineage contracts."
        ),
        "inputs": {
            "idea_id": idea_id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "research_brief_id": research_brief.id if research_brief else None,
            "research_plan_artifact_id": research_plan_artifact.id if research_plan_artifact else None,
            "research_finding_synthesis_artifact_id": research_synthesis_artifact.id
            if research_synthesis_artifact
            else None,
            "relational_feature_plan_artifact_id": relational_feature_plan_artifact.id
            if relational_feature_plan_artifact
            else None,
            "relational_feature_recipe_artifact_id": relational_feature_recipe_artifact.id
            if relational_feature_recipe_artifact
            else None,
            "relational_feature_scenario_diagnostics_artifact_id": relational_feature_diagnostics_artifact.id
            if relational_feature_diagnostics_artifact
            else None,
            "approach_type": approach["approach_type"],
            "allowed_research_modes": ["project_artifacts", "skill_library", "controlled_web_search"],
            "must_respect_split_manifest": True,
            "research_finding_synthesis": research_synthesis_inputs,
            "relational_feature_plan": relational_plan_inputs,
            "relational_feature_recipe": relational_recipe_inputs,
            "relational_feature_scenario_diagnostics": relational_diagnostics_inputs,
            **research_contract_inputs,
        },
        "required_outputs": [
            {
                "path": "reports/approach_report.md",
                "schema": "markdown_report.v1",
                "description": "Reasoning, implementation summary, results, caveats, and next steps.",
            },
            {
                "path": "artifacts/feature_recipe.json",
                "schema": "feature_recipe.v1",
                "description": "Feature generation recipe without target leakage.",
            },
            {
                "path": "artifacts/metrics.json",
                "schema": "experiment_metrics.v1",
                "description": "Metrics computed on the harness SplitManifest.",
            },
            {
                "path": "artifacts/visualization_spec.json",
                "schema": "visualization_spec.v1",
                "description": "Portable visualization spec for reports and UI.",
            },
        ],
        "quality_checks": [
            "Use the approved EvaluationSpec and SplitManifest.",
            "Compare against at least one sanity floor.",
            "Register every important output as an artifact.",
            "Summarize assumptions, risks, and source evidence.",
        ],
        "forbidden_actions": [
            "Do not read secrets or connector credentials.",
            "Do not use validation/test targets in feature generation prompts or encoders.",
            "Do not destructively modify evaluation_spec or split_manifest.",
            "Do not write to production databases.",
        ],
        "context_files": [
            "AGENTS.md",
            "docs/dev.md",
            "schemas/agent_task_contract.schema.json",
            "schemas/agent_result.schema.json",
            "schemas/approach_candidate.schema.json",
            "schemas/visualization_spec.schema.json",
        ],
        "output_schema_path": "schemas/agent_result.schema.json",
        "assumption_context": {
            "target_column": project.target_column,
            "risk_level": approach.get("risk_level"),
            "requires_research_citations_for_external_claims": True,
        },
        "autonomy_level": 3,
    }


def research_plan_contract_inputs(research_plan_artifact: Artifact | None) -> dict[str, Any]:
    if research_plan_artifact is None:
        return {
            "recommended_asset_ids": [],
            "recommended_asset_version_ids": [],
            "research_source_policy": {},
        }
    try:
        payload = loads_json(artifact_primary_path(research_plan_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    skill_plan = payload.get("skill_plan")
    recommendations = []
    if isinstance(skill_plan, dict) and isinstance(skill_plan.get("recommended_references"), list):
        recommendations = [item for item in skill_plan["recommended_references"] if isinstance(item, dict)]
    source_policy = payload.get("source_policy")
    return {
        "recommended_asset_ids": unique_strings(item.get("asset_id") for item in recommendations),
        "recommended_asset_version_ids": unique_strings(item.get("latest_version_id") for item in recommendations),
        "research_source_policy": source_policy if isinstance(source_policy, dict) else {},
    }


def research_synthesis_contract_inputs(synthesis_artifact: Artifact | None) -> dict[str, Any]:
    if synthesis_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(synthesis_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    return {
        "artifact_id": synthesis_artifact.id,
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "citation_audit": payload.get("citation_audit") if isinstance(payload.get("citation_audit"), dict) else {},
        "follow_up_requirements": payload.get("follow_up_requirements")
        if isinstance(payload.get("follow_up_requirements"), list)
        else [],
        "agent_task_handoff": payload.get("agent_task_handoff")
        if isinstance(payload.get("agent_task_handoff"), dict)
        else {},
    }


def relational_feature_plan_contract_inputs(plan_artifact: Artifact | None) -> dict[str, Any]:
    if plan_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(plan_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    return {
        "artifact_id": plan_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "table_coverage": payload.get("table_coverage") if isinstance(payload.get("table_coverage"), dict) else {},
        "aggregation_candidate_count": len(payload.get("aggregation_candidates", []))
        if isinstance(payload.get("aggregation_candidates"), list)
        else 0,
        "risk_register": payload.get("risk_register") if isinstance(payload.get("risk_register"), list) else [],
        "agent_task_handoff": payload.get("agent_task_handoff")
        if isinstance(payload.get("agent_task_handoff"), dict)
        else {},
    }


def relational_feature_recipe_contract_inputs(recipe_artifact: Artifact | None) -> dict[str, Any]:
    if recipe_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(recipe_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    raw_execution_summary = payload.get("execution_summary")
    raw_safety = payload.get("safety")
    raw_steps = payload.get("steps")
    raw_deferred_steps = payload.get("deferred_steps")
    raw_execution_scope = payload.get("execution_scope")
    execution_summary: dict[str, Any] = raw_execution_summary if isinstance(raw_execution_summary, dict) else {}
    safety: dict[str, Any] = raw_safety if isinstance(raw_safety, dict) else {}
    steps: list[Any] = raw_steps if isinstance(raw_steps, list) else []
    deferred_steps: list[Any] = raw_deferred_steps if isinstance(raw_deferred_steps, list) else []
    execution_scope: dict[str, Any] = raw_execution_scope if isinstance(raw_execution_scope, dict) else {}
    return {
        "artifact_id": recipe_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "execution_summary": execution_summary,
        "safety": safety,
        "generated_feature_count": int(execution_summary.get("generated_feature_count") or 0),
        "executed_step_count": len(steps),
        "deferred_step_count": len(deferred_steps),
        "preview_only": execution_scope.get("mode") == "preview_only" if execution_scope else True,
    }


def relational_feature_scenario_diagnostics_contract_inputs(diagnostics_artifact: Artifact | None) -> dict[str, Any]:
    if diagnostics_artifact is None:
        return {}
    try:
        payload = loads_json(artifact_primary_path(diagnostics_artifact).read_text(encoding="utf-8"), {})
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        return {}
    raw_preview_summary = payload.get("preview_summary")
    raw_split_compatibility = payload.get("split_compatibility")
    raw_safety = payload.get("safety")
    raw_scenarios = payload.get("scenario_comparison")
    preview_summary: dict[str, Any] = raw_preview_summary if isinstance(raw_preview_summary, dict) else {}
    split_compatibility: dict[str, Any] = (
        raw_split_compatibility if isinstance(raw_split_compatibility, dict) else {}
    )
    safety: dict[str, Any] = raw_safety if isinstance(raw_safety, dict) else {}
    scenarios: list[Any] = raw_scenarios if isinstance(raw_scenarios, list) else []
    return {
        "artifact_id": diagnostics_artifact.id,
        "source_summary": payload.get("source_summary") if isinstance(payload.get("source_summary"), dict) else {},
        "preview_summary": preview_summary,
        "split_compatibility": split_compatibility,
        "scenario_count": len(scenarios),
        "scenario_comparison": scenarios[:4],
        "safety": safety,
    }


def unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def render_research_brief(
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    question: str,
    sources: list[dict[str, Any]],
    key_findings: list[str],
    recommended_approaches: list[dict[str, Any]],
    profile: dict[str, Any],
) -> str:
    lines = [
        "# Approach Research Brief",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Target column: {project.target_column or 'not set'}",
        f"- DatasetSnapshot: {dataset.id if dataset else 'not available'}",
        f"- EvaluationSpec: {evaluation_spec.id if evaluation_spec else 'not approved yet'}",
        f"- Question: {question}",
        "",
        "## Dataset Signals",
        "",
        f"- Column count: {profile.get('column_count', 0)}",
        f"- Semantic counts: {profile.get('semantic_counts', {})}",
        f"- Role counts: {profile.get('roles', {})}",
        f"- Leakage suspects: {profile.get('leakage_columns', [])}",
        "",
        "## Sources",
    ]
    for source in sources:
        lines.append(f"- {source['source_type']}: {source['title']} ({source['ref']}) - {source['summary']}")
    lines.extend(["", "## Key Findings"])
    lines.extend([f"- {finding}" for finding in key_findings])
    lines.extend(["", "## Recommended Approach Candidates"])
    for approach in recommended_approaches:
        lines.extend(
            [
                f"### {approach['title']}",
                "",
                f"- Type: {approach['approach_type']}",
                f"- Hypothesis: {approach['hypothesis']}",
                f"- Risk: {approach.get('risk_level', 'medium')}",
                "",
                str(approach["rationale_md"]),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_project_report(
    *,
    project: Project,
    datasets: list[DatasetSnapshot],
    assumptions: list[Assumption],
    ideas: list[Idea],
    runs: list[ExperimentRun],
    model_versions: list[ModelVersion],
    insights: list[Insight],
    visualizations: list[VisualizationSpec],
    relational_context: dict[str, Any],
) -> str:
    lines = [
        f"# {project.name} Project Report",
        "",
        "## Current State",
        "",
        f"- Phase: {project.current_phase}",
        f"- Target column: {project.target_column or 'not set'}",
        f"- Dataset snapshots: {len(datasets)}",
        f"- Assumptions: {len(assumptions)}",
        f"- Proposed ideas: {len(ideas)}",
        f"- Experiment runs: {len(runs)}",
        f"- Model versions: {len(model_versions)}",
        f"- Insights: {len(insights)}",
        f"- Visualization specs: {len(visualizations)}",
        "",
        "## Insights",
    ]
    if insights:
        for insight in insights[:8]:
            lines.extend(
                [
                    f"### {insight.title}",
                    "",
                    f"- Type: {insight.insight_type}",
                    f"- Severity: {insight.severity}",
                    f"- Confidence: {insight.confidence:.2f}",
                    "",
                    insight.summary,
                    "",
                ]
            )
    else:
        lines.append("No generated insights are available yet.")
    lines.extend(
        [
            "",
            "## Visualizations",
        ]
    )
    if visualizations:
        for visualization in visualizations[:8]:
            lines.append(f"- {visualization.title}: {visualization.chart_type} ({visualization.status})")
    else:
        lines.append("No visualization specs have been generated yet.")
    lines.extend(["", "## Relational Feature Context"])
    lines.append(f"- Status: {relational_context.get('status')}")
    lines.append(f"- Detail: {relational_context.get('detail')}")
    lines.append(f"- Generated preview features: {relational_context.get('generated_feature_count') or '-'}")
    lines.append(f"- Usable preview features: {relational_context.get('usable_feature_count') or '-'}")
    lines.append(f"- Deferred steps: {relational_context.get('deferred_step_count') or '-'}")
    lines.extend(
        [
        "",
        "## Approach Candidates",
        ]
    )
    if ideas:
        for idea in ideas[:8]:
            lines.extend(
                [
                    f"### {idea.title}",
                    "",
                    f"- Type: {idea.approach_type}",
                    f"- Status: {idea.status}",
                    f"- Risk: {idea.risk_level}",
                    f"- Confidence: {idea.confidence:.2f}",
                    f"- Hypothesis: {idea.hypothesis}",
                    "",
                ]
            )
    else:
        lines.append("No approach candidates have been generated yet.")
    lines.extend(["", "## Runs"])
    if runs:
        for run in runs[:8]:
            metrics = loads_json(run.metrics_json, {})
            lines.append(
                f"- {run.id}: {run.status}, {metrics.get('primary_metric_name', 'metric')}={metrics.get('primary_metric_value', '-')}"
            )
    else:
        lines.append("No experiment runs have been recorded yet.")
    lines.extend(["", "## Risks And Follow-ups"])
    high_risk = [assumption for assumption in assumptions if assumption.risk_level in {"high", "blocking", "deployment_blocking"}]
    if high_risk:
        for assumption in high_risk[:8]:
            lines.append(f"- {assumption.statement} ({assumption.fallback_policy})")
    else:
        lines.append("- Continue checking assumptions as new approaches and data slices are added.")
    return "\n".join(lines).strip() + "\n"


def build_report_source_assets(
    *,
    datasets: list[DatasetSnapshot],
    ideas: list[Idea],
    runs: list[ExperimentRun],
    artifacts: list[Artifact] | None = None,
) -> list[dict[str, str]]:
    source_assets: list[dict[str, str]] = []
    source_assets.extend({"asset_type": "dataset_snapshot", "asset_id": dataset.id} for dataset in datasets[:5])
    source_assets.extend({"asset_type": "idea", "asset_id": idea.id} for idea in ideas[:10])
    source_assets.extend({"asset_type": "experiment_run", "asset_id": run.id} for run in runs[:10])
    source_assets.extend({"asset_type": "artifact", "asset_id": artifact.id} for artifact in (artifacts or [])[:10])
    return source_assets


def first_sentence(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip("# ").strip()
        if stripped:
            return stripped[:280]
    return "Project report"


def store_json_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str | None,
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


def store_text_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str | None,
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
