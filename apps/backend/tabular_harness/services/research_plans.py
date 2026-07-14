from __future__ import annotations

import ast
import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    ExperimentRun,
    LineageEdge,
    Project,
    Question,
    Report,
    ResearchPlan,
    ResearchPlanCurrentWork,
    ResearchPlanRevision,
    User,
    utc_now,
)
from tabular_harness.services.artifacts import artifact_primary_path, create_lineage_edge
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.prediction_pipeline_contract import (
    leaderboard_ready_pipeline_artifact,
)


@dataclass(frozen=True)
class ResearchPlanCommitResult:
    plan: ResearchPlan
    revision: ResearchPlanRevision
    created: bool


class ResearchPlanValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        errors = [issue for issue in issues if issue.get("severity", "error") == "error"]
        summary = "; ".join(str(issue.get("message") or issue.get("code") or "invalid") for issue in errors[:4])
        super().__init__(f"ResearchPlan document rejected: {summary}")


PLAN_BLOCK_STATUSES = {"done", "active", "pending", "blocked", "waiting", "skipped"}
PLAN_TERMINAL_STATUSES = {"done", "skipped"}
PLAN_CURRENT_STATUSES = {"active", "blocked", "waiting"}
PLAN_TOP_LEVEL_GRANULARITIES = {"chapter", "phase", "milestone"}
PLAN_MAX_TOP_LEVEL_BLOCKS = 7
PLAN_TOO_FINE_GRANULARITIES = {
    "analysis",
    "check",
    "diagnostic",
    "experiment",
    "model",
    "model_attempt",
    "notebook",
    "report",
    "run",
    "step",
    "subtask",
    "task",
}
PLAN_NOTEBOOK_ASSET_TYPES = {
    "analysis_notebook",
    "marimo_notebook",
}
PLAN_DISPLAY_TITLE_FIELDS = ("title",)
PLAN_DISPLAY_DETAIL_FIELDS = (
    "detail",
    "subtitle",
    "summary",
    "description",
    "why_it_matters",
    "next_action",
    "notes",
    "done_criteria",
)
STATIC_NOTEBOOK_HTML_ASSET_TYPES = {"notebook_html", "notebook_execution_html", "notebook_evidence_html"}
PLAN_REPORT_ASSET_TYPES = {
    "agent_session_report",
    "analysis_report",
    "report",
}
PLAN_FIGURE_ASSET_TYPES = {"agent_session_figure", "visualization", "visualization_spec"}
HARNESS_RESEARCH_PLAN_BOOTSTRAP_SOURCES = {
    "harness_initial_research_plan",
    "harness_dataset_upload",
    "harness_objective_framing",
}
_MISSING = object()


def latest_research_plan_revision(db: Session, *, project_id: str) -> ResearchPlanRevision | None:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id))
    if plan is None or not plan.active_revision_id:
        return None
    active = db.get(ResearchPlanRevision, plan.active_revision_id)
    if active is None or not research_plan_revision_is_invalid_harness_artifact(active):
        return active
    revisions = list(
        db.scalars(
            select(ResearchPlanRevision)
            .where(ResearchPlanRevision.research_plan_id == plan.id)
            .order_by(ResearchPlanRevision.revision_index.desc())
        ).all()
    )
    fallback = next(
        (revision for revision in revisions if not research_plan_revision_is_invalid_harness_artifact(revision)),
        None,
    )
    if fallback is None:
        return active
    plan.active_revision_id = fallback.id
    plan.updated_at = utc_now()
    db.flush()
    return fallback


def research_plan_revision_is_invalid_harness_artifact(revision: ResearchPlanRevision) -> bool:
    if revision.author_type != "harness" or revision.source_artifact_id is None:
        return False
    document = research_plan_revision_document(revision)
    timeline_blocks = document.get("timeline_blocks")
    if not isinstance(timeline_blocks, list) or not timeline_blocks:
        return True
    metadata = loads_json(revision.metadata_json, {})
    issues = metadata.get("validation_issues")
    return isinstance(issues, list) and any(
        isinstance(issue, dict) and issue.get("severity", "error") == "error"
        for issue in issues
    )


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


def ensure_harness_initial_research_plan_revision(db: Session, *, project_id: str) -> ResearchPlanRevision:
    existing = latest_research_plan_revision(db, project_id=project_id)
    if existing is not None:
        return existing
    result = commit_research_plan_revision(
        db,
        project_id=project_id,
        document=harness_initial_research_plan_document(project_id=project_id),
        author_type="harness",
        reason="Initialize the harness-owned ResearchPlan anchors.",
        metadata={"source": "harness_initial_research_plan"},
        strict_validation=True,
    )
    return result.revision


def harness_initial_research_plan_document(*, project_id: str) -> dict[str, Any]:
    return {
        "schema_version": "research_plan.v2",
        "project_id": project_id,
        "timeline_blocks": [
            {
                "id": "data_upload",
                "title": "Data upload",
                "subtitle": "Upload one or more tables and optional relationship evidence.",
                "granularity": "chapter",
                "status": "active",
                "target_tab": "Data",
                "target_anchor": "dataset-upload",
                "localizations": {
                    "ja-JP": {
                        "title": "データアップロード",
                        "subtitle": "1つ以上のテーブルと、必要に応じて関係性の根拠をアップロードします。",
                    }
                },
            },
            {
                "id": "objective_framing",
                "title": "Objective and task framing",
                "subtitle": "Define the prediction, optimization, or analysis objective after seeing the data when needed.",
                "granularity": "chapter",
                "status": "pending",
                "target_tab": "Assumptions",
                "target_anchor": "assumption-review",
                "localizations": {
                    "ja-JP": {
                        "title": "目的設定",
                        "subtitle": "必要ならデータを見た後で、予測・最適化・分析の目的を定義します。",
                    }
                },
            },
            {
                "id": "data_understanding",
                "title": "Data understanding",
                "subtitle": "Understand row semantics, relationships, missingness, leakage risk, and useful hypotheses before modeling.",
                "granularity": "chapter",
                "status": "pending",
                "target_tab": "Data",
                "target_anchor": "data-focus",
                "deliverable_contract": {"expected_outputs": ["notebook"]},
                "localizations": {
                    "ja-JP": {
                        "title": "データ理解",
                        "subtitle": "モデリング前に、行の意味、関係構造、欠損、漏洩リスク、有用な仮説を理解します。",
                    }
                },
            },
            {
                "id": "prior_knowledge_research",
                "title": "Prior knowledge research",
                "subtitle": "Collect relevant domain, Kaggle, literature, and Skill context when it can improve the project.",
                "granularity": "chapter",
                "status": "pending",
                "target_tab": "Insight",
                "target_anchor": "insights",
                "deliverable_contract": {"expected_outputs": ["research_findings"]},
                "localizations": {
                    "ja-JP": {
                        "title": "従来知見の調査",
                        "subtitle": "プロジェクトに役立つ場合、ドメイン、Kaggle、文献、Skillの文脈を集めます。",
                    }
                },
            },
        ],
    }


