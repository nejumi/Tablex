from __future__ import annotations

from tabular_harness.services.agent_response_composer import (
    codex_unavailable_message,
    parse_composer_decision,
    response_composer_model,
    response_shortcut_for_message,
)


def test_response_composer_model_uses_utility_model_when_set() -> None:
    assert response_composer_model({"model_preferences": {"utility_model": "gpt-5-mini"}}) == "gpt-5-mini"


def test_response_composer_model_skips_default_values() -> None:
    assert response_composer_model({"model_preferences": {"utility_model": "default"}}) is None
    assert response_composer_model({"model_preferences": {"utility_model": "codex-default"}}) is None
    assert response_composer_model({"model_preferences": {"utility_model": "utility-default"}}) is None
    assert response_composer_model({"model_preferences": {"utility_model": ""}}) is None


def test_btw_is_explicit_sidecar_status_shortcut() -> None:
    assert response_shortcut_for_message("/btw") == "btw_status_explanation"
    assert response_shortcut_for_message(" /BTW ") == "btw_status_explanation"
    assert response_shortcut_for_message("状況を説明してください") is None


def test_codex_unavailable_message_does_not_expose_unfinished_placeholder_copy() -> None:
    message = codex_unavailable_message({"response_locale": "Japanese", "composer_warning": "Codex CLI exited with 1."})

    assert "まだ実行" not in message
    assert "まだ生成" not in message
    assert "Codex CLI exited" not in message
    assert "入力は保存済み" in message
    assert "Raw" in message


def test_parse_composer_decision_accepts_handoff_json() -> None:
    parsed = parse_composer_decision(
        '{"handoff_to_main_session": true, "message": null, "handoff_reason": "Need to inspect the training script."}'
    )

    assert parsed["handoff_to_main_session"] is True
    assert parsed["message"] is None
    assert parsed["handoff_reason"] == "Need to inspect the training script."


def test_parse_composer_decision_preserves_plain_text_answer() -> None:
    parsed = parse_composer_decision("The saved project records show three runs.")

    assert parsed["handoff_to_main_session"] is False
    assert parsed["message"] == "The saved project records show three runs."
    assert parsed["handoff_reason"] is None
