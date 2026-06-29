from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Artifact, Evidence, Project, Report
from tabular_harness.services.approach import store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)

MAX_SCHEMA_HINT_BYTES = 25 * 1024 * 1024
ALLOWED_SCHEMA_HINT_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".json"}
SCHEMA_HINT_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


@dataclass(frozen=True)
class RelationalSchemaHintResult:
    artifact: Artifact
    report_artifact: Artifact
    report: Report
    evidence: Evidence
    summary: dict[str, Any]


def create_relational_schema_hint(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    filename: str,
    content_type: str | None,
    data: bytes,
    note: str | None = None,
) -> RelationalSchemaHintResult:
    source_filename = Path(filename or "relational_schema_hint.bin").name
    suffix = Path(source_filename).suffix.lower()
    if suffix not in ALLOWED_SCHEMA_HINT_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SCHEMA_HINT_SUFFIXES))
        raise ValueError(f"Only ER diagram PNG, JPEG, SVG, PDF, or JSON uploads are supported ({allowed}).")
    if not data:
        raise ValueError("Uploaded ER diagram file is empty.")
    if len(data) > MAX_SCHEMA_HINT_BYTES:
        raise ValueError("Uploaded ER diagram file is too large. Limit is 25 MB.")

    effective_content_type = SCHEMA_HINT_CONTENT_TYPES[suffix]
    parsed_hint = parse_schema_hint_json(data) if suffix == ".json" else {}
    summary = build_schema_hint_summary(
        project=project,
        filename=source_filename,
        content_type=effective_content_type,
        size_bytes=len(data),
        parsed_hint=parsed_hint,
        note=note,
    )
    name = f"relational_schema_hint_{new_id('rsh')}"
    version = next_artifact_version(db, project.id, "relational_schema_hint", name)
    artifact_dir, stored, content_hash = store.store_stream(
        org_id="local-org",
        project_id=project.id,
        asset_type="relational_schema_hint",
        name=name,
        version=version,
        filename=source_filename,
        stream=io.BytesIO(data),
        metadata={
            "project_id": project.id,
            "source_filename": source_filename,
            "content_type": effective_content_type,
            "media_kind": summary["media_kind"],
            "parsed_table_count": summary["parsed_table_count"],
            "parsed_relationship_count": summary["parsed_relationship_count"],
        },
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="relational_schema_hint",
        name=name,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "project_id": project.id,
            "source_filename": source_filename,
            "content_type": effective_content_type,
            "primary_path": str(stored.path),
            "media_kind": summary["media_kind"],
            "parsed_table_count": summary["parsed_table_count"],
            "parsed_relationship_count": summary["parsed_relationship_count"],
            "user_note": summary["user_note"],
        },
        version=version,
    )
    summary["artifact_id"] = artifact.id
    report_md = render_relational_schema_hint_report(summary)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="relational_schema_hint_report",
        name=f"relational_schema_hint_report_{new_id('rshr')}",
        filename="relational_schema_hint_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "relational_schema_hint_artifact_id": artifact.id,
            "content_type": effective_content_type,
            "parsed_table_count": summary["parsed_table_count"],
            "parsed_relationship_count": summary["parsed_relationship_count"],
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="relational_schema_hint",
        title="Relational Schema Hint",
        summary=str(summary["headline"]),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json([{"asset_type": "artifact", "asset_id": artifact.id}]),
        status="ready",
        created_by_type="user",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="relational_schema_hint",
        summary=str(summary["headline"]),
        strength="medium" if summary["parsed_relationship_count"] else "weak",
        source_artifact_id=artifact.id,
        metadata_json=dumps_json(
            {
                "report_artifact_id": report_artifact.id,
                "content_type": effective_content_type,
                "parsed_table_count": summary["parsed_table_count"],
                "parsed_relationship_count": summary["parsed_relationship_count"],
            }
        ),
    )
    db.add(evidence)
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="summarized_by",
    )
    return RelationalSchemaHintResult(
        artifact=artifact,
        report_artifact=report_artifact,
        report=report,
        evidence=evidence,
        summary=summary,
    )


