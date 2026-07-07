from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, Artifact, Evidence, Project, utc_now
from tabular_harness.services.agent_inbox import latest_inbox_entry_path, write_inbox_entry
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.research_plans import attach_research_plan_artifact

SESSION_INTERNAL_DIR = ".tablex"
SESSION_REQUESTS_DIR = "requests"
SESSION_ACKS_DIR = "acks"
RESEARCH_REQUESTS_DIR = "research"
RESEARCH_REQUEST_SCHEMA_VERSION = "tablex_research_request.v1"
RESEARCH_ACK_SCHEMA_VERSION = "tablex_research_ack.v1"
RESEARCH_REPORT_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

AppendSessionEvent = Callable[..., Any]
RegisterAttention = Callable[..., Any]
RegisterResearchChat = Callable[..., Any]


def research_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="research_request_rejection", kind="rejection")


def research_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / RESEARCH_REQUESTS_DIR


def research_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / RESEARCH_REQUESTS_DIR


def process_research_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
    register_attention_fn: RegisterAttention | None = None,
    register_research_chat_fn: RegisterResearchChat | None = None,
) -> None:
    request_dir = research_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = research_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            request = loads_json(raw_text, {})
            if not isinstance(request, dict):
                raise ValueError("Research request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != RESEARCH_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported research request schema_version: {schema_version or '<missing>'}; "
                    f"expected {RESEARCH_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation != "register_research_findings":
                raise ValueError(f"Unsupported research request operation: {operation or '<missing>'}")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = execute_research_registration_request(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                request_id=request_id,
                payload=payload,
                register_research_chat_fn=register_research_chat_fn,
            )
            ack = {
                "schema_version": RESEARCH_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_research_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="research_request_succeeded",
                    role="harness",
                    title="Research request processed",
                    content=f"Processed research request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    artifact_id=result.get("artifact_id"),
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": RESEARCH_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_research_tool_ack(ack_path, ack)
            write_research_request_rejection_to_workspace_inbox(
                workspace,
                request_id=request_id,
                operation=operation,
                request_relative_path=str(path.relative_to(workspace)),
                ack_relative_path=str(ack_path.relative_to(workspace)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="research_request_failed",
                    role="harness",
                    title="Research request failed",
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
                    attention_key=research_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    ),
                    status="needs_attention",
                    message_kind="research_request_failed",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1200],
                        "workspace_relative_path": str(path.relative_to(workspace)),
                    },
                )


