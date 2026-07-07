from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.db.session import init_db
from tabular_harness.models.entities import AgentSession, Artifact, DatasetSnapshot, LineageEdge, Project
from tabular_harness.services.agent_inbox import list_inbox_entries
from tabular_harness.services.agent_sessions import process_data_tool_requests
from tabular_harness.services.artifacts import LocalArtifactStore, register_artifact


def _session_setup(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    init_db(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "workspace"
    (workspace / ".tablex" / "requests" / "data").mkdir(parents=True)
    (workspace / ".tablex" / "acks" / "data").mkdir(parents=True)
    (workspace / ".tablex" / "inbox").mkdir(parents=True)
    return session_factory, store, workspace


def _add_project_session_dataset(db, store: LocalArtifactStore, workspace: Path) -> tuple[Project, AgentSession, DatasetSnapshot]:
    project = Project(id="p_data_req", name="data request", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
    db.add(project)
    artifact_dir, stored, content_hash = store.store_text(
        org_id="local-org",
        project_id=project.id,
        asset_type="uploaded_supporting_table",
        name="uploaded_events",
        version=1,
        filename="events.csv",
        text="store_id,date,demand\n1,2026-01-01,10\n2,2026-01-01,14\n",
        metadata={"project_id": project.id, "source_filename": "events.csv", "primary_path": "events.csv"},
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="uploaded_supporting_table",
        name="uploaded_events",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={"project_id": project.id, "source_filename": "events.csv", "primary_path": str(stored.path)},
        version=1,
    )
    dataset = DatasetSnapshot(
        id="ds_events",
        project_id=project.id,
        artifact_id=artifact.id,
        source_type="user_upload_bundle_table",
        source_ref="events.csv",
        row_count=2,
        column_count=3,
        schema_hash="schema",
        data_hash=content_hash,
    )
    session = AgentSession(id="ags_data_req", project_id=project.id, workspace_path=str(workspace), goal_text="Continue.")
    db.add(dataset)
    db.add(session)
    db.flush()
    return project, session, dataset


def _write_data_request(workspace: Path, name: str, payload: dict) -> Path:
    path = workspace / ".tablex" / "requests" / "data" / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_ack(workspace: Path, name: str) -> dict:
    return loads_json((workspace / ".tablex" / "acks" / "data" / f"{name}.ack.json").read_text(encoding="utf-8"), {})


def test_set_primary_table_accepts_dataset_snapshot_reference(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        assert project.primary_dataset_snapshot_id is None
        _write_data_request(
            workspace,
            "set_primary",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "set_primary",
                "operation": "set_primary_table",
                "payload": {
                    "dataset_snapshot_id": dataset.id,
                    "rationale": "The historical events table is the current row-grain candidate.",
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "set_primary")
        assert ack["status"] == "succeeded"
        assert ack["result"]["dataset_snapshot_id"] == dataset.id
        assert project.primary_dataset_snapshot_id == dataset.id
        artifact = db.get(Artifact, dataset.artifact_id)
        assert artifact is not None
        metadata = loads_json(artifact.metadata_json, {})
        assert metadata["selected_as_primary_dataset_snapshot_id"] == dataset.id


def test_set_primary_table_accepts_uploaded_artifact_without_existing_dataset_snapshot(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project = Project(id="p_data_req", name="data request", current_phase="AUTONOMOUS_LOOP", autonomy_mode="full_auto")
        db.add(project)
        artifact_dir, stored, content_hash = store.store_text(
            org_id="local-org",
            project_id=project.id,
            asset_type="uploaded_supporting_table",
            name="uploaded_events_without_profile",
            version=1,
            filename="events.csv",
            text="store_id,date,demand\n1,2026-01-01,10\n2,2026-01-01,14\n",
            metadata={"project_id": project.id, "source_filename": "events.csv", "primary_path": "events.csv"},
        )
        artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type="uploaded_supporting_table",
            name="uploaded_events_without_profile",
            uri=str(artifact_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={"project_id": project.id, "source_filename": "events.csv", "primary_path": str(stored.path)},
            version=1,
        )
        session = AgentSession(id="ags_data_req", project_id=project.id, workspace_path=str(workspace), goal_text="Continue.")
        db.add(session)
        db.flush()
        assert db.scalars(select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id)).all() == []

        _write_data_request(
            workspace,
            "set_primary_from_artifact",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "set_primary_from_artifact",
                "operation": "set_primary_table",
                "payload": {
                    "artifact_id": artifact.id,
                    "rationale": "The uploaded events artifact is the row-grain candidate after data understanding.",
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "set_primary_from_artifact")
        assert ack["status"] == "succeeded"
        dataset = db.get(DatasetSnapshot, ack["result"]["dataset_snapshot_id"])
        assert dataset is not None
        assert dataset.artifact_id == artifact.id
        assert dataset.source_type == "codex_selected_primary_table"
        assert project.primary_dataset_snapshot_id == dataset.id
        metadata = loads_json(artifact.metadata_json, {})
        assert metadata["selected_as_primary_dataset_snapshot_id"] == dataset.id


def test_set_primary_table_rejects_ambiguous_or_foreign_reference(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        other_project = Project(id="p_other", name="other")
        other_dataset = DatasetSnapshot(
            id="ds_other",
            project_id=other_project.id,
            artifact_id=dataset.artifact_id,
            source_type="fixture",
            source_ref="other.csv",
            row_count=1,
            column_count=1,
            schema_hash="other",
            data_hash="other",
        )
        db.add_all([other_project, other_dataset])
        db.flush()

        _write_data_request(
            workspace,
            "ambiguous_primary",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "ambiguous_primary",
                "operation": "set_primary_table",
                "payload": {
                    "dataset_snapshot_id": dataset.id,
                    "artifact_id": dataset.artifact_id,
                },
            },
        )
        _write_data_request(
            workspace,
            "foreign_primary",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "foreign_primary",
                "operation": "set_primary_table",
                "payload": {"dataset_snapshot_id": other_dataset.id},
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ambiguous_ack = _read_ack(workspace, "ambiguous_primary")
        foreign_ack = _read_ack(workspace, "foreign_primary")
        assert ambiguous_ack["status"] == "failed"
        assert "exactly one" in ambiguous_ack["error"]["message"]
        assert foreign_ack["status"] == "failed"
        assert "does not belong to this project" in foreign_ack["error"]["message"]
        assert project.primary_dataset_snapshot_id is None
        entries = list_inbox_entries(workspace)
        assert sum(1 for item in entries if item["kind"] == "rejection" and item["type"] == "data_request_rejection") == 2


def test_commit_task_spec_allows_unsupervised_without_targets(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        _write_data_request(
            workspace,
            "commit_clustering",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "commit_clustering",
                "operation": "commit_task_spec",
                "payload": {
                    "task_spec": {
                        "schema_version": "task_spec.v1",
                        "objective_text": "Group stores by observed demand patterns before choosing a supervised target.",
                        "task_shape": "clustering",
                        "targets": [],
                        "granularity": {
                            "kind": "row",
                            "dataset_snapshot_id": dataset.id,
                            "description": "One row is one store-date observation.",
                        },
                        "assumptions": [],
                        "status": "provisional",
                    }
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "commit_clustering")
        assert ack["status"] == "succeeded"
        assert ack["result"]["task_shape"] == "clustering"
        assert ack["result"]["target_column"] is None
        assert project.task_type == "clustering"
        assert project.target_column is None
        task_artifact = db.get(Artifact, ack["result"]["task_spec_artifact_id"])
        assert task_artifact is not None
        assert task_artifact.asset_type == "task_spec"


def test_commit_task_spec_accepts_supervised_target_table_ref_and_denormalizes_target(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        _write_data_request(
            workspace,
            "commit_supervised",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "commit_supervised",
                "operation": "commit_task_spec",
                "payload": {
                    "task_spec": {
                        "schema_version": "task_spec.v1",
                        "objective_text": "Predict demand for future store-date rows after reviewing row grain.",
                        "task_shape": "supervised_regression",
                        "targets": [{"table_ref": dataset.id, "column": "demand", "derivation": None}],
                        "granularity": {
                            "kind": "row",
                            "table_ref": dataset.id,
                            "description": "One row is one store-date observation.",
                        },
                        "assumptions": ["Future rows will have the same feature columns except the target."],
                        "status": "provisional",
                    }
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "commit_supervised")
        assert ack["status"] == "succeeded"
        assert ack["result"]["task_shape"] == "supervised_regression"
        assert ack["result"]["target_column"] == "demand"
        assert project.task_type == "supervised_regression"
        assert project.target_column == "demand"
        lineage = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "dataset_snapshot",
                LineageEdge.from_asset_id == dataset.id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.relation_type == "referenced_by_task_spec",
            )
        )
        assert lineage is not None


def test_commit_task_spec_rejects_dataset_reference_from_another_project(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, _dataset = _add_project_session_dataset(db, store, workspace)
        _write_data_request(
            workspace,
            "bad_ref",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "bad_ref",
                "operation": "commit_task_spec",
                "payload": {
                    "task_spec": {
                        "schema_version": "task_spec.v1",
                        "objective_text": "Predict demand.",
                        "task_shape": "supervised_regression",
                        "targets": [{"table_ref": "ds_missing", "column": "demand", "derivation": None}],
                        "granularity": {"kind": "row", "table_ref": "ds_missing"},
                        "assumptions": [],
                        "status": "provisional",
                    }
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "bad_ref")
        assert ack["status"] == "failed"
        assert "outside this project" in ack["error"]["message"]
        entries = list_inbox_entries(workspace)
        assert any(item["kind"] == "rejection" and item["type"] == "data_request_rejection" for item in entries)
        assert db.scalars(select(Artifact).where(Artifact.project_id == project.id, Artifact.asset_type == "task_spec")).all() == []


def test_commit_task_spec_rejects_legacy_task_shape_alias(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        _write_data_request(
            workspace,
            "legacy_shape",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "legacy_shape",
                "operation": "commit_task_spec",
                "payload": {
                    "task_spec": {
                        "schema_version": "task_spec.v1",
                        "objective_text": "Predict demand.",
                        "task_shape": "regression",
                        "targets": [{"table_ref": dataset.id, "column": "demand", "derivation": None}],
                        "granularity": {"kind": "row", "table_ref": dataset.id},
                        "assumptions": [],
                        "status": "provisional",
                    }
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "legacy_shape")
        assert ack["status"] == "failed"
        assert "supervised_regression" in ack["error"]["message"]
        assert project.target_column is None


def test_register_derived_table_records_dataset_and_lineage(tmp_path: Path) -> None:
    session_factory, store, workspace = _session_setup(tmp_path)
    with session_factory() as db:
        project, session, dataset = _add_project_session_dataset(db, store, workspace)
        derived_path = workspace / "outputs" / "store_summary.csv"
        derived_path.parent.mkdir(parents=True)
        derived_path.write_text("store_id,mean_demand\n1,10\n2,14\n", encoding="utf-8")
        _write_data_request(
            workspace,
            "register_derived",
            {
                "schema_version": "tablex_data_request.v1",
                "request_id": "register_derived",
                "operation": "register_derived_table",
                "payload": {
                    "workspace_path": "outputs/store_summary.csv",
                    "name": "store_summary",
                    "derivation": {
                        "source_dataset_snapshot_ids": [dataset.id],
                        "description": "Fold-independent row-grain summary for inspection.",
                    },
                    "row_granularity": {"kind": "entity", "entity": "store_id"},
                },
            },
        )

        process_data_tool_requests(db, store=store, project=project, session=session, workspace=workspace)
        db.flush()

        ack = _read_ack(workspace, "register_derived")
        assert ack["status"] == "succeeded"
        derived_dataset = db.get(DatasetSnapshot, ack["result"]["dataset_snapshot_id"])
        assert derived_dataset is not None
        assert derived_dataset.source_ref == "store_summary"
        edge = db.scalar(
            select(LineageEdge).where(
                LineageEdge.project_id == project.id,
                LineageEdge.from_asset_type == "dataset_snapshot",
                LineageEdge.from_asset_id == dataset.id,
                LineageEdge.to_asset_type == "dataset_snapshot",
                LineageEdge.to_asset_id == derived_dataset.id,
                LineageEdge.relation_type == "derived_table_input",
            )
        )
        assert edge is not None
