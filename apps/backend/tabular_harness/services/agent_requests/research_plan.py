from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, Artifact, Project, utc_now
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.research_plans import (
    ResearchPlanValidationError,
    attach_research_plan_artifact,
    commit_research_plan_revision,
    request_research_plan_human_attention,
    research_plan_current_work_payload,
    set_research_plan_current_work,
)

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
RESEARCH_PLAN_REQUESTS_DIR = "research_plan"
RESEARCH_PLAN_REQUEST_SCHEMA_VERSION = "tablex_research_plan_request.v1"
RESEARCH_PLAN_ACK_SCHEMA_VERSION = "tablex_research_plan_ack.v1"

AppendSessionEvent = Callable[..., Any]
RegisterAttention = Callable[..., Any]
LatestArtifactForWorkspacePath = Callable[..., Artifact | None]
WriteResearchPlanRejection = Callable[..., Any]


def research_plan_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / RESEARCH_PLAN_REQUESTS_DIR


def research_plan_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / RESEARCH_PLAN_REQUESTS_DIR


def process_research_plan_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    latest_artifact_for_workspace_path_fn: LatestArtifactForWorkspacePath,
    write_rejection_fn: WriteResearchPlanRejection,
    append_session_event_fn: AppendSessionEvent | None = None,
    register_attention_fn: RegisterAttention | None = None,
) -> None:
    request_dir = research_plan_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = research_plan_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    pending_paths = [
        path
        for path in sorted(item for item in request_dir.glob("*.json") if item.is_file())
        if not (ack_dir / f"{path.stem}.ack.json").exists()
    ]
    pending_paths.sort(key=research_plan_request_processing_order)
    for path in pending_paths:
        ack_path = ack_dir / f"{path.stem}.ack.json"
        request_id = path.stem
        operation = ""
        body: dict[str, Any] = {}
        try:
            raw_text = path.read_text(encoding="utf-8")
            payload = loads_json(raw_text, {})
            if not isinstance(payload, dict):
                raise ValueError("ResearchPlan request must be a JSON object")
            request_id = str(payload.get("request_id") or path.stem)
            schema_version = str(payload.get("schema_version") or "")
            if schema_version != RESEARCH_PLAN_REQUEST_SCHEMA_VERSION:
                expected = RESEARCH_PLAN_REQUEST_SCHEMA_VERSION
                raise ValueError(
                    f"Unsupported ResearchPlan request schema_version: {schema_version or '<missing>'}; expected {expected}"
                )
            operation = str(payload.get("operation") or payload.get("tool") or "").strip()
            body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            result = execute_research_plan_tool_request(
                db,
                project=project,
                workspace=workspace,
                operation=operation,
                payload=body,
                latest_artifact_for_workspace_path_fn=latest_artifact_for_workspace_path_fn,
            )
            ack = {
                "schema_version": RESEARCH_PLAN_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_research_plan_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="research_plan_request_succeeded",
                    role="harness",
                    title="ResearchPlan request processed",
                    content=f"Processed ResearchPlan request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    update_heartbeat=False,
                )
            if operation == "request_human_attention" and register_attention_fn is not None:
                result_payload = result if isinstance(result, dict) else {}
                register_attention_fn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=f"research_plan_human_attention:{result_payload.get('question_id') or request_id}",
                    status="needs_attention",
                    message_kind="research_plan_human_attention_requested",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "question_id": result_payload.get("question_id"),
                        "question": body.get("question") if isinstance(body.get("question"), str) else "",
                        "why_it_matters": body.get("why_it_matters") if isinstance(body.get("why_it_matters"), str) else "",
                        "node_id": body.get("node_id") if isinstance(body.get("node_id"), str) else "",
                        "can_proceed_without_answer": result_payload.get("can_proceed_without_answer"),
                    },
                )
        except ResearchPlanValidationError as exc:
            ack = research_plan_failed_ack(
                request_id=request_id,
                operation=operation,
                error_type=type(exc).__name__,
                error_message=str(exc),
                issues=exc.issues,
            )
            write_research_plan_tool_ack(ack_path, ack)
            write_rejection_fn(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc)[:1200],
                issues=exc.issues,
            )
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="research_plan_request_failed",
                    role="harness",
                    title="ResearchPlan request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )
            if register_attention_fn is not None:
                register_attention_fn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=research_plan_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        issues=exc.issues,
                    ),
                    status="needs_attention",
                    message_kind="research_plan_request_failed",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1200],
                        "issues": exc.issues[:8],
                        "workspace_relative_path": str(path.relative_to(workspace)),
                    },
                )
        except Exception as exc:
            ack = research_plan_failed_ack(
                request_id=request_id,
                operation=operation,
                error_type=type(exc).__name__,
                error_message=str(exc),
                issues=None,
            )
            write_research_plan_tool_ack(ack_path, ack)
            write_rejection_fn(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc)[:1200],
                issues=None,
            )
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="research_plan_request_failed",
                    role="harness",
                    title="ResearchPlan request failed",
                    content=str(exc),
                    payload={**ack, "workspace_relative_path": str(path.relative_to(workspace))},
                    update_heartbeat=False,
                )
            if register_attention_fn is not None:
                register_attention_fn(
                    db,
                    store=store,
                    project=project,
                    session=session,
                    attention_key=research_plan_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        issues=None,
                    ),
                    status="needs_attention",
                    message_kind="research_plan_request_failed",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1200],
                        "workspace_relative_path": str(path.relative_to(workspace)),
                    },
                )


