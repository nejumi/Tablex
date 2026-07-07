from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import AgentSession, Artifact, Evidence, ExperimentRun, Project, utc_now
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
MODEL_DIAGNOSTICS_REQUESTS_DIR = "model_diagnostics"
MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION = "tablex_model_diagnostics_request.v1"
MODEL_DIAGNOSTICS_ACK_SCHEMA_VERSION = "tablex_model_diagnostics_ack.v1"
MODEL_DIAGNOSTICS_MANIFEST_SCHEMA_VERSION = "tablex_model_diagnostics_manifest.v1"
MODEL_DIAGNOSTIC_CHECK_NAMES = (
    "permutation_importance",
    "native_feature_importance",
    "partial_dependence",
    "shap",
)
MODEL_DIAGNOSTIC_CHECK_STATUSES = (
    "included",
    "not_applicable",
    "needs_model_artifact",
    "needs_dependency",
    "deferred",
)
MODEL_DIAGNOSTICS_ASSET_TYPE_BY_KEY = {
    "permutation_importance": "permutation_importance",
    "permutation": "permutation_importance",
    "native_feature_importance": "feature_importance",
    "feature_importance": "feature_importance",
    "partial_dependence": "partial_dependence",
    "pdp": "partial_dependence",
    "shap": "shap_summary",
    "shap_summary": "shap_summary",
    "model_diagnostics": "model_diagnostics_artifact_pack",
    "model_diagnostics_artifact_pack": "model_diagnostics_artifact_pack",
}
MODEL_DIAGNOSTICS_DEFAULT_KEYS_BY_CHECK = {
    "permutation_importance": ("permutation_importance", "permutation"),
    "native_feature_importance": ("native_feature_importance", "feature_importance"),
    "partial_dependence": ("partial_dependence", "pdp"),
    "shap": ("shap_summary", "shap"),
}

AppendSessionEvent = Callable[..., Any]
RegisterAttention = Callable[..., Any]


def model_diagnostics_request_rejection_path(workspace: Path) -> Path:
    return latest_inbox_entry_path(workspace, entry_type="model_diagnostics_request_rejection", kind="rejection")


def model_diagnostics_requests_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_REQUESTS_DIR / MODEL_DIAGNOSTICS_REQUESTS_DIR


def model_diagnostics_acks_dir(workspace: Path) -> Path:
    return workspace / SESSION_INTERNAL_DIR / SESSION_ACKS_DIR / MODEL_DIAGNOSTICS_REQUESTS_DIR


