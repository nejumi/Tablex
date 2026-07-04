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
    LineageEdge,
    Project,
    Question,
    ResearchPlan,
    ResearchPlanCurrentWork,
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


def get_or_create_research_plan(db: Session, *, project_id: str) -> ResearchPlan:
    project = db.get(Project, project_id)
    org_id = project.org_id if project is not None else "local-org"
    created_by = project.created_by if project is not None else "local-user"
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id))
    if plan is None:
        plan = ResearchPlan(id=new_id("rplan"), org_id=org_id, project_id=project_id, created_by=created_by)
        db.add(plan)
        db.flush()
    return plan


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
    plan = get_or_create_research_plan(db, project_id=project_id)

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


def set_research_plan_current_work(
    db: Session,
    *,
    project_id: str,
    node_id: str,
    summary: str,
    status: str = "active",
    expected_outputs: list[str] | None = None,
    revision_id: str | None = None,
    updated_by_type: str = "codex",
    updated_by: str | None = None,
) -> ResearchPlanCurrentWork:
    allowed_statuses = {"active", "pending", "blocked", "waiting", "done", "skipped"}
    if status not in allowed_statuses:
        raise ValueError(f"Unsupported current_work status: {status}")
    cleaned_node_id = node_id.strip()
    if not cleaned_node_id:
        raise ValueError("node_id is required")
    plan = get_or_create_research_plan(db, project_id=project_id)
    revision = db.get(ResearchPlanRevision, revision_id) if revision_id else None
    if revision_id is not None and (revision is None or revision.research_plan_id != plan.id):
        raise ValueError("revision_id does not belong to this project's ResearchPlan")
    if revision is None and plan.active_revision_id:
        revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    current = db.scalar(select(ResearchPlanCurrentWork).where(ResearchPlanCurrentWork.research_plan_id == plan.id))
    if current is None:
        current = ResearchPlanCurrentWork(
            id=new_id("rpcw"),
            org_id=plan.org_id,
            project_id=project_id,
            research_plan_id=plan.id,
        )
        db.add(current)
    current.revision_id = revision.id if revision is not None else None
    current.node_id = cleaned_node_id[:160]
    current.status = status
    current.summary = summary.strip()[:4000]
    current.expected_outputs_json = dumps_json([str(item).strip()[:400] for item in (expected_outputs or [])[:40]])
    current.updated_by_type = updated_by_type.strip()[:80] or "codex"
    current.updated_by = updated_by.strip()[:160] if isinstance(updated_by, str) and updated_by.strip() else None
    current.updated_at = utc_now()
    plan.updated_at = utc_now()
    db.flush()
    return current


def latest_research_plan_current_work(db: Session, *, project_id: str) -> ResearchPlanCurrentWork | None:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id))
    if plan is None:
        return None
    return db.scalar(select(ResearchPlanCurrentWork).where(ResearchPlanCurrentWork.research_plan_id == plan.id))


def research_plan_current_work_payload(current: ResearchPlanCurrentWork | None) -> dict[str, Any] | None:
    if current is None:
        return None
    expected_outputs = loads_json(current.expected_outputs_json, [])
    return {
        "id": current.id,
        "project_id": current.project_id,
        "research_plan_id": current.research_plan_id,
        "revision_id": current.revision_id,
        "node_id": current.node_id,
        "status": current.status,
        "summary": current.summary,
        "expected_outputs": expected_outputs if isinstance(expected_outputs, list) else [],
        "updated_by_type": current.updated_by_type,
        "updated_by": current.updated_by,
        "updated_at": current.updated_at.isoformat(),
    }


