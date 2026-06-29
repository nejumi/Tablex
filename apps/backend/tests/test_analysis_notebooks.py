from __future__ import annotations

from tabular_harness.services.analysis_notebooks import (
    _notebook_content_signal,
    _notebook_recommendation_reason,
    _notebook_recommendation_score,
)


def test_empty_model_diagnostics_is_not_recommended_as_real_evidence() -> None:
    content = _notebook_content_signal(
        "model_diagnostics",
        {
            "primary_metric_name": "pr_auc",
            "primary_metric_value": None,
            "prediction_summary": {"status": "missing", "row_count": 0},
            "evidence_readiness": "not_ready",
            "evidence_quality_score": 0,
        },
    )
    coverage = {
        "has_html_preview": True,
        "has_report": True,
        "has_visualization": True,
        "has_execution_plan": False,
        "has_execution_capture": True,
        "execution_status": "generated_not_executed",
    }

    score = _notebook_recommendation_score("model_diagnostics", coverage, {"run_id": "run_empty"}, content)
    reason = _notebook_recommendation_reason("model_diagnostics", coverage, content)

    assert content["readiness"] == "not_ready"
    assert content["prediction_rows"] == 0
    assert score < 50
    assert "not useful yet" in reason


def test_evidence_ready_model_diagnostics_can_beat_data_understanding() -> None:
    model_content = _notebook_content_signal(
        "model_diagnostics",
        {
            "primary_metric_name": "pr_auc",
            "primary_metric_value": 0.72,
            "prediction_summary": {"status": "available", "row_count": 500},
            "evidence_readiness": "evidence_ready",
            "evidence_quality_score": 85,
        },
    )
    data_content = _notebook_content_signal(
        "data_understanding",
        {
            "analysis_brief": {"read_this_first": [{"title": "Start"}]},
            "visual_story_cards": [{"title": "Shape"}, {"title": "Target"}],
            "eda_playbook": [{"stage": "Review"}],
            "feature_family_summary": [{"family": "numeric"}, {"family": "categorical"}],
        },
    )
    shared_coverage = {
        "has_html_preview": True,
        "has_report": True,
        "has_visualization": True,
        "has_execution_plan": False,
        "has_execution_capture": False,
        "execution_status": "generated_not_executed",
    }

    model_score = _notebook_recommendation_score(
        "model_diagnostics", shared_coverage, {"run_id": "run_ready"}, model_content
    )
    data_score = _notebook_recommendation_score("data_understanding", shared_coverage, {}, data_content)

    assert model_content["readiness"] == "evidence_ready"
    assert model_score > data_score
