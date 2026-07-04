from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, utc_now
from tabular_harness.services.artifacts import artifact_primary_path
from tabular_harness.services.locales import locale_language
from tabular_harness.services.research_plans import (
    latest_research_plan_current_work,
    latest_research_plan_revision,
    research_plan_artifact_links,
    research_plan_current_work_payload,
    research_plan_revision_document,
)

_MISSING = object()


def build_research_plan_timeline_response(db: Session, *, project_id: str, locale: str | None = None) -> dict[str, Any]:
    revision = latest_research_plan_revision(db, project_id=project_id)
    if revision is not None:
        payload = research_plan_revision_document(revision)
        raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
        response_locale = _research_plan_effective_locale(locale, payload)
        artifact_links = research_plan_artifact_links(db, revision=revision)
        blocks = clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale)
        attach_research_plan_artifact_links_to_blocks(blocks, artifact_links)
        return {
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
            "localization": research_plan_localization_summary(raw_blocks, locale=response_locale),
            "current_work": research_plan_current_work_payload(
                latest_research_plan_current_work(db, project_id=project_id)
            ),
            "artifact_links": artifact_links,
            "blocks": blocks,
        }
    artifact = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "research_plan")
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    if artifact is None:
        return {
            "schema_version": "research_plan_timeline.v1",
            "project_id": project_id,
            "source_artifact_id": None,
            "response_locale": locale,
            "generated_at": utc_now().isoformat(),
            "localization": research_plan_localization_summary([], locale=locale),
            "current_work": research_plan_current_work_payload(
                latest_research_plan_current_work(db, project_id=project_id)
            ),
            "artifact_links": [],
            "blocks": [],
        }
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
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
        "localization": research_plan_localization_summary(raw_blocks, locale=response_locale),
        "current_work": research_plan_current_work_payload(
            latest_research_plan_current_work(db, project_id=project_id)
        ),
        "artifact_links": [],
        "blocks": clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale),
    }


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
                "localization_status": "localized",
                "missing_localization_fields": [],
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
                "localization_status": "localized",
                "missing_localization_fields": [],
            }
        )
    return subtasks


def research_plan_localization_summary(raw_blocks: Any, *, locale: str | None = None) -> dict[str, Any]:
    return {
        "requested_locale": locale,
        "requires_explicit_locale": False,
        "missing_block_count": 0,
        "missing_subtask_count": 0,
        "blocks": [],
    }


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


def _research_plan_locale_language(locale: str | None) -> str:
    return locale_language(locale)


def _research_plan_locale_is_japanese(locale: str | None) -> bool:
    return _research_plan_locale_language(locale) == "ja"


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