def execute_research_registration_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    request_id: str,
    payload: dict[str, Any],
    register_research_chat_fn: RegisterResearchChat | None = None,
) -> dict[str, Any]:
    normalized = validate_research_findings_payload(payload)
    rich_report_artifact, figure_artifacts = register_research_markdown_report_from_payload(
        db,
        store=store,
        project=project,
        session=session,
        workspace=workspace,
        request_id=request_id,
        payload=normalized,
    )
    rich_report_artifact_id = rich_report_artifact.id if rich_report_artifact is not None else None
    figure_artifact_ids = [artifact.id for artifact in figure_artifacts]
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="research_findings_report",
        name=f"agent_session_{session.id}_research_{request_id}",
        filename="research_findings.json",
        payload={
            "schema_version": "research_findings_report.v1",
            "request_id": request_id,
            "agent_session_id": session.id,
            "rich_report_artifact_id": rich_report_artifact_id,
            "figure_artifact_ids": figure_artifact_ids,
            **normalized,
        },
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "research_plan_node_id": normalized.get("research_plan_node_id"),
            "topic": normalized.get("topic"),
            "source_count": len(normalized.get("sources", [])),
            "finding_count": len(normalized.get("findings", [])),
            "no_findings": isinstance(normalized.get("no_findings"), dict),
            "rich_report_artifact_id": rich_report_artifact_id,
            "figure_artifact_ids": figure_artifact_ids,
            "source": "main_agent_session_research_request",
        },
    )
    if rich_report_artifact is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=rich_report_artifact.id,
            relation_type="has_rich_report",
            metadata={"request_id": request_id, "report_workspace_path": normalized.get("report_workspace_path")},
        )
        for figure_artifact in figure_artifacts:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=rich_report_artifact.id,
                to_asset_type="artifact",
                to_asset_id=figure_artifact.id,
                relation_type="references_figure",
                metadata={"request_id": request_id},
            )
    evidence_ids: list[str] = []
    for index, finding in enumerate(normalized.get("findings", [])):
        evidence = Evidence(
            id=new_id("evd"),
            project_id=project.id,
            evidence_type="research_finding",
            summary=str(finding["claim"]),
            strength="reported",
            source_artifact_id=artifact.id,
            metadata_json=dumps_json(
                {
                    "request_id": request_id,
                    "finding_index": index,
                    "source_indexes": finding["source_indexes"],
                    "implication_for_project": finding.get("implication_for_project"),
                    "recommended_action": finding.get("recommended_action"),
                }
            ),
        )
        db.add(evidence)
        evidence_ids.append(evidence.id)
    no_findings = normalized.get("no_findings")
    if isinstance(no_findings, dict):
        evidence = Evidence(
            id=new_id("evd"),
            project_id=project.id,
            evidence_type="research_no_findings",
            summary=str(no_findings.get("rationale") or normalized.get("topic") or "No findings registered."),
            strength="reported",
            source_artifact_id=artifact.id,
            metadata_json=dumps_json({"request_id": request_id, "no_findings": no_findings}),
        )
        db.add(evidence)
        evidence_ids.append(evidence.id)
    node_id = normalized.get("research_plan_node_id")
    if isinstance(node_id, str) and node_id.strip():
        attach_research_plan_artifact(
            db,
            project_id=project.id,
            node_id=node_id.strip(),
            artifact_id=artifact.id,
            role="research_findings",
            metadata={"request_id": request_id, "evidence_ids": evidence_ids},
        )
    if register_research_chat_fn is not None:
        register_research_chat_fn(
            db,
            store=store,
            project=project,
            session=session,
            research_artifact=artifact,
            research_payload={
                **normalized,
                "request_id": request_id,
                "evidence_ids": evidence_ids,
            },
        )
    return {
        "artifact_id": artifact.id,
        "rich_report_artifact_id": rich_report_artifact_id,
        "figure_artifact_ids": figure_artifact_ids,
        "evidence_ids": evidence_ids,
        "research_plan_node_id": node_id,
    }


