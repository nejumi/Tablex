from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Artifact, Base, Project
from tabular_harness.services import analysis_notebooks as analysis_notebooks_module
from tabular_harness.services.analysis_notebooks import (
    _model_metric_comparison,
    _notebook_content_signal,
    _notebook_recommendation_reason,
    _notebook_recommendation_score,
    _validate_marimo_notebook_source,
    build_project_notebook_index,
    extract_marimo_markdown_cells,
    list_latest_notebook_index_artifacts,
    notebook_execution_status,
    render_notebook_execution_html_preview,
    run_marimo_html_export,
    source_notebook_path_for_export,
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


def test_codex_authored_marimo_notebook_does_not_need_product_marker() -> None:
    source = """
import marimo

app = marimo.App()

@app.cell
def _():
    return
"""

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is True
    assert validation["is_capture_eligible"] is True
    assert "is_tablex_generated" not in validation


def test_codex_authored_marimo_notebook_allows_standard_alias_import() -> None:
    source = """
import marimo as mo

app = mo.App()

@app.cell
def _():
    return
"""

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is True
    assert validation["is_capture_eligible"] is True
    assert validation["checks"]["imports_marimo"] is True
    assert validation["checks"]["defines_marimo_app"] is True


def test_codex_authored_marimo_notebook_allows_direct_app_import() -> None:
    source = """
from marimo import App

app = App()

@app.cell
def _():
    return
"""

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is True
    assert validation["is_capture_eligible"] is True
    assert validation["checks"]["imports_marimo"] is True
    assert validation["checks"]["defines_marimo_app"] is True


def test_static_notebook_preview_renders_codex_authored_markdown_cells() -> None:
    source = '''
import marimo

app = marimo.App()

@app.cell
def _(mo):
    mo.md("""# salary 予測ノート

Codexが今回のデータから書いた説明です。

- `pay_period` を確認
- company split を利用
""")
    return
'''
    manifest = {
        "summary": {"headline": "marimo export failed"},
        "linked_artifacts": [{"role": "notebook", "asset_type": "analysis_notebook", "artifact_id": "art_nb"}],
        "marimo_export": {"status": "failed", "stderr_excerpt": "cell failed"},
    }

    html = render_notebook_execution_html_preview(manifest, source)

    assert extract_marimo_markdown_cells(source)[0].startswith("# salary")
    assert "salary 予測ノート" in html
    assert "Codexが今回のデータから書いた説明です。" in html
    assert "<code>pay_period</code>" in html
    assert "Notebook Execution Capture" not in html


def test_static_notebook_preview_skips_unexecuted_conditional_markdown() -> None:
    source = '''
import marimo

app = marimo.App()

@app.cell
def _(mo):
    mo.md("常に読む説明")
    if False:
        mo.md("実行されていない分岐")
    return
'''

    cells = extract_marimo_markdown_cells(source)

    assert cells == ["常に読む説明"]


def test_marimo_notebook_validation_does_not_accept_comment_markers_only() -> None:
    source = '''
# import marimo
# app = marimo.App()
text = "marimo.App should not make this a notebook"
'''

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is False
    assert validation["is_capture_eligible"] is False
    assert validation["checks"]["imports_marimo"] is False
    assert validation["checks"]["defines_marimo_app"] is False


def test_source_notebook_export_prefers_agent_workspace_without_cwd_dependency(tmp_path: Path) -> None:
    project_id = "p_export"
    session_id = "ags_export"
    store_root = tmp_path / "data" / "artifacts"
    stored_dir = store_root / "local-org" / project_id / "analysis_notebook" / "agent_notebook" / "v1"
    workspace_notebook = store_root / "agent_sessions" / project_id / session_id / "notebooks" / "report.py"
    stored_notebook = stored_dir / "report.py"
    workspace_notebook.parent.mkdir(parents=True)
    stored_dir.mkdir(parents=True)
    workspace_notebook.write_text("workspace copy", encoding="utf-8")
    stored_notebook.write_text("stored copy", encoding="utf-8")
    notebook = Artifact(
        id="art_notebook_export",
        org_id="local-org",
        project_id=project_id,
        asset_type="analysis_notebook",
        name="agent_notebook",
        version=1,
        uri=str(stored_dir),
        content_hash="hash",
        metadata_json=dumps_json(
            {
                "primary_path": str(stored_notebook),
                "agent_session_id": session_id,
                "workspace_relative_path": "notebooks/report.py",
            }
        ),
    )

    assert source_notebook_path_for_export(notebook) == workspace_notebook.resolve()


def test_marimo_html_export_disables_marimo_uv_sandbox(tmp_path: Path, monkeypatch: Any) -> None:
    notebook_path = tmp_path / "notebook.py"
    notebook_path.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")
    notebook = Artifact(
        id="art_marimo_export",
        org_id="local-org",
        project_id="p_export",
        asset_type="analysis_notebook",
        name="notebook",
        version=1,
        uri=str(tmp_path),
        content_hash="hash",
        metadata_json=dumps_json({"primary_path": str(notebook_path)}),
    )
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, capture_output, text, timeout, check
        captured["command"] = command
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("<html><body>ok</body></html>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(analysis_notebooks_module, "marimo_available", lambda: True)
    monkeypatch.setattr(analysis_notebooks_module.subprocess, "run", fake_run)

    result = run_marimo_html_export(notebook, notebook_path.read_text(encoding="utf-8"))

    assert result["status"] == "succeeded"
    assert "--no-sandbox" in captured["command"]


def artifact(
    artifact_id: str,
    *,
    project_id: str,
    asset_type: str,
    name: str,
    version: int = 1,
    metadata: dict[str, object] | None = None,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
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


def test_notebook_index_uses_latest_artifact_version_per_name(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_versions"
    session_id = "ags_notebook_versions"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Versions")
        older_notebook = artifact(
            "art_notebook_v1",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_ags_notebook_versions_notebooks_grandmaster_eda_py",
            version=1,
            metadata={
                "agent_session_id": session_id,
                "workspace_relative_path": "notebooks/grandmaster_eda.py",
                "notebook_kind": "data_understanding",
            },
        )
        latest_notebook = artifact(
            "art_notebook_v2",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_ags_notebook_versions_notebooks_grandmaster_eda_py",
            version=2,
            metadata={
                "agent_session_id": session_id,
                "workspace_relative_path": "notebooks/grandmaster_eda.py",
                "notebook_kind": "data_understanding",
            },
        )
        older_html = artifact(
            "art_html_v1",
            project_id=project_id,
            asset_type="agent_session_report",
            name="agent_session_ags_notebook_versions_reports_grandmaster_eda_html",
            version=1,
            metadata={"agent_session_id": session_id, "workspace_relative_path": "reports/grandmaster_eda.html"},
        )
        latest_html = artifact(
            "art_html_v2",
            project_id=project_id,
            asset_type="agent_session_report",
            name="agent_session_ags_notebook_versions_reports_grandmaster_eda_html",
            version=2,
            metadata={"agent_session_id": session_id, "workspace_relative_path": "reports/grandmaster_eda.html"},
        )
        db.add_all([project, older_notebook, latest_notebook, older_html, latest_html])
        db.commit()

        latest_artifacts = list_latest_notebook_index_artifacts(db, project_id)
        index = build_project_notebook_index(db, project)

        assert {artifact.id for artifact in latest_artifacts} == {"art_notebook_v2", "art_html_v2"}
        assert index["counts"]["total"] == 1
        item = index["items"][0]
        assert item["notebook_artifact_id"] == "art_notebook_v2"
        assert item["artifact_ids"]["html_preview"] == "art_html_v2"


def test_notebook_index_caps_figure_ids_and_targets_recommended_capture(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_caps"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Caps")
        data_notebook = artifact(
            "art_data_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="data_understanding_notebook",
            metadata={"notebook_kind": "data_understanding"},
        )
        newer_unknown_notebook = artifact(
            "art_unknown_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_side_notebook",
            metadata={"notebook_kind": "agent_authored"},
        )
        evidence_figures = [
            artifact(
                f"art_evidence_figure_{index}",
                project_id=project_id,
                asset_type="notebook_evidence_svg",
                name=f"notebook_evidence_figure_{index}",
                metadata={"notebook_artifact_id": data_notebook.id},
            )
            for index in range(20)
        ]
        db.add_all([project, data_notebook, newer_unknown_notebook, *evidence_figures])
        db.commit()

        index = build_project_notebook_index(db, project)

        recommended = index["recommended_notebook"]
        assert recommended["notebook_artifact_id"] == data_notebook.id
        assert recommended["coverage"]["evidence_figure_count"] == 20
        assert len(recommended["artifact_ids"]["evidence_figures"]) == 12
        assert index["next_actions"][0]["endpoint"] == f"/api/analysis-notebooks/{data_notebook.id}/execution-capture"


def test_notebook_index_uses_execution_manifest_status_when_notebook_metadata_is_unknown(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_execution_status"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Execution Status")
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="data_understanding_notebook",
            metadata={"notebook_kind": "data_understanding"},
        )
        execution_manifest = artifact(
            "art_execution_manifest",
            project_id=project_id,
            asset_type="notebook_execution_manifest",
            name="notebook_execution_manifest",
            metadata={
                "notebook_artifact_id": notebook.id,
                "execution_status": "marimo_export_succeeded",
            },
        )
        execution_html = artifact(
            "art_execution_html",
            project_id=project_id,
            asset_type="notebook_execution_html",
            name="notebook_execution_html",
            metadata={"notebook_artifact_id": notebook.id},
        )
        db.add_all([project, notebook, execution_manifest, execution_html])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["status"] == "marimo_export_succeeded"
        assert item["coverage"]["execution_status"] == "marimo_export_succeeded"
        assert item["coverage"]["execution_capture_status"] == "marimo_export_succeeded"
        assert item["coverage"]["has_execution_html"] is True
        assert item["coverage"]["has_html_preview"] is True
        assert index["counts"]["with_html_preview"] == 1
        assert item["artifact_ids"]["preview"] == "art_execution_html"
        assert item["preview_artifact_id"] == "art_execution_html"


def test_notebook_index_inherits_run_context_from_related_artifact_metadata(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_run_context"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Run Context")
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="model_diagnostics_notebook",
            metadata={"notebook_kind": "model_diagnostics"},
        )
        execution_manifest = artifact(
            "art_execution_manifest",
            project_id=project_id,
            asset_type="notebook_execution_manifest",
            name="notebook_execution_manifest",
            metadata={
                "notebook_artifact_id": notebook.id,
                "execution_status": "marimo_export_succeeded",
                "run_id": "run_context",
                "model_version_id": "mv_context",
            },
        )
        execution_html = artifact(
            "art_execution_html",
            project_id=project_id,
            asset_type="notebook_execution_html",
            name="notebook_execution_html",
            metadata={"notebook_artifact_id": notebook.id},
        )
        db.add_all([project, notebook, execution_manifest, execution_html])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["run_id"] == "run_context"
        assert item["model_version_id"] == "mv_context"
