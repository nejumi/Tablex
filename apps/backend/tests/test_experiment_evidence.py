from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tabular_harness.api.routes import list_runs
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    Base,
    DatasetSnapshot,
    EvaluationSpec,
    ExperimentRun,
    LineageEdge,
    Project,
    SplitManifest,
)
from tabular_harness.services.agent_session_results import RunSpec, register_experiment_run_specs
from tabular_harness.services.approach import store_text_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path
from tabular_harness.services.experiment_evidence import register_experiment_evidence


def test_experiment_evidence_replays_oof_against_frozen_labels(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    with sessionmaker(engine)() as db:
        project, run, oof_artifact = create_run_fixture(db, store=store, project_id="p_evidence")
        artifact = register_experiment_evidence(
            db,
            store=store,
            project=project,
            run=run,
            payload=evidence_payload(run=run, oof_artifact=oof_artifact),
        )
        db.commit()

        saved = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        assert saved["schema_version"] == "experiment_evidence.v1"
        assert saved["verification"]["predictions"]["coverage_status"] == "complete"
        assert saved["verification"]["predictions"]["labels_read_from_frozen_dataset"] is True
        assert saved["verification"]["metric_replay"]["status"] == "passed"
        assert saved["verification"]["metric_replay"]["replayed_aggregate_value"] == pytest.approx(1.0)
        assert len(saved["verification"]["metric_replay"]["fold_values"]) == 2
        edges = list(
            db.scalars(
                select(LineageEdge).where(
                    LineageEdge.project_id == project.id,
                    LineageEdge.to_asset_id == artifact.id,
                )
            ).all()
        )
        assert {edge.relation_type for edge in edges} == {
            "documents_experiment_evidence",
            "supports_experiment_evidence",
        }
        run_payload = list_runs(project.id, db)[0]
        assert run_payload["experiment_evidence"] == {
            "status": "verified",
            "artifact_id": artifact.id,
            "parent_run_id": None,
            "metric_replay_status": "passed",
            "prediction_coverage_status": "complete",
            "prediction_coverage_scope": "full_labeled_dataset",
            "hypothesis_verdict": "supported",
            "decision_action": "retain_and_refine",
        }


def test_experiment_evidence_rejects_incomplete_oof_coverage(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    with sessionmaker(engine)() as db:
        project, run, _ = create_run_fixture(db, store=store, project_id="p_incomplete")
        incomplete = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="oof_predictions",
            name="incomplete_oof",
            filename="oof.csv",
            text="row_index,fold,score\n0,0,0.1\n1,0,0.9\n",
            metadata={"schema_version": "oof_predictions.v1"},
        )
        db.commit()

        with pytest.raises(ValueError, match="coverage is incomplete"):
            register_experiment_evidence(
                db,
                store=store,
                project=project,
                run=run,
                payload=evidence_payload(run=run, oof_artifact=incomplete),
            )


def test_experiment_registration_links_verified_evidence_to_run(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    with sessionmaker(engine)() as db:
        project, fixture_run, oof_artifact = create_run_fixture(db, store=store, project_id="p_registration")
        db.delete(fixture_run)
        session = AgentSession(
            id="ags_registration",
            project_id=project.id,
            goal_text="Register a verified candidate.",
            workspace_path=str(tmp_path / "workspace"),
        )
        db.add(session)
        db.flush()
        payload = evidence_payload(run=fixture_run, oof_artifact=oof_artifact)
        runs = register_experiment_run_specs(
            db,
            store=store,
            project=project,
            session=session,
            specs=[
                RunSpec(
                    source_key="verified-candidate",
                    model_id="verified_candidate",
                    summary="Candidate registered with replayed OOF evidence.",
                    metrics={
                        "roc_auc": 1.0,
                        "primary_metric_name": "roc_auc",
                        "primary_metric_value": 1.0,
                    },
                    params={"features_used": ["behavioral_aggregate"]},
                    primary_metric_name="roc_auc",
                    primary_metric_value=1.0,
                    dataset_snapshot_id=fixture_run.dataset_snapshot_id,
                    evaluation_spec_id=fixture_run.evaluation_spec_id,
                    split_manifest_id=fixture_run.split_manifest_id,
                    experiment_evidence=payload,
                )
            ],
            source_artifact=None,
            source_request_id="request-verified-candidate",
        )
        db.commit()

        assert len(runs) == 1
        params = loads_json(runs[0].params_json, {})
        assert params["experiment_evidence_status"] == "verified"
        evidence_artifact = db.get(Artifact, params["experiment_evidence_artifact_id"])
        assert evidence_artifact is not None
        assert evidence_artifact.asset_type == "experiment_evidence"


def test_experiment_evidence_keeps_custom_metric_as_registered_unreplayed(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    with sessionmaker(engine)() as db:
        project, run, oof_artifact = create_run_fixture(db, store=store, project_id="p_custom_metric")
        run.metrics_json = dumps_json(
            {
                "business_utility": 0.8,
                "primary_metric_name": "business_utility",
                "primary_metric_value": 0.8,
            }
        )
        payload = evidence_payload(run=run, oof_artifact=oof_artifact)
        payload["evaluation"]["primary_metric"] = "business_utility"  # type: ignore[index]
        payload["evaluation"]["aggregate_value"] = 0.8  # type: ignore[index]
        payload["evaluation"]["fold_values"] = [0.7, 0.9]  # type: ignore[index]
        artifact = register_experiment_evidence(
            db,
            store=store,
            project=project,
            run=run,
            payload=payload,
        )

        saved = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        assert saved["verification"]["predictions"]["coverage_status"] == "complete"
        assert saved["verification"]["metric_replay"]["status"] == "unsupported"


def test_experiment_evidence_replays_declared_validation_scope(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    store = LocalArtifactStore(tmp_path / "artifacts")
    with sessionmaker(engine)() as db:
        project, run, _ = create_run_fixture(db, store=store, project_id="p_validation_scope")
        validation_predictions = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="validation_predictions",
            name="validation_predictions",
            filename="validation.csv",
            text="row_index,fold,score\n1,valid,0.9\n2,valid,0.2\n",
            metadata={"schema_version": "validation_predictions.v1"},
        )
        validation_split = store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="split_manifest",
            name="validation_scope_split",
            filename="split.csv",
            text="row_index,split\n0,train\n1,valid\n2,valid\n3,train\n",
            metadata={"schema_version": "split_manifest.v1"},
        )
        split = db.get(SplitManifest, run.split_manifest_id)
        assert split is not None
        split.artifact_id = validation_split.id
        payload = evidence_payload(run=run, oof_artifact=validation_predictions)
        payload["evaluation"]["coverage_scope"] = "split_manifest_validation"  # type: ignore[index]
        payload["evaluation"]["fold_values"] = [{"fold": "valid", "value": 1.0}]  # type: ignore[index]
        payload["artifacts"] = {"validation_predictions": validation_predictions.id}
        artifact = register_experiment_evidence(
            db,
            store=store,
            project=project,
            run=run,
            payload=payload,
        )

        saved = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        assert saved["verification"]["predictions"]["coverage_scope"] == "split_manifest_validation"
        assert saved["verification"]["predictions"]["expected_row_count"] == 2
        assert saved["verification"]["metric_replay"]["replayed_aggregate_value"] == pytest.approx(1.0)


def create_run_fixture(
    db,
    *,
    store: LocalArtifactStore,
    project_id: str,
) -> tuple[Project, ExperimentRun, Artifact]:
    project = Project(id=project_id, name="Evidence Test", target_column="target")
    db.add(project)
    db.flush()
    dataset_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="dataset_snapshot",
        name="training_data",
        filename="train.csv",
        text="feature,target\n10,0\n20,1\n30,0\n40,1\n",
        metadata={"project_id": project.id},
    )
    split_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="split_manifest",
        name="evaluation_split",
        filename="split.json",
        text="{}",
        metadata={"project_id": project.id},
    )
    dataset = DatasetSnapshot(
        id=f"ds_{project_id}",
        project_id=project.id,
        artifact_id=dataset_artifact.id,
        source_type="upload",
        row_count=4,
        column_count=2,
        schema_hash="schema",
    )
    evaluation = EvaluationSpec(
        id=f"eval_{project_id}",
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        name="Two-fold OOF",
        split_type="stratified_kfold",
        primary_metric="roc_auc",
        rationale_md="Replay OOF predictions against frozen labels.",
        risk_level="low",
        status="approved",
    )
    split = SplitManifest(
        id=f"split_{project_id}",
        project_id=project.id,
        evaluation_spec_id=evaluation.id,
        artifact_id=split_artifact.id,
        train_count=2,
        valid_count=2,
    )
    run = ExperimentRun(
        id=f"run_{project_id}",
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        evaluation_spec_id=evaluation.id,
        split_manifest_id=split.id,
        runner_type="codex_main_session",
        status="succeeded",
        params_json=dumps_json({"model_id": "candidate"}),
        metrics_json=dumps_json(
            {"roc_auc": 1.0, "primary_metric_name": "roc_auc", "primary_metric_value": 1.0}
        ),
        summary_md="A candidate with complete two-fold OOF predictions.",
    )
    db.add_all([dataset, evaluation, split, run])
    oof_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="oof_predictions",
        name="candidate_oof",
        filename="oof.csv",
        text="row_index,fold,score\n0,0,0.1\n1,0,0.9\n2,1,0.2\n3,1,0.8\n",
        metadata={"schema_version": "oof_predictions.v1"},
    )
    db.flush()
    return project, run, oof_artifact


def evidence_payload(*, run: ExperimentRun, oof_artifact: Artifact) -> dict[str, object]:
    return {
        "schema_version": "experiment_evidence.v1",
        "hypothesis": {
            "statement": "The candidate ranks positive examples above negative examples.",
            "expected_observation": "OOF ROC-AUC improves consistently across folds.",
        },
        "change_set": {"feature_families_added": ["behavioral_aggregate"]},
        "evaluation": {
            "split_manifest_id": run.split_manifest_id,
            "primary_metric": "roc_auc",
            "aggregate_value": 1.0,
            "fold_values": [1.0, 1.0],
            "coverage_scope": "full_labeled_dataset",
        },
        "artifacts": {"oof_predictions": oof_artifact.id},
        "learning": {"verdict": "supported", "remaining_uncertainty": "Small synthetic fixture."},
        "decision": {"action": "retain_and_refine"},
    }
