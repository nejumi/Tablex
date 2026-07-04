from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tabular_harness.agent import (
    CodexCliRunner,
    ExecutionPolicy,
    LocalStubAgentRunner,
    NoopAgentRunner,
    WorkspaceRef,
)
from tabular_harness.agent.runners import CODEX_HARNESS_CONFIG_ARGS, render_prompt, safe_env
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
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval", "gave_up"]},
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
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval", "gave_up"]},
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


def test_codex_cli_runner_missing_binary_fails_schema_safely(tmp_path: Path) -> None:
    contract = AgentTaskContract(
        task_id="task_codex",
        task_type="author_analysis_notebook",
        project_id="p_001",
        objective="Write a notebook from the authoring brief.",
        inputs={"notebook_authoring": {"artifact_id": "art_brief"}},
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
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval", "gave_up"]},
            "final_message": {"type": "string"},
            "outputs": {"type": "object"},
            "artifacts": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }

    prompt = render_prompt(contract)
    assert "Read the notebook_authoring_brief" in prompt
    assert "do not copy public prose" in prompt

    result = CodexCliRunner(codex_binary=str(tmp_path / "missing-codex")).run_task(
        WorkspaceRef(project_id="p_001", path=str(tmp_path)),
        contract,
        output_schema,
        ExecutionPolicy(),
    )

    assert result.status == "failed"
    assert result.outputs["runner"] == "codex_cli"
    assert result.failure_reason == "codex_binary_not_found"


