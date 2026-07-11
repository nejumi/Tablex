from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.main import create_app
from tabular_harness.services.avatar_generation import (
    AvatarCandidate,
    AvatarGenerationError,
    ensure_codex_cli_authenticated,
    generate_user_avatar_candidates,
)


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'data' / 'metadata' / 'app.db'}",
        artifact_root=tmp_path / "data" / "artifacts",
        max_upload_bytes=100 * 1024 * 1024,
        cors_origins=("http://localhost:5173",),
    )
    return TestClient(create_app(settings))


def test_avatar_candidate_endpoint_queues_generated_data_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)

    def fake_generate_user_avatar_candidates(
        *,
        prompt: str,
        count: int,
        user: str | None = None,
    ) -> list[AvatarCandidate]:
        assert prompt == "friendly analyst avatar"
        assert count == 3
        assert user == "tablex-user-avatar"
        return [
            AvatarCandidate(
                id="candidate_1",
                data_url="data:image/png;base64,aGVsbG8=",
                model="test-image-model",
                revised_prompt="friendly analyst avatar, square icon",
            )
        ]

    monkeypatch.setattr(
        "tabular_harness.worker.jobs.generate_user_avatar_candidates",
        fake_generate_user_avatar_candidates,
    )

    response = client.post(
        "/api/user/avatar-candidates",
        json={"prompt": "friendly analyst avatar", "count": 3},
    )

    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"
    assert job["job_type"] == "generate_user_avatar_candidates"
    assert job["policy"]["execution"] == "queued_worker"

    worker_response = client.post("/api/worker/run-once?include_long_running=true")
    assert worker_response.status_code == 200, worker_response.text
    completed = worker_response.json()
    assert completed["id"] == job["id"]
    assert completed["status"] == "succeeded"
    assert completed["output"] == {
        "candidates": [
            {
                "id": "candidate_1",
                "data_url": "data:image/png;base64,aGVsbG8=",
                "model": "test-image-model",
                "revised_prompt": "friendly analyst avatar, square icon",
            }
        ],
        "candidate_count": 1,
        "worker_events": [
            {
                "worker_id": "avatar-generator",
                "display_name": "Avatar Generator",
                "status": "succeeded",
                "headline": "Avatar candidates generated",
                "detail": "Generated 1 user avatar candidate(s).",
                "target_tab": "Settings",
                "target_anchor": "user-avatar",
                "current_tokens": 40,
                "cumulative_tokens": 120,
                "token_series": [18, 45, 72, 120],
                "source": "avatar_generation_worker",
            }
        ],
    }


def test_avatar_candidate_worker_reports_generator_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)

    def unavailable_generate_user_avatar_candidates(
        *,
        prompt: str,
        count: int,
        user: str | None = None,
    ) -> list[AvatarCandidate]:
        raise AvatarGenerationError("OPENAI_API_KEY is not configured for image generation.", status_code=503)

    monkeypatch.setattr(
        "tabular_harness.worker.jobs.generate_user_avatar_candidates",
        unavailable_generate_user_avatar_candidates,
    )

    response = client.post(
        "/api/user/avatar-candidates",
        json={"prompt": "friendly analyst avatar", "count": 3},
    )

    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "queued"

    worker_response = client.post("/api/worker/run-once?include_long_running=true")
    assert worker_response.status_code == 200, worker_response.text
    completed = worker_response.json()
    assert completed["id"] == job["id"]
    assert completed["status"] == "failed"
    assert completed["error_message"] == "OPENAI_API_KEY is not configured for image generation."


def test_avatar_generation_uses_codex_cli_without_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TABLEX_AVATAR_PROVIDER", raising=False)
    monkeypatch.setattr("tabular_harness.services.avatar_generation.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.services.avatar_generation.ensure_codex_cli_authenticated",
        lambda codex: None,
    )

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        check: bool,
        stdin: int,
        text: bool,
        timeout: int,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["/usr/bin/codex", "exec"]
        assert "--skip-git-repo-check" in command
        assert "--sandbox" not in command
        assert Path(env["CODEX_HOME"]) != Path(os.environ.get("CODEX_HOME", ""))
        config_text = (Path(env["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8")
        assert "default_permissions = \"workspace\"" in config_text
        assert capture_output is True
        assert check is False
        assert text is True
        assert timeout >= 30
        assert stdin == subprocess.DEVNULL
        workdir = Path(cwd)
        (workdir / "candidate_1.png").write_bytes(b"\x89PNG\r\n\x1a\navatar")
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text(
            json.dumps({"files": ["candidate_1.png"], "revised_prompt": "friendly avatar"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("tabular_harness.services.avatar_generation.subprocess.run", fake_run)

    candidates = generate_user_avatar_candidates(prompt="friendly analyst avatar", count=1)

    assert len(candidates) == 1
    assert candidates[0].model == "codex-cli:gpt-image-2"
    assert candidates[0].data_url.startswith("data:image/png;base64,")
    assert candidates[0].revised_prompt == "friendly avatar"


def test_avatar_generation_collects_builtin_generated_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.delenv("TABLEX_AVATAR_PROVIDER", raising=False)
    monkeypatch.setattr("tabular_harness.services.avatar_generation.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "tabular_harness.services.avatar_generation.ensure_codex_cli_authenticated",
        lambda codex: None,
    )

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        generated = Path(str(env["CODEX_HOME"])) / "generated_images" / "session-1" / "generated.png"
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"\x89PNG\r\n\x1a\navatar")
        result_path = Path(command[command.index("--output-last-message") + 1])
        result_path.write_text(
            json.dumps({"files": [str(generated)], "revised_prompt": "built-in avatar"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("tabular_harness.services.avatar_generation.subprocess.run", fake_run)

    candidates = generate_user_avatar_candidates(prompt="friendly analyst avatar", count=1)

    assert len(candidates) == 1
    assert candidates[0].data_url.startswith("data:image/png;base64,")
    assert candidates[0].revised_prompt == "built-in avatar"



def test_avatar_generation_requires_codex_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tabular_harness.services.avatar_generation.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="Not logged in", stderr=""),
    )

    with pytest.raises(AvatarGenerationError) as exc_info:
        ensure_codex_cli_authenticated("/usr/bin/codex")

    assert exc_info.value.status_code == 503
    assert "not authenticated for Tablex" in str(exc_info.value)


def test_avatar_generation_reports_no_backend_when_codex_and_openai_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TABLEX_AVATAR_PROVIDER", raising=False)
    monkeypatch.setattr("tabular_harness.services.avatar_generation.shutil.which", lambda name: None)

    with pytest.raises(AvatarGenerationError) as exc_info:
        generate_user_avatar_candidates(prompt="friendly analyst avatar", count=1)

    assert exc_info.value.status_code == 503
    assert "Codex CLI is not available" in str(exc_info.value)
