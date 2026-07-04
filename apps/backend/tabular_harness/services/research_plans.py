from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Project,
    ResearchPlan,
    ResearchPlanRevision,
    utc_now,
)
from tabular_harness.services.artifacts import artifact_primary_path, create_lineage_edge


@dataclass(frozen=True)
class ResearchPlanCommitResult:
    plan: ResearchPlan
    revision: ResearchPlanRevision
    created: bool


def latest_research_plan_revision(db: Session, *, project_id: str) -> ResearchPlanRevision | None:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id))
    if plan is None or not plan.active_revision_id:
        return None
    return db.get(ResearchPlanRevision, plan.active_revision_id)


def commit_research_plan_artifact_revision(
    db: Session,
    *,
    artifact: Artifact,
    reason: str | None = None,
) -> ResearchPlanCommitResult | None:
    if artifact.project_id is None or artifact.asset_type != "research_plan":
        return None
    try:
        document = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return None
    if not isinstance(document, dict):
        return None
    metadata = loads_json(artifact.metadata_json, {})
    source = str(metadata.get("source") or "")
    author_type = "codex" if "codex" in source or "agent_session" in source or "main_agent" in source else "harness"
    return commit_research_plan_revision(
        db,
        project_id=artifact.project_id,
        document=document,
        author_type=author_type,
        reason=reason or f"Committed research_plan artifact {artifact.id}.",
        source_artifact_id=artifact.id,
        metadata={"artifact_name": artifact.name, "artifact_version": artifact.version, "source": source},
    )


def commit_research_plan_revision(
    db: Session,
    *,
    project_id: str,
    document: dict[str, Any],
    author_type: str,
    reason: str,
    source_artifact_id: str | None = None,
    parent_revision_id: str | None = None,
    author_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResearchPlanCommitResult:
    project = db.get(Project, project_id)
    org_id = project.org_id if project is not None else "local-org"
    created_by = project.created_by if project is not None else "local-user"
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id))
    if plan is None:
        plan = ResearchPlan(id=new_id("rplan"), org_id=org_id, project_id=project_id, created_by=created_by)
        db.add(plan)
        db.flush()

    canonical_document = research_plan_document(document)
    document_json = dumps_json(canonical_document)
    document_hash = hashlib.sha256(document_json.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(ResearchPlanRevision).where(
            ResearchPlanRevision.research_plan_id == plan.id,
            ResearchPlanRevision.document_hash == document_hash,
        )
    )
    if existing is not None:
        if plan.active_revision_id is None:
            plan.active_revision_id = existing.id
            plan.updated_at = utc_now()
            db.flush()
        return ResearchPlanCommitResult(plan=plan, revision=existing, created=False)

    current_max = db.scalar(
        select(func.max(ResearchPlanRevision.revision_index)).where(ResearchPlanRevision.research_plan_id == plan.id)
    )
    revision = ResearchPlanRevision(
        id=new_id("rprev"),
        org_id=org_id,
        project_id=project_id,
        research_plan_id=plan.id,
        parent_revision_id=parent_revision_id if parent_revision_id is not None else plan.active_revision_id,
        revision_index=int(current_max or 0) + 1,
        author_type=author_type,
        author_id=author_id,
        reason=reason[:2000],
        document_json=document_json,
        document_hash=document_hash,
        source_artifact_id=source_artifact_id,
        metadata_json=dumps_json(metadata or {}),
    )
    db.add(revision)
    db.flush()
    plan.active_revision_id = revision.id
    plan.updated_at = utc_now()
    if source_artifact_id:
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="artifact",
            from_asset_id=source_artifact_id,
            to_asset_type="research_plan_revision",
            to_asset_id=revision.id,
            relation_type="committed_as",
            metadata={"research_plan_id": plan.id, "revision_index": revision.revision_index},
            org_id=org_id,
        )
    db.flush()
    return ResearchPlanCommitResult(plan=plan, revision=revision, created=True)


def research_plan_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        **document,
        "schema_version": str(document.get("schema_version") or "research_plan.v1"),
    }


def research_plan_revision_document(revision: ResearchPlanRevision) -> dict[str, Any]:
    payload = loads_json(revision.document_json, {})
    return payload if isinstance(payload, dict) else {}
