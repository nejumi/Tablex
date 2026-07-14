from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    Job,
    LineageEdge,
    ModelVersion,
    Project,
    ResearchPlanRevision,
    utc_now,
)
from tabular_harness.services.agent_notebook_quality import notebook_quality_feedback_from_metadata
from tabular_harness.services.agent_notebook_registration import (
    notebook_registration_chat_status,
    notebook_registration_visible_surfaces,
)
from tabular_harness.services.agent_outputs import is_chat_update_path
from tabular_harness.services.agent_session_inbox import (
    notebook_context_request_path,
    notebook_quality_repair_path,
    write_notebook_context_request_to_workspace_inbox,
    write_notebook_quality_repair_to_workspace_inbox,
)
from tabular_harness.services.agent_transcript import append_session_event
from tabular_harness.services.agent_workspace import latest_project_response_locale
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, artifact_primary_path
from tabular_harness.services.jobs import TERMINAL_STATUSES as TERMINAL_JOB_STATUSES
from tabular_harness.services.jobs import mark_job_succeeded
from tabular_harness.services.locales import locale_is_japanese
from tabular_harness.services.research_plan_timeline import research_plan_evidence_links
from tabular_harness.services.research_plans import (
    PLAN_CURRENT_STATUSES,
    attach_research_plan_artifact,
    latest_research_plan_current_work,
    latest_research_plan_revision,
    research_plan_artifact_is_native_marimo_source,
    research_plan_revision_document,
)

NOTEBOOK_RUNTIME_RETRY_AFTER_SECONDS = 5 * 60
NATIVE_NOTEBOOK_ASSET_TYPES = {"analysis_notebook", "marimo_notebook"}


def register_research_registration_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    research_artifact: Artifact,
    research_payload: dict[str, Any],
) -> Artifact | None:
    metadata = loads_json(research_artifact.metadata_json, {})
    source_key = str(metadata.get("request_id") or research_artifact.id).strip()
    existing = latest_research_registration_chat_turn(
        db,
        project=project,
        session=session,
        source_key=source_key,
    )
    if existing is not None:
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    topic = str(research_payload.get("topic") or "").strip()
    sources = research_payload.get("sources") if isinstance(research_payload.get("sources"), list) else []
    findings = research_payload.get("findings") if isinstance(research_payload.get("findings"), list) else []
    no_findings = research_payload.get("no_findings") if isinstance(research_payload.get("no_findings"), dict) else None
    if no_findings is not None:
        assistant_message = (
            "従来知見の調査結果を保存しました。今回は追加で採用する知見なしとして記録されています。"
            if japanese
            else "The prior-knowledge research result was saved. Codex recorded that no additional finding should be adopted from this pass."
        )
    elif japanese:
        assistant_message = f"従来知見の調査結果を保存しました。{len(sources)}件のsourceと{len(findings)}件のfindingを確認できます。"
    else:
        assistant_message = f"Saved prior-knowledge research with {len(sources)} source(s) and {len(findings)} finding(s)."
    if topic:
        assistant_message = f"{assistant_message}\n\n{topic}"
    action_label = "保存済みの関連調査を開く" if japanese else "Open saved related research"
    action_detail = (
        "Codexが登録したsource、finding、projectへの示唆を確認します。"
        if japanese
        else "Open the sources, findings, and project implications registered by Codex."
    )
    rich_report_artifact_id = str(metadata.get("rich_report_artifact_id") or "").strip()
    open_artifact_id = rich_report_artifact_id or research_artifact.id
    open_asset_type = "research_markdown_report" if rich_report_artifact_id else research_artifact.asset_type
    open_artifact_ids = [open_artifact_id]
    if research_artifact.id not in open_artifact_ids:
        open_artifact_ids.append(research_artifact.id)
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "research_findings_registered",
            "source": "main_agent_session_workspace",
            "status": "ready",
        },
        "actions": [
            {
                "type": "open_artifact",
                "status": "ready",
                "label": action_label,
                "target_tab": "Assets",
                "target_anchor": "assets-artifact-preview",
                "detail": action_detail,
                "artifact_id": open_artifact_id,
                "artifact_ids": open_artifact_ids,
                "asset_type": open_asset_type,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "research_findings_registered.v1",
            "agent_session_id": session.id,
            "research_findings_report_artifact_id": research_artifact.id,
            "rich_report_artifact_id": rich_report_artifact_id or None,
            "research_plan_node_id": research_payload.get("research_plan_node_id"),
            "topic": topic or None,
            "source_count": len(sources),
            "finding_count": len(findings),
            "no_findings": no_findings,
        },
        "visible_surfaces": {
            "assets": {
                "target_tab": "Assets",
                "target_anchor": "assets-artifact-preview",
                "artifact_id": open_artifact_id,
                "artifact_ids": open_artifact_ids,
                "asset_type": open_asset_type,
            }
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {
            "target_tab": "Assets",
            "target_anchor": "assets-artifact-preview",
            "artifact_id": open_artifact_id,
            "artifact_ids": open_artifact_ids,
            "asset_type": open_asset_type,
            "label": action_label,
        },
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_research_findings_{session.id}_{hashlib.sha1(source_key.encode('utf-8')).hexdigest()[:12]}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source": "main_agent_session_research_registration",
            "source_key": source_key,
            "source_artifact_id": research_artifact.id,
            "research_findings_report_artifact_id": research_artifact.id,
        },
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="research_chat_turn_registered",
        role="harness",
        title="Research findings chat turn registered",
        content="Registered research findings availability in Agent Chat.",
        payload={
            "chat_artifact_id": chat_artifact.id,
            "research_findings_report_artifact_id": research_artifact.id,
            "source_count": len(sources),
            "finding_count": len(findings),
        },
        artifact_id=chat_artifact.id,
        update_heartbeat=False,
    )
    annotate_agent_chat_turn_with_source_event(chat_artifact, event)
    return chat_artifact


def latest_research_registration_chat_turn(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    source_key: str,
) -> Artifact | None:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(100)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_research_registration"
            and metadata.get("agent_session_id") == session.id
            and metadata.get("source_key") == source_key
        ):
            return artifact
    return None


def register_agent_session_notebook_source_output(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    artifact: Artifact,
) -> None:
    if artifact.asset_type not in NATIVE_NOTEBOOK_ASSET_TYPES or artifact.project_id is None:
        return
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("source") != "main_agent_session_workspace":
        return
    if not research_plan_artifact_is_native_marimo_source(artifact):
        return
    existing_success = latest_agent_session_notebook_registration_event(
        db,
        session=session,
        artifact=artifact,
        event_types=("notebook_registered", "notebook_auto_registration_succeeded"),
    )
    if existing_success is not None:
        register_agent_session_notebook_chat_turn(
            db,
            store=store,
            session=session,
            notebook_artifact=artifact,
            status=notebook_registration_chat_status(artifact),
        )
        return
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_registered",
        role="harness",
        title="Notebook registered",
        content="A Codex-authored marimo notebook was registered for native marimo viewing.",
        payload={
            "notebook_artifact_id": artifact.id,
        },
        artifact_id=artifact.id,
    )
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=artifact,
    )
    register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=artifact,
        status=notebook_registration_chat_status(artifact),
        linked_plan_node_id=linked_plan_node_id,
    )


def register_agent_session_notebook_chat_turn_from_registration_event(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    notebook_artifact: Artifact,
    event: AgentTranscriptEvent,
) -> Artifact | None:
    linked_plan_node_id = attach_notebook_artifacts_to_current_research_plan(
        db,
        session=session,
        notebook_artifact=notebook_artifact,
    )
    return register_agent_session_notebook_chat_turn(
        db,
        store=store,
        session=session,
        notebook_artifact=notebook_artifact,
        status=notebook_registration_chat_status(notebook_artifact),
        linked_plan_node_id=linked_plan_node_id,
    )


def notebook_runtime_failure_retry_due(
    event: AgentTranscriptEvent,
    *,
    retry_after_seconds: int = NOTEBOOK_RUNTIME_RETRY_AFTER_SECONDS,
) -> bool:
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (utc_now() - created_at).total_seconds() >= retry_after_seconds


