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
        title = _research_plan_localized_string(raw_block, "title", locale=locale)
        if not title:
            continue
        raw_status = raw_block.get("status")
        status = raw_status if isinstance(raw_status, str) and raw_status in statuses else "pending"
        block_id = raw_block.get("id")
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
                "subtasks": clean_research_plan_timeline_subtasks(raw_block.get("subtasks"), locale=locale),
                "phase": str(raw_block.get("phase") or "").strip()[:120] or None,
                "next_action": (_research_plan_localized_string(raw_block, "next_action", locale=locale) or "")[:600] or None,
                "done_criteria": (_research_plan_localized_string(raw_block, "done_criteria", locale=locale) or "")[:600]
                or None,
                "blockers": _research_plan_string_list(
                    _research_plan_localized_value(raw_block, "blockers", locale=locale), limit=6
                ),
                "supporting_artifacts": _research_plan_supporting_artifacts(raw_block.get("supporting_artifacts"), limit=8),
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
        title = _research_plan_localized_string(raw_subtask, "title", locale=locale)
        if not title:
            continue
        raw_status = raw_subtask.get("status")
        status = raw_status if isinstance(raw_status, str) and raw_status in statuses else "pending"
        subtask_id = raw_subtask.get("id")
        evidence = _research_plan_localized_value(raw_subtask, "evidence", locale=locale)
        subtasks.append(
            {
                "id": subtask_id if isinstance(subtask_id, str) and subtask_id.strip() else f"subtask_{index}",
                "title": title.strip()[:160],
                "detail": (
                    _research_plan_localized_string(raw_subtask, "detail", locale=locale)
                    or _research_plan_localized_string(raw_subtask, "subtitle", locale=locale)
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
        value = _research_plan_localized_string(raw_block, key, locale=locale)
        if value:
            return value.strip()
    return ""


def _research_plan_block_evidence(raw_block: dict[str, Any], *, locale: str | None = None) -> str | None:
    evidence = _research_plan_localized_value(raw_block, "evidence", locale=locale)
    if isinstance(evidence, str) and evidence.strip():
        return evidence.strip()
    blockers = _research_plan_string_list(_research_plan_localized_value(raw_block, "blockers", locale=locale), limit=3)
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


def _research_plan_localized_string(raw_block: dict[str, Any], key: str, *, locale: str | None) -> str | None:
    value = _research_plan_localized_value(raw_block, key, locale=locale)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _research_plan_localized_value(raw_block: dict[str, Any], key: str, *, locale: str | None) -> Any:
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
    return _research_plan_locale_fallback(raw_block.get(key), key=key, locale=locale)


def _research_plan_locale_keys(locale: str | None) -> list[str]:
    if not isinstance(locale, str) or not locale.strip():
        return []
    normalized = locale.strip().replace("_", "-")
    lower = normalized.lower()
    language = lower.split("-", 1)[0]
    return list(dict.fromkeys([normalized, lower, language]))


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


def _research_plan_locale_fallback(value: Any, *, key: str, locale: str | None) -> Any:
    if not _research_plan_locale_is_japanese(locale):
        return value
    if isinstance(value, str):
        return _research_plan_japanese_structured_text(value, key=key)
    if isinstance(value, list):
        return [_research_plan_japanese_structured_text(item, key=key) if isinstance(item, str) else item for item in value]
    return value


def _research_plan_locale_is_japanese(locale: str | None) -> bool:
    return isinstance(locale, str) and locale.strip().lower().replace("_", "-").startswith("ja")


def _research_plan_count_label(count: int, noun: str, *, locale: str | None) -> str:
    if _research_plan_locale_is_japanese(locale):
        if noun == "blocker":
            return f"ブロッカー {count}件"
        if noun == "evidence":
            return f"根拠 {count}件"
    if noun == "blocker":
        return f"{count} blocker{'s' if count != 1 else ''}"
    return f"{count} evidence"


_RESEARCH_PLAN_JA_TITLE_FALLBACKS = {
    "approval blocker handoff": "承認ブロッカー引き継ぎ",
    "approval decision brief": "承認判断ブリーフ",
    "approval response contract": "承認回答の契約",
    "approval response intake guard": "承認回答の取り込みガード",
    "approval review evidence pack": "承認レビュー用の根拠パック",
    "baseline and diagnostics": "ベースラインと診断",
    "baseline, diagnostics, release candidate evidence": "ベースライン・診断・リリース候補の根拠",
    "baseline、diagnostics、release candidate evidence": "ベースライン・診断・リリース候補の根拠",
    "contextual money mention triage": "文脈別の金額表現トリアージ",
    "data owner approval request": "データオーナーへの承認依頼",
    "data owner faq": "データオーナーFAQ",
    "data owner response kit": "データオーナー回答キット",
    "feature availability and leakage surface audit": "特徴量利用可否と漏洩面の監査",
    "inbox delivery acknowledgement": "受信箱反映の確認",
    "post-response execution runbook": "回答後の実行手順",
    "prior-knowledge research anchors": "従来知見の調査アンカー",
    "target policy human resolution": "ターゲット方針の人間確認",
    "target policy response dry-run harness": "ターゲット方針回答のドライランハーネス",
    "target policy risk register": "ターゲット方針リスク台帳",
    "target-free input schema guard": "ターゲット非依存の入力スキーマガード",
    "text compensation leakage audit": "テキスト内報酬表現の漏洩監査",
    "text scrub blast radius": "テキストマスク影響範囲",
    "text scrub policy contract": "テキストマスク方針契約",
    "text scrub policy simulator": "テキストマスク方針シミュレーター",
}

_RESEARCH_PLAN_JA_TITLE_PHRASE_FALLBACKS = {
    "project context": "プロジェクト文脈",
}


def _research_plan_japanese_structured_text(value: str, *, key: str) -> str:
    text = value.strip()
    if not text:
        return value
    if key == "evidence":
        count_match = re.fullmatch(r"(\d+)\s+(evidence|blockers?)", text, flags=re.IGNORECASE)
        if count_match:
            noun = "blocker" if count_match.group(2).lower().startswith("blocker") else "evidence"
            return _research_plan_count_label(int(count_match.group(1)), noun, locale="ja-JP")
    if key != "title":
        return value
    version_match = re.search(r"\s+(v\d+)$", text, flags=re.IGNORECASE)
    version = f" {version_match.group(1)}" if version_match else ""
    base = text[: version_match.start()].strip() if version_match else text
    normalized = re.sub(r"[_\s]+", " ", base.replace("/", " ").strip()).lower()
    translated = _RESEARCH_PLAN_JA_TITLE_FALLBACKS.get(normalized)
    if translated:
        return f"{translated}{version}"
    display = text
    for source, target in sorted(_RESEARCH_PLAN_JA_TITLE_PHRASE_FALLBACKS.items(), key=lambda item: len(item[0]), reverse=True):
        display = re.sub(re.escape(source), target, display, flags=re.IGNORECASE)
    if display != text:
        return display
    return value
