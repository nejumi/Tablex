from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    ExperimentRun,
    Idea,
    Insight,
    Job,
    ModelVersion,
    Project,
    Question,
    Report,
    ResearchBrief,
    SplitManifest,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)

NATIVE_NOTEBOOK_ASSET_TYPES = ("analysis_notebook", "marimo_notebook")


@dataclass(frozen=True)
class GuidedJourneySnapshotResult:
    snapshot: dict[str, Any]
    artifact: Artifact
    report: Report
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class GuidedJourneyComparisonResult:
    comparison: dict[str, Any]
    artifact: Artifact
    report: Report
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class AutonomousDecisionBriefResult:
    brief: dict[str, Any]
    artifact: Artifact
    report: Report
    report_artifact: Artifact
    artifact_ids: list[str]


def build_project_guidance(db: Session, project: Project) -> dict[str, Any]:
    counts = {
        "datasets": _count_project_rows(db, DatasetSnapshot, project.id),
        "artifacts": _count_project_rows(db, Artifact, project.id),
        "questions": _count_project_rows(db, Question, project.id),
        "assumptions": _count_project_rows(db, Assumption, project.id),
        "evaluation_candidates": _count_project_rows(db, EvaluationCandidate, project.id),
        "evaluation_specs": _count_project_rows(db, EvaluationSpec, project.id),
        "split_manifests": _count_project_rows(db, SplitManifest, project.id),
        "experiment_runs": _count_project_rows(db, ExperimentRun, project.id),
        "model_versions": _count_project_rows(db, ModelVersion, project.id),
        "jobs": _count_project_rows(db, Job, project.id),
        "research_briefs": _count_project_rows(db, ResearchBrief, project.id),
        "ideas": _count_project_rows(db, Idea, project.id),
        "reports": _count_project_rows(db, Report, project.id),
        "visualizations": _count_project_rows(db, VisualizationSpec, project.id),
        "insights": _count_project_rows(db, Insight, project.id),
        "analysis_notebooks": _count_project_rows(
            db, Artifact, project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES)
        ),
        "notebook_execution_plans": _count_project_rows(
            db, Artifact, project.id, Artifact.asset_type == "notebook_execution_plan"
        ),
    }
    state = _state_summary(db, project, counts)
    focus = _recommended_focus(project, counts, state)
    journey_stages = _journey_stages(project, counts, state, focus)
    current_stage = _current_journey_stage(journey_stages)
    autonomous_navigation = _autonomous_navigation(
        project=project,
        counts=counts,
        state=state,
        focus=focus,
        journey_stages=journey_stages,
        current_stage=current_stage,
    )
    hidden_detail_groups = [
        {
            "id": "risk_and_questions",
            "label": "Risk and questions",
            "count": int(state["unresolved_high_risk_assumption_count"]) + int(state["blocking_question_count"]),
        },
        {
            "id": "activity",
            "label": "Jobs and activity",
            "count": counts["jobs"],
        },
        {
            "id": "assets",
            "label": "Artifacts and lineage inputs",
            "count": counts["artifacts"],
        },
    ]
    return {
        "schema_version": "project_guidance.v1",
        "project_id": project.id,
        "generated_at": utc_now().isoformat(),
        "attention_budget": 1,
        "overview_mode": "guided",
        "recommended_focus": focus,
        "journey_stages": journey_stages,
        "current_stage_id": current_stage["id"] if current_stage else None,
        "state_summary": state,
        "supporting_counts": counts,
        "hidden_detail_groups": hidden_detail_groups,
        "agent_guidance": _agent_guidance(state),
        "autonomous_navigation": autonomous_navigation,
    }


def create_guided_journey_snapshot(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> GuidedJourneySnapshotResult:
    guidance = build_project_guidance(db, project)
    current_stage = next(
        (stage for stage in guidance["journey_stages"] if stage["id"] == guidance["current_stage_id"]),
        None,
    )
    status_counts = {
        status: sum(1 for stage in guidance["journey_stages"] if stage["status"] == status)
        for status in ("done", "current", "next", "blocked", "waiting")
    }
    snapshot = {
        "schema_version": "guided_journey_snapshot.v1",
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": guidance["generated_at"],
        "current_stage_id": guidance["current_stage_id"],
        "current_stage_label": current_stage["label"] if current_stage else None,
        "recommended_focus_key": guidance["recommended_focus"]["focus_key"],
        "recommended_focus_title": guidance["recommended_focus"]["title"],
        "status_counts": status_counts,
        "guidance": guidance,
        "persistence_policy": {
            "artifact_first": True,
            "external_dashboard_required": False,
            "agent_runner_role": "consumer_of_harness_context_not_owner",
        },
    }
    suffix = new_id("journey")
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="guided_journey_snapshot",
        name=f"guided_journey_snapshot_{suffix}",
        filename="guided_journey_snapshot.json",
        payload=snapshot,
        metadata={
            "project_id": project.id,
            "current_stage_id": snapshot["current_stage_id"],
            "recommended_focus_key": snapshot["recommended_focus_key"],
            "blocked_stage_count": status_counts["blocked"],
        },
    )
    report_md = render_guided_journey_report(snapshot)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="guided_journey_report",
        name=f"guided_journey_report_{suffix}",
        filename="guided_journey_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "guided_journey_snapshot_artifact_id": artifact.id,
            "current_stage_id": snapshot["current_stage_id"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="guided_journey_report",
        title=f"{project.name} Guided Journey",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": artifact.id}]),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_guided_journey_visualization_spec(snapshot)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"guided_journey_visualization_{suffix}",
        filename="guided_journey_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "source_artifact_id": artifact.id,
            "chart_type": visualization_payload["chart_type"],
            "visualization_scope": "guided_journey",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title=visualization_payload["title"],
        chart_type=visualization_payload["chart_type"],
        spec_json=dumps_json(visualization_payload["spec"]),
        source_artifact_id=artifact.id,
        artifact_id=visualization_artifact.id,
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
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="snapshot_of",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualized_by",
    )
    return GuidedJourneySnapshotResult(
        snapshot=snapshot,
        artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=[artifact.id, report_artifact.id, visualization_artifact.id],
    )


