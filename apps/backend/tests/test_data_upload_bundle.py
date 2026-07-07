from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from tabular_harness.api.routes import project_data_columns, stage_upload_bundle_files
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.db.session import init_db
from tabular_harness.models.entities import Artifact, DatasetSnapshot, Project, SemanticCatalog
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import create_job, mark_job_running
from tabular_harness.worker.jobs import select_primary_table_handler, upload_data_bundle_handler


def test_upload_data_bundle_worker_ingests_staged_files_and_primary_can_change(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_upload",
            name="upload",
            target_column="outcome",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        job = create_job(db, job_type="upload_data_bundle", project_id=project.id, input_payload={})
        uploads = [
            SimpleNamespace(
                filename="customers.csv",
                content_type="text/csv",
                file=BytesIO(b"customer_id,outcome,score\n1,0,10\n2,1,20\n"),
            ),
            SimpleNamespace(
                filename="payments.csv",
                content_type="text/csv",
                file=BytesIO(b"customer_id,payment_id\n1,100\n2,200\n"),
            ),
        ]
        staged = stage_upload_bundle_files(db, store=store, project=project, job=job, uploads=uploads, stage_kind="table")
        staged_metadata = loads_json(staged[0].metadata_json, {})
        assert staged_metadata["column_names"] == ["customer_id", "outcome", "score"]
        assert staged_metadata["column_count"] == 3
        job.input_json = dumps_json(
            {
                "staged_table_artifact_ids": [artifact.id for artifact in staged],
                "staged_relational_hint_artifact_ids": [],
                "primary_filename": "customers.csv",
                "target_column": "outcome",
                "response_locale": "ja-JP",
            }
        )
        staged_column_catalog = project_data_columns(project.id, db)
        staged_by_source = {table["source_ref"]: table for table in staged_column_catalog["tables"]}
        assert staged_by_source["customers.csv"]["dataset_snapshot_id"].startswith("staged:")
        assert staged_by_source["customers.csv"]["is_primary"] is True
        assert staged_by_source["customers.csv"]["columns"] == ["customer_id", "outcome", "score"]
        mark_job_running(job)

        output = upload_data_bundle_handler(db, job, store)
        db.flush()
        progress_output = loads_json(job.output_json, {})

        assert output["schema_version"] == "upload_data_bundle.v1"
        assert progress_output["schema_version"] == "upload_data_bundle_progress.v1"
        assert progress_output["progress_stage"] == "finalizing"
        assert progress_output["progress_percent"] == 94
        assert output["dataset_snapshot_id"] == project.primary_dataset_snapshot_id
        assert project.current_phase == "AUTONOMOUS_LOOP"
        assert len(output["supporting_table_artifact_ids"]) == 1
        supporting_artifact = db.get(Artifact, output["supporting_table_artifact_ids"][0])
        assert supporting_artifact is not None
        supporting_metadata = loads_json(supporting_artifact.metadata_json, {})
        assert supporting_metadata["column_names"] == ["customer_id", "payment_id"]
        primary = db.get(DatasetSnapshot, project.primary_dataset_snapshot_id)
        assert primary is not None
        assert primary.source_ref == "customers.csv"

        initial_column_catalog = project_data_columns(project.id, db)
        initial_by_source = {table["source_ref"]: table for table in initial_column_catalog["tables"]}
        assert initial_by_source["customers.csv"]["columns"] == ["customer_id", "outcome", "score"]
        assert initial_by_source["customers.csv"]["column_details"][0]["name"] == "customer_id"
        assert "physical_type" in initial_by_source["customers.csv"]["column_details"][0]
        for column_detail in initial_by_source["customers.csv"]["column_details"]:
            assert "role" not in column_detail
            assert "is_leakage_suspect" not in column_detail
            assert "available_at_prediction_time" not in column_detail
        assert initial_by_source["payments.csv"]["columns"] == ["customer_id", "payment_id"]
        assert [item["name"] for item in initial_by_source["payments.csv"]["column_details"]] == [
            "customer_id",
            "payment_id",
        ]
        assert initial_by_source["payments.csv"]["dataset_snapshot_id"].startswith("ds_")

        select_job = create_job(
            db,
            job_type="select_primary_table",
            project_id=project.id,
            input_payload={
                "artifact_id": output["supporting_table_artifact_ids"][0],
                "target_column": "outcome",
                "locale": "ja-JP",
            },
        )
        mark_job_running(select_job)
        select_output = select_primary_table_handler(db, select_job, store)
        db.flush()
        changed = db.get(DatasetSnapshot, select_output["dataset_snapshot_id"])

        datasets = db.scalars(select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id)).all()
        assert len(datasets) == 2
        assert changed is not None
        assert changed.source_ref == "payments.csv"
        assert project.primary_dataset_snapshot_id == changed.id
        assert project.current_phase == "AUTONOMOUS_LOOP"
        assert select_output["schema_version"] == "select_primary_table.v1"

        column_catalog = project_data_columns(project.id, db)
        table_by_source = {table["source_ref"]: table for table in column_catalog["tables"]}
        assert table_by_source["payments.csv"]["is_primary"] is True
        assert table_by_source["customers.csv"]["is_primary"] is False
        assert table_by_source["customers.csv"]["columns"] == ["customer_id", "outcome", "score"]
        assert table_by_source["customers.csv"]["column_details"][1]["name"] == "outcome"
        assert table_by_source["payments.csv"]["columns"] == ["customer_id", "payment_id"]
        assert table_by_source["payments.csv"]["column_details"][0]["name"] == "customer_id"

        for catalog in db.scalars(select(SemanticCatalog).where(SemanticCatalog.project_id == project.id)).all():
            db.delete(catalog)
        db.flush()

        fallback_column_catalog = project_data_columns(project.id, db)
        fallback_by_source = {table["source_ref"]: table for table in fallback_column_catalog["tables"]}
        assert fallback_by_source["customers.csv"]["columns"] == ["customer_id", "outcome", "score"]
        assert fallback_by_source["customers.csv"]["column_details"] == [
            {"name": "customer_id"},
            {"name": "outcome"},
            {"name": "score"},
        ]
        assert fallback_by_source["payments.csv"]["columns"] == ["customer_id", "payment_id"]


