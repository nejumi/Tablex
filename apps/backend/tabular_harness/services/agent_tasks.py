from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.agent import ExecutionPolicy, LocalStubAgentRunner, WorkspaceRef
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import Artifact, Evidence, Idea, Job, Project, Report, utc_now
from tabular_harness.schemas import AgentResult, AgentTaskContract
from tabular_harness.services.agent_result_ingestion import (
    AgentResultExperimentIngestion,
    ingest_agent_result_experiment_outputs,
)
from tabular_harness.services.approach import (
    first_sentence,
    store_json_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)


@dataclass(frozen=True)
class AgentTaskExecutionResult:
    agent_result: AgentResult
    artifact_ids: list[str]
    report_id: str
    evidence_id: str
    workspace_artifact_id: str
    ingested_artifact_ids: list[str]
    experiment_ingestion: AgentResultExperimentIngestion


def run_idea_agent_task_stub(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    idea: Idea,
    job: Job,
) -> AgentTaskExecutionResult:
    contract_payload = loads_json(idea.agent_task_contract_json, {})
    contract = AgentTaskContract.model_validate(contract_payload)
    output_schema = load_agent_result_schema()
    workspace_path = store.root / "_workspaces" / project.id / idea.id / job.id
    workspace_manifest_artifact = materialize_agent_workspace(
        db,
        store=store,
        project=project,
        idea=idea,
        job=job,
        contract=contract,
        output_schema=output_schema,
        workspace_path=workspace_path,
    )
    result = LocalStubAgentRunner().run_task(
        WorkspaceRef(project_id=project.id, path=str(workspace_path)),
        contract,
        output_schema,
        ExecutionPolicy(sandbox="workspace_write", network="disabled", timeout_seconds=300),
    )
    report_md = result.outputs.get("report_md")
    if not isinstance(report_md, str):
        report_md = result.final_message
    visualization_spec = result.outputs.get("visualization_spec")
    if not isinstance(visualization_spec, dict):
        visualization_spec = {
            "schema_version": "visualization_spec.v1",
            "title": "Agent Task",
            "chart_type": "artifact_checklist",
            "data": [],
            "encoding": {},
            "empty_state": "No visualization produced.",
        }
    ingested_artifacts = ingest_agent_result_artifacts(
        db,
        store=store,
        project=project,
        idea=idea,
        job=job,
        workspace_path=workspace_path,
        result=result,
    )
    experiment_ingestion = ingest_agent_result_experiment_outputs(
        db,
        store=store,
        project=project,
        job=job,
        contract=contract,
        agent_result=result,
        ingested_artifacts=ingested_artifacts,
        source_asset_type="idea",
        source_asset_id=idea.id,
    )
    report_artifact = first_artifact_of_type(ingested_artifacts, "agent_task_report")
    if report_artifact is None:
        report_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_task_report",
            name=f"agent_task_report_fallback_{job.id}",
            filename="agent_task_report.json",
            payload={"report_md": report_md},
            metadata={"project_id": project.id, "idea_id": idea.id, "job_id": job.id, "task_id": result.task_id},
        )
        ingested_artifacts.append(report_artifact)
    result_artifact = first_artifact_of_type(ingested_artifacts, "agent_result")
    if result_artifact is None:
        result_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_result",
            name=f"agent_result_fallback_{job.id}",
            filename="agent_result.json",
            payload=result.model_dump(mode="json"),
            metadata={"project_id": project.id, "idea_id": idea.id, "job_id": job.id, "task_id": result.task_id},
        )
        ingested_artifacts.append(result_artifact)
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="agent_task_report",
        title=f"Agent Task Report: {idea.title}",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "idea", "asset_id": idea.id},
                {"asset_type": "job", "asset_id": job.id},
            ]
        ),
        status="draft",
        created_by_type="agent_runner",
    )
    db.add(report)
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="agent_result",
        summary=f"LocalStubAgentRunner produced AgentResult for idea `{idea.id}` with status `{result.status}`.",
        strength="medium",
        source_artifact_id=result_artifact.id,
        metadata_json=dumps_json({"idea_id": idea.id, "job_id": job.id, "task_id": result.task_id}),
    )
    db.add(evidence)
    idea.status = "agent_stub_completed"
    idea.updated_at = utc_now()
    db.flush()

    artifacts = [workspace_manifest_artifact, *ingested_artifacts]
    for artifact in artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="idea",
            from_asset_id=idea.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="agent_generates",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=workspace_manifest_artifact.id,
        to_asset_type="artifact",
        to_asset_id=result_artifact.id,
        relation_type="execution_context_for",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="idea",
        from_asset_id=idea.id,
        to_asset_type="report",
        to_asset_id=report.id,
        relation_type="summarizes_execution",
    )
    return AgentTaskExecutionResult(
        agent_result=result,
        artifact_ids=[artifact.id for artifact in artifacts],
        report_id=report.id,
        evidence_id=evidence.id,
        workspace_artifact_id=workspace_manifest_artifact.id,
        ingested_artifact_ids=[artifact.id for artifact in ingested_artifacts],
        experiment_ingestion=experiment_ingestion,
    )


