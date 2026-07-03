from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Artifact, Base, Project
from tabular_harness.services.analysis_notebooks import (
    _model_metric_comparison,
    _notebook_content_signal,
    _notebook_recommendation_reason,
    _notebook_recommendation_score,
    build_project_notebook_index,
    notebook_execution_status,
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


def test_model_metric_comparison_respects_metric_direction() -> None:
    auc_comparison = _model_metric_comparison(
        primary_metric_name="pr_auc",
        primary_metric_value=0.42,
        sanity_floor={"primary_metric_name": "pr_auc", "primary_metric_value": 0.2, "pr_auc": 0.2},
    )
    rmse_comparison = _model_metric_comparison(
        primary_metric_name="rmse",
        primary_metric_value=2.1,
        sanity_floor={"primary_metric_name": "rmse", "primary_metric_value": 3.0, "rmse": 3.0},
    )

    assert auc_comparison["status"] == "beats_sanity_floor"
    assert auc_comparison["delta"] > 0
    assert auc_comparison["higher_is_better"] is True
    assert rmse_comparison["status"] == "beats_sanity_floor"
    assert rmse_comparison["delta"] < 0
    assert rmse_comparison["higher_is_better"] is False


def test_notebook_execution_status_separates_marimo_failure_from_static_capture() -> None:
    compile_ok = {"status": "succeeded"}

    assert notebook_execution_status(compile_ok, {"status": "succeeded"}) == "marimo_export_succeeded"
    assert notebook_execution_status(compile_ok, {"status": "skipped"}) == "static_capture_succeeded"
    assert notebook_execution_status(compile_ok, {"status": "failed"}) == "marimo_export_failed"
    assert notebook_execution_status({"status": "failed"}, {"status": "succeeded"}) == "static_capture_failed"


def artifact(
    artifact_id: str,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    metadata: dict[str, object] | None = None,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=1,
        uri=f"/tmp/{artifact_id}",
        content_hash=artifact_id,
        metadata_json=dumps_json(metadata or {}),
    )


def test_notebook_index_ignores_unrelated_agent_session_reports(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_index"
    session_id = "ags_notebook_index"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Index")
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_ags_notebook_index_notebooks_grandmaster_eda_py",
            metadata={
                "agent_session_id": session_id,
                "workspace_relative_path": "notebooks/grandmaster_eda.py",
                "notebook_kind": "data_understanding",
            },
        )
        matching_html = artifact(
            "art_matching_html",
            project_id=project_id,
            asset_type="agent_session_report",
            name="agent_session_ags_notebook_index_reports_grandmaster_eda_html",
            metadata={"agent_session_id": session_id, "workspace_relative_path": "reports/grandmaster_eda.html"},
        )
        unrelated_reports = [
            artifact(
                f"art_unrelated_{index}",
                project_id=project_id,
                asset_type="agent_session_report",
                name=f"agent_session_ags_notebook_index_reports_unrelated_{index}_html",
                metadata={"agent_session_id": session_id, "workspace_relative_path": f"reports/unrelated_{index}.html"},
            )
            for index in range(300)
        ]
        db.add_all([project, notebook, matching_html, *unrelated_reports])
        db.commit()

        index = build_project_notebook_index(db, project)

        assert index["counts"]["total"] == 1
        assert index["counts"]["with_html_preview"] == 1
        item = index["items"][0]
        assert item["artifact_ids"]["html_preview"] == "art_matching_html"