def test_upload_data_bundle_worker_allows_primary_to_remain_open(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_upload_open",
            name="upload-open",
            target_column=None,
            current_phase="IDLE",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        job = create_job(db, job_type="upload_data_bundle", project_id=project.id, input_payload={})
        uploads = [
            SimpleNamespace(
                filename="events.csv",
                content_type="text/csv",
                file=BytesIO(b"store_id,date,demand\n1,2026-01-01,10\n2,2026-01-01,14\n"),
            ),
            SimpleNamespace(
                filename="stores.csv",
                content_type="text/csv",
                file=BytesIO(b"store_id,region\n1,east\n2,west\n"),
            ),
        ]
        staged = stage_upload_bundle_files(db, store=store, project=project, job=job, uploads=uploads, stage_kind="table")
        job.input_json = dumps_json(
            {
                "staged_table_artifact_ids": [artifact.id for artifact in staged],
                "staged_relational_hint_artifact_ids": [],
                "primary_filename": None,
                "target_column": None,
                "response_locale": "ja-JP",
            }
        )
        mark_job_running(job)

        output = upload_data_bundle_handler(db, job, store)
        db.flush()

        assert output["schema_version"] == "upload_data_bundle.v1"
        assert output["dataset_snapshot_id"] is None
        assert output["primary_dataset_snapshot_id"] is None
        assert len(output["dataset_snapshot_ids"]) == 2
        assert project.primary_dataset_snapshot_id is None
        assert project.target_column is None
        assert project.current_phase == "UNDERSTANDING_REVIEW"

        datasets = db.scalars(select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id)).all()
        assert len(datasets) == 2
        assert {dataset.source_ref for dataset in datasets} == {"events.csv", "stores.csv"}

        column_catalog = project_data_columns(project.id, db)
        table_by_source = {table["source_ref"]: table for table in column_catalog["tables"]}
        assert table_by_source["events.csv"]["is_primary"] is False
        assert table_by_source["stores.csv"]["is_primary"] is False
        assert table_by_source["events.csv"]["dataset_snapshot_id"].startswith("ds_")
        assert table_by_source["stores.csv"]["dataset_snapshot_id"].startswith("ds_")
        assert table_by_source["events.csv"]["columns"] == ["store_id", "date", "demand"]
        assert table_by_source["stores.csv"]["columns"] == ["store_id", "region"]