def maybe_defer_agent_session_notebook_registration(db: Session, *, session: AgentSession, artifact: Artifact) -> None:
    if artifact.asset_type not in NATIVE_NOTEBOOK_ASSET_TYPES or artifact.project_id is None:
        return
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("source") != "main_agent_session_workspace":
        return
    if not research_plan_artifact_is_native_marimo_source(artifact):
        return
    if agent_session_notebook_registration_event_exists(
        db,
        session=session,
        artifact=artifact,
        event_types=(
            "notebook_registered_deferred",
            "notebook_registered",
            "notebook_auto_registration_deferred",
            "notebook_auto_registration_succeeded",
            "notebook_auto_registration_failed",
        ),
    ):
        return
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_registered_deferred",
        role="harness",
        title="Notebook registration deferred",
        content="A Codex-authored marimo notebook was saved; Tablex will link it to Chat and ResearchPlan after the active Codex turn yields.",
        payload={"notebook_artifact_id": artifact.id},
        artifact_id=artifact.id,
        update_heartbeat=False,
    )


def register_pending_agent_session_notebooks(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
) -> None:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in reversed(notebook_artifacts):
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        register_agent_session_notebook_source_output(db, store=store, session=session, artifact=artifact)


def request_context_for_auto_registered_notebooks(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    limit: int = 50,
) -> int:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    pending: list[Artifact] = []
    for artifact in notebook_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        if metadata.get("notebook_context_source") == "tablex_notebook_request":
            continue
        if notebook_artifact_has_declared_context(db, artifact=artifact):
            continue
        if not research_plan_artifact_is_native_marimo_source(artifact):
            continue
        pending.append(artifact)
    if not pending:
        try:
            notebook_context_request_path(workspace).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return 0
    digest_source = "|".join(sorted(artifact.id for artifact in pending))
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    attention_key = f"notebook_context_registration_needed:{session.id}:{digest}"
    if agent_session_attention_chat_turn_exists(db, project=project, session=session, attention_key=attention_key):
        return len(pending)
    write_notebook_context_request_to_workspace_inbox(workspace, notebook_artifacts=pending)
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=attention_key,
        status="needs_attention",
        message_kind="notebook_context_registration_needed",
        details={
            "notebook_count": len(pending),
            "notebook_artifact_ids": [artifact.id for artifact in pending[:12]],
            "notebook_versions": [artifact.version for artifact in pending[:12]],
            "workspace_paths": [
                str(loads_json(artifact.metadata_json, {}).get("workspace_relative_path") or "")
                for artifact in pending[:12]
            ],
        },
    )
    return len(pending)


def request_quality_repair_for_session_notebooks(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    limit: int = 50,
) -> int:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    pending: list[Artifact] = []
    for artifact in notebook_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        if not research_plan_artifact_is_native_marimo_source(artifact):
            continue
        if notebook_quality_needs_repair(artifact):
            pending.append(artifact)
    if not pending:
        try:
            notebook_quality_repair_path(workspace).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return 0
    digest_source = "|".join(
        f"{artifact.id}:{notebook_quality_feedback_from_metadata(artifact).get('status')}" for artifact in pending
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    attention_key = f"notebook_quality_repair_needed:{session.id}:{digest}"
    if agent_session_attention_chat_turn_exists(db, project=project, session=session, attention_key=attention_key):
        return len(pending)
    write_notebook_quality_repair_to_workspace_inbox(workspace, notebook_artifacts=pending)
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=attention_key,
        status="needs_attention",
        message_kind="notebook_quality_repair_needed",
        details={
            "notebook_count": len(pending),
            "notebook_artifact_ids": [artifact.id for artifact in pending[:12]],
            "notebook_versions": [artifact.version for artifact in pending[:12]],
            "workspace_paths": [
                str(loads_json(artifact.metadata_json, {}).get("workspace_relative_path") or "")
                for artifact in pending[:12]
            ],
            "quality_statuses": [
                str(notebook_quality_feedback_from_metadata(artifact).get("status") or "")
                for artifact in pending[:12]
            ],
        },
    )
    return len(pending)


def notebook_quality_needs_repair(artifact: Artifact) -> bool:
    status = str(notebook_quality_feedback_from_metadata(artifact).get("status") or "")
    return status.startswith("needs_")


def reconcile_project_notebook_context_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    limit: int = 80,
) -> int:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    session_ids: set[str] = set()
    for artifact in notebook_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("notebook_context_source") == "tablex_notebook_request":
            continue
        if notebook_artifact_has_declared_context(db, artifact=artifact):
            continue
        session_id = metadata.get("agent_session_id")
        if isinstance(session_id, str) and session_id.strip():
            session_ids.add(session_id.strip())
    reconciled = 0
    for session_id in sorted(session_ids):
        session = db.get(AgentSession, session_id)
        if session is None or session.project_id != project.id or not session.workspace_path:
            continue
        reconciled += request_context_for_auto_registered_notebooks(
            db,
            store=store,
            project=project,
            session=session,
            workspace=resolve_runtime_data_path(session.workspace_path),
            limit=limit,
        )
    return reconciled


def reconcile_project_notebook_quality_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    limit: int = 80,
) -> int:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    session_ids: set[str] = set()
    for artifact in notebook_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if not notebook_quality_needs_repair(artifact):
            continue
        session_id = metadata.get("agent_session_id")
        if isinstance(session_id, str) and session_id.strip():
            session_ids.add(session_id.strip())
    reconciled = 0
    for session_id in sorted(session_ids):
        session = db.get(AgentSession, session_id)
        if session is None or session.project_id != project.id or not session.workspace_path:
            continue
        reconciled += request_quality_repair_for_session_notebooks(
            db,
            store=store,
            project=project,
            session=session,
            workspace=resolve_runtime_data_path(session.workspace_path),
            limit=limit,
        )
    return reconciled


def notebook_artifact_has_declared_context(
    db: Session,
    *,
    artifact: Artifact,
    include_sibling_versions: bool = False,
) -> bool:
    if notebook_artifact_has_direct_declared_context(db, artifact=artifact):
        return True
    if not include_sibling_versions or artifact.project_id is None:
        return False
    metadata = loads_json(artifact.metadata_json, {})
    workspace_relative_path = str(metadata.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path:
        return False
    sibling_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == artifact.project_id,
                Artifact.asset_type == artifact.asset_type,
                Artifact.id != artifact.id,
            )
            .order_by(Artifact.created_at.desc())
            .limit(200)
        ).all()
    )
    for sibling in sibling_artifacts:
        sibling_metadata = loads_json(sibling.metadata_json, {})
        if str(sibling_metadata.get("workspace_relative_path") or "").strip() != workspace_relative_path:
            continue
        if notebook_artifact_has_direct_declared_context(db, artifact=sibling):
            return True
    return False


