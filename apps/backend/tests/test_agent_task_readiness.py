from __future__ import annotations

from tabular_harness.models.entities import Artifact, Project
from tabular_harness.schemas import AgentRequiredOutput, AgentTaskContract
from tabular_harness.services.agent_task_readiness import build_readiness_review


def test_readiness_review_blocks_without_evaluation_split() -> None:
    project = Project(id="p_ready", name="Readiness", target_column="target", task_type="binary_classification")
    contract = AgentTaskContract(
        task_id="agt_ready",
        task_type="implement_prediction_approach",
        project_id=project.id,
        objective="Implement a controlled approach",
        inputs={
            "schema_version": "agent_task_planning.v1",
            "evaluation_contract": {
                "evaluation_spec_id": None,
                "split_manifest": None,
            },
            "assumption_context": {"high_risk_assumptions": [], "blocking_question_count": 0},
            "constraints": {
                "target_column": "target",
                "secret_access": "forbidden",
                "connector_credentials": "never_materialized",
            },
            "available_context_artifacts": [],
            "library_recommendations": [],
            "reporting_requirements": {"self_contained_ui": True},
            "artifact_expectations": [{"asset_type": "run_report"}],
            "must_respect_split_manifest": True,
        },
        required_outputs=[
            AgentRequiredOutput(path="reports/approach_report.md", schema="markdown_report.v1"),
            AgentRequiredOutput(path="artifacts/experiment_metrics.json", schema="experiment_metrics.v1"),
            AgentRequiredOutput(path="artifacts/visualization_spec.json", schema="visualization_spec.v1"),
        ],
        quality_checks=["Use harness evaluation."],
        forbidden_actions=["Do not read secrets.", "Do not use connector credentials."],
    )
    contract_artifact = Artifact(
        id="art_contract",
        project_id=project.id,
        asset_type="agent_task_contract",
        name="contract",
        version=1,
        uri="/tmp/contract",
        content_hash="hash",
    )

    review = build_readiness_review(
        project=project,
        contract=contract,
        contract_artifact=contract_artifact,
        workspace_artifact=None,
        workspace_manifest=None,
    )

    assert review["schema_version"] == "agent_task_readiness_review.v1"
    assert review["status"] == "blocked"
    assert review["blocker_count"] >= 1
    assert any(item["check_id"] == "evaluation_contract" for item in review["checks"])
    assert "Approve an EvaluationSpec" in " ".join(review["next_actions"])


def test_notebook_authoring_readiness_warns_without_target_or_evaluation() -> None:
    project = Project(id="p_notebook_ready", name="Notebook Readiness", target_column=None, task_type="unknown")
    contract = AgentTaskContract(
        task_id="agt_notebook_ready",
        task_type="author_analysis_notebook",
        project_id=project.id,
        objective="Write a human-facing analysis notebook.",
        inputs={
            "schema_version": "agent_task_planning.v1",
            "evaluation_contract": {
                "evaluation_spec_id": None,
                "split_manifest": None,
            },
            "assumption_context": {"high_risk_assumptions": [], "blocking_question_count": 0},
            "constraints": {
                "target_column": None,
                "secret_access": "forbidden",
                "connector_credentials": "never_materialized",
            },
            "available_context_artifacts": [{"role": "eda_review_bundle", "artifact_id": "art_eda"}],
            "library_recommendations": [],
            "reporting_requirements": {"self_contained_ui": True},
            "artifact_expectations": [{"asset_type": "analysis_notebook"}],
            "must_respect_split_manifest": True,
        },
        required_outputs=[
            AgentRequiredOutput(path="notebooks/tablex_analysis_notebook.py", schema="marimo_notebook.v1"),
            AgentRequiredOutput(path="reports/notebook_authoring_report.md", schema="markdown_report.v1"),
            AgentRequiredOutput(path="artifacts/notebook_figure_manifest.json", schema="notebook_figure_manifest.v1"),
            AgentRequiredOutput(path="artifacts/notebook_evidence_bundle.json", schema="notebook_evidence_bundle.v1"),
            AgentRequiredOutput(path="artifacts/notebook_quality_review.json", schema="notebook_quality_review.v1"),
        ],
        quality_checks=["Read notebook_authoring_brief first."],
        forbidden_actions=["Do not read secrets.", "Do not use connector credentials."],
    )
    contract_artifact = Artifact(
        id="art_notebook_contract",
        project_id=project.id,
        asset_type="agent_task_contract",
        name="contract",
        version=1,
        uri="/tmp/contract",
        content_hash="hash",
    )

    review = build_readiness_review(
        project=project,
        contract=contract,
        contract_artifact=contract_artifact,
        workspace_artifact=None,
        workspace_manifest=None,
    )

    assert review["status"] == "ready_with_warnings"
    assert review["blocker_count"] == 0
    checks = {item["check_id"]: item for item in review["checks"]}
    assert checks["target_context"]["status"] == "warning"
    assert checks["evaluation_contract"]["status"] == "warning"
    assert checks["required_outputs"]["status"] == "pass"
