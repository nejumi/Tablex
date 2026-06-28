from __future__ import annotations

from pathlib import Path

from tabular_harness.agent import ExecutionPolicy, NoopAgentRunner, WorkspaceRef
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
