from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import AgentSession, Artifact, ExperimentRun, Project, utc_now
from tabular_harness.services.artifacts import artifact_primary_path
from tabular_harness.services.portal import running_codex_processes_for_project
from tabular_harness.services.research_plans import (
    PLAN_CURRENT_STATUSES,
    PLAN_MAX_TOP_LEVEL_BLOCKS,
    ResearchPlanValidationError,
    commit_research_plan_artifact_revision,
    harness_initial_research_plan_document,
    latest_research_plan_current_work,
    latest_research_plan_revision,
    research_plan_artifact_links,
    research_plan_artifact_surface_target,
    research_plan_block_id,
    research_plan_block_status,
    research_plan_current_work_payload,
    research_plan_evidence_artifact,
    research_plan_evidence_items,
    research_plan_evidence_run_ids,
    research_plan_revision_document,
    research_plan_visible_artifact_for_link,
    validate_research_plan_document,
)

_MISSING = object()


def build_research_plan_timeline_response(db: Session, *, project_id: str, locale: str | None = None) -> dict[str, Any]:
    revision = latest_research_plan_revision(db, project_id=project_id)
    artifact = latest_research_plan_artifact(db, project_id=project_id)
    ignored_source_artifact: dict[str, Any] | None = None
    if artifact is not None and research_plan_artifact_should_commit(artifact, revision=revision):
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except OSError:
            payload = {}
        validation = research_plan_contract_validation_summary(
            db,
            project_id=project_id,
            payload=payload if isinstance(payload, dict) else {},
        )
        if research_plan_payload_is_promotable_artifact(
            db,
            project_id=project_id,
            payload=payload,
            validation=validation,
        ):
            try:
                commit_research_plan_artifact_revision(
                    db,
                    artifact=artifact,
                    reason=f"Committed valid research_plan artifact {artifact.id} from timeline read.",
                    strict_validation=False,
                )
                revision = latest_research_plan_revision(db, project_id=project_id)
            except ResearchPlanValidationError:
                ignored_source_artifact = ignored_research_plan_source_payload(artifact, validation=validation)
        else:
            ignored_source_artifact = ignored_research_plan_source_payload(artifact, validation=validation)
    if revision is not None:
        payload = research_plan_revision_document(revision)
        raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
        response_locale = _research_plan_effective_locale(locale, payload)
        artifact_links = research_plan_artifact_links(db, revision=revision)
        evidence_links = research_plan_evidence_links(db, revision=revision, raw_blocks=raw_blocks)
        all_links = merge_research_plan_links(artifact_links, evidence_links)
        blocks = clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale)
        attach_research_plan_artifact_links_to_blocks(blocks, all_links)
        response = {
            "schema_version": "research_plan_timeline.v1",
            "project_id": project_id,
            "source_artifact_id": revision.source_artifact_id,
            "source_revision_id": revision.id,
            "research_plan_id": revision.research_plan_id,
            "revision_index": revision.revision_index,
            "revision_author_type": revision.author_type,
            "response_locale": response_locale,
            "requested_locale": locale,
            "authored_locale": _research_plan_payload_locale(payload),
            "generated_at": revision.created_at.isoformat(),
            "contract_validation": research_plan_contract_validation_summary(
                db,
                project_id=project_id,
                payload=payload,
            ),
            "current_work": annotate_research_plan_current_work_activity(
                db,
                project_id=project_id,
                payload=research_plan_effective_current_work_payload(
                    db,
                    project_id=project_id,
                    revision=revision,
                    raw_blocks=raw_blocks,
                    locale=response_locale,
                ),
            ),
            "artifact_links": all_links,
            "blocks": blocks,
        }
        if ignored_source_artifact is not None:
            response["ignored_source_artifact"] = ignored_source_artifact
        return response
    if artifact is None:
        return transient_harness_initial_research_plan_timeline_response(db, project_id=project_id, locale=locale)
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
    validation = research_plan_contract_validation_summary(
        db,
        project_id=project_id,
        payload=payload if isinstance(payload, dict) else {},
    )
    if research_plan_payload_is_promotable_artifact(
        db,
        project_id=project_id,
        payload=payload,
        validation=validation,
    ):
        try:
            result = commit_research_plan_artifact_revision(
                db,
                artifact=artifact,
                reason=f"Committed valid legacy research_plan artifact {artifact.id} from timeline read.",
                strict_validation=False,
            )
        except ResearchPlanValidationError:
            result = None
        if result is not None:
            return build_research_plan_timeline_response(db, project_id=project_id, locale=locale)
    if not research_plan_payload_is_displayable_legacy(payload, locale=locale):
        response = transient_harness_initial_research_plan_timeline_response(db, project_id=project_id, locale=locale)
        response["ignored_source_artifact"] = ignored_research_plan_source_payload(artifact, validation=validation)
        return response
    raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
    response_locale = _research_plan_effective_locale(locale, payload)
    return {
        "schema_version": "research_plan_timeline.v1",
        "project_id": project_id,
        "source_artifact_id": artifact.id,
        "response_locale": response_locale,
        "requested_locale": locale,
        "authored_locale": _research_plan_payload_locale(payload),
        "generated_at": artifact.created_at.isoformat(),
        "contract_validation": research_plan_contract_validation_summary(
            db,
            project_id=project_id,
            payload=payload if isinstance(payload, dict) else {},
        ),
        "current_work": annotate_research_plan_current_work_activity(
            db,
            project_id=project_id,
            payload=research_plan_effective_current_work_payload(
                db,
                project_id=project_id,
                revision=None,
                raw_blocks=raw_blocks,
                locale=response_locale,
            ),
        ),
        "artifact_links": [],
        "blocks": clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale),
    }


