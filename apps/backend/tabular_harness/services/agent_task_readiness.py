from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Job,
    Project,
    Report,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.schemas import AgentTaskContract
from tabular_harness.services.agent_task_planner import validate_agent_task_contract
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.planned_agent_workspace import load_contract_payload
from tabular_harness.services.reporting import persist_visualization_spec


@dataclass(frozen=True)
class AgentTaskReadinessResult:
    review: dict[str, Any]
    review_artifact: Artifact
    report: Report
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def review_agent_task_readiness(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    contract_artifact: Artifact,
    job: Job | None = None,
) -> AgentTaskReadinessResult:
    contract_payload = load_contract_payload(contract_artifact)
    validate_agent_task_contract(contract_payload)
    contract = AgentTaskContract.model_validate(contract_payload)
    if contract.project_id != project.id:
        raise ValueError("AgentTaskContract project_id does not match the requested project")

    workspace_artifact = latest_workspace_manifest_for_contract(db, project.id, contract_artifact.id)
    workspace_manifest = load_workspace_manifest(workspace_artifact)
    review = build_readiness_review(
        project=project,
        contract=contract,
        contract_artifact=contract_artifact,
        workspace_artifact=workspace_artifact,
        workspace_manifest=workspace_manifest,
    )
    review_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_task_readiness_review",
        name=f"agent_task_readiness_review_{contract.task_id}_{new_id('atr')}",
        filename="agent_task_readiness_review.json",
        payload=review,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "task_id": contract.task_id,
            "source_contract_artifact_id": contract_artifact.id,
            "workspace_artifact_id": workspace_artifact.id if workspace_artifact else None,
            "readiness_status": review["status"],
            "blocker_count": review["blocker_count"],
            "warning_count": review["warning_count"],
        },
    )
    report_md = render_readiness_report(review)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_task_readiness_report",
        name=f"agent_task_readiness_report_{contract.task_id}_{new_id('atrr')}",
        filename="agent_task_readiness_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "job_id": job.id if job else None,
            "task_id": contract.task_id,
            "source_contract_artifact_id": contract_artifact.id,
            "readiness_status": review["status"],
            "report_type": "agent_task_readiness_report",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="agent_task_readiness_report",
        title=f"Agent Task Readiness: {contract.task_id}",
        summary=readiness_summary(review),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "artifact", "asset_id": contract_artifact.id},
                *(
                    [{"asset_type": "artifact", "asset_id": workspace_artifact.id}]
                    if workspace_artifact
                    else []
                ),
            ]
        ),
        status="draft",
        created_by_type="system",
    )
    db.add(report)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=build_readiness_visualization_spec(review),
        source_artifact_id=review_artifact.id,
    )
    create_readiness_lineage(
        db,
        project=project,
        job=job,
        contract_artifact=contract_artifact,
        workspace_artifact=workspace_artifact,
        review_artifact=review_artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
    )
    artifact_ids = [review_artifact.id, report_artifact.id, visualization_artifact.id]
    return AgentTaskReadinessResult(
        review=review,
        review_artifact=review_artifact,
        report=report,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def build_readiness_review(
    *,
    project: Project,
    contract: AgentTaskContract,
    contract_artifact: Artifact,
    workspace_artifact: Artifact | None,
    workspace_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = contract.inputs
    evaluation_contract = dict_value(inputs.get("evaluation_contract"))
    assumption_context = dict_value(inputs.get("assumption_context"))
    constraints = dict_value(inputs.get("constraints"))
    checks = [
        contract_schema_check(contract),
        target_context_check(project, constraints),
        evaluation_check(evaluation_contract),
        required_outputs_check(contract),
        safety_check(contract, constraints),
        assumptions_check(assumption_context),
        context_artifacts_check(inputs),
        strategy_context_check(inputs, workspace_manifest),
        relational_context_check(inputs, workspace_manifest),
        library_assets_check(inputs, workspace_manifest),
        workspace_check(workspace_artifact, workspace_manifest),
        reporting_check(inputs),
    ]
    blocker_count = sum(1 for check in checks if check["status"] == "blocker")
    warning_count = sum(1 for check in checks if check["status"] == "warning")
    status = "blocked" if blocker_count else "ready_with_warnings" if warning_count else "ready"
    return {
        "schema_version": "agent_task_readiness_review.v1",
        "project_id": project.id,
        "project_name": project.name,
        "task_id": contract.task_id,
        "contract_artifact_id": contract_artifact.id,
        "workspace_artifact_id": workspace_artifact.id if workspace_artifact else None,
        "status": status,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
        "next_actions": next_actions(checks),
        "reviewed_at": utc_now().isoformat(),
    }


def contract_schema_check(contract: AgentTaskContract) -> dict[str, Any]:
    return check(
        "contract_schema",
        "AgentTaskContract schema",
        "pass",
        "info",
        f"Contract `{contract.task_id}` is schema-valid.",
    )


def target_context_check(project: Project, constraints: dict[str, Any]) -> dict[str, Any]:
    target = constraints.get("target_column") or project.target_column
    if not target:
        return check(
            "target_context",
            "Target column",
            "blocker",
            "high",
            "Target column is not available in project or contract constraints.",
            "Set or confirm the target column before execution.",
        )
    return check("target_context", "Target column", "pass", "info", f"Target column is `{target}`.")


def evaluation_check(evaluation_contract: dict[str, Any]) -> dict[str, Any]:
    spec_id = evaluation_contract.get("evaluation_spec_id")
    split_manifest = evaluation_contract.get("split_manifest")
    split_id = split_manifest.get("split_manifest_id") if isinstance(split_manifest, dict) else None
    if not spec_id or not split_id:
        return check(
            "evaluation_contract",
            "EvaluationSpec and SplitManifest",
            "blocker",
            "high",
            "Approved evaluation context or SplitManifest is missing.",
            "Approve an EvaluationSpec and generate a SplitManifest before runner execution.",
        )
    return check(
        "evaluation_contract",
        "EvaluationSpec and SplitManifest",
        "pass",
        "info",
        f"EvaluationSpec `{spec_id}` and SplitManifest `{split_id}` are present.",
    )


def required_outputs_check(contract: AgentTaskContract) -> dict[str, Any]:
    paths = [item.path for item in contract.required_outputs]
    missing_categories = []
    if not any("report" in path for path in paths):
        missing_categories.append("report")
    if not any("metric" in path for path in paths):
        missing_categories.append("metrics")
    if not any("visualization" in path for path in paths):
        missing_categories.append("visualization")
    if missing_categories:
        return check(
            "required_outputs",
            "Required outputs",
            "warning",
            "medium",
            f"Required outputs are missing expected categories: {', '.join(missing_categories)}.",
            "Update the contract required_outputs before execution if these outputs are required.",
        )
    return check(
        "required_outputs",
        "Required outputs",
        "pass",
        "info",
        f"{len(contract.required_outputs)} required outputs are declared.",
    )


def safety_check(contract: AgentTaskContract, constraints: dict[str, Any]) -> dict[str, Any]:
    forbidden_text = " ".join(contract.forbidden_actions).lower()
    secret_ok = constraints.get("secret_access") == "forbidden" and "secret" in forbidden_text
    credential_ok = (
        constraints.get("connector_credentials") in {"never_materialized", "not_materialized"}
        and "credential" in forbidden_text
    )
    split_ok = bool(contract.inputs.get("must_respect_split_manifest", True))
    if not (secret_ok and credential_ok and split_ok):
        return check(
            "safety_constraints",
            "Safety constraints",
            "blocker",
            "high",
            "Secret, credential, or SplitManifest safety constraints are incomplete.",
            "Regenerate or edit the contract so runner safety policy is explicit.",
        )
    return check(
        "safety_constraints",
        "Safety constraints",
        "pass",
        "info",
        "Secret access, connector credential handling, and SplitManifest policy are explicit.",
    )


def assumptions_check(assumption_context: dict[str, Any]) -> dict[str, Any]:
    high_risk = list_value(assumption_context.get("high_risk_assumptions"))
    blocking_count = int_value(assumption_context.get("blocking_question_count"))
    if blocking_count > 0:
        return check(
            "assumptions_questions",
            "Assumptions and questions",
            "blocker",
            "high",
            f"{blocking_count} open question(s) have block_until_answered policy.",
            "Answer or downgrade blocking questions before execution.",
        )
    if high_risk:
        return check(
            "assumptions_questions",
            "Assumptions and questions",
            "warning",
            "medium",
            f"{len(high_risk)} high-risk assumption(s) remain unresolved.",
            "Review high-risk assumptions and fallback policies before trusting results.",
        )
    return check(
        "assumptions_questions",
        "Assumptions and questions",
        "pass",
        "info",
        "No blocking questions or high-risk assumptions are present in the contract context.",
    )


def context_artifacts_check(inputs: dict[str, Any]) -> dict[str, Any]:
    context_artifacts = list_value(inputs.get("available_context_artifacts"))
    if not context_artifacts:
        return check(
            "context_artifacts",
            "Context artifacts",
            "warning",
            "medium",
            "No context artifacts are attached to the contract.",
            "Generate understanding, data quality, research, or evaluation artifacts before execution.",
        )
    return check(
        "context_artifacts",
        "Context artifacts",
        "pass",
        "info",
        f"{len(context_artifacts)} context artifact reference(s) are available.",
    )


def strategy_context_check(inputs: dict[str, Any], workspace_manifest: dict[str, Any] | None) -> dict[str, Any]:
    strategy_context = dict_value(inputs.get("adaptive_strategy_brief"))
    artifact_id = strategy_context.get("artifact_id")
    if not artifact_id:
        return check(
            "adaptive_strategy_context",
            "Adaptive Strategy Brief",
            "warning",
            "low",
            "No Adaptive Strategy Brief is attached to the AgentTaskContract.",
            "Create an Adaptive Strategy Brief before planning the next AgentTask when strategy guidance exists.",
        )
    if workspace_manifest is not None and not materialized_artifact_id(workspace_manifest, str(artifact_id)):
        return check(
            "adaptive_strategy_context",
            "Adaptive Strategy Brief",
            "warning",
            "medium",
            "Adaptive Strategy Brief is attached to the contract but was not materialized in the workspace.",
            "Run Prepare Workspace again so Codex receives the same strategy guidance shown in the UI.",
        )
    return check(
        "adaptive_strategy_context",
        "Adaptive Strategy Brief",
        "pass",
        "info",
        "Adaptive Strategy Brief is attached for open-ended Codex handoff.",
    )


def relational_context_check(inputs: dict[str, Any], workspace_manifest: dict[str, Any] | None) -> dict[str, Any]:
    relational_inputs = [
        dict_value(inputs.get("relational_feature_plan")),
        dict_value(inputs.get("relational_feature_recipe")),
        dict_value(inputs.get("relational_feature_scenario_diagnostics")),
    ]
    expected_ids = [
        str(item["artifact_id"])
        for item in relational_inputs
        if isinstance(item.get("artifact_id"), str) and item.get("artifact_id")
    ]
    available_context = list_value(inputs.get("available_context_artifacts"))
    expected_ids.extend(
        [
            str(item["artifact_id"])
            for item in available_context
            if isinstance(item, dict)
            and str(item.get("role") or "").startswith("relational_")
            and isinstance(item.get("artifact_id"), str)
            and item.get("artifact_id")
        ]
    )
    expected_count = len(set(expected_ids))
    materialized = materialized_source_count(workspace_manifest, "relational_context_artifact")
    if expected_count == 0:
        return check(
            "relational_context",
            "Relational runner context",
            "pass",
            "info",
            "No relational feature context is attached to this contract.",
        )
    if workspace_manifest is None:
        return check(
            "relational_context",
            "Relational runner context",
            "warning",
            "medium",
            f"{expected_count} relational context artifact(s) are attached, but no workspace is prepared.",
            "Run Prepare Workspace so relational plan, recipe, preview, diagnostics, and reports are materialized.",
        )
    if materialized == 0:
        return check(
            "relational_context",
            "Relational runner context",
            "warning",
            "medium",
            "Relational context is attached to the contract, but no relational files were materialized.",
            "Prepare the workspace again and inspect skipped sources before running an AgentRunner.",
        )
    return check(
        "relational_context",
        "Relational runner context",
        "pass",
        "info",
        f"{materialized} relational context artifact(s) are materialized in the controlled workspace.",
    )


def library_assets_check(inputs: dict[str, Any], workspace_manifest: dict[str, Any] | None) -> dict[str, Any]:
    recommendations = list_value(inputs.get("library_recommendations"))
    materialized = materialized_source_count(workspace_manifest, "library_asset")
    if not recommendations:
        return check(
            "library_assets",
            "Library assets",
            "warning",
            "medium",
            "No Skill or reusable asset recommendations are attached.",
            "Seed or attach relevant Skill/FeatureRecipe assets before execution.",
        )
    if workspace_manifest is not None and materialized == 0:
        return check(
            "library_assets",
            "Library assets",
            "warning",
            "medium",
            "Library assets are recommended but none are materialized in the workspace.",
            "Prepare the workspace again or inspect skipped sources.",
        )
    summary = (
        f"{len(recommendations)} library recommendation(s)"
        + (f" and {materialized} materialized asset(s)." if workspace_manifest else ".")
    )
    return check("library_assets", "Library assets", "pass", "info", summary)


def workspace_check(
    workspace_artifact: Artifact | None,
    workspace_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    if workspace_artifact is None or workspace_manifest is None:
        return check(
            "workspace_manifest",
            "Controlled workspace",
            "warning",
            "medium",
            "No prepared workspace manifest exists for this contract.",
            "Run Prepare Workspace before starting an AgentRunner.",
        )
    files = list_value(workspace_manifest.get("files"))
    required_files = {".harness/task_contract.json", ".harness/agent_result.schema.json", ".harness/execution_policy.json"}
    missing = sorted(required_files.difference({str(item) for item in files}))
    if missing:
        return check(
            "workspace_manifest",
            "Controlled workspace",
            "blocker",
            "high",
            f"Workspace manifest is missing required files: {', '.join(missing)}.",
            "Regenerate the controlled workspace.",
        )
    return check(
        "workspace_manifest",
        "Controlled workspace",
        "pass",
        "info",
        f"Workspace manifest `{workspace_artifact.id}` includes required harness files.",
    )


def reporting_check(inputs: dict[str, Any]) -> dict[str, Any]:
    requirements = dict_value(inputs.get("reporting_requirements"))
    expectations = list_value(inputs.get("artifact_expectations"))
    if not requirements or not expectations:
        return check(
            "reporting_artifacts",
            "Reporting and artifact expectations",
            "warning",
            "medium",
            "Reporting requirements or artifact expectations are missing.",
            "Regenerate the contract before execution to preserve UI-complete outputs.",
        )
    return check(
        "reporting_artifacts",
        "Reporting and artifact expectations",
        "pass",
        "info",
        f"{len(expectations)} artifact expectation(s) and reporting requirements are present.",
    )


def check(
    check_id: str,
    title: str,
    status: str,
    severity: str,
    summary: str,
    action: str | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "title": title,
        "status": status,
        "severity": severity,
        "summary": summary,
        "action": action,
    }


def next_actions(checks: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in checks:
        action = item.get("action")
        if isinstance(action, str) and action and action not in actions:
            actions.append(action)
    return actions


def build_readiness_visualization_spec(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "visualization_spec.v1",
        "title": f"Agent Task Readiness: {review['task_id']}",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": item["title"],
                "status": "ready" if item["status"] == "pass" else item["status"],
                "count": 1,
                "detail": item["summary"],
            }
            for item in review["checks"]
        ],
        "encoding": {"stage": "stage", "status": "status", "detail": "detail"},
        "empty_state": "No readiness checks are available.",
    }


def render_readiness_report(review: dict[str, Any]) -> str:
    lines = [
        "# Agent Task Readiness Review",
        "",
        f"- Task: {review['task_id']}",
        f"- Status: {review['status']}",
        f"- Contract artifact: {review['contract_artifact_id']}",
        f"- Workspace artifact: {review.get('workspace_artifact_id') or 'missing'}",
        f"- Blockers: {review['blocker_count']}",
        f"- Warnings: {review['warning_count']}",
        "",
        "## Checks",
    ]
    for item in review["checks"]:
        lines.extend(
            [
                f"### {item['title']}",
                "",
                f"- Status: {item['status']}",
                f"- Severity: {item['severity']}",
                f"- Summary: {item['summary']}",
            ]
        )
        if item.get("action"):
            lines.append(f"- Action: {item['action']}")
        lines.append("")
    lines.append("## Next Actions")
    if review["next_actions"]:
        lines.extend([f"- {action}" for action in review["next_actions"]])
    else:
        lines.append("- No blocking next actions.")
    return "\n".join(lines).strip() + "\n"


def readiness_summary(review: dict[str, Any]) -> str:
    return (
        f"Agent task `{review['task_id']}` readiness is {review['status']} "
        f"with {review['blocker_count']} blockers and {review['warning_count']} warnings."
    )


def latest_workspace_manifest_for_contract(
    db: Session,
    project_id: str,
    contract_artifact_id: str,
) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_workspace_manifest")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source_contract_artifact_id") == contract_artifact_id:
            return artifact
    return None


def load_workspace_manifest(artifact: Artifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else None


def create_readiness_lineage(
    db: Session,
    *,
    project: Project,
    job: Job | None,
    contract_artifact: Artifact,
    workspace_artifact: Artifact | None,
    review_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    visualization: VisualizationSpec,
) -> None:
    if job:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=review_artifact.id,
            relation_type="produces",
        )
    for source in [contract_artifact, workspace_artifact]:
        if source is None:
            continue
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=source.id,
            to_asset_type="artifact",
            to_asset_id=review_artifact.id,
            relation_type="reviewed_by",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=review_artifact.id,
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
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=review_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="visualized_by",
    )


def materialized_source_count(workspace_manifest: dict[str, Any] | None, source_kind: str) -> int:
    if workspace_manifest is None:
        return 0
    return sum(
        1
        for item in list_value(workspace_manifest.get("materialized_sources"))
        if isinstance(item, dict) and item.get("source_kind") == source_kind
    )


def materialized_artifact_id(workspace_manifest: dict[str, Any] | None, artifact_id: str) -> bool:
    if workspace_manifest is None:
        return False
    return any(
        isinstance(item, dict) and item.get("artifact_id") == artifact_id
        for item in list_value(workspace_manifest.get("materialized_sources"))
    )


def dict_value(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def int_value(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0
