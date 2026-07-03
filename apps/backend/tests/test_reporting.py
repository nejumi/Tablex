from __future__ import annotations

from tabular_harness.api.routes import (
    artifact_preview_limit_bytes,
    artifact_preview_to_dict,
    report_to_dict,
)
from tabular_harness.models.entities import Artifact, Assumption, Project, Report, utc_now
from tabular_harness.services.reporting import (
    build_assumption_risk_spec,
    build_evaluation_readiness_spec,
    build_insight_payloads,
)


def test_assumption_risk_visualization_counts_risk_levels() -> None:
    assumptions = [
        Assumption(
            id="a1",
            project_id="p1",
            topic="leakage",
            statement="Final status may leak the target.",
            status="adopted",
            confidence=0.8,
            risk_level="high",
            fallback_policy="exclude_until_confirmed",
        ),
        Assumption(
            id="a2",
            project_id="p1",
            topic="metric",
            statement="Accuracy is acceptable for initial review.",
            status="adopted",
            confidence=0.6,
            risk_level="medium",
            fallback_policy="conservative_default",
        ),
    ]

    spec = build_assumption_risk_spec(assumptions)

    assert spec["chart_type"] == "category_bars"
    assert {"label": "high", "count": 1} in spec["data"]
    assert {"label": "medium", "count": 1} in spec["data"]


def test_evaluation_readiness_marks_missing_stages() -> None:
    spec = build_evaluation_readiness_spec(candidates=[], specs=[], splits=[], runs=[])

    assert spec["chart_type"] == "stage_status"
    assert all(row["status"] == "missing" for row in spec["data"])


def test_build_insight_payloads_keeps_sources_and_evaluation_warning() -> None:
    project = Project(id="p1", name="Demo", target_column="target")

    payloads = build_insight_payloads(
        project=project,
        dataset=None,
        profile_artifact=None,
        assumptions=[],
        candidates=[],
        specs=[],
        splits=[],
        runs=[],
        ideas=[],
        model_versions=[],
    )

    evaluation = next(item for item in payloads if item["insight_type"] == "evaluation_readiness")
    assert evaluation["severity"] == "warning"
    assert evaluation["source_asset_ids"] == [{"asset_type": "project", "asset_id": "p1"}]


def test_report_to_dict_normalizes_legacy_string_source_refs() -> None:
    report = Report(
        id="r1",
        project_id="p1",
        report_type="analysis_notebook",
        title="Notebook",
        summary="Summary",
        artifact_id="art_report",
        source_asset_ids_json='["art_profile", {"asset_id": "art_html", "asset_type": "artifact"}]',
        status="ready",
        created_by_type="agent",
        created_at=utc_now(),
    )

    payload = report_to_dict(report)

    assert payload["source_asset_ids"] == [
        {"asset_type": "artifact", "asset_id": "art_profile"},
        {"asset_type": "artifact", "asset_id": "art_html"},
    ]


def test_html_artifact_preview_inlines_local_images(tmp_path) -> None:
    report_dir = tmp_path / "reports"
    figure_dir = tmp_path / "outputs" / "figures"
    report_dir.mkdir()
    figure_dir.mkdir(parents=True)
    (figure_dir / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    html_path = report_dir / "notebook.html"
    html_path.write_text('<html><body><img src="../outputs/figures/chart.png"></body></html>', encoding="utf-8")
    artifact = Artifact(
        id="art_html",
        project_id="p1",
        asset_type="notebook_html",
        name="notebook_html",
        version=1,
        uri=str(html_path),
        content_hash="hash",
        size_bytes=html_path.stat().st_size,
        metadata_json="{}",
        created_at=utc_now(),
    )

    preview = artifact_preview_to_dict(artifact, html_path, limit_bytes=20_000)

    assert "data:image/png;base64," in preview["preview"]


def test_html_artifact_preview_limit_uses_file_type_not_only_asset_type(tmp_path) -> None:
    html_path = tmp_path / "agent_report.html"
    html_path.write_text("<html><body>Codex-authored report</body></html>", encoding="utf-8")
    markdown_path = tmp_path / "agent_report.md"
    markdown_path.write_text("# Report", encoding="utf-8")
    catalog_path = tmp_path / "relational_catalog.json"
    catalog_path.write_text("{}", encoding="utf-8")

    report_artifact = Artifact(
        id="art_agent_html",
        project_id="p1",
        asset_type="agent_session_report",
        name="agent_session_report",
        version=1,
        uri=str(html_path),
        content_hash="hash",
        size_bytes=html_path.stat().st_size,
        metadata_json="{}",
        created_at=utc_now(),
    )
    markdown_artifact = Artifact(
        id="art_agent_md",
        project_id="p1",
        asset_type="agent_session_report",
        name="agent_session_report",
        version=1,
        uri=str(markdown_path),
        content_hash="hash",
        size_bytes=markdown_path.stat().st_size,
        metadata_json="{}",
        created_at=utc_now(),
    )
    catalog_artifact = Artifact(
        id="art_relcat",
        project_id="p1",
        asset_type="relational_catalog",
        name="relational_catalog",
        version=1,
        uri=str(catalog_path),
        content_hash="hash",
        size_bytes=catalog_path.stat().st_size,
        metadata_json="{}",
        created_at=utc_now(),
    )

    assert artifact_preview_limit_bytes(report_artifact, html_path) == 5_000_000
    assert artifact_preview_limit_bytes(markdown_artifact, markdown_path) == 20_000
    assert artifact_preview_limit_bytes(catalog_artifact, catalog_path) == 500_000
