from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from tabular_harness.agent import ExecutionPolicy
from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Artifact, Asset, AssetVersion, Job, Project
from tabular_harness.schemas import AgentTaskContract
from tabular_harness.services.agent_task_planner import validate_agent_task_contract
from tabular_harness.services.agent_tasks import load_agent_result_schema
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)

MAX_CONTEXT_SOURCE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class PlannedAgentWorkspaceResult:
    manifest: dict[str, Any]
    artifact: Artifact
    materialized_context_count: int
    materialized_relational_context_count: int
    materialized_library_asset_count: int
    skipped_source_count: int


def prepare_workspace_from_contract_artifact(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    contract_artifact: Artifact,
    job: Job,
) -> PlannedAgentWorkspaceResult:
    contract_payload = load_contract_payload(contract_artifact)
    validate_agent_task_contract(contract_payload)
    contract = AgentTaskContract.model_validate(contract_payload)
    if contract.project_id != project.id:
        raise ValueError("AgentTaskContract project_id does not match the requested project")

    workspace_path = store.root / "_workspaces" / project.id / "planned" / contract.task_id / job.id
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    harness_dir = workspace_path / ".harness"
    context_dir = harness_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    (harness_dir / "task_contract.json").write_text(
        contract.model_dump_json(by_alias=True, indent=2),
        encoding="utf-8",
    )
    output_schema = load_agent_result_schema()
    (harness_dir / "agent_result.schema.json").write_text(
        json.dumps(output_schema, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    policy = ExecutionPolicy(sandbox="workspace_write", network="disabled", timeout_seconds=300)
    (harness_dir / "execution_policy.json").write_text(policy.model_dump_json(indent=2), encoding="utf-8")

    materialized_sources, skipped_sources = materialize_contract_sources(
        db,
        contract=contract,
        contract_artifact=contract_artifact,
        context_dir=context_dir,
    )
    readme = render_planned_workspace_readme(
        project=project,
        contract=contract,
        contract_artifact=contract_artifact,
        sources=materialized_sources,
        skipped_sources=skipped_sources,
    )
    (workspace_path / "README.md").write_text(readme, encoding="utf-8")

    manifest = {
        "schema_version": "agent_workspace_manifest.v1",
        "project_id": project.id,
        "idea_id": f"planned_contract:{contract_artifact.id}",
        "job_id": job.id,
        "workspace_path": str(workspace_path),
        "task_id": contract.task_id,
        "source_contract_artifact_id": contract_artifact.id,
        "execution_policy": policy.model_dump(mode="json"),
        "materialized_sources": materialized_sources,
        "skipped_sources": skipped_sources,
        "files": sorted(str(path.relative_to(workspace_path)) for path in workspace_path.rglob("*") if path.is_file()),
        "safety": {
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "network": policy.network,
            "must_respect_split_manifest": bool(contract.inputs.get("must_respect_split_manifest", True)),
            "production_write": "forbidden",
        },
        "runner_handoff": {
            "status": "workspace_prepared",
            "runner_type": "planned_contract",
            "execution_not_started": True,
        },
    }
    Draft202012Validator(load_agent_workspace_manifest_schema()).validate(manifest)
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_workspace_manifest",
        name=f"planned_agent_workspace_manifest_{job.id}",
        filename="agent_workspace_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "task_id": contract.task_id,
            "source_contract_artifact_id": contract_artifact.id,
            "materialized_context_count": count_context_sources(materialized_sources),
            "materialized_relational_context_count": count_sources(
                materialized_sources, "relational_context_artifact"
            ),
            "materialized_library_asset_count": count_sources(materialized_sources, "library_asset"),
            "skipped_source_count": len(skipped_sources),
        },
    )
    create_workspace_lineage(
        db,
        project=project,
        job=job,
        contract_artifact=contract_artifact,
        manifest_artifact=artifact,
        materialized_sources=materialized_sources,
    )
    return PlannedAgentWorkspaceResult(
        manifest=manifest,
        artifact=artifact,
        materialized_context_count=count_context_sources(materialized_sources),
        materialized_relational_context_count=count_sources(materialized_sources, "relational_context_artifact"),
        materialized_library_asset_count=count_sources(materialized_sources, "library_asset"),
        skipped_source_count=len(skipped_sources),
    )


