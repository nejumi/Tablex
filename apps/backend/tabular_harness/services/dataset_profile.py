from __future__ import annotations

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    AssumptionEvidenceLink,
    DatasetSnapshot,
    Evidence,
    Project,
    Question,
    SemanticCatalog,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.profiler import profile_tabular_file


def profile_dataset_artifact(
    db: Session,
    store: LocalArtifactStore,
    project: Project,
    dataset_artifact: Artifact,
    target_column: str | None,
    source_type: str = "upload",
    source_ref: str | None = None,
) -> DatasetSnapshot:
    source_path = artifact_primary_path(dataset_artifact)
    result = profile_tabular_file(source_path, project.id, target_column)
    artifact_metadata = loads_json(dataset_artifact.metadata_json, {})
    dataset = DatasetSnapshot(
        id=new_id("ds"),
        project_id=project.id,
        artifact_id=dataset_artifact.id,
        source_type=source_type,
        source_ref=source_ref if source_ref is not None else artifact_metadata.get("source_filename"),
        row_count=result.row_count,
        column_count=result.column_count,
        schema_hash=result.schema_hash,
        data_hash=dataset_artifact.content_hash,
    )
    db.add(dataset)
    db.flush()

    profile_metadata = {
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "profile_mode": result.profile.get("profile_mode"),
        "column_stat_scope": result.profile.get("column_stat_scope"),
        "sample_row_count": (result.profile.get("profile_sample") or {}).get("sample_row_count"),
        "deep_profile_recommended": (result.profile.get("deferred_deep_profile") or {}).get("recommended"),
        "deferred_column_count": (result.profile.get("deferred_deep_profile") or {}).get("deferred_column_count"),
    }
    profile_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="eda_profile",
        name="profile",
        filename="profile.json",
        payload=result.profile,
        metadata=profile_metadata,
    )
    understanding_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="understanding_report",
        name="understanding",
        filename="understanding.md",
        text=result.understanding_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "profile_mode": result.profile.get("profile_mode"),
            "deep_profile_recommended": (result.profile.get("deferred_deep_profile") or {}).get("recommended"),
        },
    )
    semantic_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="semantic_catalog",
        name="semantic_catalog",
        filename="semantic_catalog.json",
        payload=result.semantic_catalog,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="question_set",
        name="questions",
        filename="questions.json",
        payload=result.questions,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="assumption_set",
        name="assumptions",
        filename="assumptions.json",
        payload=result.assumptions,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )
    store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="evidence_set",
        name="evidence",
        filename="evidence.json",
        payload=result.evidence,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id},
    )

    catalog = SemanticCatalog(
        id=new_id("scat"),
        project_id=project.id,
        dataset_snapshot_id=dataset.id,
        artifact_id=semantic_artifact.id,
        columns_json=dumps_json(result.semantic_catalog),
    )
    db.add(catalog)
    evidence_records = []
    for item in result.evidence:
        evidence = Evidence(
            id=item["id"],
            project_id=project.id,
            evidence_type=item["evidence_type"],
            summary=item["summary"],
            strength=item["strength"],
            source_artifact_id=profile_artifact.id,
            metadata_json=dumps_json(item.get("metadata") or {}),
        )
        db.add(evidence)
        evidence_records.append(evidence)
    assumption_records = []
    for item in result.assumptions:
        assumption = Assumption(
            id=item["id"],
            project_id=project.id,
            topic=item["topic"],
            subject_type=item.get("subject_type"),
            subject_ref=item.get("subject_ref"),
            statement=item["statement"],
            status=item["status"],
            confidence=float(item["confidence"]),
            risk_level=item["risk_level"],
            fallback_policy=item["fallback_policy"],
            requires_user_confirmation=bool(item.get("requires_user_confirmation")),
            created_by_type="system",
        )
        db.add(assumption)
        assumption_records.append(assumption)
    for item in result.questions:
        question = Question(
            id=item["id"],
            project_id=project.id,
            question_set_id=item["question_set_id"],
            topic=item.get("topic"),
            question=item["question"],
            why_it_matters=item["why_it_matters"],
            default_assumption=item.get("default_assumption"),
            impact_if_wrong=item.get("impact_if_wrong"),
            choices_json=dumps_json(item.get("choices") or []),
            priority=int(item.get("priority") or 50),
            risk_level=item["risk_level"],
            value_of_answer=item["value_of_answer"],
            can_proceed_without_answer=bool(item["can_proceed_without_answer"]),
            fallback_policy=item["fallback_policy"],
            related_assumption_id=item.get("related_assumption_id"),
            blocks_next_phase=bool(item.get("blocks_next_phase")),
        )
        db.add(question)
    db.flush()
    if evidence_records:
        for assumption in assumption_records:
            db.add(
                AssumptionEvidenceLink(
                    id=new_id("ael"),
                    assumption_id=assumption.id,
                    evidence_id=evidence_records[0].id,
                    effect="supports",
                    weight=1.0,
                )
            )
    for artifact in [dataset_artifact, profile_artifact, understanding_artifact, semantic_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    return dataset
