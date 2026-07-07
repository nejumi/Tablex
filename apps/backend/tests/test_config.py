from __future__ import annotations

from tabular_harness.agent.runners import codex_harness_config_args
from tabular_harness.core.config import get_settings


def test_agent_timeout_settings_can_be_overridden(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    monkeypatch.setenv("TABLEX_AGENT_IDLE_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("TABLEX_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("TABLEX_AGENT_SESSION_NETWORK_ENABLED", "false")
    monkeypatch.setenv("TABLEX_AGENT_SESSION_WEB_SEARCH_ENABLED", "false")
    monkeypatch.setenv("TABLEX_NOTEBOOK_DATA_COPY_MAX_BYTES", "4096")

    settings = get_settings()

    assert settings.agent_idle_timeout_seconds == 17
    assert settings.agent_turn_start_silence_timeout_seconds == 5
    assert settings.agent_session_network_enabled is False
    assert settings.agent_session_web_search_enabled is False
    assert settings.notebook_data_copy_max_bytes == 4096
    get_settings.cache_clear()


def test_codex_harness_config_args_can_enable_main_session_research_network() -> None:
    disabled_args = codex_harness_config_args(network_enabled=False, web_search_enabled=False)
    enabled_args = codex_harness_config_args(network_enabled=True, web_search_enabled=True)

    assert "sandbox_workspace_write.network_access=true" not in disabled_args
    assert "--enable" not in disabled_args
    assert 'web_search="live"' not in disabled_args
    assert "sandbox_workspace_write.network_access=true" in enabled_args
    assert "--enable" not in enabled_args
    assert 'web_search="live"' in enabled_args