def process_model_diagnostics_tool_requests(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    append_session_event_fn: AppendSessionEvent | None = None,
    register_attention_fn: RegisterAttention | None = None,
) -> None:
    request_dir = model_diagnostics_requests_dir(workspace)
    if not request_dir.exists():
        return
    ack_dir = model_diagnostics_acks_dir(workspace)
    ack_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in request_dir.glob("*.json") if item.is_file()):
        ack_path = ack_dir / f"{path.stem}.ack.json"
        if ack_path.exists():
            if model_diagnostics_ack_artifacts_are_persisted(db, project=project, ack_path=ack_path):
                continue
            try:
                ack_path.unlink()
            except OSError:
                continue
        request_id = path.stem
        operation = ""
        try:
            raw_text = path.read_text(encoding="utf-8")
            request = loads_json(raw_text, {})
            if not isinstance(request, dict):
                raise ValueError("Model diagnostics request must be a JSON object")
            request_id = str(request.get("request_id") or path.stem)
            schema_version = str(request.get("schema_version") or "")
            if schema_version != MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION:
                raise ValueError(
                    "Unsupported model diagnostics request schema_version: "
                    f"{schema_version or '<missing>'}; expected {MODEL_DIAGNOSTICS_REQUEST_SCHEMA_VERSION}"
                )
            operation = str(request.get("operation") or "").strip()
            if operation != "register_model_diagnostics_artifacts":
                raise ValueError(f"Unsupported model diagnostics request operation: {operation or '<missing>'}")
            payload = request.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            result = execute_model_diagnostics_registration_request(
                db,
                store=store,
                project=project,
                session=session,
                workspace=workspace,
                request_id=request_id,
                payload=payload,
            )
            ack = {
                "schema_version": MODEL_DIAGNOSTICS_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "succeeded",
                "request_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "processed_at": utc_now().isoformat(),
                "result": result,
            }
            write_model_diagnostics_tool_ack(ack_path, ack)
            if append_session_event_fn is not None:
                append_session_event_fn(
                    db,
                    session,
                    source="tablex_sidecar",
                    event_type="model_diagnostics_request_succeeded",
                    role="harness",
                    title="Model diagnostics request processed",
                    content=f"Processed model diagnostics request `{operation}` from `{path.relative_to(workspace)}`.",
                    payload=ack,
                    artifact_id=result.get("model_diagnostics_artifact_pack_id"),
                    update_heartbeat=False,
                )
        except Exception as exc:
            ack = {
                "schema_version": MODEL_DIAGNOSTICS_ACK_SCHEMA_VERSION,
                "request_id": request_id,
                "operation": operation,
                "status": "failed",
                "processed_at": utc_now().isoformat(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            write_model_diagnostics_tool_ack(ack_path, ack)
            write_model_diagnostics_request_rejection_to_workspace_inbox(
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
                    event_type="model_diagnostics_request_failed",
                    role="harness",
                    title="Model diagnostics request failed",
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
                    attention_key=model_diagnostics_request_failure_attention_key(
                        operation=operation,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    ),
                    status="needs_attention",
                    message_kind="model_diagnostics_request_failed",
                    details={
                        "request_id": request_id,
                        "operation": operation,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1200],
                        "workspace_relative_path": str(path.relative_to(workspace)),
                    },
                )


def execute_model_diagnostics_registration_request(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    request_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    run_ids = model_diagnostics_request_run_ids(db, project=project, payload=payload)
    checks = model_diagnostics_checks_for_request(payload.get("checks"))
    artifact_specs = model_diagnostics_artifact_specs(payload.get("artifacts"))
    require_included_model_diagnostics_artifacts(checks, artifact_specs)
    research_plan_node_id = optional_nonempty_string(payload, "research_plan_node_id")
    revision_id = optional_nonempty_string(payload, "revision_id")
    registered_artifacts: list[Artifact] = []
    by_key: dict[str, list[Artifact]] = {}
    for spec in artifact_specs:
        artifact = model_diagnostics_artifact_from_spec(
            db,
            store=store,
            project=project,
            session=session,
            workspace=workspace,
            request_id=request_id,
            run_ids=run_ids,
            spec=spec,
        )
        registered_artifacts.append(artifact)
        by_key.setdefault(spec["key"], []).append(artifact)
    pack_artifacts = [
        artifact for artifact in registered_artifacts if artifact.asset_type == "model_diagnostics_artifact_pack"
    ]
    if not pack_artifacts:
        pack_artifacts.append(
            create_model_diagnostics_artifact_pack(
                db,
                store=store,
                project=project,
                session=session,
                request_id=request_id,
                run_ids=run_ids,
                checks=checks,
                registered_artifacts=registered_artifacts,
            )
        )
        registered_artifacts.append(pack_artifacts[0])
    for pack_artifact in pack_artifacts:
        metadata = loads_json(pack_artifact.metadata_json, {})
        metadata["checks"] = checks
        metadata["availability"] = {
            check["name"]: check["status"]
            for check in checks
            if isinstance(check.get("name"), str) and isinstance(check.get("status"), str)
        }
        pack_artifact.metadata_json = dumps_json(metadata)
    for artifact in registered_artifacts:
        for run_id in run_ids:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="experiment_run",
                from_asset_id=run_id,
                to_asset_type="artifact",
                to_asset_id=artifact.id,
                relation_type="diagnoses",
                metadata={"agent_session_id": session.id, "request_id": request_id},
            )
        if research_plan_node_id:
            attach_research_plan_artifact(
                db,
                project_id=project.id,
                node_id=research_plan_node_id,
                artifact_id=artifact.id,
                role=artifact.asset_type,
                revision_id=revision_id,
                metadata={
                    "agent_session_id": session.id,
                    "request_id": request_id,
                    "source": "model_diagnostics_request",
                },
            )
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="model_diagnostics_artifact_pack",
        summary=f"Registered model diagnostics artifact pack for {len(run_ids)} run(s).",
        strength="strong" if all(check["status"] == "included" for check in checks) else "medium",
        source_artifact_id=pack_artifacts[0].id,
        source_run_id=run_ids[0],
        metadata_json=dumps_json({"run_ids": run_ids, "agent_session_id": session.id, "request_id": request_id}),
    )
    db.add(evidence)
    db.flush()
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pack_artifacts[0].id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
        metadata={"agent_session_id": session.id, "request_id": request_id},
    )
    return {
        "schema_version": "model_diagnostics_registration_result.v1",
        "run_ids": run_ids,
        "artifact_ids": [artifact.id for artifact in registered_artifacts],
        "model_diagnostics_artifact_pack_id": pack_artifacts[0].id,
        "feature_importance_artifact_ids": [
            artifact.id for artifact in registered_artifacts if artifact.asset_type == "feature_importance"
        ],
        "permutation_importance_artifact_ids": [
            artifact.id for artifact in registered_artifacts if artifact.asset_type == "permutation_importance"
        ],
        "partial_dependence_artifact_ids": [
            artifact.id for artifact in registered_artifacts if artifact.asset_type == "partial_dependence"
        ],
        "shap_summary_artifact_ids": [
            artifact.id for artifact in registered_artifacts if artifact.asset_type == "shap_summary"
        ],
        "research_plan_node_id": research_plan_node_id,
        "checks": checks,
        "evidence_id": evidence.id,
        "artifact_keys": {key: [artifact.id for artifact in artifacts] for key, artifacts in by_key.items()},
    }


