from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    Artifact,
    Asset,
    AssetReference,
    AssetVersion,
    DatasetSnapshot,
    EvaluationSpec,
    Idea,
    Job,
    Project,
    SplitManifest,
)
from tabular_harness.schemas import AgentTaskContract
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_to_dict,
    create_lineage_edge,
)
from tabular_harness.services.asset_library import asset_reference_to_dict


@dataclass(frozen=True)
class AgentContextPackResult:
    context_pack: dict[str, Any]
    artifact: Artifact


def prepare_idea_agent_context_pack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    idea: Idea,
    job: Job | None = None,
) -> AgentContextPackResult:
    contract_payload = loads_json(idea.agent_task_contract_json, {})
    contract = AgentTaskContract.model_validate(contract_payload)
    dataset = db.get(DatasetSnapshot, idea.dataset_snapshot_id) if idea.dataset_snapshot_id else latest_dataset(db, project.id)
    evaluation_spec = db.get(EvaluationSpec, idea.evaluation_spec_id) if idea.evaluation_spec_id else latest_approved_spec(db, project.id)
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    quality_gate_artifact = latest_project_artifact(db, project.id, "data_quality_gate")
    relational_catalog_artifact = latest_project_artifact(db, project.id, "relational_catalog")
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.created_at.desc())
            .limit(16)
        ).all()
    )
    asset_references = list(
        db.scalars(
            select(AssetReference)
            .where(
                or_(
                    (AssetReference.source_type == "project") & (AssetReference.source_id == project.id),
                    (AssetReference.source_type == "idea") & (AssetReference.source_id == idea.id),
                )
            )
            .order_by(AssetReference.created_at.desc())
        ).all()
    )
    context_pack = build_agent_context_pack(
        project=project,
        idea=idea,
        contract=contract,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        quality_gate_artifact=quality_gate_artifact,
        relational_catalog_artifact=relational_catalog_artifact,
        artifacts=artifacts,
        asset_references=expanded_asset_references(db, asset_references),
    )
    Draft202012Validator(load_agent_context_pack_schema()).validate(context_pack)
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_context_pack",
        name=f"agent_context_pack_{idea.id}_{new_id('acpart')}",
        filename="agent_context_pack.json",
        payload=context_pack,
        metadata={
            "project_id": project.id,
            "idea_id": idea.id,
            "context_pack_id": context_pack["id"],
            "job_id": job.id if job else None,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
        },
    )
    create_context_lineage(
        db,
        project=project,
        idea=idea,
        artifact=artifact,
        dataset=dataset,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
        asset_references=asset_references,
        job=job,
    )
    return AgentContextPackResult(context_pack=context_pack, artifact=artifact)