def notebook_artifact_has_direct_declared_context(db: Session, *, artifact: Artifact) -> bool:
    if artifact.project_id is None:
        return False
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("notebook_context_source") == "tablex_notebook_request":
        return True
    for key in ("research_plan_node_id", "dataset_snapshot_id", "run_id", "model_version_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return True
    edge_id = db.scalar(
        select(LineageEdge.id)
        .where(
            LineageEdge.project_id == artifact.project_id,
            LineageEdge.to_asset_type == "artifact",
            LineageEdge.to_asset_id == artifact.id,
            LineageEdge.relation_type == "supports_plan_node",
        )
        .limit(1)
    )
    return isinstance(edge_id, str) and bool(edge_id)


def reconcile_project_notebook_chat_links(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    limit: int = 80,
) -> int:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    registered = 0
    for artifact in reversed(notebook_artifacts):
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        session_id = metadata.get("agent_session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            continue
        session = db.get(AgentSession, session_id)
        if session is None or session.project_id != project.id:
            continue
        if not research_plan_artifact_is_native_marimo_source(artifact):
            continue
        chat_artifact = register_agent_session_notebook_chat_turn(
            db,
            store=store,
            session=session,
            notebook_artifact=artifact,
            status=notebook_registration_chat_status(artifact),
        )
        if chat_artifact is not None:
            registered += 1
    return registered


def attach_registered_session_notebooks_to_current_research_plan(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
) -> None:
    notebook_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(NATIVE_NOTEBOOK_ASSET_TYPES))
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in reversed(notebook_artifacts):
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_agent_session_workspace":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        if not research_plan_artifact_is_native_marimo_source(artifact):
            continue
        attach_notebook_artifacts_to_current_research_plan(
            db,
            session=session,
            notebook_artifact=artifact,
        )


def attach_notebook_artifacts_to_current_research_plan(
    db: Session,
    *,
    session: AgentSession,
    notebook_artifact: Artifact,
    related_artifacts: list[tuple[Any | None, str]] | None = None,
    node_id: str | None = None,
    revision_id: str | None = None,
    strict: bool = False,
) -> str | None:
    if notebook_artifact.project_id is None:
        return None
    if not research_plan_artifact_is_native_marimo_source(notebook_artifact):
        return None
    current = latest_research_plan_current_work(db, project_id=notebook_artifact.project_id)
    target_node_id = node_id.strip() if isinstance(node_id, str) and node_id.strip() else None
    if target_node_id is None:
        metadata = loads_json(notebook_artifact.metadata_json, {})
        target_node_id = metadata_text(metadata, "research_plan_node_id")
    if target_node_id is None and current is not None:
        expected_outputs = loads_json(current.expected_outputs_json, [])
        normalized_outputs = {
            str(output).strip().lower().replace("-", "_").replace(" ", "_")
            for output in expected_outputs
            if isinstance(output, str) and output.strip()
        }
        if normalized_outputs.intersection({"notebook", "marimo_notebook", "analysis_notebook"}):
            target_node_id = current.node_id.strip() or None
    if target_node_id is None:
        return None
    target_revision_id = revision_id.strip() if isinstance(revision_id, str) and revision_id.strip() else None
    if target_revision_id is None and current is not None and current.revision_id:
        target_revision_id = current.revision_id
    if target_revision_id is None:
        revision = latest_research_plan_revision(db, project_id=notebook_artifact.project_id)
        target_revision_id = revision.id if revision is not None else None
    artifact_roles: list[tuple[str, str]] = [(notebook_artifact.id, "notebook_source")]
    for artifact_like, role in related_artifacts or []:
        artifact_id = getattr(artifact_like, "id", None)
        if isinstance(artifact_id, str) and artifact_id.strip():
            artifact_roles.append((artifact_id, role))
    attached_any = False
    for artifact_id, role in artifact_roles:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != notebook_artifact.project_id:
            continue
        if research_plan_artifact_link_exists(
            db,
            project_id=notebook_artifact.project_id,
            node_id=target_node_id,
            artifact_id=artifact.id,
        ):
            continue
        try:
            attach_research_plan_artifact(
                db,
                project_id=notebook_artifact.project_id,
                node_id=target_node_id,
                artifact_id=artifact.id,
                role=role,
                revision_id=target_revision_id,
                metadata={
                    "agent_session_id": session.id,
                    "notebook_artifact_id": notebook_artifact.id,
                    "source": "main_agent_session_notebook_link",
                },
            )
        except ValueError:
            if strict:
                raise
            continue
        attached_any = True
    return target_node_id if attached_any or strict else None


def single_current_research_plan_node_id(revision: ResearchPlanRevision | None) -> str | None:
    if revision is None:
        return None
    document = research_plan_revision_document(revision)
    raw_blocks = document.get("timeline_blocks")
    if not isinstance(raw_blocks, list):
        return None
    current_node_ids: list[str] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            continue
        node_id = str(raw_block.get("id") or "").strip()
        status = str(raw_block.get("status") or "").strip().lower()
        if node_id and status in PLAN_CURRENT_STATUSES:
            current_node_ids.append(node_id)
    return current_node_ids[0] if len(current_node_ids) == 1 else None


def research_plan_artifact_link_exists(
    db: Session,
    *,
    project_id: str,
    node_id: str,
    artifact_id: str,
) -> bool:
    edges = list(
        db.scalars(
            select(LineageEdge)
            .where(
                LineageEdge.project_id == project_id,
                LineageEdge.to_asset_type == "artifact",
                LineageEdge.to_asset_id == artifact_id,
                LineageEdge.relation_type == "supports_plan_node",
            )
            .order_by(LineageEdge.created_at.desc())
            .limit(20)
        ).all()
    )
    for edge in edges:
        metadata = loads_json(edge.metadata_json, {})
        if metadata.get("node_id") == node_id:
            return True
    return False


def agent_session_notebook_registration_event_exists(
    db: Session,
    *,
    session: AgentSession,
    artifact: Artifact,
    event_types: tuple[str, ...],
) -> bool:
    return latest_agent_session_notebook_registration_event(
        db,
        session=session,
        artifact=artifact,
        event_types=event_types,
    ) is not None


def latest_agent_session_notebook_registration_event(
    db: Session,
    *,
    session: AgentSession,
    artifact: Artifact,
    event_types: tuple[str, ...],
) -> AgentTranscriptEvent | None:
    recent_events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(
                AgentTranscriptEvent.session_id == session.id,
                AgentTranscriptEvent.event_type.in_(event_types),
            )
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(100)
        ).all()
    )
    for event in recent_events:
        payload = loads_json(event.payload_json, {})
        if payload.get("notebook_artifact_id") == artifact.id:
            return event
    return None


def register_agent_session_notebook_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    session: AgentSession,
    notebook_artifact: Artifact,
    status: str,
    linked_plan_node_id: str | None = None,
    error: str | None = None,
) -> Artifact | None:
    if notebook_artifact.project_id is None:
        return None
    project = db.get(Project, notebook_artifact.project_id)
    if project is None:
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    notebook_metadata = loads_json(notebook_artifact.metadata_json, {})
    workspace_path = str(notebook_metadata.get("workspace_relative_path") or "").strip()
    notebook_label = Path(workspace_path).name if workspace_path else notebook_artifact.name
    notebook_version = notebook_artifact.version
    change_kind = "updated" if notebook_version > 1 else "new"
    identity = f"`{notebook_label}` v{notebook_version}"
    if status == "ready":
        assistant_message = (
            f"Notebookを{'更新' if change_kind == 'updated' else '新規登録'}しました: {identity}。"
            "Tablex内のmarimoビューアーで開けます。"
            if japanese
            else f"{'Updated' if change_kind == 'updated' else 'New'} notebook: {identity}. Open it in the Tablex marimo viewer."
        )
        action_status = "ready"
        action_label = "ノートブックを開く" if japanese else "Open notebook"
        action_detail = (
            "保存されたmarimo sourceをnative marimoで開きます。"
            if japanese
            else "Open the saved marimo source with native marimo."
        )
        next_focus_label = "ノートブック" if japanese else "Notebook"
    elif status == "source_saved":
        assistant_message = (
            f"Notebookを{'更新' if change_kind == 'updated' else '新規登録'}しました: {identity}。"
            "ここからmarimoで開けます。"
            if japanese
            else f"{'Updated' if change_kind == 'updated' else 'New'} notebook: {identity}. Open it here with marimo."
        )
        action_status = "ready"
        action_label = "ノートブックを開く" if japanese else "Open notebook"
        action_detail = (
            "保存されたmarimo sourceをnative marimoで開きます。"
            if japanese
            else "Open the saved marimo source with native marimo."
        )
        next_focus_label = "ノートブック" if japanese else "Notebook"
    elif status == "quality_needs_attention":
        assistant_message = (
            f"Notebookは修正が必要です: {identity}。人が読む成果物としてはまだ不足があります。"
            "図や発見、読順を補って再提出する修正対象として扱います。"
            if japanese
            else (
                f"Notebook needs revision: {identity}. It is not yet a complete human-facing deliverable. "
                "It needs richer figures, findings, or read order before it should be treated as ready."
            )
        )
        action_status = "needs_attention"
        action_label = "ノートブックを確認" if japanese else "Review notebook"
        action_detail = (
            "保存済みのmarimo sourceを開き、不足している図や説明を確認します。"
            if japanese
            else "Open the saved marimo source and review the missing notebook quality signals."
        )
        next_focus_label = "ノートブック" if japanese else "Notebook"
    else:
        assistant_message = (
            f"Notebookの実行修正が必要です: {identity}。marimoで正常に開ける状態ではありません。"
            if japanese
            else f"Notebook runtime fix required: {identity}. It cannot yet be opened successfully with marimo."
        )
        action_status = "needs_attention"
        action_label = "ノートブックを開く" if japanese else "Open notebook"
        action_detail = (
            "失敗は隠さず、Notebook/runtimeの修正対象として扱います。"
            if japanese
            else "The failure is exposed as a notebook/runtime issue to fix."
        )
        next_focus_label = "ノートブック" if japanese else "Notebook"
    context_links = notebook_artifact_context_links_from_metadata(db, project=project, notebook_artifact=notebook_artifact)
    notebook_quality = notebook_quality_feedback_from_metadata(notebook_artifact)
    linked_plan_node_id = linked_plan_node_id or notebook_artifact_research_plan_node_id(db, notebook_artifact=notebook_artifact)
    visible_surfaces = notebook_registration_visible_surfaces(
        notebook_artifact=notebook_artifact,
        chat_artifact_id=None,
        linked_plan_node_id=linked_plan_node_id,
        dataset_snapshot_id=context_links.get("dataset_snapshot_id"),
        run_id=context_links.get("run_id"),
        model_version_id=context_links.get("model_version_id"),
    )
    actions = notebook_registration_chat_actions(
        notebook_artifact=notebook_artifact,
        visible_surfaces=visible_surfaces,
        status=action_status,
        notebook_label=action_label,
        notebook_detail=action_detail,
        japanese=japanese,
    )
    existing_chat_artifact = latest_agent_session_notebook_chat_turn(
        db,
        project=project,
        session=session,
        notebook_artifact=notebook_artifact,
        status=status,
    )
    if existing_chat_artifact is not None:
        update_agent_session_notebook_chat_payload(
            existing_chat_artifact,
            visible_surfaces=visible_surfaces,
            context_links=context_links,
            notebook_quality=notebook_quality,
            actions=actions,
            linked_plan_node_id=linked_plan_node_id,
        )
        return None
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "notebook_artifact_update",
            "source": "main_agent_session_workspace",
            "status": status,
        },
        "actions": actions,
        "action_summary": {},
        "response_brief": {
            "schema_version": "notebook_artifact_update.v1",
            "agent_session_id": session.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_name": notebook_label,
            "notebook_version": notebook_version,
            "change_kind": change_kind,
            "status": status,
            "error": error,
            "research_plan_node_id": linked_plan_node_id,
            "visible_surfaces": visible_surfaces,
            "notebook_quality": notebook_quality,
            **context_links,
        },
        "visible_surfaces": visible_surfaces,
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": [],
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {
            "target_tab": "Notebooks",
            "target_anchor": "notebook-native-marimo-top",
            "artifact_id": notebook_artifact.id,
            "artifact_ids": [notebook_artifact.id],
            "asset_type": notebook_artifact.asset_type,
            "label": next_focus_label,
        },
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_notebook_update_{session.id}_{notebook_artifact.id}_{status}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source_artifact_id": notebook_artifact.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_status": status,
            "source": "main_agent_session_notebook_update",
        },
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="notebook_chat_turn_registered",
        role="harness",
        title="Notebook chat turn registered",
        content="Registered notebook availability in Agent Chat.",
        payload={
            "chat_artifact_id": chat_artifact.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_status": status,
        },
        artifact_id=chat_artifact.id,
        update_heartbeat=False,
    )
    annotate_agent_chat_turn_with_source_event(chat_artifact, event)
    update_agent_session_notebook_chat_payload(
        chat_artifact,
        visible_surfaces=visible_surfaces,
        context_links=context_links,
        notebook_quality=notebook_quality,
        actions=actions,
        linked_plan_node_id=linked_plan_node_id,
    )
    return chat_artifact