def model_diagnostics_request_run_ids(db: Session, *, project: Project, payload: dict[str, Any]) -> list[str]:
    run_id = optional_nonempty_string(payload, "run_id")
    related_run_ids = require_string_list(payload.get("related_run_ids"), "payload.related_run_ids")
    run_ids = unique_texts([*([run_id] if run_id else []), *related_run_ids])
    if not run_ids:
        raise ValueError("payload.run_id or payload.related_run_ids is required")
    for item in run_ids:
        run = db.get(ExperimentRun, item)
        if run is None or run.project_id != project.id:
            raise ValueError(f"ExperimentRun `{item}` does not belong to this project")
    return run_ids


def model_diagnostics_checks_for_request(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("payload.checks must be an array")
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value[:24]):
        if not isinstance(raw, dict):
            raise ValueError(f"payload.checks[{index}] must be an object")
        name = str(raw.get("name") or "").strip()
        if name not in MODEL_DIAGNOSTIC_CHECK_NAMES:
            raise ValueError(f"payload.checks[{index}].name must be one of {', '.join(MODEL_DIAGNOSTIC_CHECK_NAMES)}")
        if name in seen:
            raise ValueError(f"payload.checks[{index}].name duplicates {name}")
        seen.add(name)
        status = str(raw.get("status") or "").strip()
        if status not in MODEL_DIAGNOSTIC_CHECK_STATUSES:
            raise ValueError(
                f"payload.checks[{index}].status must be one of {', '.join(MODEL_DIAGNOSTIC_CHECK_STATUSES)}"
            )
        artifact_keys = require_string_list(raw.get("artifact_keys"), f"payload.checks/{index}/artifact_keys")
        reason = optional_nonempty_string(raw, "reason")
        if status != "included" and not reason:
            raise ValueError(f"payload.checks[{index}].reason is required when status is {status}")
        checks.append(
            {
                "name": name,
                "status": status,
                "artifact_keys": artifact_keys,
                **({"reason": reason} if reason else {}),
            }
        )
    missing = [name for name in MODEL_DIAGNOSTIC_CHECK_NAMES if name not in seen]
    if missing:
        raise ValueError("payload.checks is missing required model diagnostic checks: " + ", ".join(missing))
    return checks


