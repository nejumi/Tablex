from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tabular_harness.services import agent_response_composer
from tabular_harness.services.agent_response_composer import compose_with_codex_cli
from tabular_harness.services.project_execution_control import (
    request_project_execution_stop,
    wait_for_project_execution_stop_ack,
)
from tabular_harness.worker import agent_supervisor_cli


def test_host_supervisor_requires_stable_zero_process_ack(tmp_path, monkeypatch: Any) -> None:
    request = request_project_execution_stop(tmp_path, project_id="p_control_test")
    observations = [
        [{"pid": 1234, "command": "codex exec --cd /data/p_control_test/work"}],
        [],
        [],
        [],
    ]
    terminated: list[int] = []

    monkeypatch.setattr(
        agent_supervisor_cli,
        "running_codex_processes_for_project",
        lambda project_id: observations.pop(0),
    )
    monkeypatch.setattr(
        agent_supervisor_cli,
        "terminate_stale_codex_process",
        lambda pid: terminated.append(pid) or True,
    )

    agent_supervisor_cli.reconcile_project_execution_stop_requests(tmp_path)
    first_ack = wait_for_project_execution_stop_ack(
        tmp_path, request=request, timeout_seconds=0.01
    )
    assert first_ack["verified"] is False

    agent_supervisor_cli.reconcile_project_execution_stop_requests(tmp_path)
    second_ack = wait_for_project_execution_stop_ack(
        tmp_path, request=request, timeout_seconds=0.01
    )
    assert second_ack["verified"] is True
    assert second_ack["consecutive_zero_observations"] == 2
    assert terminated == [1234]


def test_response_composer_does_not_start_codex_after_power_off(
    tmp_path, monkeypatch: Any
) -> None:
    request_project_execution_stop(tmp_path, project_id="p_stopped")
    monkeypatch.setattr(
        agent_response_composer,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )
    monkeypatch.setattr(agent_response_composer.shutil, "which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(
        agent_response_composer.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Codex must not start")),
    )

    result = compose_with_codex_cli({"project": {"id": "p_stopped"}})

    assert result.status == "cancelled"
    assert result.message is None
