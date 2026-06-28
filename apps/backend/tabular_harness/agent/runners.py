from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from tabular_harness.schemas import AgentResult, AgentTaskContract


class WorkspaceRef(BaseModel):
    project_id: str
    path: str
    git_commit: str | None = None


class ExecutionPolicy(BaseModel):
    sandbox: Literal["read_only", "workspace_write", "full_access"] = "workspace_write"
    network: Literal["disabled", "harness_only", "restricted", "full"] = "disabled"
    timeout_seconds: int = 1800
    max_retries: int = 0
    allow_secret_access: bool = False
    require_approval_for_external_network: bool = True
    require_approval_for_production_write: bool = True


class AgentRunner(ABC):
    @abstractmethod
    def run_task(
        self,
        workspace_ref: WorkspaceRef,
        task_contract: AgentTaskContract,
        output_schema: dict[str, Any],
        execution_policy: ExecutionPolicy,
    ) -> AgentResult:
        raise NotImplementedError


class NoopAgentRunner(AgentRunner):
    def run_task(
        self,
        workspace_ref: WorkspaceRef,
        task_contract: AgentTaskContract,
        output_schema: dict[str, Any],
        execution_policy: ExecutionPolicy,
    ) -> AgentResult:
        result = AgentResult(
            task_id=task_contract.task_id,
            status="succeeded",
            final_message="Noop runner accepted the task contract without executing agent code.",
            outputs={"workspace": workspace_ref.path, "runner": "noop"},
            artifacts=[],
            warnings=["No agent execution was performed."],
            requires_human_review=False,
        )
        validate_against_schema(result.model_dump(mode="json"), output_schema)
        return result


class LocalStubAgentRunner(NoopAgentRunner):
    def run_task(
        self,
        workspace_ref: WorkspaceRef,
        task_contract: AgentTaskContract,
        output_schema: dict[str, Any],
        execution_policy: ExecutionPolicy,
    ) -> AgentResult:
        report_md = render_stub_report(task_contract, execution_policy)
        feature_recipe = render_stub_feature_recipe(task_contract)
        experiment_metrics = render_stub_experiment_metrics(task_contract)
        visualization_spec = {
            "schema_version": "visualization_spec.v1",
            "title": "Agent Task Output Checklist",
            "chart_type": "artifact_checklist",
            "data": [
                {
                    "path": output.path,
                    "schema": output.schema_,
                    "status": "planned",
                }
                for output in task_contract.required_outputs
            ],
            "encoding": {
                "x": "path",
                "color": "schema",
                "tooltip": ["path", "schema", "status"],
            },
            "empty_state": "Agent task has no required outputs.",
        }
        result = AgentResult(
            task_id=task_contract.task_id,
            status="succeeded",
            final_message="Local stub runner generated an execution-ready plan without running agent code.",
            outputs={
                "workspace": workspace_ref.path,
                "runner": "local_stub",
                "report_md": report_md,
                "feature_recipe": feature_recipe,
                "experiment_metrics": experiment_metrics,
                "visualization_spec": visualization_spec,
            },
            artifacts=[
                {
                    "path": "reports/agent_task_report.md",
                    "asset_type": "agent_task_report",
                    "name": f"agent_task_report_{task_contract.task_id}",
                    "metadata": {"task_id": task_contract.task_id},
                },
                {
                    "path": "artifacts/feature_recipe.json",
                    "asset_type": "feature_recipe",
                    "name": f"agent_feature_recipe_{task_contract.task_id}",
                    "metadata": {"task_id": task_contract.task_id},
                },
                {
                    "path": "artifacts/experiment_metrics.json",
                    "asset_type": "experiment_metrics",
                    "name": f"agent_experiment_metrics_{task_contract.task_id}",
                    "metadata": {"task_id": task_contract.task_id},
                },
                {
                    "path": "artifacts/agent_result.json",
                    "asset_type": "agent_result",
                    "name": f"agent_result_{task_contract.task_id}",
                    "metadata": {"task_id": task_contract.task_id},
                },
                {
                    "path": "artifacts/visualization_spec.json",
                    "asset_type": "visualization_spec",
                    "name": f"agent_task_visualization_{task_contract.task_id}",
                    "metadata": {"task_id": task_contract.task_id},
                },
            ],
            warnings=["No Codex or external research execution was performed."],
            requires_human_review=True,
        )
        write_stub_workspace_outputs(
            workspace=Path(workspace_ref.path),
            report_md=report_md,
            feature_recipe=feature_recipe,
            experiment_metrics=experiment_metrics,
            visualization_spec=visualization_spec,
            result=result,
        )
        validate_against_schema(result.model_dump(mode="json"), output_schema)
        return result