def create_autonomous_decision_brief(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> AutonomousDecisionBriefResult:
    guidance = build_project_guidance(db, project)
    brief = dict(guidance["autonomous_navigation"]["decision_brief"])
    suffix = new_id("decisionbrief")
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="autonomous_decision_brief",
        name=f"autonomous_decision_brief_{suffix}",
        filename="autonomous_decision_brief.json",
        payload=brief,
        metadata={
            "project_id": project.id,
            "focus_key": brief["focus_key"],
            "target_tab": brief["target_tab"],
            "risk_level": brief["risk_level"],
        },
    )
    report_md = render_autonomous_decision_brief_report(brief)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="autonomous_decision_brief_report",
        name=f"autonomous_decision_brief_report_{suffix}",
        filename="autonomous_decision_brief.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "autonomous_decision_brief_artifact_id": artifact.id,
            "focus_key": brief["focus_key"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="autonomous_decision_brief",
        title=f"{project.name} Autonomous Decision Brief",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": artifact.id}]),
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
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="decision_brief_for",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="materializes",
    )
    return AutonomousDecisionBriefResult(
        brief=brief,
        artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        artifact_ids=[artifact.id, report_artifact.id],
    )


def create_guided_journey_comparison(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> GuidedJourneyComparisonResult:
    snapshot_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "guided_journey_snapshot")
            .order_by(Artifact.created_at.desc())
            .limit(2)
        ).all()
    )
    if len(snapshot_artifacts) < 2:
        raise ValueError("At least two guided journey snapshots are required for comparison")
    current_artifact, previous_artifact = snapshot_artifacts[0], snapshot_artifacts[1]
    previous = load_guided_journey_snapshot(previous_artifact)
    current = load_guided_journey_snapshot(current_artifact)
    comparison = build_guided_journey_comparison(
        previous=previous,
        current=current,
        previous_artifact=previous_artifact,
        current_artifact=current_artifact,
    )
    suffix = new_id("journeycmp")
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="guided_journey_comparison",
        name=f"guided_journey_comparison_{suffix}",
        filename="guided_journey_comparison.json",
        payload=comparison,
        metadata={
            "project_id": project.id,
            "previous_snapshot_artifact_id": previous_artifact.id,
            "current_snapshot_artifact_id": current_artifact.id,
            "changed_stage_count": comparison["summary"]["changed_stage_count"],
            "current_stage_changed": comparison["summary"]["current_stage_changed"],
            "recommended_focus_changed": comparison["summary"]["recommended_focus_changed"],
        },
    )
    report_md = render_guided_journey_comparison_report(comparison)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="guided_journey_comparison_report",
        name=f"guided_journey_comparison_report_{suffix}",
        filename="guided_journey_comparison_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "guided_journey_comparison_artifact_id": artifact.id,
            "previous_snapshot_artifact_id": previous_artifact.id,
            "current_snapshot_artifact_id": current_artifact.id,
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="guided_journey_comparison_report",
        title=f"{project.name} Guided Journey Comparison",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "artifact", "asset_id": previous_artifact.id},
                {"asset_type": "artifact", "asset_id": current_artifact.id},
                {"asset_type": "artifact", "asset_id": artifact.id},
            ]
        ),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization_payload = build_guided_journey_comparison_visualization_spec(comparison)
    visualization_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="visualization_spec",
        name=f"guided_journey_comparison_visualization_{suffix}",
        filename="guided_journey_comparison_visualization.json",
        payload=visualization_payload,
        metadata={
            "project_id": project.id,
            "source_artifact_id": artifact.id,
            "chart_type": visualization_payload["chart_type"],
            "visualization_scope": "guided_journey_comparison",
        },
    )
    visualization = VisualizationSpec(
        id=new_id("viz"),
        project_id=project.id,
        title=visualization_payload["title"],
        chart_type=visualization_payload["chart_type"],
        spec_json=dumps_json(visualization_payload["spec"]),
        source_artifact_id=artifact.id,
        artifact_id=visualization_artifact.id,
        status="draft",
        created_by_type="system",
    )
    db.add(visualization)
    db.flush()
    for source_artifact in (previous_artifact, current_artifact):
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="compared_in",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="summarized_by",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualized_by",
    )
    return GuidedJourneyComparisonResult(
        comparison=comparison,
        artifact=artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=[artifact.id, report_artifact.id, visualization_artifact.id],
    )


def load_guided_journey_snapshot(artifact: Artifact) -> dict[str, Any]:
    payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    if not isinstance(payload, dict) or payload.get("schema_version") != "guided_journey_snapshot.v1":
        raise ValueError(f"Artifact {artifact.id} is not a guided journey snapshot")
    return payload


def build_guided_journey_comparison(
    *,
    previous: dict[str, Any],
    current: dict[str, Any],
    previous_artifact: Artifact,
    current_artifact: Artifact,
) -> dict[str, Any]:
    previous_stages = stage_map(previous)
    current_stages = stage_map(current)
    stage_ids = [stage["id"] for stage in previous["guidance"]["journey_stages"]]
    stage_ids.extend(stage_id for stage_id in current_stages if stage_id not in previous_stages)
    stage_changes = []
    for stage_id in stage_ids:
        before = previous_stages.get(stage_id)
        after = current_stages.get(stage_id)
        before_status = before.get("status") if before else None
        after_status = after.get("status") if after else None
        stage_changes.append(
            {
                "stage_id": stage_id,
                "stage": str((after or before or {}).get("label") or stage_id),
                "from_status": before_status,
                "to_status": after_status,
                "status_changed": before_status != after_status,
                "from_evidence": before.get("evidence", []) if before else [],
                "to_evidence": after.get("evidence", []) if after else [],
                "summary": str((after or before or {}).get("summary") or ""),
            }
        )
    previous_focus = str(previous.get("recommended_focus_key") or previous["guidance"]["recommended_focus"]["focus_key"])
    current_focus = str(current.get("recommended_focus_key") or current["guidance"]["recommended_focus"]["focus_key"])
    return {
        "schema_version": "guided_journey_comparison.v1",
        "project_id": current["project_id"],
        "project_name": current["project_name"],
        "generated_at": utc_now().isoformat(),
        "previous_snapshot": snapshot_ref(previous, previous_artifact),
        "current_snapshot": snapshot_ref(current, current_artifact),
        "summary": {
            "changed_stage_count": sum(1 for item in stage_changes if item["status_changed"]),
            "current_stage_changed": previous.get("current_stage_id") != current.get("current_stage_id"),
            "recommended_focus_changed": previous_focus != current_focus,
            "previous_focus_key": previous_focus,
            "current_focus_key": current_focus,
        },
        "stage_changes": stage_changes,
        "policy": {
            "artifact_first": True,
            "external_dashboard_required": False,
            "comparison_scope": "latest_two_saved_guided_journey_snapshots",
        },
    }


