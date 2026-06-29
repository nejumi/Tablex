from __future__ import annotations

import numpy as np
from tabular_harness.services.model_diagnostics_artifacts import (
    build_native_feature_importance,
    build_prediction_review,
    threshold_review,
)


class DummyModel:
    feature_importances_ = np.array([np.float32(0.2), np.float32(0.7), np.float32(0.1)])


class DummyFeatureBuilder:
    numeric_columns = ["income", "external_score"]
    categorical_columns = ["contract_type"]
    text_vectorizers = {}


def test_native_feature_importance_keeps_numpy_float_values() -> None:
    importance = build_native_feature_importance(
        {
            "model": DummyModel(),
            "feature_builder": DummyFeatureBuilder(),
        }
    )

    assert importance["status"] == "ready"
    assert importance["top_features"][0]["feature_name"] == "external_score"
    assert importance["top_features"][0]["importance"] == np.float32(0.7).item()
    assert importance["family_importance"][0]["importance"] > 0


def test_classification_prediction_review_adds_calibration_and_thresholds() -> None:
    predictions = [
        {"target": "1", "prediction": "1", "score": 0.91},
        {"target": "1", "prediction": "0", "score": 0.31},
        {"target": "0", "prediction": "0", "score": 0.12},
        {"target": "0", "prediction": "1", "score": 0.76},
    ]

    review = build_prediction_review(
        predictions=predictions,
        metrics={"positive_label": "1"},
        task_kind="classification",
    )

    assert review["status"] == "ready"
    assert review["positive_label"] == "1"
    assert review["calibration_bins"]
    assert review["threshold_review"]
    assert any(row["threshold"] == 0.5 for row in review["threshold_review"])


def test_threshold_review_preserves_precision_recall_tradeoff() -> None:
    rows = [
        {"target": "1", "score": 0.9},
        {"target": "0", "score": 0.8},
        {"target": "1", "score": 0.7},
        {"target": "0", "score": 0.1},
    ]

    thresholds = threshold_review(rows, "1")
    low_threshold = next(row for row in thresholds if row["threshold"] == 0.1)
    high_threshold = next(row for row in thresholds if row["threshold"] == 0.5)

    assert low_threshold["recall"] >= high_threshold["recall"]
    assert high_threshold["predicted_positive_count"] < low_threshold["predicted_positive_count"]