def update_agent_session_notebook_chat_payload(
    chat_artifact: Artifact,
    *,
    visible_surfaces: dict[str, Any],
    context_links: dict[str, str | None],
    notebook_quality: dict[str, Any],
    actions: list[dict[str, Any]],
    linked_plan_node_id: str | None,
) -> None:
    chat_visible_surfaces = notebook_registration_visible_surfaces_with_chat_artifact(
        visible_surfaces,
        chat_artifact_id=chat_artifact.id,
    )
    try:
        path = artifact_primary_path(chat_artifact)
        payload = loads_json(path.read_text(encoding="utf-8"), {})
        if isinstance(payload, dict):
            payload["visible_surfaces"] = chat_visible_surfaces
            payload["actions"] = actions
            response_brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
            payload["response_brief"] = {
                **response_brief,
                "research_plan_node_id": linked_plan_node_id,
                "visible_surfaces": chat_visible_surfaces,
                "notebook_quality": notebook_quality,
                **context_links,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass


def notebook_registration_visible_surfaces_with_chat_artifact(
    visible_surfaces: dict[str, Any],
    *,
    chat_artifact_id: str,
) -> dict[str, Any]:
    return {
        **visible_surfaces,
        "chat": {
            **visible_surfaces.get("chat", {}),
            "target_tab": "Home",
            "target_anchor": "agent-workspace",
            "artifact_id": chat_artifact_id,
        },
    }


def notebook_artifact_context_links_from_metadata(
    db: Session,
    *,
    project: Project,
    notebook_artifact: Artifact,
) -> dict[str, str | None]:
    metadata = loads_json(notebook_artifact.metadata_json, {})
    dataset_snapshot_id = metadata_text(metadata, "dataset_snapshot_id")
    run_id = metadata_text(metadata, "run_id")
    model_version_id = metadata_text(metadata, "model_version_id")
    run: ExperimentRun | None = None
    model_version: ModelVersion | None = None
    dataset_snapshot: DatasetSnapshot | None = None

    if run_id:
        candidate = db.get(ExperimentRun, run_id)
        if candidate is not None and candidate.project_id == project.id:
            run = candidate
            model_version_id = model_version_id or run.model_version_id
            dataset_snapshot_id = dataset_snapshot_id or run.dataset_snapshot_id
        else:
            run_id = None

    if model_version_id:
        candidate_model = db.get(ModelVersion, model_version_id)
        if candidate_model is not None and candidate_model.project_id == project.id:
            model_version = candidate_model
            if run_id and model_version.experiment_run_id and model_version.experiment_run_id != run_id:
                model_version = None
                model_version_id = None
            else:
                run_id = run_id or model_version.experiment_run_id
                dataset_snapshot_id = dataset_snapshot_id or model_version.dataset_snapshot_id
        else:
            model_version_id = None

    if dataset_snapshot_id:
        candidate_dataset = db.get(DatasetSnapshot, dataset_snapshot_id)
        if candidate_dataset is not None and candidate_dataset.project_id == project.id:
            dataset_snapshot = candidate_dataset
        else:
            dataset_snapshot_id = None

    if dataset_snapshot is not None:
        if run is not None and run.dataset_snapshot_id and run.dataset_snapshot_id != dataset_snapshot.id:
            dataset_snapshot_id = None
        if model_version is not None and model_version.dataset_snapshot_id and model_version.dataset_snapshot_id != dataset_snapshot.id:
            dataset_snapshot_id = None

    return {
        "dataset_snapshot_id": dataset_snapshot_id,
        "run_id": run_id,
        "model_version_id": model_version_id,
    }


def notebook_artifact_research_plan_node_id(db: Session, *, notebook_artifact: Artifact) -> str | None:
    if notebook_artifact.project_id is None:
        return None
    metadata = loads_json(notebook_artifact.metadata_json, {})
    metadata_node_id = metadata_text(metadata, "research_plan_node_id")
    if metadata_node_id:
        return metadata_node_id
    edge = db.scalar(
        select(LineageEdge)
        .where(
            LineageEdge.project_id == notebook_artifact.project_id,
            LineageEdge.to_asset_type == "artifact",
            LineageEdge.to_asset_id == notebook_artifact.id,
            LineageEdge.relation_type == "supports_plan_node",
        )
        .order_by(LineageEdge.created_at.desc())
    )
    if edge is None:
        return None
    edge_metadata = loads_json(edge.metadata_json, {})
    return metadata_text(edge_metadata, "node_id")


def metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def notebook_registration_chat_actions(
    *,
    notebook_artifact: Artifact,
    visible_surfaces: dict[str, Any],
    status: str,
    notebook_label: str,
    notebook_detail: str,
    japanese: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "type": "open_artifact",
            "status": status,
            "label": notebook_label,
            "target_tab": "Notebooks",
            "target_anchor": "notebook-native-marimo-top",
            "detail": notebook_detail,
            "artifact_id": notebook_artifact.id,
            "artifact_ids": [notebook_artifact.id],
            "asset_type": notebook_artifact.asset_type,
        }
    ]
    if "data" in visible_surfaces:
        data_surface = visible_surfaces["data"]
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "関連データを見る" if japanese else "Open related data",
                "target_tab": data_surface["target_tab"],
                "target_anchor": data_surface["target_anchor"],
                "detail": "このNotebookが説明しているDatasetへ移動します。" if japanese else "Open the Dataset linked to this notebook.",
                "artifact_id": notebook_artifact.id,
                "asset_type": notebook_artifact.asset_type,
                "entity_ids": [data_surface["dataset_snapshot_id"]],
            }
        )
    if "leaderboard" in visible_surfaces:
        leaderboard_surface = visible_surfaces["leaderboard"]
        entity_ids = [
            value
            for value in [leaderboard_surface.get("run_id"), leaderboard_surface.get("model_version_id")]
            if isinstance(value, str) and value.strip()
        ]
        actions.append(
            {
                "type": "open_surface",
                "status": "ready",
                "label": "関連モデル結果を見る" if japanese else "Open related model result",
                "target_tab": leaderboard_surface["target_tab"],
                "target_anchor": leaderboard_surface["target_anchor"],
                "detail": "このNotebookが説明しているRunまたはModel結果へ移動します。"
                if japanese
                else "Open the Run or Model result linked to this notebook.",
                "artifact_id": notebook_artifact.id,
                "asset_type": notebook_artifact.asset_type,
                "entity_ids": entity_ids,
            }
        )
    assets_surface = visible_surfaces["assets"]
    actions.append(
        {
            "type": "open_artifact",
            "status": "ready",
            "label": "Assetsで見る" if japanese else "Open in Assets",
            "target_tab": assets_surface["target_tab"],
            "target_anchor": assets_surface["target_anchor"],
            "detail": "Notebook source assetと関連成果物の棚へ移動します。" if japanese else "Open the notebook source asset shelf.",
            "artifact_id": notebook_artifact.id,
            "artifact_ids": [notebook_artifact.id],
            "asset_type": notebook_artifact.asset_type,
        }
    )
    return actions