def research_plan_failed_ack(
    *,
    request_id: str,
    operation: str,
    error_type: str,
    error_message: str,
    issues: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"type": error_type, "message": error_message}
    if issues is not None:
        error["issues"] = issues
    return {
        "schema_version": RESEARCH_PLAN_ACK_SCHEMA_VERSION,
        "request_id": request_id,
        "operation": operation,
        "status": "failed",
        "processed_at": utc_now().isoformat(),
        "error": error,
    }


def research_plan_request_processing_order(path: Path) -> tuple[int, str]:
    priority = {
        "commit_revision": 0,
        "attach_artifact": 1,
        "set_current_work": 2,
        "request_human_attention": 3,
    }
    try:
        payload = loads_json(path.read_text(encoding="utf-8"), {})
        if not isinstance(payload, dict):
            return (99, path.name)
        operation = str(payload.get("operation") or payload.get("tool") or "").strip()
        return (priority.get(operation, 50), path.name)
    except Exception:
        return (99, path.name)


def execute_research_plan_tool_request(
    db: Session,
    *,
    project: Project,
    workspace: Path,
    operation: str,
    payload: dict[str, Any],
    latest_artifact_for_workspace_path_fn: LatestArtifactForWorkspacePath,
) -> dict[str, Any]:
    if operation == "commit_revision":
        compatibility_warnings: list[str] = []
        document = payload.get("document")
        if not isinstance(document, dict):
            research_plan_path = optional_nonempty_string(payload, "research_plan_path")
            if research_plan_path:
                document = read_research_plan_document_from_workspace_path(workspace, research_plan_path)
                compatibility_warnings.append(
                    "Accepted research_plan_path as an explicit workspace JSON reference; "
                    "prefer payload.document for new requests."
                )
        if not isinstance(document, dict):
            raise ValueError(
                "payload.document is required for commit_revision. "
                "Alternative compatibility form: provide research_plan_path pointing to a JSON file under the workspace."
            )
        result = commit_research_plan_revision(
            db,
            project_id=project.id,
            document=document,
            author_type=str(payload.get("author_type") or "codex"),
            author_id=str(payload.get("author_id")) if payload.get("author_id") is not None else None,
            reason=str(payload.get("reason") or ""),
            source_artifact_id=str(payload.get("source_artifact_id"))
            if payload.get("source_artifact_id") is not None
            else None,
            parent_revision_id=str(payload.get("parent_revision_id"))
            if payload.get("parent_revision_id") is not None
            else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            strict_validation=True,
        )
        return {
            "research_plan_id": result.plan.id,
            "revision_id": result.revision.id,
            "revision_index": result.revision.revision_index,
            "created": result.created,
            "compatibility_warnings": compatibility_warnings,
        }
    if operation == "set_current_work":
        node_id, compatibility_warnings = research_plan_request_node_id(payload)
        current = set_research_plan_current_work(
            db,
            project_id=project.id,
            node_id=node_id,
            summary=str(payload.get("summary") or ""),
            status=str(payload.get("status") or "active"),
            expected_outputs=[str(item) for item in payload.get("expected_outputs", [])]
            if isinstance(payload.get("expected_outputs"), list)
            else [],
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
            updated_by_type=str(payload.get("updated_by_type") or "codex"),
            updated_by=str(payload.get("updated_by")) if payload.get("updated_by") is not None else None,
        )
        return {
            "current_work": research_plan_current_work_payload(current),
            "compatibility_warnings": compatibility_warnings,
        }
    if operation == "attach_artifact":
        node_id, compatibility_warnings = research_plan_request_node_id(payload)
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            workspace_path = payload.get("workspace_path")
            if not isinstance(workspace_path, str) or not workspace_path.strip():
                raise ValueError("payload.artifact_id or payload.workspace_path is required for attach_artifact")
            artifact = latest_artifact_for_workspace_path_fn(
                db,
                project_id=project.id,
                workspace=workspace,
                workspace_path=workspace_path,
            )
            if artifact is None:
                raise ValueError(f"No registered artifact found for workspace_path {workspace_path}")
            artifact_id = artifact.id
        edge = attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=node_id,
            artifact_id=artifact_id,
            role=str(payload.get("role") or "evidence"),
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
        return {
            "link_id": edge.id,
            "artifact_id": edge.to_asset_id,
            "node_id": str(loads_json(edge.metadata_json, {}).get("node_id") or ""),
            "compatibility_warnings": compatibility_warnings,
        }
    if operation == "request_human_attention":
        node_id, compatibility_warnings = research_plan_request_node_id(payload, required=False)
        requested_blocks_next_phase = bool(payload.get("blocks_next_phase") or False)
        full_auto_continues = project.autonomy_mode == "full_auto" and requested_blocks_next_phase
        question = request_research_plan_human_attention(
            db,
            project_id=project.id,
            question=str(payload.get("question") or ""),
            why_it_matters=str(payload.get("why_it_matters") or ""),
            node_id=node_id or None,
            provisional_assumption=str(payload.get("provisional_assumption"))
            if payload.get("provisional_assumption") is not None
            else None,
            impact_if_wrong=str(payload.get("impact_if_wrong")) if payload.get("impact_if_wrong") is not None else None,
            urgency=str(payload.get("urgency") or "medium"),
            fallback_policy=(
                "infer_and_continue"
                if full_auto_continues
                else str(payload.get("fallback_policy") or "infer_and_continue")
            ),
            blocks_next_phase=requested_blocks_next_phase and not full_auto_continues,
            revision_id=str(payload.get("revision_id")) if payload.get("revision_id") is not None else None,
        )
        return {
            "question_id": question.id,
            "can_proceed_without_answer": question.can_proceed_without_answer,
            "continued_automatically": full_auto_continues,
            "compatibility_warnings": compatibility_warnings,
        }
    raise ValueError(f"Unsupported ResearchPlan request operation: {operation}")