def record_harness_dataset_upload_in_research_plan(
    db: Session,
    *,
    project_id: str,
    artifact_ids: list[str],
    dataset_snapshot_id: str | None = None,
    primary_artifact_id: str | None = None,
) -> ResearchPlanRevision | None:
    revision = ensure_harness_initial_research_plan_revision(db, project_id=project_id)
    if not research_plan_revision_is_harness_bootstrap(revision):
        return None
    verified_artifacts = research_plan_verified_project_artifacts(
        db,
        project_id=project_id,
        artifact_ids=artifact_ids,
    )
    if not verified_artifacts:
        return None

    document = copy.deepcopy(research_plan_revision_document(revision))
    raw_blocks = document.get("timeline_blocks")
    if not isinstance(raw_blocks, list):
        document = harness_initial_research_plan_document(project_id=project_id)
        raw_blocks = document["timeline_blocks"]
    blocks = [block for block in raw_blocks if isinstance(block, dict)]
    block_by_id = {str(block.get("id") or "").strip(): block for block in blocks}
    data_upload = block_by_id.get("data_upload")
    if data_upload is None:
        return None

    data_upload["status"] = "done"
    data_upload["subtitle"] = "Uploaded data is registered as Tablex artifacts."
    data_upload["target_tab"] = "Data"
    data_upload["target_anchor"] = "dataset-upload"
    data_upload["deliverable_contract"] = {"expected_outputs": ["artifact"]}
    data_upload["completion_evidence"] = [
        {
            "output_type": "artifact",
            "artifact_id": artifact.id,
            "role": "primary_dataset" if primary_artifact_id and artifact.id == primary_artifact_id else artifact.asset_type,
        }
        for artifact in verified_artifacts
    ]
    data_upload.setdefault("localizations", {})
    localizations = data_upload["localizations"] if isinstance(data_upload["localizations"], dict) else {}
    localizations["ja-JP"] = {
        **(localizations.get("ja-JP") if isinstance(localizations.get("ja-JP"), dict) else {}),
        "title": "データアップロード",
        "subtitle": "アップロード済みデータはTablex artifactとして登録されています。",
    }
    data_upload["localizations"] = localizations

    if not any(research_plan_block_status(block) in PLAN_CURRENT_STATUSES for block in blocks):
        first_open = next((block for block in blocks if research_plan_block_status(block) not in PLAN_TERMINAL_STATUSES), None)
        if first_open is not None:
            first_open["status"] = "active"
    elif research_plan_block_status(data_upload) in PLAN_CURRENT_STATUSES:
        for block in blocks:
            if block is data_upload:
                continue
            if research_plan_block_status(block) not in PLAN_TERMINAL_STATUSES:
                block["status"] = "active"
                break

    result = commit_research_plan_revision(
        db,
        project_id=project_id,
        document=document,
        author_type="harness",
        reason="Record uploaded dataset artifacts in the harness-owned ResearchPlan.",
        metadata={
            "source": "harness_dataset_upload",
            "dataset_snapshot_id": dataset_snapshot_id,
            "artifact_ids": [artifact.id for artifact in verified_artifacts],
        },
        strict_validation=True,
    )
    return result.revision


def record_harness_objective_in_research_plan(
    db: Session,
    *,
    project_id: str,
    objective_label: str | None,
) -> ResearchPlanRevision | None:
    cleaned_objective = objective_label.strip() if isinstance(objective_label, str) and objective_label.strip() else None
    if not cleaned_objective:
        return None
    revision = ensure_harness_initial_research_plan_revision(db, project_id=project_id)
    if not research_plan_revision_is_harness_bootstrap(revision):
        return None

    document = copy.deepcopy(research_plan_revision_document(revision))
    raw_blocks = document.get("timeline_blocks")
    if not isinstance(raw_blocks, list):
        document = harness_initial_research_plan_document(project_id=project_id)
        raw_blocks = document["timeline_blocks"]
    blocks = [block for block in raw_blocks if isinstance(block, dict)]
    block_by_id = {str(block.get("id") or "").strip(): block for block in blocks}
    objective = block_by_id.get("objective_framing")
    if objective is None:
        return None

    objective_index = blocks.index(objective)
    for prior_block in blocks[:objective_index]:
        if research_plan_block_status(prior_block) not in PLAN_TERMINAL_STATUSES:
            return None

    objective["status"] = "done"
    objective["subtitle"] = f"Current objective is {cleaned_objective}."
    objective["target_tab"] = "Home"
    objective["target_anchor"] = "research-plan"
    objective["no_output_required"] = True
    objective["no_output_required_rationale"] = "The structured project objective is stored on the Project record."
    objective["completion_evidence"] = [
        {
            "output_type": "project_setting",
            "role": "project_objective",
            "project_field": "target_column",
            "value": cleaned_objective,
        }
    ]
    objective.setdefault("localizations", {})
    localizations = objective["localizations"] if isinstance(objective["localizations"], dict) else {}
    localizations["ja-JP"] = {
        **(localizations.get("ja-JP") if isinstance(localizations.get("ja-JP"), dict) else {}),
        "title": "目的設定",
        "subtitle": f"現在の目的: {cleaned_objective}",
    }
    objective["localizations"] = localizations

    for block in blocks[objective_index + 1 :]:
        if research_plan_block_status(block) not in PLAN_TERMINAL_STATUSES:
            block["status"] = "active"
            break

    result = commit_research_plan_revision(
        db,
        project_id=project_id,
        document=document,
        author_type="harness",
        reason="Record the structured project objective in the harness-owned ResearchPlan.",
        metadata={"source": "harness_objective_framing", "objective_label": cleaned_objective},
        strict_validation=True,
    )
    return result.revision


def research_plan_revision_is_harness_bootstrap(revision: ResearchPlanRevision) -> bool:
    metadata = loads_json(revision.metadata_json, {})
    return revision.author_type == "harness" and metadata.get("source") in HARNESS_RESEARCH_PLAN_BOOTSTRAP_SOURCES


def research_plan_verified_project_artifacts(
    db: Session,
    *,
    project_id: str,
    artifact_ids: list[str],
) -> list[Artifact]:
    verified: list[Artifact] = []
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in seen:
            continue
        artifact = db.get(Artifact, artifact_id.strip())
        if artifact is None or artifact.project_id != project_id:
            continue
        verified.append(artifact)
        seen.add(artifact.id)
    return verified


