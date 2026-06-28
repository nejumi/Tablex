from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from tabular_harness.agent import ExecutionPolicy, LocalStubAgentRunner, WorkspaceRef
from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json
from tabular_harness.models.entities import Artifact, Evidence, Job, Project, Report
from tabular_harness.schemas import AgentResult, AgentTaskContract
from tabular_harness.services.agent_task_readiness import (
    AgentTaskReadinessResult,
    latest_workspace_manifest_for_contract,
    load_workspace_manifest,
    review_agent_task_readiness,
)
from tabular_harness.services.agent_tasks import (
    first_artifact_of_type,
    load_agent_result_schema,
    safe_workspace_file,
)
from tabular_harness.services.approach import first_sentence, store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.planned_agent_workspace import (
    load_contract_payload,
    prepare_workspace_from_contract_artifact,
)


@dataclass(frozen=True)
class PlannedAgentTaskExecutionResult:
    agent_result: AgentResult
    artifact_ids: list[str]
    report_id: str
    evidence_id: str
    workspace_artifact_id: str
    readiness_artifact_id: str
    readiness_status: str
    ingested_artifact_ids: list[str]
    auto_prepared_workspace: bool


def run_planned_agent_task_local_stub(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    contract_artifact: Artifact,
    job: Job,
) -> PlannedAgentTaskExecutionResult:
    contract_payload = load_contract_payload(contract_artifact)
    contract = AgentTaskContract.model_validate(contract_payload)
    workspace_artifact = latest_workspace_manifest_for_contract(db, project.id, contract_artifact.id)
    workspace_manifest: dict[str, Any] | None
    auto_prepared = False
    if workspace_artifact is None:
        workspace_result = prepare_workspace_from_contract_artifact(
            db,
            store=store,
            project=project,
            contract_artifact=contract_artifact,
            job=job,
        )
        workspace_artifact = workspace_result.artifact
        workspace_manifest = workspace_result.manifest
        auto_prepared = True
    else:
        workspace_manifest = load_workspace_manifest(workspace_artifact)
    if workspace_manifest is None:
        raise ValueError("Prepared workspace manifest could not be loaded")

    readiness = review_agent_task_readiness(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        job=job,
    )
    if readiness.review["blocker_count"] > 0:
        raise ValueError(
            "AgentTask readiness has blockers: "
            + "; ".join(str(action) for action in readiness.review.get("next_actions", []))
        )

    output_schema = load_agent_result_schema()
    workspace_path = Path(str(workspace_manifest["workspace_path"]))
    policy = ExecutionPolicy(sandbox="workspace_write", network="disabled", timeout_seconds=300)
    result = LocalStubAgentRunner().run_task(
        WorkspaceRef(project_id=project.id, path=str(workspace_path)),
        contract,
        output_schema,
        policy,
    )
    ingested_artifacts = ingest_planned_agent_result_artifacts(
        db,
        store=store,
        project=project,
        contract_artifact=contract_artifact,
        workspace_artifact=workspace_artifact,
        job=job,
        workspace_path=workspace_path,
        result=result,
    )
    report_artifact = first_artifact_of_type(ingested_artifacts, "agent_task_report")
    if report_artifact is None:
        report_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_task_report",
            name=f"planned_agent_task_report_fallback_{job.id}",
            filename="agent_task_report.json",
            payload={"report_md": result.final_message},
            metadata={
                "project_id": project.id,
                "job_id": job.id,
                "task_id": result.task_id,
                "source_contract_artifact_id": contract_artifact.id,
            },
        )
        ingested_artifacts.append(report_artifact)
    result_artifact = first_artifact_of_type(ingested_artifacts, "agent_result")
    if result_artifact is None:
        result_artifact = store_json_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="agent_result",
            name=f"planned_agent_result_fallback_{job.id}",
            filename="agent_result.json",
            payload=result.model_dump(mode="json"),
            metadata={
                "project_id": project.id,
                "job_id": job.id,
                "task_id": result.task_id,
                "source_contract_artifact_id": contract_artifact.id,
            },
        )
        ingested_artifacts.append(result_artifact)

    report_md = result.outputs.get("report_md")
    if not isinstance(report_md, str):
        report_md = result.final_message
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="agent_task_report",
        title=f"Planned Agent Task Report: {contract.task_id}",
        summary=first_sentence(report_md),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "artifact", "asset_id": contract_artifact.id},
                {"asset_type": "artifact", "asset_id": workspace_artifact.id},
                {"asset_type": "artifact", "asset_id": readiness.review_artifact.id},
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
        summary=(
            f"LocalStubAgentRunner produced AgentResult for planned contract `{contract_artifact.id}` "
            f"with status `{result.status}`."
        ),
        strength="medium",
        source_artifact_id=result_artifact.id,
        metadata_json=dumps_json(
            {
                "job_id": job.id,
                "task_id": result.task_id,
                "source_contract_artifact_id": contract_artifact.id,
                "workspace_artifact_id": workspace_artifact.id,
                "readiness_artifact_id": readiness.review_artifact.id,
            }
        ),
    )
    db.add(evidence)
    db.flush()
    create_execution_lineage(
        db,
        project=project,
        job=job,
        contract_artifact=contract_artifact,
        workspace_artifact=workspace_artifact,
        readiness=readiness,
        ingested_artifacts=ingested_artifacts,
        report=report,
        evidence=evidence,
    )
    artifact_ids = list(
        dict.fromkeys(
            [
                workspace_artifact.id,
                *readiness.artifact_ids,
                *[artifact.id for artifact in ingested_artifacts],
            ]
        )
    )
    return PlannedAgentTaskExecutionResult(
        agent_result=result,
        artifact_ids=artifact_ids,
        report_id=report.id,
        evidence_id=evidence.id,
        workspace_artifact_id=workspace_artifact.id,
        readiness_artifact_id=readiness.review_artifact.id,
        readiness_status=str(readiness.review["status"]),
        ingested_artifact_ids=[artifact.id for artifact in ingested_artifacts],
        auto_prepared_workspace=auto_prepared,
    )


