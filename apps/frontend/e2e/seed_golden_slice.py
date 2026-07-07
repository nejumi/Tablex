from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from tabular_harness.core.config import get_settings
from tabular_harness.core.json import dumps_json
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.models.entities import (
    DatasetSnapshot,
    ExperimentRun,
    ModelVersion,
    PilotDeployment,
    PilotOutcomeBatch,
    PilotPredictionBatch,
    Project,
    utc_now,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a deterministic Tablex browser smoke project.")
    parser.add_argument("--project-id", help="Existing project id to enrich. Creates one when omitted.")
    return parser.parse_args()


def notebook_source() -> str:
    return '''import marimo

__generated_with = "0.14.17"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import plotly.express as px
    return mo, pd, px


@app.cell
def _(mo):
    mo.md(
        """
        # Golden slice model diagnostics

        This native marimo notebook is a deterministic browser smoke fixture. It verifies that Tablex opens the
        model diagnostics notebook linked from Chat and Leaderboard without falling back to static HTML.
        """
    )
    return


@app.cell
def _(pd):
    leaderboard_frame = pd.DataFrame(
        [
            {"model": "Golden slice logistic", "roc_auc": 0.812, "log_loss": 0.412},
            {"model": "Constant baseline", "roc_auc": 0.500, "log_loss": 0.691},
        ]
    )
    return (leaderboard_frame,)


@app.cell
def _(leaderboard_frame, px):
    score_figure = px.bar(
        leaderboard_frame,
        x="roc_auc",
        y="model",
        orientation="h",
        title="Validation ROC AUC by candidate",
        range_x=[0.45, 0.85],
    )
    score_figure
    return (score_figure,)


@app.cell
def _(pd):
    importance_frame = pd.DataFrame(
        [
            {"feature": "debt_to_income", "importance": 0.31},
            {"feature": "recent_delinquency_count", "importance": 0.24},
            {"feature": "credit_history_months", "importance": 0.18},
            {"feature": "income_log", "importance": 0.12},
        ]
    )
    return (importance_frame,)


@app.cell
def _(importance_frame, px):
    importance_figure = px.bar(
        importance_frame,
        x="importance",
        y="feature",
        orientation="h",
        title="Permutation importance smoke fixture",
    )
    importance_figure
    return (importance_figure,)


@app.cell
def _(mo, importance_frame, leaderboard_frame):
    mo.vstack(
        [
            mo.md("## Tables available to human reviewers"),
            mo.ui.table(leaderboard_frame),
            mo.ui.table(importance_frame),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
'''


def pipeline_manifest(dataset_snapshot_id: str) -> dict[str, Any]:
    return {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {
                "columns": [
                    {"name": "customer_id", "dtype": "string", "required": True},
                    {"name": "debt_to_income", "dtype": "float", "required": True},
                    {"name": "recent_delinquency_count", "dtype": "float", "required": True},
                ]
            }
        },
        "output_contract": {
            "columns": [
                {"name": "customer_id", "dtype": "string"},
                {"name": "prediction", "dtype": "float"},
            ],
            "id_columns": ["customer_id"],
            "prediction_column": "prediction",
        },
        "training": {
            "dataset_snapshot_id": dataset_snapshot_id,
            "split_manifest_id": None,
            "evaluation_spec_id": None,
            "seed": 11,
            "deterministic": True,
        },
        "expected_metrics": [{"name": "roc_auc", "value": 0.812, "split": "validation"}],
        "runtime": {"python": ">=3.11", "timeout_seconds_predict": 120},
    }