def commit_research_plan_artifact_revision(
    db: Session,
    *,
    artifact: Artifact,
    reason: str | None = None,
    strict_validation: bool = False,
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
    try:
        return commit_research_plan_revision(
            db,
            project_id=artifact.project_id,
            document=document,
            author_type=author_type,
            reason=reason or f"Committed research_plan artifact {artifact.id}.",
            source_artifact_id=artifact.id,
            metadata={"artifact_name": artifact.name, "artifact_version": artifact.version, "source": source},
            strict_validation=strict_validation or author_type == "harness",
        )
    except ResearchPlanValidationError:
        if author_type != "harness":
            raise
        return None


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
    strict_validation: bool = False,
) -> ResearchPlanCommitResult:
    project = db.get(Project, project_id)
    org_id = project.org_id if project is not None else "local-org"
    plan = get_or_create_research_plan(db, project_id=project_id)

    canonical_document = research_plan_document(document)
    validation_issues = validate_research_plan_document(
        db,
        project_id=project_id,
        document=canonical_document,
        strict=strict_validation,
    )
    validation_errors = [issue for issue in validation_issues if issue.get("severity", "error") == "error"]
    if validation_errors and strict_validation:
        raise ResearchPlanValidationError(validation_issues)
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
        metadata_json=dumps_json({**(metadata or {}), "validation_issues": validation_issues}),
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
    allowed_statuses = PLAN_CURRENT_STATUSES
    if status not in allowed_statuses:
        raise ValueError(
            f"Unsupported current_work status: {status}. "
            "current_work represents live presence and must be active, waiting, or blocked. "
            "Use commit_revision to mark plan nodes pending, done, or skipped."
        )
    cleaned_node_id = node_id.strip()
    if not cleaned_node_id:
        raise ValueError("node_id is required")
    cleaned_summary = summary.strip()
    if not cleaned_summary:
        raise ValueError(
            "current_work.summary is required. "
            "Describe the active work briefly so the visible plan can show what Codex is doing."
        )
    plan = get_or_create_research_plan(db, project_id=project_id)
    revision = db.get(ResearchPlanRevision, revision_id) if revision_id else None
    if revision_id is not None and (revision is None or revision.research_plan_id != plan.id):
        raise ValueError("revision_id does not belong to this project's ResearchPlan")
    if revision is None and plan.active_revision_id:
        revision = db.get(ResearchPlanRevision, plan.active_revision_id)
    validate_research_plan_current_work_target(revision, node_id=cleaned_node_id, status=status)
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
    current.summary = cleaned_summary[:4000]
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
    validate_research_plan_node_exists(revision, node_id=cleaned_node_id)
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
                LineageEdge.to_asset_type.in_(("artifact", "experiment_run")),
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.asc())
        ).all()
    )
    artifact_ids = list(dict.fromkeys(edge.to_asset_id for edge in edges if edge.to_asset_type == "artifact"))
    artifacts: dict[str, Artifact] = {}
    for chunk in _research_plan_link_id_chunks(artifact_ids):
        artifacts.update({artifact.id: artifact for artifact in db.scalars(select(Artifact).where(Artifact.id.in_(chunk))).all()})
    run_ids = list(dict.fromkeys(edge.to_asset_id for edge in edges if edge.to_asset_type == "experiment_run"))
    runs: dict[str, ExperimentRun] = {}
    for chunk in _research_plan_link_id_chunks(run_ids):
        runs.update({run.id: run for run in db.scalars(select(ExperimentRun).where(ExperimentRun.id.in_(chunk))).all()})
    links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, str, str]] = set()
    for edge in edges:
        metadata = loads_json(edge.metadata_json, {})
        node_id = str(metadata.get("node_id") or "")
        role = str(metadata.get("role") or "experiment_run")
        if edge.to_asset_type == "experiment_run":
            run = runs.get(edge.to_asset_id)
            params = loads_json(run.params_json, {}) if run is not None else {}
            leaderboard_ready = (
                run is not None
                and leaderboard_ready_pipeline_artifact(db, run, params=params) is not None
            )
            model_id = params.get("model_id") if isinstance(params, dict) else None
            link_key = ("experiment_run", node_id, edge.to_asset_id, role)
            if link_key in seen_links:
                continue
            seen_links.add(link_key)
            links.append(
                {
                    "id": edge.id,
                    "link_type": "experiment_run",
                    "revision_id": revision.id,
                    "node_id": node_id,
                    "role": role,
                    "run_id": edge.to_asset_id,
                    "artifact_id": None,
                    "artifact_name": f"{model_id} · {edge.to_asset_id}" if isinstance(model_id, str) and model_id.strip() else edge.to_asset_id,
                    "asset_type": "experiment_run",
                    "artifact_version": None,
                    "target_tab": "Leaderboard" if leaderboard_ready else "Experiments",
                    "target_anchor": "result-readout" if leaderboard_ready else "experiment-history",
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "created_at": edge.created_at.isoformat(),
                }
            )
        else:
            raw_artifact = artifacts.get(edge.to_asset_id)
            artifact = research_plan_visible_artifact_for_link(db, raw_artifact)
            if artifact is None:
                continue
            role = str(metadata.get("role") or "evidence")
            link_key = ("artifact", node_id, artifact.id, role)
            if link_key in seen_links:
                continue
            seen_links.add(link_key)
            links.append(
                {
                    "id": edge.id,
                    "link_type": "artifact",
                    "revision_id": revision.id,
                    "node_id": node_id,
                    "role": role,
                    "artifact_id": artifact.id,
                    "artifact_name": artifact.name,
                    "asset_type": artifact.asset_type,
                    "artifact_version": artifact.version,
                    **research_plan_artifact_surface_target(artifact, role=role),
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "created_at": edge.created_at.isoformat(),
                }
            )
    return links


def _research_plan_link_id_chunks(ids: list[str], chunk_size: int = 500) -> list[list[str]]:
    return [ids[index : index + chunk_size] for index in range(0, len(ids), chunk_size)]


def research_plan_visible_artifact_for_link(db: Session, artifact: Artifact | None) -> Artifact | None:
    if artifact is None:
        return None
    if artifact.asset_type not in STATIC_NOTEBOOK_HTML_ASSET_TYPES:
        return artifact
    metadata = loads_json(artifact.metadata_json, {})
    for key in ("notebook_artifact_id", "analysis_notebook_artifact_id", "source_notebook_artifact_id"):
        source_id = metadata.get(key)
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        source = db.get(Artifact, source_id)
        if (
            source is not None
            and source.project_id == artifact.project_id
            and source.asset_type in PLAN_NOTEBOOK_ASSET_TYPES
            and research_plan_artifact_is_native_marimo_source(source)
        ):
            return source
    return None


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


