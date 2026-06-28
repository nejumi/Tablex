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
    Report,
    ResearchBrief,
    SemanticCatalog,
    VisualizationSpec,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
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
    sources = build_research_sources(project, dataset, evaluation_spec, research_plan_artifact)
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
        "evaluation_scenario_comparison": latest_project_artifact(db, project.id, "evaluation_scenario_comparison"),
        "evaluation_approval_review": latest_project_artifact(db, project.id, "evaluation_approval_review"),
        "baseline_strategy_plan": latest_project_artifact(db, project.id, "baseline_strategy_plan"),
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
    source_asset_ids = build_report_source_assets(datasets=list(datasets), ideas=list(ideas), runs=list(runs))
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
    for asset in asset_context:
        semantic_tags = {str(tag) for tag in asset.get("semantic_tags", [])}
        asset_type = str(asset.get("asset_type"))
        reason = None
        if "controlled_research" in semantic_tags or asset_type == "skill":
            reason = "Use to guide controlled research and source-backed approach selection."
        elif "split_manifest" in semantic_tags and context_artifacts.get("evaluation_scenario_comparison"):
            reason = "Use to compare feature scenarios under stable evaluation constraints."
        elif "text_features" in semantic_tags and profile.get("has_text"):
            reason = "Text-like columns are present."
        elif "leakage_control" in semantic_tags:
            reason = "Leakage and prediction-time availability controls are always relevant."
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
) -> dict[str, Any]:
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
            "approach_type": approach["approach_type"],
            "allowed_research_modes": ["project_artifacts", "skill_library", "controlled_web_search"],
            "must_respect_split_manifest": True,
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
) -> list[dict[str, str]]:
    source_assets: list[dict[str, str]] = []
    source_assets.extend({"asset_type": "dataset_snapshot", "asset_id": dataset.id} for dataset in datasets[:5])
    source_assets.extend({"asset_type": "idea", "asset_id": idea.id} for idea in ideas[:10])
    source_assets.extend({"asset_type": "experiment_run", "asset_id": run.id} for run in runs[:10])
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