def ingest_planned_agent_result_artifacts(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    contract_artifact: Artifact,
    workspace_artifact: Artifact,
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
                "job_id": job.id,
                "task_id": result.task_id,
                "source_contract_artifact_id": contract_artifact.id,
                "workspace_artifact_id": workspace_artifact.id,
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
                "job_id": job.id,
                "task_id": result.task_id,
                "source_contract_artifact_id": contract_artifact.id,
                "workspace_artifact_id": workspace_artifact.id,
                "workspace_relative_path": relative,
                "ingested_from_agent_result": True,
                **metadata,
            },
            version=version,
        )
        artifacts.append(artifact)
    return artifacts


def create_execution_lineage(
    db: Session,
    *,
    project: Project,
    job: Job,
    contract_artifact: Artifact,
    workspace_artifact: Artifact,
    readiness: AgentTaskReadinessResult,
    ingested_artifacts: list[Artifact],
    report: Report,
    evidence: Evidence,
) -> None:
    for artifact in [
        workspace_artifact,
        readiness.review_artifact,
        readiness.report_artifact,
        readiness.visualization_artifact,
        *ingested_artifacts,
    ]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="job",
            from_asset_id=job.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    for artifact in ingested_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=contract_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="contract_for_execution",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=workspace_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="execution_context_for",
        )
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=readiness.review_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="gates_execution",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report.artifact_id,
        relation_type="materializes",
    )
    agent_result_artifact = first_artifact_of_type(ingested_artifacts, "agent_result")
    evidence_source_artifact_id = (
        agent_result_artifact.id if agent_result_artifact is not None else ingested_artifacts[0].id
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=evidence_source_artifact_id,
        to_asset_type="evidence",
        to_asset_id=evidence.id,
        relation_type="supports",
    )