def load_contract_payload(contract_artifact: Artifact) -> dict[str, Any]:
    if contract_artifact.asset_type != "agent_task_contract":
        raise ValueError("Artifact is not an agent_task_contract")
    payload = loads_json(artifact_primary_path(contract_artifact).read_text(encoding="utf-8"), {})
    if not isinstance(payload, dict):
        raise ValueError("AgentTaskContract artifact did not contain a JSON object")
    return cast(dict[str, Any], payload)


def materialize_contract_sources(
    db: Session,
    *,
    contract: AgentTaskContract,
    contract_artifact: Artifact,
    context_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = [
        {
            "source_kind": "agent_task_contract",
            "artifact_id": contract_artifact.id,
            "asset_type": contract_artifact.asset_type,
            "context_path": ".harness/task_contract.json",
        }
    ]
    skipped: list[dict[str, Any]] = []
    inputs = contract.inputs
    available_context = inputs.get("available_context_artifacts")
    if isinstance(available_context, list):
        for item in available_context:
            if not isinstance(item, dict):
                continue
            artifact_id = item.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id:
                continue
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:
                skipped.append({"artifact_id": artifact_id, "reason": "artifact_not_found"})
                continue
            role = str(item.get("role") or artifact.asset_type)
            is_relational = is_relational_context_artifact(role, artifact.asset_type)
            copied = copy_artifact_to_context(
                artifact,
                context_dir=context_dir,
                relative_dir=Path("relational") if is_relational else Path("artifacts"),
                filename_prefix=safe_filename_part(role),
            )
            if copied is None:
                skipped.append({"artifact_id": artifact.id, "reason": "too_large_or_missing"})
                continue
            sources.append(
                {
                    "source_kind": "relational_context_artifact" if is_relational else "context_artifact",
                    "role": role,
                    "artifact_id": artifact.id,
                    "asset_type": artifact.asset_type,
                    "name": artifact.name,
                    "context_path": copied,
                    "content_hash": artifact.content_hash,
                    "size_bytes": artifact.size_bytes,
                }
            )

    library_recommendations = inputs.get("library_recommendations")
    if isinstance(library_recommendations, list):
        for item in library_recommendations:
            if not isinstance(item, dict):
                continue
            version_id = item.get("asset_version_id") or item.get("latest_version_id")
            if not isinstance(version_id, str) or not version_id:
                continue
            version = db.get(AssetVersion, version_id)
            if version is None:
                skipped.append({"asset_version_id": version_id, "reason": "asset_version_not_found"})
                continue
            asset = db.get(Asset, version.asset_id)
            artifact = db.get(Artifact, version.artifact_id)
            if artifact is None:
                skipped.append({"asset_version_id": version_id, "reason": "asset_version_artifact_not_found"})
                continue
            copied = copy_artifact_to_context(
                artifact,
                context_dir=context_dir,
                relative_dir=Path("library_assets"),
                filename_prefix=library_asset_filename_prefix(asset=asset, version=version, raw=item),
            )
            if copied is None:
                skipped.append({"asset_version_id": version_id, "reason": "too_large_or_missing"})
                continue
            sources.append(
                {
                    "source_kind": "library_asset",
                    "asset_id": asset.id if asset else version.asset_id,
                    "asset_type": asset.asset_type if asset else item.get("asset_type"),
                    "asset_name": asset.name if asset else item.get("name"),
                    "asset_version_id": version.id,
                    "version": version.version,
                    "artifact_id": artifact.id,
                    "reason": item.get("reason"),
                    "context_path": copied,
                }
            )
    return sources, skipped


def is_relational_context_artifact(role: str, asset_type: str) -> bool:
    return role.startswith("relational_") or asset_type.startswith("relational_")


def copy_artifact_to_context(
    artifact: Artifact,
    *,
    context_dir: Path,
    relative_dir: Path,
    filename_prefix: str,
) -> str | None:
    source_path = artifact_primary_path(artifact)
    if not source_path.exists() or not source_path.is_file():
        return None
    if source_path.stat().st_size > MAX_CONTEXT_SOURCE_BYTES:
        return None
    suffix = source_path.suffix if source_path.suffix else ".json"
    if suffix.lower() not in {".json", ".md", ".txt", ".yaml", ".yml", ".csv", ".tsv"}:
        suffix = ".json"
    target = context_dir / relative_dir / f"{filename_prefix}__{safe_filename_part(artifact.id)}{suffix}"
    ensure_safe_context_target(context_dir, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)
    return str(target.relative_to(context_dir.parent.parent))


def ensure_safe_context_target(context_dir: Path, target: Path) -> None:
    resolved_context = context_dir.resolve()
    resolved_target = target.resolve()
    if resolved_context not in resolved_target.parents:
        raise ValueError(f"Unsafe context target: {target}")


def library_asset_filename_prefix(
    *,
    asset: Asset | None,
    version: AssetVersion,
    raw: dict[str, Any],
) -> str:
    return "__".join(
        [
            safe_filename_part(asset.asset_type if asset else str(raw.get("asset_type") or "asset")),
            safe_filename_part(asset.name if asset else str(raw.get("name") or "library_asset")),
            safe_filename_part(version.id),
        ]
    )[:180]


def safe_filename_part(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    cleaned = "".join(char if char in allowed else "_" for char in value).strip("._")
    return cleaned[:80] or "source"


def render_planned_workspace_readme(
    *,
    project: Project,
    contract: AgentTaskContract,
    contract_artifact: Artifact,
    sources: list[dict[str, Any]],
    skipped_sources: list[dict[str, Any]],
) -> str:
    lines = [
        "# Controlled Agent Workspace",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Task: {contract.task_id}",
        f"- Contract artifact: {contract_artifact.id}",
        "- Source: planned AgentTaskContract",
        "- Secrets: forbidden",
        "- Connector credentials: not materialized",
        "- Production writes: forbidden",
        "- SplitManifest: must be respected when present in context",
        "",
        "## Materialized Context",
    ]
    if sources:
        lines.extend(
            [
                f"- {source['source_kind']}: {source.get('asset_type', source.get('asset_name', 'source'))} -> {source['context_path']}"
                for source in sources
            ]
        )
    else:
        lines.append("- No context artifacts were materialized.")
    if skipped_sources:
        lines.extend(["", "## Skipped Sources"])
        lines.extend([f"- {item}" for item in skipped_sources])
    return "\n".join(lines).strip() + "\n"


def create_workspace_lineage(
    db: Session,
    *,
    project: Project,
    job: Job,
    contract_artifact: Artifact,
    manifest_artifact: Artifact,
    materialized_sources: list[dict[str, Any]],
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="job",
        from_asset_id=job.id,
        to_asset_type="artifact",
        to_asset_id=manifest_artifact.id,
        relation_type="produces",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=contract_artifact.id,
        to_asset_type="artifact",
        to_asset_id=manifest_artifact.id,
        relation_type="materialized_as_workspace",
    )
    for source in materialized_sources:
        artifact_id = source.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id and artifact_id != contract_artifact.id:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact_id,
                to_asset_type="artifact",
                to_asset_id=manifest_artifact.id,
                relation_type="materialized_into_workspace",
            )
        version_id = source.get("asset_version_id")
        if isinstance(version_id, str) and version_id:
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="asset_version",
                from_asset_id=version_id,
                to_asset_type="artifact",
                to_asset_id=manifest_artifact.id,
                relation_type="materialized_into_workspace",
            )


def count_sources(sources: list[dict[str, Any]], source_kind: str) -> int:
    return sum(1 for source in sources if source.get("source_kind") == source_kind)


def count_context_sources(sources: list[dict[str, Any]]) -> int:
    return sum(
        1
        for source in sources
        if source.get("source_kind") in {"context_artifact", "relational_context_artifact"}
    )


def load_agent_workspace_manifest_schema() -> dict[str, Any]:
    candidates = [
        Path("schemas/agent_workspace_manifest.schema.json"),
        Path(__file__).resolve().parents[4] / "schemas" / "agent_workspace_manifest.schema.json",
    ]
    for path in candidates:
        if path.exists():
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    raise ValueError("schemas/agent_workspace_manifest.schema.json not found")