def stage_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(stage["id"]): stage for stage in snapshot["guidance"]["journey_stages"]}


def snapshot_ref(snapshot: dict[str, Any], artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "created_at": artifact.created_at.isoformat(),
        "current_stage_id": snapshot.get("current_stage_id"),
        "current_stage_label": snapshot.get("current_stage_label"),
        "recommended_focus_key": snapshot.get("recommended_focus_key"),
        "recommended_focus_title": snapshot.get("recommended_focus_title"),
        "status_counts": snapshot.get("status_counts", {}),
    }


def render_guided_journey_report(snapshot: dict[str, Any]) -> str:
    guidance = snapshot["guidance"]
    focus = guidance["recommended_focus"]
    lines = [
        f"# Guided Journey: {snapshot['project_name']}",
        "",
        "## Current Focus",
        "",
        f"- Stage: {snapshot.get('current_stage_label') or snapshot.get('current_stage_id') or 'unknown'}",
        f"- Recommended focus: {focus['title']}",
        f"- Risk level: {focus['risk_level']}",
        f"- Confidence: {focus['confidence']}",
        "",
        "## Journey Stages",
        "",
        "| Stage | Status | Evidence | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for stage in guidance["journey_stages"]:
        evidence = "; ".join(str(item) for item in stage.get("evidence", [])[:3])
        lines.append(f"| {stage['label']} | {stage['status']} | {evidence} | {stage['summary']} |")
    lines.extend(
        [
            "",
            "## Recommended Action",
            "",
            f"- Action: {focus['primary_action']['label']}",
            f"- Target tab: {focus['primary_action']['target_tab']}",
            f"- Action type: {focus['primary_action']['action_type']}",
            "",
            "## Agent Guidance",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in guidance["agent_guidance"])
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- This snapshot is an in-product artifact and report; external dashboards are not required.",
            "- The Approach stage records handoff readiness only. It does not force Codex into a fixed modeling recipe.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_autonomous_decision_brief_report(brief: dict[str, Any]) -> str:
    action = brief["primary_action"]
    lines = [
        f"# Autonomous Decision Brief: {brief['project_name']}",
        "",
        "## One Decision",
        "",
        f"- Question: {brief['decision_question']}",
        f"- Focus: {brief['headline']}",
        f"- Target tab: {brief['target_tab']}",
        f"- Status: {brief['status']}",
        f"- Risk: {brief['risk_level']}",
        f"- Confidence: {brief['confidence']}",
        "",
        "## Why Now",
        "",
        str(brief["why_now"]),
        "",
        "## Evidence To Check",
        "",
    ]
    lines.extend(f"- {item}" for item in brief.get("evidence_to_check", []))
    lines.extend(
        [
            "",
            "## Primary Action",
            "",
            f"- Action: {action['label']}",
            f"- Action type: {action['action_type']}",
            f"- Target tab: {action['target_tab']}",
            "",
            "## Not Now",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in brief.get("not_now", []))
    lines.extend(
        [
            "",
            "## If Done",
            "",
            str(brief.get("if_done") or "Refresh the Autonomous Navigator."),
            "",
            "## Codex Handoff",
            "",
            str(brief["codex_handoff"]["prompt"]),
            "",
            "## Harness Boundaries",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in brief.get("harness_boundaries", []))
    return "\n".join(lines) + "\n"


def render_guided_journey_comparison_report(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    lines = [
        f"# Guided Journey Comparison: {comparison['project_name']}",
        "",
        "## Summary",
        "",
        f"- Changed stages: {summary['changed_stage_count']}",
        f"- Current stage changed: {summary['current_stage_changed']}",
        f"- Recommended focus changed: {summary['recommended_focus_changed']}",
        f"- Previous focus: {summary['previous_focus_key']}",
        f"- Current focus: {summary['current_focus_key']}",
        "",
        "## Snapshots",
        "",
        f"- Previous: {comparison['previous_snapshot']['artifact_id']} ({comparison['previous_snapshot']['current_stage_label']})",
        f"- Current: {comparison['current_snapshot']['artifact_id']} ({comparison['current_snapshot']['current_stage_label']})",
        "",
        "## Stage Changes",
        "",
        "| Stage | Previous | Current | Changed | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for change in comparison["stage_changes"]:
        lines.append(
            "| "
            f"{change['stage']} | "
            f"{change.get('from_status') or '-'} | "
            f"{change.get('to_status') or '-'} | "
            f"{change['status_changed']} | "
            f"{change['summary']} |"
        )
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- This comparison uses saved Guided Journey snapshots only.",
            "- It records navigation and readiness changes, not a forced modeling recipe.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_guided_journey_visualization_spec(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "stage": stage["label"],
            "status": "ready" if stage["status"] == "done" else stage["status"],
            "count": len(stage.get("evidence", [])),
            "detail": stage["summary"],
        }
        for stage in snapshot["guidance"]["journey_stages"]
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": f"Guided Journey: {snapshot['project_name']}",
        "chart_type": "stage_status",
        "data": rows,
        "spec": {
            "schema_version": "guided_journey_stage_status.v1",
            "current_stage_id": snapshot["current_stage_id"],
            "recommended_focus_key": snapshot["recommended_focus_key"],
            "status_counts": snapshot["status_counts"],
        },
        "encoding": {"stage": "stage", "status": "status", "count": "count", "detail": "detail"},
        "empty_state": "Save a guided journey snapshot after project guidance is available.",
    }


def build_guided_journey_comparison_visualization_spec(comparison: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {
            "stage": change["stage"],
            "status": "changed" if change["status_changed"] else "ready",
            "count": 1 if change["status_changed"] else 0,
            "detail": f"{change.get('from_status') or '-'} -> {change.get('to_status') or '-'}",
        }
        for change in comparison["stage_changes"]
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": f"Guided Journey Comparison: {comparison['project_name']}",
        "chart_type": "stage_status",
        "data": rows,
        "spec": {
            "schema_version": "guided_journey_comparison_stage_status.v1",
            "previous_snapshot_artifact_id": comparison["previous_snapshot"]["artifact_id"],
            "current_snapshot_artifact_id": comparison["current_snapshot"]["artifact_id"],
            "changed_stage_count": comparison["summary"]["changed_stage_count"],
            "recommended_focus_changed": comparison["summary"]["recommended_focus_changed"],
        },
        "encoding": {"stage": "stage", "status": "status", "count": "count", "detail": "detail"},
        "empty_state": "Save at least two guided journey snapshots before comparing progress.",
    }


def first_sentence(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip("# ").strip()
        if stripped:
            return stripped[:280]
    return "Guided journey report"


def _state_summary(db: Session, project: Project, counts: dict[str, int]) -> dict[str, Any]:
    latest_dataset = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id)
        .order_by(DatasetSnapshot.created_at.desc())
    )
    latest_approved_spec = db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project.id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )
    latest_successful_run = db.scalar(
        select(ExperimentRun)
        .where(ExperimentRun.project_id == project.id, ExperimentRun.status == "succeeded")
        .order_by(ExperimentRun.started_at.desc().nullslast(), ExperimentRun.id.desc())
    )
    latest_notebook = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
        .order_by(Artifact.created_at.desc())
    )
    has_understanding_report = _count_project_rows(
        db,
        Artifact,
        project.id,
        Artifact.asset_type == "understanding_report",
    ) > 0
    has_eda_profile = _count_project_rows(
        db,
        Artifact,
        project.id,
        Artifact.asset_type == "eda_profile",
    ) > 0
    unresolved_high_risk_assumption_count = _count_project_rows(
        db,
        Assumption,
        project.id,
        Assumption.risk_level.in_(["high", "blocking", "deployment_blocking"]),
        Assumption.status.not_in(["confirmed", "resolved", "rejected"]),
    )
    blocking_question_count = _count_project_rows(
        db,
        Question,
        project.id,
        Question.status != "answered",
        ((Question.blocks_next_phase.is_(True)) | (Question.fallback_policy == "block_until_answered")),
    )
    approved_evaluation_spec_count = _count_project_rows(
        db,
        EvaluationSpec,
        project.id,
        EvaluationSpec.status == "approved",
    )
    successful_run_count = _count_project_rows(
        db,
        ExperimentRun,
        project.id,
        ExperimentRun.status == "succeeded",
    )
    failed_recent_job_count = _count_project_rows(
        db,
        Job,
        project.id,
        Job.status.in_(["failed", "timed_out"]),
    )
    return {
        "project_phase": project.current_phase,
        "target_column": project.target_column,
        "latest_dataset_snapshot_id": latest_dataset.id if latest_dataset else None,
        "latest_approved_evaluation_spec_id": latest_approved_spec.id if latest_approved_spec else None,
        "latest_successful_run_id": latest_successful_run.id if latest_successful_run else None,
        "latest_analysis_notebook_artifact_id": latest_notebook.id if latest_notebook else None,
        "has_dataset": counts["datasets"] > 0,
        "has_eda_profile": has_eda_profile,
        "has_understanding_report": has_understanding_report,
        "unresolved_high_risk_assumption_count": unresolved_high_risk_assumption_count,
        "blocking_question_count": blocking_question_count,
        "approved_evaluation_spec_count": approved_evaluation_spec_count,
        "split_manifest_count": counts["split_manifests"],
        "successful_run_count": successful_run_count,
        "failed_recent_job_count": failed_recent_job_count,
        "report_count": counts["reports"],
        "analysis_notebook_count": counts["analysis_notebooks"],
        "notebook_execution_plan_count": counts["notebook_execution_plans"],
        "candidate_count": counts["evaluation_candidates"],
        "idea_count": counts["ideas"],
        "visualization_count": counts["visualizations"],
    }


def _autonomous_navigation(
    *,
    project: Project,
    counts: dict[str, int],
    state: dict[str, Any],
    focus: dict[str, Any],
    journey_stages: list[dict[str, Any]],
    current_stage: dict[str, Any] | None,
) -> dict[str, Any]:
    attention_state = _navigation_attention_state(focus, state)
    primary_action = focus["primary_action"]
    current_stage_label = current_stage["label"] if current_stage else str(focus["target_tab"])
    visible_context = [
        {"label": "Now", "value": focus["title"]},
        {"label": "Why", "value": focus["reason"]},
        {"label": "Decision stage", "value": current_stage_label},
    ]
    hidden_complexity = [
        "raw artifact inventory",
        "full job history",
        "secondary tabs",
        "debug lineage details",
    ]
    if int(state["unresolved_high_risk_assumption_count"]) > 0:
        hidden_complexity.append("non-critical assumptions")
    if counts["reports"] > 0:
        hidden_complexity.append("older report shelves")
    runner_prompt = focus.get("suggested_agent_prompt") or _navigation_runner_prompt(project, focus, state)
    decision_brief = _autonomous_decision_brief(
        project=project,
        state=state,
        focus=focus,
        attention_state=attention_state,
        runner_prompt=runner_prompt,
    )
    return {
        "schema_version": "autonomous_navigation.v1",
        "mode": "one_decision_at_a_time",
        "aesthetic_principle": "show_the_next_decision_not_the_system_topology",
        "attention_budget": 1,
        "status": attention_state,
        "headline": focus["title"],
        "why": focus["reason"],
        "target_tab": focus["target_tab"],
        "primary_action": primary_action,
        "secondary_action_count": len(focus.get("secondary_actions", [])),
        "confidence": focus["confidence"],
        "risk_level": focus["risk_level"],
        "evidence": focus["evidence"][:3],
        "visible_context": visible_context,
        "hidden_complexity": hidden_complexity,
        "decision_brief": decision_brief,
        "journey_progress": {
            "current_stage_id": current_stage["id"] if current_stage else None,
            "current_stage_label": current_stage_label,
            "done_count": sum(1 for stage in journey_stages if stage["status"] == "done"),
            "total_count": len(journey_stages),
        },
        "codex_navigation": {
            "role": "interactive_guide_and_runner_not_product_owner",
            "prompt": runner_prompt,
            "runner_may_choose_approach": True,
            "must_respect_harness_boundaries": [
                "EvaluationSpec",
                "SplitManifest",
                "artifact lineage",
                "secret and connector credential boundaries",
            ],
        },
    }


def _autonomous_decision_brief(
    *,
    project: Project,
    state: dict[str, Any],
    focus: dict[str, Any],
    attention_state: str,
    runner_prompt: str,
) -> dict[str, Any]:
    focus_key = str(focus["focus_key"])
    decision_question = _decision_question(focus_key, state)
    return {
        "schema_version": "autonomous_decision_brief.v1",
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": utc_now().isoformat(),
        "attention_budget": 1,
        "focus_key": focus_key,
        "target_tab": focus["target_tab"],
        "headline": focus["title"],
        "decision_question": decision_question,
        "why_now": focus["reason"],
        "status": attention_state,
        "risk_level": focus["risk_level"],
        "confidence": focus["confidence"],
        "evidence_to_check": focus["evidence"][:3],
        "primary_action": focus["primary_action"],
        "not_now": _not_now_guidance(focus_key),
        "if_done": _if_done_guidance(focus_key),
        "codex_handoff": {
            "prompt": runner_prompt,
            "runner_may_choose_approach": True,
            "do_not_force_recipe": True,
        },
        "harness_boundaries": [
            "Do not expose secrets or connector credentials to runner prompts.",
            "Do not mutate approved EvaluationSpec or SplitManifest without explicit review.",
            "Register important outputs as artifacts with lineage.",
        ],
    }


def _decision_question(focus_key: str, state: dict[str, Any]) -> str:
    target = state.get("target_column") or "the target"
    questions = {
        "upload_data": "What data should Tablex understand first?",
        "understand_data": f"What does this data mean before choosing {target}, evaluation, or features?",
        "assumptions": "Which assumption could invalidate evaluation or feature design if left unresolved?",
        "evaluation": "What evaluation design is reliable enough to constrain runner work?",
        "approach": "What should Codex try next, given the evidence and harness constraints?",
        "experiments": "What experiment evidence is missing before comparing approaches?",
        "notebooks": "What notebook evidence would make the current results readable and decision-grade?",
        "reports": "What decision can a human make from the current evidence, and what is still unsafe?",
    }
    return questions.get(focus_key, "What is the smallest useful decision now?")


def _not_now_guidance(focus_key: str) -> list[str]:
    shared = ["Do not start by browsing raw artifacts.", "Do not optimize a model before the current decision is resolved."]
    specific = {
        "assumptions": ["Do not ask Codex to engineer features around unresolved leakage or availability risks."],
        "evaluation": ["Do not run leaderboard-style comparisons before the split and metric are owned by the harness."],
        "approach": ["Do not reduce Codex to a fixed AutoML recipe; pass evidence and constraints instead."],
        "notebooks": ["Do not promote empty previews or unexecuted diagnostics as decision evidence."],
        "reports": ["Do not treat a report as deployment approval."],
    }
    return [*shared, *specific.get(focus_key, [])]


def _if_done_guidance(focus_key: str) -> str:
    followups = {
        "upload_data": "Run Data Understanding and let the harness infer questions and assumptions.",
        "understand_data": "Review high-risk assumptions before locking evaluation.",
        "assumptions": "Move to Evaluation and lock a primary design only after risky assumptions are handled.",
        "evaluation": "Prepare an open-ended Codex runner handoff with EvaluationSpec and SplitManifest attached.",
        "approach": "Run or inspect experiments, then demand diagnostics instead of raw rank chasing.",
        "experiments": "Generate notebook diagnostics so humans can read what changed and why.",
        "notebooks": "Generate or refresh the decision report from notebook and run evidence.",
        "reports": "Use the report to choose the next controlled runner task or human review decision.",
    }
    return followups.get(focus_key, "Refresh the Autonomous Navigator and follow the next decision.")


def _navigation_attention_state(focus: dict[str, Any], state: dict[str, Any]) -> str:
    if focus["risk_level"] == "blocking" or int(state["blocking_question_count"]) > 0:
        return "blocked"
    if focus["risk_level"] == "high":
        return "needs_attention"
    if int(state["failed_recent_job_count"]) > 0:
        return "recover"
    return "ready_to_act"


def _navigation_runner_prompt(project: Project, focus: dict[str, Any], state: dict[str, Any]) -> str:
    target = state.get("target_column") or "the target after data understanding"
    return (
        f"Guide the user through the next Tablex decision for project '{project.name}'. "
        f"The current focus is '{focus['title']}' for target {target}. Explain the smallest useful next action, "
        "what evidence justifies it, what uncertainty remains, and what Codex should do only after harness-owned "
        "EvaluationSpec, SplitManifest, artifacts, and safety boundaries are respected."
    )


def _recommended_focus(project: Project, counts: dict[str, int], state: dict[str, Any]) -> dict[str, Any]:
    if not state["has_dataset"]:
        return _focus(
            focus_key="upload_data",
            target_tab="Data",
            title="Upload or import a dataset",
            reason="The project cannot build understanding, assumptions, evaluation, or agent tasks until a DatasetSnapshot exists.",
            risk_level="blocking",
            confidence=0.98,
            evidence=["0 DatasetSnapshots", f"phase: {project.current_phase}"],
            primary_action=_navigate_action("upload_dataset", "Open Data upload", "Data"),
            secondary_actions=[
                _navigate_action("inspect_understanding_empty", "Preview Understanding", "Understanding"),
                _agent_prompt_action(project.id, "plan_data_intake", _data_intake_prompt(project)),
            ],
        )

    if not state["has_understanding_report"]:
        return _focus(
            focus_key="understand_data",
            target_tab="Understanding",
            title="Understand the data before choosing an objective or evaluation",
            reason="The next useful decision depends on schema, possible task shapes, leakage risk, missingness, and semantic assumptions.",
            risk_level="high",
            confidence=0.92,
            evidence=[f"{counts['datasets']} DatasetSnapshots", "understanding report missing"],
            primary_action=_endpoint_action(
                "run_understanding",
                "Run data understanding",
                "Understanding",
                f"/api/projects/{project.id}/understanding/run",
            ),
            secondary_actions=[
                _navigate_action("inspect_data", "Inspect Data", "Data"),
                _navigate_action("review_assumptions_empty", "Review Assumptions", "Assumptions"),
            ],
        )

    if int(state["blocking_question_count"]) > 0 or int(state["unresolved_high_risk_assumption_count"]) > 0:
        risk_count = int(state["unresolved_high_risk_assumption_count"])
        question_count = int(state["blocking_question_count"])
        return _focus(
            focus_key="assumptions",
            target_tab="Assumptions",
            title="Resolve risky assumptions",
            reason="High-risk assumptions and blocking questions can silently invalidate evaluation or feature design if they are not reviewed.",
            risk_level="high",
            confidence=0.9,
            evidence=[
                f"{risk_count} high-risk assumptions",
                f"{question_count} blocking questions",
                f"{counts['assumptions']} total assumptions",
            ],
            primary_action=_navigate_action("review_assumptions", "Review risk and assumptions", "Assumptions"),
            secondary_actions=[
                _navigate_action("inspect_understanding", "Inspect Understanding", "Understanding"),
                _navigate_action("compare_evaluation_context", "Inspect Evaluation", "Evaluation"),
            ],
        )

    if int(state["approved_evaluation_spec_count"]) == 0:
        if counts["evaluation_candidates"] == 0:
            primary_action = _endpoint_action(
                "compare_evaluation_scenarios",
                "Compare evaluation scenarios",
                "Evaluation",
                f"/api/projects/{project.id}/evaluation/compare",
            )
        else:
            primary_action = _navigate_action("review_evaluation_candidates", "Review evaluation candidates", "Evaluation")
        return _focus(
            focus_key="evaluation",
            target_tab="Evaluation",
            title="Lock a reliable evaluation design",
            reason="Modeling and agent work should stay downstream of EvaluationSpec and SplitManifest constraints.",
            risk_level="high",
            confidence=0.88,
            evidence=[
                f"{counts['evaluation_candidates']} candidates",
                f"{state['approved_evaluation_spec_count']} approved specs",
            ],
            primary_action=primary_action,
            secondary_actions=[
                _navigate_action("review_assumptions_before_eval", "Review Assumptions", "Assumptions"),
                _agent_prompt_action(project.id, "ask_eval_design", _evaluation_prompt(project)),
            ],
        )

    if int(state["split_manifest_count"]) == 0:
        approved_spec_id = state["latest_approved_evaluation_spec_id"]
        primary_action = (
            _endpoint_action(
                "generate_split_manifest",
                "Generate split manifest",
                "Evaluation",
                f"/api/evaluation-specs/{approved_spec_id}/generate-split",
            )
            if isinstance(approved_spec_id, str)
            else _navigate_action("inspect_evaluation_spec", "Inspect approved evaluation", "Evaluation")
        )
        return _focus(
            focus_key="evaluation",
            target_tab="Evaluation",
            title="Materialize the split manifest",
            reason="Experiment runs need a SplitManifest so Codex and local runners cannot drift from the approved evaluation design.",
            risk_level="medium",
            confidence=0.86,
            evidence=[f"{state['approved_evaluation_spec_count']} approved specs", "0 split manifests"],
            primary_action=primary_action,
            secondary_actions=[_navigate_action("inspect_lineage_before_split", "Inspect Lineage", "Lineage")],
        )

    if int(state["successful_run_count"]) == 0:
        prompt = _approach_prompt(project, state)
        return _focus(
            focus_key="approach",
            target_tab="Home",
            title="Plan the next flexible agent approach",
            reason="The harness has enough context to ask Codex for a scoped approach without forcing a fixed recipe.",
            risk_level="medium",
            confidence=0.84,
            evidence=[
                f"{state['approved_evaluation_spec_count']} approved specs",
                f"{state['split_manifest_count']} split manifests",
                "0 successful runs",
            ],
            primary_action=_agent_prompt_action(project.id, "create_scoped_agent_task", prompt),
            secondary_actions=[
                _navigate_action("inspect_experiments_empty", "Inspect Experiments", "Leaderboard"),
                _navigate_action("inspect_assets_for_agent", "Inspect Assets", "Assets"),
            ],
            suggested_agent_prompt=prompt,
        )

    if int(state["analysis_notebook_count"]) == 0:
        latest_run_id = state.get("latest_successful_run_id")
        primary_action = (
            _endpoint_action(
                "generate_model_diagnostics_notebook",
                "Generate model diagnostics notebook",
                "Notebooks",
                f"/api/runs/{latest_run_id}/analysis-notebook",
            )
            if isinstance(latest_run_id, str)
            else _navigate_action("inspect_notebooks", "Open Notebooks", "Notebooks")
        )
        return _focus(
            focus_key="notebooks",
            target_tab="Notebooks",
            title="Generate notebook evidence",
            reason="Experiment evidence is easier to review when diagnostics, findings, and visual explanations are consolidated into native marimo notebook artifacts.",
            risk_level="medium",
            confidence=0.81,
            evidence=[f"{state['successful_run_count']} successful runs", "0 analysis notebooks"],
            primary_action=primary_action,
            secondary_actions=[
                _navigate_action("inspect_experiments_for_notebooks", "Inspect Experiments", "Leaderboard"),
                _navigate_action("inspect_leaderboard_for_notebooks", "Inspect Leaderboard", "Leaderboard"),
            ],
        )

    if int(state["report_count"]) == 0:
        return _focus(
            focus_key="reports",
            target_tab="Insight",
            title="Create the decision report",
            reason="Reports summarize readiness, risks, evidence, and next actions without requiring raw artifact inspection.",
            risk_level="medium",
            confidence=0.82,
            evidence=[f"{state['successful_run_count']} successful runs", "0 reports"],
            primary_action=_endpoint_action(
                "generate_decision_report",
                "Generate decision report",
                "Insight",
                f"/api/projects/{project.id}/decision-report/generate",
            ),
            secondary_actions=[
                _navigate_action("inspect_leaderboard", "Inspect Leaderboard", "Leaderboard"),
                _navigate_action("inspect_lineage", "Inspect Lineage", "Lineage"),
            ],
        )

    return _focus(
        focus_key="reports",
        target_tab="Insight",
        title="Read the decision report",
        reason="The project has enough evidence to review outcomes and decide the next controlled agent task.",
        risk_level="low",
        confidence=0.78,
        evidence=[f"{counts['reports']} reports", f"{state['successful_run_count']} successful runs"],
        primary_action=_navigate_action("read_reports", "Open Reports", "Insight"),
        secondary_actions=[
            _navigate_action("inspect_leaderboard_ready", "Inspect Leaderboard", "Leaderboard"),
            _agent_prompt_action(project.id, "plan_next_iteration", _next_iteration_prompt(project)),
        ],
    )


def _journey_stages(
    project: Project,
    counts: dict[str, int],
    state: dict[str, Any],
    focus: dict[str, Any],
) -> list[dict[str, Any]]:
    focus_key = str(focus["focus_key"])
    high_risk_count = int(state["unresolved_high_risk_assumption_count"])
    blocking_question_count = int(state["blocking_question_count"])
    evaluation_locked = int(state["approved_evaluation_spec_count"]) > 0 and int(state["split_manifest_count"]) > 0
    has_agent_planning = counts["ideas"] > 0 or counts["research_briefs"] > 0
    has_successful_run = int(state["successful_run_count"]) > 0
    has_notebook_source = int(state["analysis_notebook_count"]) > 0
    has_report = int(state["report_count"]) > 0

    data_status = "done" if state["has_dataset"] else "current"
    if state["has_understanding_report"]:
        understanding_status = "done"
    elif focus_key == "understand_data":
        understanding_status = "current"
    else:
        understanding_status = "waiting"
    if not state["has_understanding_report"]:
        assumption_status = "waiting"
    elif blocking_question_count > 0:
        assumption_status = "blocked"
    elif high_risk_count > 0:
        assumption_status = "current"
    else:
        assumption_status = "done"

    if evaluation_locked:
        evaluation_status = "done"
    elif not state["has_understanding_report"]:
        evaluation_status = "waiting"
    elif blocking_question_count > 0:
        evaluation_status = "blocked"
    elif focus_key == "evaluation":
        evaluation_status = "current"
    elif high_risk_count == 0:
        evaluation_status = "next"
    else:
        evaluation_status = "waiting"

    if has_successful_run or has_agent_planning:
        approach_status = "done"
    elif focus_key == "approach":
        approach_status = "current"
    elif evaluation_locked:
        approach_status = "next"
    else:
        approach_status = "waiting"

    if has_successful_run:
        experiments_status = "done"
    elif focus_key == "experiments":
        experiments_status = "current"
    elif evaluation_locked and has_agent_planning:
        experiments_status = "next"
    else:
        experiments_status = "waiting"

    if has_notebook_source:
        notebooks_status = "done"
    elif focus_key == "notebooks":
        notebooks_status = "current"
    elif has_successful_run:
        notebooks_status = "next"
    else:
        notebooks_status = "waiting"

    if has_report:
        reports_status = "done"
    elif focus_key == "reports":
        reports_status = "current"
    elif has_successful_run and has_notebook_source:
        reports_status = "next"
    else:
        reports_status = "waiting"

    focus_action_by_stage = {
        "data_intake": "upload_data",
        "understanding": "understand_data",
        "assumptions": "assumptions",
        "evaluation": "evaluation",
        "approach": "approach",
        "experiments": "experiments",
        "notebooks": "notebooks",
        "reports": "reports",
    }

    def stage_action(stage_id: str) -> dict[str, Any] | None:
        return focus["primary_action"] if focus_action_by_stage[stage_id] == focus_key else None

    return [
        _journey_stage(
            "data_intake",
            "Data",
            "Data",
            data_status,
            "Register the prediction data as a DatasetSnapshot before deeper guidance.",
            [f"{counts['datasets']} DatasetSnapshots", f"phase: {project.current_phase}"],
            stage_action("data_intake"),
        ),
        _journey_stage(
            "understanding",
            "Understanding",
            "Understanding",
            understanding_status,
            "Profile the data, summarize semantics, and surface target or leakage questions.",
            [
                "understanding report present" if state["has_understanding_report"] else "understanding report missing",
                "EDA profile present" if state["has_eda_profile"] else "EDA profile missing",
            ],
            stage_action("understanding"),
        ),
        _journey_stage(
            "assumptions",
            "Assumptions",
            "Assumptions",
            assumption_status,
            "Review only the assumptions that can change evaluation or feature safety.",
            [
                f"{high_risk_count} high-risk assumptions",
                f"{blocking_question_count} blocking questions",
            ],
            stage_action("assumptions"),
        ),
        _journey_stage(
            "evaluation",
            "Evaluation",
            "Evaluation",
            evaluation_status,
            "Lock an EvaluationSpec and SplitManifest before comparing model claims.",
            [
                f"{state['approved_evaluation_spec_count']} approved specs",
                f"{state['split_manifest_count']} split manifests",
            ],
            stage_action("evaluation"),
        ),
        _journey_stage(
            "approach",
            "Approach",
            "Home",
            approach_status,
            "Prepare an open-ended Codex/Skill handoff without forcing a fixed recipe.",
            [
                f"{counts['research_briefs']} research briefs",
                f"{counts['ideas']} ideas",
            ],
            stage_action("approach"),
        ),
        _journey_stage(
            "experiments",
            "Experiments",
            "Leaderboard",
            experiments_status,
            "Run or ingest evidence-producing experiments under the locked evaluation design.",
            [f"{state['successful_run_count']} successful runs", f"{counts['jobs']} jobs"],
            stage_action("experiments"),
        ),
        _journey_stage(
            "notebooks",
            "Notebooks",
            "Notebooks",
            notebooks_status,
            "Turn run evidence into inspectable native marimo notebooks and linked supporting artifacts.",
            [
                f"{state['analysis_notebook_count']} analysis notebooks",
                "native marimo is the primary viewer",
            ],
            stage_action("notebooks"),
        ),
        _journey_stage(
            "reports",
            "Reports",
            "Insight",
            reports_status,
            "Turn evidence, risks, diagnostics, and next actions into in-product reports.",
            [f"{state['report_count']} reports", f"{state['visualization_count']} visualizations"],
            stage_action("reports"),
        ),
    ]


def _journey_stage(
    stage_id: str,
    label: str,
    target_tab: str,
    status: str,
    summary: str,
    evidence: list[str],
    action: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "label": label,
        "target_tab": target_tab,
        "status": status,
        "summary": summary,
        "evidence": evidence,
        "action": action,
    }


def _current_journey_stage(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for status in ("blocked", "current", "next", "waiting"):
        for stage in stages:
            if stage["status"] == status:
                return stage
    return stages[-1] if stages else None


def _focus(
    *,
    focus_key: str,
    target_tab: str,
    title: str,
    reason: str,
    risk_level: str,
    confidence: float,
    evidence: list[str],
    primary_action: dict[str, Any],
    secondary_actions: list[dict[str, Any]],
    suggested_agent_prompt: str | None = None,
) -> dict[str, Any]:
    return {
        "focus_key": focus_key,
        "target_tab": target_tab,
        "title": title,
        "reason": reason,
        "risk_level": risk_level,
        "confidence": confidence,
        "evidence": evidence,
        "primary_action": primary_action,
        "secondary_actions": secondary_actions,
        "suggested_agent_prompt": suggested_agent_prompt,
    }


def _navigate_action(action_id: str, label: str, target_tab: str) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "target_tab": target_tab,
        "action_type": "navigate",
        "method": None,
        "endpoint": None,
        "request_body": None,
        "prompt": None,
        "disabled": False,
        "disabled_reason": None,
    }


def _endpoint_action(action_id: str, label: str, target_tab: str, endpoint: str) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "target_tab": target_tab,
        "action_type": "run_endpoint",
        "method": "POST",
        "endpoint": endpoint,
        "request_body": {},
        "prompt": None,
        "disabled": False,
        "disabled_reason": None,
    }


