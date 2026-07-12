from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Asset,
    AssetReference,
    AssetVersion,
    Base,
    LineageEdge,
    Project,
    utc_now,
)
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.asset_library import equip_default_project_skills

ProjectCloneMode = Literal["data_only", "full"]

RUNTIME_TABLES = {
    "agent_sessions",
    "agent_supervisor_leases",
    "agent_transcript_events",
    "agent_transcript_sequences",
    "auth_sessions",
    "jobs",
    "projects",
    "users",
}
SPECIAL_TABLES = {"artifacts", "assets", "asset_versions", "asset_references"}
DEPENDENT_TABLES = {
    "answers": ("question_id", "questions"),
    "assumption_evidence_links": ("assumption_id", "assumptions"),
    "pilot_outcome_batches": ("deployment_id", "pilot_deployments"),
    "pilot_prediction_batches": ("deployment_id", "pilot_deployments"),
}
DATA_ONLY_ARTIFACT_TYPES = {
    "dataset_snapshot",
    "uploaded_supporting_table",
    "relational_schema_hint",
    "relational_schema_hint_report",
    "relational_catalog",
    "relational_table_bundle_manifest",
    "semantic_catalog",
}


def clone_project(
    db: Session,
    *,
    store: LocalArtifactStore,
    source: Project,
    name: str,
    mode: ProjectCloneMode,
    created_by: str,
) -> tuple[Project, dict[str, int]]:
    target = Project(
        id=new_id("p"),
        org_id=source.org_id,
        name=name.strip(),
        description=source.description,
        task_type=source.task_type if mode == "full" else None,
        target_column=source.target_column if mode == "full" else None,
        primary_dataset_snapshot_id=None,
        current_phase=("IDLE" if mode == "full" else "DATA_READY"),
        status="active",
        autonomy_mode="approval_based",
        created_by=created_by,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(target)
    db.flush()

    rows_by_table = project_rows_to_clone(db, source=source, mode=mode)
    asset_rows, version_rows, reference_rows = project_asset_rows_to_clone(
        db,
        source=source,
        artifact_rows=rows_by_table.get("artifacts", []),
        include_project_assets=mode == "full",
    )
    if asset_rows:
        rows_by_table["assets"] = asset_rows
    if version_rows:
        rows_by_table["asset_versions"] = version_rows
    if reference_rows:
        rows_by_table["asset_references"] = reference_rows

    id_map = build_clone_id_map(source.id, target.id, rows_by_table)
    cloned_storage_roots: set[Path] = set()
    try:
        clone_artifact_storage(
            rows_by_table.get("artifacts", []),
            store=store,
            source_project_id=source.id,
            target_project_id=target.id,
            cloned_roots=cloned_storage_roots,
        )
        insert_clone_rows(db, rows_by_table=rows_by_table, id_map=id_map, target_project_id=target.id)
        clone_project_asset_references(
            db,
            source_project_id=source.id,
            target_project_id=target.id,
            id_map=id_map,
            copied_reference_rows=rows_by_table.get("asset_references", []),
        )
        if mode == "data_only":
            equip_default_project_skills(db, store, project_id=target.id)
        if source.primary_dataset_snapshot_id:
            target.primary_dataset_snapshot_id = id_map.get(source.primary_dataset_snapshot_id)
        db.add(
            LineageEdge(
                id=new_id("lin"),
                org_id=source.org_id,
                project_id=target.id,
                from_asset_type="project",
                from_asset_id=source.id,
                to_asset_type="project",
                to_asset_id=target.id,
                relation_type="cloned_from_project",
                metadata_json=dumps_json({"mode": mode, "source_project_name": source.name}),
            )
        )
        db.flush()
    except Exception:
        for root in sorted(cloned_storage_roots, key=lambda item: len(item.parts), reverse=True):
            if root.is_dir():
                shutil.rmtree(root, ignore_errors=True)
            else:
                root.unlink(missing_ok=True)
        raise

    counts = {
        table_name: len(rows)
        for table_name, rows in rows_by_table.items()
        if rows and table_name not in {"assets", "asset_versions", "asset_references"}
    }
    counts["datasets"] = counts.pop("dataset_snapshots", 0)
    counts["artifacts"] = len(rows_by_table.get("artifacts", []))
    return target, counts


def project_rows_to_clone(db: Session, *, source: Project, mode: ProjectCloneMode) -> dict[str, list[dict[str, Any]]]:
    tables = {table.name: table for table in Base.metadata.sorted_tables}
    dataset_rows = row_mappings(
        db,
        select(tables["dataset_snapshots"]).where(tables["dataset_snapshots"].c.project_id == source.id),
    )
    dataset_artifact_ids = {str(row["artifact_id"]) for row in dataset_rows}
    if mode == "data_only":
        artifact_rows = row_mappings(
            db,
            select(tables["artifacts"]).where(
                tables["artifacts"].c.project_id == source.id,
                (tables["artifacts"].c.id.in_(dataset_artifact_ids))
                | (tables["artifacts"].c.asset_type.in_(DATA_ONLY_ARTIFACT_TYPES)),
            ),
        )
        artifact_ids = {str(row["id"]) for row in artifact_rows}
        semantic_rows = row_mappings(
            db,
            select(tables["semantic_catalogs"]).where(tables["semantic_catalogs"].c.project_id == source.id),
        )
        report_rows = row_mappings(
            db,
            select(tables["reports"]).where(
                tables["reports"].c.project_id == source.id,
                tables["reports"].c.report_type == "relational_schema_hint",
            ),
        )
        evidence_rows = row_mappings(
            db,
            select(tables["evidence"]).where(
                tables["evidence"].c.project_id == source.id,
                tables["evidence"].c.evidence_type == "relational_schema_hint",
            ),
        )
        data_entity_ids = artifact_ids | {str(row["id"]) for row in dataset_rows + semantic_rows + report_rows + evidence_rows}
        lineage_rows = [
            row
            for row in row_mappings(
                db,
                select(tables["lineage_edges"]).where(tables["lineage_edges"].c.project_id == source.id),
            )
            if str(row["from_asset_id"]) in data_entity_ids and str(row["to_asset_id"]) in data_entity_ids
        ]
        rows_by_table = {
            "artifacts": artifact_rows,
            "dataset_snapshots": dataset_rows,
            "semantic_catalogs": semantic_rows,
            "reports": report_rows,
            "evidence": evidence_rows,
            "lineage_edges": lineage_rows,
        }
        return {table_name: rows for table_name, rows in rows_by_table.items() if rows}

    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in RUNTIME_TABLES or table.name in SPECIAL_TABLES or "project_id" not in table.c:
            continue
        rows = row_mappings(db, select(table).where(table.c.project_id == source.id))
        if rows:
            rows_by_table[table.name] = rows
    rows_by_table["artifacts"] = row_mappings(
        db,
        select(tables["artifacts"]).where(tables["artifacts"].c.project_id == source.id),
    )
    add_dependent_rows(db, rows_by_table=rows_by_table)
    return rows_by_table


def add_dependent_rows(db: Session, *, rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
    tables = {table.name: table for table in Base.metadata.sorted_tables}
    for table_name, (foreign_key, parent_table_name) in DEPENDENT_TABLES.items():
        parent_ids = {str(row["id"]) for row in rows_by_table.get(parent_table_name, [])}
        if not parent_ids:
            continue
        rows = row_mappings(db, select(tables[table_name]).where(tables[table_name].c[foreign_key].in_(parent_ids)))
        if rows:
            rows_by_table[table_name] = rows


def project_asset_rows_to_clone(
    db: Session,
    *,
    source: Project,
    artifact_rows: list[dict[str, Any]],
    include_project_assets: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not include_project_assets:
        return [], [], []
    artifact_ids = {str(row["id"]) for row in artifact_rows}
    versions = list(
        db.scalars(
            select(AssetVersion).where(
                (AssetVersion.created_from_project_id == source.id) | (AssetVersion.artifact_id.in_(artifact_ids))
            )
        ).all()
    )
    asset_ids = {version.asset_id for version in versions}
    assets = list(db.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()) if asset_ids else []
    references = list(
        db.scalars(
            select(AssetReference).where(
                AssetReference.source_type == "project",
                AssetReference.source_id == source.id,
            )
        ).all()
    )
    return (
        [dict(row.__dict__) for row in assets],
        [dict(row.__dict__) for row in versions],
        [dict(row.__dict__) for row in references if row.target_asset_id in asset_ids],
    )


def clone_project_asset_references(
    db: Session,
    *,
    source_project_id: str,
    target_project_id: str,
    id_map: dict[str, str],
    copied_reference_rows: list[dict[str, Any]],
) -> None:
    copied_ids = {str(row["id"]) for row in copied_reference_rows}
    references = db.scalars(
        select(AssetReference).where(
            AssetReference.source_type == "project",
            AssetReference.source_id == source_project_id,
        )
    ).all()
    for reference in references:
        if reference.id in copied_ids:
            continue
        db.add(
            AssetReference(
                id=new_id("aref"),
                source_type="project",
                source_id=target_project_id,
                target_asset_id=id_map.get(reference.target_asset_id, reference.target_asset_id),
                target_asset_version_id=id_map.get(
                    reference.target_asset_version_id,
                    reference.target_asset_version_id,
                ),
                relation_type=reference.relation_type,
                locked=reference.locked,
                created_at=reference.created_at,
            )
        )


def build_clone_id_map(
    source_project_id: str,
    target_project_id: str,
    rows_by_table: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    id_map = {source_project_id: target_project_id}
    for rows in rows_by_table.values():
        for row in rows:
            value = row.get("id")
            if not isinstance(value, str) or value in id_map:
                continue
            prefix = value.split("_", 1)[0] if "_" in value else "clone"
            id_map[value] = new_id(prefix)
    return id_map


def insert_clone_rows(
    db: Session,
    *,
    rows_by_table: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    target_project_id: str,
) -> None:
    tables = {table.name: table for table in Base.metadata.sorted_tables}
    ordered_names = ["artifacts", "assets", "asset_versions"] + [
        table.name
        for table in Base.metadata.sorted_tables
        if table.name in rows_by_table and table.name not in SPECIAL_TABLES
    ]
    if "asset_references" in rows_by_table:
        ordered_names.append("asset_references")
    seen: set[str] = set()
    for table_name in ordered_names:
        if table_name in seen:
            continue
        seen.add(table_name)
        table = tables[table_name]
        source_rows = rows_by_table.get(table_name, [])
        if table_name == "research_plan_revisions":
            source_rows = parent_first_rows(source_rows, parent_key="parent_revision_id")
        for source_row in source_rows:
            row = {key: value for key, value in source_row.items() if key in table.c and key != "_sa_instance_state"}
            row = remap_row(row, id_map=id_map, target_project_id=target_project_id)
            db.execute(insert(table).values(**row))


def parent_first_rows(rows: list[dict[str, Any]], *, parent_key: str) -> list[dict[str, Any]]:
    """Return self-referencing rows with each available parent before its children."""
    remaining = list(rows)
    available_ids = {None, ""}
    ordered: list[dict[str, Any]] = []
    while remaining:
        ready = [row for row in remaining if row.get(parent_key) in available_ids]
        if not ready:
            # Preserve all rows for databases without FK enforcement while allowing
            # an integrity error to expose a malformed cycle when enforcement is on.
            ordered.extend(remaining)
            break
        for row in ready:
            ordered.append(row)
            available_ids.add(row.get("id"))
            remaining.remove(row)
    return ordered


def remap_row(row: dict[str, Any], *, id_map: dict[str, str], target_project_id: str) -> dict[str, Any]:
    remapped: dict[str, Any] = {}
    for key, value in row.items():
        if key == "project_id":
            remapped[key] = target_project_id
        elif key.endswith("_json") and isinstance(value, str):
            payload = loads_json(value, None)
            remapped[key] = dumps_json(remap_json_value(payload, id_map)) if payload is not None else remap_text(value, id_map)
        elif isinstance(value, str):
            remapped[key] = id_map.get(value, remap_text(value, id_map) if key in {"uri", "workspace_path"} else value)
        else:
            remapped[key] = value
    return remapped


def remap_json_value(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: remap_json_value(item, id_map) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_json_value(item, id_map) for item in value]
    if isinstance(value, str):
        return id_map.get(value, remap_text(value, id_map))
    return value


def remap_text(value: str, id_map: dict[str, str]) -> str:
    result = value
    for source_id, target_id in sorted(id_map.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(source_id, target_id)
    return result


def clone_artifact_storage(
    artifact_rows: list[dict[str, Any]],
    *,
    store: LocalArtifactStore,
    source_project_id: str,
    target_project_id: str,
    cloned_roots: set[Path],
) -> None:
    copied: set[Path] = set()
    store_root = store.root.resolve()
    for row in artifact_rows:
        uri = row.get("uri")
        if not isinstance(uri, str) or source_project_id not in uri:
            continue
        source_path = Path(uri).resolve()
        target_path = Path(uri.replace(source_project_id, target_project_id)).resolve()
        try:
            source_path.relative_to(store_root)
            target_path.relative_to(store_root)
        except ValueError as exc:
            raise ValueError(f"Project artifact is outside the configured artifact store: {uri}") from exc
        if source_path in copied or not source_path.exists():
            continue
        copied.add(source_path)
        cloned_roots.add(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, copy_function=hardlink_or_copy)
        else:
            hardlink_or_copy(source_path, target_path)


def hardlink_or_copy(source: str | Path, target: str | Path) -> str:
    source_path = Path(source)
    target_path = Path(target)
    try:
        os.link(source_path, target_path)
    except OSError:
        shutil.copy2(source_path, target_path)
    return str(target_path)


def row_mappings(db: Session, statement: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(statement).mappings().all()]
