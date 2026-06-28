from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Asset, AssetReference, AssetVersion
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore

DEFAULT_LIBRARY_ASSETS: list[dict[str, Any]] = [
    {
        "asset_type": "skill",
        "name": "tabular_approach_research",
        "description": "Guides an agent to research tabular modeling approaches while preserving harness-owned evaluation.",
        "tags": ["agent", "research", "tabular"],
        "semantic_tags": ["approach_studio", "controlled_research"],
        "content": {
            "instructions": [
                "Use project artifacts and approved EvaluationSpec first.",
                "Use controlled web or literature search only when allowed by AgentTaskContract.",
                "Return citations as Evidence or artifact-backed sources.",
            ]
        },
    },
    {
        "asset_type": "evaluation_pattern",
        "name": "scenario_compare_text_features",
        "description": "Compare no-text and text-enhanced scenarios under the same SplitManifest.",
        "tags": ["evaluation", "scenario_compare", "text"],
        "semantic_tags": ["text_features", "split_manifest"],
        "content": {
            "scenarios": ["without_text", "with_text"],
            "required_controls": ["same_split_manifest", "train_fold_only_vectorizer"],
        },
    },
    {
        "asset_type": "prompt_template",
        "name": "agent_result_report_prompt",
        "description": "Template for concise agent run reports with metrics, assumptions, risks, and next steps.",
        "tags": ["report", "prompt"],
        "semantic_tags": ["agent_result", "reporting"],
        "content": {
            "sections": ["Objective", "Data/Evaluation Context", "Implementation", "Results", "Risks", "Next Steps"]
        },
    },
    {
        "asset_type": "visualization_template",
        "name": "leaderboard_primary_metric",
        "description": "Portable visualization template for comparing primary metrics across runs.",
        "tags": ["visualization", "leaderboard"],
        "semantic_tags": ["metrics", "reports"],
        "content": {
            "chart_type": "leaderboard_bar",
            "encoding": {"x": "run_id", "y": "primary_metric_value", "color": "runner_type"},
        },
    },
    {
        "asset_type": "feature_recipe",
        "name": "prediction_time_safe_features",
        "description": "Checklist for feature recipes that avoid target leakage and respect prediction-time availability.",
        "tags": ["features", "safety"],
        "semantic_tags": ["leakage_control", "prediction_time"],
        "content": {
            "checks": [
                "exclude target and validation/test labels",
                "exclude unconfirmed leakage-suspect columns",
                "fit encoders on train split only",
            ]
        },
    },
]


def seed_default_assets(db: Session, store: LocalArtifactStore) -> list[Asset]:
    created_or_existing: list[Asset] = []
    for definition in DEFAULT_LIBRARY_ASSETS:
        existing = db.scalar(
            select(Asset).where(Asset.asset_type == definition["asset_type"], Asset.name == definition["name"])
        )
        if existing is not None:
            created_or_existing.append(existing)
            continue
        created_or_existing.append(create_library_asset(db, store=store, payload=definition))
    return created_or_existing


def create_library_asset(db: Session, *, store: LocalArtifactStore, payload: dict[str, Any]) -> Asset:
    asset_id = new_id("asset")
    artifact = store_json_artifact(
        db,
        store,
        project_id=None,
        asset_type=f"library_{payload['asset_type']}",
        name=str(payload["name"]),
        filename="asset_version.json",
        payload={
            "schema_version": "asset_version.v1",
            "asset_type": payload["asset_type"],
            "name": payload["name"],
            "description": payload.get("description"),
            "content": payload.get("content") or {},
            "tags": payload.get("tags") or [],
            "semantic_tags": payload.get("semantic_tags") or [],
        },
        metadata={"asset_id": asset_id, "scope": "organization"},
    )
    asset = Asset(
        id=asset_id,
        asset_type=str(payload["asset_type"]),
        name=str(payload["name"]),
        description=payload.get("description"),
        scope="organization",
        tags_json=dumps_json(payload.get("tags") or []),
        semantic_tags_json=dumps_json(payload.get("semantic_tags") or []),
        visibility=str(payload.get("visibility") or "private"),
        status="active",
    )
    db.add(asset)
    db.flush()
    version = AssetVersion(
        id=new_id("av"),
        asset_id=asset.id,
        version="1.0.0",
        artifact_id=artifact.id,
        digest=artifact.content_hash,
        inputs_schema_json=dumps_json(payload.get("inputs_schema") or {}),
        outputs_schema_json=dumps_json(payload.get("outputs_schema") or {}),
        runtime_requirements_json=dumps_json(payload.get("runtime_requirements") or {}),
        created_from_project_id=payload.get("created_from_project_id"),
        created_from_run_id=payload.get("created_from_run_id"),
        status="active",
    )
    db.add(version)
    db.flush()
    asset.latest_version_id = version.id
    return asset


def create_asset_reference(
    db: Session,
    *,
    source_type: str,
    source_id: str,
    target_asset_id: str,
    target_asset_version_id: str,
    relation_type: str,
) -> AssetReference:
    asset = db.get(Asset, target_asset_id)
    version = db.get(AssetVersion, target_asset_version_id)
    if asset is None or version is None or version.asset_id != asset.id:
        raise ValueError("Target asset/version not found")
    existing = db.scalar(
        select(AssetReference).where(
            AssetReference.source_type == source_type,
            AssetReference.source_id == source_id,
            AssetReference.target_asset_id == target_asset_id,
            AssetReference.target_asset_version_id == target_asset_version_id,
        )
    )
    if existing is not None:
        return existing
    reference = AssetReference(
        id=new_id("aref"),
        source_type=source_type,
        source_id=source_id,
        target_asset_id=target_asset_id,
        target_asset_version_id=target_asset_version_id,
        relation_type=relation_type,
        locked=True,
    )
    db.add(reference)
    db.flush()
    return reference


def asset_to_dict(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "description": asset.description,
        "scope": asset.scope,
        "tags": loads_json(asset.tags_json, []),
        "semantic_tags": loads_json(asset.semantic_tags_json, []),
        "latest_version_id": asset.latest_version_id,
        "visibility": asset.visibility,
        "status": asset.status,
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


def asset_version_to_dict(version: AssetVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "asset_id": version.asset_id,
        "version": version.version,
        "artifact_id": version.artifact_id,
        "digest": version.digest,
        "inputs_schema": loads_json(version.inputs_schema_json, {}),
        "outputs_schema": loads_json(version.outputs_schema_json, {}),
        "runtime_requirements": loads_json(version.runtime_requirements_json, {}),
        "created_from_project_id": version.created_from_project_id,
        "created_from_run_id": version.created_from_run_id,
        "status": version.status,
        "created_at": version.created_at.isoformat(),
    }


def asset_reference_to_dict(
    reference: AssetReference,
    *,
    asset: Asset | None = None,
    version: AssetVersion | None = None,
) -> dict[str, Any]:
    return {
        "id": reference.id,
        "source_type": reference.source_type,
        "source_id": reference.source_id,
        "target_asset_id": reference.target_asset_id,
        "target_asset_version_id": reference.target_asset_version_id,
        "relation_type": reference.relation_type,
        "locked": reference.locked,
        "created_at": reference.created_at.isoformat(),
        "asset": asset_to_dict(asset) if asset else None,
        "version": asset_version_to_dict(version) if version else None,
    }