def model_diagnostics_artifact_specs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (dict, list)):
        raise ValueError("payload.artifacts must be an object or array")
    specs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip()
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in values:
                specs.append(model_diagnostics_artifact_spec(item, default_key=key))
    else:
        for index, item in enumerate(value):
            specs.append(model_diagnostics_artifact_spec(item, default_key=f"artifact_{index}"))
    if not specs:
        raise ValueError("payload.artifacts must include at least one diagnostic artifact")
    return specs


def model_diagnostics_artifact_spec(value: Any, *, default_key: str) -> dict[str, Any]:
    if isinstance(value, str):
        raw: dict[str, Any] = {"workspace_path": value}
    elif isinstance(value, dict):
        raw = dict(value)
    else:
        raise ValueError(f"payload.artifacts.{default_key} must be a workspace path string or object")
    key = str(raw.get("key") or raw.get("artifact_type") or raw.get("check_name") or default_key).strip()
    normalized_key = normalize_model_diagnostics_artifact_key(key)
    asset_type = normalize_model_diagnostics_asset_type(str(raw.get("asset_type") or normalized_key))
    workspace_path = optional_nonempty_string(raw, "workspace_path")
    artifact_id = optional_nonempty_string(raw, "artifact_id")
    if not workspace_path and not artifact_id:
        raise ValueError(f"payload.artifacts.{default_key} must include workspace_path or artifact_id")
    if workspace_path and artifact_id:
        raise ValueError(f"payload.artifacts.{default_key} must not include both workspace_path and artifact_id")
    return {
        "key": normalized_key,
        "asset_type": asset_type,
        "workspace_path": workspace_path,
        "artifact_id": artifact_id,
        "name": optional_nonempty_string(raw, "name"),
        "label": optional_nonempty_string(raw, "label"),
        "status": optional_nonempty_string(raw, "status"),
    }


def normalize_model_diagnostics_artifact_key(value: str) -> str:
    normalized = value.strip().replace("-", "_").replace(" ", "_").casefold()
    if normalized not in MODEL_DIAGNOSTICS_ASSET_TYPE_BY_KEY:
        raise ValueError(
            "Unknown model diagnostics artifact key "
            f"`{value}`; expected one of {', '.join(sorted(MODEL_DIAGNOSTICS_ASSET_TYPE_BY_KEY))}"
        )
    return normalized


def normalize_model_diagnostics_asset_type(value: str) -> str:
    normalized = normalize_model_diagnostics_artifact_key(value)
    return MODEL_DIAGNOSTICS_ASSET_TYPE_BY_KEY[normalized]


def require_included_model_diagnostics_artifacts(checks: list[dict[str, Any]], specs: list[dict[str, Any]]) -> None:
    keys = {spec["key"] for spec in specs}
    asset_types = {spec["asset_type"] for spec in specs}
    for check in checks:
        if check["status"] != "included":
            continue
        declared_keys = list(check.get("artifact_keys") or [])
        candidate_keys = declared_keys or list(MODEL_DIAGNOSTICS_DEFAULT_KEYS_BY_CHECK.get(check["name"], ()))
        if any(key in keys for key in candidate_keys):
            continue
        expected_asset_type = MODEL_DIAGNOSTICS_ASSET_TYPE_BY_KEY.get(candidate_keys[0]) if candidate_keys else None
        if expected_asset_type and expected_asset_type in asset_types:
            continue
        raise ValueError(
            f"payload.checks `{check['name']}` is included but no matching artifact was provided. "
            f"Expected artifact key(s): {', '.join(candidate_keys)}"
        )