def parse_schema_hint_json(data: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ER JSON upload must be valid UTF-8 JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("ER JSON upload must be a JSON object.")
    return cast(dict[str, Any], parsed)


def build_schema_hint_summary(
    *,
    project: Project,
    filename: str,
    content_type: str,
    size_bytes: int,
    parsed_hint: dict[str, Any],
    note: str | None,
) -> dict[str, Any]:
    tables = summarize_hint_tables(parsed_hint.get("tables"))
    relationships = summarize_hint_relationships(parsed_hint.get("relationships"))
    media_kind = "structured_json" if content_type == "application/json" else "diagram_file"
    headline = (
        f"Uploaded structured ER hint with {len(tables)} table(s) and {len(relationships)} relationship(s)."
        if media_kind == "structured_json"
        else "Uploaded ER diagram evidence for relational review."
    )
    return {
        "schema_version": "relational_schema_hint.v1",
        "project_id": project.id,
        "headline": headline,
        "source_filename": filename,
        "content_type": content_type,
        "media_kind": media_kind,
        "size_bytes": size_bytes,
        "parsed_table_count": len(tables),
        "parsed_relationship_count": len(relationships),
        "tables": tables[:20],
        "relationships": relationships[:40],
        "user_note": (note or "").strip() or None,
        "review_status": "needs_human_confirmation",
        "safety": {
            "inferred_relationships_are_not_join_contracts": True,
            "prediction_time_availability_unconfirmed": True,
            "runner_must_respect_split_manifest": True,
        },
        "next_actions": [
            "Compare the uploaded ER hint with the inferred RelationalCatalog map.",
            "Confirm join keys, cardinality, and prediction-time availability before generating relational features.",
            "Use Codex runner work only through a harness-owned AgentTaskContract.",
        ],
    }


def summarize_hint_tables(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tables: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            tables.append({"table_name": item, "source_index": index})
        elif isinstance(item, dict):
            name = item.get("table_name") or item.get("name") or item.get("id") or item.get("path")
            if name:
                tables.append(
                    {
                        "table_name": str(name),
                        "role": item.get("role"),
                        "columns": [str(column) for column in item.get("columns", [])[:12]]
                        if isinstance(item.get("columns"), list)
                        else [],
                        "source_index": index,
                    }
                )
    return tables


def summarize_hint_relationships(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    relationships: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        left_table = item.get("left_table") or item.get("from_table") or item.get("source_table")
        right_table = item.get("right_table") or item.get("to_table") or item.get("target_table")
        if not left_table or not right_table:
            continue
        relationships.append(
            {
                "left_table": str(left_table),
                "right_table": str(right_table),
                "left_column": item.get("left_column") or item.get("from_column") or item.get("source_column"),
                "right_column": item.get("right_column") or item.get("to_column") or item.get("target_column"),
                "relation_type": item.get("relation_type") or item.get("cardinality") or "unknown",
                "confidence": item.get("confidence"),
                "source_index": index,
            }
        )
    return relationships


def render_relational_schema_hint_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Relational Schema Hint",
        "",
        str(summary["headline"]),
        "",
        "## Source",
        "",
        f"- File: `{summary['source_filename']}`",
        f"- Content type: `{summary['content_type']}`",
        f"- Parsed tables: {summary['parsed_table_count']}",
        f"- Parsed relationships: {summary['parsed_relationship_count']}",
        f"- Review status: {summary['review_status']}",
    ]
    if summary.get("user_note"):
        lines.extend(["", "## User Note", "", str(summary["user_note"])])
    lines.extend(["", "## Tables"])
    tables = cast(list[dict[str, Any]], summary.get("tables") or [])
    if tables:
        for table in tables[:12]:
            columns = ", ".join(str(column) for column in table.get("columns", [])[:6]) or "-"
            lines.append(f"- {table['table_name']} (columns: {columns})")
    else:
        lines.append("- No structured tables were parsed from this upload.")
    lines.extend(["", "## Relationships"])
    relationships = cast(list[dict[str, Any]], summary.get("relationships") or [])
    if relationships:
        for relationship in relationships[:20]:
            left = relationship.get("left_table")
            right = relationship.get("right_table")
            left_col = relationship.get("left_column") or "?"
            right_col = relationship.get("right_column") or "?"
            relation_type = relationship.get("relation_type") or "unknown"
            lines.append(f"- {left}.{left_col} -> {right}.{right_col} ({relation_type})")
    else:
        lines.append("- No structured relationships were parsed from this upload.")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Treat uploaded ER diagrams as evidence, not executable join contracts.",
            "- Confirm join keys, cardinality, leakage risk, and prediction-time availability before feature generation.",
            "- Preserve EvaluationSpec and SplitManifest boundaries for any downstream relational feature work.",
            "",
            "## Next Actions",
        ]
    )
    lines.extend([f"- {item}" for item in cast(list[str], summary["next_actions"])])
    return "\n".join(lines).strip() + "\n"