def research_plan_request_node_id(payload: dict[str, Any], *, required: bool = True) -> tuple[str, list[str]]:
    compatibility_warnings: list[str] = []
    node_id = optional_nonempty_string(payload, "node_id")
    if not node_id:
        alias_node_id = optional_nonempty_string(payload, "research_plan_node_id")
        if alias_node_id:
            node_id = alias_node_id
            compatibility_warnings.append(
                "Accepted research_plan_node_id as an explicit alias for node_id; prefer payload.node_id for new requests."
            )
    if required and not node_id:
        raise ValueError("payload.node_id is required")
    return node_id or "", compatibility_warnings


def read_research_plan_document_from_workspace_path(workspace: Path, workspace_path: str) -> dict[str, Any]:
    candidate = resolve_workspace_relative_path(workspace, workspace_path)
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"research_plan_path does not exist under the workspace: {workspace_path}")
    document = loads_json(candidate.read_text(encoding="utf-8"), {})
    if not isinstance(document, dict):
        raise ValueError(f"research_plan_path must point to a JSON object: {workspace_path}")
    return document


def research_plan_request_failure_attention_key(
    *,
    operation: str,
    error_type: str,
    error_message: str,
    issues: list[dict[str, Any]] | None,
) -> str:
    issue_codes = [
        str(issue.get("code") or issue.get("path") or issue.get("message") or "").strip()
        for issue in (issues or [])[:8]
        if isinstance(issue, dict)
    ]
    signature = {
        "operation": operation or "<missing>",
        "error_type": error_type,
        "issue_codes": [code for code in issue_codes if code],
        "message": "" if issue_codes else error_message[:240],
    }
    digest = hashlib.sha1(dumps_json(signature).encode("utf-8")).hexdigest()[:16]
    return f"research_plan_request_failed:{digest}"


def optional_nonempty_string(payload: dict[str, Any], key: str, *, prefix: str = "payload") -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def resolve_workspace_relative_path(workspace: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("workspace paths must be relative to the AgentSession workspace")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("workspace paths must not contain parent-directory segments")
    resolved = (workspace / candidate).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("workspace path escapes the AgentSession workspace") from exc
    return resolved


def write_research_plan_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
