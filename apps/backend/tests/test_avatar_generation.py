from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tabular_harness.core.config import Settings
from tabular_harness.main import create_app
from tabular_harness.services.avatar_generation import AvatarCandidate, AvatarGenerationError


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