def test_codex_cli_runner_retries_without_cli_schema_when_codex_rejects_schema(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    contract = AgentTaskContract(
        task_id="task_codex_retry",
        task_type="target_definition_review",
        project_id="p_001",
        objective="Reason about the target from Tablex context.",
        inputs={},
        required_outputs=[AgentRequiredOutput(path="outputs/result.json", schema="schemas/agent_result.schema.json")],
        quality_checks=["Return schema-valid AgentResult."],
        forbidden_actions=["Do not read secrets."],
    )
    output_schema = {
        "type": "object",
        "required": ["task_id", "status", "final_message", "outputs", "artifacts", "warnings"],
        "properties": {
            "task_id": {"type": "string"},
            "status": {"type": "string", "enum": ["succeeded", "failed", "needs_approval", "gave_up"]},
            "final_message": {"type": "string"},
            "outputs": {"type": "object"},
            "artifacts": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        commands.append(cmd)
        if len(commands) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout='{"msg":{"type":"error","code":"invalid_json_schema"}}\n',
                stderr="Invalid schema for response_format 'codex_output_schema'",
            )
        result_path = tmp_path / "outputs" / "result.json"
        result_path.parent.mkdir(exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "task_id": "task_codex_retry",
                    "status": "succeeded",
                    "final_message": "Codex completed after Tablex stopped enforcing CLI output schema.",
                    "outputs": {},
                    "artifacts": [],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout='{"msg":{"type":"done"}}\n', stderr="")

    monkeypatch.setattr("tabular_harness.agent.runners.subprocess.run", fake_run)

    result = CodexCliRunner(codex_binary="codex").run_task(
        WorkspaceRef(project_id="p_001", path=str(tmp_path)),
        contract,
        output_schema,
        ExecutionPolicy(),
    )

    assert result.status == "succeeded"
    assert len(commands) == 2
    assert "--output-schema" in commands[0]
    assert "--output-schema" not in commands[1]
    for command in commands:
        assert list(CODEX_HARNESS_CONFIG_ARGS) == command[2 : 2 + len(CODEX_HARNESS_CONFIG_ARGS)]
        assert "--ignore-user-config" in command
        assert "--ignore-rules" in command
        assert "mcp_servers={}" in command
    last_message_index = commands[1].index("--output-last-message") + 1
    assert commands[1][last_message_index].endswith(".harness/codex_last_message.md")
    assert commands[1][last_message_index] != str(tmp_path / "outputs" / "result.json")
    assert result.outputs["codex_cli"]["schema_retry_without_output_schema"] is True
    assert result.outputs["codex_cli"]["result_path"] == "outputs/result.json"
    assert result.outputs["codex_cli"]["last_message_path"] == ".harness/codex_last_message.md"


def test_codex_safe_env_does_not_pass_connector_credentials(tmp_path: Path, monkeypatch: Any) -> None:
    host_home = tmp_path / "home"
    host_codex_home = host_home / ".codex"
    host_codex_home.mkdir(parents=True)
    (host_codex_home / "auth.json").write_text('{"token":"test-only"}', encoding="utf-8")
    (host_codex_home / "config.toml").write_text("[mcp_servers.bad]\ncommand = 'bad'\n", encoding="utf-8")
    monkeypatch.setenv("KAGGLE_USERNAME", "tablex-user")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "secret-token")
    monkeypatch.setenv("WANDB_API_KEY", "secret-wandb-token")
    monkeypatch.setenv("TABLEX_INTERNAL_ONLY", "secret-internal")
    monkeypatch.setenv("CODEX_HOME", str(host_codex_home))
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    env = safe_env(tmp_path / "workspace")

    runtime_codex_home = tmp_path / "cache" / "tablex" / "codex_home"
    assert env["CODEX_HOME"] == str(runtime_codex_home.resolve())
    assert Path(env["CODEX_HOME"]) != host_codex_home
    assert (runtime_codex_home / "auth.json").is_symlink()
    assert (runtime_codex_home / "auth.json").resolve() == (host_codex_home / "auth.json").resolve()
    assert not (runtime_codex_home / "config.toml").exists()
    assert "KAGGLE_USERNAME" not in env
    assert "KAGGLE_API_TOKEN" not in env
    assert "WANDB_API_KEY" not in env
    assert "TABLEX_INTERNAL_ONLY" not in env


def test_codex_safe_env_removes_stale_runtime_config_and_plugins(tmp_path: Path, monkeypatch: Any) -> None:
    host_home = tmp_path / "home"
    host_codex_home = host_home / ".codex"
    host_codex_home.mkdir(parents=True)
    (host_codex_home / "auth.json").write_text('{"token":"test-only"}', encoding="utf-8")
    runtime_codex_home = tmp_path / "cache" / "tablex" / "codex_home"
    (runtime_codex_home / "plugins" / "bad").mkdir(parents=True)
    (runtime_codex_home / "plugins" / "bad" / "plugin.json").write_text("{}", encoding="utf-8")
    (runtime_codex_home / "skills" / "bad").mkdir(parents=True)
    (runtime_codex_home / "skills" / "bad" / "SKILL.md").write_text("bad", encoding="utf-8")
    (runtime_codex_home / "config.toml").write_text("[mcp_servers.bad]\ncommand = 'bad'\n", encoding="utf-8")
    (runtime_codex_home / "config.json").write_text('{"mcp_servers":{"bad":{}}}', encoding="utf-8")
    (runtime_codex_home / "logs_2.sqlite").write_text("keep", encoding="utf-8")
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    env = safe_env(tmp_path / "workspace")

    assert env["CODEX_HOME"] == str(runtime_codex_home.resolve())
    assert (runtime_codex_home / "auth.json").is_symlink()
    assert not (runtime_codex_home / "config.toml").exists()
    assert not (runtime_codex_home / "config.json").exists()
    assert not (runtime_codex_home / "plugins").exists()
    assert not (runtime_codex_home / "skills").exists()
    assert (runtime_codex_home / "logs_2.sqlite").exists()


def test_codex_safe_env_uses_explicit_tablex_codex_home(tmp_path: Path, monkeypatch: Any) -> None:
    host_home = tmp_path / "home"
    host_codex_home = host_home / ".codex"
    host_codex_home.mkdir(parents=True)
    (host_codex_home / "auth.json").write_text('{"token":"test-only"}', encoding="utf-8")
    tablex_codex_home = tmp_path / "runtime" / "codex_home"
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("CODEX_HOME", str(host_codex_home))
    monkeypatch.setenv("TABLEX_CODEX_HOME", str(tablex_codex_home))

    env = safe_env(tmp_path / "workspace")

    assert env["CODEX_HOME"] == str(tablex_codex_home.resolve())
    assert (tablex_codex_home / "auth.json").is_symlink()
    assert (tablex_codex_home / "auth.json").resolve() == (host_codex_home / "auth.json").resolve()