def register_research_markdown_report_from_payload(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    request_id: str,
    payload: dict[str, Any],
) -> tuple[Artifact | None, list[Artifact]]:
    report_workspace_path = payload.get("report_workspace_path")
    if not isinstance(report_workspace_path, str) or not report_workspace_path.strip():
        return None, []
    source_path = resolve_workspace_relative_path(workspace, report_workspace_path)
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"payload.report_workspace_path does not exist under the workspace: {report_workspace_path}")
    if source_path.suffix.lower() not in {".md", ".markdown"}:
        raise ValueError("payload.report_workspace_path must point to a Markdown file")
    try:
        report_text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("payload.report_workspace_path must be UTF-8 Markdown") from exc
    report_artifact = register_existing_workspace_file_artifact(
        db,
        store=store,
        project=project,
        asset_type="research_markdown_report",
        name=f"agent_session_{session.id}_research_{request_id}_markdown_report",
        source_path=source_path,
        filename=source_path.name,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "research_plan_node_id": payload.get("research_plan_node_id"),
            "workspace_relative_path": report_workspace_path.strip(),
            "source": "main_agent_session_research_request",
        },
    )
    figure_artifacts: list[Artifact] = []
    figure_reference_pairs: list[tuple[str, str]] = []
    figure_refs = research_markdown_image_refs(report_text)
    for index, reference in enumerate(figure_refs):
        figure_path = research_markdown_reference_path(
            workspace=workspace,
            report_path=source_path,
            reference=reference,
        )
        if figure_path is None or not figure_path.exists() or not figure_path.is_file():
            continue
        if figure_path.suffix.lower() not in RESEARCH_REPORT_IMAGE_SUFFIXES:
            continue
        figure_artifact = register_existing_workspace_file_artifact(
            db,
            store=store,
            project=project,
            asset_type="research_report_figure",
            name=f"agent_session_{session.id}_research_{request_id}_figure_{index + 1}",
            source_path=figure_path,
            filename=figure_path.name,
            metadata={
                "project_id": project.id,
                "agent_session_id": session.id,
                "request_id": request_id,
                "research_plan_node_id": payload.get("research_plan_node_id"),
                "source_report_artifact_id": report_artifact.id,
                "markdown_reference": reference,
                "workspace_relative_path": str(figure_path.relative_to(workspace.resolve())),
                "source": "main_agent_session_research_request",
            },
        )
        figure_artifacts.append(figure_artifact)
        figure_reference_pairs.append((reference, figure_artifact.id))
    report_metadata = loads_json(report_artifact.metadata_json, {})
    report_metadata["figure_artifact_ids"] = [artifact.id for artifact in figure_artifacts]
    report_metadata["figure_references"] = [
        {"markdown_reference": reference, "artifact_id": artifact_id}
        for reference, artifact_id in figure_reference_pairs
    ]
    report_artifact.metadata_json = dumps_json(report_metadata)
    return report_artifact, figure_artifacts


def register_existing_workspace_file_artifact(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    asset_type: str,
    name: str,
    source_path: Path,
    filename: str,
    metadata: dict[str, Any],
) -> Artifact:
    version = next_artifact_version(db, project.id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_existing_file(
        org_id="local-org",
        project_id=project.id,
        asset_type=asset_type,
        name=name,
        version=version,
        source_path=source_path,
        filename=filename,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project.id,
        asset_type=asset_type,
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        version=version,
    )


def research_markdown_image_refs(markdown: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", markdown):
        reference = match.group(1).strip()
        if reference and reference not in refs:
            refs.append(reference)
    return refs


def research_markdown_reference_path(*, workspace: Path, report_path: Path, reference: str) -> Path | None:
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", reference) or reference.startswith("#"):
        return None
    clean_reference = reference.split("#", 1)[0].split("?", 1)[0]
    if not clean_reference:
        return None
    candidate = Path(clean_reference)
    if candidate.is_absolute():
        return None
    resolved = (report_path.parent / candidate).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError:
        return None
    return resolved


def validate_research_findings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    topic = require_nonempty_string(payload, "topic")
    node_id = optional_nonempty_string(payload, "research_plan_node_id")
    report_workspace_path = optional_nonempty_string(payload, "report_workspace_path")
    query_log = require_string_list(payload.get("query_log", []), "query_log")
    sources = payload.get("sources")
    findings = payload.get("findings")
    no_findings = payload.get("no_findings")
    if no_findings is not None and not isinstance(no_findings, dict):
        raise ValueError("payload.no_findings must be an object when provided")
    if no_findings is None:
        if not isinstance(sources, list) or not sources:
            raise ValueError("payload.sources must contain at least one source unless no_findings is provided")
        if not isinstance(findings, list) or not findings:
            raise ValueError("payload.findings must contain at least one finding unless no_findings is provided")
    if no_findings is not None and (sources or findings):
        raise ValueError("payload.no_findings cannot be combined with sources or findings")
    normalized_sources = [validate_research_source(item, index) for index, item in enumerate(sources or [])]
    normalized_findings = [
        validate_research_finding(item, index, source_count=len(normalized_sources))
        for index, item in enumerate(findings or [])
    ]
    normalized_no_findings = None
    if isinstance(no_findings, dict):
        normalized_no_findings = {
            "searched_queries": require_string_list(no_findings.get("searched_queries", []), "no_findings.searched_queries"),
            "rationale": require_nonempty_string(no_findings, "rationale"),
        }
    return {
        "topic": topic,
        "research_plan_node_id": node_id,
        "report_workspace_path": report_workspace_path,
        "query_log": query_log,
        "sources": normalized_sources,
        "findings": normalized_findings,
        "no_findings": normalized_no_findings,
    }


def validate_research_source(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"payload.sources/{index} must be an object")
    return {
        "url": require_nonempty_string(item, "url", prefix=f"payload.sources/{index}"),
        "title": require_nonempty_string(item, "title", prefix=f"payload.sources/{index}"),
        "source_type": require_nonempty_string(item, "source_type", prefix=f"payload.sources/{index}"),
        "retrieved_at": require_nonempty_string(item, "retrieved_at", prefix=f"payload.sources/{index}"),
        "key_claims": require_string_list(item.get("key_claims", []), f"payload.sources/{index}.key_claims"),
        "reliability_notes": optional_nonempty_string(item, "reliability_notes") or "",
    }


def validate_research_finding(item: Any, index: int, *, source_count: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"payload.findings/{index} must be an object")
    source_indexes = item.get("source_indexes")
    if not isinstance(source_indexes, list) or not source_indexes:
        raise ValueError(f"payload.findings/{index}/source_indexes must be a non-empty integer array")
    normalized_indexes: list[int] = []
    for source_index in source_indexes:
        if not isinstance(source_index, int) or isinstance(source_index, bool):
            raise ValueError(f"payload.findings/{index}/source_indexes must contain integers")
        if source_index < 0 or source_index >= source_count:
            raise ValueError(f"payload.findings/{index}/source_indexes contains out-of-range index {source_index}")
        normalized_indexes.append(source_index)
    return {
        "claim": require_nonempty_string(item, "claim", prefix=f"payload.findings/{index}"),
        "source_indexes": normalized_indexes,
        "implication_for_project": require_nonempty_string(item, "implication_for_project", prefix=f"payload.findings/{index}"),
        "recommended_action": require_nonempty_string(item, "recommended_action", prefix=f"payload.findings/{index}"),
    }


def require_nonempty_string(payload: dict[str, Any], key: str, *, prefix: str = "payload") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}.{key} is required")
    return value.strip()


def optional_nonempty_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"payload.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def require_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    output: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}/{index} must be a non-empty string")
        output.append(item.strip())
    return output


