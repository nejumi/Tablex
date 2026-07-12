from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.db.session import init_db
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationCandidate,
    ExperimentRun,
    Project,
)
from tabular_harness.services.artifacts import LocalArtifactStore, register_artifact
from tabular_harness.services.project_cloning import clone_project


def setup_project(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False), LocalArtifactStore(
        tmp_path / "artifacts"
    )


def add_dataset(db, store: LocalArtifactStore, project: Project) -> tuple[DatasetSnapshot, Artifact, Path]:
    target_dir, stored, content_hash = store.store_json(
        org_id=project.org_id,
        project_id=project.id,
        asset_type="uploaded_table",
        name="training",
        version=1,
        filename="training.json",
        payload=[{"row_id": 1, "target": 0}],
        metadata={"source_project_id": project.id},
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="uploaded_table",
        name="training",
        uri=str(target_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={"source_project_id": project.id},
    )
    dataset = DatasetSnapshot(
        id="ds_source",
        project_id=project.id,
        artifact_id=artifact.id,
        source_type="upload",
        source_ref="training.json",
        row_count=1,
        column_count=2,
        schema_hash=hashlib.sha256(b"row_id,target").hexdigest(),
        data_hash=stored.sha256,
    )
    db.add(dataset)
    db.flush()
    project.primary_dataset_snapshot_id = dataset.id
    return dataset, artifact, stored.path


def test_data_only_clone_copies_uploaded_data_and_resets_analysis(tmp_path: Path) -> None:
    session_factory, store = setup_project(tmp_path)
    with session_factory() as db:
        source = Project(
            id="p_source",
            name="Home Credit",
            task_type="classification",
            target_column="TARGET",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        db.add(source)
        db.flush()
        _, _, source_file = add_dataset(db, store, source)
        clone, counts = clone_project(
            db,
            store=store,
            source=source,
            name="Home Credit data copy",
            mode="data_only",
            created_by="local-user",
        )
        db.commit()

        cloned_dataset = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.project_id == clone.id))
        assert cloned_dataset is not None
        cloned_artifact = db.get(Artifact, cloned_dataset.artifact_id)
        assert cloned_artifact is not None
        cloned_file = Path(cloned_artifact.uri) / "training.json"
        assert counts["datasets"] == 1
        assert clone.current_phase == "DATA_READY"
        assert clone.task_type is None
        assert clone.target_column is None
        assert clone.primary_dataset_snapshot_id == cloned_dataset.id
        assert cloned_file != source_file
        assert cloned_file.read_bytes() == source_file.read_bytes()


def test_full_clone_remaps_saved_progress_without_copying_live_state(tmp_path: Path) -> None:
    session_factory, store = setup_project(tmp_path)
    with session_factory() as db:
        source = Project(
            id="p_source",
            name="Home Credit",
            task_type="classification",
            target_column="TARGET",
            current_phase="AUTONOMOUS_LOOP",
            autonomy_mode="full_auto",
        )
        db.add(source)
        db.flush()
        dataset, _, _ = add_dataset(db, store, source)
        candidate = EvaluationCandidate(
            id="evc_source",
            project_id=source.id,
            dataset_snapshot_id=dataset.id,
            name="Applicant-stratified folds",
            split_type="stratified",
            primary_metric="roc_auc",
            rationale_md="Stable applicant-level comparison.",
            confidence=0.9,
            risk_level="medium",
            status="proposed",
        )
        run = ExperimentRun(
            id="run_source",
            project_id=source.id,
            dataset_snapshot_id=dataset.id,
            evaluation_candidate_id=candidate.id,
            runner_type="codex_main_session",
            status="succeeded",
            params_json=dumps_json({"dataset_snapshot_id": dataset.id, "project_id": source.id}),
            metrics_json=dumps_json({"roc_auc": 0.78}),
        )
        db.add_all([candidate, run])
        db.flush()

        clone, _ = clone_project(
            db,
            store=store,
            source=source,
            name="Home Credit full copy",
            mode="full",
            created_by="local-user",
        )
        db.commit()

        cloned_dataset = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.project_id == clone.id))
        cloned_candidate = db.scalar(select(EvaluationCandidate).where(EvaluationCandidate.project_id == clone.id))
        cloned_run = db.scalar(select(ExperimentRun).where(ExperimentRun.project_id == clone.id))
        assert cloned_dataset is not None and cloned_dataset.id != dataset.id
        assert cloned_candidate is not None and cloned_candidate.dataset_snapshot_id == cloned_dataset.id
        assert cloned_run is not None
        assert cloned_run.dataset_snapshot_id == cloned_dataset.id
        assert cloned_run.evaluation_candidate_id == cloned_candidate.id
        assert loads_json(cloned_run.params_json, {}) == {
            "dataset_snapshot_id": cloned_dataset.id,
            "project_id": clone.id,
        }
        assert clone.current_phase == "IDLE"
        assert clone.autonomy_mode == "approval_based"
        assert clone.task_type == source.task_type
        assert clone.target_column == source.target_column
