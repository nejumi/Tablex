from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from tabular_harness.schemas import AgentResult, AgentTaskContract
from tabular_harness.services.codex_transcript import build_codex_cli_transcript

CODEX_HARNESS_CONFIG_ARGS = ("-c", "mcp_servers={}")


def codex_harness_config_args(
    *,
    network_enabled: bool = False,
    web_search_enabled: bool = False,
) -> tuple[str, ...]:
    args = list(CODEX_HARNESS_CONFIG_ARGS)
    if web_search_enabled:
        args.extend(["-c", 'web_search="live"'])
    return tuple(args)


def codex_harness_config_args_for_policy(execution_policy: ExecutionPolicy) -> tuple[str, ...]:
    network_enabled = execution_policy.network in {"restricted", "full"}
    web_search_enabled = execution_policy.network == "full"
    return codex_harness_config_args(
        network_enabled=network_enabled,
        web_search_enabled=web_search_enabled,
    )


class WorkspaceRef(BaseModel):
    project_id: str
    path: str
    git_commit: str | None = None
    context_summary: dict[str, Any] | None = None


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
        context_summary = workspace_ref.context_summary or {}
        relational_context = dict_value(context_summary.get("relational_context"))
        has_relational_context = bool(relational_context.get("source_count"))
        report_md = render_stub_report(task_contract, execution_policy, relational_context)
        feature_recipe = render_stub_feature_recipe(task_contract, relational_context)
        experiment_metrics = render_stub_experiment_metrics(task_contract, relational_context)
        approach_decision_trace = render_stub_approach_decision_trace(task_contract, relational_context)
        source_citation_manifest = render_stub_source_citation_manifest(task_contract, execution_policy)
        citation_audit_report = render_stub_citation_audit_report(source_citation_manifest)
        citation_visualization_spec = render_stub_citation_visualization(source_citation_manifest)
        notebook_authoring_plan = (
            render_stub_notebook_authoring_plan(task_contract)
            if task_contract.task_type == "author_analysis_notebook"
            else None
        )
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
        relational_visualization_spec = (
            render_stub_relational_context_visualization(relational_context) if has_relational_context else None
        )
        output_artifacts = [
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
            {
                "path": "artifacts/source_citation_manifest.json",
                "asset_type": "source_citation_manifest",
                "name": f"source_citation_manifest_{task_contract.task_id}",
                "metadata": {"task_id": task_contract.task_id},
            },
            {
                "path": "artifacts/approach_decision_trace.json",
                "asset_type": "approach_decision_trace",
                "name": f"approach_decision_trace_{task_contract.task_id}",
                "metadata": {
                    "task_id": task_contract.task_id,
                    "policy": approach_decision_trace["autonomy_policy"].get("approach_selection"),
                    "advisory_not_prescriptive": True,
                },
            },
            {
                "path": "reports/citation_audit_report.md",
                "asset_type": "citation_audit_report",
                "name": f"citation_audit_report_{task_contract.task_id}",
                "metadata": {"task_id": task_contract.task_id},
            },
            {
                "path": "artifacts/citation_visualization_spec.json",
                "asset_type": "visualization_spec",
                "name": f"citation_visualization_{task_contract.task_id}",
                "metadata": {"task_id": task_contract.task_id, "visualization_role": "citation_audit"},
            },
        ]
        if has_relational_context:
            output_artifacts.extend(
                [
                    {
                        "path": "artifacts/relational_context_summary.json",
                        "asset_type": "relational_runner_context_summary",
                        "name": f"relational_runner_context_summary_{task_contract.task_id}",
                        "metadata": {
                            "task_id": task_contract.task_id,
                            "source_count": relational_context.get("source_count"),
                        },
                    },
                    {
                        "path": "artifacts/relational_context_visualization_spec.json",
                        "asset_type": "visualization_spec",
                        "name": f"relational_context_visualization_{task_contract.task_id}",
                        "metadata": {
                            "task_id": task_contract.task_id,
                            "visualization_role": "relational_runner_context",
                        },
                    },
                ]
            )
        if notebook_authoring_plan is not None:
            output_artifacts.append(
                {
                    "path": "reports/notebook_authoring_plan.md",
                    "asset_type": "notebook_authoring_plan",
                    "name": f"notebook_authoring_plan_{task_contract.task_id}",
                    "metadata": {
                        "task_id": task_contract.task_id,
                        "task_type": task_contract.task_type,
                        "notebook_authoring_brief_artifact_id": dict_value(
                            task_contract.inputs.get("notebook_authoring")
                        ).get("artifact_id"),
                    },
                }
            )
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
                "source_citation_manifest": source_citation_manifest,
                "citation_audit_report": citation_audit_report,
                "notebook_authoring_plan": notebook_authoring_plan,
                "relational_context_summary": relational_context if has_relational_context else None,
                "approach_decision_trace": approach_decision_trace,
            },
            artifacts=output_artifacts,
            warnings=["No Codex or external research execution was performed."],
            evidence_sources=source_citation_manifest["evidence_sources"],
            citations=source_citation_manifest["citations"],
            report_citations=source_citation_manifest["report_citations"],
            requires_human_review=True,
        )
        write_stub_workspace_outputs(
            workspace=Path(workspace_ref.path),
            report_md=report_md,
            feature_recipe=feature_recipe,
            experiment_metrics=experiment_metrics,
            visualization_spec=visualization_spec,
            source_citation_manifest=source_citation_manifest,
            approach_decision_trace=approach_decision_trace,
            citation_audit_report=citation_audit_report,
            citation_visualization_spec=citation_visualization_spec,
            notebook_authoring_plan=notebook_authoring_plan,
            relational_context_summary=relational_context if has_relational_context else None,
            relational_visualization_spec=relational_visualization_spec,
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
        last_message_path = harness_dir / "codex_last_message.md"
        (workspace / "outputs").mkdir(exist_ok=True)
        prompt = render_prompt(task_contract)
        config_args = codex_harness_config_args_for_policy(execution_policy)

        def build_command(*, include_output_schema: bool) -> list[str]:
            cmd = [
                self.codex_binary,
                "exec",
                *config_args,
                "--cd",
                str(workspace),
                "--json",
            ]
            if include_output_schema:
                cmd.extend(["--output-schema", str(schema_path)])
            cmd.extend(
                [
                    "--output-last-message",
                    str(last_message_path),
                    "--skip-git-repo-check",
                    "-",
                ]
            )
            return cmd

        cmd = build_command(include_output_schema=True)
        command_summary = " ".join(cmd[:-1] + ["-"])
        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=execution_policy.timeout_seconds,
                env=safe_env(
                    workspace,
                    sandbox=execution_policy.sandbox,
                    network_enabled=execution_policy.network in {"restricted", "full"},
                ),
                check=False,
            )
        except FileNotFoundError:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            transcript = build_codex_cli_transcript(
                status="codex_binary_not_found",
                codex_binary=self.codex_binary,
                command=command_summary,
                duration_ms=duration_ms,
            )
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI binary was not found.",
                outputs={
                    "runner": "codex_cli",
                    "codex_cli": transcript,
                },
                artifacts=[],
                warnings=[],
                failure_reason="codex_binary_not_found",
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            transcript = build_codex_cli_transcript(
                status="timeout",
                command=command_summary,
                timeout_seconds=execution_policy.timeout_seconds,
                duration_ms=duration_ms,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=exc.stderr if isinstance(exc.stderr, str) else "",
            )
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI timed out.",
                outputs={
                    "runner": "codex_cli",
                    "codex_cli": transcript,
                },
                artifacts=[],
                warnings=[],
                failure_reason=str(exc),
            )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        codex_cli_log = build_codex_cli_transcript(
            status="succeeded" if completed.returncode == 0 else "failed",
            command=command_summary,
            timeout_seconds=execution_policy.timeout_seconds,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        codex_cli_log["result_path"] = str(result_path.relative_to(workspace))
        codex_cli_log["last_message_path"] = str(last_message_path.relative_to(workspace))
        if completed.returncode != 0 and codex_cli_rejected_output_schema(completed):
            first_attempt_log = codex_cli_log
            retry_cmd = build_command(include_output_schema=False)
            retry_command_summary = " ".join(retry_cmd[:-1] + ["-"])
            retry_started_at = time.perf_counter()
            try:
                completed = subprocess.run(
                    retry_cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=execution_policy.timeout_seconds,
                    env=safe_env(
                    workspace,
                    sandbox=execution_policy.sandbox,
                    network_enabled=execution_policy.network in {"restricted", "full"},
                ),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.perf_counter() - retry_started_at) * 1000)
                retry_log = build_codex_cli_transcript(
                    status="timeout",
                    command=retry_command_summary,
                    timeout_seconds=execution_policy.timeout_seconds,
                    duration_ms=duration_ms,
                    stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                    stderr=exc.stderr if isinstance(exc.stderr, str) else "",
                )
                retry_log["result_path"] = str(result_path.relative_to(workspace))
                retry_log["last_message_path"] = str(last_message_path.relative_to(workspace))
                retry_log["schema_retry_without_output_schema"] = True
                retry_log["attempts"] = [first_attempt_log]
                return AgentResult(
                    task_id=task_contract.task_id,
                    status="failed",
                    final_message="Codex CLI timed out after retrying without CLI output-schema enforcement.",
                    outputs={
                        "runner": "codex_cli",
                        "codex_cli": retry_log,
                    },
                    artifacts=[],
                    warnings=[],
                    failure_reason=str(exc),
                )
            duration_ms = int((time.perf_counter() - retry_started_at) * 1000)
            codex_cli_log = build_codex_cli_transcript(
                status="succeeded" if completed.returncode == 0 else "failed",
                command=retry_command_summary,
                timeout_seconds=execution_policy.timeout_seconds,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
            codex_cli_log["result_path"] = str(result_path.relative_to(workspace))
            codex_cli_log["last_message_path"] = str(last_message_path.relative_to(workspace))
            codex_cli_log["schema_retry_without_output_schema"] = True
            codex_cli_log["attempts"] = [first_attempt_log]
        (harness_dir / "codex_cli_log.json").write_text(
            json.dumps(codex_cli_log, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI failed.",
                outputs={"runner": "codex_cli", "codex_cli": codex_cli_log},
                artifacts=[],
                warnings=[],
                failure_reason=completed.stderr[-4000:],
            )
        if not result_path.exists():
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI completed but outputs/result.json was not found.",
                outputs={"runner": "codex_cli", "codex_cli": codex_cli_log},
                artifacts=[],
                warnings=[],
                failure_reason="missing_result_json",
            )
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return AgentResult(
                task_id=task_contract.task_id,
                status="failed",
                final_message="Codex CLI completed but outputs/result.json was not valid JSON.",
                outputs={"runner": "codex_cli", "codex_cli": codex_cli_log},
                artifacts=[],
                warnings=[],
                failure_reason=f"invalid_result_json: {exc}",
            )
        validate_against_schema(data, output_schema)
        result = AgentResult.model_validate(data)
        result.outputs = {**result.outputs, "runner": result.outputs.get("runner") or "codex_cli", "codex_cli": codex_cli_log}
        return result


def validate_against_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    Draft202012Validator(schema).validate(data)


def codex_cli_rejected_output_schema(completed: subprocess.CompletedProcess[str]) -> bool:
    combined = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    return "invalid_json_schema" in combined or "Invalid schema for response_format" in combined


def write_stub_workspace_outputs(
    *,
    workspace: Path,
    report_md: str,
    feature_recipe: dict[str, Any],
    experiment_metrics: dict[str, Any],
    visualization_spec: dict[str, Any],
    source_citation_manifest: dict[str, Any],
    approach_decision_trace: dict[str, Any],
    citation_audit_report: str,
    citation_visualization_spec: dict[str, Any],
    notebook_authoring_plan: str | None,
    relational_context_summary: dict[str, Any] | None,
    relational_visualization_spec: dict[str, Any] | None,
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
    (artifacts_dir / "source_citation_manifest.json").write_text(
        json.dumps(source_citation_manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (artifacts_dir / "approach_decision_trace.json").write_text(
        json.dumps(approach_decision_trace, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (reports_dir / "citation_audit_report.md").write_text(citation_audit_report, encoding="utf-8")
    if notebook_authoring_plan is not None:
        (reports_dir / "notebook_authoring_plan.md").write_text(notebook_authoring_plan, encoding="utf-8")
    (artifacts_dir / "citation_visualization_spec.json").write_text(
        json.dumps(citation_visualization_spec, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if relational_context_summary is not None:
        (artifacts_dir / "relational_context_summary.json").write_text(
            json.dumps(relational_context_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if relational_visualization_spec is not None:
        (artifacts_dir / "relational_context_visualization_spec.json").write_text(
            json.dumps(relational_visualization_spec, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (artifacts_dir / "agent_result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )


def render_stub_feature_recipe(contract: AgentTaskContract, relational_context: dict[str, Any] | None = None) -> dict[str, Any]:
    dataset_context = dict_value(contract.inputs.get("dataset_context"))
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    relational_context = relational_context or {}
    feature_families: list[dict[str, Any]] = [
        {
            "name": "dataset_specific_features",
            "status": "planned",
            "notes": "Future runner should select features from project evidence, Skill assets, and approved evaluation constraints.",
        }
    ]
    if relational_context.get("source_count"):
        feature_families.append(
            {
                "name": "relational_context_review",
                "status": "available_for_agent_review",
                "source_count": relational_context.get("source_count"),
                "usable_preview_feature_count": dict_value(relational_context.get("preview_summary")).get(
                    "usable_feature_count"
                ),
                "notes": (
                    "Relational preview artifacts are available for planning. A real runner must implement "
                    "train-fold-safe generation before model claims."
                ),
            }
        )
    return {
        "recipe_version": "feature_recipe.v1",
        "recipe_name": "local_stub_planned_feature_recipe",
        "execution_status": "not_executed",
        "runner": "local_stub",
        "task_id": contract.task_id,
        "dataset_snapshot_id": dataset_context.get("dataset_snapshot_id"),
        "evaluation_spec_id": evaluation_contract.get("evaluation_spec_id"),
        "split_manifest_id": split_manifest_id(evaluation_contract),
        "feature_families": feature_families,
        "relational_context": relational_context if relational_context.get("source_count") else None,
        "safety": {
            "fit_preprocessing_on_train_only": True,
            "must_respect_split_manifest": True,
            "validation_or_test_targets_forbidden": True,
            "secrets_forbidden": True,
        },
    }


def render_stub_experiment_metrics(contract: AgentTaskContract, relational_context: dict[str, Any] | None = None) -> dict[str, Any]:
    dataset_context = dict_value(contract.inputs.get("dataset_context"))
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    relational_context = relational_context or {}
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
        "relational_context": {
            "status": relational_context.get("status") or "missing",
            "source_count": relational_context.get("source_count") or 0,
            "usable_feature_count": dict_value(relational_context.get("preview_summary")).get(
                "usable_feature_count"
            ),
            "deferred_safety_check_count": len(list_value(relational_context.get("deferred_safety_checks"))),
        },
        "split_manifest_respected": bool(split_manifest_id(evaluation_contract)),
        "notes": [
            "LocalStubAgentRunner does not train or evaluate a model.",
            "This metrics artifact exists so the harness can test AgentResult ingestion without making benchmark claims.",
        ],
    }


def render_stub_approach_decision_trace(
    contract: AgentTaskContract,
    relational_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    autonomy_policy = dict_value(contract.inputs.get("runner_autonomy_policy"))
    approach_space = dict_value(contract.inputs.get("open_ended_approach_space"))
    strategy_context = dict_value(contract.inputs.get("adaptive_strategy_brief"))
    candidates = list_value(contract.inputs.get("recommended_approach_candidates"))
    recommendations = list_value(contract.inputs.get("library_recommendations"))
    research_queries = list_value(contract.inputs.get("research_queries"))
    relational_context = relational_context or {}
    relational_available = bool(relational_context.get("source_count"))
    return {
        "schema_version": "approach_decision_trace.v1",
        "execution_status": "not_executed",
        "runner": "local_stub",
        "task_id": contract.task_id,
        "autonomy_policy": autonomy_policy,
        "open_ended_approach_space": approach_space,
        "context_used": {
            "recommended_approach_count": len(candidates),
            "recommended_asset_count": len(recommendations),
            "research_query_count": len(research_queries),
            "relational_context_available": relational_available,
            "relational_context_source_count": relational_context.get("source_count") or 0,
            "adaptive_strategy_brief_artifact_id": strategy_context.get("artifact_id"),
        },
        "adaptive_strategy_guidance": summarize_strategy_context(strategy_context),
        "approaches_considered": summarize_approach_candidates(candidates),
        "chosen_or_placeholder_approach": {
            "status": "not_chosen_by_local_stub",
            "reason": (
                "LocalStub validates handoff shape only. A real Codex or Skill runner should choose, revise, "
                "or replace approaches after inspecting project evidence and current research."
            ),
        },
        "rejected_or_deferred_approaches": [
            {
                "approach": "fixed_predefined_recipe_execution",
                "status": "rejected_as_product_default",
                "reason": (
                    "Tablex should preserve runner autonomy. Recommended assets and relational recipes are "
                    "evidence and scaffolding, not a closed list of executable choices."
                ),
            },
            *relational_deferred_trace_items(relational_context),
        ],
        "new_approach_hypotheses": [
            {
                "hypothesis": "A project-specific approach may outperform listed candidates when supported by data semantics, Skills, or fresh literature.",
                "status": "open_for_runner",
                "requires": ["evidence", "evaluation_spec", "split_manifest"],
            }
        ],
        "additional_research_or_skill_needs": summarize_research_needs(research_queries, recommendations),
        "hard_constraints_checked": autonomy_policy.get(
            "runner_must",
            [
                "respect_evaluation_spec_and_split_manifest",
                "register_important_outputs_as_artifacts",
            ],
        ),
        "forbidden_constraints_checked": autonomy_policy.get(
            "runner_must_not",
            [
                "read_secrets",
                "materialize_connector_credentials",
                "destructively_modify_evaluation_spec_or_split_manifest",
            ],
        ),
        "agent_guidance": [
            "Use structured context to stay auditable, not to restrict creativity.",
            "Prefer evidence-backed project-specific reasoning over default recipes.",
            "Record why any harness suggestion was accepted, modified, rejected, or deferred.",
        ],
    }


def render_stub_notebook_authoring_plan(contract: AgentTaskContract) -> str:
    notebook_context = dict_value(contract.inputs.get("notebook_authoring"))
    dataset_context = dict_value(contract.inputs.get("dataset_context"))
    evaluation_contract = dict_value(contract.inputs.get("evaluation_contract"))
    sources = [item for item in list_value(notebook_context.get("source_inspirations")) if isinstance(item, dict)]
    principles = [item for item in list_value(notebook_context.get("authoring_principles")) if isinstance(item, dict)]
    context_artifacts = [
        item for item in list_value(notebook_context.get("context_artifacts")) if isinstance(item, dict)
    ]
    lines = [
        "# Notebook Authoring Plan",
        "",
        "LocalStub did not write the final notebook. This artifact defines the handoff a real Codex runner must use.",
        "",
        "## Reader Objective",
        "",
        str(notebook_context.get("objective") or contract.objective),
        "",
        "## Current Evidence",
        "",
        f"- Notebook authoring brief: `{notebook_context.get('artifact_id') or 'missing'}`",
        f"- DatasetSnapshot: `{dataset_context.get('dataset_snapshot_id') or 'missing'}`",
        f"- Rows: `{dataset_context.get('row_count')}`",
        f"- Columns: `{dataset_context.get('column_count')}`",
        f"- Target: `{dataset_context.get('target_column') or 'not selected'}`",
        f"- EvaluationSpec: `{evaluation_contract.get('evaluation_spec_id') or 'missing'}`",
        f"- Primary metric: `{evaluation_contract.get('primary_metric') or 'not selected'}`",
        "",
        "## Source Inspirations",
    ]
    if sources:
        for source in sources:
            lines.append(f"- {source.get('title')}: {source.get('runner_use')}")
    else:
        lines.append("- No public craft source cards were attached; runner should ask for or create them before external claims.")
    lines.extend(["", "## Authoring Principles"])
    if principles:
        for principle in principles:
            lines.append(f"- **{principle.get('principle')}**: {principle.get('implementation')}")
    else:
        lines.append("- Use the Tablex notebook quality Skill as the fallback quality bar.")
    lines.extend(
        [
            "",
            "## Context Artifacts To Open First",
        ]
    )
    if context_artifacts:
        for artifact in context_artifacts:
            lines.append(f"- `{artifact.get('role')}`: `{artifact.get('artifact_id')}` ({artifact.get('asset_type')})")
    else:
        lines.append("- No EDA/Data Review artifacts were attached; generate Data Review before final notebook authoring.")
    lines.extend(
        [
            "",
            "## Codex Execution Instructions",
            "",
            "- Decide the notebook flow from evidence, not from a fixed Tablex template.",
            "- Start with a concise reader brief, then a question ladder: question, evidence, interpretation, next action.",
            "- Prefer a small number of purposeful figures over a chart gallery.",
            "- Label missing evidence, unresolved assumptions, profile boundaries, and deferred checks.",
            "- Return the marimo source, rendered report, figure manifest, evidence bundle, quality review, and citation audit.",
            "",
            "## Non-Negotiable Boundaries",
            "",
            "- Do not read secrets or connector credentials.",
            "- Do not copy public notebook prose, code, or section order.",
            "- Do not change EvaluationSpec or SplitManifest.",
            "- Do not make model or metric claims unless supported by Tablex artifacts.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def summarize_approach_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    summarized = []
    for item in candidates[:8]:
        if not isinstance(item, dict):
            continue
        summarized.append(
            {
                "title": item.get("title"),
                "approach_type": item.get("approach_type"),
                "confidence": item.get("confidence"),
                "risk_level": item.get("risk_level"),
                "status": "advisory_candidate",
            }
        )
    return summarized


def summarize_strategy_context(strategy_context: dict[str, Any]) -> dict[str, Any]:
    if not strategy_context:
        return {"status": "missing"}
    recommended_action = dict_value(strategy_context.get("recommended_next_action"))
    codex_handoff = dict_value(strategy_context.get("codex_handoff"))
    autonomy_policy = dict_value(codex_handoff.get("autonomy_policy"))
    return {
        "status": "available",
        "artifact_id": strategy_context.get("artifact_id"),
        "strategy_mode": strategy_context.get("strategy_mode"),
        "fixed_recipe_policy": strategy_context.get("fixed_recipe_policy"),
        "recommended_action": {
            "action_type": recommended_action.get("action_type"),
            "label": recommended_action.get("label"),
            "reason": recommended_action.get("reason"),
        },
        "runner_can_propose_new_approach_classes": autonomy_policy.get("can_propose_new_approach_classes"),
        "must_emit_approach_decision_trace": autonomy_policy.get("must_emit_approach_decision_trace"),
        "policy": strategy_context.get("policy"),
    }


def relational_deferred_trace_items(relational_context: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for check_item in list_value(relational_context.get("deferred_safety_checks")):
        if not isinstance(check_item, dict):
            continue
        items.append(
            {
                "approach": f"relational_context::{check_item.get('check')}",
                "status": check_item.get("status") or "deferred",
                "reason": check_item.get("reason"),
            }
        )
    return items


def summarize_research_needs(research_queries: list[Any], recommendations: list[Any]) -> list[dict[str, Any]]:
    needs = []
    if research_queries:
        needs.append(
            {
                "need": "controlled_research_follow_up",
                "status": "available_in_contract",
                "count": len(research_queries),
            }
        )
    if recommendations:
        needs.append(
            {
                "need": "skill_or_asset_review",
                "status": "available_in_contract",
                "count": len(recommendations),
            }
        )
    if not needs:
        needs.append(
            {
                "need": "runner_defined_research_questions",
                "status": "open",
                "count": 0,
            }
        )
    return needs


def render_stub_source_citation_manifest(
    contract: AgentTaskContract,
    policy: ExecutionPolicy,
) -> dict[str, Any]:
    source_pack = dict_value(contract.inputs.get("research_source_pack"))
    source_policy = dict_value(contract.inputs.get("research_source_policy")) or dict_value(
        source_pack.get("source_policy")
    )
    source_pack_artifact_id = source_pack.get("artifact_id")
    source_id = "research_source_pack" if isinstance(source_pack_artifact_id, str) else "runner_source_policy"
    evidence_sources = [
        {
            "source_id": source_id,
            "source_type": "harness_artifact" if isinstance(source_pack_artifact_id, str) else "runner_policy",
            "title": "Research Source Pack" if isinstance(source_pack_artifact_id, str) else "Runner source policy",
            "url": None,
            "artifact_id": source_pack_artifact_id if isinstance(source_pack_artifact_id, str) else None,
            "summary": (
                "Harness-provided source policy and citation requirements were available to the runner."
                if isinstance(source_pack_artifact_id, str)
                else "No Research Source Pack artifact was supplied; only runner policy was audited."
            ),
            "verification_status": "local_artifact" if isinstance(source_pack_artifact_id, str) else "policy_placeholder",
            "retrieved_at": None,
            "freshness": "not_applicable",
            "risk_level": "low" if isinstance(source_pack_artifact_id, str) else "medium",
            "metadata": {
                "controlled_query_count": source_pack.get("controlled_query_count"),
                "network_policy": policy.network,
            },
        }
    ]
    citations = [
        {
            "citation_id": "cit_local_stub_no_external_search",
            "source_id": source_id,
            "claim": "LocalStubAgentRunner did not access external network, retrieve literature, or validate modeling claims.",
            "usage_context": "citation_audit",
            "confidence": 1.0,
            "requires_follow_up": True,
            "metadata": {
                "execution_status": "not_executed",
                "network_policy": policy.network,
                "connector_credentials_materialized": False,
            },
        }
    ]
    return {
        "schema_version": "source_citation_manifest.v1",
        "task_id": contract.task_id,
        "runner": "local_stub",
        "execution_status": "not_executed",
        "external_network_accessed": False,
        "connector_credentials_materialized": False,
        "research_source_pack_artifact_id": source_pack_artifact_id if isinstance(source_pack_artifact_id, str) else None,
        "source_policy": source_policy,
        "citation_requirements": list_value(source_pack.get("citation_requirements")),
        "freshness_expectations": dict_value(source_pack.get("freshness_expectations")),
        "evidence_sources": evidence_sources,
        "citations": citations,
        "report_citations": [
            {
                "section": "Stub Result",
                "citation_ids": [citation["citation_id"] for citation in citations],
                "note": "This citation records source-policy compliance only; it is not model evidence.",
            }
        ],
        "audit": {
            "real_sources_retrieved": 0,
            "policy_sources_available": len(evidence_sources),
            "network_policy": policy.network,
            "requires_human_review": True,
        },
    }


def render_stub_citation_audit_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# Citation Audit Report",
        "",
        f"- Task: {manifest.get('task_id')}",
        f"- Runner: {manifest.get('runner')}",
        f"- Execution status: {manifest.get('execution_status')}",
        f"- External network accessed: {str(manifest.get('external_network_accessed')).lower()}",
        f"- Connector credentials materialized: {str(manifest.get('connector_credentials_materialized')).lower()}",
        f"- Research Source Pack artifact: {manifest.get('research_source_pack_artifact_id') or 'none'}",
        "",
        "## Evidence Sources",
    ]
    for source in list_value(manifest.get("evidence_sources")):
        if isinstance(source, dict):
            lines.append(
                f"- `{source.get('source_id')}`: {source.get('title')} "
                f"({source.get('verification_status')})"
            )
    lines.extend(["", "## Citations"])
    for citation in list_value(manifest.get("citations")):
        if isinstance(citation, dict):
            lines.append(f"- `{citation.get('citation_id')}`: {citation.get('claim')}")
    lines.extend(
        [
            "",
            "## Follow-up",
            "",
            "- A real runner must attach source summaries and citations before external claims are treated as evidence.",
            "- Connector credentials and secrets are not present in this citation audit.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_stub_citation_visualization(manifest: dict[str, Any]) -> dict[str, Any]:
    source_count = len(list_value(manifest.get("evidence_sources")))
    citation_count = len(list_value(manifest.get("citations")))
    external_accessed = bool(manifest.get("external_network_accessed"))
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Citation Audit",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": "Source policy",
                "status": "ready" if manifest.get("source_policy") else "warning",
                "count": source_count,
                "detail": "Harness source policy captured for runner handoff.",
            },
            {
                "stage": "Citations",
                "status": "warning" if citation_count == 0 else "ready",
                "count": citation_count,
                "detail": "LocalStub records audit citations but no external source claims.",
            },
            {
                "stage": "External access",
                "status": "warning" if external_accessed else "ready",
                "count": 1 if external_accessed else 0,
                "detail": "Network remains disabled for LocalStub execution.",
            },
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "detail"]},
        "empty_state": "Citation audit will appear after an AgentResult is ingested.",
    }


def render_stub_relational_context_visualization(relational_context: dict[str, Any]) -> dict[str, Any]:
    preview = dict_value(relational_context.get("preview_summary"))
    coverage = dict_value(relational_context.get("coverage"))
    deferred_count = len(list_value(relational_context.get("deferred_safety_checks")))
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Relational Runner Context",
        "chart_type": "stage_status",
        "data": [
            {
                "stage": "Context files",
                "status": "ready" if relational_context.get("source_count") else "warning",
                "count": relational_context.get("source_count") or 0,
                "detail": "Relational artifacts materialized in the controlled workspace.",
            },
            {
                "stage": "Recipe",
                "status": "ready" if coverage.get("has_recipe") else "warning",
                "count": 1 if coverage.get("has_recipe") else 0,
                "detail": "Relational feature recipe available for runner review.",
            },
            {
                "stage": "Usable preview features",
                "status": "ready" if int_value(preview.get("usable_feature_count")) else "warning",
                "count": int_value(preview.get("usable_feature_count")),
                "detail": "Preview features are planning evidence, not train-fold-fitted model inputs.",
            },
            {
                "stage": "Deferred safety checks",
                "status": "warning" if deferred_count else "ready",
                "count": deferred_count,
                "detail": "Checks that must be resolved before relational model claims.",
            },
        ],
        "encoding": {"x": "stage", "color": "status", "tooltip": ["stage", "status", "detail"]},
        "empty_state": "Prepare a workspace with relational context before running an AgentRunner.",
    }


def split_manifest_id(evaluation_contract: dict[str, Any]) -> str | None:
    raw_manifest = evaluation_contract.get("split_manifest")
    if not isinstance(raw_manifest, dict):
        return None
    value = raw_manifest.get("split_manifest_id")
    return value if isinstance(value, str) and value else None


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def int_value(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


def codex_sandbox(policy: str) -> str:
    if policy == "read_only":
        return "read-only"
    if policy == "full_access":
        return "danger-full-access"
    return "workspace-write"


def render_prompt(contract: AgentTaskContract) -> str:
    lines = [
        "Execute the following Tablex harness task contract inside this prepared workspace.",
        "",
        "Hard rules:",
        "- Follow AGENTS.md and any relevant Skill files.",
        "- Do not access secrets, connector credentials, or files outside the workspace.",
        "- Do not destructively modify EvaluationSpec or SplitManifest.",
        "- Register every important output in outputs/result.json as an AgentResult artifact descriptor.",
        "- Write the final schema-valid AgentResult to outputs/result.json.",
        "- The final chat response may summarize what happened, but outputs/result.json is the structured contract Tablex ingests.",
        "- Treat Give Up as a last resort for any task. If you genuinely cannot continue because required information, "
        "execution capability, safety policy, or data access is missing, return status `gave_up`, explain "
        "`give_up_reason`, list `required_next_inputs`, and preserve every useful partial artifact.",
    ]
    if contract.task_type == "author_analysis_notebook":
        lines.extend(
            [
                "",
                "Notebook authoring rules:",
                "- Read .harness/task_contract.json first.",
                "- Read skills/tablex-notebook-quality/SKILL.md if present.",
                "- Read skills/tablex-grandmaster-eda/SKILL.md and its references if present.",
                "- Read the notebook_authoring_brief referenced in contract.inputs.notebook_authoring.artifact_id.",
                "- Inspect the materialized Tablex context artifacts under .harness/context before choosing the notebook flow.",
                "- Use public Kaggle Grandmaster-style source cards as craft inspiration only; do not copy public prose, code, or section order.",
                "- Decide the exploration path, hypotheses, narrative, sections, figures, and caveats from current evidence instead of using a fixed template.",
                "- If target or evaluation context is missing, write a useful data-understanding notebook and label target-aware/model claims as blocked.",
                "- Produce the requested marimo source, reader report, EDA hypotheses, visual story cards, figure manifest, evidence bundle, quality review, and citation audit.",
            ]
        )
    if contract.task_type == "notebook_followup_diagnostics":
        lines.extend(
            [
                "",
                "Notebook follow-up diagnostics rules:",
                "- Read .harness/task_contract.json first, then inspect materialized notebook, Data Review, run, diagnostics, and prediction artifacts.",
                "- Treat the current Analysis Story as the reader context, not as a fixed template.",
                "- Materialize feature importance, permutation importance, PDP, calibration, threshold, score-bin, slice, or worst-example diagnostics only when source artifacts support them.",
                "- If the needed model, prediction, split, or metric artifact is missing, write the evidence gap and the narrow next artifact request instead of inventing figures.",
                "- Keep EvaluationSpec and SplitManifest read-only, and compute diagnostics only on allowed split rows.",
                "- Produce a concise report, visualization spec, evidence bundle, figure manifest, and marimo follow-up notebook suitable for Tablex UI.",
            ]
        )
    if contract.task_type == "target_definition_review":
        lines.extend(
            [
                "",
                "Prediction/task objective review rules:",
                "- Read .harness/task_contract.json first, then inspect materialized profile, semantic catalog, EDA, assumptions, questions, and relational context artifacts.",
                "- Propose the project objective from data-science reasoning, not from column-name shortcuts or a fixed supervised-learning template.",
                "- Consider supervised prediction, derived labels, aggregate objectives, time-to-event or distributional prediction, clustering, anomaly detection, inverse-problem analysis, and optimization-coupled workflows when the evidence suggests them.",
                "- Explain prediction-time or decision-time semantics, leakage risks, rejected objective options, and the evidence that would change your recommendation.",
                "- Do not train a model or mutate EvaluationSpec/SplitManifest in this task.",
                "- Put the structured proposal in outputs.target_definition_proposal for backward compatibility and also write artifacts/target_definition_proposal.json. The proposal may describe a non-column or unsupervised objective.",
            ]
        )
    lines.extend(["", "Task contract:", "", contract.model_dump_json(by_alias=True, indent=2)])
    return "\n".join(lines)


def render_stub_report(
    contract: AgentTaskContract,
    policy: ExecutionPolicy,
    relational_context: dict[str, Any] | None = None,
) -> str:
    relational_context = relational_context or {}
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
    source_pack = dict_value(contract.inputs.get("research_source_pack"))
    source_pack_artifact_id = source_pack.get("artifact_id") if isinstance(source_pack.get("artifact_id"), str) else None
    lines.extend(
        [
            "",
            "## Source Policy and Citation Audit",
            "",
            f"- Research Source Pack artifact: {source_pack_artifact_id or 'none'}",
            "- Citation audit artifact: `artifacts/source_citation_manifest.json`",
            "- Citation audit report: `reports/citation_audit_report.md`",
            "- Approach decision trace: `artifacts/approach_decision_trace.json`",
            "- External network execution: not performed by LocalStubAgentRunner.",
            "",
            "## Runner Autonomy",
            "",
            "- Recommended approaches, Skills, and relational recipes are advisory context, not mandatory recipes.",
            "- A real runner may accept, modify, reject, or replace candidates when project evidence supports it.",
            "- The hard boundary is evaluation, safety, artifact registration, and lineage, not a closed model menu.",
        ]
    )
    if relational_context.get("source_count"):
        preview = dict_value(relational_context.get("preview_summary"))
        lines.extend(
            [
                "",
                "## Relational Runner Context",
                "",
                f"- Materialized relational artifacts: {relational_context.get('source_count')}",
                f"- Usable preview features: {preview.get('usable_feature_count')}",
                f"- Generated preview features: {preview.get('generated_feature_count')}",
                "- Context directory: `.harness/context/relational/`",
                "- Policy: inspect relational context as advisory evidence, not a mandatory recipe.",
                "- Runner autonomy: reject, revise, or replace relational approaches when project evidence supports a better path.",
                "- Hard constraints: respect harness EvaluationSpec/SplitManifest, do not read secrets, and register important outputs as artifacts.",
                "",
                "### Scenario Recommendations",
            ]
        )
        recommendations = list_value(relational_context.get("recommended_agent_task_scenarios"))
        if recommendations:
            for item in recommendations:
                if isinstance(item, dict):
                    lines.append(f"- `{item.get('name')}`: {item.get('description')}")
        else:
            lines.append("- No scenario recommendations were attached.")
        lines.extend(["", "### Deferred Safety Checks"])
        for item in list_value(relational_context.get("deferred_safety_checks")):
            if isinstance(item, dict):
                lines.append(f"- `{item.get('check')}` ({item.get('status')}): {item.get('reason')}")
    lines.extend(
        [
            "",
            "## Stub Result",
            "",
            "This is an execution-ready plan. It verifies contract shape, safety policy, and expected artifacts before a real runner is enabled.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def safe_env(
    workspace: Path,
    *,
    sandbox: str = "workspace_write",
    network_enabled: bool = False,
) -> dict[str, str]:
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "OPENAI_API_KEY",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    workspace_bin = workspace / ".tablex" / "bin"
    existing_path = env.get("PATH") or os.defpath
    isolated_home = workspace / ".harness" / "home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(isolated_home)
    codex_home = tablex_codex_home_for_workspace(workspace)
    try:
        prepare_tablex_codex_home(
            codex_home,
            workspace=workspace,
            sandbox=sandbox,
            network_enabled=network_enabled,
        )
    except OSError:
        codex_home = (workspace / ".tablex" / "codex_home").resolve()
        prepare_tablex_codex_home(
            codex_home,
            workspace=workspace,
            sandbox=sandbox,
            network_enabled=network_enabled,
        )
    runtime_codex_bin = codex_home / "bin"
    env["PATH"] = os.pathsep.join((str(workspace_bin), str(runtime_codex_bin), existing_path))
    env["CODEX_HOME"] = str(codex_home)
    return env


def tablex_codex_home_for_workspace(workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:16]
    return tablex_codex_home() / digest


def tablex_codex_home() -> Path:
    override = os.environ.get("TABLEX_CODEX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        base = Path(cache_home).expanduser()
    else:
        host_home = os.environ.get("HOME")
        base = (Path(host_home).expanduser() if host_home else Path.home()) / ".cache"
    return (base / "tablex" / "codex_home").resolve()


def prepare_tablex_codex_home(
    codex_home: Path,
    *,
    workspace: Path,
    sandbox: str,
    network_enabled: bool,
) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    try:
        codex_home.chmod(0o700)
    except OSError:
        pass
    remove_tablex_codex_runtime_state(codex_home)
    host_codex_home = host_codex_home_for_auth()
    prepare_codex_runtime_binary(codex_home, host_codex_home=host_codex_home)
    write_tablex_codex_config(
        codex_home,
        workspace=workspace,
        sandbox=sandbox,
        network_enabled=network_enabled,
        host_codex_home=host_codex_home,
    )
    if host_codex_home is None:
        return
    for filename in ("auth.json", "installation_id"):
        source = host_codex_home / filename
        if not source.exists():
            continue
        target = codex_home / filename
        if target.exists():
            continue
        if target.is_symlink():
            target.unlink()
        try:
            target.symlink_to(source)
        except OSError:
            # Keep the runtime isolated even if the platform disallows symlinks.
            # API-key auth can still work through OPENAI_API_KEY.
            pass


def write_tablex_codex_config(
    codex_home: Path,
    *,
    workspace: Path,
    sandbox: str,
    network_enabled: bool,
    host_codex_home: Path | None,
) -> None:
    root_permission = "write" if sandbox == "full_access" else "read"
    workspace_permission = "read" if sandbox == "read_only" else "write"
    filesystem_permissions: list[tuple[Path | str, str]] = [
        (":root", root_permission),
        (":tmpdir", "write"),
        (workspace.resolve(), workspace_permission),
    ]
    if host_codex_home is not None:
        filesystem_permissions.append((host_codex_home.resolve(), "none"))
    lines = [
        "default_permissions = \"workspace\"",
        "approval_policy = \"never\"",
        "",
        "[permissions.workspace.filesystem]",
    ]
    lines.extend(
        f"{json.dumps(str(path))} = {json.dumps(permission)}"
        for path, permission in filesystem_permissions
    )
    if network_enabled:
        lines.extend(
            [
                "",
                "[permissions.workspace.network]",
                "enabled = true",
                "mode = \"full\"",
                "allow_local_binding = false",
            ]
        )
    (codex_home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_tablex_codex_runtime_state(codex_home: Path) -> None:
    for filename in ("config.toml", "config.json"):
        path = codex_home / filename
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass
    for dirname in ("plugins", "skills"):
        path = codex_home / dirname
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass
    for relative_path in (
        Path(".tmp") / "plugins",
        Path("cache") / "codex_apps_server_info",
        Path("cache") / "codex_apps_tools",
    ):
        path = codex_home / relative_path
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass


def host_codex_home_for_auth() -> Path | None:
    configured = os.environ.get("CODEX_HOME")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    host_home = os.environ.get("HOME")
    if host_home:
        candidates.append(Path(host_home).expanduser() / ".codex")
    runtime_home = tablex_codex_home()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved == runtime_home:
            continue
        if candidate.exists():
            return candidate
    return None


def prepare_codex_runtime_binary(codex_home: Path, *, host_codex_home: Path | None) -> None:
    if host_codex_home is None:
        return
    for command in ("codex", "rg"):
        prepare_codex_runtime_tool(codex_home, host_codex_home=host_codex_home, command=command)


def prepare_codex_runtime_tool(codex_home: Path, *, host_codex_home: Path, command: str) -> None:
    tool_binary = shutil.which(command)
    if tool_binary is None:
        return
    try:
        resolved_binary = Path(tool_binary).resolve(strict=True)
        resolved_binary.relative_to(host_codex_home.resolve())
    except (OSError, ValueError):
        return
    try:
        with resolved_binary.open("rb") as source:
            if source.read(4) != b"\x7fELF":
                return
        runtime_bin = codex_home / "bin"
        runtime_bin.mkdir(parents=True, exist_ok=True)
        target = runtime_bin / command
        source_stat = resolved_binary.stat()
        if target.exists():
            target_stat = target.stat()
            if target_stat.st_size == source_stat.st_size and target_stat.st_mtime_ns == source_stat.st_mtime_ns:
                return
        shutil.copy2(resolved_binary, target)
        target.chmod(0o755)
    except OSError:
        return