def agent_session_notebook_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    notebook_artifact: Artifact,
    status: str,
) -> bool:
    return (
        latest_agent_session_notebook_chat_turn(
            db,
            project=project,
            session=session,
            notebook_artifact=notebook_artifact,
            status=status,
        )
        is not None
    )


def latest_agent_session_notebook_chat_turn(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    notebook_artifact: Artifact,
    status: str,
) -> Artifact | None:
    artifact_name = f"agent_session_notebook_update_{session.id}_{notebook_artifact.id}_{status}"
    artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.project_id == project.id,
            Artifact.asset_type == "agent_chat_turn",
            Artifact.name == artifact_name,
        )
        .order_by(Artifact.version.desc())
        .limit(1)
    )
    if artifact is None:
        return None
    metadata = loads_json(artifact.metadata_json, {})
    if metadata.get("source") != "main_agent_session_notebook_update":
        return None
    return artifact


def register_agent_session_attention_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    attention_key: str,
    status: str,
    message_kind: str,
    details: dict[str, Any] | None = None,
) -> Artifact | None:
    cleaned_key = attention_key.strip()[:240]
    if not cleaned_key:
        return None
    if agent_session_attention_chat_turn_exists(db, project=project, session=session, attention_key=cleaned_key):
        return None
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    details = details or {}
    assistant_message = attention_chat_message(message_kind, details=details, japanese=japanese)
    target_tab, target_anchor, action_label = attention_chat_action_target(message_kind, japanese=japanese)
    worker_events = attention_chat_worker_events(
        project=project,
        session=session,
        status=status,
        message_kind=message_kind,
        assistant_message=assistant_message,
        target_tab=target_tab,
        target_anchor=target_anchor,
        japanese=japanese,
    )
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": assistant_message,
        "intent": {
            "type": "agent_attention_event",
            "source": "main_agent_session_observation",
            "status": status,
            "message_kind": message_kind,
        },
        "actions": [
            {
                "type": "open_surface",
                "status": status,
                "label": action_label,
                "target_tab": target_tab,
                "target_anchor": target_anchor,
                "detail": assistant_message,
            }
        ],
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_attention_event.v1",
            "agent_session_id": session.id,
            "attention_key": cleaned_key,
            "status": status,
            "message_kind": message_kind,
            "details": details,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_agent_session",
            "status": "harness_fact",
        },
        "worker_events": worker_events,
        "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        "next_focus": {"target_tab": target_tab, "target_anchor": target_anchor, "label": action_label},
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_attention_{session.id}_{hashlib.sha1(cleaned_key.encode('utf-8')).hexdigest()[:12]}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "attention_key": cleaned_key,
            "message_kind": message_kind,
            "source": "main_agent_session_attention",
        },
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="attention_chat_turn_registered",
        role="harness",
        title="Attention event registered in Chat",
        content="Registered an agent attention event in Agent Chat.",
        payload={"chat_artifact_id": chat_artifact.id, "attention_key": cleaned_key, "message_kind": message_kind},
        artifact_id=chat_artifact.id,
        update_heartbeat=False,
    )
    annotate_agent_chat_turn_with_source_event(chat_artifact, event)
    return chat_artifact


def attention_chat_worker_events(
    *,
    project: Project,
    session: AgentSession,
    status: str,
    message_kind: str,
    assistant_message: str,
    target_tab: str,
    target_anchor: str,
    japanese: bool,
) -> list[dict[str, Any]]:
    if message_kind not in {"process_timeout", "turn_start_silence", "turn_recovery", "runner_unavailable"}:
        return []
    recovering = message_kind in {"process_timeout", "turn_start_silence", "turn_recovery"}
    headline = "Agentを復旧中" if japanese and recovering else "Agentが待機中" if japanese else "Agent is recovering" if recovering else "Agent is waiting"
    return [
        {
            "worker_id": f"agent-availability-{session.id}-{message_kind}",
            "display_name": "Agent Activity",
            "status": "recovering" if recovering else status,
            "headline": headline,
            "detail": assistant_message,
            "job_id": None,
            "job_type": "agent_session",
            "project_id": project.id,
            "target_tab": target_tab,
            "target_anchor": target_anchor,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
            "active": recovering,
            "human_description": {
                "source": "agent_attention",
                "title": "Agent Activity",
                "summary": assistant_message,
            },
            "token_usage": {"source": "not_applicable", "is_estimate": False, "series": []},
        }
    ]


