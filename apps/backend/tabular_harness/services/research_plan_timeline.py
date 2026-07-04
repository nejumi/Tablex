from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, utc_now
from tabular_harness.services.artifacts import artifact_primary_path
from tabular_harness.services.locales import locale_language

_MISSING = object()


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
        "blocks": clean_research_plan_timeline_blocks(raw_blocks, locale=response_locale),
    }


def clean_research_plan_timeline_blocks(raw_blocks: Any, *, locale: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    statuses = {"done", "active", "pending", "blocked", "waiting", "skipped"}
    blocks: list[dict[str, Any]] = []
    for index, raw_block in enumerate(raw_blocks[:40], start=1):
        if not isinstance(raw_block, dict):
            continue
        missing_localization_fields = _research_plan_missing_localization_fields(
            raw_block,
            locale=locale,
            fields=("title", "subtitle", "why_it_matters", "next_action", "done_criteria", "notes", "blockers"),
        )
        subtasks = clean_research_plan_timeline_subtasks(raw_block.get("subtasks"), locale=locale)
        subtask_needs_locale = any(item.get("localization_status") == "needs_locale_refresh" for item in subtasks)
        needs_locale_refresh = bool(missing_localization_fields or subtask_needs_locale)
        title = _research_plan_display_string(
            raw_block,
            "title",
            locale=locale,
        )
        if needs_locale_refresh and _research_plan_requires_explicit_locale(locale):
            title = _research_plan_missing_title_label(locale)
        elif not title:
            if _research_plan_requires_explicit_locale(locale) and _research_plan_has_visible_value(raw_block.get("title")):
                title = _research_plan_missing_title_label(locale)
            else:
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
        evidence = None if needs_locale_refresh else _research_plan_block_evidence(raw_block, locale=locale)
        subtitle = "" if needs_locale_refresh else _research_plan_block_subtitle(raw_block, locale=locale)
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
                    None
                    if needs_locale_refresh
                    else (_research_plan_display_string(raw_block, "next_action", locale=locale) or "")
                )[:600]
                if not needs_locale_refresh
                else None,
                "done_criteria": (
                    None
                    if needs_locale_refresh
                    else (_research_plan_display_string(raw_block, "done_criteria", locale=locale) or "")
                )[:600]
                if not needs_locale_refresh
                else None,
                "blockers": _research_plan_string_list(
                    None
                    if needs_locale_refresh
                    else _research_plan_localized_value(
                        raw_block, "blockers", locale=locale, allow_unlocalized_fallback=False
                    ),
                    limit=6,
                ),
                "supporting_artifacts": supporting_artifacts,
                "missing_supporting_artifact_count": missing_supporting_artifact_count,
                "status_adjustment_reason": status_adjustment_reason,
                "localization_status": "needs_locale_refresh" if needs_locale_refresh else "localized",
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
        )
        if not title:
            if _research_plan_requires_explicit_locale(locale) and _research_plan_has_visible_value(raw_subtask.get("title")):
                title = _research_plan_missing_title_label(locale)
            else:
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
        needs_locale_refresh = bool(missing_localization_fields)
        if needs_locale_refresh and _research_plan_requires_explicit_locale(locale):
            title = _research_plan_missing_title_label(locale)
        subtasks.append(
            {
                "id": subtask_id if isinstance(subtask_id, str) and subtask_id.strip() else f"subtask_{index}",
                "title": title.strip()[:160],
                "detail": ""
                if needs_locale_refresh
                else (
                    _research_plan_display_string(raw_subtask, "detail", locale=locale)
                    or _research_plan_display_string(raw_subtask, "subtitle", locale=locale)
                    or ""
                )[:600],
                "status": status,
                "evidence": None if needs_locale_refresh else str(evidence).strip()[:240] if evidence is not None else None,
                "target_tab": raw_subtask.get("target_tab") if isinstance(raw_subtask.get("target_tab"), str) else None,
                "target_anchor": raw_subtask.get("target_anchor") if isinstance(raw_subtask.get("target_anchor"), str) else None,
                "localization_status": "needs_locale_refresh" if needs_locale_refresh else "localized",
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
        value = _research_plan_display_string(raw_block, key, locale=locale)
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
) -> str | None:
    value = _research_plan_localized_value(raw_block, key, locale=locale, allow_unlocalized_fallback=False)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raw_value = raw_block.get(key)
    if isinstance(raw_value, str) and raw_value.strip() and not _research_plan_requires_explicit_locale(locale):
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
    if allow_unlocalized_fallback or not _research_plan_requires_explicit_locale(locale):
        return value
    return value if _research_plan_value_matches_locale(value, locale=locale) else None


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
                value = container[field_key]
                if not _research_plan_requires_explicit_locale(locale) or _research_plan_value_matches_locale(value, locale=locale):
                    return value
    for locale_key in locale_keys:
        suffix = locale_key.replace("-", "_")
        for field_key in (f"{key}_{suffix}", f"{suffix}_{key}"):
            if field_key in raw_block:
                return raw_block[field_key]
    for field_key in _research_plan_display_field_keys(key):
        if field_key in raw_block:
            value = raw_block[field_key]
            if not _research_plan_requires_explicit_locale(locale) or _research_plan_value_matches_locale(value, locale=locale):
                return value
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
    value = _research_plan_explicit_localized_value(raw_block, key, locale=locale)
    return value is not _MISSING and _research_plan_has_visible_value(value)


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
    language = _research_plan_locale_language(locale)
    if language == "en":
        return not _research_plan_has_cjk_text(value)
    if language != "ja":
        return False
    japanese_char_count = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", value))
    latin_letter_count = len(re.findall(r"[A-Za-z]", value))
    if japanese_char_count < 2:
        return False
    if _research_plan_has_unlocalized_latin_phrase(value):
        return False
    return latin_letter_count <= max(18, int(japanese_char_count * 1.5))


def _research_plan_has_unlocalized_latin_phrase(value: str) -> bool:
    """Detect English phrase fragments that should not leak into localized plan UI."""
    stripped = re.sub(r"`[^`]*`", " ", value)
    stripped = re.sub(r"https?://\S+", " ", stripped)
    for fragment in re.split(r"[\u3040-\u30ff\u3400-\u9fff]+", stripped):
        words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", fragment)
        if len(words) >= 2:
            return True
    return False


def _research_plan_has_cjk_text(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value))


def _research_plan_requires_explicit_locale(locale: str | None) -> bool:
    return bool(_research_plan_locale_language(locale))


def _research_plan_missing_title_label(locale: str | None) -> str:
    if _research_plan_locale_is_japanese(locale):
        return "表示言語の更新待ち"
    return "Display language refresh pending"


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