class CodexCliRunner(AgentRunner):
    def __init__(self, codex_binary: str = "codex") -> None:
        self.codex_binary = codex_binary

    def run_task(
        self,
        workspace_ref: WorkspaceRef,
        task_contract: AgentTaskContract,
        output_schema: dict[str, Any],
        execution_policy: ExecutionPolicy,
    ) -> AgentResult:
        workspace = Path(workspace_ref.path).resolve()
        harness_dir = workspace / ".harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        contract_path = harness_dir / "task_contract.json"
        schema_path = harness_dir / "output_schema.json"
        contract_path.write_text(task_contract.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        schema_path.write_text(json.dumps(output_schema, indent=2, sort_keys=True), encoding="utf-8")

        result_path = workspace / "outputs" / "result.json"
        (workspace / "outputs").mkdir(exist_ok=True)
        cmd = [
            self.codex_binary,
            "exec",
            "--cd",
            str(workspace),
            "--sandbox",
            codex_sandbox(execution_policy.sandbox),
            "--output-schema",
            str(schema_path),
            "--skip-git-repo-check",
            "-",
        ]
        prompt = render_prompt(task_contract)
        completed = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=execution_policy.timeout_seconds,
            env=safe_env(workspace),
            check=False,
        )
        if completed.returncode != 0:
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI failed.",
                outputs={"returncode": completed.returncode},
                artifacts=[],
                warnings=[],
                failure_reason=completed.stderr[-4000:],
                raw_log_path=None,  # type: ignore[call-arg]
            )
        if not result_path.exists():
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI completed but outputs/result.json was not found.",
                outputs={"stdout_tail": completed.stdout[-4000:]},
                artifacts=[],
                warnings=[],
                failure_reason="missing_result_json",
            )
        data = json.loads(result_path.read_text(encoding="utf-8"))
        validate_against_schema(data, output_schema)
        return AgentResult.model_validate(data)


def validate_against_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    Draft202012Validator(schema).validate(data)


