from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Artifact, Report
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)

TRANSLATABLE_SUFFIXES = {".csv", ".json", ".md", ".txt", ".yaml", ".yml", ".tsv", ".log"}


@dataclass(frozen=True)
class TranslationResult:
    translated_artifact: Artifact
    contract_artifact: Artifact
    translated_report: Report | None
    preview: dict[str, Any]
    provider_status: str
    translation_status: str


def translate_artifact(
    db: Session,
    *,
    store: LocalArtifactStore,
    artifact: Artifact,
    target_locale: str,
    source_locale: str = "en-US",
    source_report: Report | None = None,
    job_id: str | None = None,
) -> TranslationResult:
    path = artifact_primary_path(artifact)
    source_text = read_translatable_text(path)
    contract = build_codex_translation_contract(
        artifact=artifact,
        source_report=source_report,
        source_text=source_text,
        source_locale=source_locale,
        target_locale=target_locale,
    )
    contract_artifact = store_json_artifact(
        db,
        store,
        project_id=artifact.project_id,
        asset_type="agent_task_contract",
        name=f"codex_translation_contract_{job_id or artifact.id}_{normalize_locale(target_locale)}",
        filename="agent_task_contract.json",
        payload=contract,
        org_id=artifact.org_id,
        metadata={
            "schema_version": "codex_translation_contract.v1",
            "task_id": contract["task_id"],
            "task_type": contract["task_type"],
            "source_artifact_id": artifact.id,
            "source_report_id": source_report.id if source_report else None,
            "source_locale": normalize_locale(source_locale),
            "target_locale": normalize_locale(target_locale),
            "runner": "CodexCliRunner",
            "execution_status": "planned_not_executed",
            "job_id": job_id,
        },
    )
    translated_text, provider_status, translation_status = translate_text(
        source_text,
        source_locale=source_locale,
        target_locale=target_locale,
    )
    metadata = loads_json(artifact.metadata_json, {})
    translated_metadata = {
        "schema_version": "translated_preview.v1",
        "source_artifact_id": artifact.id,
        "source_report_id": source_report.id if source_report else None,
        "source_asset_type": artifact.asset_type,
        "source_locale": source_locale,
        "target_locale": normalize_locale(target_locale),
        "translation_provider": "codex_translation_runner",
        "provider_status": provider_status,
        "translation_status": translation_status,
        "codex_translation_contract_artifact_id": contract_artifact.id,
        "codex_execution_status": "planned_not_executed",
        "source_content_hash": artifact.content_hash,
        "source_artifact_name": artifact.name,
        "primary_path": None,
        "source_metadata": {
            "asset_type": artifact.asset_type,
            "content_type": path.suffix.lower().removeprefix(".") or "text",
            "truncated_for_translation": False,
            "original_metadata_keys": sorted(metadata.keys())[:40],
        },
    }
    asset_type = "translated_report" if source_report else "translated_artifact_preview"
    base_name = source_report.title if source_report else artifact.name
    name = f"{safe_artifact_name(base_name)}_{normalize_locale(target_locale)}"
    version = next_artifact_version(db, artifact.project_id, asset_type, name)
    filename = f"{name}.md"
    artifact_dir, stored, content_hash = store.store_text(
        org_id=artifact.org_id,
        project_id=artifact.project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        text=translated_text,
        metadata={**translated_metadata, "primary_path": None},
    )
    translated_metadata["primary_path"] = str(stored.path)
    translated_artifact = register_artifact(
        db,
        project_id=artifact.project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata=translated_metadata,
        org_id=artifact.org_id,
    )
    create_lineage_edge(
        db,
        project_id=artifact.project_id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="artifact",
        to_asset_id=contract_artifact.id,
        relation_type="planned_translation_task",
        metadata={
            "source_locale": source_locale,
            "target_locale": normalize_locale(target_locale),
            "runner": "CodexCliRunner",
        },
        org_id=artifact.org_id,
    )
    create_lineage_edge(
        db,
        project_id=artifact.project_id,
        from_asset_type="artifact",
        from_asset_id=contract_artifact.id,
        to_asset_type="artifact",
        to_asset_id=translated_artifact.id,
        relation_type="translated_to",
        metadata={
            "source_locale": source_locale,
            "target_locale": normalize_locale(target_locale),
            "provider_status": provider_status,
        },
        org_id=artifact.org_id,
    )
    translated_report = None
    if source_report is not None:
        translated_report = Report(
            id=new_id("rep"),
            project_id=source_report.project_id,
            report_type=f"{source_report.report_type}_translation",
            title=f"{source_report.title} ({normalize_locale(target_locale)})",
            summary=f"On-demand translation draft for {source_report.title}.",
            artifact_id=translated_artifact.id,
            source_asset_ids_json=dumps_json(
                [
                    {"asset_type": "report", "asset_id": source_report.id},
                    {"asset_type": "artifact", "asset_id": artifact.id},
                ]
            ),
            status="draft_translation",
            created_by_type="local_stub_translator",
        )
        db.add(translated_report)
        db.flush()
        create_lineage_edge(
            db,
            project_id=source_report.project_id,
            from_asset_type="report",
            from_asset_id=source_report.id,
            to_asset_type="report",
            to_asset_id=translated_report.id,
            relation_type="translated_to",
            metadata={
                "source_locale": source_locale,
                "target_locale": normalize_locale(target_locale),
                "translated_artifact_id": translated_artifact.id,
            },
            org_id=artifact.org_id,
        )
        create_lineage_edge(
            db,
            project_id=source_report.project_id,
            from_asset_type="report",
            from_asset_id=translated_report.id,
            to_asset_type="artifact",
            to_asset_id=translated_artifact.id,
            relation_type="materialized_as",
            metadata={"target_locale": normalize_locale(target_locale)},
            org_id=artifact.org_id,
        )
    preview = {
        "id": translated_artifact.id,
        "asset_type": translated_artifact.asset_type,
        "name": translated_artifact.name,
        "filename": stored.path.name,
        "content_type": "md",
        "preview_available": True,
        "preview": translated_text,
        "truncated": False,
        "size_bytes": translated_artifact.size_bytes,
        "reason": None,
    }
    return TranslationResult(
        translated_artifact=translated_artifact,
        contract_artifact=contract_artifact,
        translated_report=translated_report,
        preview=preview,
        provider_status=provider_status,
        translation_status=translation_status,
    )


