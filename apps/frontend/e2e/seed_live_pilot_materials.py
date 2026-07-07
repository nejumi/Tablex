from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from tabular_harness.core.config import get_settings
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.models.entities import DatasetSnapshot, ExperimentRun, ModelVersion, Project
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    next_artifact_version,
    register_artifact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed deterministic pilot materials for a live Full Auto audit run.")
    parser.add_argument("--project-id", required=True)
    return parser.parse_args()


def pipeline_manifest(dataset_snapshot_id: str) -> dict[str, Any]:
    return {
        "schema_version": "pipeline_manifest.v1",
        "input_contract": {
            "inference_format": {
                "columns": [
                    {"name": "customer_id", "dtype": "string", "required": True},
                    {"name": "age", "dtype": "float", "required": True},
                    {"name": "balance", "dtype": "float", "required": True},
                    {"name": "contact_count", "dtype": "float", "required": True},
                    {"name": "previous_campaign_success", "dtype": "float", "required": True},
                    {"name": "channel", "dtype": "string", "required": False},
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
            "evaluation_spec_id": None,
            "split_manifest_id": None,
            "seed": 21,
            "deterministic": True,
        },
        "expected_metrics": [{"name": "roc_auc", "value": 0.74, "split": "validation"}],
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
        age = float(row.get("age") or 0.0)
        balance = float(row.get("balance") or 0.0)
        contacts = float(row.get("contact_count") or 0.0)
        previous = float(row.get("previous_campaign_success") or 0.0)
        score = 0.12 + min(balance, 8000.0) / 40000.0 + previous * 0.24 + contacts * 0.015 + max(age - 35.0, 0.0) * 0.002
        score = min(0.96, max(0.02, score))
        writer.writerow({"customer_id": row.get("customer_id", ""), "prediction": f"{score:.6f}"})
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pipeline_manifest.json", dumps_json(manifest))
        archive.writestr("train.py", "print('deterministic live audit training placeholder')\n")
        archive.writestr("predict.py", predict_py)
        archive.writestr("requirements.txt", "\n")
        archive.writestr("README.md", "# Live audit pilot pipeline\n")


def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_engine_for_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    store = LocalArtifactStore(settings.artifact_root)

    with session_factory() as db:
        project = db.get(Project, args.project_id)
        if project is None:
            raise SystemExit(f"Project not found: {args.project_id}")
        dataset = None
        if project.primary_dataset_snapshot_id:
            dataset = db.get(DatasetSnapshot, project.primary_dataset_snapshot_id)
        if dataset is None:
            dataset = db.scalar(
                select(DatasetSnapshot)
                .where(DatasetSnapshot.project_id == project.id)
                .order_by(DatasetSnapshot.created_at.asc())
            )
        if dataset is None:
            raise SystemExit("No dataset snapshot is available for the project.")

        run = ExperimentRun(
            id=new_id("run"),
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            runner_type="live_audit_seed",
            status="succeeded",
            params_json=dumps_json(
                {
                    "model_id": "live_audit_pilot_pipeline",
                    "model_description": "Deterministic pilot pipeline used only to verify live pilot observation delivery.",
                    "features_used": ["age", "balance", "contact_count", "previous_campaign_success"],
                }
            ),
            metrics_json=dumps_json({"primary_metric_name": "roc_auc", "primary_metric_value": 0.74, "roc_auc": 0.74}),
            summary_md="Deterministic pilot pipeline for the 0121 live audit smoke.",
            created_by="e2e_live_audit",
        )
        db.add(run)
        db.flush()

        model_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="model_package",
            name="live_audit_pilot_model_package",
            filename="model_package.json",
            payload={"schema_version": "model_package.v1", "model": "live_audit_pilot_pipeline"},
            metadata={"project_id": project.id, "run_id": run.id, "source": "e2e_live_audit"},
        )
        model_version = ModelVersion(
            id=new_id("mv"),
            project_id=project.id,
            experiment_run_id=run.id,
            dataset_snapshot_id=dataset.id,
            artifact_id=model_artifact.id,
            name="live_audit_pilot_pipeline",
            version=1,
            model_family="deterministic",
            model_type="score_formula",
            task_type=project.task_type or "binary_classification",
            target_column=project.target_column or "converted",
            primary_metric_name="roc_auc",
            primary_metric_value=0.74,
            metrics_json=run.metrics_json,
            params_json=run.params_json,
            status="succeeded",
            created_by="e2e_live_audit",
        )
        db.add(model_version)
        run.model_version_id = model_version.id

        with tempfile.TemporaryDirectory(prefix="tablex-live-audit-pipeline-") as temp_dir_text:
            zip_path = Path(temp_dir_text) / "live_audit_pipeline.zip"
            write_pipeline_zip(zip_path, pipeline_manifest(dataset.id))
            version = next_artifact_version(db, project.id, "prediction_pipeline", "live_audit_pilot_pipeline")
            artifact_dir, stored, content_hash = store.store_existing_file(
                org_id=project.org_id,
                project_id=project.id,
                asset_type="prediction_pipeline",
                name="live_audit_pilot_pipeline",
                version=version,
                source_path=zip_path,
                filename="live_audit_pipeline.zip",
                metadata={"project_id": project.id, "run_id": run.id, "primary_path": str(zip_path)},
            )
            pipeline_artifact = register_artifact(
                db,
                project_id=project.id,
                asset_type="prediction_pipeline",
                name="live_audit_pilot_pipeline",
                uri=str(artifact_dir),
                content_hash=content_hash,
                size_bytes=stored.size_bytes,
                metadata={
                    "project_id": project.id,
                    "run_id": run.id,
                    "experiment_run_ids": [run.id],
                    "primary_path": str(artifact_dir / "live_audit_pipeline.zip"),
                    "smoke_validation": {"status": "passed", "runtime_isolated": True},
                },
                version=version,
                org_id=project.org_id,
            )

        input_text = (
            "customer_id,age,balance,contact_count,previous_campaign_success,channel\n"
            "F001,42,5200,2,1,email\n"
            "F002,31,400,1,0,phone\n"
            "F003,55,7600,3,1,email\n"
            "F004,28,900,4,0,phone\n"
        )
        input_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="dataset_snapshot",
            name="live_audit_pilot_input",
            filename="future_customers.csv",
            text=input_text,
            metadata={"project_id": project.id, "source": "e2e_live_audit"},
        )
        future_dataset = DatasetSnapshot(
            id=new_id("ds"),
            project_id=project.id,
            artifact_id=input_artifact.id,
            source_type="e2e_live_audit_pilot_input",
            source_ref="future_customers.csv",
            row_count=4,
            column_count=6,
            schema_hash="live_audit_future_customers_v1",
        )
        db.add(future_dataset)

        outcome_artifact = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="pilot_outcomes",
            name="live_audit_pilot_outcomes",
            filename="future_outcomes.csv",
            text=(
                "customer_id,converted,observed_at\n"
                "F001,1,2026-07-10T00:00:00Z\n"
                "F002,0,2026-07-10T00:00:00Z\n"
                "F003,1,2026-07-10T00:00:00Z\n"
                "F004,0,2026-07-10T00:00:00Z\n"
            ),
            metadata={"project_id": project.id, "source": "e2e_live_audit"},
        )
        db.commit()

        print(
            json.dumps(
                {
                    "schema_version": "tablex_live_pilot_seed.v1",
                    "project_id": project.id,
                    "dataset_snapshot_id": dataset.id,
                    "experiment_run_id": run.id,
                    "model_version_id": model_version.id,
                    "pipeline_artifact_id": pipeline_artifact.id,
                    "future_dataset_snapshot_id": future_dataset.id,
                    "outcomes_artifact_id": outcome_artifact.id,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
