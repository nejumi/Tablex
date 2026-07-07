from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, Artifact, Project
from tabular_harness.services.agent_outputs import (
    asset_type_for_session_output,
    metadata_for_session_output,
    session_output_artifact_name,
    session_output_rejection_message_kind,
    session_output_rejection_reason,
    should_register_session_output,
    should_skip_session_output,
)
from tabular_harness.services.agent_requests.research_plan import research_plan_request_failure_attention_key
from tabular_harness.services.agent_session_chat import (
    agent_session_attention_chat_turn_exists,
    attach_registered_session_notebooks_to_current_research_plan,
    maybe_defer_agent_session_notebook_registration,
    maybe_register_chat_update_from_workspace_output,
    register_agent_session_attention_chat_turn,
    register_agent_session_notebook_source_output,
    register_pending_agent_session_notebooks,
    request_context_for_auto_registered_notebooks,
    request_quality_repair_for_session_notebooks,
)
from tabular_harness.services.agent_session_inbox import (
    write_research_plan_artifact_rejection_to_workspace_inbox,
    write_session_output_rejection_to_workspace_inbox,
)
from tabular_harness.services.agent_transcript import append_session_event
from tabular_harness.services.agent_workspace import latest_project_response_locale
from tabular_harness.services.artifacts import LocalArtifactStore, next_artifact_version, register_artifact
from tabular_harness.services.research_plans import ResearchPlanValidationError, commit_research_plan_artifact_revision


def latest_session_artifact_for_workspace_path(
    db: Session,
    *,
    project_id: str,
    workspace: Path,
    workspace_path: str,
) -> Artifact | None:
    candidate = Path(workspace_path)
    if candidate.is_absolute():
        try:
            relative_path = str(candidate.relative_to(workspace))
        except ValueError:
            relative_path = str(candidate)
    else:
        relative_path = str(candidate)
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at.desc())
            .limit(300)
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("workspace_relative_path") == relative_path:
            return artifact
    return None