def validate_research_plan_document(
    db: Session,
    *,
    project_id: str,
    document: dict[str, Any],
    strict: bool = False,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    raw_blocks = document.get("timeline_blocks")
    if raw_blocks is None:
        if strict:
            issues.append(
                research_plan_issue(
                    "missing_timeline_blocks",
                    "/timeline_blocks",
                    "timeline_blocks is required for ResearchPlan tool commits.",
                    "Submit a document with timeline_blocks so Tablex can display and validate the plan.",
                )
            )
        return issues
    if not isinstance(raw_blocks, list):
        issues.append(
            research_plan_issue(
                "invalid_timeline_blocks",
                "/timeline_blocks",
                "timeline_blocks must be an array.",
                "Use an ordered array of ResearchPlan nodes.",
            )
        )
        return issues

    blocks = [block for block in raw_blocks if isinstance(block, dict)]
    required_display_locale = research_plan_required_explicit_display_locale(
        db,
        project_id=project_id,
        document=document,
    ) if strict else None
    if strict and len(blocks) > PLAN_MAX_TOP_LEVEL_BLOCKS:
        issues.append(
            research_plan_issue(
                "top_level_plan_too_granular",
                "/timeline_blocks",
                f"The plan has {len(blocks)} top-level nodes; the main ResearchPlan allows at most {PLAN_MAX_TOP_LEVEL_BLOCKS}.",
                "Keep the top-level plan chapter-like. Put individual analyses, model attempts, diagnostics, and report sections under subtasks, ExperimentRuns, notebooks, or reports.",
            )
        )
    seen_ids: set[str] = set()
    current_count = 0
    first_open: tuple[int, str, str] | None = None
    seen_pending: tuple[int, str, str] | None = None
    for index, block in enumerate(blocks):
        path = f"/timeline_blocks/{index}"
        block_id = research_plan_block_id(block, index)
        status = research_plan_block_status(block)
        granularity = research_plan_block_granularity(block)
        if required_display_locale:
            issues.extend(
                research_plan_locale_display_issues(
                    block,
                    locale=required_display_locale,
                    path=path,
                    node_id=block_id,
                )
            )
            subtasks = block.get("subtasks")
            if isinstance(subtasks, list):
                for subtask_index, subtask in enumerate(subtasks):
                    if not isinstance(subtask, dict):
                        continue
                    subtask_id = str(subtask.get("id") or f"subtask_{subtask_index + 1}")
                    issues.extend(
                        research_plan_locale_display_issues(
                            subtask,
                            locale=required_display_locale,
                            path=f"{path}/subtasks/{subtask_index}",
                            node_id=f"{block_id}/{subtask_id}",
                        )
                    )
        if strict and granularity:
            if granularity in PLAN_TOO_FINE_GRANULARITIES:
                issues.append(
                    research_plan_issue(
                        "top_level_node_granularity_too_fine",
                        f"{path}/granularity",
                        f"Top-level node `{block_id}` declares granularity `{granularity}`, which is too fine for the main ResearchPlan.",
                        "Keep top-level nodes chapter-like. Put individual analyses, diagnostics, model attempts, notebooks, and reports under subtasks, ExperimentRuns, artifacts, or deliverable evidence.",
                    )
                )
            elif granularity not in PLAN_TOP_LEVEL_GRANULARITIES:
                issues.append(
                    research_plan_issue(
                        "unsupported_top_level_granularity",
                        f"{path}/granularity",
                        f"Top-level node `{block_id}` declares unsupported granularity `{granularity}`.",
                        f"Use one of: {', '.join(sorted(PLAN_TOP_LEVEL_GRANULARITIES))}.",
                    )
                )
        elif strict:
            issues.append(
                research_plan_issue(
                    "top_level_granularity_missing",
                    f"{path}/granularity",
                    f"Top-level node `{block_id}` does not declare its granularity.",
                    "Set granularity to chapter, phase, or milestone. Keep detailed work in subtasks and artifacts.",
                )
            )
        if block_id in seen_ids:
            issues.append(
                research_plan_issue(
                    "duplicate_node_id",
                    f"{path}/id",
                    f"ResearchPlan node id `{block_id}` appears more than once.",
                    "Keep node ids stable and unique; create a new id when the work is genuinely different.",
                )
            )
        seen_ids.add(block_id)
        if status not in PLAN_BLOCK_STATUSES:
            issues.append(
                research_plan_issue(
                    "invalid_status",
                    f"{path}/status",
                    f"Unsupported ResearchPlan status `{status}`.",
                    f"Use one of: {', '.join(sorted(PLAN_BLOCK_STATUSES))}.",
                )
            )
            continue
        if status in PLAN_CURRENT_STATUSES:
            current_count += 1
            if seen_pending is not None:
                prior_index, prior_id, prior_status = seen_pending
                issues.append(
                    research_plan_issue(
                        "active_after_pending_predecessor",
                        f"{path}/status",
                        f"Node `{block_id}` is {status}, but earlier node `{prior_id}` at position {prior_index + 1} is still {prior_status}.",
                        "Revise the earlier node to done/skipped with evidence, or make that earlier node the current work.",
                    )
                )
        if status in PLAN_TERMINAL_STATUSES and first_open is not None:
            prior_index, prior_id, prior_status = first_open
            issues.append(
                research_plan_issue(
                    "completed_after_open_predecessor",
                    f"{path}/status",
                    f"Node `{block_id}` is {status}, but earlier node `{prior_id}` at position {prior_index + 1} is still {prior_status}.",
                    "Keep the visible timeline left-to-right: finish or explicitly skip earlier nodes before marking later nodes done.",
                )
            )
        if status in PLAN_TERMINAL_STATUSES:
            if (
                strict
                and status == "done"
                and block.get("no_output_required") is not True
                and not isinstance(block.get("deliverable_contract"), dict)
            ):
                issues.append(
                    research_plan_issue(
                        "done_node_missing_deliverable_contract",
                        f"{path}/deliverable_contract",
                        f"Node `{block_id}` is done without a deliverable_contract.",
                        "Declare the expected output classes in deliverable_contract.expected_outputs so Tablex can verify notebook, report, experiment, leaderboard, or no-output decisions without reading the title.",
                    )
                )
            if status == "done" and not research_plan_block_has_completion_evidence(block):
                issues.append(
                    research_plan_issue(
                        "done_node_missing_completion_evidence",
                        f"{path}/completion_evidence",
                        f"Node `{block_id}` is done, but no structured completion evidence is attached.",
                        "Attach completion_evidence or supporting_artifacts, or set no_output_required with a rationale when no artifact is appropriate.",
                    )
                )
            if status == "done":
                missing_deliverables = missing_research_plan_deliverables(block)
                if missing_deliverables:
                    issues.append(
                        research_plan_issue(
                            "done_node_missing_contract_deliverables",
                            f"{path}/deliverable_contract/expected_outputs",
                            f"Node `{block_id}` is done, but completion evidence does not satisfy expected output(s): {', '.join(missing_deliverables[:6])}.",
                            "Attach evidence with matching output_type/type/role/asset_type, or revise the deliverable_contract before marking the node done.",
                        )
                    )
                if strict:
                    incomplete_pipeline_run_ids = research_plan_incomplete_pipeline_run_ids(
                        db,
                        project_id=project_id,
                        block=block,
                    )
                    if incomplete_pipeline_run_ids:
                        issues.append(
                            research_plan_issue(
                                "done_node_incomplete_prediction_pipelines",
                                f"{path}/completion_evidence",
                                f"Node `{block_id}` references model run(s) without prediction-enabled runtimes: {', '.join(incomplete_pipeline_run_ids[:6])}.",
                                "Create and register one smoke-validated model-specific prediction runtime per run before marking the node done. A complete downloadable training bundle is not required. Do not remove model evidence to bypass this requirement.",
                            )
                        )
                    missing_registered_deliverables = missing_registered_research_plan_deliverables(
                        db,
                        project_id=project_id,
                        block=block,
                    )
                    if missing_registered_deliverables:
                        issues.append(
                            research_plan_issue(
                                "done_node_missing_registered_deliverables",
                                f"{path}/completion_evidence",
                                f"Node `{block_id}` is done, but the expected output(s) are not linked to registered Tablex assets or runs: {', '.join(missing_registered_deliverables[:6])}.",
                                "For notebooks/reports/artifacts, reference a registered artifact_id or a workspace_path that Tablex has already ingested. For model results/leaderboard entries, reference an experiment_run_id registered through the experiment result tool.",
                            )
                        )
            if status == "skipped" and not research_plan_block_has_skip_reason(block):
                issues.append(
                    research_plan_issue(
                        "skipped_node_missing_reason",
                        f"{path}/skip_reason",
                        f"Node `{block_id}` is skipped, but no skip reason is recorded.",
                        "Add skip_reason or no_output_required_rationale so the user can understand why the node was skipped.",
                    )
                )
            supporting_artifacts = block.get("supporting_artifacts")
            if isinstance(supporting_artifacts, list):
                missing = [
                    str(item.get("path") or item.get("artifact_id") or index)
                    for index, item in enumerate(supporting_artifacts)
                    if isinstance(item, dict) and item.get("exists") is False
                ]
                if missing:
                    issues.append(
                        research_plan_issue(
                            "completed_node_has_missing_artifacts",
                            f"{path}/supporting_artifacts",
                            f"Node `{block_id}` is {status}, but declared supporting artifact(s) are missing: {', '.join(missing[:4])}.",
                            "Register or attach the artifact first, or leave the node pending/active until the evidence exists.",
                        )
                    )
        elif first_open is None:
            first_open = (index, block_id, status)
        if status == "pending" and seen_pending is None:
            seen_pending = (index, block_id, status)
    if current_count > 1:
        issues.append(
            research_plan_issue(
                "multiple_current_nodes",
                "/timeline_blocks",
                f"{current_count} ResearchPlan nodes are active/waiting/blocked.",
                "Keep the top-level timeline to one current node; put parallel work under subtasks or child agents.",
            )
        )
    if strict and current_count == 0 and any(research_plan_block_status(block) not in PLAN_TERMINAL_STATUSES for block in blocks):
        issues.append(
            research_plan_issue(
                "missing_current_node",
                "/timeline_blocks",
                "The ResearchPlan has open top-level work but no active/waiting/blocked current node.",
                "Mark exactly one open top-level node active, waiting, or blocked so the UI always shows where Codex is working.",
            )
        )

    previous_revision = latest_research_plan_revision(db, project_id=project_id)
    if previous_revision is not None:
        previous_document = research_plan_revision_document(previous_revision)
        previous_blocks = previous_document.get("timeline_blocks") if isinstance(previous_document, dict) else None
        if isinstance(previous_blocks, list):
            current_by_id = {
                research_plan_block_id(block, index): block
                for index, block in enumerate(blocks)
                if isinstance(block, dict)
            }
            current_index_by_id = {
                research_plan_block_id(block, index): index
                for index, block in enumerate(blocks)
                if isinstance(block, dict)
            }
            for previous_index, previous_block in enumerate(previous_blocks):
                if not isinstance(previous_block, dict):
                    continue
                previous_id = research_plan_block_id(previous_block, previous_index)
                previous_status = research_plan_block_status(previous_block)
                if previous_status not in PLAN_TERMINAL_STATUSES:
                    continue
                current_block = current_by_id.get(previous_id)
                if current_block is None:
                    issues.append(
                        research_plan_issue(
                            "completed_node_removed",
                            "/timeline_blocks",
                            f"Previously completed node `{previous_id}` was removed.",
                            "ResearchPlan history is append-only for completed work. Keep the node and add a superseding node or note.",
                        )
                    )
                    continue
                current_status = research_plan_block_status(current_block)
                if current_status not in PLAN_TERMINAL_STATUSES:
                    issues.append(
                        research_plan_issue(
                            "completed_node_reopened",
                            "/timeline_blocks",
                            f"Previously completed node `{previous_id}` was changed from {previous_status} to {current_status}.",
                            "Do not reopen completed nodes. Add a new follow-up node if more work is needed.",
                        )
                    )
                current_index = current_index_by_id.get(previous_id, 0)
                if research_plan_has_display_text(
                    previous_block,
                    PLAN_DISPLAY_TITLE_FIELDS,
                ) and not research_plan_has_display_text(current_block, PLAN_DISPLAY_TITLE_FIELDS):
                    issues.append(
                        research_plan_issue(
                            "completed_node_title_erased",
                            f"/timeline_blocks/{current_index}/title",
                            f"Previously completed node `{previous_id}` had a display title, but the new revision removes it.",
                            "Keep completed node display titles non-empty. Add a superseding node if the wording needs to change.",
                        )
                    )
                if research_plan_has_display_text(
                    previous_block,
                    PLAN_DISPLAY_DETAIL_FIELDS,
                ) and not research_plan_has_display_text(current_block, PLAN_DISPLAY_DETAIL_FIELDS):
                    issues.append(
                        research_plan_issue(
                            "completed_node_display_text_erased",
                            f"/timeline_blocks/{current_index}/subtitle",
                            f"Previously completed node `{previous_id}` had display detail text, but the new revision removes it.",
                            "Keep a non-empty subtitle, summary, description, why_it_matters, next_action, notes, or done_criteria field for completed nodes that already had user-visible detail.",
                        )
                    )
            current_contracts = [
                research_plan_expected_output_types(block)
                for block in blocks
                if isinstance(block, dict)
            ]
            for previous_index, previous_block in enumerate(previous_blocks):
                if not isinstance(previous_block, dict):
                    continue
                previous_id = research_plan_block_id(previous_block, previous_index)
                previous_status = research_plan_block_status(previous_block)
                if previous_status in PLAN_TERMINAL_STATUSES:
                    continue
                expected_outputs = research_plan_expected_output_types(previous_block)
                if not expected_outputs:
                    continue
                if previous_id in current_by_id:
                    continue
                if any(expected_outputs.issubset(contract) for contract in current_contracts):
                    continue
                issues.append(
                    research_plan_issue(
                        "open_contract_node_removed",
                        "/timeline_blocks",
                        f"Open node `{previous_id}` with expected output(s) was removed: {', '.join(sorted(expected_outputs))}.",
                        "Keep the node, mark it done/skipped with structured evidence, or add a replacement node whose deliverable_contract.expected_outputs carries the same output classes.",
                    )
                )
    return issues


def research_plan_required_explicit_display_locale(
    db: Session,
    *,
    project_id: str,
    document: dict[str, Any],
) -> str | None:
    locale = research_plan_document_locale(document)
    if not locale:
        project = db.get(Project, project_id)
        if project is not None and project.created_by:
            user = db.get(User, project.created_by)
            if user is not None and user.locale and user.locale.strip():
                locale = user.locale.strip()
    if locale_is_japanese(locale):
        return "ja-JP"
    return None


def research_plan_document_locale(document: dict[str, Any]) -> str | None:
    for key in ("response_locale", "locale", "language"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for container_key in ("project", "human_interface", "ui", "display"):
        container = document.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("response_locale", "locale", "language", "notebook_language"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def research_plan_locale_display_issues(
    block: dict[str, Any],
    *,
    locale: str,
    path: str,
    node_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for key in PLAN_DISPLAY_TITLE_FIELDS:
        if not research_plan_has_explicit_locale_display_text(block, key, locale):
            issues.append(
                research_plan_issue(
                    "localized_display_missing",
                    f"{path}/{key}",
                    f"ResearchPlan node `{node_id}` is being submitted for locale `{locale}`, but `{key}` has no explicit localized display value.",
                    f"Add localizations.{locale}.{key} (or an equivalent locale-keyed display field). Do not rely on raw English fields for this locale.",
                )
            )
    for key in PLAN_DISPLAY_DETAIL_FIELDS:
        if not research_plan_has_display_text(block, (key,)):
            continue
        if research_plan_has_explicit_locale_display_text(block, key, locale):
            continue
        issues.append(
            research_plan_issue(
                "localized_display_missing",
                f"{path}/{key}",
                f"ResearchPlan node `{node_id}` includes `{key}` display text, but no explicit `{locale}` localized value for that field.",
                f"Add localizations.{locale}.{key} (or an equivalent locale-keyed display field), or remove that display field if it should not be shown.",
            )
        )
    return issues


def research_plan_has_explicit_locale_display_text(block: dict[str, Any], key: str, locale: str | None) -> bool:
    value = research_plan_explicit_locale_display_value(block, key, locale=locale)
    return isinstance(value, str) and value.strip() != ""


def research_plan_explicit_locale_display_value(block: dict[str, Any], key: str, *, locale: str | None) -> Any:
    locale_keys = research_plan_locale_keys(locale)
    if not locale_keys:
        return _MISSING
    display_field_keys = (key, *_research_plan_display_field_keys(key))
    for container_key in ("localizations", "localized", "translations", "translated"):
        container = block.get(container_key)
        if not isinstance(container, dict):
            continue
        for locale_key in locale_keys:
            localized = container.get(locale_key)
            if not isinstance(localized, dict):
                continue
            for display_key in display_field_keys:
                if display_key in localized:
                    return localized[display_key]
    for container_key in ("display", "human_display", "ui_display", "localized_display"):
        container = block.get(container_key)
        if not isinstance(container, dict):
            continue
        for locale_key in locale_keys:
            localized = container.get(locale_key)
            if not isinstance(localized, dict):
                continue
            for display_key in display_field_keys:
                if display_key in localized:
                    return localized[display_key]
    for locale_key in locale_keys:
        suffix = locale_key.replace("-", "_")
        for display_key in display_field_keys:
            for field_key in (f"{display_key}_{suffix}", f"{suffix}_{display_key}"):
                if field_key in block:
                    return block[field_key]
    return _MISSING


def research_plan_locale_keys(locale: str | None) -> list[str]:
    if not isinstance(locale, str) or not locale.strip():
        return []
    normalized = locale.strip().replace("_", "-")
    lower = normalized.lower()
    language = lower.split("-", 1)[0]
    keys = [normalized, lower, language]
    if locale_is_japanese(locale):
        keys.extend(["ja-JP", "ja-jp", "ja", "Japanese", "japanese", "日本語", "Japanese / 日本語"])
    elif language == "en":
        keys.extend(["en-US", "en-us", "en", "English", "english"])
    return list(dict.fromkeys(keys))


def validate_research_plan_current_work_target(
    revision: ResearchPlanRevision | None,
    *,
    node_id: str,
    status: str,
) -> None:
    if revision is None:
        raise ValueError("ResearchPlan revision is required before setting current_work")
    blocks = research_plan_blocks_from_revision(revision)
    node_index = next((index for index, block in enumerate(blocks) if research_plan_block_id(block, index) == node_id), None)
    if node_index is None:
        raise ValueError(
            f"current_work.node_id `{node_id}` is not present in the active ResearchPlan revision. "
            "Commit a revised plan containing the node first."
        )
    node_status = research_plan_block_status(blocks[node_index])
    if status in PLAN_CURRENT_STATUSES and node_status in PLAN_TERMINAL_STATUSES:
        raise ValueError(
            f"current_work.node_id `{node_id}` points to a {node_status} ResearchPlan node. "
            "Set current_work to the next open node, or commit a follow-up node before declaring active work."
        )


def validate_research_plan_node_exists(revision: ResearchPlanRevision, *, node_id: str) -> None:
    blocks = research_plan_blocks_from_revision(revision)
    for index, block in enumerate(blocks):
        if research_plan_block_id(block, index) == node_id:
            return
    raise ValueError(f"ResearchPlan node `{node_id}` is not present in the active revision")


def research_plan_blocks_from_revision(revision: ResearchPlanRevision) -> list[dict[str, Any]]:
    document = research_plan_revision_document(revision)
    raw_blocks = document.get("timeline_blocks") if isinstance(document, dict) else None
    return [block for block in raw_blocks if isinstance(block, dict)] if isinstance(raw_blocks, list) else []


def research_plan_block_id(block: dict[str, Any], index: int) -> str:
    raw_id = block.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    return f"plan_block_{index + 1}"


def research_plan_block_status(block: dict[str, Any]) -> str:
    raw_status = block.get("status")
    return raw_status.strip() if isinstance(raw_status, str) and raw_status.strip() else "pending"


def research_plan_block_granularity(block: dict[str, Any]) -> str:
    for key in ("granularity", "plan_level", "level"):
        raw_value = block.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip().casefold().replace("-", "_").replace(" ", "_")
    return ""


def research_plan_has_display_text(block: dict[str, Any], field_keys: tuple[str, ...]) -> bool:
    for key in field_keys:
        for value in research_plan_display_text_values(block, key):
            if isinstance(value, str) and value.strip():
                return True
    return False


def research_plan_display_text_values(block: dict[str, Any], key: str) -> list[Any]:
    values: list[Any] = [block.get(key)]
    display_field_keys = (key, *_research_plan_display_field_keys(key))
    for display_key in display_field_keys[1:]:
        values.append(block.get(display_key))
    for raw_key, raw_value in block.items():
        if not isinstance(raw_key, str):
            continue
        if raw_key.startswith(f"{key}_") or raw_key.endswith(f"_{key}"):
            values.append(raw_value)
    for container_key in (
        "localizations",
        "localized",
        "translations",
        "translated",
        "display",
        "human_display",
        "ui_display",
        "localized_display",
    ):
        container = block.get(container_key)
        if not isinstance(container, dict):
            continue
        for display_key in display_field_keys:
            values.append(container.get(display_key))
        for localized in container.values():
            if not isinstance(localized, dict):
                continue
            for display_key in display_field_keys:
                values.append(localized.get(display_key))
    return values


def _research_plan_display_field_keys(key: str) -> tuple[str, ...]:
    return (
        f"display_{key}",
        f"{key}_display",
        f"localized_{key}",
        f"{key}_localized",
        f"human_{key}",
        f"{key}_human",
        f"ui_{key}",
        f"{key}_ui",
    )


def research_plan_block_has_completion_evidence(block: dict[str, Any]) -> bool:
    completion_evidence = block.get("completion_evidence")
    if isinstance(completion_evidence, list):
        for item in completion_evidence:
            if not isinstance(item, dict):
                continue
            if any(
                isinstance(item.get(key), str) and item.get(key).strip()
                for key in (
                    "artifact_id",
                    "run_id",
                    "experiment_run_id",
                    "report_id",
                    "notebook_artifact_id",
                    "lineage_edge_id",
                    "workspace_path",
                )
            ):
                return True
    supporting_artifacts = block.get("supporting_artifacts")
    if isinstance(supporting_artifacts, list):
        for item in supporting_artifacts:
            if isinstance(item, dict) and item.get("exists") is not False:
                if any(isinstance(item.get(key), str) and item.get(key).strip() for key in ("artifact_id", "path", "workspace_path")):
                    return True
    if block.get("no_output_required") is True:
        rationale = block.get("no_output_required_rationale") or block.get("rationale")
        return isinstance(rationale, str) and bool(rationale.strip())
    return False


def research_plan_block_has_skip_reason(block: dict[str, Any]) -> bool:
    for key in ("skip_reason", "no_output_required_rationale", "rationale"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def missing_research_plan_deliverables(block: dict[str, Any]) -> list[str]:
    expected = sorted(research_plan_expected_output_types(block))
    if not expected:
        return []
    evidence_types = research_plan_evidence_output_types(block)
    missing: list[str] = []
    for output_type in expected:
        if output_type not in evidence_types:
            missing.append(output_type)
    return missing


def missing_registered_research_plan_deliverables(
    db: Session,
    *,
    project_id: str,
    block: dict[str, Any],
) -> list[str]:
    expected = sorted(research_plan_expected_output_types(block))
    if not expected:
        return []
    verified_types = research_plan_verified_evidence_output_types(db, project_id=project_id, block=block)
    return [output_type for output_type in expected if output_type not in verified_types]


def research_plan_incomplete_pipeline_run_ids(
    db: Session,
    *,
    project_id: str,
    block: dict[str, Any],
) -> list[str]:
    incomplete: list[str] = []
    for item in research_plan_evidence_items(block):
        for run_id in research_plan_evidence_run_ids(item):
            run = research_plan_experiment_run(db, project_id=project_id, run_id=run_id)
            if run is None or run.status != "succeeded":
                continue
            if (
                leaderboard_ready_pipeline_artifact(
                    db,
                    run,
                    params=loads_json(run.params_json, {}),
                )
                is None
            ):
                incomplete.append(run.id)
    return list(dict.fromkeys(incomplete))


def research_plan_expected_output_types(block: dict[str, Any]) -> set[str]:
    contract = block.get("deliverable_contract")
    if not isinstance(contract, dict):
        return set()
    expected_outputs = contract.get("expected_outputs")
    if not isinstance(expected_outputs, list):
        return set()
    return {
        output_type
        for item in expected_outputs
        for output_type in [normalize_research_plan_output_type(item)]
        if output_type and output_type != "none"
    }


def normalize_research_plan_output_type(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("output_type", "type", "asset_type", "kind", "role"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return normalize_research_plan_type_token(item)
        return ""
    if isinstance(value, str):
        return normalize_research_plan_type_token(value)
    return ""


def research_plan_verified_evidence_output_types(
    db: Session,
    *,
    project_id: str,
    block: dict[str, Any],
) -> set[str]:
    verified_types: set[str] = set()
    for item in research_plan_evidence_items(block):
        verified_types.update(research_plan_verified_output_types_for_evidence_item(db, project_id=project_id, item=item))
    if block.get("no_output_required") is True and research_plan_block_has_completion_evidence(block):
        verified_types.add("none")
    return verified_types


def research_plan_evidence_items(block: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    completion_evidence = block.get("completion_evidence")
    if isinstance(completion_evidence, list):
        items.extend(item for item in completion_evidence if isinstance(item, dict))
    supporting_artifacts = block.get("supporting_artifacts")
    if isinstance(supporting_artifacts, list):
        items.extend(item for item in supporting_artifacts if isinstance(item, dict) and item.get("exists") is not False)
    return items


def research_plan_verified_output_types_for_evidence_item(
    db: Session,
    *,
    project_id: str,
    item: dict[str, Any],
) -> set[str]:
    verified_types: set[str] = set()
    for run_id in research_plan_evidence_run_ids(item):
        run = research_plan_experiment_run(db, project_id=project_id, run_id=run_id)
        if run is not None:
            verified_types.add("experiment_run")
            if (
                run.status == "succeeded"
                and leaderboard_ready_pipeline_artifact(
                    db,
                    run,
                    params=loads_json(run.params_json, {}),
                )
                is not None
            ):
                verified_types.add("leaderboard_entry")
    artifact = research_plan_evidence_artifact(db, project_id=project_id, item=item)
    if artifact is not None:
        verified_types.update(research_plan_artifact_output_types(artifact))
        for declared_type in research_plan_declared_output_types(item):
            if declared_type == "artifact":
                verified_types.add("artifact")
            elif declared_type in research_plan_artifact_output_types(artifact):
                verified_types.add(declared_type)
    report = research_plan_evidence_report(db, project_id=project_id, item=item)
    if report is not None:
        verified_types.add("report")
        artifact = db.get(Artifact, report.artifact_id)
        if artifact is not None and artifact.project_id == project_id:
            verified_types.update(research_plan_artifact_output_types(artifact))
    return verified_types


def research_plan_declared_output_types(item: dict[str, Any]) -> set[str]:
    declared: set[str] = set()
    for key in ("output_type", "type", "asset_type", "kind", "role"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            declared.add(normalize_research_plan_type_token(value))
    return declared


def research_plan_evidence_run_ids(item: dict[str, Any]) -> list[str]:
    run_ids: list[str] = []
    for key in ("run_id", "experiment_run_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            run_ids.append(value.strip())
    return run_ids


def research_plan_experiment_run_exists(db: Session, *, project_id: str, run_id: str) -> bool:
    return research_plan_experiment_run(db, project_id=project_id, run_id=run_id) is not None


def research_plan_experiment_run(db: Session, *, project_id: str, run_id: str) -> ExperimentRun | None:
    run = db.get(ExperimentRun, run_id)
    if run is None or run.project_id != project_id:
        return None
    return run


def research_plan_evidence_artifact(
    db: Session,
    *,
    project_id: str,
    item: dict[str, Any],
) -> Artifact | None:
    for key in ("artifact_id", "notebook_artifact_id", "report_artifact_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            artifact = db.get(Artifact, value.strip())
            if artifact is not None and artifact.project_id == project_id:
                return artifact
    report_id = item.get("report_id")
    if isinstance(report_id, str) and report_id.strip():
        artifact = db.get(Artifact, report_id.strip())
        if artifact is not None and artifact.project_id == project_id:
            return artifact
        report = db.get(Report, report_id.strip())
        if report is not None and report.project_id == project_id:
            artifact = db.get(Artifact, report.artifact_id)
            if artifact is not None and artifact.project_id == project_id:
                return artifact
    for key in ("workspace_path", "path"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            artifact = latest_project_artifact_for_workspace_path(db, project_id=project_id, workspace_path=value)
            if artifact is not None:
                return artifact
    return None


def research_plan_evidence_report(
    db: Session,
    *,
    project_id: str,
    item: dict[str, Any],
) -> Report | None:
    report_id = item.get("report_id")
    if not isinstance(report_id, str) or not report_id.strip():
        return None
    report = db.get(Report, report_id.strip())
    if report is not None and report.project_id == project_id:
        return report
    return None


def latest_project_artifact_for_workspace_path(
    db: Session,
    *,
    project_id: str,
    workspace_path: str,
) -> Artifact | None:
    relative_path = workspace_path.strip()
    if not relative_path:
        return None
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
            .limit(1000)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("workspace_relative_path") == relative_path:
            return artifact
    return None


def research_plan_artifact_output_types(artifact: Artifact) -> set[str]:
    asset_type = artifact.asset_type.strip().casefold()
    raw_asset_type = asset_type.replace("-", "_").replace(" ", "_")
    normalized_asset_type = normalize_research_plan_type_token(asset_type)
    output_types = {"artifact"}
    if raw_asset_type:
        output_types.add(raw_asset_type)
    if normalized_asset_type and normalized_asset_type != "notebook":
        output_types.add(normalized_asset_type)
    if (asset_type in PLAN_NOTEBOOK_ASSET_TYPES or normalized_asset_type == "notebook") and research_plan_artifact_is_native_marimo_source(artifact):
        output_types.add("notebook")
    if asset_type in PLAN_REPORT_ASSET_TYPES or normalized_asset_type == "report":
        output_types.add("report")
    if asset_type in PLAN_FIGURE_ASSET_TYPES or normalized_asset_type == "visualization":
        output_types.add("visualization")
    if raw_asset_type == "research_findings_report":
        output_types.update({"research_findings", "prior_research", "evidence", "report"})
    if raw_asset_type == "validation_scheme_audit":
        output_types.update({"validation_audit", "pilot_audit", "evidence", "report"})
    if raw_asset_type == "pilot_scoring_report":
        output_types.update({"pilot_scoring", "pilot_report", "evidence", "report"})
    if raw_asset_type == "prediction_pipeline":
        output_types.update({"pipeline", "prediction_pipeline", "reproducible_pipeline"})
    if raw_asset_type == "model_diagnostics_artifact_pack":
        output_types.update({"model_diagnostics", "model_diagnostics_artifacts", "evidence", "report"})
    if raw_asset_type == "feature_importance":
        output_types.update({"model_diagnostics", "native_feature_importance", "feature_importance", "evidence"})
    if raw_asset_type == "permutation_importance":
        output_types.update({"model_diagnostics", "permutation_importance", "evidence"})
    if raw_asset_type == "partial_dependence":
        output_types.update({"model_diagnostics", "partial_dependence", "pdp", "evidence", "visualization"})
    if raw_asset_type == "shap_summary":
        output_types.update({"model_diagnostics", "shap", "shap_summary", "evidence"})
    return output_types


def research_plan_artifact_surface_target(artifact: Artifact | None, *, role: str = "") -> dict[str, str]:
    if artifact is not None and "notebook" in research_plan_artifact_output_types(artifact):
        return {"target_tab": "Notebooks", "target_anchor": "notebook-native-marimo-top"}
    normalized_role = normalize_research_plan_type_token(role) if role else ""
    if artifact is not None and (artifact.asset_type in PLAN_REPORT_ASSET_TYPES or normalized_role == "report"):
        return {"target_tab": "Assets", "target_anchor": "assets-artifact-preview"}
    if artifact is not None and (artifact.asset_type in PLAN_FIGURE_ASSET_TYPES or normalized_role == "visualization"):
        return {"target_tab": "Assets", "target_anchor": "assets-artifact-preview"}
    return {"target_tab": "Assets", "target_anchor": "assets-artifact-preview"}


def research_plan_artifact_is_native_marimo_source(artifact: Artifact) -> bool:
    try:
        path = artifact_primary_path(artifact)
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return False
    if path.suffix.lower() != ".py":
        return False
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return research_plan_source_is_marimo_notebook(source)


def research_plan_source_is_marimo_notebook(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    marimo_module_names: set[str] = set()
    marimo_app_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "marimo":
                    marimo_module_names.add(alias.asname or "marimo")
        elif isinstance(node, ast.ImportFrom) and node.module == "marimo":
            for alias in node.names:
                if alias.name == "App":
                    marimo_app_names.add(alias.asname or "App")
    if not marimo_module_names and not marimo_app_names:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "App":
            if isinstance(callee.value, ast.Name) and callee.value.id in marimo_module_names:
                return True
        elif isinstance(callee, ast.Name) and callee.id in marimo_app_names:
            return True
    return False


def research_plan_evidence_output_types(block: dict[str, Any]) -> set[str]:
    evidence_types: set[str] = set()
    completion_evidence = block.get("completion_evidence")
    if isinstance(completion_evidence, list):
        for item in completion_evidence:
            if not isinstance(item, dict):
                continue
            for key in ("output_type", "type", "asset_type", "kind", "role"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    evidence_types.add(normalize_research_plan_type_token(value))
            if any(isinstance(item.get(key), str) and item.get(key).strip() for key in ("run_id", "experiment_run_id")):
                evidence_types.add("experiment_run")
            if any(isinstance(item.get(key), str) and item.get(key).strip() for key in ("notebook_artifact_id", "notebook_id")):
                evidence_types.add("notebook")
            if any(isinstance(item.get(key), str) and item.get(key).strip() for key in ("report_id",)):
                evidence_types.add("report")
    supporting_artifacts = block.get("supporting_artifacts")
    if isinstance(supporting_artifacts, list):
        for item in supporting_artifacts:
            if not isinstance(item, dict) or item.get("exists") is False:
                continue
            for key in ("output_type", "type", "asset_type", "kind", "role"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    evidence_types.add(normalize_research_plan_type_token(value))
            path = item.get("path") or item.get("workspace_path")
            if isinstance(path, str):
                lower_path = path.lower()
                if "notebook" in lower_path or lower_path.endswith(".py"):
                    evidence_types.add("notebook")
                if lower_path.endswith((".md", ".html")):
                    evidence_types.add("report")
                if "model_result" in lower_path or "leaderboard" in lower_path or "experiment" in lower_path:
                    evidence_types.add("experiment_run")
    return evidence_types


def normalize_research_plan_type_token(value: str) -> str:
    token = value.strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "marimo": "notebook",
        "marimo_notebook": "notebook",
        "analysis_notebook": "notebook",
        "data_understanding_notebook": "notebook",
        "model_diagnostics_notebook": "notebook",
        "eda_notebook": "notebook",
        "leaderboard": "leaderboard_entry",
        "leaderboard_result": "leaderboard_entry",
        "leaderboard_row": "leaderboard_entry",
        "run": "experiment_run",
        "experiment": "experiment_run",
        "model_run": "experiment_run",
        "model_results": "experiment_run",
        "agent_session_report": "report",
        "analysis_report": "report",
        "eda_report": "report",
        "markdown_report": "report",
        "html_report": "report",
        "chart": "visualization",
        "figure": "visualization",
        "plot": "visualization",
        "visualization_spec": "visualization",
    }
    if token in aliases:
        return aliases[token]
    if token.endswith("_notebook"):
        return "notebook"
    if token.endswith("_report"):
        return "report"
    if token.endswith(("_figure", "_plot", "_chart", "_visualization")):
        return "visualization"
    return token


def research_plan_issue(
    code: str,
    path: str,
    message: str,
    fix: str,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message, "fix": fix, "severity": severity}
