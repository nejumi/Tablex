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