def transient_harness_initial_research_plan_timeline_response(
    db: Session,
    *,
    project_id: str,
    locale: str | None = None,
) -> dict[str, Any]:
    payload = harness_initial_research_plan_document(project_id=project_id)
    raw_blocks = payload.get("timeline_blocks")
    response_locale = _research_plan_effective_locale(locale, payload)
    return {
        "schema_version": "research_plan_timeline.v1",
        "project_id": project_id,
        "source_artifact_id": None,
        "source_revision_id": None,
        "research_plan_id": None,
        "revision_index": 0,
        "revision_author_type": "harness",
        "response_locale": response_locale,
        "requested_locale": locale,
        "authored_locale": _research_plan_payload_locale(payload),
        "generated_at": utc_now().isoformat(),
        "contract_validation": research_plan_contract_validation_summary(
            db,
            project_id=project_id,
            payload=payload,
        ),
        "current_work": annotate_research_plan_current_work_activity(
            db,
            project_id=project_id,
            payload=research_plan_effective_current_work_payload(
                db,
                project_id=project_id,
                revision=None,
                raw_blocks=raw_blocks,
                locale=response_locale,
            ),
        ),
        "artifact_links": [],
        "blocks": clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale),
    }


def latest_research_plan_artifact(db: Session, *, project_id: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "research_plan")
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )


def research_plan_payload_is_promotable_artifact(
    db: Session,
    *,
    project_id: str,
    payload: Any,
    validation: dict[str, Any] | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    raw_blocks = payload.get("timeline_blocks")
    if not isinstance(raw_blocks, list):
        return False
    validation_summary = validation or research_plan_contract_validation_summary(
        db,
        project_id=project_id,
        payload=payload,
    )
    return int(validation_summary.get("error_count") or 0) == 0


def research_plan_payload_is_displayable_legacy(payload: Any, *, locale: str | None = None) -> bool:
    if not isinstance(payload, dict):
        return False
    blocks = clean_research_plan_timeline_blocks(payload.get("timeline_blocks"), locale=locale)
    if not blocks:
        return False
    return len(blocks) <= PLAN_MAX_TOP_LEVEL_BLOCKS


def research_plan_artifact_should_commit(artifact: Artifact, *, revision: Any | None) -> bool:
    if revision is None:
        return True
    if revision.source_artifact_id == artifact.id:
        return False
    revision_created_at = revision.created_at
    artifact_created_at = artifact.created_at
    return artifact_created_at >= revision_created_at


def ignored_research_plan_source_payload(artifact: Artifact, *, validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ignored_research_plan_source.v1",
        "status": "needs_revision",
        "source_artifact_id": artifact.id,
        "artifact_name": artifact.name,
        "artifact_version": artifact.version,
        "reason": "latest_research_plan_artifact_failed_contract_validation",
        "contract_validation": validation,
    }


def annotate_research_plan_current_work_activity(
    db: Session,
    *,
    project_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    annotated = dict(payload)
    project = db.get(Project, project_id)
    if project is None or project.current_phase != "AUTONOMOUS_LOOP":
        annotated["activity_state"] = "paused"
        annotated["is_live"] = False
        return annotated
    session = db.scalar(
        select(AgentSession)
        .where(
            AgentSession.project_id == project_id,
            AgentSession.session_type == "main_autonomous",
            AgentSession.status.in_(("starting", "running", "between_turns", "waiting_for_runner")),
        )
        .order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
    )
    if session is None:
        annotated["activity_state"] = "inactive"
        annotated["is_live"] = False
        return annotated
    if annotated.get("source") == "research_plan_revision_status":
        annotated["activity_state"] = "declared_only"
        annotated["is_live"] = False
        annotated["agent_session_id"] = session.id
        annotated["agent_session_status"] = session.status
        annotated["observed_codex_process_count"] = len(running_codex_processes_for_project(project_id))
        return annotated
    observed_processes = running_codex_processes_for_project(project_id)
    if session.status == "running" and observed_processes:
        annotated["activity_state"] = "active"
        annotated["is_live"] = True
    elif session.status in {"starting", "running", "between_turns", "waiting_for_runner"}:
        annotated["activity_state"] = "scheduled"
        annotated["is_live"] = False
    else:
        annotated["activity_state"] = "inactive"
        annotated["is_live"] = False
    annotated["agent_session_id"] = session.id
    annotated["agent_session_status"] = session.status
    annotated["observed_codex_process_count"] = len(observed_processes)
    return annotated


def research_plan_effective_current_work_payload(
    db: Session,
    *,
    project_id: str,
    revision: Any | None,
    raw_blocks: Any,
    locale: str | None = None,
) -> dict[str, Any] | None:
    stored = latest_research_plan_current_work(db, project_id=project_id)
    blocks = [block for block in raw_blocks if isinstance(block, dict)] if isinstance(raw_blocks, list) else []
    block_by_id = {research_plan_block_id(block, index): block for index, block in enumerate(blocks)}
    stored_payload = research_plan_current_work_payload(stored)
    current_blocks = [
        (index, block)
        for index, block in enumerate(blocks)
        if research_plan_block_status(block) in PLAN_CURRENT_STATUSES
    ]
    stored_block = block_by_id.get(str(stored_payload.get("node_id"))) if stored_payload is not None else None
    stored_block_status = research_plan_block_status(stored_block) if stored_block is not None else None
    stored_summary = str(stored_payload.get("summary") or "").strip() if stored_payload is not None else ""
    if (
        stored_payload is not None
        and stored_summary
        and stored_block is not None
        and stored_block_status in PLAN_CURRENT_STATUSES
    ):
        return stored_payload

    if len(current_blocks) != 1:
        return None
    index, block = current_blocks[0]
    node_id = research_plan_block_id(block, index)
    deliverable_contract = block.get("deliverable_contract")
    expected_outputs: list[str] = []
    if isinstance(deliverable_contract, dict) and isinstance(deliverable_contract.get("expected_outputs"), list):
        expected_outputs = [str(item) for item in deliverable_contract["expected_outputs"] if str(item).strip()]
    summary = (
        _research_plan_block_subtitle(block, locale=locale)
        or _research_plan_display_string(block, "title", locale=locale)
        or ""
    )
    revision_id = getattr(revision, "id", None)
    research_plan_id = getattr(revision, "research_plan_id", None)
    updated_at = getattr(revision, "created_at", None)
    return {
        "id": f"derived:{revision_id or 'artifact'}:{node_id}",
        "project_id": project_id,
        "research_plan_id": research_plan_id or "",
        "revision_id": revision_id,
        "node_id": node_id,
        "status": research_plan_block_status(block),
        "summary": str(summary),
        "expected_outputs": expected_outputs,
        "updated_by_type": "codex",
        "updated_by": None,
        "updated_at": updated_at.isoformat() if updated_at is not None else "",
        "source": "research_plan_revision_status",
    }


def research_plan_contract_validation_summary(
    db: Session,
    *,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    issues = validate_research_plan_document(db, project_id=project_id, document=payload, strict=True)
    errors = [issue for issue in issues if issue.get("severity", "error") == "error"]
    warnings = [issue for issue in issues if issue.get("severity") == "warning"]
    return {
        "schema_version": "research_plan_contract_validation.v1",
        "status": "needs_revision" if errors else "ok",
        "issue_count": len(issues),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues[:12],
    }


def merge_research_plan_links(*link_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for links in link_groups:
        for link in links:
            link_type = str(link.get("link_type") or "artifact")
            node_id = str(link.get("node_id") or "")
            target_id = str(link.get("artifact_id") or link.get("run_id") or link.get("id") or "")
            role = str(link.get("role") or "")
            key = (link_type, node_id, target_id, role)
            if key in seen:
                continue
            seen.add(key)
            merged.append(link)
    return merged


def research_plan_evidence_links(
    db: Session,
    *,
    revision: Any,
    raw_blocks: Any,
) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    links: list[dict[str, Any]] = []
    for block_index, block in enumerate(raw_blocks):
        if not isinstance(block, dict):
            continue
        node_id = research_plan_block_id(block, block_index)
        for item_index, item in enumerate(research_plan_evidence_items(block)):
            role = research_plan_evidence_role(item)
            artifact = research_plan_visible_artifact_for_link(
                db,
                research_plan_evidence_artifact(db, project_id=revision.project_id, item=item),
            )
            if artifact is not None:
                links.append(
                    {
                        "id": f"evidence_artifact:{revision.id}:{node_id}:{item_index}:{artifact.id}",
                        "link_type": "artifact",
                        "revision_id": revision.id,
                        "node_id": node_id,
                        "role": role,
                        "artifact_id": artifact.id,
                        "artifact_name": artifact.name,
                        "asset_type": artifact.asset_type,
                        "artifact_version": artifact.version,
                        **research_plan_artifact_surface_target(artifact, role=role),
                        "metadata": {"source": "research_plan_completion_evidence"},
                        "created_at": revision.created_at.isoformat(),
                    }
                )
            for run_id in research_plan_evidence_run_ids(item):
                run = db.get(ExperimentRun, run_id)
                if run is None or run.project_id != revision.project_id:
                    continue
                links.append(
                    {
                        "id": f"evidence_run:{revision.id}:{node_id}:{item_index}:{run.id}",
                        "link_type": "experiment_run",
                        "revision_id": revision.id,
                        "node_id": node_id,
                        "role": role,
                        "run_id": run.id,
                        "artifact_id": None,
                        "artifact_name": research_plan_run_label(run),
                        "asset_type": "experiment_run",
                        "artifact_version": None,
                        "target_tab": "Leaderboard",
                        "target_anchor": "result-readout",
                        "metadata": {
                            "source": "research_plan_completion_evidence",
                            "runner_type": run.runner_type,
                            "status": run.status,
                        },
                        "created_at": revision.created_at.isoformat(),
                    }
                )
    return links


def research_plan_evidence_role(item: dict[str, Any]) -> str:
    for key in ("role", "output_type", "type", "asset_type", "kind"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return "evidence"


def research_plan_run_label(run: ExperimentRun) -> str:
    params = loads_json(run.params_json, {})
    if isinstance(params, dict):
        for key in ("model_id", "run_name", "name", "condition"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return f"{value.strip()} · {run.id}"
    return run.id


def attach_research_plan_artifact_links_to_blocks(
    blocks: list[dict[str, Any]],
    artifact_links: list[dict[str, Any]],
) -> None:
    by_node_id: dict[str, list[dict[str, Any]]] = {}
    for link in artifact_links:
        node_id = link.get("node_id")
        if isinstance(node_id, str) and node_id:
            by_node_id.setdefault(node_id, []).append(link)
    for block in blocks:
        block_id = block.get("id")
        if isinstance(block_id, str):
            block["attached_artifacts"] = by_node_id.get(block_id, [])


def clean_research_plan_timeline_blocks(raw_blocks: Any, *, locale: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    statuses = {"done", "active", "pending", "blocked", "waiting", "skipped"}
    blocks: list[dict[str, Any]] = []
    for index, raw_block in enumerate(raw_blocks[:40], start=1):
        if not isinstance(raw_block, dict):
            continue
        subtasks = clean_research_plan_timeline_subtasks(raw_block.get("subtasks"), locale=locale)
        title = _research_plan_display_string(
            raw_block,
            "title",
            locale=locale,
        )
        if not title:
            continue
        raw_status = raw_block.get("status")
        status = raw_status if isinstance(raw_status, str) and raw_status in statuses else "pending"
        block_id = raw_block.get("id")
        supporting_artifacts = _research_plan_supporting_artifacts(raw_block.get("supporting_artifacts"), limit=8)
        missing_supporting_artifact_count = sum(1 for item in supporting_artifacts if item.get("exists") is False)
        evidence = _research_plan_block_evidence(raw_block, locale=locale)
        subtitle = _research_plan_block_subtitle(raw_block, locale=locale)
        blocks.append(
            {
                "id": block_id if isinstance(block_id, str) and block_id.strip() else f"plan_block_{index}",
                "title": title.strip()[:160],
                "subtitle": subtitle[:600],
                "status": status,
                "evidence": evidence[:240] if evidence else None,
                "target_tab": raw_block.get("target_tab") if isinstance(raw_block.get("target_tab"), str) else None,
                "target_anchor": raw_block.get("target_anchor") if isinstance(raw_block.get("target_anchor"), str) else None,
                "subtasks": subtasks,
                "phase": str(raw_block.get("phase") or "").strip()[:120] or None,
                "next_action": (_research_plan_display_string(raw_block, "next_action", locale=locale) or "")[:600],
                "done_criteria": (_research_plan_display_string(raw_block, "done_criteria", locale=locale) or "")[:600],
                "blockers": _research_plan_string_list(
                    _research_plan_localized_value(raw_block, "blockers", locale=locale, allow_unlocalized_fallback=True),
                    limit=6,
                ),
                "supporting_artifacts": supporting_artifacts,
                "missing_supporting_artifact_count": missing_supporting_artifact_count,
                "evidence_verified": missing_supporting_artifact_count == 0,
                "status_adjustment_reason": None,
            }
        )
    return blocks


def clean_research_plan_timeline_subtasks(raw_subtasks: Any, *, locale: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw_subtasks, list):
        return []
    statuses = {"done", "active", "pending", "blocked", "waiting", "skipped"}
    subtasks: list[dict[str, Any]] = []
    for index, raw_subtask in enumerate(raw_subtasks[:80], start=1):
        if not isinstance(raw_subtask, dict):
            continue
        title = _research_plan_display_string(
            raw_subtask,
            "title",
            locale=locale,
        )
        if not title:
            continue
        raw_status = raw_subtask.get("status")
        status = raw_status if isinstance(raw_status, str) and raw_status in statuses else "pending"
        subtask_id = raw_subtask.get("id")
        evidence = _research_plan_localized_value(
            raw_subtask,
            "evidence",
            locale=locale,
            allow_unlocalized_fallback=True,
        )
        subtasks.append(
            {
                "id": subtask_id if isinstance(subtask_id, str) and subtask_id.strip() else f"subtask_{index}",
                "title": title.strip()[:160],
                "detail": (
                    _research_plan_display_string(raw_subtask, "detail", locale=locale)
                    or _research_plan_display_string(raw_subtask, "subtitle", locale=locale)
                    or ""
                )[:600],
                "status": status,
                "evidence": str(evidence).strip()[:240] if evidence is not None else None,
                "target_tab": raw_subtask.get("target_tab") if isinstance(raw_subtask.get("target_tab"), str) else None,
                "target_anchor": raw_subtask.get("target_anchor") if isinstance(raw_subtask.get("target_anchor"), str) else None,
            }
        )
    return subtasks


def _research_plan_block_subtitle(raw_block: dict[str, Any], *, locale: str | None = None) -> str:
    for key in ("subtitle", "why_it_matters", "next_action", "notes", "done_criteria"):
        value = _research_plan_display_string(raw_block, key, locale=locale)
        if value:
            return value.strip()
    return ""


def _research_plan_block_evidence(raw_block: dict[str, Any], *, locale: str | None = None) -> str | None:
    evidence = _research_plan_localized_value(raw_block, "evidence", locale=locale, allow_unlocalized_fallback=True)
    if isinstance(evidence, str) and evidence.strip():
        return evidence.strip()
    blockers = _research_plan_string_list(
        _research_plan_localized_value(raw_block, "blockers", locale=locale, allow_unlocalized_fallback=True), limit=3
    )
    if blockers:
        return _research_plan_count_label(len(blockers), "blocker", locale=locale)
    supporting_artifacts = _research_plan_supporting_artifacts(raw_block.get("supporting_artifacts"), limit=8)
    existing_count = sum(1 for item in supporting_artifacts if item.get("exists") is True)
    if existing_count:
        return _research_plan_count_label(existing_count, "evidence", locale=locale)
    phase = raw_block.get("phase")
    if isinstance(phase, str) and phase.strip():
        return phase.strip()
    return None


def _research_plan_display_string(
    raw_block: dict[str, Any],
    key: str,
    *,
    locale: str | None,
) -> str | None:
    value = _research_plan_localized_value(raw_block, key, locale=locale, allow_unlocalized_fallback=False)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raw_value = raw_block.get(key)
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    return None


def _research_plan_localized_string(
    raw_block: dict[str, Any],
    key: str,
    *,
    locale: str | None,
    allow_unlocalized_fallback: bool = True,
) -> str | None:
    value = _research_plan_localized_value(
        raw_block,
        key,
        locale=locale,
        allow_unlocalized_fallback=allow_unlocalized_fallback,
    )
    return value.strip() if isinstance(value, str) and value.strip() else None


def _research_plan_localized_value(
    raw_block: dict[str, Any],
    key: str,
    *,
    locale: str | None,
    allow_unlocalized_fallback: bool = True,
) -> Any:
    explicit_value = _research_plan_explicit_localized_value(raw_block, key, locale=locale)
    if explicit_value is not _MISSING:
        return explicit_value
    if not allow_unlocalized_fallback:
        return _MISSING
    value = raw_block.get(key)
    return value


def _research_plan_explicit_localized_value(raw_block: dict[str, Any], key: str, *, locale: str | None) -> Any:
    locale_keys = _research_plan_locale_keys(locale)
    if not locale_keys:
        return _MISSING
    for container_key in ("localizations", "localized", "translations", "translated"):
        container = raw_block.get(container_key)
        if not isinstance(container, dict):
            continue
        for locale_key in locale_keys:
            localized = container.get(locale_key)
            if isinstance(localized, dict) and key in localized:
                return localized[key]
    for container_key in ("display", "human_display", "ui_display", "localized_display"):
        container = raw_block.get(container_key)
        if not isinstance(container, dict):
            continue
        for locale_key in locale_keys:
            localized = container.get(locale_key)
            if isinstance(localized, dict) and key in localized:
                return localized[key]
        for field_key in (key, *_research_plan_display_field_keys(key)):
            if field_key in container:
                return container[field_key]
    for locale_key in locale_keys:
        suffix = locale_key.replace("-", "_")
        for field_key in (f"{key}_{suffix}", f"{suffix}_{key}"):
            if field_key in raw_block:
                return raw_block[field_key]
    for field_key in _research_plan_display_field_keys(key):
        if field_key in raw_block:
            return raw_block[field_key]
    return _MISSING


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


def _research_plan_locale_keys(locale: str | None) -> list[str]:
    if not isinstance(locale, str) or not locale.strip():
        return []
    normalized = locale.strip().replace("_", "-")
    lower = normalized.lower()
    language = lower.split("-", 1)[0]
    keys = [normalized, lower, language]
    if _research_plan_locale_is_japanese(locale):
        keys.extend(["ja-JP", "ja-jp", "ja", "Japanese", "japanese", "日本語", "Japanese / 日本語"])
    elif language == "en":
        keys.extend(["en-US", "en-us", "en", "English", "english"])
    return list(dict.fromkeys(keys))


def _research_plan_string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text:
            output.append(text[:240])
    return output


def _research_plan_supporting_artifacts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("artifact_id") or item.get("name") or "").strip()
            if not path:
                continue
            output.append(
                {
                    "path": path[:320],
                    "exists": bool(item.get("exists")) if "exists" in item else None,
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                output.append({"path": text[:320], "exists": None})
    return output

def _research_plan_locale_is_japanese(locale: str | None) -> bool:
    if not isinstance(locale, str):
        return False
    normalized = locale.strip().casefold().replace("_", "-")
    return normalized == "ja" or normalized.startswith("ja-") or "japanese" in normalized or "日本語" in normalized


def _research_plan_effective_locale(requested_locale: str | None, payload: Any) -> str | None:
    if isinstance(requested_locale, str) and requested_locale.strip():
        return requested_locale.strip()
    return _research_plan_payload_locale(payload)


def _research_plan_payload_locale(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("response_locale", "locale", "language"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for container_key in ("project", "human_interface", "ui", "display"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("response_locale", "locale", "language", "notebook_language"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _research_plan_count_label(count: int, noun: str, *, locale: str | None) -> str:
    if _research_plan_locale_is_japanese(locale):
        if noun == "blocker":
            return f"ブロッカー {count}件"
        if noun == "evidence":
            return f"根拠 {count}件"
    if noun == "blocker":
        return f"{count} blocker{'s' if count != 1 else ''}"
    return f"{count} evidence"
