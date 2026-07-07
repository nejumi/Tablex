from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, ExperimentRun, Project
from tabular_harness.services.decision_reporting import (
    artifact_ref,
    build_decision_report_bundle,
    current_decision_report_payload,
    latest_project_artifact,
)
from tabular_harness.services.reporting import leaderboard_sort_key


def build_result_readout(db: Session, *, project: Project) -> dict[str, Any]:
    runs = list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project.id, ExperimentRun.status == "succeeded")
            .order_by(ExperimentRun.started_at.desc())
        ).all()
    )
    ranked_runs = sorted(runs, key=leaderboard_sort_key)
    top_run = ranked_runs[0] if ranked_runs else None
    bundle = build_decision_report_bundle(db, project=project)
    decision_report = current_decision_report_payload(db, project=project)
    sections = bundle["sections"]
    experiment_section = sections["experiments"]
    evaluation_section = sections["evaluation"]
    notebook_section = sections["notebooks"]
    coverage = bundle["coverage_summary"]
    comparison_artifact = latest_project_artifact(db, project.id, "experiment_comparison")
    comparison_report_artifact = latest_project_artifact(db, project.id, "experiment_comparison_report")
    diagnostics_artifact = latest_diagnostics_for_run(db, project.id, top_run.id) if top_run else None
    diagnostics_report_artifact = latest_diagnostics_report_for_run(db, project.id, top_run.id) if top_run else None
    top_run_ref = run_readout_ref(top_run)
    status = result_status(
        has_top_run=top_run is not None,
        evaluation_status=str(evaluation_section.get("status") or "missing"),
        experiment_status=str(experiment_section.get("status") or "missing"),
        decision_report_available=bool(decision_report["available"]),
        missing_count=int(coverage.get("missing_count") or 0),
        attention_count=int(coverage.get("attention_count") or 0),
    )
    read_order = build_read_order(
        top_run_ref=top_run_ref,
        evaluation_section=evaluation_section,
        experiment_section=experiment_section,
        notebook_section=notebook_section,
        decision_report=decision_report,
        comparison_report_artifact=comparison_report_artifact,
        diagnostics_artifact=diagnostics_artifact,
        status=status,
    )
    next_action = next_result_action(
        top_run=top_run,
        evaluation_status=str(evaluation_section.get("status") or "missing"),
        experiment_status=str(experiment_section.get("status") or "missing"),
        has_diagnostics=diagnostics_artifact is not None,
        has_comparison=comparison_report_artifact is not None,
        decision_report_available=bool(decision_report["available"]),
        bundle_next_action=bundle["recommended_next_action"],
    )
    return {
        "schema_version": "result_readout.v1",
        "project_id": project.id,
        "status": status,
        "headline": result_headline(status, top_run_ref),
        "summary": result_summary(status, top_run_ref, experiment_section, decision_report),
        "top_run": top_run_ref,
        "metric_story": metric_story(top_run_ref),
        "evaluation_contract": {
            "status": evaluation_section.get("status"),
            "summary": evaluation_section.get("human_summary"),
            "primary_metric": evaluation_section.get("primary_metric"),
            "split_type": evaluation_section.get("split_type"),
            "evaluation_spec": evaluation_section.get("approved_spec"),
            "split_manifest": evaluation_section.get("latest_split"),
        },
        "comparison": {
            "available": comparison_report_artifact is not None,
            "artifact": artifact_ref(comparison_artifact),
            "report_artifact": artifact_ref(comparison_report_artifact),
        },
        "diagnostics": {
            "available": diagnostics_artifact is not None,
            "artifact": artifact_ref(diagnostics_artifact),
            "report_artifact": artifact_ref(diagnostics_report_artifact),
            "summary": experiment_section.get("human_summary"),
        },
        "notebook": {
            "status": notebook_section.get("status"),
            "summary": notebook_section.get("human_summary"),
            "recommended": notebook_section.get("recommended_notebook"),
            "count": notebook_section.get("notebook_count"),
            "source_count": notebook_section.get("source_count"),
            "action_endpoint": f"/api/projects/{project.id}/results/notebook-evidence",
            "action_label": "Build Notebook Evidence",
            "target_tab": "Notebooks",
            "target_anchor": "notebook-focus",
        },
        "decision_report": {
            "available": decision_report["available"],
            "generated_at": decision_report["generated_at"],
            "report": decision_report["report"],
            "report_artifact": decision_report["report_artifact"],
            "readiness": bundle["readiness"],
            "coverage_summary": coverage,
        },
        "read_order": read_order,
        "next_action": next_action,
        "evidence_gaps": evidence_gaps(bundle["evidence_map"]),
        "safety": {
            "external_dashboards_required": False,
            "leaderboard_is_decision": False,
            "evaluation_spec_destructively_changed": False,
            "missing_evidence_is_visible": True,
        },
    }