def write_pipeline_zip(path: Path, manifest: dict[str, Any]) -> None:
    predict_py = """import argparse
import csv

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

with open(args.input, encoding="utf-8", newline="") as src:
    rows = list(csv.DictReader(src))

with open(args.output, "w", encoding="utf-8", newline="") as dst:
    writer = csv.DictWriter(dst, fieldnames=["customer_id", "prediction"])
    writer.writeheader()
    for row in rows:
        debt = float(row.get("debt_to_income") or 0.0)
        delinquency = float(row.get("recent_delinquency_count") or 0.0)
        score = min(0.99, max(0.01, 0.08 + debt * 0.35 + delinquency * 0.08))
        writer.writerow({"customer_id": row.get("customer_id", ""), "prediction": f"{score:.6f}"})
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pipeline_manifest.json", dumps_json(manifest))
        archive.writestr("train.py", "print('deterministic browser smoke training placeholder')\n")
        archive.writestr("predict.py", predict_py)
        archive.writestr("requirements.txt", "\n")
        archive.writestr("README.md", "# Golden slice prediction pipeline\n")


def ensure_project(db, project_id: str | None) -> Project:
    if project_id:
        project = db.get(Project, project_id)
        if project is None:
            raise SystemExit(f"Project not found: {project_id}")
        project.name = "E2E Golden Slice"
        project.description = "Browser smoke project for Tablex artifact navigation."
        project.task_type = "binary_classification"
        project.target_column = "TARGET"
        project.current_phase = "IDLE"
        project.autonomy_mode = "full_auto"
        return project
    project = Project(
        id="p_e2e_golden_slice",
        name="E2E Golden Slice",
        description="Browser smoke project for Tablex artifact navigation.",
        task_type="binary_classification",
        target_column="TARGET",
        current_phase="IDLE",
        autonomy_mode="full_auto",
    )
    db.merge(project)
    return project


def ensure_dataset(db, store: LocalArtifactStore, project: Project) -> DatasetSnapshot:
    existing = db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project.id)
        .order_by(DatasetSnapshot.created_at.asc())
        .limit(1)
    )
    if existing is not None:
        project.primary_dataset_snapshot_id = existing.id
        project.target_column = "TARGET"
        return existing
    artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="dataset_snapshot",
        name="golden_credit_sample",
        filename="application_train.csv",
        text="customer_id,debt_to_income,recent_delinquency_count,TARGET\nC001,0.22,0,0\nC002,0.61,2,1\nC003,0.35,0,0\n",
        metadata={"project_id": project.id, "source_ref": "application_train.csv"},
    )
    dataset = DatasetSnapshot(
        id="ds_e2e_golden_slice",
        project_id=project.id,
        artifact_id=artifact.id,
        source_type="upload",
        source_ref="application_train.csv",
        row_count=3,
        column_count=4,
        schema_hash="e2e_golden_slice_schema",
        data_hash=artifact.content_hash,
    )
    db.add(dataset)
    project.primary_dataset_snapshot_id = dataset.id
    return dataset


def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_engine_for_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    store = LocalArtifactStore(settings.artifact_root)
    now = utc_now()

    with session_factory() as db:
        project = ensure_project(db, args.project_id)
        db.add(project)
        db.flush()
        dataset = ensure_dataset(db, store, project)
        db.flush()

        run_id = "run_e2e_golden_slice"
        manifest = pipeline_manifest(dataset.id)
        with tempfile.TemporaryDirectory(prefix="tablex-e2e-pipeline-") as temp_dir_text:
            zip_path = Path(temp_dir_text) / "golden_slice_pipeline.zip"
            write_pipeline_zip(zip_path, manifest)
            version = next_artifact_version(db, project.id, "prediction_pipeline", "golden_slice_pipeline")
            artifact_dir, stored, content_hash = store.store_existing_file(
                org_id=project.org_id,
                project_id=project.id,
                asset_type="prediction_pipeline",
                name="golden_slice_pipeline",
                version=version,
                source_path=zip_path,
                filename="golden_slice_pipeline.zip",
                metadata={"project_id": project.id, "run_id": run_id, "primary_path": str(zip_path)},
            )
            pipeline_artifact = register_artifact(
                db,
                project_id=project.id,
                asset_type="prediction_pipeline",
                name="golden_slice_pipeline",
                uri=str(artifact_dir),
                content_hash=content_hash,
                size_bytes=stored.size_bytes,
                metadata={
                    "project_id": project.id,
                    "run_id": run_id,
                    "experiment_run_ids": [run_id],
                    "primary_path": str(artifact_dir / "golden_slice_pipeline.zip"),
                    "metric_reproduction": {"metric_reproduced": True},
                    "smoke_validation": {"status": "passed", "runtime_isolated": True},
                },
                version=version,
                org_id=project.org_id,
            )

        run = db.get(ExperimentRun, run_id)
        if run is None:
            run = ExperimentRun(
                id=run_id,
                project_id=project.id,
                dataset_snapshot_id=dataset.id,
                runner_type="codex_main_session",
                status="succeeded",
                started_at=now,
                ended_at=now,
                created_by="e2e",
            )
            db.add(run)
        run.params_json = dumps_json(
            {
                "model_id": "golden_slice_logistic",
                "model_label": "Golden slice logistic model",
                "model_description": (
                    "Deterministic credit-risk model with a reproducible prediction pipeline, "
                    "diagnostics notebook, and pilot scoring record."
                ),
                "features_used": ["debt_to_income", "recent_delinquency_count"],
                "feature_summary": "two numeric credit-risk features",
                "pipeline_artifact_id": pipeline_artifact.id,
            }
        )
        run.metrics_json = dumps_json(
            {"primary_metric_name": "roc_auc", "primary_metric_value": 0.812, "roc_auc": 0.812, "log_loss": 0.412}
        )
        run.summary_md = "Golden slice run used to verify browser navigation from leaderboard to notebook and pipeline bundle."
        db.flush()

        model_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="model_package",
            name="golden_slice_model_package",
            filename="model_package.json",
            payload={"schema_version": "model_package.v1", "model": "golden_slice_logistic"},
            metadata={"project_id": project.id, "run_id": run.id},
        )
        model_version = db.get(ModelVersion, "mv_e2e_golden_slice")
        if model_version is None:
            model_version = ModelVersion(
                id="mv_e2e_golden_slice",
                project_id=project.id,
                experiment_run_id=run.id,
                dataset_snapshot_id=dataset.id,
                artifact_id=model_artifact.id,
                name="golden_slice_logistic",
                version=1,
                model_family="linear",
                model_type="logistic_regression",
                task_type="binary_classification",
                target_column="TARGET",
                primary_metric_name="roc_auc",
                primary_metric_value=0.812,
                metrics_json=run.metrics_json,
                params_json=run.params_json,
                status="succeeded",
                created_by="e2e",
            )
            db.add(model_version)
        run.model_version_id = model_version.id

        quality_manifest = {
            "schema_version": "tablex_notebook_quality_manifest.v1",
            "notebook_purpose": "Golden slice model diagnostics notebook",
            "visual_summary": "ROC AUC comparison and permutation importance smoke figures.",
            "figure_count": 2,
            "table_count": 2,
            "key_findings": [
                "Leaderboard and notebook links resolve to the model diagnostics notebook.",
                "Native marimo opens from source without static HTML fallback.",
            ],
            "read_order": [
                {"label": "Model comparison", "anchor": "score_figure", "detail": "Check the validation score chart."},
                {"label": "Permutation importance", "anchor": "importance_figure", "detail": "Check the diagnostic chart."},
            ],
            "data_sources_used": ["application_train.csv"],
            "limitations": ["This is a deterministic browser smoke fixture, not a scientific benchmark."],
            "model_diagnostics": {
                "schema_version": "tablex_model_diagnostics_manifest.v1",
                "checks": [
                    {"name": "permutation_importance", "status": "included", "evidence": "importance_figure"},
                    {"name": "native_feature_importance", "status": "not_applicable", "reason": "linear smoke model"},
                    {"name": "partial_dependence", "status": "deferred", "reason": "fixture keeps native marimo startup light"},
                    {"name": "shap", "status": "deferred", "reason": "fixture keeps native marimo startup light"},
                ],
            },
        }
        notebook_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="analysis_notebook",
            name="golden_slice_model_diagnostics_notebook",
            filename="golden_slice_model_diagnostics.py",
            text=notebook_source(),
            metadata={
                "project_id": project.id,
                "title": "Golden slice model diagnostics notebook",
                "notebook_kind": "model_diagnostics",
                "dataset_snapshot_id": dataset.id,
                "run_id": run.id,
                "related_run_ids": [run.id],
                "model_version_id": model_version.id,
                "notebook_quality_manifest": quality_manifest,
                "figure_count": quality_manifest["figure_count"],
                "table_count": quality_manifest["table_count"],
                "key_finding_count": len(quality_manifest["key_findings"]),
                "execution_status": "source_registered",
            },
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="documents_model_diagnostics",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="experiment_run",
            from_asset_id=run.id,
            to_asset_type="artifact",
            to_asset_id=pipeline_artifact.id,
            relation_type="materializes_prediction_pipeline",
        )

        store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="model_diagnostics_artifact_pack",
            name="golden_slice_model_diagnostics_pack",
            filename="diagnostics_pack.json",
            payload={
                "schema_version": "model_diagnostics_artifact_pack.v1",
                "availability": {
                    "permutation_importance": "ready",
                    "native_feature_importance": "not_applicable",
                    "partial_dependence": "deferred",
                    "shap": "deferred",
                },
            },
            metadata={"project_id": project.id, "run_id": run.id},
        )
        store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="permutation_importance",
            name="golden_slice_permutation_importance",
            filename="permutation_importance.json",
            payload={"features": [{"feature": "debt_to_income", "importance": 0.31}]},
            metadata={"project_id": project.id, "run_id": run.id},
        )

        deployment = db.get(PilotDeployment, "pdep_e2e_golden_slice")
        if deployment is None:
            deployment = PilotDeployment(
                id="pdep_e2e_golden_slice",
                project_id=project.id,
                pipeline_artifact_id=pipeline_artifact.id,
                model_version_id=model_version.id,
                experiment_run_id=run.id,
                status="active",
                notes="Browser smoke deployment.",
            )
            db.add(deployment)
            db.flush()

        predictions_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="prediction_batch",
            name="golden_slice_seed_predictions",
            filename="predictions.csv",
            text="customer_id,prediction\nC001,0.157000\nC002,0.453500\nC003,0.202500\n",
            metadata={"project_id": project.id, "pipeline_artifact_id": pipeline_artifact.id, "deployment_id": deployment.id},
        )
        prediction_batch = db.get(PilotPredictionBatch, "ppb_e2e_golden_slice")
        if prediction_batch is None:
            prediction_batch = PilotPredictionBatch(
                id="ppb_e2e_golden_slice",
                deployment_id=deployment.id,
                as_of=now,
                input_artifact_id=dataset.artifact_id,
                predictions_artifact_id=predictions_artifact.id,
                row_count=3,
            )
            db.add(prediction_batch)

        outcomes_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_outcomes",
            name="golden_slice_outcomes",
            filename="outcomes.csv",
            text="customer_id,TARGET\nC001,0\nC002,1\nC003,0\n",
            metadata={"project_id": project.id, "deployment_id": deployment.id},
        )
        outcome_batch = db.get(PilotOutcomeBatch, "pout_e2e_golden_slice")
        if outcome_batch is None:
            outcome_batch = PilotOutcomeBatch(
                id="pout_e2e_golden_slice",
                deployment_id=deployment.id,
                outcomes_artifact_id=outcomes_artifact.id,
                join_keys_json=dumps_json(["customer_id"]),
                matched_rows=3,
            )
            db.add(outcome_batch)

        scoring_report = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_scoring_report",
            name="golden_slice_pilot_scoring_report",
            filename="pilot_scoring_report.json",
            payload={
                "schema_version": "pilot_scoring_report.v1",
                "deployment_id": deployment.id,
                "prediction_batch_id": "ppb_e2e_golden_slice",
                "outcome_batch_id": "pout_e2e_golden_slice",
                "metrics": {"roc_auc": 0.78, "brier": 0.12},
                "matched_rows": 3,
                "metric_count": 2,
                "as_of_violations": {"count": 0, "examples": []},
            },
            metadata={
                "project_id": project.id,
                "deployment_id": deployment.id,
                "prediction_batch_id": "ppb_e2e_golden_slice",
                "outcome_batch_id": "pout_e2e_golden_slice",
            },
        )
        store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="validation_scheme_audit",
            name="golden_slice_validation_audit",
            filename="validation_audit.json",
            payload={
                "schema_version": "validation_scheme_audit.v1",
                "deployment_id": deployment.id,
                "scheme_verdict": "acceptable_for_smoke",
                "next_iteration_focus": "Use real outcome data in live runs.",
                "gap_decomposition": [{"source": "fixture_scope", "impact": "low"}],
                "scoring_report_artifact_ids": [scoring_report.id],
            },
            metadata={"project_id": project.id, "deployment_id": deployment.id, "scheme_verdict": "acceptable_for_smoke"},
        )

        chat_payload = {
            "schema_version": "agent_chat_turn.v1",
            "project_id": project.id,
            "user_message": "",
            "assistant_message": (
                "The model diagnostics notebook is ready. Open it to inspect the browser smoke figures, "
                "then review the leaderboard row and pipeline bundle."
            ),
            "intent": {"type": "artifact_ready", "status": "ready"},
            "actions": [
                {
                    "type": "open_surface",
                    "status": "ready",
                    "label": "Open model diagnostics notebook",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "artifact_id": notebook_artifact.id,
                    "artifact_ids": [notebook_artifact.id],
                    "detail": "Open the native marimo notebook linked to the model run.",
                },
                {
                    "type": "open_surface",
                    "status": "ready",
                    "label": "Open leaderboard",
                    "target_tab": "Leaderboard",
                    "target_anchor": "result-readout",
                    "detail": "Review model description, pipeline bundle, and pilot scoring.",
                },
            ],
            "action_summary": {"schema_version": "agent_action_summary.v1", "outcome": "succeeded"},
            "response_brief": {},
            "response_composer": {"schema_version": "agent_response_composer.v1", "mode": "e2e_fixture", "status": "succeeded"},
            "worker_events": [],
            "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
            "next_focus": {"target_tab": "Notebooks", "target_anchor": "notebook-native-marimo-top", "label": "Open model diagnostics notebook"},
        }
        chat_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_chat_turn",
            name="golden_slice_chat_notebook_link",
            filename="agent_chat_turn.json",
            payload=chat_payload,
            metadata={"project_id": project.id, "source": "e2e_fixture", "intent_type": "artifact_ready", "action_count": 2},
        )
        db.commit()
        print(
            json.dumps(
                {
                    "project_id": project.id,
                    "dataset_snapshot_id": dataset.id,
                    "run_id": run.id,
                    "model_version_id": model_version.id,
                    "notebook_artifact_id": notebook_artifact.id,
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "deployment_id": deployment.id,
                    "chat_artifact_id": chat_artifact.id,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
