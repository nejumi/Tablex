from __future__ import annotations

from tabular_harness.models.entities import Assumption, Project
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
