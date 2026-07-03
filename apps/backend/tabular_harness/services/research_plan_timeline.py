from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, utc_now
from tabular_harness.services.artifacts import artifact_primary_path


def build_research_plan_timeline_response(db: Session, *, project_id: str, locale: str | None = None) -> dict[str, Any]:
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
            "blocks": [],
        }
    try:
        payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
    except OSError:
        payload = {}
    raw_blocks = payload.get("timeline_blocks") if isinstance(payload, dict) else None
    return {
        "schema_version": "research_plan_timeline.v1",
        "project_id": project_id,
        "source_artifact_id": artifact.id,
        "response_locale": locale,
        "generated_at": artifact.created_at.isoformat(),
        "localization": research_plan_localization_summary(raw_blocks, locale=locale),
        "blocks": clean_research_plan_timeline_blocks(raw_blocks, locale=locale),
    }


def clean_research_plan_timeline_blocks(raw_blocks: Any, *, locale: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    statuses = {"done", "active", "pending", "blocked", "waiting", "skipped"}
    blocks: list[dict[str, Any]] = []
    for index, raw_block in enumerate(raw_blocks[:40], start=1):
        if not isinstance(raw_block, dict):
            continue
        title = _research_plan_display_string(
            raw_block,
            "title",
            locale=locale,
            placeholder=_research_plan_placeholder("block_title", locale=locale),
        )
        if not title:
            continue
        raw_status = raw_block.get("status")
        status = raw_status if isinstance(raw_status, str) and raw_status in statuses else "pending"
        block_id = raw_block.get("id")
        supporting_artifacts = _research_plan_supporting_artifacts(raw_block.get("supporting_artifacts"), limit=8)
        missing_supporting_artifact_count = sum(1 for item in supporting_artifacts if item.get("exists") is False)
        status_adjustment_reason = (
            "missing_supporting_artifacts" if status == "done" and missing_supporting_artifact_count else None
        )
        display_status = "pending" if status_adjustment_reason else status
        evidence = _research_plan_block_evidence(raw_block, locale=locale)
        subtitle = _research_plan_block_subtitle(raw_block, locale=locale)
        missing_localization_fields = _research_plan_missing_localization_fields(
            raw_block,
            locale=locale,
            fields=("title", "subtitle", "why_it_matters", "next_action", "done_criteria", "notes", "blockers"),
        )
        subtasks = clean_research_plan_timeline_subtasks(raw_block.get("subtasks"), locale=locale)
        subtask_needs_locale = any(item.get("localization_status") == "needs_locale_refresh" for item in subtasks)
        blocks.append(
            {
                "id": block_id if isinstance(block_id, str) and block_id.strip() else f"plan_block_{index}",
                "title": title.strip()[:160],
                "subtitle": subtitle[:600],
                "status": display_status,
                "evidence": evidence[:240] if evidence else None,
                "target_tab": raw_block.get("target_tab") if isinstance(raw_block.get("target_tab"), str) else None,
                "target_anchor": raw_block.get("target_anchor") if isinstance(raw_block.get("target_anchor"), str) else None,
                "subtasks": subtasks,
                "phase": str(raw_block.get("phase") or "").strip()[:120] or None,
                "next_action": (
                    _research_plan_display_string(raw_block, "next_action", locale=locale, placeholder=None) or ""
                )[:600]
                or None,
                "done_criteria": (
                    _research_plan_display_string(raw_block, "done_criteria", locale=locale, placeholder=None) or ""
                )[:600]
                or None,
                "blockers": _research_plan_string_list(
                    _research_plan_localized_value(raw_block, "blockers", locale=locale, allow_unlocalized_fallback=False),
                    limit=6,
                ),
                "supporting_artifacts": supporting_artifacts,
                "missing_supporting_artifact_count": missing_supporting_artifact_count,
                "status_adjustment_reason": status_adjustment_reason,
                "localization_status": "needs_locale_refresh"
                if missing_localization_fields or subtask_needs_locale
                else "localized",
                "missing_localization_fields": missing_localization_fields,
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
            placeholder=_research_plan_placeholder("subtask_title", locale=locale),
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
            allow_unlocalized_fallback=False,
        )
        missing_localization_fields = _research_plan_missing_localization_fields(
            raw_subtask,
            locale=locale,
            fields=("title", "detail", "subtitle", "evidence"),
        )
        subtasks.append(
            {
                "id": subtask_id if isinstance(subtask_id, str) and subtask_id.strip() else f"subtask_{index}",
                "title": title.strip()[:160],
                "detail": (
                    _research_plan_display_string(raw_subtask, "detail", locale=locale, placeholder=None)
                    or _research_plan_display_string(raw_subtask, "subtitle", locale=locale, placeholder=None)
                    or ""
                )[:600],
                "status": status,
                "evidence": str(evidence).strip()[:240] if evidence is not None else None,
                "target_tab": raw_subtask.get("target_tab") if isinstance(raw_subtask.get("target_tab"), str) else None,
                "target_anchor": raw_subtask.get("target_anchor") if isinstance(raw_subtask.get("target_anchor"), str) else None,
                "localization_status": "needs_locale_refresh" if missing_localization_fields else "localized",
                "missing_localization_fields": missing_localization_fields,
            }
        )
    return subtasks


def research_plan_localization_summary(raw_blocks: Any, *, locale: str | None = None) -> dict[str, Any]:
    if not isinstance(raw_blocks, list):
        raw_blocks = []
    block_issues: list[dict[str, Any]] = []
    subtask_issue_count = 0
    for index, raw_block in enumerate(raw_blocks[:40], start=1):
        if not isinstance(raw_block, dict):
            continue
        block_id = raw_block.get("id")
        missing_fields = _research_plan_missing_localization_fields(
            raw_block,
            locale=locale,
            fields=("title", "subtitle", "why_it_matters", "next_action", "done_criteria", "notes", "blockers"),
        )
        raw_subtasks = raw_block.get("subtasks")
        if isinstance(raw_subtasks, list):
            for raw_subtask in raw_subtasks[:80]:
                if not isinstance(raw_subtask, dict):
                    continue
                subtask_missing = _research_plan_missing_localization_fields(
                    raw_subtask,
                    locale=locale,
                    fields=("title", "detail", "subtitle", "evidence"),
                )
                if subtask_missing:
                    subtask_issue_count += 1
        if missing_fields:
            block_issues.append(
                {
                    "id": block_id if isinstance(block_id, str) and block_id.strip() else f"plan_block_{index}",
                    "title": str(raw_block.get("title") or "")[:160],
                    "missing_fields": missing_fields,
                }
            )
    return {
        "requested_locale": locale,
        "requires_explicit_locale": _research_plan_requires_explicit_locale(locale),
        "missing_block_count": len(block_issues),
        "missing_subtask_count": subtask_issue_count,
        "blocks": block_issues[:20],
    }


def _research_plan_block_subtitle(raw_block: dict[str, Any], *, locale: str | None = None) -> str:
    for key in ("subtitle", "why_it_matters", "next_action", "notes", "done_criteria"):
        value = _research_plan_display_string(raw_block, key, locale=locale, placeholder=None)
        if value:
            return value.strip()
    return ""


def _research_plan_block_evidence(raw_block: dict[str, Any], *, locale: str | None = None) -> str | None:
    evidence = _research_plan_localized_value(raw_block, "evidence", locale=locale, allow_unlocalized_fallback=False)
    if isinstance(evidence, str) and evidence.strip():
        return evidence.strip()
    blockers = _research_plan_string_list(
        _research_plan_localized_value(raw_block, "blockers", locale=locale, allow_unlocalized_fallback=False), limit=3
    )
    if blockers:
        return _research_plan_count_label(len(blockers), "blocker", locale=locale)
    supporting_artifacts = _research_plan_supporting_artifacts(raw_block.get("supporting_artifacts"), limit=8)
    existing_count = sum(1 for item in supporting_artifacts if item.get("exists") is True)
    if existing_count:
        return _research_plan_count_label(existing_count, "evidence", locale=locale)
    phase = raw_block.get("phase")
    if (
        isinstance(phase, str)
        and phase.strip()
        and (not _research_plan_requires_explicit_locale(locale) or _research_plan_text_matches_locale(phase, locale=locale))
    ):
        return phase.strip()
    return None


def _research_plan_display_string(
    raw_block: dict[str, Any],
    key: str,
    *,
    locale: str | None,
    placeholder: str | None,
) -> str | None:
    value = _research_plan_localized_value(raw_block, key, locale=locale, allow_unlocalized_fallback=False)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raw_value = raw_block.get(key)
    if placeholder and _research_plan_has_visible_value(raw_value):
        return placeholder
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
    locale_keys = _research_plan_locale_keys(locale)
    if locale_keys:
        for container_key in ("localizations", "localized"):
            container = raw_block.get(container_key)
            if not isinstance(container, dict):
                continue
            for locale_key in locale_keys:
                localized = container.get(locale_key)
                if isinstance(localized, dict) and key in localized:
                    return localized[key]
        for locale_key in locale_keys:
            field_key = f"{key}_{locale_key.replace('-', '_')}"
            if field_key in raw_block:
                return raw_block[field_key]
    value = raw_block.get(key)
    if allow_unlocalized_fallback or not _research_plan_requires_explicit_locale(locale):
        return value
    return value if _research_plan_value_matches_locale(value, locale=locale) else None


def _research_plan_locale_keys(locale: str | None) -> list[str]:
    if not isinstance(locale, str) or not locale.strip():
        return []
    normalized = locale.strip().replace("_", "-")
    lower = normalized.lower()
    language = lower.split("-", 1)[0]
    keys = [normalized, lower, language]
    if _research_plan_locale_is_japanese(locale):
        keys.extend(["ja-JP", "ja-jp", "ja"])
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


def _research_plan_missing_localization_fields(
    raw_block: dict[str, Any], *, locale: str | None, fields: tuple[str, ...]
) -> list[str]:
    if not _research_plan_requires_explicit_locale(locale):
        return []
    missing: list[str] = []
    for key in fields:
        if key not in raw_block:
            continue
        value = raw_block.get(key)
        if not _research_plan_has_visible_value(value):
            continue
        if _research_plan_has_explicit_locale_value(raw_block, key, locale=locale):
            continue
        if _research_plan_value_matches_locale(value, locale=locale):
            continue
        missing.append(key)
    return missing


def _research_plan_has_explicit_locale_value(raw_block: dict[str, Any], key: str, *, locale: str | None) -> bool:
    for locale_key in _research_plan_locale_keys(locale):
        for container_key in ("localizations", "localized"):
            container = raw_block.get(container_key)
            localized = container.get(locale_key) if isinstance(container, dict) else None
            if isinstance(localized, dict) and _research_plan_has_visible_value(localized.get(key)):
                return True
        field_key = f"{key}_{locale_key.replace('-', '_')}"
        if _research_plan_has_visible_value(raw_block.get(field_key)):
            return True
    return False


def _research_plan_has_visible_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_research_plan_has_visible_value(item) for item in value)
    return value is not None


def _research_plan_value_matches_locale(value: Any, *, locale: str | None) -> bool:
    if isinstance(value, str):
        return _research_plan_text_matches_locale(value, locale=locale)
    if isinstance(value, list):
        visible_items = [item for item in value if _research_plan_has_visible_value(item)]
        if not visible_items:
            return True
        return all(_research_plan_value_matches_locale(item, locale=locale) for item in visible_items)
    return True


def _research_plan_text_matches_locale(value: str, *, locale: str | None) -> bool:
    if not _research_plan_locale_is_japanese(locale):
        return False
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value))