def latest_diagnostics_for_run(db: Session, project_id: str, run_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type == "evaluation_diagnostics",
            Artifact.metadata_json.contains(run_id),
        )
        .order_by(Artifact.created_at.desc())
    )


def latest_diagnostics_report_for_run(db: Session, project_id: str, run_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.asset_type == "evaluation_diagnostics_report",
            Artifact.metadata_json.contains(run_id),
        )
        .order_by(Artifact.created_at.desc())
    )


def run_readout_ref(run: ExperimentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    metrics = loads_json(run.metrics_json, {})
    metric_name = string_value(metrics.get("primary_metric_name")) or primary_metric_from_metrics(metrics)
    metric_value = numeric_value(metrics.get("primary_metric_value"))
    if metric_value is None and metric_name:
        metric_value = numeric_value(metrics.get(metric_name))
    return {
        "id": run.id,
        "runner_type": run.runner_type,
        "model_version_id": run.model_version_id,
        "evaluation_spec_id": run.evaluation_spec_id,
        "split_manifest_id": run.split_manifest_id,
        "primary_metric_name": metric_name,
        "primary_metric_value": metric_value,
        "metrics": metrics,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }


def result_status(
    *,
    has_top_run: bool,
    evaluation_status: str,
    experiment_status: str,
    decision_report_available: bool,
    missing_count: int,
    attention_count: int,
) -> str:
    if evaluation_status != "ready":
        return "needs_evaluation"
    if not has_top_run:
        return "needs_run"
    if experiment_status in {"missing", "partial"}:
        return "needs_diagnostics"
    if not decision_report_available:
        return "needs_decision_report"
    if missing_count or attention_count:
        return "needs_attention"
    return "ready_for_review"


def result_headline(status: str, top_run: dict[str, Any] | None) -> str:
    if status == "needs_evaluation":
        return "Lock evaluation before reading results"
    if status == "needs_run":
        return "No comparable run evidence yet"
    if status == "needs_diagnostics":
        return "A top run exists; diagnostics need to catch up"
    if status == "needs_decision_report":
        return "Result evidence is ready to summarize"
    if status == "ready_for_review":
        return "Result readout is ready for human review"
    if top_run:
        return f"Top run {top_run['id']} is readable, with open evidence gaps"
    return "Result readout needs attention"


def result_summary(
    status: str,
    top_run: dict[str, Any] | None,
    experiment_section: dict[str, Any],
    decision_report: dict[str, Any],
) -> str:
    if top_run is None:
        return "Run a baseline or controlled AgentRunner task after approving evaluation. Tablex will keep the leaderboard empty until there is comparable evidence."
    metric = metric_story(top_run)
    if status == "needs_decision_report":
        return f"{metric} Diagnostics and comparison evidence can now be turned into a decision report."
    if decision_report["available"]:
        return f"{metric} The current decision report is available; read that first, then drill into Leaderboard only for rank-level details."
    return str(experiment_section.get("human_summary") or metric)


def metric_story(top_run: dict[str, Any] | None) -> str:
    if top_run is None:
        return "No metric is available yet."
    metric_name = top_run.get("primary_metric_name") or "primary metric"
    metric_value = top_run.get("primary_metric_value")
    if isinstance(metric_value, (int, float)):
        return f"Best run {top_run['id']} reports {metric_name}={metric_value:.6g}."
    return f"Best run {top_run['id']} has no numeric primary metric recorded."


def build_read_order(
    *,
    top_run_ref: dict[str, Any] | None,
    evaluation_section: dict[str, Any],
    experiment_section: dict[str, Any],
    notebook_section: dict[str, Any],
    decision_report: dict[str, Any],
    comparison_report_artifact: Artifact | None,
    diagnostics_artifact: Artifact | None,
    status: str,
) -> list[dict[str, Any]]:
    report_ref = decision_report["report"] if decision_report["available"] else None
    recommended_notebook = notebook_section.get("recommended_notebook")
    notebook_artifact_id = notebook_source_artifact_id(recommended_notebook if isinstance(recommended_notebook, dict) else None)
    return [
        {
            "step": 1,
            "title": "Read the result",
            "body": metric_story(top_run_ref),
            "target_tab": "Insight" if report_ref else "Leaderboard",
            "artifact_id": report_ref.get("artifact_id") if isinstance(report_ref, dict) else None,
            "state": "ready" if top_run_ref else "missing",
        },
        {
            "step": 2,
            "title": "Check the evaluation contract",
            "body": str(evaluation_section.get("human_summary") or "Evaluation contract is not ready."),
            "target_tab": "Evaluation",
            "artifact_id": (evaluation_section.get("approved_spec") or {}).get("id")
            if isinstance(evaluation_section.get("approved_spec"), dict)
            else None,
            "state": evaluation_section.get("status"),
        },
        {
            "step": 3,
            "title": "Inspect diagnostics and comparison",
            "body": str(experiment_section.get("human_summary") or "No experiment diagnostics are available yet."),
            "target_tab": "Leaderboard",
            "artifact_id": comparison_report_artifact.id if comparison_report_artifact else diagnostics_artifact.id if diagnostics_artifact else None,
            "state": "ready" if comparison_report_artifact or diagnostics_artifact else "missing",
        },
        {
            "step": 4,
            "title": "Open notebook evidence",
            "body": str(notebook_section.get("human_summary") or "No notebook evidence is available yet."),
            "target_tab": "Notebooks",
            "artifact_id": notebook_artifact_id,
            "state": notebook_section.get("status"),
        },
        {
            "step": 5,
            "title": "Decide the next action",
            "body": "Use the decision report when it exists; otherwise generate it from this readout.",
            "target_tab": "Insight",
            "artifact_id": report_ref.get("artifact_id") if isinstance(report_ref, dict) else None,
            "state": "ready" if status in {"needs_attention", "ready_for_review"} and report_ref else "needs_action",
        },
    ]


def notebook_source_artifact_id(notebook: dict[str, Any] | None) -> str | None:
    if not notebook:
        return None
    artifact_ids = notebook.get("artifact_ids")
    if not isinstance(artifact_ids, dict):
        return None
    for key in ("notebook", "report_artifact", "figure_manifest", "evidence_bundle"):
        value = artifact_ids.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def next_result_action(
    *,
    top_run: ExperimentRun | None,
    evaluation_status: str,
    experiment_status: str,
    has_diagnostics: bool,
    has_comparison: bool,
    decision_report_available: bool,
    bundle_next_action: dict[str, Any],
) -> dict[str, Any]:
    if evaluation_status != "ready":
        return {
            "label": "Approve evaluation and build split",
            "target_tab": "Evaluation",
            "target_anchor": None,
            "agent_prompt": "Help me lock the evaluation design and build the split manifest.",
        }
    if top_run is None:
        return {
            "label": "Run a baseline or agent experiment",
            "target_tab": "Leaderboard",
            "target_anchor": None,
            "agent_prompt": "Run a flexible baseline or plan the next agent experiment under the approved evaluation.",
        }
    if experiment_status != "ready" or not has_diagnostics:
        return {
            "label": "Generate top-run diagnostics",
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "agent_prompt": "Diagnose the top run and show me the result readout.",
        }
    if not has_comparison:
        return {
            "label": "Compare current runs",
            "target_tab": "Leaderboard",
            "target_anchor": "result-readout",
            "agent_prompt": "Compare the current top runs and show me the result readout.",
        }
    if not decision_report_available:
        return {
            "label": "Generate post-run decision report",
            "target_tab": "Insight",
            "target_anchor": "decision-report",
            "agent_prompt": "Prepare a post-run decision report with diagnostics and run comparison.",
        }
    return {
        "label": str(bundle_next_action.get("title") or "Read the current decision report"),
        "target_tab": normalize_result_readout_target_tab(str(bundle_next_action.get("target_tab") or "Insight")),
        "target_anchor": "decision-report",
        "agent_prompt": (
            f"{bundle_next_action.get('title') or 'Explain the next action'}: "
            f"{bundle_next_action.get('reason') or 'Explain the next action from the result readout.'}"
        ),
    }


def evidence_gaps(evidence_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps = [item for item in evidence_map if item.get("status") != "ready"]
    return [
        {
            "area": item.get("area"),
            "status": item.get("status"),
            "summary": item.get("summary"),
            "target_tab": gap_target_tab(str(item.get("area") or "")),
        }
        for item in gaps[:6]
    ]


def gap_target_tab(area: str) -> str:
    return normalize_result_readout_target_tab({
        "Data Review": "Data",
        "Assumptions": "Assumptions",
        "Evaluation": "Evaluation",
        "Experiments": "Leaderboard",
        "Notebooks": "Notebooks",
        "Runner Results": "Home",
        "Citations": "Home",
        "Reports": "Insight",
        "Benchmark": "Data",
        "Relational": "Data",
    }.get(area, "Insight"))


def normalize_result_readout_target_tab(target_tab: str) -> str:
    return {
        "Overview": "Home",
        "Approach": "Home",
        "Experiments": "Leaderboard",
        "Reports": "Insight",
        "Notebooks": "Notebooks",
    }.get(target_tab, target_tab)


def primary_metric_from_metrics(metrics: dict[str, Any]) -> str | None:
    for key in ["roc_auc", "pr_auc", "rmse", "mae", "accuracy", "f1", "log_loss"]:
        if key in metrics:
            return key
    return None


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