def write_research_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_research_request_rejection_to_workspace_inbox(
    workspace: Path,
    *,
    request_id: str,
    operation: str,
    request_relative_path: str,
    ack_relative_path: str,
    error_type: str,
    error_message: str,
) -> None:
    lines = [
        "schema_version: tablex_research_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The research findings request was rejected by Tablex fixed-format validation and was not registered as evidence.",
        "Read the ack JSON, repair the request under `.tablex/requests/research/`, and resubmit with a new request_id.",
        "",
        "Requirements:",
        "- Use schema_version `tablex_research_request.v1` and operation `register_research_findings`.",
        "- Provide either sources plus findings with valid source_indexes, or provide no_findings with searched_queries and rationale.",
        "- Do not mark the prior-research plan node done until the repaired request is accepted or you intentionally keep that node open.",
        "",
        "Error:",
        error_message,
    ]
    write_inbox_entry(
        workspace,
        kind="rejection",
        entry_type="research_request_rejection",
        content="\n".join(lines),
        payload={
            "schema_version": "tablex_research_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
        },
        title="Research request rejected",
    )


def research_request_failure_attention_key(*, operation: str, error_type: str, error_message: str) -> str:
    normalized = {
        "operation": operation or "unknown",
        "error_type": error_type,
        "error_message": error_message[:800],
    }
    signature = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"research_request_failed:{signature}"


def resolve_workspace_relative_path(workspace: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"path must be workspace-relative: {value}")
    resolved = (workspace / relative).resolve()
    workspace_resolved = workspace.resolve()
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {value}") from exc
    return resolved