def test_upload_bundle_column_catalog_uses_metadata_when_csv_header_has_blank_first_cell(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "artifacts")

    with session_factory() as db:
        project = Project(
            id="p_upload_blank_header",
            name="upload-blank-header",
            target_column=None,
            current_phase="IDLE",
            autonomy_mode="full_auto",
        )
        db.add(project)
        db.flush()
        job = create_job(db, job_type="upload_data_bundle", project_id=project.id, input_payload={})
        uploads = [
            SimpleNamespace(
                filename="HomeCredit_columns_description.csv",
                content_type="text/csv",
                file=BytesIO(
                    b",Table,Row,Description,Special\n"
                    b"1,application_train.csv,TARGET,Target variable,\n"
                    b"2,application_train.csv,SK_ID_CURR,Client id,\n"
                ),
            ),
        ]
        staged = stage_upload_bundle_files(db, store=store, project=project, job=job, uploads=uploads, stage_kind="table")
        staged_metadata = loads_json(staged[0].metadata_json, {})
        assert staged_metadata["column_names"] == ["Table", "Row", "Description", "Special"]
        job.input_json = dumps_json(
            {
                "staged_table_artifact_ids": [artifact.id for artifact in staged],
                "staged_relational_hint_artifact_ids": [],
                "primary_filename": None,
                "target_column": None,
                "response_locale": "ja-JP",
            }
        )
        mark_job_running(job)

        output = upload_data_bundle_handler(db, job, store)
        db.flush()

        assert output["schema_version"] == "upload_data_bundle.v1"
        catalog = db.scalar(select(SemanticCatalog).where(SemanticCatalog.project_id == project.id))
        assert catalog is not None
        semantic_columns = loads_json(catalog.columns_json, [])
        assert [item["column_name"] for item in semantic_columns] == ["Table", "Row", "Description", "Special"]
        assert "column0" not in {item["column_name"] for item in semantic_columns}

        column_catalog = project_data_columns(project.id, db)
        table_by_source = {table["source_ref"]: table for table in column_catalog["tables"]}
        assert table_by_source["HomeCredit_columns_description.csv"]["columns"] == [
            "Table",
            "Row",
            "Description",
            "Special",
        ]

        dataset = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id))
        assert dataset is not None
        artifact = db.get(Artifact, dataset.artifact_id)
        assert artifact is not None
        stale_metadata = loads_json(artifact.metadata_json, {})
        stale_metadata["column_names"] = ["column0", "Table", "Row", "Description", "Special"]
        artifact.metadata_json = dumps_json(stale_metadata)
        for stale_catalog in db.scalars(select(SemanticCatalog).where(SemanticCatalog.project_id == project.id)).all():
            db.delete(stale_catalog)
        db.flush()

        fallback_catalog = project_data_columns(project.id, db)
        fallback_by_source = {table["source_ref"]: table for table in fallback_catalog["tables"]}
        assert fallback_by_source["HomeCredit_columns_description.csv"]["columns"] == [
            "Table",
            "Row",
            "Description",
            "Special",
        ]
        assert "column0" not in fallback_by_source["HomeCredit_columns_description.csv"]["columns"]
