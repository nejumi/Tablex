from __future__ import annotations

from tabular_harness.services.metric_preferences import (
    metric_name,
    metric_value,
    normalize_metric_name,
)


def test_roc_auc_is_normalized_as_builtin_metric() -> None:
    assert normalize_metric_name("ROC-AUC") == "roc_auc"
    assert normalize_metric_name("ROC AUC") == "roc_auc"
    assert normalize_metric_name("ROCーAUC") == "roc_auc"
    assert normalize_metric_name("auc") == "roc_auc"


def test_requested_leaderboard_metric_does_not_fallback_per_row() -> None:
    metrics = {
        "primary_metric_name": "accuracy",
        "primary_metric_value": 0.91,
        "accuracy": 0.91,
    }

    assert metric_name(metrics, "roc_auc") == "roc_auc"
    assert metric_value(metrics, "roc_auc") is None
