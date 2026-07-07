from __future__ import annotations

import numpy as np
from tabular_harness.services.model_diagnostics_artifacts import (
    build_native_feature_importance,
    build_partial_dependence,
    build_prediction_review,
    build_shap_summary,
    threshold_review,
)
from tabular_harness.services.baseline import SPLIT_VALUE_COLUMN, TARGET_VALUE_COLUMN


class DummyModel:
    feature_importances_ = np.array([np.float32(0.2), np.float32(0.7), np.float32(0.1)])


class DummyFeatureBuilder:
    numeric_columns = ["income", "external_score"]
    categorical_columns = ["contract_type"]
    text_vectorizers = {}

    def transform(self, rows):
        return np.asarray([[float(row["income"]), float(row["external_score"])] for row in rows])


class DummyRegressionModel:
    feature_importances_ = np.array([0.8, 0.2])

    def predict(self, matrix):
        return np.asarray(matrix)[:, 0] * 2.0 + np.asarray(matrix)[:, 1]


class DummyRegressionModelWithoutNativeImportance:
    def predict(self, matrix):
        return np.asarray(matrix)[:, 0] + np.asarray(matrix)[:, 1] * 3.0


class DummyCatBoostLikeRegressionModel:
    def get_feature_importance(self):
        return np.asarray([0.1, 0.9])

    def predict(self, matrix):
        return np.asarray(matrix)[:, 0] + np.asarray(matrix)[:, 1] * 3.0


class DummyBooster:
    def get_score(self, importance_type="gain"):
        return {"f0": 0.2, "f1": 0.8}


class DummyBoosterLikeRegressionModel:
    def get_booster(self):
        return DummyBooster()

    def predict(self, matrix):
        return np.asarray(matrix)[:, 0] + np.asarray(matrix)[:, 1] * 3.0


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


def test_native_feature_importance_uses_get_feature_importance_when_available() -> None:
    importance = build_native_feature_importance(
        {
            "model": DummyCatBoostLikeRegressionModel(),
            "feature_builder": DummyFeatureBuilder(),
        }
    )

    assert importance["status"] == "ready"
    assert importance["method"] == "model_get_feature_importance"
    assert importance["top_features"][0]["feature_name"] == "external_score"


def test_native_feature_importance_uses_booster_score_when_available() -> None:
    importance = build_native_feature_importance(
        {
            "model": DummyBoosterLikeRegressionModel(),
            "feature_builder": DummyFeatureBuilder(),
        }
    )

    assert importance["status"] == "ready"
    assert importance["method"] == "booster_get_score"
    assert importance["top_features"][0]["feature_name"] == "external_score"


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


def test_partial_dependence_builds_bounded_curves_for_model_package() -> None:
    rows = [
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 1.0, "income": 1.0, "external_score": 0.1},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 2.0, "income": 2.0, "external_score": 0.2},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 3.0, "income": 3.0, "external_score": 0.3},
        {SPLIT_VALUE_COLUMN: "train", TARGET_VALUE_COLUMN: 4.0, "income": 4.0, "external_score": 0.4},
    ]

    partial_dependence = build_partial_dependence(
        model_package={
            "model": DummyRegressionModel(),
            "feature_builder": DummyFeatureBuilder(),
            "baseline_plan": {},
        },
        split_rows=rows,
        metrics={"primary_metric_name": "rmse"},
        task_kind="regression",
    )

    assert partial_dependence["status"] == "ready"
    assert partial_dependence["curves"][0]["feature_name"] == "income"
    assert partial_dependence["curves"][0]["points"]
    assert partial_dependence["curves"][0]["points"][0]["average_response"] is not None


def test_partial_dependence_uses_permutation_ranking_when_native_importance_is_unavailable() -> None:
    rows = [
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 1.0, "income": 1.0, "external_score": 0.1},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 2.0, "income": 2.0, "external_score": 0.2},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 3.0, "income": 3.0, "external_score": 0.3},
    ]

    partial_dependence = build_partial_dependence(
        model_package={
            "model": DummyRegressionModelWithoutNativeImportance(),
            "feature_builder": DummyFeatureBuilder(),
            "baseline_plan": {},
        },
        split_rows=rows,
        metrics={"primary_metric_name": "rmse"},
        task_kind="regression",
        permutation_importance={
            "status": "ready",
            "top_features": [
                {"feature_index": 1, "feature_name": "external_score", "importance_delta": 0.9},
                {"feature_index": 0, "feature_name": "income", "importance_delta": 0.2},
            ],
        },
    )

    assert partial_dependence["status"] == "ready"
    assert partial_dependence["curves"][0]["feature_name"] == "external_score"


def test_partial_dependence_uses_supported_native_importance_api_before_permutation() -> None:
    rows = [
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 1.0, "income": 1.0, "external_score": 0.1},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 2.0, "income": 2.0, "external_score": 0.2},
        {SPLIT_VALUE_COLUMN: "valid", TARGET_VALUE_COLUMN: 3.0, "income": 3.0, "external_score": 0.3},
    ]

    partial_dependence = build_partial_dependence(
        model_package={
            "model": DummyCatBoostLikeRegressionModel(),
            "feature_builder": DummyFeatureBuilder(),
            "baseline_plan": {},
        },
        split_rows=rows,
        metrics={"primary_metric_name": "rmse"},
        task_kind="regression",
        permutation_importance={
            "status": "ready",
            "top_features": [
                {"feature_index": 0, "feature_name": "income", "importance_delta": 0.9},
                {"feature_index": 1, "feature_name": "external_score", "importance_delta": 0.2},
            ],
        },
    )

    assert partial_dependence["status"] == "ready"
    assert partial_dependence["curves"][0]["feature_name"] == "external_score"


def test_shap_summary_reports_missing_model_package_as_fixed_status() -> None:
    summary = build_shap_summary(model_package=None, split_rows=[], metrics={}, task_kind="regression")

    assert summary["status"] == "blocked"
    assert summary["reason"] == "missing_model_package"
