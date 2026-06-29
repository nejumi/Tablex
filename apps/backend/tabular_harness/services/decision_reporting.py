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
    Assumption,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Evidence,
    ExperimentRun,
    Insight,
    Job,
    ModelVersion,
    Project,
    Question,
    Report,
    SplitManifest,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.agent_task_results import list_agent_task_result_summaries
from tabular_harness.services.analysis_notebooks import build_project_notebook_index
from tabular_harness.services.approach import (
    decision_benchmark_context,
    decision_relational_context,
    first_sentence,
    latest_artifacts_by_type,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.reporting import leaderboard_sort_key


@dataclass(frozen=True)
class DecisionReportV1Result:
    report: Report
    report_artifact: Artifact
    bundle_artifact: Artifact
    evidence: Evidence
    bundle: dict[str, Any]


def create_decision_report_v1(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> DecisionReportV1Result:
    bundle = build_decision_report_bundle(db, project=project)
    markdown = render_decision_report_v1(bundle)
    bundle_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="decision_report_bundle",
        name=f"decision_report_bundle_{new_id('drb')}",
        filename="decision_report_bundle.json",
        payload=bundle,
        metadata={
            "project_id": project.id,
            "report_type": "decision_report_v1",
            "readiness_status": bundle["readiness"]["status"],
            "coverage_ready_count": bundle["coverage_summary"]["ready_count"],
            "coverage_attention_count": bundle["coverage_summary"]["attention_count"],
            "recommended_next_action": bundle["recommended_next_action"]["title"],
        },
    )
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="decision_report",
        name=f"decision_report_v1_{new_id('drptart')}",
        filename="decision_report.md",
        text=markdown,
        metadata={
            "project_id": project.id,
            "report_type": "decision_report_v1",
            "decision_report_bundle_artifact_id": bundle_artifact.id,
            "readiness_status": bundle["readiness"]["status"],
            "coverage_ready_count": bundle["coverage_summary"]["ready_count"],
            "coverage_attention_count": bundle["coverage_summary"]["attention_count"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="decision_report_v1",
        title=f"{project.name} Decision Report",
        summary=first_sentence(markdown),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(bundle["source_assets"]),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="decision_report",
        summary=(
            f"Decision report generated with {bundle['coverage_summary']['ready_count']} ready evidence areas "
            f"and {bundle['coverage_summary']['attention_count']} attention areas."
        ),
        strength="medium" if bundle["readiness"]["status"] == "needs_attention" else "strong",
        source_artifact_id=bundle_artifact.id,
        metadata_json=dumps_json(
            {
                "report_id": report.id,
                "report_artifact_id": report_artifact.id,
                "readiness_status": bundle["readiness"]["status"],
                "source_asset_count": len(bundle["source_assets"]),
            }
        ),
    )
    db.add(evidence)
    db.flush()
    _record_decision_report_lineage(
        db,
        project=project,
        report=report,
        report_artifact=report_artifact,
        bundle_artifact=bundle_artifact,
        evidence=evidence,
        source_assets=bundle["source_assets"],
    )
    _attach_report_ids_to_bundle_artifact(
        db,
        bundle_artifact=bundle_artifact,
        report=report,
        report_artifact=report_artifact,
        evidence=evidence,
    )
    return DecisionReportV1Result(
        report=report,
        report_artifact=report_artifact,
        bundle_artifact=bundle_artifact,
        evidence=evidence,
        bundle=bundle,
    )


def current_decision_report_payload(db: Session, *, project: Project) -> dict[str, Any]:
    report = db.scalar(
        select(Report)
        .where(Report.project_id == project.id, Report.report_type == "decision_report_v1")
        .order_by(Report.created_at.desc())
    )
    bundle_artifact = latest_project_artifact(db, project.id, "decision_report_bundle")
    if report is None and bundle_artifact is not None:
        metadata = artifact_metadata(bundle_artifact)
        report_id = string_value(metadata.get("report_id"))
        report = db.get(Report, report_id) if report_id else None
    report_artifact = db.get(Artifact, report.artifact_id) if report else None
    bundle = load_json_artifact(bundle_artifact)
    return {
        "schema_version": "decision_report_current.v1",
        "project_id": project.id,
        "available": bool(report and report_artifact and bundle_artifact and bundle),
        "generated_at": bundle.get("generated_at") if bundle else None,
        "report": report_ref(report) if report else None,
        "report_artifact": artifact_ref(report_artifact) if report_artifact else None,
        "bundle_artifact": artifact_ref(bundle_artifact) if bundle_artifact else None,
        "bundle": bundle or None,
        "action_endpoint": f"/api/projects/{project.id}/decision-report/generate",
    }


def build_decision_report_bundle(db: Session, *, project: Project) -> dict[str, Any]:
    generated_at = utc_now().isoformat()
    datasets = list(
        db.scalars(
            select(DatasetSnapshot)
            .where(DatasetSnapshot.project_id == project.id)
            .order_by(DatasetSnapshot.created_at.desc())
        ).all()
    )
    latest_dataset = datasets[0] if datasets else None
    assumptions = list(
        db.scalars(select(Assumption).where(Assumption.project_id == project.id).order_by(Assumption.updated_at.desc())).all()
    )
    questions = list(
        db.scalars(select(Question).where(Question.project_id == project.id).order_by(Question.created_at.desc())).all()
    )
    candidates = list(
        db.scalars(select(EvaluationCandidate).where(EvaluationCandidate.project_id == project.id)).all()
    )
    specs = list(
        db.scalars(select(EvaluationSpec).where(EvaluationSpec.project_id == project.id).order_by(EvaluationSpec.created_at.desc())).all()
    )
    splits = list(
        db.scalars(select(SplitManifest).where(SplitManifest.project_id == project.id).order_by(SplitManifest.created_at.desc())).all()
    )
    runs = list(db.scalars(select(ExperimentRun).where(ExperimentRun.project_id == project.id)).all())
    model_versions = list(
        db.scalars(select(ModelVersion).where(ModelVersion.project_id == project.id).order_by(ModelVersion.created_at.desc())).all()
    )
    reports = list(db.scalars(select(Report).where(Report.project_id == project.id).order_by(Report.created_at.desc())).all())
    insights = list(
        db.scalars(select(Insight).where(Insight.project_id == project.id).order_by(Insight.created_at.desc())).all()
    )
    visualizations = list(
        db.scalars(
            select(VisualizationSpec)
            .where(VisualizationSpec.project_id == project.id)
            .order_by(VisualizationSpec.created_at.desc())
        ).all()
    )
    artifacts = list(
        db.scalars(select(Artifact).where(Artifact.project_id == project.id).order_by(Artifact.created_at.desc())).all()
    )
    jobs = list(db.scalars(select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc())).all())
    artifacts_by_type = latest_artifacts_by_type(artifacts)
    notebook_index = build_project_notebook_index(db, project=project)
    agent_task_results = list_agent_task_result_summaries(db, project=project)
    data_review = build_data_review_section(artifacts_by_type, latest_dataset)
    assumption_section = build_assumption_section(assumptions, questions)
    evaluation_section = build_evaluation_section(candidates, specs, splits, artifacts_by_type)
    experiment_section = build_experiment_section(runs, model_versions, artifacts_by_type)
    notebook_section = build_notebook_section(notebook_index)
    runner_section = build_runner_section(agent_task_results, artifacts_by_type)
    citations_section = build_citations_section(artifacts_by_type)
    reporting_section = build_reporting_section(reports, visualizations, artifacts_by_type)
    benchmark_context = decision_benchmark_context(artifacts_by_type)
    relational_context = decision_relational_context(artifacts_by_type)
    evidence_map = build_evidence_map(
        data_review=data_review,
        assumption_section=assumption_section,
        evaluation_section=evaluation_section,
        experiment_section=experiment_section,
        notebook_section=notebook_section,
        runner_section=runner_section,
        citations_section=citations_section,
        reporting_section=reporting_section,
        benchmark_context=benchmark_context,
        relational_context=relational_context,
    )
    coverage_summary = coverage_summary_from_map(evidence_map)
    next_actions = build_decision_next_actions(
        latest_dataset=latest_dataset,
        assumption_section=assumption_section,
        evaluation_section=evaluation_section,
        experiment_section=experiment_section,
        notebook_section=notebook_section,
        runner_section=runner_section,
        citations_section=citations_section,
        relational_context=relational_context,
    )
    readiness = build_report_readiness(
        latest_dataset=latest_dataset,
        evaluation_section=evaluation_section,
        experiment_section=experiment_section,
        coverage_summary=coverage_summary,
        next_actions=next_actions,
    )
    source_assets = decision_report_source_assets(
        datasets=datasets,
        assumptions=assumptions,
        questions=questions,
        specs=specs,
        splits=splits,
        runs=runs,
        reports=reports,
        artifacts=artifacts,
    )
    return {
        "schema_version": "decision_report_bundle.v1",
        "generated_at": generated_at,
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "readiness": readiness,
        "recommended_next_action": next_actions[0],
        "next_actions": next_actions,
        "coverage_summary": coverage_summary,
        "evidence_map": evidence_map,
        "sections": {
            "data_review": data_review,
            "assumptions": assumption_section,
            "evaluation": evaluation_section,
            "experiments": experiment_section,
            "notebooks": notebook_section,
            "runner_results": runner_section,
            "citations": citations_section,
            "reporting": reporting_section,
            "benchmark": benchmark_context,
            "relational": relational_context,
        },
        "counts": {
            "datasets": len(datasets),
            "assumptions": len(assumptions),
            "questions": len(questions),
            "evaluation_candidates": len(candidates),
            "evaluation_specs": len(specs),
            "split_manifests": len(splits),
            "experiment_runs": len(runs),
            "model_versions": len(model_versions),
            "notebooks": notebook_section["notebook_count"],
            "runner_results": len(agent_task_results),
            "reports": len(reports),
            "visualizations": len(visualizations),
            "jobs": len(jobs),
            "artifacts": len(artifacts),
            "insights": len(insights),
        },
        "source_assets": source_assets,
        "human_reading_order": [
            "Decision State",
            "Evidence Map",
            "Data Review",
            "Evaluation Design",
            "Experiments and Model Evidence",
            "Notebook Evidence",
            "Runner Results and Citations",
            "Next Actions",
        ],
        "safety": {
            "external_dashboards_required": False,
            "connector_credentials_materialized": citations_section["connector_credentials_materialized"],
            "secret_values_included": False,
            "evaluation_spec_destructively_changed": False,
        },
    }


def build_data_review_section(
    artifacts_by_type: dict[str, Artifact],
    latest_dataset: DatasetSnapshot | None,
) -> dict[str, Any]:
    review_artifact = artifacts_by_type.get("eda_review_bundle")
    profile_artifact = artifacts_by_type.get("eda_profile")
    quality_artifact = artifacts_by_type.get("data_quality_gate")
    review = load_json_artifact(review_artifact)
    profile = load_json_artifact(profile_artifact)
    quality = load_json_artifact(quality_artifact)
    findings = list_value(review.get("findings")) or list_value(quality.get("findings"))
    story_cards = list_value(review.get("story_cards")) or list_value(review.get("visual_story_cards"))
    quality_score = review.get("quality_score") or quality.get("quality_score")
    target_profile = review.get("target_profile") if isinstance(review.get("target_profile"), dict) else {}
    if not target_profile:
        target_profile = profile.get("target_profile") if isinstance(profile.get("target_profile"), dict) else {}
    status = "ready" if review_artifact else "partial" if profile_artifact or quality_artifact else "missing"
    return {
        "status": status,
        "dataset_snapshot_id": latest_dataset.id if latest_dataset else None,
        "row_count": latest_dataset.row_count if latest_dataset else profile.get("row_count"),
        "column_count": latest_dataset.column_count if latest_dataset else profile.get("column_count"),
        "profile_boundary": review.get("profile_boundary") or profile.get("profile_boundary") or {},
        "quality_score": quality_score,
        "target_profile": target_profile,
        "top_findings": [compact_finding(item) for item in findings[:6]],
        "story_cards": [compact_story_card(item) for item in story_cards[:4]],
        "artifact_refs": compact_artifact_refs(
            {
                "eda_review_bundle": review_artifact,
                "eda_profile": profile_artifact,
                "data_quality_gate": quality_artifact,
                "eda_review_report": artifacts_by_type.get("eda_review_report"),
                "eda_review_html": artifacts_by_type.get("eda_review_html"),
            }
        ),
        "human_summary": data_review_summary(status, latest_dataset, findings, quality_score),
    }


def build_assumption_section(assumptions: list[Assumption], questions: list[Question]) -> dict[str, Any]:
    high_risk = [
        assumption
        for assumption in assumptions
        if assumption.risk_level in {"high", "blocking", "deployment_blocking"} or assumption.status in {"challenged", "needs_review"}
    ]
    blocking_questions = [question for question in questions if question.fallback_policy == "block_until_answered"]
    open_questions = [question for question in questions if question.status == "open"]
    status = "ready"
    if high_risk or blocking_questions:
        status = "needs_attention"
    elif not assumptions and not questions:
        status = "missing"
    return {
        "status": status,
        "assumption_count": len(assumptions),
        "high_risk_count": len(high_risk),
        "open_question_count": len(open_questions),
        "blocking_question_count": len(blocking_questions),
        "top_assumptions": [
            {
                "id": item.id,
                "topic": item.topic,
                "statement": item.statement,
                "risk_level": item.risk_level,
                "confidence": item.confidence,
                "fallback_policy": item.fallback_policy,
                "status": item.status,
            }
            for item in high_risk[:8]
        ],
        "top_questions": [
            {
                "id": item.id,
                "topic": item.topic,
                "question": item.question,
                "risk_level": item.risk_level,
                "fallback_policy": item.fallback_policy,
                "can_proceed_without_answer": item.can_proceed_without_answer,
                "status": item.status,
            }
            for item in open_questions[:6]
        ],
        "human_summary": assumption_summary(assumptions, high_risk, open_questions),
    }


def build_evaluation_section(
    candidates: list[EvaluationCandidate],
    specs: list[EvaluationSpec],
    splits: list[SplitManifest],
    artifacts_by_type: dict[str, Artifact],
) -> dict[str, Any]:
    approved_spec = next((item for item in specs if item.status == "approved"), None)
    latest_split = splits[0] if splits else None
    status = "ready" if approved_spec and latest_split else "needs_attention" if candidates or specs else "missing"
    comparison_artifact = artifacts_by_type.get("evaluation_scenario_comparison")
    approval_artifact = artifacts_by_type.get("evaluation_approval_review")
    return {
        "status": status,
        "candidate_count": len(candidates),
        "approved_spec": evaluation_spec_ref(approved_spec),
        "latest_split": split_ref(latest_split),
        "comparison_artifact": artifact_ref(comparison_artifact),
        "approval_artifact": artifact_ref(approval_artifact),
        "primary_metric": approved_spec.primary_metric if approved_spec else None,
        "split_type": approved_spec.split_type if approved_spec else None,
        "excluded_columns": list_value(loads_json(approved_spec.excluded_columns_json, [])) if approved_spec else [],
        "human_summary": evaluation_summary(candidates, approved_spec, latest_split),
    }


def build_experiment_section(
    runs: list[ExperimentRun],
    model_versions: list[ModelVersion],
    artifacts_by_type: dict[str, Artifact],
) -> dict[str, Any]:
    succeeded = [run for run in runs if run.status == "succeeded"]
    best_run = sorted(succeeded, key=leaderboard_sort_key)[0] if succeeded else None
    best_metrics = loads_json(best_run.metrics_json, {}) if best_run else {}
    diagnostics_artifact = artifacts_by_type.get("evaluation_diagnostics")
    prediction_artifact = artifacts_by_type.get("prediction_output")
    validation_artifact = artifacts_by_type.get("model_validation_report")
    status = "ready" if best_run and diagnostics_artifact else "partial" if best_run else "missing"
    return {
        "status": status,
        "run_count": len(runs),
        "succeeded_run_count": len(succeeded),
        "model_version_count": len(model_versions),
        "best_run": run_ref(best_run),
        "best_metrics": best_metrics,
        "diagnostics_artifact": artifact_ref(diagnostics_artifact),
        "prediction_artifact": artifact_ref(prediction_artifact),
        "validation_artifact": artifact_ref(validation_artifact),
        "human_summary": experiment_summary(best_run, best_metrics, diagnostics_artifact),
    }


def build_notebook_section(notebook_index: dict[str, Any]) -> dict[str, Any]:
    counts = dict_value(notebook_index.get("counts"))
    recommended = dict_value(notebook_index.get("recommended_notebook"))
    items = list_value(notebook_index.get("items"))
    has_capture = int(counts.get("with_execution_capture") or 0) > 0
    has_notebook = int(counts.get("total") or 0) > 0
    content_quality = recommended.get("content_quality_score")
    status = "ready" if has_capture else "partial" if has_notebook else "missing"
    if isinstance(content_quality, (int, float)) and content_quality < 50:
        status = "needs_attention"
    return {
        "status": status,
        "notebook_count": int(counts.get("total") or len(items)),
        "captured_count": int(counts.get("with_execution_capture") or 0),
        "html_preview_count": int(counts.get("with_html_preview") or 0),
        "recommended_notebook": recommended or None,
        "next_actions": list_value(notebook_index.get("next_actions"))[:5],
        "human_summary": notebook_summary(status, recommended, counts),
    }


def build_runner_section(
    agent_task_results: list[dict[str, Any]],
    artifacts_by_type: dict[str, Artifact],
) -> dict[str, Any]:
    successful = [item for item in agent_task_results if item.get("agent_status") == "succeeded"]
    latest = agent_task_results[0] if agent_task_results else None
    latest_contract = artifacts_by_type.get("agent_task_contract")
    status = "ready" if successful else "partial" if agent_task_results or latest_contract else "missing"
    return {
        "status": status,
        "result_count": len(agent_task_results),
        "successful_count": len(successful),
        "latest_result": latest,
        "latest_contract_artifact": artifact_ref(latest_contract),
        "human_summary": runner_summary(status, latest, successful),
    }


def build_citations_section(artifacts_by_type: dict[str, Artifact]) -> dict[str, Any]:
    citation_manifest_artifact = artifacts_by_type.get("source_citation_manifest")
    citation_report_artifact = artifacts_by_type.get("citation_audit_report")
    manifest = load_json_artifact(citation_manifest_artifact)
    citations = list_value(manifest.get("citations"))
    evidence_sources = list_value(manifest.get("evidence_sources"))
    external_network_accessed = bool(manifest.get("external_network_accessed"))
    credentials_materialized = bool(manifest.get("connector_credentials_materialized"))
    status = "ready" if citations and not credentials_materialized else "needs_attention" if credentials_materialized else "missing"
    return {
        "status": status,
        "citation_count": len(citations),
        "source_count": len(evidence_sources),
        "external_network_accessed": external_network_accessed,
        "connector_credentials_materialized": credentials_materialized,
        "citation_manifest_artifact": artifact_ref(citation_manifest_artifact),
        "citation_report_artifact": artifact_ref(citation_report_artifact),
        "sample_citations": citations[:5],
        "human_summary": citation_summary(status, citations, external_network_accessed, credentials_materialized),
    }


def build_reporting_section(
    reports: list[Report],
    visualizations: list[VisualizationSpec],
    artifacts_by_type: dict[str, Artifact],
) -> dict[str, Any]:
    report_refs = [report_ref(report) for report in reports[:12]]
    visualization_refs = [visualization_ref(visualization) for visualization in visualizations[:12]]
    status = "ready" if reports else "missing"
    return {
        "status": status,
        "report_count": len(reports),
        "visualization_count": len(visualizations),
        "latest_reports": report_refs,
        "latest_visualizations": visualization_refs,
        "decision_dashboard": artifact_ref(artifacts_by_type.get("decision_dashboard")),
        "human_summary": (
            f"{len(reports)} artifact-backed reports and {len(visualizations)} visualization specs are available."
            if reports
            else "No prior report artifacts are available; this decision report is the first reading surface."
        ),
    }


def build_evidence_map(**sections: Any) -> list[dict[str, Any]]:
    rows = [
        evidence_row("Data Review", sections["data_review"], "Shape, quality, target, and finding evidence."),
        evidence_row("Assumptions", sections["assumption_section"], "Explicit uncertainty and fallback policies."),
        evidence_row("Evaluation", sections["evaluation_section"], "Approved metric, split, and evaluation guardrails."),
        evidence_row("Experiments", sections["experiment_section"], "Run metrics, diagnostics, predictions, and model packages."),
        evidence_row("Notebooks", sections["notebook_section"], "Narrative analysis and figure evidence that humans can inspect."),
        evidence_row("Runner Results", sections["runner_section"], "Codex/runner contracts, outputs, and handoff state."),
        evidence_row("Citations", sections["citations_section"], "Source and citation audit for external or timely claims."),
        evidence_row("Reports", sections["reporting_section"], "Artifact-backed summaries and visualizations."),
        context_row("Benchmark", sections["benchmark_context"], "Benchmark intent, fixture policy, and source context."),
        context_row("Relational", sections["relational_context"], "Multi-table plan, recipe preview, and deferred safety checks."),
    ]
    return rows


def evidence_row(name: str, section: dict[str, Any], why: str) -> dict[str, Any]:
    status = str(section.get("status") or "missing")
    return {
        "area": name,
        "status": status,
        "summary": section.get("human_summary") or "-",
        "why_it_matters": why,
        "primary_artifact_id": primary_artifact_id(section),
    }


def context_row(name: str, context: dict[str, Any], why: str) -> dict[str, Any]:
    raw_status = str(context.get("status") or "missing")
    status = "ready" if raw_status in {"available", "ready_for_agent_review"} else raw_status
    if raw_status in {"not_present", "needs_plan", "needs_recipe", "needs_diagnostics"}:
        status = "partial" if raw_status != "not_present" else "missing"
    return {
        "area": name,
        "status": status,
        "summary": context.get("detail") or context.get("fixture_policy") or raw_status,
        "why_it_matters": why,
        "primary_artifact_id": (
            context.get("artifact_id")
            or context.get("diagnostics_artifact_id")
            or context.get("recipe_artifact_id")
            or context.get("plan_artifact_id")
        ),
    }


def coverage_summary_from_map(evidence_map: list[dict[str, Any]]) -> dict[str, Any]:
    ready_count = sum(1 for item in evidence_map if item["status"] == "ready")
    attention_count = sum(1 for item in evidence_map if item["status"] in {"needs_attention", "blocked", "partial"})
    missing_count = sum(1 for item in evidence_map if item["status"] == "missing")
    return {
        "ready_count": ready_count,
        "attention_count": attention_count,
        "missing_count": missing_count,
        "total": len(evidence_map),
    }


def build_decision_next_actions(
    *,
    latest_dataset: DatasetSnapshot | None,
    assumption_section: dict[str, Any],
    evaluation_section: dict[str, Any],
    experiment_section: dict[str, Any],
    notebook_section: dict[str, Any],
    runner_section: dict[str, Any],
    citations_section: dict[str, Any],
    relational_context: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if latest_dataset is None:
        actions.append(action(100, "Import or upload data", "A decision report cannot be evidence-backed without a DatasetSnapshot.", "Data"))
    if assumption_section["status"] == "needs_attention":
        actions.append(action(95, "Review high-risk assumptions", "Open assumptions or questions can invalidate evaluation and features.", "Assumptions"))
    if evaluation_section["status"] != "ready":
        actions.append(action(90, "Approve evaluation and build split", "Experiments must be judged against a stable EvaluationSpec and SplitManifest.", "Evaluation"))
    if experiment_section["status"] == "missing":
        actions.append(action(85, "Run a real baseline or agent experiment", "The report has no model evidence to compare or diagnose.", "Experiments"))
    elif experiment_section["status"] == "partial":
        actions.append(action(82, "Generate run diagnostics", "Metrics need diagnostics, slices, and prediction evidence before decision use.", "Experiments"))
    if notebook_section["status"] in {"missing", "partial", "needs_attention"}:
        actions.append(action(75, "Generate or capture notebook evidence", "Human-readable analysis should sit next to model evidence in Tablex.", "Notebooks"))
    if runner_section["status"] == "missing":
        actions.append(action(68, "Prepare a controlled Codex runner task", "Use Codex for flexible approach selection while preserving harness evidence boundaries.", "Approach"))
    if citations_section["status"] != "ready":
        actions.append(action(62, "Attach citation-backed research or record no external claims", "Decision-grade reports should cite external or timely claims.", "Approach"))
    if relational_context.get("status") in {"needs_plan", "needs_recipe", "needs_diagnostics", "ready_with_deferred_risks"}:
        actions.append(action(58, "Review relational feature safety", "Multi-table features need prediction-time availability and split discipline checks.", "Data"))
    if not actions:
        actions.append(
            action(40, "Hold a human decision review", "Core evidence is present; review tradeoffs before deployment or deeper agent work.", "Reports")
        )
    return actions[:8]


def build_report_readiness(
    *,
    latest_dataset: DatasetSnapshot | None,
    evaluation_section: dict[str, Any],
    experiment_section: dict[str, Any],
    coverage_summary: dict[str, Any],
    next_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    if latest_dataset is None:
        blockers.append("DatasetSnapshot is missing.")
    if evaluation_section["status"] != "ready":
        blockers.append("Approved EvaluationSpec and SplitManifest are not both present.")
    if experiment_section["status"] == "missing":
        blockers.append("No successful experiment evidence is available.")
    if blockers:
        status = "blocked"
    elif coverage_summary["attention_count"] or coverage_summary["missing_count"]:
        status = "needs_attention"
    else:
        status = "ready_for_review"
    return {
        "status": status,
        "headline": readiness_headline(status),
        "blockers": blockers,
        "ready_evidence_areas": coverage_summary["ready_count"],
        "attention_evidence_areas": coverage_summary["attention_count"],
        "missing_evidence_areas": coverage_summary["missing_count"],
        "recommended_next_action": next_actions[0]["title"],
    }


def render_decision_report_v1(bundle: dict[str, Any]) -> str:
    project = bundle["project"]
    sections = bundle["sections"]
    lines = [
        f"# {project['name']} Decision Report",
        "",
        "> Artifact-backed executive report generated inside Tablex. It is intended to be readable without opening external dashboards.",
        "",
        "## Decision State",
        "",
        f"- Verdict: {bundle['readiness']['headline']}",
        f"- Status: `{bundle['readiness']['status']}`",
        f"- Target: {project.get('target_column') or 'not set'}",
        f"- Task type: {project.get('task_type') or 'not set'}",
        f"- Generated at: {bundle['generated_at']}",
        f"- Recommended next action: {bundle['recommended_next_action']['title']}",
        "",
        "### What Is Proven",
        "",
    ]
    ready_rows = [row for row in bundle["evidence_map"] if row["status"] == "ready"]
    if ready_rows:
        for row in ready_rows[:6]:
            lines.append(f"- {row['area']}: {row['summary']}")
    else:
        lines.append("- No evidence area is fully ready yet.")
    lines.extend(["", "### What Still Needs Attention", ""])
    attention_rows = [row for row in bundle["evidence_map"] if row["status"] != "ready"]
    if attention_rows:
        for row in attention_rows[:8]:
            lines.append(f"- {row['area']} (`{row['status']}`): {row['summary']}")
    else:
        lines.append("- No immediate attention item was generated.")
    lines.extend(["", "## Evidence Map", "", "| Area | Status | Evidence | Why it matters |", "| --- | --- | --- | --- |"])
    for row in bundle["evidence_map"]:
        lines.append(
            f"| {markdown_cell(row['area'])} | `{markdown_cell(row['status'])}` | "
            f"{markdown_cell(row['summary'])} | {markdown_cell(row['why_it_matters'])} |"
        )
    lines.extend(["", "## Data Review", "", sections["data_review"]["human_summary"]])
    add_key_values(
        lines,
        {
            "Rows": sections["data_review"].get("row_count"),
            "Columns": sections["data_review"].get("column_count"),
            "Quality score": sections["data_review"].get("quality_score"),
            "Profile boundary": compact_json(sections["data_review"].get("profile_boundary")),
        },
    )
    add_list_section(lines, "Top Findings", [finding["summary"] for finding in sections["data_review"]["top_findings"]])
    add_list_section(lines, "Visual Story Cards", [card["title"] for card in sections["data_review"]["story_cards"]])
    lines.extend(["", "## Assumptions And Questions", "", sections["assumptions"]["human_summary"]])
    add_key_values(
        lines,
        {
            "Assumptions": sections["assumptions"]["assumption_count"],
            "High risk": sections["assumptions"]["high_risk_count"],
            "Open questions": sections["assumptions"]["open_question_count"],
            "Blocking questions": sections["assumptions"]["blocking_question_count"],
        },
    )
    add_list_section(
        lines,
        "Risk Queue",
        [
            f"{item['risk_level']}: {item['statement']} (fallback: {item['fallback_policy']})"
            for item in sections["assumptions"]["top_assumptions"]
        ],
    )
    lines.extend(["", "## Evaluation Design", "", sections["evaluation"]["human_summary"]])
    approved = sections["evaluation"].get("approved_spec") or {}
    latest_split = sections["evaluation"].get("latest_split") or {}
    add_key_values(
        lines,
        {
            "Primary metric": sections["evaluation"].get("primary_metric"),
            "Split type": sections["evaluation"].get("split_type"),
            "EvaluationSpec": approved.get("id"),
            "SplitManifest": latest_split.get("id"),
            "Excluded columns": ", ".join(str(item) for item in sections["evaluation"].get("excluded_columns", [])[:8]),
        },
    )
    lines.extend(["", "## Experiments And Model Evidence", "", sections["experiments"]["human_summary"]])
    best_run = sections["experiments"].get("best_run") or {}
    add_key_values(
        lines,
        {
            "Best run": best_run.get("id"),
            "Runner": best_run.get("runner_type"),
            "Succeeded runs": sections["experiments"]["succeeded_run_count"],
            "Model versions": sections["experiments"]["model_version_count"],
        },
    )
    add_metric_lines(lines, sections["experiments"].get("best_metrics", {}))
    lines.extend(["", "## Notebook Evidence", "", sections["notebooks"]["human_summary"]])
    recommended = sections["notebooks"].get("recommended_notebook") or {}
    add_key_values(
        lines,
        {
            "Notebooks": sections["notebooks"]["notebook_count"],
            "Captured": sections["notebooks"]["captured_count"],
            "Recommended notebook": recommended.get("title"),
            "Recommendation reason": recommended.get("recommendation_reason"),
        },
    )
    lines.extend(["", "## Runner Results And Citations", "", sections["runner_results"]["human_summary"]])
    add_key_values(
        lines,
        {
            "Runner results": sections["runner_results"]["result_count"],
            "Successful runner results": sections["runner_results"]["successful_count"],
            "Citations": sections["citations"]["citation_count"],
            "Evidence sources": sections["citations"]["source_count"],
            "External network accessed": str(sections["citations"]["external_network_accessed"]).lower(),
            "Connector credentials materialized": str(sections["citations"]["connector_credentials_materialized"]).lower(),
        },
    )
    add_list_section(
        lines,
        "Citation Samples",
        [
            f"{item.get('citation_id') or item.get('id')}: {item.get('title') or item.get('summary') or item.get('url')}"
            for item in sections["citations"].get("sample_citations", [])
            if isinstance(item, dict)
        ],
    )
    lines.extend(["", "## Relational And Benchmark Context", ""])
    add_key_values(
        lines,
        {
            "Benchmark status": sections["benchmark"].get("status"),
            "Benchmark policy": sections["benchmark"].get("fixture_policy"),
            "Relational status": sections["relational"].get("status"),
            "Relational detail": sections["relational"].get("detail"),
            "Usable preview features": sections["relational"].get("usable_feature_count"),
            "Deferred relational steps": sections["relational"].get("deferred_step_count"),
        },
    )
    lines.extend(["", "## Next Actions", ""])
    for item in bundle["next_actions"]:
        lines.append(f"- P{item['priority']} [{item['target_tab']}] {item['title']}: {item['reason']}")
    lines.extend(["", "## Source Artifacts", ""])
    for source in bundle["source_assets"][:30]:
        label = f"{source['asset_type']}:{source['asset_id']}"
        detail = source.get("label") or source.get("role") or ""
        lines.append(f"- `{label}` {detail}".rstrip())
    lines.extend(["", "## Safety Boundaries", ""])
    for key, value in bundle["safety"].items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    return "\n".join(lines).strip() + "\n"


def decision_report_source_assets(
    *,
    datasets: list[DatasetSnapshot],
    assumptions: list[Assumption],
    questions: list[Question],
    specs: list[EvaluationSpec],
    splits: list[SplitManifest],
    runs: list[ExperimentRun],
    reports: list[Report],
    artifacts: list[Artifact],
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    sources.extend({"asset_type": "dataset_snapshot", "asset_id": item.id, "label": "DatasetSnapshot"} for item in datasets[:3])
    sources.extend({"asset_type": "assumption", "asset_id": item.id, "label": item.topic} for item in assumptions[:8])
    sources.extend({"asset_type": "question", "asset_id": item.id, "label": item.topic or "question"} for item in questions[:8])
    sources.extend({"asset_type": "evaluation_spec", "asset_id": item.id, "label": item.name} for item in specs[:3])
    sources.extend({"asset_type": "split_manifest", "asset_id": item.id, "label": "SplitManifest"} for item in splits[:3])
    sources.extend({"asset_type": "experiment_run", "asset_id": item.id, "label": item.runner_type} for item in runs[:5])
    sources.extend(
        {"asset_type": "report", "asset_id": item.id, "label": item.report_type}
        for item in reports[:8]
        if item.report_type != "decision_report_v1"
    )
    important_types = {
        "eda_review_bundle",
        "eda_review_report",
        "data_quality_gate",
        "evaluation_scenario_comparison",
        "evaluation_approval_review",
        "baseline_strategy_plan",
        "baseline_metrics",
        "baseline_report",
        "evaluation_diagnostics",
        "run_report",
        "notebook_evidence_bundle",
        "notebook_evidence_html",
        "source_citation_manifest",
        "citation_audit_report",
        "agent_task_contract",
        "relational_feature_plan",
        "relational_feature_recipe",
        "relational_feature_scenario_diagnostics",
        "benchmark_scenario_pack",
        "decision_dashboard",
        "visualization_spec",
    }
    sources.extend(
        {"asset_type": item.asset_type, "asset_id": item.id, "label": item.name}
        for item in artifacts
        if item.asset_type in important_types
    )
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["asset_type"], source["asset_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped[:60]


def _record_decision_report_lineage(
    db: Session,
    *,
    project: Project,
    report: Report,
    report_artifact: Artifact,
    bundle_artifact: Artifact,
    evidence: Evidence,
    source_assets: list[dict[str, str]],
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="project",
        from_asset_id=project.id,
        to_asset_type="artifact",
        to_asset_id=bundle_artifact.id,
        relation_type="summarizes_decision_state",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=bundle_artifact.id,
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
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=bundle_artifact.id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
    for source in source_assets[:60]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type=source["asset_type"],
            from_asset_id=source["asset_id"],
            to_asset_type="artifact",
            to_asset_id=bundle_artifact.id,
            relation_type="informs",
        )


def _attach_report_ids_to_bundle_artifact(
    db: Session,
    *,
    bundle_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    evidence: Evidence,
) -> None:
    metadata = artifact_metadata(bundle_artifact)
    metadata.update(
        {
            "report_id": report.id,
            "report_artifact_id": report_artifact.id,
            "evidence_id": evidence.id,
        }
    )
    bundle_artifact.metadata_json = dumps_json(metadata)
    db.flush()


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def load_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        payload = json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def artifact_metadata(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    return cast(dict[str, Any], loads_json(artifact.metadata_json, {}))


def compact_artifact_refs(items: dict[str, Artifact | None]) -> dict[str, dict[str, Any] | None]:
    return {key: artifact_ref(value) for key, value in items.items()}


def artifact_ref(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "created_at": artifact.created_at.isoformat(),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def report_ref(report: Report | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "id": report.id,
        "project_id": report.project_id,
        "report_type": report.report_type,
        "title": report.title,
        "summary": report.summary,
        "artifact_id": report.artifact_id,
        "status": report.status,
        "created_at": report.created_at.isoformat(),
    }


def visualization_ref(visualization: VisualizationSpec) -> dict[str, Any]:
    return {
        "id": visualization.id,
        "title": visualization.title,
        "chart_type": visualization.chart_type,
        "artifact_id": visualization.artifact_id,
        "status": visualization.status,
        "created_at": visualization.created_at.isoformat(),
    }


def evaluation_spec_ref(spec: EvaluationSpec | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    return {
        "id": spec.id,
        "name": spec.name,
        "status": spec.status,
        "split_type": spec.split_type,
        "primary_metric": spec.primary_metric,
        "risk_level": spec.risk_level,
    }


def split_ref(split: SplitManifest | None) -> dict[str, Any] | None:
    if split is None:
        return None
    return {
        "id": split.id,
        "evaluation_spec_id": split.evaluation_spec_id,
        "train_count": split.train_count,
        "valid_count": split.valid_count,
        "test_count": split.test_count,
        "artifact_id": split.artifact_id,
    }


def run_ref(run: ExperimentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    metrics = loads_json(run.metrics_json, {})
    return {
        "id": run.id,
        "runner_type": run.runner_type,
        "status": run.status,
        "model_version_id": run.model_version_id,
        "primary_metric_name": metrics.get("primary_metric_name"),
        "primary_metric_value": metrics.get("primary_metric_value"),
    }


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def string_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def primary_artifact_id(section: dict[str, Any]) -> str | None:
    for key in [
        "diagnostics_artifact",
        "prediction_artifact",
        "citation_manifest_artifact",
        "latest_contract_artifact",
        "decision_dashboard",
        "comparison_artifact",
        "approval_artifact",
    ]:
        value = section.get(key)
        if isinstance(value, dict) and value.get("id"):
            return str(value["id"])
    refs = section.get("artifact_refs")
    if isinstance(refs, dict):
        for value in refs.values():
            if isinstance(value, dict) and value.get("id"):
                return str(value["id"])
    return None


def compact_finding(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"summary": str(item)}
    return {
        "title": item.get("title") or item.get("finding") or item.get("name") or item.get("severity") or "Finding",
        "summary": item.get("summary") or item.get("detail") or item.get("message") or item.get("finding") or str(item),
        "severity": item.get("severity") or item.get("risk_level") or "info",
    }


def compact_story_card(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": str(item), "detail": ""}
    return {
        "title": item.get("title") or item.get("headline") or item.get("name") or "Story card",
        "detail": item.get("detail") or item.get("summary") or item.get("body") or "",
    }


def data_review_summary(
    status: str,
    latest_dataset: DatasetSnapshot | None,
    findings: list[Any],
    quality_score: Any,
) -> str:
    if status == "missing":
        return "No Data Review or profile artifact is available yet."
    shape = (
        f"{latest_dataset.row_count or 'unknown'} rows and {latest_dataset.column_count or 'unknown'} columns"
        if latest_dataset
        else "profile-backed shape"
    )
    score = f" Quality score is {quality_score}." if quality_score is not None else ""
    return f"Data Review is {status}: {shape}; {len(findings)} findings are available.{score}"


def assumption_summary(assumptions: list[Assumption], high_risk: list[Assumption], open_questions: list[Question]) -> str:
    if not assumptions and not open_questions:
        return "No assumptions or questions have been registered yet."
    if high_risk:
        return f"{len(high_risk)} high-risk assumptions require explicit review before decision use."
    if open_questions:
        return f"{len(open_questions)} open questions remain, but no high-risk assumption is currently registered."
    return f"{len(assumptions)} assumptions are tracked without a high-risk item in the current queue."


def evaluation_summary(
    candidates: list[EvaluationCandidate],
    approved_spec: EvaluationSpec | None,
    latest_split: SplitManifest | None,
) -> str:
    if approved_spec and latest_split:
        return (
            f"Evaluation is locked on `{approved_spec.primary_metric}` with `{approved_spec.split_type}` split "
            f"and SplitManifest `{latest_split.id}`."
        )
    if candidates:
        return f"{len(candidates)} EvaluationCandidates exist, but the primary EvaluationSpec/SplitManifest pair is incomplete."
    return "No evaluation candidates exist yet."


def experiment_summary(best_run: ExperimentRun | None, metrics: dict[str, Any], diagnostics_artifact: Artifact | None) -> str:
    if best_run is None:
        return "No successful experiment run is available."
    metric_name = metrics.get("primary_metric_name", "primary_metric")
    metric_value = metrics.get("primary_metric_value", "-")
    diagnostic_text = " Diagnostics are available." if diagnostics_artifact else " Diagnostics are still missing."
    return f"Best run `{best_run.id}` reports {metric_name}={metric_value}.{diagnostic_text}"


def notebook_summary(status: str, recommended: dict[str, Any], counts: dict[str, Any]) -> str:
    total = int(counts.get("total") or 0)
    captured = int(counts.get("with_execution_capture") or 0)
    if total == 0:
        return "No analysis notebook evidence is available yet."
    title = recommended.get("title") or "recommended notebook"
    return f"Notebook evidence is {status}: {total} notebooks exist, {captured} have capture evidence, and `{title}` is recommended."


def runner_summary(status: str, latest: dict[str, Any] | None, successful: list[dict[str, Any]]) -> str:
    if latest is None:
        return "No AgentRunner result has been ingested yet."
    task = latest.get("task_id") or latest.get("job_id") or "latest runner task"
    return f"Runner evidence is {status}: {len(successful)} successful results; latest task is `{task}`."


def citation_summary(status: str, citations: list[Any], network: bool, credentials: bool) -> str:
    if not citations:
        return "No citation manifest is available for external or timely claims."
    return (
        f"Citation evidence is {status}: {len(citations)} citations recorded; "
        f"external network accessed={str(network).lower()}, credentials materialized={str(credentials).lower()}."
    )


def readiness_headline(status: str) -> str:
    return {
        "ready_for_review": "Ready for human decision review",
        "needs_attention": "Evidence exists, but attention is required before decision use",
        "blocked": "Decision-grade reporting is blocked by missing core evidence",
    }.get(status, "Decision state requires review")


def action(priority: int, title: str, reason: str, target_tab: str) -> dict[str, Any]:
    return {
        "priority": priority,
        "title": title,
        "reason": reason,
        "target_tab": target_tab,
        "action_type": "navigate",
    }


def markdown_cell(value: Any) -> str:
    text = str(value or "-").replace("\n", " ").replace("|", "\\|")
    return " ".join(text.split())


def compact_json(value: Any) -> str:
    if not value:
        return "-"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:240]


def add_key_values(lines: list[str], values: dict[str, Any]) -> None:
    lines.append("")
    for key, value in values.items():
        rendered = "-" if value is None or value == "" else value
        lines.append(f"- {key}: {rendered}")


def add_list_section(lines: list[str], title: str, items: list[str]) -> None:
    lines.extend(["", f"### {title}", ""])
    if items:
        for item in items:
            lines.append(f"- {item}")
    else:
        lines.append("- No item is available yet.")


def add_metric_lines(lines: list[str], metrics: dict[str, Any]) -> None:
    display_keys = [
        "primary_metric_name",
        "primary_metric_value",
        "roc_auc",
        "pr_auc",
        "log_loss",
        "rmse",
        "mae",
        "accuracy",
        "feature_count",
        "train_count",
        "valid_count",
    ]
    lines.extend(["", "### Metrics", ""])
    added = False
    for key in display_keys:
        if key in metrics:
            lines.append(f"- {key}: {metrics[key]}")
            added = True
    if not added:
        lines.append("- No metric payload is available.")