def _agent_prompt_action(project_id: str, action_id: str, prompt: str) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": "Create scoped AgentTask",
        "target_tab": "Home",
        "action_type": "agent_task_prompt",
        "method": "POST",
        "endpoint": f"/api/projects/{project_id}/approach/agent-task-plan",
        "request_body": {"task_type": "implement_prediction_approach", "objective": prompt},
        "prompt": prompt,
        "disabled": False,
        "disabled_reason": None,
    }


def _agent_guidance(state: dict[str, Any]) -> list[str]:
    guidance = [
        "Keep the user inside the product UI; use artifacts, reports, and lineage instead of external dashboards.",
        "Respect EvaluationSpec and SplitManifest before making model-improvement claims.",
        "Treat unanswered items as assumptions with explicit fallback policy instead of blocking by default.",
    ]
    if int(state["unresolved_high_risk_assumption_count"]) > 0:
        guidance.append("Review high-risk assumptions before asking Codex to generate feature or model code.")
    if int(state["successful_run_count"]) == 0 and int(state["split_manifest_count"]) > 0:
        guidance.append("Ask Codex for a flexible, evidence-backed approach rather than a fixed baseline recipe.")
    if int(state["successful_run_count"]) > 0 and int(state["analysis_notebook_count"]) == 0:
        guidance.append("Generate a marimo notebook before relying on final reports for experiment interpretation.")
    return guidance