def ingest_session_workspace_outputs_impl(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    allow_notebook_auto_registration: bool = True,
    project_session_still_registered_fn: Callable[..., bool],
    process_data_tool_requests_fn: Callable[..., None],
    process_research_plan_tool_requests_fn: Callable[..., None],
    process_research_tool_requests_fn: Callable[..., None],
    maybe_request_research_plan_contract_revision_fn: Callable[..., None],
    process_notebook_tool_requests_fn: Callable[..., None],
    process_experiment_result_requests_fn: Callable[..., None],
    process_model_diagnostics_tool_requests_fn: Callable[..., None],
    process_pipeline_tool_requests_fn: Callable[..., None],
    process_pilot_tool_requests_fn: Callable[..., None],
    ingest_registered_session_experiment_artifacts_fn: Callable[..., None],
) -> None:
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    output_roots = [workspace / "outputs", workspace / "reports", workspace / "notebooks", workspace / "artifacts"]
    for root in output_roots:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
                return
            if session_output_rejection_reason(path):
                register_rejected_session_output(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    workspace=workspace,
                    path=path,
                    reason=session_output_rejection_reason(path) or "unsupported_output",
                )
                continue
            if should_skip_session_output(path):
                continue
            metadata = {
                "project_id": project.id,
                "agent_session_id": session.id,
                "workspace_relative_path": str(path.relative_to(workspace)),
                "source": "main_agent_session_workspace",
                **metadata_for_session_output(path),
            }
            name = session_output_artifact_name(session.id, path.relative_to(workspace))
            asset_type = asset_type_for_session_output(path)
            existing = db.scalar(
                select(Artifact).where(
                    Artifact.project_id == project.id,
                    Artifact.asset_type == asset_type,
                    Artifact.name == name,
                ).order_by(Artifact.version.desc())
            )
            if existing is not None and not should_register_session_output(path, existing):
                continue
            version = next_artifact_version(db, project.id, asset_type, name)
            target_dir, stored, content_hash = store.store_existing_file(
                org_id=project.org_id,
                project_id=project.id,
                asset_type=asset_type,
                name=name,
                version=version,
                source_path=path,
                filename=path.name,
                metadata={**metadata, "primary_path": str(path)},
            )
            artifact = register_artifact(
                db,
                project_id=project.id,
                asset_type=asset_type,
                name=name,
                uri=str(target_dir),
                content_hash=content_hash,
                size_bytes=stored.size_bytes,
                metadata={**metadata, "primary_path": str(target_dir / path.name)},
                version=version,
                org_id=project.org_id,
            )
            append_session_event(
                db,
                session,
                source="tablex_sidecar",
                event_type="artifact_registered",
                role="harness",
                title="Workspace output registered",
                content=f"Registered `{path.relative_to(workspace)}` as `{asset_type}`.",
                payload=metadata,
                artifact_id=artifact.id,
            )
            maybe_register_chat_update_from_workspace_output(
                db,
                store=store,
                project=project,
                session=session,
                path=path,
                artifact=artifact,
            )
            if asset_type == "research_plan":
                try:
                    commit_research_plan_artifact_revision(
                        db,
                        artifact=artifact,
                        reason=f"Committed Codex-authored workspace ResearchPlan from {path.relative_to(workspace)}.",
                        strict_validation=True,
                    )
                except ResearchPlanValidationError as exc:
                    rejection_event = append_session_event(
                        db,
                        session,
                        source="tablex_sidecar",
                        event_type="research_plan_artifact_rejected",
                        role="harness",
                        title="ResearchPlan artifact rejected",
                        content=str(exc),
                        payload={
                            "artifact_id": artifact.id,
                            "workspace_relative_path": str(path.relative_to(workspace)),
                            "issues": exc.issues[:12],
                        },
                        artifact_id=artifact.id,
                        update_heartbeat=False,
                    )
                    write_research_plan_artifact_rejection_to_workspace_inbox(
                        session,
                        event=rejection_event,
                        artifact=artifact,
                        workspace_relative_path=str(path.relative_to(workspace)),
                        issues=exc.issues,
                    )
                    register_agent_session_attention_chat_turn(
                        db,
                        store=store,
                        project=project,
                        session=session,
                        attention_key=research_plan_request_failure_attention_key(
                            operation="commit_revision",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            issues=exc.issues,
                        ),
                        status="needs_attention",
                        message_kind="research_plan_request_failed",
                        details={
                            "request_id": artifact.name,
                            "operation": "commit_revision",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:1200],
                            "issues": exc.issues[:8],
                            "workspace_relative_path": str(path.relative_to(workspace)),
                        },
                    )
            if allow_notebook_auto_registration:
                register_agent_session_notebook_source_output(
                    db,
                    store=store,
                    session=session,
                    artifact=artifact,
                )
            else:
                maybe_defer_agent_session_notebook_registration(db, session=session, artifact=artifact)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_data_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_research_plan_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_research_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    maybe_request_research_plan_contract_revision_fn(
        db,
        store=store,
        project=project,
        session=session,
        locale=latest_project_response_locale(db, project),
    )
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_notebook_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_experiment_result_requests_fn(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        append_event=append_session_event,
    )
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_model_diagnostics_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_pipeline_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    process_pilot_tool_requests_fn(db, store=store, project=project, session=session, workspace=workspace)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    ingest_registered_session_experiment_artifacts_fn(db, store=store, project=project, session=session)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    attach_registered_session_notebooks_to_current_research_plan(db, project=project, session=session)
    if not project_session_still_registered_fn(db, project_id=project.id, session_id=session.id):
        return
    if allow_notebook_auto_registration:
        register_pending_agent_session_notebooks(db, store=store, project=project, session=session)
    request_context_for_auto_registered_notebooks(db, store=store, project=project, session=session, workspace=workspace)
    request_quality_repair_for_session_notebooks(db, store=store, project=project, session=session, workspace=workspace)


def register_rejected_session_output(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    path: Path,
    reason: str,
) -> None:
    relative_path = str(path.relative_to(workspace))
    attention_key = f"session_output_rejected:{session.id}:{relative_path}:{reason}"
    if agent_session_attention_chat_turn_exists(db, project=project, session=session, attention_key=attention_key):
        return
    append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="workspace_output_rejected",
        role="harness",
        title="Workspace output rejected",
        content=f"Rejected `{relative_path}`: {reason}.",
        payload={
            "workspace_relative_path": relative_path,
            "reason": reason,
            "policy": "native_marimo_source_required",
        },
        update_heartbeat=False,
    )
    write_session_output_rejection_to_workspace_inbox(
        workspace,
        workspace_relative_path=relative_path,
        reason=reason,
    )
    register_agent_session_attention_chat_turn(
        db,
        store=store,
        project=project,
        session=session,
        attention_key=attention_key,
        status="needs_attention",
        message_kind=session_output_rejection_message_kind(reason),
        details={
            "workspace_relative_path": relative_path,
            "reason": reason,
        },
    )