def annotate_agent_chat_turn_with_source_event(chat_artifact: Artifact, event: AgentTranscriptEvent) -> None:
    try:
        path = artifact_primary_path(chat_artifact)
        payload = loads_json(path.read_text(encoding="utf-8"), {})
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        payload = {}
    if isinstance(payload, dict):
        response_brief = payload.get("response_brief") if isinstance(payload.get("response_brief"), dict) else {}
        payload["response_brief"] = {
            **response_brief,
            "source_transcript_event": {
                "id": event.id,
                "event_index": event.event_index,
                "event_type": event.event_type,
                "source": event.source,
            },
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    metadata = loads_json(chat_artifact.metadata_json, {})
    chat_artifact.metadata_json = dumps_json(
        {
            **metadata,
            "source_transcript_event_id": event.id,
            "source_transcript_event_index": event.event_index,
            "source_transcript_event_type": event.event_type,
        }
    )


def attention_chat_action_target(message_kind: str, *, japanese: bool) -> tuple[str, str, str]:
    if message_kind == "completed_waiting_for_input":
        return "Home", "agent-workspace", "次の入力を確認" if japanese else "Review next input"
    if message_kind == "progress_update_requested":
        return "Home", "agent-workspace", "状況を見る" if japanese else "Review status"
    if message_kind in {
        "runner_unavailable",
        "turn_recovery",
        "process_timeout",
        "turn_start_silence",
    }:
        return "Jobs", "agent-workspace", "状況を見る" if japanese else "Review status"
    if message_kind == "research_plan_human_attention_requested":
        return "Assumptions", "assumption-review", "質問を確認" if japanese else "Review question"
    if message_kind in {
        "notebook_context_registration_needed",
        "notebook_quality_repair_needed",
        "research_request_failed",
        "notebook_request_failed",
        "model_diagnostics_request_failed",
        "pilot_request_failed",
        "static_html_output_rejected",
        "notebook_source_rejected",
    }:
        if message_kind == "research_request_failed":
            return "Home", "agent-workspace", "状況を見る" if japanese else "Review status"
        if message_kind == "model_diagnostics_request_failed":
            return "Leaderboard", "result-readout", "診断を確認" if japanese else "Review diagnostics"
        if message_kind == "pilot_request_failed":
            return "Leaderboard", "pilot", "仮運用を確認" if japanese else "Review pilot"
        return "Notebooks", "notebook-native-marimo-top", "Notebookを確認" if japanese else "Review notebook"
    return "Home", "agent-workspace", "状況を見る" if japanese else "Review status"


def attention_chat_message(message_kind: str, *, details: dict[str, Any], japanese: bool) -> str:
    if message_kind == "completed_waiting_for_input":
        if japanese:
            return (
                "現在のデータで進められる分析、評価、モデリング、診断は完了しました。"
                "次に進むには、人間の追加指示または追加データが必要です。"
                "例: テストデータで推論する、評価分割や指標を見直す、アンサンブルや高度な特徴量エンジニアリングを追加する、運用サンプルや実測値で仮運用評価を始める。"
            )
        return (
            "The available analysis, evaluation, modeling, and diagnostics are complete for the current data. "
            "To continue, provide a new instruction or additional data. Examples: run prediction on test data, "
            "revise the evaluation split or metric, add ensembles or deeper feature engineering, or start pilot validation with operational samples and outcomes."
        )
    if message_kind == "runner_unavailable":
        if japanese:
            return "分析エージェントをまだ起動できません。作業状態は保持されています。"
        return "The analysis agent is not available yet. The work state is preserved."
    if message_kind == "turn_recovery":
        if japanese:
            return "作業プロセスが一度停止しました。Full AutoはONのまま、同じ状態から続けます。"
        return "The work process stopped once. Full Auto remains on and will continue from the same state."
    if message_kind == "process_timeout":
        idle_seconds = details.get("idle_timeout_seconds")
        idle_text = f"{int(idle_seconds) // 60}分" if isinstance(idle_seconds, (int, float)) else "しばらく"
        if japanese:
            return f"分析エージェントから{idle_text}出力がありません。作業状態を保ったまま再開します。"
        if isinstance(idle_seconds, (int, float)):
            idle_text_en = f"{int(idle_seconds) // 60} minutes"
        else:
            idle_text_en = "a while"
        return f"The analysis agent produced no output for {idle_text_en}. Tablex will continue from the preserved work state."
    if message_kind == "turn_start_silence":
        idle_seconds = details.get("idle_timeout_seconds")
        idle_text = f"{int(idle_seconds) // 60}分" if isinstance(idle_seconds, (int, float)) else "しばらく"
        if japanese:
            return f"作業開始後、進捗イベントが{idle_text}届いていません。作業状態を保ったまま再開します。"
        idle_text_en = f"{int(idle_seconds) // 60} minutes" if isinstance(idle_seconds, (int, float)) else "a while"
        return f"No progress event arrived for {idle_text_en} after startup. Tablex will continue from the preserved work state."
    if message_kind == "progress_update_requested":
        stale_seconds = details.get("stale_after_seconds")
        stale_text = f"{int(stale_seconds) // 60}分" if isinstance(stale_seconds, (int, float)) else "しばらく"
        if japanese:
            return f"進捗出力が{stale_text}以上届いていないため、TablexからCodexへ現在状況の更新を依頼しました。"
        stale_text_en = f"{int(stale_seconds) // 60} minutes" if isinstance(stale_seconds, (int, float)) else "a while"
        return f"No progress output arrived for over {stale_text_en}, so Tablex asked Codex for a current status update."
    if message_kind == "research_plan_request_failed":
        if japanese:
            return (
                "作業計画の表示はまだ更新していません。分析は続いています。"
                "次の進捗で現在地または判断結果を反映します。"
            )
        return (
            "The visible work plan has not been updated yet. The analysis is still running. "
            "The next progress update will show the current position or the resulting decision."
        )
    if message_kind == "research_plan_human_attention_requested":
        question = str(details.get("question") or "").strip()
        can_proceed = details.get("can_proceed_without_answer")
        if japanese:
            suffix = (
                "回答がなくても仮定を置いて進めます。"
                if can_proceed is True
                else "この確認は次の判断に影響します。"
            )
            return f"Codexから確認したい点があります。{question} {suffix}".strip()
        suffix = (
            "If no answer arrives, Codex can continue with an explicit assumption."
            if can_proceed is True
            else "This answer affects the next decision."
        )
        return f"Codex has a question for you. {question} {suffix}".strip()
    if message_kind == "research_plan_contract_needs_revision":
        if japanese:
            return (
                "Research Planを読みやすい章立てに整理し直しています。細かい試行はトップレベルではなく、"
                "Notebook、Leaderboard、subtask、artifact linkに寄せて追跡します。"
            )
        return (
            "The Research Plan is being cleaned up into readable chapters. Fine-grained attempts should live in notebooks, "
            "leaderboard entries, subtasks, and artifact links instead of the top-level plan."
        )
    if message_kind == "research_request_failed":
        if japanese:
            return (
                "従来知見の調査結果はまだ表示に反映していません。表示済みの計画や成果物はそのまま保持し、"
                "分析は続いています。"
            )
        return (
            "The prior-knowledge research result has not been reflected in the visible workspace yet. "
            "Existing plans and artifacts are unchanged, and the analysis is continuing."
        )
    if message_kind == "notebook_request_failed":
        request_id = str(details.get("request_id") or "").strip()
        request_label = f" (`{request_id}`)" if request_id else ""
        if japanese:
            return f"Notebook登録に失敗しました{request_label}。未完成の成果物としては表示せず、Codexが修正します。"
        return f"Notebook registration failed{request_label}. It is not shown as complete; Codex will repair it."
    if message_kind == "model_diagnostics_request_failed":
        if japanese:
            return (
                "モデル診断はまだ表示に反映していません。表示済みの結果はそのまま保持し、分析は続いています。"
            )
        return (
            "The model diagnostics result has not been reflected in the visible workspace yet. "
            "Existing visible results are unchanged, and the analysis is continuing."
        )
    if message_kind == "pilot_request_failed":
        if japanese:
            return (
                "仮運用の監査結果はまだ表示に反映していません。表示済みの予測・実測結果はそのまま保持し、"
                "分析は続いています。"
            )
        return (
            "The pilot audit result has not been reflected in the visible workspace yet. "
            "Existing prediction and outcome results are unchanged, and the analysis is continuing."
        )
    if message_kind == "notebook_context_registration_needed":
        count = details.get("notebook_count")
        count_text = str(int(count)) if isinstance(count, (int, float)) else "some"
        if japanese:
            return (
                f"{count_text}件のmarimo Notebookは開けますが、どのデータ・モデル・ResearchPlanに属するかの"
                "検証済みリンクがまだありません。作業が続くと、関連するデータ・モデル・計画から開けるように整理されます。"
            )
        return (
            f"{count_text} marimo notebook source(s) can be opened, but their Dataset, Run, Model, or ResearchPlan context "
            "has not been verified yet. As the work continues, those links will be organized across the related project surfaces."
        )
    if message_kind == "notebook_quality_repair_needed":
        count = details.get("notebook_count")
        count_text = f"{int(count)}件" if isinstance(count, (int, float)) else "いくつか"
        workspace_paths = details.get("workspace_paths") if isinstance(details.get("workspace_paths"), list) else []
        versions = details.get("notebook_versions") if isinstance(details.get("notebook_versions"), list) else []
        notebook_labels = [
            f"`{Path(path).name}`{f' v{versions[index]}' if index < len(versions) else ''}"
            for index, path in enumerate(workspace_paths[:3])
            if isinstance(path, str) and path.strip()
        ]
        label_text = ", ".join(notebook_labels)
        if japanese:
            return (
                f"Notebookは修正が必要です{f': {label_text}' if label_text else f'（{count_text}）'}。"
                "人が読む成果物としては図や品質manifestが不足しています。"
                "作業は継続中で、次の進捗で修正されたNotebookまたは判断結果が反映されます。"
            )
        return (
            f"Notebook revision required{f': {label_text}' if label_text else ''}. "
            "The quality manifest shows it is not ready as a human-facing deliverable. "
            "The work is continuing, and the next progress update will show the revised notebook or the resulting decision."
        )
    if message_kind == "static_html_output_rejected":
        path = str(details.get("workspace_relative_path") or "").strip()
        if japanese:
            return (
                f"`{path}` はNotebookとして登録しませんでした。"
                "静的HTMLではなく、native marimoで開けるPython notebook sourceを保存してください。"
            )
        return (
            f"`{path}` was not registered as a Tablex notebook artifact. "
            "Save a native marimo Python notebook source instead of static HTML."
        )
    if message_kind == "notebook_source_rejected":
        path = str(details.get("workspace_relative_path") or "").strip()
        if japanese:
            return (
                f"`{path}` はNotebookとして登録しませんでした。"
                "native marimoで開けるPython notebook sourceではないため、修正対象として扱います。"
            )
        return (
            f"`{path}` was not registered as a notebook. "
            "It is not a native marimo Python source, so Codex receives this as a repair target."
        )
    return "Agent attention is needed." if not japanese else "Agentの状態確認が必要です。"


def agent_session_attention_chat_turn_exists(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    attention_key: str,
) -> bool:
    cutoff = utc_now() - timedelta(minutes=30)
    recent_chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .where(Artifact.created_at >= cutoff)
            .order_by(Artifact.created_at.desc())
            .limit(100)
        ).all()
    )
    for artifact in recent_chat_artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if (
            metadata.get("source") == "main_agent_session_attention"
            and metadata.get("agent_session_id") == session.id
            and metadata.get("attention_key") == attention_key
        ):
            return True
    return False


