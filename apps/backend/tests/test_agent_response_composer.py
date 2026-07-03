from __future__ import annotations

from tabular_harness.services.agent_response_composer import (
    response_composer_model,
    response_shortcut_for_message,
)


def test_response_composer_model_uses_utility_model_when_set() -> None:
    assert response_composer_model({"model_preferences": {"utility_model": "gpt-5-mini"}}) == "gpt-5-mini"


def test_response_composer_model_skips_default_values() -> None:
    assert response_composer_model({"model_preferences": {"utility_model": "default"}}) is None
    assert response_composer_model({"model_preferences": {"utility_model": "codex-default"}}) is None
    assert response_composer_model({"model_preferences": {"utility_model": ""}}) is None


def test_btw_is_explicit_sidecar_status_shortcut() -> None:
    assert response_shortcut_for_message("/btw") == "btw_status_explanation"
    assert response_shortcut_for_message(" /BTW ") == "btw_status_explanation"
    assert response_shortcut_for_message("状況を説明してください") is None
