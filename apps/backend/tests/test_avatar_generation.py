from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.main import create_app
from tabular_harness.services.avatar_generation import (
    AvatarCandidate,
    AvatarGenerationError,
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


def test_avatar_candidate_endpoint_returns_generated_data_urls(
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
        "tabular_harness.api.routes.generate_user_avatar_candidates",
        fake_generate_user_avatar_candidates,
    )

    response = client.post(
        "/api/user/avatar-candidates",
        json={"prompt": "friendly analyst avatar", "count": 3},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "candidates": [
            {
                "id": "candidate_1",
                "data_url": "data:image/png;base64,aGVsbG8=",
                "model": "test-image-model",
                "revised_prompt": "friendly analyst avatar, square icon",
            }
        ]
    }


def test_avatar_candidate_endpoint_reports_generator_unavailable(
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
        "tabular_harness.api.routes.generate_user_avatar_candidates",
        unavailable_generate_user_avatar_candidates,
    )

    response = client.post(
        "/api/user/avatar-candidates",
        json={"prompt": "friendly analyst avatar", "count": 3},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "OPENAI_API_KEY is not configured for image generation."


def test_avatar_generation_uses_codex_cli_without_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TABLEX_AVATAR_PROVIDER", raising=False)
    monkeypatch.setattr("tabular_harness.services.avatar_generation.shutil.which", lambda name: "/usr/bin/codex")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        check: bool,
        stdin: int,
        text: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["/usr/bin/codex", "exec"]
        assert "--skip-git-repo-check" in command
        assert "--sandbox" in command
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


def test_avatar_generation_reports_no_backend_when_codex_and_openai_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TABLEX_AVATAR_PROVIDER", raising=False)
    monkeypatch.setattr("tabular_harness.services.avatar_generation.shutil.which", lambda name: None)

    with pytest.raises(AvatarGenerationError) as exc_info:
        generate_user_avatar_candidates(prompt="friendly analyst avatar", count=1)

    assert exc_info.value.status_code == 503
    assert "Codex CLI image generation is preferred" in str(exc_info.value)
    assert "OPENAI_API_KEY is only needed" in str(exc_info.value)
