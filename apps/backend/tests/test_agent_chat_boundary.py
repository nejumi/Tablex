from __future__ import annotations

import inspect

import tabular_harness.services.agent_chat as agent_chat
from tabular_harness.services.agent_chat import conversation_next_focus


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