def build_agent_context_pack(
    *,
    project: Project,
    idea: Idea,
    contract: AgentTaskContract,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    quality_gate_artifact: Artifact | None,
    relational_catalog_artifact: Artifact | None,
    artifacts: list[Artifact],
    asset_references: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_payload = contract.model_dump(mode="json", by_alias=True)
    allowed_research_modes = contract_payload.get("inputs", {}).get("allowed_research_modes", [])
    if not isinstance(allowed_research_modes, list):
        allowed_research_modes = []
    return {
        "schema_version": "agent_context_pack.v1",
        "id": new_id("acp"),
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "idea": {
            "id": idea.id,
            "title": idea.title,
            "approach_type": idea.approach_type,
            "hypothesis": idea.hypothesis,
            "risk_level": idea.risk_level,
            "confidence": idea.confidence,
            "status": idea.status,
        },
        "agent_task_contract": contract_payload,
        "research_policy": {
            "allowed_modes": allowed_research_modes,
            "skill_library_policy": "Use only explicitly referenced cross-project assets unless the harness attaches more.",
            "controlled_web_search_policy": (
                "External web or literature search is allowed only when runner policy enables network access; "
                "claims must return citations as Evidence or artifact-backed source summaries."
            ),
            "citation_requirement": "Every external claim must include source title, URL or DOI when available, retrieval date, and relevance note.",
            "no_external_dashboard_dependency": "Summaries must be understandable inside the product UI.",
        },
        "safety_controls": {
            "secret_access": "forbidden",
            "connector_credentials": "never passed to the agent",
            "production_write": "forbidden",
            "must_respect_split_manifest": True,
            "forbidden_actions": contract.forbidden_actions,
            "feature_generation_guardrails": [
                "Do not include validation/test targets in prompts, encoders, or generated features.",
                "Fit preprocessing on the training split only.",
                "Exclude leakage-suspect columns until confirmed or scenario-compared by the harness.",
                "Do not destructively modify EvaluationSpec or SplitManifest.",
            ],
        },
        "data_context": dataset_context(dataset),
        "evaluation_context": evaluation_context(evaluation_spec, split_manifest),
        "quality_gate_context": quality_gate_context(quality_gate_artifact),
        "relational_context": relational_context(relational_catalog_artifact),
        "artifact_refs": artifact_refs(artifacts),
        "library_asset_references": asset_references,
        "required_outputs": contract_payload["required_outputs"],
        "generated_at": project.updated_at.isoformat(),
    }


def dataset_context(dataset: DatasetSnapshot | None) -> dict[str, Any]:
    if dataset is None:
        return {"dataset_snapshot_id": None, "status": "missing"}
    return {
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "source_type": dataset.source_type,
        "source_ref": dataset.source_ref,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema_hash": dataset.schema_hash,
        "data_hash": dataset.data_hash,
    }


def evaluation_context(evaluation_spec: EvaluationSpec | None, split_manifest: SplitManifest | None) -> dict[str, Any]:
    if evaluation_spec is None:
        return {
            "evaluation_spec_id": None,
            "status": "missing",
            "split_manifest_id": None,
        }
    return {
        "evaluation_spec_id": evaluation_spec.id,
        "status": evaluation_spec.status,
        "split_type": evaluation_spec.split_type,
        "primary_metric": evaluation_spec.primary_metric,
        "secondary_metrics": loads_json(evaluation_spec.secondary_metrics_json, []),
        "excluded_columns": loads_json(evaluation_spec.excluded_columns_json, []),
        "time_column": evaluation_spec.time_column,
        "group_column": evaluation_spec.group_column,
        "stratify_column": evaluation_spec.stratify_column,
        "split_manifest_id": split_manifest.id if split_manifest else None,
        "split_manifest": split_manifest_context(split_manifest),
    }


def split_manifest_context(split_manifest: SplitManifest | None) -> dict[str, Any] | None:
    if split_manifest is None:
        return None
    return {
        "id": split_manifest.id,
        "artifact_id": split_manifest.artifact_id,
        "train_count": split_manifest.train_count,
        "valid_count": split_manifest.valid_count,
        "test_count": split_manifest.test_count,
        "summary": loads_json(split_manifest.summary_json, {}),
    }


def quality_gate_context(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "severity": metadata.get("severity"),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def relational_context(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    metadata = loads_json(artifact.metadata_json, {})
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "table_count": metadata.get("table_count"),
        "relationship_count": metadata.get("relationship_count"),
        "benchmark_id": metadata.get("benchmark_id"),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def artifact_refs(artifacts: list[Artifact]) -> list[dict[str, Any]]:
    refs = []
    for artifact in artifacts:
        item = artifact_to_dict(artifact)
        refs.append(
            {
                "id": item["id"],
                "asset_type": item["asset_type"],
                "name": item["name"],
                "version": item["version"],
                "content_hash": item["content_hash"],
                "size_bytes": item["size_bytes"],
                "metadata": compact_artifact_metadata(item["metadata"]),
                "preview_url": f"/api/artifacts/{artifact.id}/preview",
                "download_url": f"/api/artifacts/{artifact.id}/download",
            }
        )
    return refs


def compact_artifact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowlist = {
        "source_filename",
        "dataset_snapshot_id",
        "evaluation_spec_id",
        "split_manifest_id",
        "model_version_id",
        "idea_id",
        "job_id",
        "report_type",
        "chart_type",
        "task_id",
        "context_pack_id",
    }
    return {key: value for key, value in metadata.items() if key in allowlist}


def expanded_asset_references(db: Session, references: list[AssetReference]) -> list[dict[str, Any]]:
    expanded = []
    for reference in references:
        asset = db.get(Asset, reference.target_asset_id)
        version = db.get(AssetVersion, reference.target_asset_version_id)
        expanded.append(asset_reference_to_dict(reference, asset=asset, version=version))
    return expanded


def create_context_lineage(
    db: Session,
    *,
    project: Project,
    idea: Idea,
    artifact: Artifact,
    dataset: DatasetSnapshot | None,
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    asset_references: list[AssetReference],
    job: Job | None,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="idea",
        from_asset_id=idea.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="contextualizes",
    )
    if job:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="included_in_context",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="included_in_context",
        )
    if split_manifest:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="split_manifest",
            from_asset_id=split_manifest.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="included_in_context",
        )
    for reference in asset_references:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="asset_reference",
            from_asset_id=reference.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="included_in_context",
        )


def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot).where(DatasetSnapshot.project_id == project_id).order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest).where(SplitManifest.evaluation_spec_id == spec_id).order_by(SplitManifest.created_at.desc())
    )


def latest_project_artifact(db: Session, project_id: str, asset_type: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    )


def load_agent_context_pack_schema() -> dict[str, Any]:
    candidates = [
        Path("schemas/agent_context_pack.schema.json"),
        Path(__file__).resolve().parents[4] / "schemas" / "agent_context_pack.schema.json",
    ]
    for path in candidates:
        if path.exists():
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    raise ValueError("schemas/agent_context_pack.schema.json not found")
