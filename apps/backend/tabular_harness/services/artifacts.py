from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Artifact, LineageEdge, Project


@dataclass(frozen=True)
class StoredFile:
    path: Path
    sha256: str
    size_bytes: int


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def artifact_dir(
        self, org_id: str, project_id: str | None, asset_type: str, name: str, version: int
    ) -> Path:
        project_part = project_id or "_cross_project"
        return self.root / org_id / project_part / asset_type / name / f"v{version}"

    def store_stream(
        self,
        *,
        org_id: str,
        project_id: str | None,
        asset_type: str,
        name: str,
        version: int,
        filename: str,
        stream: BinaryIO,
        metadata: dict[str, Any],
    ) -> tuple[Path, StoredFile, str]:
        target_dir = self.artifact_dir(org_id, project_id, asset_type, name, version)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_filename(filename)
        digest = hashlib.sha256()
        size = 0
        with target_path.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
                output.write(chunk)
        stored = StoredFile(path=target_path, sha256=digest.hexdigest(), size_bytes=size)
        content_hash = self.write_manifest(target_dir, [stored], metadata)
        return target_dir, stored, content_hash

    def store_json(
        self,
        *,
        org_id: str,
        project_id: str | None,
        asset_type: str,
        name: str,
        version: int,
        filename: str,
        payload: Any,
        metadata: dict[str, Any],
    ) -> tuple[Path, StoredFile, str]:
        target_dir = self.artifact_dir(org_id, project_id, asset_type, name, version)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_filename(filename)
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        target_path.write_bytes(data)
        stored = StoredFile(
            path=target_path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        content_hash = self.write_manifest(target_dir, [stored], metadata)
        return target_dir, stored, content_hash

    def store_text(
        self,
        *,
        org_id: str,
        project_id: str | None,
        asset_type: str,
        name: str,
        version: int,
        filename: str,
        text: str,
        metadata: dict[str, Any],
    ) -> tuple[Path, StoredFile, str]:
        target_dir = self.artifact_dir(org_id, project_id, asset_type, name, version)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_filename(filename)
        data = text.encode("utf-8")
        target_path.write_bytes(data)
        stored = StoredFile(
            path=target_path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        content_hash = self.write_manifest(target_dir, [stored], metadata)
        return target_dir, stored, content_hash

    def store_existing_file(
        self,
        *,
        org_id: str,
        project_id: str | None,
        asset_type: str,
        name: str,
        version: int,
        source_path: Path,
        filename: str,
        metadata: dict[str, Any],
    ) -> tuple[Path, StoredFile, str]:
        target_dir = self.artifact_dir(org_id, project_id, asset_type, name, version)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_filename(filename)
        shutil.copyfile(source_path, target_path)
        data = target_path.read_bytes()
        stored = StoredFile(
            path=target_path,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        content_hash = self.write_manifest(target_dir, [stored], metadata)
        return target_dir, stored, content_hash

    def write_manifest(self, target_dir: Path, files: list[StoredFile], metadata: dict[str, Any]) -> str:
        manifest = {
            "files": [
                {
                    "path": file.path.name,
                    "sha256": file.sha256,
                    "size_bytes": file.size_bytes,
                }
                for file in files
            ],
            "metadata": metadata,
        }
        hash_input = dumps_json(manifest).encode("utf-8")
        content_hash = hashlib.sha256(hash_input).hexdigest()
        manifest["content_hash"] = content_hash
        (target_dir / "artifact_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return content_hash


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    return name or "artifact.bin"


def next_artifact_version(
    db: Session, project_id: str | None, asset_type: str, name: str
) -> int:
    stmt = select(func.max(Artifact.version)).where(
        Artifact.project_id == project_id,
        Artifact.asset_type == asset_type,
        Artifact.name == name,
    )
    current = db.scalar(stmt)
    return int(current or 0) + 1


def register_artifact(
    db: Session,
    *,
    project_id: str | None,
    asset_type: str,
    name: str,
    uri: str,
    content_hash: str,
    size_bytes: int | None,
    metadata: dict[str, Any],
    version: int | None = None,
    org_id: str = "local-org",
    created_by: str | None = None,
) -> Artifact:
    artifact = Artifact(
        id=new_id("art"),
        org_id=org_id,
        project_id=project_id,
        asset_type=asset_type,
        name=name,
        version=version or next_artifact_version(db, project_id, asset_type, name),
        uri=uri,
        content_hash=content_hash,
        size_bytes=size_bytes,
        metadata_json=dumps_json(metadata),
        created_by=created_by or project_owner_id(db, project_id),
    )
    db.add(artifact)
    db.flush()
    return artifact


def project_owner_id(db: Session, project_id: str | None) -> str:
    if not project_id:
        return "local-user"
    project = db.get(Project, project_id)
    return project.created_by if project is not None and project.created_by else "local-user"


def create_lineage_edge(
    db: Session,
    *,
    project_id: str | None,
    from_asset_type: str,
    from_asset_id: str,
    to_asset_type: str,
    to_asset_id: str,
    relation_type: str,
    metadata: dict[str, Any] | None = None,
    org_id: str = "local-org",
) -> LineageEdge:
    edge = LineageEdge(
        id=new_id("lin"),
        org_id=org_id,
        project_id=project_id,
        from_asset_type=from_asset_type,
        from_asset_id=from_asset_id,
        to_asset_type=to_asset_type,
        to_asset_id=to_asset_id,
        relation_type=relation_type,
        metadata_json=dumps_json(metadata or {}),
    )
    db.add(edge)
    db.flush()
    return edge


def artifact_primary_path(artifact: Artifact) -> Path:
    metadata = loads_json(artifact.metadata_json, {})
    primary_path = metadata.get("primary_path")
    if primary_path:
        return Path(primary_path)
    manifest_path = Path(artifact.uri) / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_file = cast(str, manifest["files"][0]["path"])
    return Path(artifact.uri) / first_file


def artifact_to_dict(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "uri": artifact.uri,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
        "metadata": loads_json(artifact.metadata_json, {}),
        "created_at": artifact.created_at.isoformat(),
    }