def _research_plan_requires_explicit_locale(locale: str | None) -> bool:
    if not isinstance(locale, str) or not locale.strip():
        return False
    language = locale.strip().replace("_", "-").split("-", 1)[0].lower()
    return language not in {"", "en"}


def _research_plan_locale_is_japanese(locale: str | None) -> bool:
    if not isinstance(locale, str):
        return False
    normalized = locale.strip().lower().replace("_", "-")
    if not normalized:
        return False
    language = normalized.split("-", 1)[0]
    return language == "ja" or normalized in {"japanese", "日本語"} or normalized.startswith("日本語")


def _research_plan_placeholder(kind: str, *, locale: str | None) -> str:
    if _research_plan_locale_is_japanese(locale):
        if kind == "subtask_title":
            return "表示言語を更新中のサブタスク"
        return "表示言語を更新中の計画ブロック"
    if kind == "subtask_title":
        return "Subtask pending display-language refresh"
    return "Plan block pending display-language refresh"


def _research_plan_count_label(count: int, noun: str, *, locale: str | None) -> str:
    if _research_plan_locale_is_japanese(locale):
        if noun == "blocker":
            return f"ブロッカー {count}件"
        if noun == "evidence":
            return f"根拠 {count}件"
    if noun == "blocker":
        return f"{count} blocker{'s' if count != 1 else ''}"
    return f"{count} evidence"
