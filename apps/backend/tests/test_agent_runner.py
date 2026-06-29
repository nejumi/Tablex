from __future__ import annotations

from pathlib import Path

from tabular_harness.agent import (
    ExecutionPolicy,
    LocalStubAgentRunner,
    NoopAgentRunner,
    WorkspaceRef,
)
from tabular_harness.schemas import AgentRequiredOutput, AgentTaskContract


def test_noop_agent_runner_validates_agent_result_schema(tmp_path: Path) -> None:
    contract = AgentTaskContract(
        task_id="task_001",
        task_type="draft_data_understanding",
        project_id="p_001",
        objective="Return a stub result",
        inputs={},
        required_outputs=[
            AgentRequiredOutput(path="outputs/result.json", schema="schemas/agent_result.schema.json")
        ],
        quality_checks=["split_manifestを尊重する"],
        forbidden_actions=["secretを読む"],
    )
    output_schema = {
        "type": "object",
        "required": ["task_id", "status", "final_message", "outputs", "artifacts", "warnings"],
        "properties": {
            "task_id": {"type": "string"},
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval"]},
            "final_message": {"type": "string"},
            "outputs": {"type": "object"},
            "artifacts": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }

    result = NoopAgentRunner().run_task(
        WorkspaceRef(project_id="p_001", path=str(tmp_path)),
        contract,
        output_schema,
        ExecutionPolicy(),
    )

    assert result.status == "succeeded"
    assert result.outputs["runner"] == "noop"


def test_local_stub_agent_runner_emits_notebook_authoring_plan(tmp_path: Path) -> None:
    contract = AgentTaskContract(
        task_id="task_notebook",
        task_type="author_analysis_notebook",
        project_id="p_001",
        objective="Write a high-quality analysis notebook on the fly.",
        inputs={
            "dataset_context": {
                "dataset_snapshot_id": "ds_001",
                "row_count": 100,
                "column_count": 12,
                "target_column": "target",
            },
            "evaluation_contract": {"evaluation_spec_id": "eval_001", "primary_metric": "roc_auc"},
            "notebook_authoring": {
                "artifact_id": "art_brief",
                "objective": "Create a GM-style reader journey from current evidence.",
                "source_inspirations": [
                    {
                        "title": "Kaggle interview: Heads or Tails",
                        "runner_use": "Use as craft guidance for EDA-before-modeling narrative depth.",
                    }
                ],
                "authoring_principles": [
                    {
                        "principle": "EDA is an argument, not a gallery",
                        "implementation": "Every chart answers a question and ends with a next action.",
                    }
                ],
                "context_artifacts": [
                    {"role": "eda_review_bundle", "artifact_id": "art_eda", "asset_type": "eda_review_bundle"}
                ],
            },
        },
        required_outputs=[
            AgentRequiredOutput(path="notebooks/tablex_analysis_notebook.py", schema="marimo_notebook.v1")
        ],
        quality_checks=["Read notebook_authoring_brief first."],
        forbidden_actions=["Do not read secrets."],
    )
    output_schema = {
        "type": "object",
        "required": ["task_id", "status", "final_message", "outputs", "artifacts", "warnings"],
        "properties": {
            "task_id": {"type": "string"},
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval"]},
            "final_message": {"type": "string"},
            "outputs": {"type": "object"},
            "artifacts": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }

    result = LocalStubAgentRunner().run_task(
        WorkspaceRef(project_id="p_001", path=str(tmp_path)),
        contract,
        output_schema,
        ExecutionPolicy(),
    )

    assert result.status == "succeeded"
    assert result.outputs["notebook_authoring_plan"]
    assert any(item["asset_type"] == "notebook_authoring_plan" for item in result.artifacts)
    plan_path = tmp_path / "reports" / "notebook_authoring_plan.md"
    assert plan_path.exists()
    plan = plan_path.read_text(encoding="utf-8")
    assert "EDA is an argument" in plan
    assert "art_eda" in plan