def attach_research_plan_artifact(
    db: Session,
    *,
    project_id: str,
    node_id: str,
    artifact_id: str,
    role: str = "evidence",
    revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> LineageEdge:
    cleaned_node_id = node_id.strip()
    if not cleaned_node_id:
        raise ValueError("node_id is required")
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise ValueError("artifact_id does not belong to this project")
    plan = get_or_create_research_plan(db, project_id=project_id)
    revision = db.get(ResearchPlanRevision, revision_id) if revision_id else None
    if revision_id is not None and (revision is None or revision.research_plan_id != plan.id):
        raise ValueError("revision_id does not belong to this project's ResearchPlan")
    if revision is None and plan.active_revision_id:
        revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    if revision is None:
        raise ValueError("ResearchPlan revision is required before attaching artifacts")
    edge_metadata = {
        **(metadata or {}),
        "research_plan_id": plan.id,
        "revision_id": revision.id,
        "node_id": cleaned_node_id[:160],
        "role": role.strip()[:80] or "evidence",
    }
    edge = create_lineage_edge(
        db,
        project_id=project_id,
        from_asset_type="research_plan_revision",
        from_asset_id=revision.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="supports_plan_node",
        metadata=edge_metadata,
        org_id=plan.org_id,
    )
    plan.updated_at = utc_now()
    db.flush()
    return edge


def research_plan_artifact_links(
    db: Session,
    *,
    revision: ResearchPlanRevision | None,
) -> list[dict[str, Any]]:
    if revision is None:
        return []
    edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == revision.project_id,
                LineageEdge.from_asset_type == "research_plan_revision",
                LineageEdge.from_asset_id == revision.id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.asc())
        ).all()
    )
    artifact_ids = [edge.to_asset_id for edge in edges]
    artifacts = {
        artifact.id: artifact
        for artifact in db.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all()
    } if artifact_ids else {}
    links: list[dict[str, Any]] = []
    for edge in edges:
        metadata = loads_json(edge.metadata_json, {})
        artifact = artifacts.get(edge.to_asset_id)
        links.append(
            {
                "id": edge.id,
                "revision_id": revision.id,
                "node_id": str(metadata.get("node_id") or ""),
                "role": str(metadata.get("role") or "evidence"),
                "artifact_id": edge.to_asset_id,
                "artifact_name": artifact.name if artifact is not None else None,
                "asset_type": artifact.asset_type if artifact is not None else None,
                "artifact_version": artifact.version if artifact is not None else None,
                "metadata": metadata if isinstance(metadata, dict) else {},
                "created_at": edge.created_at.isoformat(),
            }
        )
    return links


def request_research_plan_human_attention(
    db: Session,
    *,
    project_id: str,
    question: str,
    why_it_matters: str,
    node_id: str | None = None,
    provisional_assumption: str | None = None,
    impact_if_wrong: str | None = None,
    urgency: str = "medium",
    fallback_policy: str = "infer_and_continue",
    blocks_next_phase: bool = False,
    revision_id: str | None = None,
) -> Question:
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("question is required")
    plan = get_or_create_research_plan(db, project_id=project_id)
    revision = db.get(ResearchPlanRevision, revision_id) if revision_id else None
    if revision_id is not None and (revision is None or revision.research_plan_id != plan.id):
        raise ValueError("revision_id does not belong to this project's ResearchPlan")
    if revision is None and plan.active_revision_id:
        revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    priority_by_urgency = {"low": 35, "medium": 55, "high": 75, "critical": 90}
    risk_by_urgency = {"low": "low", "medium": "medium", "high": "high", "critical": "high"}
    cleaned_urgency = urgency if urgency in priority_by_urgency else "medium"
    attention = Question(
        id=new_id("q"),
        project_id=project_id,
        question_set_id=f"research_plan_{plan.id}",
        topic="research_plan",
        question=cleaned_question[:4000],
        why_it_matters=why_it_matters.strip()[:4000],
        default_assumption=provisional_assumption.strip()[:4000]
        if isinstance(provisional_assumption, str) and provisional_assumption.strip()
        else None,
        impact_if_wrong=impact_if_wrong.strip()[:4000]
        if isinstance(impact_if_wrong, str) and impact_if_wrong.strip()
        else None,
        choices_json="[]",
        status="open",
        priority=priority_by_urgency[cleaned_urgency],
        risk_level=risk_by_urgency[cleaned_urgency],
        value_of_answer=cleaned_urgency,
        can_proceed_without_answer=not blocks_next_phase,
        fallback_policy=fallback_policy.strip()[:120] or "infer_and_continue",
        blocks_next_phase=blocks_next_phase,
    )
    db.add(attention)
    db.flush()
    if revision is not None:
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="research_plan_revision",
            from_asset_id=revision.id,
            to_asset_type="question",
            to_asset_id=attention.id,
            relation_type="requests_human_attention",
            metadata={
                "research_plan_id": plan.id,
                "revision_id": revision.id,
                "node_id": node_id.strip()[:160] if isinstance(node_id, str) and node_id.strip() else None,
                "urgency": cleaned_urgency,
            },
            org_id=plan.org_id,
        )
    plan.updated_at = utc_now()
    db.flush()
    return attention


def research_plan_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        **document,
        "schema_version": str(document.get("schema_version") or "research_plan.v1"),
    }


def research_plan_revision_document(revision: ResearchPlanRevision) -> dict[str, Any]:
    payload = loads_json(revision.document_json, {})
    return payload if isinstance(payload, dict) else {}