def materialize_agent_workspace(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    idea: Idea,
    job: Job,
    contract: AgentTaskContract,
    output_schema: dict[str, Any],
    workspace_path: Path,
) -> Artifact:
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    harness_dir = workspace_path / ".harness"
    context_dir = harness_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "task_contract.json").write_text(contract.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    (harness_dir / "agent_result.schema.json").write_text(
        json.dumps(output_schema, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    policy = ExecutionPolicy(sandbox="workspace_write", network="disabled", timeout_seconds=300)
    (harness_dir / "execution_policy.json").write_text(policy.model_dump_json(indent=2), encoding="utf-8")
    sources = copy_context_artifacts(db, project_id=project.id, idea_id=idea.id, context_dir=context_dir)
    readme = render_workspace_readme(project=project, idea=idea, sources=sources)
    (workspace_path / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "schema_version": "agent_workspace_manifest.v1",
        "project_id": project.id,
        "idea_id": idea.id,
        "job_id": job.id,
        "workspace_path": str(workspace_path),
        "task_id": contract.task_id,
        "execution_policy": policy.model_dump(mode="json"),
        "materialized_sources": sources,
        "files": sorted(str(path.relative_to(workspace_path)) for path in workspace_path.rglob("*") if path.is_file()),
        "safety": {
            "secret_access": "forbidden",
            "connector_credentials": "not_materialized",
            "network": policy.network,
            "must_respect_split_manifest": True,
        },
    }
    return store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_workspace_manifest",
        name=f"agent_workspace_manifest_{job.id}",
        filename="agent_workspace_manifest.json",
        payload=manifest,
        metadata={"project_id": project.id, "idea_id": idea.id, "job_id": job.id, "task_id": contract.task_id},
    )


def copy_context_artifacts(
    db: Session,
    *,
    project_id: str,
    idea_id: str,
    context_dir: Path,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    context_pack_artifact: Artifact | None = None
    for asset_type, name in [
        ("agent_context_pack", "agent_context_pack.json"),
        ("research_plan", "research_plan.json"),
        ("experiment_plan", "experiment_plan.json"),
        ("baseline_strategy_plan", "baseline_strategy_plan.json"),
        ("data_quality_gate", "data_quality_gate.json"),
        ("relational_catalog", "relational_catalog.json"),
        ("evaluation_diagnostics", "evaluation_diagnostics.json"),
    ]:
        artifact = latest_context_artifact(db, project_id=project_id, idea_id=idea_id, asset_type=asset_type)
        if artifact is None:
            continue
        if asset_type == "agent_context_pack":
            context_pack_artifact = artifact
        target = context_dir / name
        shutil.copyfile(artifact_primary_path(artifact), target)
        refs.append(
            {
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "context_path": str(target.relative_to(context_dir.parent.parent)),
            }
        )
    refs.extend(
        copy_materialized_library_assets(
            db,
            context_dir=context_dir,
            context_pack_artifact=context_pack_artifact,
        )
    )
    return refs


def copy_materialized_library_assets(
    db: Session,
    *,
    context_dir: Path,
    context_pack_artifact: Artifact | None,
) -> list[dict[str, Any]]:
    if context_pack_artifact is None:
        return []
    try:
        payload = loads_json(artifact_primary_path(context_pack_artifact).read_text(encoding="utf-8"), {})
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw_assets = payload.get("materialized_library_assets")
    if not isinstance(raw_assets, list):
        return []
    refs: list[dict[str, Any]] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            continue
        artifact_id = raw.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            continue
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            continue
        context_path = raw.get("context_path")
        if not isinstance(context_path, str) or not context_path:
            continue
        relative = safe_context_subpath(context_path)
        target = context_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact_primary_path(artifact), target)
        refs.append(
            {
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "context_path": str(target.relative_to(context_dir.parent.parent)),
                "source": raw.get("source"),
                "sources": raw.get("sources", []),
                "asset_id": raw.get("asset_id"),
                "asset_version_id": raw.get("asset_version_id"),
                "asset_name": raw.get("name"),
                "reason": raw.get("reason"),
                "materialized_from_context_pack_artifact_id": context_pack_artifact.id,
            }
        )
    return refs


def safe_context_subpath(context_path: str) -> Path:
    requested = Path(context_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(f"Unsafe context materialization path: {context_path}")
    parts = requested.parts
    if parts[:2] == (".harness", "context"):
        parts = parts[2:]
    elif parts[:1] == ("context",):
        parts = parts[1:]
    if not parts:
        raise ValueError(f"Empty context materialization path: {context_path}")
    relative = Path(*parts)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe context materialization path: {context_path}")
    return relative


def ingest_agent_result_artifacts(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    idea: Idea,
    job: Job,
    workspace_path: Path,
    result: AgentResult,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for index, descriptor in enumerate(result.artifacts, start=1):
        relative = str(descriptor.get("path") or "")
        source_path = safe_workspace_file(workspace_path, relative)
        asset_type = str(descriptor.get("asset_type") or "agent_artifact")
        name = str(descriptor.get("name") or f"{asset_type}_{job.id}_{index}")
        metadata_value = descriptor.get("metadata")
        metadata: dict[str, Any] = cast(dict[str, Any], metadata_value) if isinstance(metadata_value, dict) else {}
        version = next_artifact_version(db, project.id, asset_type, name)
        artifact_dir, stored, content_hash = store.store_existing_file(
            org_id="local-org",
            project_id=project.id,
            asset_type=asset_type,
            name=name,
            version=version,
            source_path=source_path,
            filename=source_path.name,
            metadata={
                "project_id": project.id,
                "idea_id": idea.id,
                "job_id": job.id,
                "task_id": result.task_id,
                "workspace_relative_path": relative,
                **metadata,
            },
        )
        artifact = register_artifact(
            db,
            project_id=project.id,
            asset_type=asset_type,
            name=name,
            uri=str(artifact_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={
                "primary_path": str(stored.path),
                "project_id": project.id,
                "idea_id": idea.id,
                "job_id": job.id,
                "task_id": result.task_id,
                "workspace_relative_path": relative,
                "ingested_from_agent_result": True,
                **metadata,
            },
            version=version,
        )
        artifacts.append(artifact)
    return artifacts


def safe_workspace_file(workspace_path: Path, relative: str) -> Path:
    if not relative:
        raise ValueError("Agent artifact path is empty")
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(f"Unsafe agent artifact path: {relative}")
    source_path = (workspace_path / requested).resolve()
    workspace_resolved = workspace_path.resolve()
    if workspace_resolved not in source_path.parents and source_path != workspace_resolved:
        raise ValueError(f"Agent artifact path escapes workspace: {relative}")
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"Agent artifact file not found: {relative}")
    if source_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"Agent artifact file is too large: {relative}")
    return source_path


def latest_context_artifact(db: Session, *, project_id: str, idea_id: str, asset_type: str) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if asset_type in {"agent_context_pack", "experiment_plan"} and metadata.get("idea_id") != idea_id:
            continue
        return artifact
    return None


def first_artifact_of_type(artifacts: list[Artifact], asset_type: str) -> Artifact | None:
    return next((artifact for artifact in artifacts if artifact.asset_type == asset_type), None)


def render_workspace_readme(*, project: Project, idea: Idea, sources: list[dict[str, Any]]) -> str:
    lines = [
        "# Controlled Agent Workspace",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- Idea: {idea.title} ({idea.id})",
        "- Secrets: forbidden",
        "- Connector credentials: not materialized",
        "- Production writes: forbidden",
        "- SplitManifest: must be respected when present in context",
        "",
        "## Materialized Context",
    ]
    if sources:
        lines.extend([f"- {source['asset_type']}: {source['context_path']}" for source in sources])
    else:
        lines.append("- No prior context artifacts were materialized.")
    return "\n".join(lines).strip() + "\n"


def load_agent_result_schema() -> dict[str, Any]:
    candidates = [
        Path("schemas/agent_result.schema.json"),
        Path(__file__).resolve().parents[4] / "schemas" / "agent_result.schema.json",
    ]
    for path in candidates:
        if path.exists():
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    raise ValueError("schemas/agent_result.schema.json not found")
