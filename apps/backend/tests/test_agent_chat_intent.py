from __future__ import annotations

from tabular_harness.services.agent_chat import infer_chat_intent, next_focus_from_actions


def test_model_evidence_request_beats_top_run_comparison_intent() -> None:
    intent = infer_chat_intent(
        "Add artifact-backed feature importance and permutation importance evidence "
        "for the top Home Credit run, then tell me exactly what to read next."
    )

    assert intent["type"] == "plan_notebook_followup_task"
    assert "feature_importance" in intent["focus_areas"]
    assert "permutation_importance" in intent["focus_areas"]


def test_next_focus_prefers_materialized_model_evidence_readout() -> None:
    focus = next_focus_from_actions(
        [
            {
                "type": "create_notebook_followup_task",
                "status": "created",
                "label": "Prepared a targeted notebook follow-up task",
                "target_tab": "Approach",
                "target_anchor": "approach-handoff",
            },
            {
                "type": "materialize_model_diagnostics_artifacts",
                "status": "applied",
                "label": "Materialized model evidence artifacts",
                "target_tab": "Leaderboard",
                "target_anchor": "result-readout",
            },
        ]
    )

    assert focus["target_tab"] == "Leaderboard"
    assert focus["target_anchor"] == "result-readout"