def _data_intake_prompt(project: Project) -> str:
    return (
        f"Plan the data intake for project '{project.name}'. Identify likely tables, target timing, "
        "prediction grain, leakage risks, and the minimum artifacts the harness should capture before modeling."
    )


def _evaluation_prompt(project: Project) -> str:
    return (
        f"Review the evaluation design options for project '{project.name}'. Compare random, stratified, "
        "time, and group split risks, then recommend what evidence is needed before approving EvaluationSpec."
    )


def _approach_prompt(project: Project, state: dict[str, Any]) -> str:
    target = state.get("target_column") or "the eventual target"
    return (
        f"Design the next prediction approach for project '{project.name}' with target {target}. "
        "Use the approved EvaluationSpec and SplitManifest, current data understanding, assumptions, "
        "available artifacts, Skill/library references, and any timely research evidence. Propose a flexible "
        "baseline/modeling plan, feature strategy, diagnostics, visualizations, and report outputs without "
        "forcing a fixed recipe."
    )


def _next_iteration_prompt(project: Project) -> str:
    return (
        f"Review the current reports and experiment evidence for project '{project.name}', then propose the next "
        "controlled agent task with expected artifacts, evaluation constraints, diagnostics, and review criteria."
    )


def _count_project_rows(db: Session, model: Any, project_id: str, *conditions: Any) -> int:
    statement = select(func.count()).select_from(model).where(model.project_id == project_id)
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)