def read_translatable_text(path: Path, limit_bytes: int = 80_000) -> str:
    suffix = path.suffix.lower()
    if suffix not in TRANSLATABLE_SUFFIXES:
        raise ValueError("Translation is only available for text, JSON, Markdown, and delimited text artifacts.")
    raw = path.open("rb").read(limit_bytes + 1)
    truncated = len(raw) > limit_bytes
    if truncated:
        raw = raw[:limit_bytes]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Artifact is not valid UTF-8 text.") from exc
    if suffix == ".json" and not truncated:
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    if truncated:
        text += "\n\n[Translation source was truncated for on-demand preview.]"
    return text


def translate_text(text: str, *, source_locale: str, target_locale: str) -> tuple[str, str, str]:
    normalized_target = normalize_locale(target_locale)
    normalized_source = normalize_locale(source_locale)
    if normalized_target.lower().startswith(normalized_source.lower().split("-")[0]):
        return text, "source_locale_matches_target", "source_returned"
    if normalized_target.lower().startswith("ja"):
        return translate_to_japanese_stub(text, source_locale=normalized_source), "codex_runner_not_executed_local_preview", "draft_translation"
    header = (
        f"> Translation draft for `{normalized_target}` is pending a configured translator runner. "
        "The English source is kept below so the workbench remains self-contained.\n\n"
    )
    return header + text, "codex_runner_not_executed", "pending_codex_translation"


