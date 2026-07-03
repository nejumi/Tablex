from __future__ import annotations

import inspect

from tabular_harness.api.routes import is_sidecar_chat_request
import tabular_harness.services.agent_chat as agent_chat
from tabular_harness.models.entities import AgentSession
from tabular_harness.services.agent_chat import (
    conversation_next_focus,
    session_has_observed_codex_process,
)


def test_agent_chat_has_no_natural_language_intent_router() -> None:
    prohibited = [
        "infer_chat_intent",
        "extract_metric",
        "extract_model_candidates",
        "notebook_followup_focus_areas",
        "is_model_candidate_run_request",
        "is_leaderboard_request",
        "is_next_step_request",
    ]

    for name in prohibited:
        assert not hasattr(agent_chat, name)


def test_agent_chat_source_does_not_keyword_match_user_language() -> None:
    source = inspect.getsource(agent_chat)

    prohibited_fragments = [
        "word in normalized",
        "phrase in normalized",
        "normalized =",
        "contains_japanese_text",
        "set_evaluation_metric",
        "show_leaderboard",
        "plan_agent_task",
    ]
    for fragment in prohibited_fragments:
        assert fragment not in source


def test_sidecar_chat_escape_is_only_an_explicit_slash_command() -> None:
    assert is_sidecar_chat_request("/btw") is True
    assert is_sidecar_chat_request(" /BTW ") is True

    natural_language_messages = [
        "状況を説明してください",
        "btw, what is running now?",
        "状況 /btw",
        "by the way, explain this project",
    ]
    for message in natural_language_messages:
        assert is_sidecar_chat_request(message) is False


def test_conversation_next_focus_uses_project_guidance_context() -> None:
    focus = conversation_next_focus(
        {
            "recommended_focus": {
                "title": "Review evaluation",
                "target_tab": "Evaluation",
                "primary_action": {
                    "label": "Open evaluation design",
                    "target_tab": "Evaluation",
                    "target_anchor": "evaluation-design",
                },
            }
        }
    )

    assert focus["target_tab"] == "Evaluation"
    assert focus["target_anchor"] == "evaluation-design"
    assert focus["label"] == "Open evaluation design"


def test_session_process_observation_requires_matching_codex_process() -> None:
    session = AgentSession(
        id="ags_pid",
        project_id="p_pid",
        session_type="main_autonomous",
        status="running",
        pid=101,
    )

    assert session_has_observed_codex_process(session, [{"pid": 202, "command": "codex exec --cd /tmp/p_pid/ags_pid"}]) is False
    assert session_has_observed_codex_process(session, [{"pid": 101, "command": "codex exec --cd /tmp/p_pid/ags_pid"}]) is True

    session.pid = None
    assert session_has_observed_codex_process(session, [{"pid": 303, "command": "codex exec --cd /tmp/p_pid/ags_pid"}]) is True
