from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Base, ExperimentRun, Project
from tabular_harness.services.agent_session_results import experiment_pipeline_registration_status
from tabular_harness.services.agent_sessions import project_has_incomplete_prediction_runs


def test_non_model_work_records_do_not_require_prediction_runtimes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_non_model_run", name="Non-model work records")
        non_model_run = ExperimentRun(
            id="run_context_audit",
            project_id=project.id,
            runner_type="codex_cli",
            status="succeeded",
            params_json=dumps_json({"model_code_executed": False}),
            metrics_json=dumps_json({"primary_metric_name": "roc_auc", "primary_metric_value": None}),
        )
        db.add_all([project, non_model_run])
        db.flush()

        status = experiment_pipeline_registration_status(db, [non_model_run])

        assert status["status"] == "ready"
        assert status["model_run_count"] == 0
        assert status["non_model_record_count"] == 1
        assert status["missing_runs"] == []
        assert project_has_incomplete_prediction_runs(db, project=project) is False


def test_executed_baseline_still_requires_a_prediction_runtime() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as db:
        project = Project(id="p_baseline_run", name="Baseline model run")
        baseline_run = ExperimentRun(
            id="run_baseline_model",
            project_id=project.id,
            runner_type="local_training",
            status="succeeded",
            params_json=dumps_json({"model_candidate": "lightgbm_classifier"}),
            metrics_json=dumps_json(
                {
                    "model_baseline_attempted": True,
                    "primary_metric_name": "roc_auc",
                    "primary_metric_value": 0.75,
                }
            ),
        )
        db.add_all([project, baseline_run])
        db.flush()

        status = experiment_pipeline_registration_status(db, [baseline_run])

        assert status["status"] == "missing"
        assert status["model_run_count"] == 1
        assert status["non_model_record_count"] == 0
        assert status["missing_runs"][0]["run_id"] == baseline_run.id
        assert project_has_incomplete_prediction_runs(db, project=project) is True
