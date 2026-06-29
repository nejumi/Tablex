from __future__ import annotations

from typing import Any

from tabular_harness.services.baseline import (
    ROW_INDEX_COLUMN,
    SPLIT_VALUE_COLUMN,
    TARGET_VALUE_COLUMN,
    build_baseline_plan,
    build_baseline_plan_from_profile,
    build_feature_dict,
    run_classification_baseline,
)


def row(index: int, split: str, feature: float, target: int, leakage: str) -> dict[str, Any]:
    return {
        ROW_INDEX_COLUMN: index,
        SPLIT_VALUE_COLUMN: split,
        TARGET_VALUE_COLUMN: target,
        "feature": feature,
        "target": target,
        "leakage_status": leakage,
        "segment": "high" if feature > 5 else "low",
    }


def rich_row(index: int, split: str, feature: float, target: int) -> dict[str, Any]:
    return {
        ROW_INDEX_COLUMN: index,
        SPLIT_VALUE_COLUMN: split,
        TARGET_VALUE_COLUMN: target,
        "customer_id": f"cust-{index}",
        "created_at": f"2026-01-{index + 1:02d}",
        "feature": feature,
        "segment": "high" if feature > 5 else "low",
        "support_note": "customer asked about renewal timing and pricing pressure",
        "target": target,
    }


def test_build_feature_dict_excludes_target_leakage_and_system_columns() -> None:
    features = build_feature_dict(
        row(0, "train", 3.0, 1, "won"),
        target_column="target",
        excluded_columns=["leakage_status"],
    )

    assert features == {"feature": 3.0, "segment": "low"}


def test_baseline_plan_detects_text_datetime_and_identifier_columns() -> None:
    rows = [rich_row(index, "train" if index < 4 else "valid", float(index), index % 2) for index in range(6)]

    plan = build_baseline_plan(
        rows,
        task_type="binary_classification",
        target_column="target",
        primary_metric="accuracy",
        excluded_columns=[],
        evaluation_spec=None,
    )

    assert "feature" in plan["numeric_columns"]
    assert "segment" in plan["categorical_columns"]
    assert "support_note" in plan["text_columns"]
    assert "created_at" in plan["datetime_columns"]
    assert "customer_id" in plan["identifier_columns"]


def test_baseline_plan_from_profile_uses_resource_guard_without_rows() -> None:
    profile = {
        "profile_mode": "bounded_sample",
        "column_stat_scope": "sample",
        "profile_sample": {"sample_row_count": 50_000},
        "deferred_deep_profile": {"recommended": True},
        "columns": [
            {"name": "SK_ID_CURR", "physical_type": "BIGINT", "semantic_type": "identifier", "role": "identifier"},
            {"name": "TARGET", "physical_type": "BIGINT", "semantic_type": "numeric", "role": "target"},
            {"name": "AMT_INCOME_TOTAL", "physical_type": "DOUBLE", "semantic_type": "numeric", "role": "feature"},
            {"name": "NAME_CONTRACT_TYPE", "physical_type": "VARCHAR", "semantic_type": "categorical", "role": "feature"},
        ],
    }

    plan = build_baseline_plan_from_profile(
        profile,
        task_type="binary_classification",
        target_column="TARGET",
        primary_metric="pr_auc",
        excluded_columns=[],
        evaluation_spec=None,
        row_count=307_511,
        column_count=122,
    )

    assert plan["planning_source"] == "eda_profile"
    assert plan["resource_guard"]["level"] == "large_local_run"
    assert "AMT_INCOME_TOTAL" in plan["numeric_columns"]
    assert "NAME_CONTRACT_TYPE" in plan["categorical_columns"]
    assert "SK_ID_CURR" in plan["identifier_columns"]
    assert "TARGET" not in plan["numeric_columns"]


def test_classification_baseline_runs_model_with_dummy_sanity_floor() -> None:
    rows = [
        row(0, "train", 0.0, 0, "lost"),
        row(1, "train", 1.0, 0, "lost"),
        row(2, "train", 9.0, 1, "won"),
        row(3, "train", 10.0, 1, "won"),
        row(4, "valid", 0.2, 0, "lost"),
        row(5, "valid", 10.5, 1, "won"),
    ]

    metrics, predictions = run_classification_baseline(
        rows,
        "accuracy",
        target_column="target",
        excluded_columns=["leakage_status"],
    )

    assert metrics["baseline_type"] == "xgboost_classifier"
    assert metrics["baseline_strength"] == "strong"
    assert metrics["model_family"] == "xgboost"
    assert metrics["model_baseline_attempted"] is True
    assert metrics["feature_count"] >= 1
    assert metrics["categorical_feature_count"] >= 1
    assert metrics["sanity_floor"]["baseline_type"] == "majority_classifier"
    assert len(predictions) == 2