def build_codex_translation_contract(
    *,
    artifact: Artifact,
    source_report: Report | None,
    source_text: str,
    source_locale: str,
    target_locale: str,
) -> dict[str, Any]:
    normalized_target = normalize_locale(target_locale)
    normalized_source = normalize_locale(source_locale)
    source_type = "report" if source_report else "artifact"
    source_id = source_report.id if source_report else artifact.id
    return {
        "task_id": new_id("translation_task"),
        "task_type": "translate_tier3_content",
        "project_id": artifact.project_id or "_cross_project",
        "objective": (
            f"Translate the {source_type} content from {normalized_source} to {normalized_target}. "
            "Preserve technical terms, dataset column names, IDs, metrics, code blocks, JSON keys, citations, "
            "and artifact references exactly unless a display-only translation is clearly appropriate. "
            "Return translated Markdown and a translation manifest."
        ),
        "inputs": {
            "schema_version": "codex_translation_task.v1",
            "source_type": source_type,
            "source_id": source_id,
            "source_artifact_id": artifact.id,
            "source_report_id": source_report.id if source_report else None,
            "source_artifact_type": artifact.asset_type,
            "source_artifact_name": artifact.name,
            "source_locale": normalized_source,
            "target_locale": normalized_target,
            "source_content": source_text,
            "source_policy": {
                "preserve_original_artifact": True,
                "write_translated_content_as_new_artifact": True,
                "do_not_translate_dataset_values_or_column_names_without_context": True,
                "do_not_access_secrets": True,
                "external_network": "disabled",
            },
        },
        "required_outputs": [
            {
                "path": "reports/translated_content.md",
                "schema": "markdown",
                "description": "Translated user-facing report or artifact preview content.",
            },
            {
                "path": "artifacts/translation_manifest.json",
                "schema": "translation_manifest.v1",
                "description": "Source artifact id, target locale, preserved terms, unresolved phrases, and quality notes.",
            },
        ],
        "quality_checks": [
            "Preserve source artifact id, report id, metric names, IDs, citations, JSON keys, and code blocks.",
            "Do not claim new analytical findings that are absent from the source content.",
            "Mark uncertain translations in the manifest instead of silently guessing.",
            "Return content suitable for registration as a translated Report/Artifact asset with lineage.",
        ],
        "forbidden_actions": [
            "Do not read secrets or connector credentials.",
            "Do not mutate the original artifact or report.",
            "Do not call external network resources unless a future harness policy explicitly allows it.",
            "Do not translate dataset column names, file names, IDs, or metric keys when that would break traceability.",
        ],
        "context_files": [],
        "output_schema_path": None,
        "assumption_context": {
            "translation_quality": "requires_human_review_for_external_publication",
            "source_of_truth": "original_english_artifact",
        },
        "autonomy_level": 2,
    }


def store_json_artifact(
    db: Session,
    store: LocalArtifactStore,
    *,
    project_id: str | None,
    asset_type: str,
    name: str,
    filename: str,
    payload: Any,
    metadata: dict[str, Any],
    org_id: str = "local-org",
) -> Artifact:
    version = next_artifact_version(db, project_id, asset_type, name)
    artifact_dir, stored, content_hash = store.store_json(
        org_id=org_id,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        filename=filename,
        payload=payload,
        metadata={**metadata, "primary_path": None},
    )
    return register_artifact(
        db,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={**metadata, "primary_path": str(stored.path)},
        org_id=org_id,
    )


def translate_to_japanese_stub(text: str, *, source_locale: str) -> str:
    replacements = [
        ("# Data Understanding", "# データ理解"),
        ("# Project Report", "# プロジェクトレポート"),
        ("# Decision Report", "# 意思決定レポート"),
        ("# Run Report", "# 実行レポート"),
        ("# Evaluation Diagnostics", "# 評価診断"),
        ("## Summary", "## 要約"),
        ("## Next Actions", "## 次のアクション"),
        ("## Risks", "## リスク"),
        ("## Evidence", "## エビデンス"),
        ("## Metrics", "## 指標"),
        ("## Assumptions", "## 仮定"),
        ("## Evaluation", "## 評価"),
        ("## Recommendations", "## 推奨"),
        ("Next Actions", "次のアクション"),
        ("High Risk Assumptions", "高リスクの仮定"),
        ("Recent Activity", "最近のアクティビティ"),
        ("Recent Artifacts", "最近のアーティファクト"),
        ("Dataset", "データセット"),
        ("Evaluation", "評価"),
        ("Assumption", "仮定"),
        ("Assumptions", "仮定"),
        ("Artifact", "アーティファクト"),
        ("Artifacts", "アーティファクト"),
        ("Lineage", "リネージ"),
        ("Report", "レポート"),
        ("Reports", "レポート"),
        ("Job", "ジョブ"),
        ("Jobs", "ジョブ"),
        ("Status", "状態"),
        ("Created", "作成日時"),
        ("Actions", "操作"),
        ("Ready", "準備完了"),
        ("Warning", "警告"),
        ("Blocked", "ブロック"),
        ("succeeded", "成功"),
        ("failed", "失敗"),
        ("warning", "警告"),
    ]
    translated = text
    for source, target in replacements:
        translated = translated.replace(source, target)
    header = (
        f"> ja-JP translation draft generated by the local stub translator from `{source_locale}`. "
        "This is an on-demand preview asset; use a configured Codex/LLM translator runner for production-quality localization.\n\n"
    )
    return header + translated


def normalize_locale(locale: str) -> str:
    cleaned = locale.strip().replace("_", "-")
    if not cleaned:
        return "en-US"
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(part.lower() if index == 0 else part.upper() for index, part in enumerate(parts))


def safe_artifact_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value.strip())
    return cleaned.strip("_")[:120] or "translated_preview"