def model_diagnostics_artifact_from_spec(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    workspace: Path,
    request_id: str,
    run_ids: list[str],
    spec: dict[str, Any],
) -> Artifact:
    artifact_id = spec.get("artifact_id")
    if isinstance(artifact_id, str) and artifact_id.strip():
        artifact = db.get(Artifact, artifact_id.strip())
        if artifact is None or artifact.project_id != project.id:
            raise ValueError(f"payload.artifacts.{spec['key']}.artifact_id does not belong to this project")
        if artifact.asset_type != spec["asset_type"]:
            raise ValueError(
                f"payload.artifacts.{spec['key']}.artifact_id has asset_type {artifact.asset_type}, "
                f"expected {spec['asset_type']}"
            )
        metadata = loads_json(artifact.metadata_json, {})
        metadata.update(
            model_diagnostics_artifact_metadata(
                project=project,
                session=session,
                request_id=request_id,
                run_ids=run_ids,
                spec=spec,
            )
        )
        artifact.metadata_json = dumps_json(metadata)
        return artifact
    workspace_path = str(spec.get("workspace_path") or "")
    source_path = resolve_workspace_relative_path(workspace, workspace_path)
    if not source_path.is_file():
        raise ValueError(f"payload.artifacts.{spec['key']}.workspace_path does not exist: {workspace_path}")
    relative_path = source_path.relative_to(workspace.resolve())
    name = spec.get("name") or session_output_artifact_name(session.id, relative_path)
    metadata = model_diagnostics_artifact_metadata(
        project=project,
        session=session,
        request_id=request_id,
        run_ids=run_ids,
        spec={**spec, "workspace_relative_path": relative_path.as_posix()},
    )
    version = next_artifact_version(db, project.id, spec["asset_type"], str(name))
    artifact_dir, stored, content_hash = store.store_existing_file(
        org_id=project.org_id,
        project_id=project.id,
        asset_type=spec["asset_type"],
        name=str(name),
        version=version,
        source_path=source_path,
        filename=source_path.name,
        metadata=metadata,
    )
    return register_artifact(
        db,
        project_id=project.id,
        asset_type=spec["asset_type"],
        name=str(name),
        version=version,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata=metadata,
        created_by="codex_main_session",
    )


