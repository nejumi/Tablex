from __future__ import annotations

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import ExperimentRun


def experiment_run_requires_prediction_runtime(run: ExperimentRun) -> bool:
    """Return whether a structured run record represents a fitted model."""
    params = loads_json(run.params_json, {})
    if params.get("model_code_executed") is False:
        return False
    if params.get("model_code_executed") is True:
        return True
    model_id = params.get("model_id")
    if isinstance(model_id, str) and model_id.strip():
        return True

    metrics = loads_json(run.metrics_json, {})
    if metrics.get("model_baseline_attempted") is True:
        return True
    model_candidate = params.get("model_candidate")
    return isinstance(model_candidate, str) and bool(model_candidate.strip())