def write_stub_workspace_outputs(
    *,
    workspace: Path,
    report_md: str,
    feature_recipe: dict[str, Any],
    experiment_metrics: dict[str, Any],
    visualization_spec: dict[str, Any],
    result: AgentResult,
) -> None:
    reports_dir = workspace / "reports"
    artifacts_dir = workspace / "artifacts"
    reports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "agent_task_report.md").write_text(report_md, encoding="utf-8")
    (artifacts_dir / "feature_recipe.json").write_text(
        json.dumps(feature_recipe, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (artifacts_dir / "experiment_metrics.json").write_text(
        json.dumps(experiment_metrics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (artifacts_dir / "visualization_spec.json").write_text(
        json.dumps(visualization_spec, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (artifacts_dir / "agent_result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )


def render_stub_feature_recipe(contract: AgentTaskContract) -> dict[str, Any]:
    dataset_context = dict_value(contract.inputs.get("dataset_context"))
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    return {
        "recipe_version": "feature_recipe.v1",
        "recipe_name": "local_stub_planned_feature_recipe",
        "execution_status": "not_executed",
        "runner": "local_stub",
        "task_id": contract.task_id,
        "dataset_snapshot_id": dataset_context.get("dataset_snapshot_id"),
        "evaluation_spec_id": evaluation_contract.get("evaluation_spec_id"),
        "split_manifest_id": split_manifest_id(evaluation_contract),
        "feature_families": [
            {
                "name": "dataset_specific_features",
                "status": "planned",
                "notes": "Future runner should select features from project evidence, Skill assets, and approved evaluation constraints.",
            }
        ],
        "safety": {
            "fit_preprocessing_on_train_only": True,
            "must_respect_split_manifest": True,
            "validation_or_test_targets_forbidden": True,
            "secrets_forbidden": True,
        },
    }


def render_stub_experiment_metrics(contract: AgentTaskContract) -> dict[str, Any]:
    dataset_context = dict_value(contract.inputs.get("dataset_context"))
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    return {
        "schema_version": "experiment_metrics.v1",
        "execution_status": "not_executed",
        "model_code_executed": False,
        "runner": "local_stub",
        "task_id": contract.task_id,
        "dataset_snapshot_id": dataset_context.get("dataset_snapshot_id"),
        "evaluation_spec_id": evaluation_contract.get("evaluation_spec_id"),
        "split_manifest_id": split_manifest_id(evaluation_contract),
        "primary_metric_name": evaluation_contract.get("primary_metric"),
        "primary_metric_value": None,
        "secondary_metrics": {},
        "split_manifest_respected": bool(split_manifest_id(evaluation_contract)),
        "notes": [
            "LocalStubAgentRunner does not train or evaluate a model.",
            "This metrics artifact exists so the harness can test AgentResult ingestion without making benchmark claims.",
        ],
    }


def split_manifest_id(evaluation_contract: dict[str, Any]) -> str | None:
    raw_manifest = evaluation_contract.get("split_manifest")
    if not isinstance(raw_manifest, dict):
        return None
    value = raw_manifest.get("split_manifest_id")
    return value if isinstance(value, str) and value else None


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def codex_sandbox(policy: str) -> str:
    if policy == "read_only":
        return "read-only"
    if policy == "full_access":
        return "danger-full-access"
    return "workspace-write"


def render_prompt(contract: AgentTaskContract) -> str:
    return (
        "Execute the following harness task contract. Follow AGENTS.md, do not access secrets, "
        "and write the final result to outputs/result.json.\n\n"
        f"{contract.model_dump_json(by_alias=True, indent=2)}"
    )


def render_stub_report(contract: AgentTaskContract, policy: ExecutionPolicy) -> str:
    lines = [
        "# Agent Task Execution Plan",
        "",
        f"- Task: {contract.task_id}",
        f"- Type: {contract.task_type}",
        f"- Project: {contract.project_id}",
        f"- Autonomy level: {contract.autonomy_level if contract.autonomy_level is not None else 'not set'}",
        f"- Network policy: {policy.network}",
        f"- Sandbox: {policy.sandbox}",
        "",
        "## Objective",
        "",
        contract.objective,
        "",
        "## Inputs",
        "",
        "```json",
        json.dumps(contract.inputs, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Required Outputs",
    ]
    for output in contract.required_outputs:
        lines.append(f"- `{output.path}` ({output.schema_})")
    lines.extend(["", "## Quality Checks"])
    lines.extend([f"- {item}" for item in contract.quality_checks])
    lines.extend(["", "## Forbidden Actions"])
    lines.extend([f"- {item}" for item in contract.forbidden_actions])
    lines.extend(
        [
            "",
            "## Stub Result",
            "",
            "This is an execution-ready plan. It verifies contract shape, safety policy, and expected artifacts before a real runner is enabled.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def safe_env(workspace: Path) -> dict[str, str]:
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "OPENAI_API_KEY",
        "CODEX_HOME",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    isolated_home = workspace / ".harness" / "home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(isolated_home)
    env.setdefault("CODEX_HOME", str(workspace / ".harness" / "codex_home"))
    return env