NOTEBOOK_EVIDENCE_ASSET_TYPES = {
    "analysis_notebook",
    "marimo_notebook",
}
REPORT_EVIDENCE_ASSET_TYPES = {
    "agent_session_report",
    "understanding_report",
    "experiment_report",
    "report",
}
CHAT_UPDATE_STATE_ARTIFACT_TYPES = {
    "analysis_notebook",
    "marimo_notebook",
    "research_findings_report",
    "research_findings_markdown_report",
    "research_report_figure",
    "experiment_report",
    "understanding_report",
    "report",
    "prediction_pipeline",
    "pilot_prediction_batch",
    "pilot_outcome_batch",
    "pilot_scoring_report",
    "validation_scheme_audit",
    "model_diagnostics_artifact_pack",
}


def chat_update_actions_from_research_plan_evidence(
    db: Session,
    *,
    project: Project,
    japanese: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    revision = latest_research_plan_revision(db, project_id=project.id)
    if revision is None:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}
    document = research_plan_revision_document(revision)
    raw_blocks = document.get("timeline_blocks") if isinstance(document, dict) else None
    links = research_plan_evidence_links(db, revision=revision, raw_blocks=raw_blocks)
    if not links:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}

    notebook_link = first_evidence_link(links, link_types={"artifact"}, asset_types=NOTEBOOK_EVIDENCE_ASSET_TYPES)
    run_link = first_evidence_link(links, link_types={"experiment_run"})
    report_link = first_evidence_link(links, link_types={"artifact"}, asset_types=REPORT_EVIDENCE_ASSET_TYPES)

    actions: list[dict[str, Any]] = []
    if notebook_link is not None:
        artifact_id = notebook_link.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            action_artifact_id, action_artifact_ids, action_detail = notebook_action_artifact_targets(
                db,
                project_id=project.id,
                evidence_artifact_id=artifact_id,
                fallback_detail=evidence_link_detail(notebook_link),
            )
            actions.append(
                {
                    "type": "open_artifact",
                    "status": "ready",
                    "label": "ノートブックを開く" if japanese else "Open notebook",
                    "target_tab": "Notebooks",
                    "target_anchor": "notebook-native-marimo-top",
                    "detail": action_detail,
                    "artifact_id": action_artifact_id,
                    "artifact_ids": action_artifact_ids,
                    "asset_type": notebook_link.get("asset_type"),
                    "research_plan_node_id": notebook_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if run_link is not None:
        run_id = run_link.get("run_id")
        if isinstance(run_id, str) and run_id:
            actions.append(
                {
                    "type": "open_surface",
                    "status": "ready",
                    "label": "リーダーボードを見る" if japanese else "Open leaderboard",
                    "target_tab": "Leaderboard",
                    "target_anchor": "result-readout",
                    "detail": evidence_link_detail(run_link),
                    "entity_ids": [run_id],
                    "run_id": run_id,
                    "research_plan_node_id": run_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if report_link is not None:
        artifact_id = report_link.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            actions.append(
                {
                    "type": "open_artifact",
                    "status": "ready",
                    "label": "レポートを開く" if japanese else "Open report",
                    "target_tab": "Assets",
                    "target_anchor": "assets-artifact-preview",
                    "detail": evidence_link_detail(report_link),
                    "artifact_id": artifact_id,
                    "artifact_ids": [artifact_id],
                    "asset_type": report_link.get("asset_type"),
                    "research_plan_node_id": report_link.get("node_id"),
                    "source": "research_plan_completion_evidence",
                }
            )
    if not actions:
        return [], {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}
    first = actions[0]
    next_focus = {
        "target_tab": first.get("target_tab") or "Home",
        "target_anchor": first.get("target_anchor") or "agent-workspace",
        "label": first.get("label") or ("Agent workspace"),
    }
    for key in ("artifact_id", "artifact_ids", "asset_type", "entity_ids", "run_id"):
        if first.get(key) is not None:
            next_focus[key] = first.get(key)
    return actions, next_focus


def chat_action_output_identity(action: dict[str, Any]) -> tuple[str, str, str, str] | None:
    artifact_id = action.get("artifact_id")
    run_id = action.get("run_id")
    entity_id = ""
    entity_ids = action.get("entity_ids")
    if isinstance(entity_ids, list):
        entity_id = next((item for item in entity_ids if isinstance(item, str) and item), "")
    output_id = artifact_id if isinstance(artifact_id, str) and artifact_id else run_id
    if not isinstance(output_id, str) or not output_id:
        output_id = entity_id
    if not output_id:
        return None
    return (
        "registered_output",
        str(action.get("target_tab") or ""),
        str(action.get("target_anchor") or ""),
        output_id,
    )


def unannounced_research_plan_actions(
    db: Session,
    *,
    project: Project,
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    announced: set[tuple[str, str, str, str]] = set()
    chat_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(500)
        ).all()
    )
    for chat_artifact in chat_artifacts:
        try:
            payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
        except OSError:
            continue
        prior_actions = payload.get("actions") if isinstance(payload, dict) else None
        if not isinstance(prior_actions, list):
            continue
        for prior_action in prior_actions:
            if not isinstance(prior_action, dict):
                continue
            identity = chat_action_output_identity(prior_action)
            if identity is not None:
                announced.add(identity)
    return [
        action
        for action in actions
        if action.get("source") != "research_plan_completion_evidence"
        or chat_action_output_identity(action) not in announced
    ]


def notebook_action_artifact_targets(
    db: Session,
    *,
    project_id: str,
    evidence_artifact_id: str,
    fallback_detail: str,
) -> tuple[str, list[str], str]:
    evidence_artifact = db.get(Artifact, evidence_artifact_id)
    if evidence_artifact is None or evidence_artifact.project_id != project_id:
        return evidence_artifact_id, [evidence_artifact_id], fallback_detail

    if evidence_artifact.asset_type in NATIVE_NOTEBOOK_ASSET_TYPES:
        return evidence_artifact.id, [evidence_artifact.id], evidence_artifact.name

    return evidence_artifact.id, [evidence_artifact.id], evidence_artifact.name or fallback_detail


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def first_evidence_link(
    links: list[dict[str, Any]],
    *,
    link_types: set[str],
    asset_types: set[str] | None = None,
) -> dict[str, Any] | None:
    for link in reversed(links):
        link_type = link.get("link_type")
        if not isinstance(link_type, str) or link_type not in link_types:
            continue
        if asset_types is not None:
            asset_type = link.get("asset_type")
            if not isinstance(asset_type, str) or asset_type not in asset_types:
                continue
        return link
    return None


def evidence_link_detail(link: dict[str, Any]) -> str:
    for key in ("artifact_name", "role", "run_id", "artifact_id"):
        value = link.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "ResearchPlan evidence"


def pending_main_session_chat_job_exists(db: Session, *, project: Project, session: AgentSession) -> bool:
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.project_id == project.id,
                Job.job_type == "agent_chat_turn",
                ~Job.status.in_(TERMINAL_JOB_STATUSES),
            )
            .order_by(Job.created_at.asc())
            .limit(100)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        if payload.get("delivered_agent_session_id") == session.id:
            return True
    return False


def chat_action_signature(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signature_keys = (
        "type",
        "status",
        "target_tab",
        "target_anchor",
        "artifact_id",
        "artifact_ids",
        "asset_type",
        "entity_ids",
        "run_id",
        "research_plan_node_id",
    )
    return [
        {key: action.get(key) for key in signature_keys if action.get(key) is not None}
        for action in actions
        if isinstance(action, dict)
    ]


def next_focus_signature(next_focus: dict[str, Any]) -> dict[str, Any]:
    return {
        key: next_focus.get(key)
        for key in ("target_tab", "target_anchor", "artifact_id", "artifact_ids", "asset_type", "entity_ids", "run_id")
        if next_focus.get(key) is not None
    }


def latest_agent_chat_update_state_fingerprint(db: Session, *, project: Project, session: AgentSession) -> str | None:
    artifact = latest_agent_chat_update_artifact_for_state(db, project=project, session=session)
    if artifact is None:
        return None
    metadata = loads_json(artifact.metadata_json, {})
    fingerprint = metadata.get("visible_state_fingerprint")
    return fingerprint if isinstance(fingerprint, str) and fingerprint else None


def latest_agent_chat_update_artifact_for_state(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    visible_state_fingerprint: str | None = None,
) -> Artifact | None:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(50)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_codex_session_chat_update":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        fingerprint = metadata.get("visible_state_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            continue
        if visible_state_fingerprint is not None and fingerprint != visible_state_fingerprint:
            continue
        return artifact
    return None


def agent_chat_turn_assistant_message(chat_artifact: Artifact) -> str | None:
    try:
        payload = loads_json(artifact_primary_path(chat_artifact).read_text(encoding="utf-8"), {})
    except OSError:
        return None
    message = payload.get("assistant_message") if isinstance(payload, dict) else None
    return message if isinstance(message, str) and message.strip() else None


def latest_agent_chat_update_artifact_for_message(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    message: str,
) -> Artifact | None:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(100)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("source") != "main_codex_session_chat_update":
            continue
        if metadata.get("agent_session_id") != session.id:
            continue
        if agent_chat_turn_assistant_message(artifact) == message:
            return artifact
    return None


def chat_update_visible_state_fingerprint(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    actions: list[dict[str, Any]],
    next_focus: dict[str, Any],
) -> str:
    revision = latest_research_plan_revision(db, project_id=project.id)
    current_work = latest_research_plan_current_work(db, project_id=project.id)
    dataset_ids = sorted(
        item.id
        for item in db.scalars(
            select(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id).order_by(DatasetSnapshot.id.asc()).limit(500)
        ).all()
    )
    run_ids = sorted(
        item.id
        for item in db.scalars(
            select(ExperimentRun).where(ExperimentRun.project_id == project.id).order_by(ExperimentRun.id.asc()).limit(500)
        ).all()
    )
    model_version_ids = sorted(
        item.id
        for item in db.scalars(
            select(ModelVersion).where(ModelVersion.project_id == project.id).order_by(ModelVersion.id.asc()).limit(500)
        ).all()
    )
    state_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id, Artifact.asset_type.in_(CHAT_UPDATE_STATE_ARTIFACT_TYPES))
            .order_by(Artifact.id.asc())
            .limit(1000)
        ).all()
    )
    artifact_ids_by_type: dict[str, list[str]] = {}
    for state_artifact in state_artifacts:
        artifact_ids_by_type.setdefault(state_artifact.asset_type, []).append(state_artifact.id)
    payload = {
        "project": {
            "id": project.id,
            "phase": project.current_phase,
            "autonomy_mode": project.autonomy_mode,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "primary_dataset_snapshot_id": project.primary_dataset_snapshot_id,
        },
        "session": {"id": session.id},
        "research_plan": {
            "revision_id": revision.id if revision is not None else None,
            "revision_index": revision.revision_index if revision is not None else None,
            "current_revision_id": current_work.revision_id if current_work is not None else None,
            "current_node_id": current_work.node_id if current_work is not None else None,
        },
        "datasets": dataset_ids,
        "experiment_runs": run_ids,
        "model_versions": model_version_ids,
        "artifacts": artifact_ids_by_type,
        "actions": chat_action_signature(actions),
        "next_focus": next_focus_signature(next_focus),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def maybe_register_chat_update_from_workspace_output(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    path: Path,
    artifact: Artifact,
) -> None:
    if not is_chat_update_path(path):
        return
    try:
        message = chat_update_message_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return
    if not message:
        return
    response_locale = latest_project_response_locale(db, project)
    japanese = locale_is_japanese(response_locale)
    actions, next_focus = chat_update_actions_from_research_plan_evidence(db, project=project, japanese=japanese)
    actions = unannounced_research_plan_actions(db, project=project, actions=actions)
    if actions:
        first_action = actions[0]
        next_focus = {
            "target_tab": first_action.get("target_tab") or "Home",
            "target_anchor": first_action.get("target_anchor") or "agent-workspace",
            "label": first_action.get("label") or "Agent workspace",
        }
        for key in ("artifact_id", "artifact_ids", "asset_type", "entity_ids", "run_id"):
            if first_action.get(key) is not None:
                next_focus[key] = first_action.get(key)
    else:
        next_focus = {"target_tab": "Home", "target_anchor": "agent-workspace", "label": "Agent workspace"}
    visible_state_fingerprint = chat_update_visible_state_fingerprint(
        db,
        project=project,
        session=session,
        actions=actions,
        next_focus=next_focus,
    )
    pending_chat_job = pending_main_session_chat_job_exists(db, project=project, session=session)
    previous_same_message = latest_agent_chat_update_artifact_for_message(
        db,
        project=project,
        session=session,
        message=message,
    )
    if previous_same_message is not None and not pending_chat_job:
        return
    latest_same_state_chat = latest_agent_chat_update_artifact_for_state(
        db,
        project=project,
        session=session,
        visible_state_fingerprint=visible_state_fingerprint,
    )
    if latest_same_state_chat is not None:
        previous_message = agent_chat_turn_assistant_message(latest_same_state_chat)
        if previous_message == message:
            if pending_chat_job:
                complete_pending_chat_job_from_main_session_update(
                    db,
                    project=project,
                    session=session,
                    chat_artifact=latest_same_state_chat,
                    message=message,
                )
            return
        if not pending_chat_job:
            return
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": "",
        "assistant_message": message[:4000],
        "intent": {
            "type": "autonomous_agent_progress_report",
            "source": "main_codex_session",
            "routing_policy": "codex_authored_human_update",
        },
        "actions": actions,
        "action_summary": {},
        "response_brief": {
            "schema_version": "agent_progress_report_brief.v1",
            "agent_session_id": session.id,
            "source_artifact_id": artifact.id,
            "workspace_relative_path": str(
                path.relative_to(resolve_runtime_data_path(session.workspace_path or path.parent))
            ),
            "linked_action_count": len(actions),
            "visible_state_fingerprint": visible_state_fingerprint,
        },
        "response_composer": {
            "schema_version": "agent_response_composer.v1",
            "mode": "main_codex_session",
            "status": "codex_authored",
        },
        "worker_events": [],
        "token_usage": {"source": "codex_cli_transcript", "is_estimate": True, "series": []},
        "next_focus": next_focus,
    }
    chat_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_session_chat_update_{session.id}_{artifact.id}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "source_artifact_id": artifact.id,
            "source": "main_codex_session_chat_update",
            "visible_state_fingerprint": visible_state_fingerprint,
        },
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="chat_update_registered",
        role="harness",
        title="Codex progress report registered",
        content="Registered Codex-authored human progress report for Agent Chat.",
        payload={
            "chat_artifact_id": chat_artifact.id,
            "source_artifact_id": artifact.id,
            "visible_state_fingerprint": visible_state_fingerprint,
        },
        artifact_id=chat_artifact.id,
    )
    annotate_agent_chat_turn_with_source_event(chat_artifact, event)
    complete_pending_chat_job_from_main_session_update(
        db,
        project=project,
        session=session,
        chat_artifact=chat_artifact,
        message=message,
    )


def complete_pending_chat_job_from_main_session_update(
    db: Session,
    *,
    project: Project,
    session: AgentSession,
    chat_artifact: Artifact,
    message: str,
) -> Job | None:
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.project_id == project.id,
                Job.job_type == "agent_chat_turn",
                ~Job.status.in_(TERMINAL_JOB_STATUSES),
            )
            .order_by(Job.created_at.asc())
            .limit(100)
        ).all()
    )
    for job in jobs:
        payload = loads_json(job.input_json, {})
        if payload.get("delivered_agent_session_id") != session.id:
            continue
        mark_job_succeeded(
            job,
            {
                "schema_version": "agent_chat_turn_completion.v1",
                "status": "answered_by_main_codex_session",
                "agent_session_id": session.id,
                "progress_artifact_id": chat_artifact.id,
                "response_locale": payload.get("locale") if isinstance(payload.get("locale"), str) else None,
                "message_preview": message[:280],
            },
        )
        return job
    return None


def chat_update_message_from_text(text: str, limit: int = 900) -> str:
    stripped = text.strip()
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", stripped) if item.strip()]
    message = paragraphs[-1] if paragraphs else stripped
    if len(message) <= limit:
        return message
    return message[-limit:].lstrip()