def model_diagnostics_artifact_metadata(
    *,
    project: Project,
    session: AgentSession,
    request_id: str,
    run_ids: list[str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    metadata = {
        "schema_version": "model_diagnostics_artifact_link.v1",
        "project_id": project.id,
        "agent_session_id": session.id,
        "request_id": request_id,
        "diagnostic_key": spec["key"],
        "source": "model_diagnostics_request",
        "run_ids": run_ids,
    }
    if len(run_ids) == 1:
        metadata["run_id"] = run_ids[0]
    else:
        metadata["related_run_ids"] = run_ids
    for key in ("label", "status", "workspace_relative_path"):
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    return metadata


def create_model_diagnostics_artifact_pack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    request_id: str,
    run_ids: list[str],
    checks: list[dict[str, Any]],
    registered_artifacts: list[Artifact],
) -> Artifact:
    artifact_refs = [
        {
            "artifact_id": artifact.id,
            "asset_type": artifact.asset_type,
            "diagnostic_key": loads_json(artifact.metadata_json, {}).get("diagnostic_key"),
        }
        for artifact in registered_artifacts
    ]
    payload = {
        "schema_version": "model_diagnostics_artifact_pack.v1",
        "project_id": project.id,
        "run_ids": run_ids,
        "checks": checks,
        "artifacts": artifact_refs,
        "source": "model_diagnostics_request",
        "agent_session_id": session.id,
        "request_id": request_id,
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="model_diagnostics_artifact_pack",
        name=f"model_diagnostics_artifact_pack_{request_id}",
        filename="model_diagnostics_artifact_pack.json",
        payload=payload,
        metadata={
            "project_id": project.id,
            "agent_session_id": session.id,
            "request_id": request_id,
            "run_ids": run_ids,
            "source": "model_diagnostics_request",
            "diagnostic_key": "model_diagnostics_artifact_pack",
            **({"run_id": run_ids[0]} if len(run_ids) == 1 else {"related_run_ids": run_ids}),
        },
    )


def model_diagnostics_ack_artifacts_are_persisted(db: Session, *, project: Project, ack_path: Path) -> bool:
    try:
        ack = loads_json(ack_path.read_text(encoding="utf-8"), {})
    except OSError:
        return False
    if not isinstance(ack, dict) or ack.get("status") != "succeeded":
        return True
    result = ack.get("result")
    if not isinstance(result, dict):
        return False
    raw_artifact_ids = result.get("artifact_ids")
    artifact_ids = [str(item).strip() for item in raw_artifact_ids] if isinstance(raw_artifact_ids, list) else []
    artifact_ids = [item for item in artifact_ids if item]
    pack_id = result.get("model_diagnostics_artifact_pack_id")
    if isinstance(pack_id, str) and pack_id.strip():
        artifact_ids = unique_texts([*artifact_ids, pack_id.strip()])
    if not artifact_ids:
        return False
    for artifact_id in artifact_ids:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project.id:
            return False
    return True


def write_model_diagnostics_tool_ack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def write_model_diagnostics_request_rejection_to_workspace_inbox(
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
        "schema_version: tablex_model_diagnostics_request_rejection.v1",
        f"request_id: {request_id}",
        f"operation: {operation or '<unknown>'}",
        f"created_at: {utc_now().isoformat()}",
        f"request_path: {request_relative_path}",
        f"ack_path: {ack_relative_path}",
        f"error_type: {error_type}",
        "",
        "The model diagnostics request did not register diagnostics artifacts, ResearchPlan evidence, or run links.",
        "Read the ack JSON, repair the fixed request payload, and resubmit under `.tablex/requests/model_diagnostics/` with a new request_id.",
        "",
        "Required checks: permutation_importance, native_feature_importance, partial_dependence, shap.",
        "If a check is not applicable or blocked by a missing dependency, declare that fixed status with a reason.",
        "",
        "Error:",
        error_message,
    ]
    write_workspace_inbox_text(
        workspace,
        kind="rejection",
        entry_type="model_diagnostics_request_rejection",
        lines=lines,
        payload={
            "schema_version": "tablex_model_diagnostics_request_rejection.v1",
            "request_id": request_id,
            "operation": operation,
            "request_path": request_relative_path,
            "ack_path": ack_relative_path,
            "error_type": error_type,
            "error_message": error_message,
        },
        title="Model diagnostics request rejected",
    )


def model_diagnostics_request_failure_attention_key(*, operation: str, error_type: str, error_message: str) -> str:
    normalized = {
        "operation": operation or "unknown",
        "error_type": error_type,
        "error_message": error_message[:800],
    }
    signature = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"model_diagnostics_request_failed:{signature}"


def write_workspace_inbox_text(
    workspace: Path,
    *,
    kind: str,
    entry_type: str,
    lines: list[str],
    payload: dict[str, Any] | None = None,
    title: str | None = None,
) -> Path | None:
    try:
        return write_inbox_entry(
            workspace,
            kind=kind,
            entry_type=entry_type,
            payload=payload or {},
            content="\n".join(lines).strip() + "\n",
            title=title,
        )
    except (OSError, ValueError):
        return None


def session_output_artifact_name(session_id: str, relative_path: Path) -> str:
    normalized = "_".join(relative_path.with_suffix("").parts)
    normalized = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in normalized)
    normalized = normalized.strip("_") or "artifact"
    digest = hashlib.sha256(str(relative_path).encode("utf-8")).hexdigest()[:8]
    return f"agent_session_{session_id}_{normalized}_{digest}"


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


def optional_nonempty_string(payload: dict[str, Any], key: str, *, prefix: str = "payload") -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{prefix}.{key} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def require_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        result.append(item.strip())
    return result


def unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = value.strip()
        if cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
