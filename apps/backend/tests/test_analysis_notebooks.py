from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    Base,
    DatasetSnapshot,
    ExperimentRun,
    LineageEdge,
    ModelVersion,
    Project,
)
from tabular_harness.services.analysis_notebooks import (
    _analysis_story_from_notebook,
    _model_metric_comparison,
    _notebook_content_signal,
    _notebook_recommendation_reason,
    _notebook_recommendation_score,
    _validate_marimo_notebook_source,
    build_project_notebook_index,
    list_latest_notebook_index_artifacts,
    marimo_available,
    marimo_notebook_runtime_preflight_for_artifact,
    marimo_notebook_source_hash_for_artifact,
    source_notebook_path_for_export,
    source_notebook_working_dir_for_export,
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
        "has_native_source": True,
        "has_report": True,
        "has_visualization": True,
        "has_execution_plan": False,
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
        "has_native_source": True,
        "has_report": True,
        "has_visualization": True,
        "has_execution_plan": False,
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
    assert validation["is_native_marimo_source"] is True
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
    assert validation["is_native_marimo_source"] is True
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
    assert validation["is_native_marimo_source"] is True
    assert validation["checks"]["imports_marimo"] is True
    assert validation["checks"]["defines_marimo_app"] is True


def test_marimo_notebook_validation_does_not_accept_comment_markers_only() -> None:
    source = '''
# import marimo
# app = marimo.App()
text = "marimo.App should not make this a notebook"
'''

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is False
    assert validation["is_native_marimo_source"] is False
    assert validation["checks"]["imports_marimo"] is False
    assert validation["checks"]["defines_marimo_app"] is False


def test_marimo_notebook_validation_rejects_duplicate_public_cell_variables() -> None:
    source = """
import marimo

app = marimo.App()

@app.cell
def _():
    fig = 1
    fig
    return

@app.cell
def _():
    fig = 2
    fig
    return
"""

    validation = _validate_marimo_notebook_source(source)

    assert validation["is_valid_marimo_notebook"] is False
    assert validation["checks"]["has_duplicate_public_cell_definitions"] is True
    assert validation["checks"]["duplicate_public_cell_definitions"] == [{"name": "fig", "lines": [8, 14]}]
    assert "fig" in validation["errors"][0]


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
    assert source_notebook_working_dir_for_export(notebook) == (
        store_root / "agent_sessions" / project_id / session_id
    ).resolve()


def test_marimo_runtime_preflight_reads_session_data_from_workspace_cwd(tmp_path: Path) -> None:
    if not marimo_available():
        pytest.skip("marimo is not installed")
    if importlib.util.find_spec("pandas") is None:
        pytest.skip("pandas is not installed")
    if importlib.util.find_spec("matplotlib") is None:
        pytest.skip("matplotlib is not installed")
    project_id = "p_marimo_data_access"
    session_id = "ags_marimo_data_access"
    store_root = tmp_path / "data" / "artifacts"
    stored_dir = store_root / "local-org" / project_id / "analysis_notebook" / "agent_notebook" / "v1"
    session_root = store_root / "agent_sessions" / project_id / session_id
    workspace_notebook = session_root / "notebooks" / "report.py"
    stored_notebook = stored_dir / "report.py"
    data_path = session_root / ".tablex" / "data" / "live.csv"
    workspace_notebook.parent.mkdir(parents=True)
    stored_dir.mkdir(parents=True)
    data_path.parent.mkdir(parents=True)
    data_path.write_text("x,y\nA,2\nB,5\n", encoding="utf-8")
    source = """
import marimo

app = marimo.App()

@app.cell
def _():
    from pathlib import Path
    import pandas as pd
    import matplotlib.pyplot as plt
    frame = pd.read_csv(Path(".tablex/data/live.csv"))
    _fig, _ax = plt.subplots()
    _ax.bar(frame["x"], frame["y"])
    _ax.set_title("session data access")
    _fig
    return
"""
    workspace_notebook.write_text(source, encoding="utf-8")
    stored_notebook.write_text(source, encoding="utf-8")
    notebook = Artifact(
        id="art_marimo_data_access",
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

    result = marimo_notebook_runtime_preflight_for_artifact(notebook, timeout_seconds=30)

    error_summary = str(result.get("error_summary") or "")
    if result.get("ok") is not True and "Operation not permitted" in error_summary and "multiprocessing" in error_summary:
        pytest.skip("local sandbox prevents marimo's multiprocessing socket during export")
    assert result["ok"] is True, result


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


def marimo_notebook_artifact(
    tmp_path: Path,
    artifact_id: str,
    *,
    project_id: str,
    name: str,
    notebook_kind: str,
    context: dict[str, object],
    version: int = 1,
) -> Artifact:
    stored_dir = tmp_path / project_id / artifact_id / f"v{version}"
    stored_dir.mkdir(parents=True)
    source_path = stored_dir / f"{name}.py"
    source_path.write_text(
        "import marimo\n\n"
        "app = marimo.App()\n\n"
        f"context = {dumps_json(context)}\n\n"
        "@app.cell\n"
        "def _():\n"
        "    return\n",
        encoding="utf-8",
    )
    return Artifact(
        id=artifact_id,
        project_id=project_id,
        asset_type="analysis_notebook",
        name=name,
        version=version,
        uri=str(stored_dir),
        content_hash=artifact_id,
        metadata_json=dumps_json({"notebook_kind": notebook_kind, "primary_path": str(source_path)}),
    )


def test_notebook_index_surfaces_invalid_native_source_instead_of_hiding_it(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_invalid_notebook_source"
    source_path = tmp_path / "invalid_notebook.py"
    source_path.write_text(
        """
import marimo

app = marimo.App()

@app.cell
def _():
    fig = 1
    return

@app.cell
def _():
    fig = 2
    return
""",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Invalid Notebook Source")
        notebook = artifact(
            "art_invalid_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="invalid_data_understanding",
            metadata={"notebook_kind": "data_understanding", "primary_path": str(source_path)},
        )
        db.add_all([project, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        assert index["counts"]["total"] == 1
        item = index["items"][0]
        assert item["notebook_artifact_id"] == notebook.id
        assert item["status"] == "needs_attention"
        assert item["coverage"]["native_marimo_status"] == "source_error"
        assert "fig" in item["coverage"]["native_marimo_source_errors"][0]


def test_notebook_index_uses_quality_manifest_for_content_readiness(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_quality_readiness"
    source_path = tmp_path / "quality_notebook.py"
    source_path.write_text(
        """
import marimo

app = marimo.App()

@app.cell
def _():
    import plotly.express as px
    return px,

@app.cell
def _(px):
    _fig = px.bar(x=["a", "b"], y=[1, 2])
    _fig
    return
""",
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Quality Readiness")
        notebook = artifact(
            "art_quality_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="quality_data_understanding",
            metadata={
                "notebook_kind": "data_understanding",
                "primary_path": str(source_path),
                "notebook_quality_status": "manifest_provided",
                "notebook_quality_manifest": {
                    "schema_version": "tablex_notebook_quality_manifest.v1",
                    "figure_count": 1,
                    "table_count": 0,
                    "key_findings": ["A registered finding is available."],
                    "read_order": [{"label": "Start here"}],
                    "data_sources_used": ["train.csv"],
                    "limitations": ["Fixture notebook."],
                },
            },
        )
        db.add_all([project, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["status"] == "ready"
        assert item["content"]["readiness"] == "narrative_ready"
        assert item["coverage"]["content_readiness"] == "narrative_ready"
        assert item["coverage"]["declared_figure_count"] == 1


def test_analysis_story_keeps_recommended_notebook_instead_of_diverting_to_data_notebook(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_story_no_diversion"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Story No Diversion")
        model_notebook = marimo_notebook_artifact(
            tmp_path,
            "art_empty_model_story",
            project_id=project_id,
            name="model_diagnostics",
            notebook_kind="model_diagnostics",
            context={
                "summary": {
                    "overview": "Model diagnostics source exists but result evidence is incomplete.",
                    "primary_metric_name": "mae",
                    "primary_metric_value": None,
                    "prediction_summary": {"status": "missing", "row_count": 0},
                    "evidence_readiness": "not_ready",
                    "evidence_quality_score": 0,
                }
            },
        )
        data_notebook = marimo_notebook_artifact(
            tmp_path,
            "art_data_story",
            project_id=project_id,
            name="data_understanding",
            notebook_kind="data_understanding",
            context={
                "summary": {
                    "overview": "Data understanding notebook is available.",
                    "analysis_brief": {"read_this_first": [{"title": "Start with rows", "why": "Shape first"}]},
                    "visual_story_cards": [{"title": "Target shape", "why_read": "Clarifies objective"}],
                    "eda_playbook": [{"stage": "Profile"}],
                }
            },
        )
        db.add_all([project, model_notebook, data_notebook])
        db.commit()

        story = _analysis_story_from_notebook(
            db,
            project,
            {
                "items": [
                    {
                        "notebook_artifact_id": model_notebook.id,
                        "notebook_kind": "model_diagnostics",
                        "title": "Model diagnostics",
                        "created_at": model_notebook.created_at.isoformat(),
                        "content": {"readiness": "not_ready"},
                        "artifact_ids": {"notebook": model_notebook.id, "source": model_notebook.id},
                        "recommendation_score": 100,
                        "recommendation_reason": "This is the selected story source even if its evidence is incomplete.",
                    },
                    {
                        "notebook_artifact_id": data_notebook.id,
                        "notebook_kind": "data_understanding",
                        "title": "Data understanding",
                        "created_at": data_notebook.created_at.isoformat(),
                        "content": {"readiness": "narrative_ready"},
                        "artifact_ids": {"notebook": data_notebook.id, "source": data_notebook.id},
                        "recommendation_score": 90,
                        "recommendation_reason": "Available but not selected.",
                    },
                ],
                "recommended_notebook": {
                    "notebook_artifact_id": model_notebook.id,
                    "notebook_kind": "model_diagnostics",
                    "title": "Model diagnostics",
                    "created_at": model_notebook.created_at.isoformat(),
                    "content": {"readiness": "not_ready"},
                    "artifact_ids": {"notebook": model_notebook.id, "source": model_notebook.id},
                    "recommendation_score": 100,
                    "recommendation_reason": "This is the selected story source even if its evidence is incomplete.",
                },
            },
        )

        assert story is not None
        assert story["selected_source"]["artifact_id"] == model_notebook.id
        assert story["primary_action"]["artifact_id"] == model_notebook.id
        assert any("incomplete" in caveat for caveat in story["caveats"])


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
        unrelated_reports = [
            artifact(
                f"art_unrelated_{index}",
                project_id=project_id,
                asset_type="agent_session_report",
                name=f"agent_session_ags_notebook_index_reports_unrelated_{index}_md",
                metadata={"agent_session_id": session_id, "workspace_relative_path": f"reports/unrelated_{index}.md"},
            )
            for index in range(300)
        ]
        db.add_all([project, notebook, *unrelated_reports])
        db.commit()

        index = build_project_notebook_index(db, project)

        assert index["counts"]["total"] == 1
        assert index["counts"]["with_native_source"] == 1
        item = index["items"][0]
        assert item["artifact_ids"]["source"] == notebook.id
        assert item["source_artifact_id"] == notebook.id
        assert "preview_artifact_id" not in item


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
        db.add_all([project, older_notebook, latest_notebook])
        db.commit()

        latest_artifacts = list_latest_notebook_index_artifacts(db, project_id)
        index = build_project_notebook_index(db, project)

        assert {artifact.id for artifact in latest_artifacts} == {"art_notebook_v2"}
        assert index["counts"]["total"] == 1
        item = index["items"][0]
        assert item["notebook_artifact_id"] == "art_notebook_v2"
        assert item["artifact_ids"]["source"] == "art_notebook_v2"


def test_notebook_index_caps_figure_ids_and_targets_recommended_native_source(tmp_path: Path) -> None:
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
        assert all("execution-capture" not in str(action.get("endpoint") or "") for action in index["next_actions"])


def test_notebook_index_uses_native_source_as_preview_when_notebook_metadata_is_unknown(tmp_path: Path) -> None:
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
        db.add_all([project, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["status"] == "needs_attention"
        assert item["coverage"]["notebook_quality_status"] == "needs_manifest"
        assert item["coverage"]["native_marimo_status"] == "source_registered"
        assert item["coverage"]["has_native_source"] is True
        assert index["counts"]["with_native_source"] == 1
        assert item["artifact_ids"]["source"] == notebook.id
        assert item["source_artifact_id"] == notebook.id
        assert "preview_artifact_id" not in item


def test_notebook_index_excludes_static_html_even_if_registered_as_notebook(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_static_html_guard"
    html_path = tmp_path / "grandmaster_eda_static.html"
    html_path.write_text("<html><body>static notebook snapshot</body></html>", encoding="utf-8")
    marimo_path = tmp_path / "grandmaster_eda.py"
    marimo_path.write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Static HTML Guard")
        static_html = artifact(
            "art_static_html_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_static_html",
            metadata={
                "notebook_kind": "data_understanding",
                "primary_path": str(html_path),
            },
        )
        marimo_source = artifact(
            "art_native_marimo_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_session_marimo_source",
            metadata={
                "notebook_kind": "data_understanding",
                "primary_path": str(marimo_path),
            },
        )
        db.add_all([project, static_html, marimo_source])
        db.commit()

        index = build_project_notebook_index(db, project)

        assert index["counts"]["total"] == 1
        assert [item["notebook_artifact_id"] for item in index["items"]] == [marimo_source.id]


def test_notebook_index_marks_native_marimo_runtime_failure_as_attention(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_runtime_failure_status"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Runtime Failure Status")
        broken_notebook = marimo_notebook_artifact(
            tmp_path,
            "art_runtime_broken_notebook",
            project_id=project_id,
            name="runtime_broken",
            notebook_kind="data_understanding",
            context={
                "summary": {
                    "overview": "This notebook has a useful story but currently fails in native marimo.",
                    "analysis_brief": {"read_this_first": [{"title": "Start", "why": "Useful when repaired"}]},
                    "visual_story_cards": [{"title": "Signal", "why_read": "Useful when repaired"}],
                    "eda_playbook": [{"stage": "Deep dive"}],
                }
            },
        )
        healthy_notebook = marimo_notebook_artifact(
            tmp_path,
            "art_runtime_healthy_notebook",
            project_id=project_id,
            name="runtime_healthy",
            notebook_kind="data_understanding",
            context={
                "summary": {
                    "overview": "This notebook opens cleanly.",
                    "analysis_brief": {"read_this_first": [{"title": "Read this", "why": "It opens"}]},
                    "visual_story_cards": [{"title": "Clean", "why_read": "No runtime failure"}],
                    "eda_playbook": [{"stage": "Review"}],
                }
            },
        )
        failure = artifact(
            "art_runtime_failure_chat",
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="native_marimo_runtime_failure",
            metadata={
                "source": "native_marimo_runtime_failure",
                "notebook_artifact_id": broken_notebook.id,
                "notebook_source_hash": marimo_notebook_source_hash_for_artifact(broken_notebook),
                "status": "failed",
            },
        )
        db.add_all([project, broken_notebook, healthy_notebook, failure])
        db.commit()

        index = build_project_notebook_index(db, project)

        by_id = {item["notebook_artifact_id"]: item for item in index["items"]}
        broken = by_id[broken_notebook.id]
        healthy = by_id[healthy_notebook.id]
        assert broken["status"] == "needs_attention"
        assert broken["coverage"]["native_marimo_status"] == "runtime_error"
        assert broken["coverage"]["native_marimo_error_artifact_id"] == failure.id
        assert "runtime error" in broken["recommendation_reason"]
        assert index["recommended_notebook"]["notebook_artifact_id"] == healthy_notebook.id
        assert index["items"][0]["notebook_artifact_id"] == healthy_notebook.id
        assert index["items"][-1]["notebook_artifact_id"] == broken_notebook.id
        assert healthy["recommendation_score"] > broken["recommendation_score"]


def test_notebook_index_accepts_list_shaped_visual_story_artifact(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_visual_story_list"
    session_id = "ags_visual_story_list"
    story_path = tmp_path / "visual_story_cards.json"
    story_path.write_text(
        dumps_json(
            [
                {"title": "Target distribution", "why_read": "Start with the response shape."},
                {"title": "Demand by store", "why_read": "Check group-level heterogeneity."},
            ]
        ),
        encoding="utf-8",
    )

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Visual Story List")
        notebook = marimo_notebook_artifact(
            tmp_path,
            "art_visual_story_notebook",
            project_id=project_id,
            name="data_understanding",
            notebook_kind="data_understanding",
            context={"summary": {"overview": "Codex-authored source only."}},
        )
        notebook.metadata_json = dumps_json(
            {
                "notebook_kind": "data_understanding",
                "primary_path": str(tmp_path / project_id / notebook.id / "v1" / "data_understanding.py"),
                "agent_session_id": session_id,
                "workspace_relative_path": "notebooks/data_understanding.py",
            }
        )
        visual_story = artifact(
            "art_visual_story_cards_list",
            project_id=project_id,
            asset_type="agent_session_report",
            name="visual_story_cards",
            metadata={
                "agent_session_id": session_id,
                "workspace_relative_path": "artifacts/visual_story_cards.json",
                "primary_path": str(story_path),
            },
        )
        db.add_all([project, notebook, visual_story])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["notebook_artifact_id"] == notebook.id
        assert item["content"]["story_card_count"] == 2


def test_notebook_index_ignores_stale_native_marimo_runtime_failure_after_source_changes(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_runtime_failure_stale"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Runtime Failure Stale")
        notebook = marimo_notebook_artifact(
            tmp_path,
            "art_runtime_repaired_notebook",
            project_id=project_id,
            name="runtime_repaired",
            notebook_kind="data_understanding",
            context={
                "summary": {
                    "overview": "This notebook source has changed after an earlier runtime failure.",
                    "analysis_brief": {"read_this_first": [{"title": "Current source", "why": "It is current"}]},
                    "visual_story_cards": [{"title": "Current", "why_read": "Source changed"}],
                    "eda_playbook": [{"stage": "Review current source"}],
                }
            },
        )
        stale_failure = artifact(
            "art_runtime_failure_stale_chat",
            project_id=project_id,
            asset_type="agent_chat_turn",
            name="native_marimo_runtime_failure_stale",
            metadata={
                "source": "native_marimo_runtime_failure",
                "notebook_artifact_id": notebook.id,
                "notebook_source_hash": "stale-source-hash",
                "status": "failed",
            },
        )
        db.add_all([project, notebook, stale_failure])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["notebook_artifact_id"] == notebook.id
        assert item["coverage"]["native_marimo_status"] == "source_registered"
        assert item["coverage"]["native_marimo_error_artifact_id"] is None
        assert "runtime error" not in item["recommendation_reason"]


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
            metadata={
                "notebook_kind": "model_diagnostics",
                "run_id": "run_context",
                "model_version_id": "mv_context",
            },
        )
        db.add_all([project, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["run_id"] == "run_context"
        assert item["model_version_id"] == "mv_context"


def test_notebook_index_links_data_notebook_to_unique_dataset_context(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_unique_dataset"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Unique Dataset")
        dataset_artifact = artifact(
            "art_dataset",
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
        )
        dataset = DatasetSnapshot(
            id="ds_unique",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_hash",
        )
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_data_understanding",
            metadata={"notebook_kind": "data_understanding"},
        )
        db.add_all([project, dataset_artifact, dataset, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["context_link_source"] == "unique_project_dataset"


def test_notebook_index_does_not_guess_dataset_when_multiple_exist(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_multiple_datasets"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Multiple Datasets")
        first_artifact = artifact(
            "art_dataset_a",
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="dataset_a",
        )
        second_artifact = artifact(
            "art_dataset_b",
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="dataset_b",
        )
        first_dataset = DatasetSnapshot(
            id="ds_a",
            project_id=project_id,
            artifact_id=first_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_a",
        )
        second_dataset = DatasetSnapshot(
            id="ds_b",
            project_id=project_id,
            artifact_id=second_artifact.id,
            source_type="upload",
            row_count=11,
            column_count=4,
            schema_hash="schema_b",
        )
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_data_understanding",
            metadata={"notebook_kind": "data_understanding"},
        )
        db.add_all([project, first_artifact, second_artifact, first_dataset, second_dataset, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["dataset_snapshot_id"] is None
        assert item["context_link_source"] == "none"


def test_notebook_index_links_model_notebook_to_unique_run_context(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_unique_run"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Unique Run")
        dataset_artifact = artifact(
            "art_dataset",
            project_id=project_id,
            asset_type="dataset_snapshot",
            name="uploaded_dataset",
        )
        model_artifact = artifact(
            "art_model",
            project_id=project_id,
            asset_type="model_package",
            name="model_package",
        )
        dataset = DatasetSnapshot(
            id="ds_unique",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_hash",
        )
        run = ExperimentRun(
            id="run_unique",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        model_version = ModelVersion(
            id="mv_unique",
            project_id=project_id,
            experiment_run_id=run.id,
            dataset_snapshot_id=dataset.id,
            artifact_id=model_artifact.id,
            name="model",
            version=1,
            model_family="tree",
            model_type="regressor",
            task_type="regression",
            status="created",
        )
        run.model_version_id = model_version.id
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_model_diagnostics",
            metadata={"notebook_kind": "model_diagnostics"},
        )
        db.add_all([project, dataset_artifact, model_artifact, dataset, run, model_version, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["run_id"] == run.id
        assert item["model_version_id"] == model_version.id
        assert item["context_link_source"] == "unique_project_run"


def test_notebook_index_does_not_guess_run_when_multiple_exist(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_multiple_runs"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Multiple Runs")
        first_run = ExperimentRun(id="run_a", project_id=project_id, runner_type="codex_cli", status="succeeded")
        second_run = ExperimentRun(id="run_b", project_id=project_id, runner_type="codex_cli", status="succeeded")
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_model_diagnostics",
            metadata={"notebook_kind": "model_diagnostics"},
        )
        db.add_all([project, first_run, second_run, notebook])
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["run_id"] is None
        assert item["model_version_id"] is None
        assert item["context_link_source"] == "none"


def test_notebook_index_links_run_from_same_research_plan_node_without_guessing(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_plan_node_run"
    revision_id = "rpr_notebook_plan_node"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Plan Node Run")
        dataset_artifact = artifact(
            "art_dataset",
            project_id=project_id,
            asset_type="dataset_file",
            name="dataset_file",
        )
        dataset = DatasetSnapshot(
            id="ds_plan_node",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_hash",
        )
        first_run = ExperimentRun(
            id="run_notebook_node",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        second_run = ExperimentRun(id="run_unrelated", project_id=project_id, runner_type="codex_cli", status="succeeded")
        notebook = artifact(
            "art_notebook",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_model_diagnostics",
            metadata={"notebook_kind": "model_diagnostics"},
        )
        db.add_all(
            [
                project,
                dataset_artifact,
                dataset,
                first_run,
                second_run,
                notebook,
                LineageEdge(
                    id="le_notebook_node",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id=revision_id,
                    to_asset_type="artifact",
                    to_asset_id=notebook.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json({"revision_id": revision_id, "node_id": "modeling", "role": "notebook_source"}),
                ),
                LineageEdge(
                    id="le_run_node",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id=revision_id,
                    to_asset_type="experiment_run",
                    to_asset_id=first_run.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json({"revision_id": revision_id, "node_id": "modeling", "role": "experiment_run"}),
                ),
            ]
        )
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["run_id"] == first_run.id
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["context_link_source"] == "research_plan_node"
        assert item["research_plan_node_id"] == "modeling"
        assert item["related_run_ids"] == [first_run.id]


def test_notebook_index_links_multiple_runs_from_same_research_plan_node(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_plan_node_runs"
    research_plan_id = "rplan_notebook_context"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Plan Node Runs")
        dataset_artifact = artifact(
            "art_dataset_multi",
            project_id=project_id,
            asset_type="dataset_file",
            name="dataset_file",
        )
        dataset = DatasetSnapshot(
            id="ds_plan_node_multi",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_hash",
        )
        first_run = ExperimentRun(
            id="run_notebook_node_a",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        second_run = ExperimentRun(
            id="run_notebook_node_b",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        unrelated_run = ExperimentRun(
            id="run_notebook_node_other",
            project_id=project_id,
            dataset_snapshot_id=dataset.id,
            runner_type="codex_cli",
            status="succeeded",
        )
        notebook = artifact(
            "art_notebook_multi",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_model_comparison",
            metadata={"notebook_kind": "model_diagnostics"},
        )
        db.add_all(
            [
                project,
                dataset_artifact,
                dataset,
                first_run,
                second_run,
                unrelated_run,
                notebook,
                LineageEdge(
                    id="le_notebook_node_multi",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id="rpr_notebook_plan_latest",
                    to_asset_type="artifact",
                    to_asset_id=notebook.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json(
                        {
                            "research_plan_id": research_plan_id,
                            "revision_id": "rpr_notebook_plan_latest",
                            "node_id": "modeling",
                            "role": "notebook_source",
                        }
                    ),
                ),
                LineageEdge(
                    id="le_run_node_a",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id="rpr_notebook_plan_a",
                    to_asset_type="experiment_run",
                    to_asset_id=first_run.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json(
                        {
                            "research_plan_id": research_plan_id,
                            "revision_id": "rpr_notebook_plan_a",
                            "node_id": "modeling",
                            "role": "experiment_run",
                        }
                    ),
                ),
                LineageEdge(
                    id="le_run_node_b",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id="rpr_notebook_plan_b",
                    to_asset_type="experiment_run",
                    to_asset_id=second_run.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json(
                        {
                            "research_plan_id": research_plan_id,
                            "revision_id": "rpr_notebook_plan_b",
                            "node_id": "modeling",
                            "role": "experiment_run",
                        }
                    ),
                ),
                LineageEdge(
                    id="le_run_node_other",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id="rpr_notebook_plan_other",
                    to_asset_type="experiment_run",
                    to_asset_id=unrelated_run.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json(
                        {
                            "research_plan_id": research_plan_id,
                            "revision_id": "rpr_notebook_plan_other",
                            "node_id": "diagnostics",
                            "role": "experiment_run",
                        }
                    ),
                ),
            ]
        )
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["run_id"] is None
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["context_link_source"] == "research_plan_node_runs"
        assert item["research_plan_id"] == research_plan_id
        assert item["research_plan_node_id"] == "modeling"
        assert set(item["related_run_ids"]) == {first_run.id, second_run.id}


def test_notebook_index_links_plan_node_notebook_to_unique_project_dataset(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    project_id = "p_notebook_plan_node_dataset"
    revision_id = "rpr_notebook_plan_dataset"

    with sessionmaker(engine)() as db:
        project = Project(id=project_id, name="Notebook Plan Node Dataset")
        dataset_artifact = artifact(
            "art_dataset_unique",
            project_id=project_id,
            asset_type="dataset_file",
            name="dataset_file",
        )
        dataset = DatasetSnapshot(
            id="ds_plan_node_unique",
            project_id=project_id,
            artifact_id=dataset_artifact.id,
            source_type="upload",
            row_count=10,
            column_count=3,
            schema_hash="schema_hash",
        )
        notebook = artifact(
            "art_notebook_dataset",
            project_id=project_id,
            asset_type="analysis_notebook",
            name="agent_data_report",
            metadata={"notebook_kind": "agent_authored"},
        )
        db.add_all(
            [
                project,
                dataset_artifact,
                dataset,
                notebook,
                LineageEdge(
                    id="le_notebook_node_dataset",
                    project_id=project_id,
                    from_asset_type="research_plan_revision",
                    from_asset_id=revision_id,
                    to_asset_type="artifact",
                    to_asset_id=notebook.id,
                    relation_type="supports_plan_node",
                    metadata_json=dumps_json(
                        {"revision_id": revision_id, "node_id": "data_understanding", "role": "notebook_source"}
                    ),
                ),
            ]
        )
        db.commit()

        index = build_project_notebook_index(db, project)

        item = index["items"][0]
        assert item["dataset_snapshot_id"] == dataset.id
        assert item["run_id"] is None
        assert item["context_link_source"] == "research_plan_node"
        assert item["research_plan_node_id"] == "data_understanding"
