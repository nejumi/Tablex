from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.core.config import Settings
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import (
    Artifact,
    Base,
    ExperimentRun,
    LineageEdge,
    ModelVersion,
    Project,
    ResearchPlan,
    ResearchPlanRevision,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.storage_management import artifact_gc_plan, storage_usage_report


def test_register_artifact_reuses_existing_project_name_type_content_hash(tmp_path: Path) -> None:
    db = memory_session()
    project = Project(id="p_storage", name="Storage")
    db.add(project)
    db.flush()
    store = LocalArtifactStore(tmp_path / "artifacts")

    first_dir, first_stored, first_hash = store.store_text(
        org_id="local-org",
        project_id=project.id,
        asset_type="agent_session_report",
        name="chat_update",
        version=next_artifact_version(db, project.id, "agent_session_report", "chat_update"),
        filename="chat_update.md",
        text="same report",
        metadata={},
    )
    first = register_artifact(
        db,
        project_id=project.id,
        asset_type="agent_session_report",
        name="chat_update",
        uri=str(first_dir),
        content_hash=first_hash,
        size_bytes=first_stored.size_bytes,
        metadata={"primary_path": str(first_stored.path)},
        version=1,
    )
    second_dir, second_stored, second_hash = store.store_text(
        org_id="local-org",
        project_id=project.id,
        asset_type="agent_session_report",
        name="chat_update",
        version=next_artifact_version(db, project.id, "agent_session_report", "chat_update"),
        filename="chat_update.md",
        text="same report",
        metadata={},
    )
    second = register_artifact(
        db,
        project_id=project.id,
        asset_type="agent_session_report",
        name="chat_update",
        uri=str(second_dir),
        content_hash=second_hash,
        size_bytes=second_stored.size_bytes,
        metadata={"primary_path": str(second_stored.path)},
        version=2,
    )

    assert second.id == first.id
    assert len(db.scalars(select(Artifact).where(Artifact.name == "chat_update")).all()) == 1


def test_artifact_gc_plan_respects_lineage_plan_and_model_references(tmp_path: Path) -> None:
    db = memory_session()
    project = Project(id="p_gc", name="GC")
    db.add(project)
    db.flush()
    artifacts = [
        add_file_artifact(db, tmp_path, project_id=project.id, version=version, content=f"v{version}")
        for version in range(5)
    ]
    db.add(
        LineageEdge(
            id="lin_keep",
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifacts[1].id,
            to_asset_type="artifact",
            to_asset_id=artifacts[1].id,
            relation_type="supports_plan_node",
        )
    )
    plan = ResearchPlan(id="rp_keep", project_id=project.id, active_revision_id=None)
    db.add(plan)
    db.flush()
    revision = ResearchPlanRevision(
        id="rprev_keep",
        project_id=project.id,
        research_plan_id=plan.id,
        revision_index=1,
        document_json=dumps_json({"completion_evidence": [{"artifact_id": artifacts[2].id}]}),
        document_hash="hash_keep",
    )
    db.add(revision)
    run = ExperimentRun(id="run_keep", project_id=project.id, runner_type="test", status="succeeded")
    db.add(run)
    model = ModelVersion(
        id="mv_keep",
        project_id=project.id,
        experiment_run_id=run.id,
        artifact_id=artifacts[3].id,
        name="model",
        version=1,
        model_family="test",
        model_type="test",
        task_type="regression",
    )
    db.add(model)
    db.commit()

    plan_result = artifact_gc_plan(db, settings=storage_settings(tmp_path), dry_run=True, retention=1)

    candidate_ids = {item["artifact_id"] for item in plan_result["candidates"]}
    assert candidate_ids == {artifacts[0].id}
    assert plan_result["candidate_count"] == 1
    assert plan_result["reclaimable_bytes"] > 0


def test_storage_usage_report_has_required_categories(tmp_path: Path) -> None:
    db = memory_session()
    project = Project(id="p_usage", name="Usage")
    db.add(project)
    db.flush()
    artifact = add_file_artifact(db, tmp_path, project_id=project.id, version=1, content="dataset")
    artifact.asset_type = "dataset_snapshot"
    db.commit()
    settings = storage_settings(tmp_path)
    (settings.data_dir / "marimo_sessions" / "old").mkdir(parents=True)
    (settings.data_dir / "marimo_sessions" / "old" / "stderr.log").write_text("x", encoding="utf-8")

    usage = storage_usage_report(settings, db)

    assert usage["schema_version"] == "storage_usage.v1"
    assert set(usage["categories"]) == {"datasets", "artifacts", "workspaces", "pipeline_envs", "marimo", "db"}
    assert usage["categories"]["datasets"] > 0
    assert usage["categories"]["marimo"] > 0


def memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def add_file_artifact(db, tmp_path: Path, *, project_id: str, version: int, content: str) -> Artifact:
    artifact_dir = tmp_path / "artifacts" / "local-org" / project_id / "agent_session_report" / "rolling" / f"v{version}"
    artifact_dir.mkdir(parents=True)
    file_path = artifact_dir / "report.md"
    file_path.write_text(content, encoding="utf-8")
    artifact = Artifact(
        id=f"art_gc_{version}",
        project_id=project_id,
        asset_type="agent_session_report",
        name="rolling",
        version=version,
        uri=str(artifact_dir),
        content_hash=f"hash_{version}",
        size_bytes=len(content),
        metadata_json=dumps_json({"primary_path": str(file_path)}),
    )
    db.add(artifact)
    db.flush()
    return artifact


def storage_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_display_name="Tablex",
        data_dir=tmp_path / "data",
        database_url="sqlite://",
        artifact_root=tmp_path / "artifacts",
        max_upload_bytes=1024,
        cors_origins=(),
        artifact_version_retention=1,
    )
