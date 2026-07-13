from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.core.runtime_paths import resolve_runtime_data_path
from tabular_harness.models.entities import (
    AgentSession,
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    Job,
    Project,
    utc_now,
)
from tabular_harness.services.agent_inbox import write_inbox_entry
from tabular_harness.services.agent_transcript import append_session_event
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.jobs import create_job


def create_agent_managed_prediction_operation(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    session: AgentSession,
    pipeline_artifact: Artifact,
    execution_payload: dict[str, Any],
    requested_by: str,
    locale: str | None,
) -> tuple[Job, Artifact]:
    job = create_job(
        db,
        job_type="run_prediction_pipeline",
        project_id=project.id,
        input_payload={**execution_payload, "agent_managed": True, "agent_session_id": session.id},
        context={"source": "leaderboard_prediction", "agent_session_id": session.id},
        policy={
            "execution": "agent_managed_local_worker",
            "external_network_access": "disabled",
            "connector_credentials_materialized": False,
            "secrets_materialized": False,
        },
        priority=90,
        max_attempts=20,
        created_by=requested_by,
    )
    job.status = "waiting_for_agent"
    context = prediction_context_pack(
        db,
        project=project,
        job=job,
        pipeline_artifact=pipeline_artifact,
        execution_payload=execution_payload,
    )
    workspace = resolve_runtime_data_path(session.workspace_path)
    operation_dir = workspace / ".tablex" / "prediction_operations" / job.id
    operation_dir.mkdir(parents=True, exist_ok=True)
    materialized_inputs = materialize_prediction_operation_inputs(
        db,
        operation_dir=operation_dir,
        execution_payload=execution_payload,
    )
    context["materialized_inputs"] = materialized_inputs
    context_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="prediction_context_pack",
        name=f"prediction_context_{job.id}",
        filename="prediction_context.json",
        payload=context,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "pipeline_artifact_id": pipeline_artifact.id,
            "agent_session_id": session.id,
        },
        created_by=requested_by,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pipeline_artifact.id,
        to_asset_type="artifact",
        to_asset_id=context_artifact.id,
        relation_type="provides_pipeline_for_prediction_context",
        metadata={"prediction_operation_job_id": job.id},
        org_id=project.org_id,
    )
    for input_context in context.get("input_artifacts") or []:
        artifact_id = input_context.get("artifact_id") if isinstance(input_context, dict) else None
        if isinstance(artifact_id, str):
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact_id,
                to_asset_type="artifact",
                to_asset_id=context_artifact.id,
                relation_type="provides_input_for_prediction_context",
                metadata={"prediction_operation_job_id": job.id},
                org_id=project.org_id,
            )
    for run_context in context.get("experiment_runs") or []:
        run_id = run_context.get("experiment_run_id") if isinstance(run_context, dict) else None
        if isinstance(run_id, str):
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="experiment_run",
                from_asset_id=run_id,
                to_asset_type="artifact",
                to_asset_id=context_artifact.id,
                relation_type="provides_evaluation_context_for_prediction",
                metadata={"prediction_operation_job_id": job.id},
                org_id=project.org_id,
            )
    context_path = operation_dir / "context.json"
    context_path.write_text(dumps_json({**context, "context_artifact_id": context_artifact.id}) + "\n", encoding="utf-8")
    message = prediction_operation_instruction(
        job_id=job.id,
        context_workspace_path=str(context_path.relative_to(workspace)),
        materialized_inputs=materialized_inputs,
        locale=locale,
    )
    event = append_session_event(
        db,
        session,
        source="user",
        event_type="prediction_operation_requested",
        role="user",
        title="Run prediction",
        content=message,
        payload={
            "schema_version": "prediction_operation_requested.v1",
            "prediction_operation_job_id": job.id,
            "prediction_context_artifact_id": context_artifact.id,
            "prediction_context_workspace_path": str(context_path.relative_to(workspace)),
            "pipeline_artifact_id": pipeline_artifact.id,
            "requested_by": requested_by,
        },
        artifact_id=context_artifact.id,
    )
    inbox_path = write_inbox_entry(
        workspace,
        kind="request",
        entry_type="prediction_operation_requested",
        payload={
            "schema_version": "prediction_operation_requested.v1",
            "prediction_operation_job_id": job.id,
            "prediction_context_artifact_id": context_artifact.id,
            "prediction_context_workspace_path": str(context_path.relative_to(workspace)),
            "pipeline_artifact_id": pipeline_artifact.id,
            "transcript_event_id": event.id,
        },
        content=message + "\n",
        title="Run prediction",
    )
    job.context_json = dumps_json(
        {
            "source": "leaderboard_prediction",
            "agent_session_id": session.id,
            "prediction_context_artifact_id": context_artifact.id,
            "prediction_context_workspace_path": str(context_path.relative_to(workspace)),
            "prediction_request_inbox_path": str(inbox_path.relative_to(workspace)),
        }
    )
    job.updated_at = utc_now()
    return job, context_artifact


def prediction_context_pack(
    db: Session,
    *,
    project: Project,
    job: Job,
    pipeline_artifact: Artifact,
    execution_payload: dict[str, Any],
) -> dict[str, Any]:
    pipeline_metadata = loads_json(pipeline_artifact.metadata_json, {})
    input_artifacts = prediction_input_artifact_context(db, project=project, execution_payload=execution_payload)
    run_context = prediction_run_context(
        db,
        project=project,
        run_ids=pipeline_metadata.get("experiment_run_ids"),
    )
    return {
        "schema_version": "prediction_context_pack.v1",
        "project_id": project.id,
        "prediction_operation_job_id": job.id,
        "prediction_purpose": execution_payload.get("batch_kind"),
        "pipeline": {
            "artifact_id": pipeline_artifact.id,
            "name": pipeline_artifact.name,
            "content_hash": pipeline_artifact.content_hash,
            "experiment_run_ids": pipeline_metadata.get("experiment_run_ids") or [],
            "research_plan_node_id": pipeline_metadata.get("research_plan_node_id"),
            "manifest": pipeline_metadata.get("pipeline_manifest"),
            "smoke_validation": pipeline_metadata.get("smoke_validation"),
            "metric_claim_consistency": pipeline_metadata.get("metric_claim_consistency"),
        },
        "input_artifacts": input_artifacts,
        "input_contract_observation": prediction_input_contract_observation(
            pipeline_metadata=pipeline_metadata,
            execution_payload=execution_payload,
        ),
        "experiment_runs": run_context,
        "execution_payload": execution_payload,
        "agent_responsibility": {
            "owner": "main_codex_session",
            "before_execution": (
                "Inspect the actual inputs, declared input contract, missing-table observation, coverage, and relevant project evidence; "
                "then decide what checks and repairs are material for this prediction. Do not silently represent an absent table as all-null data."
            ),
            "execution": "Start the canonical pipeline only through the structured execute_prediction request.",
            "after_execution": "Inspect the result in context, repair or rerun when needed, and complete the operation with a user-facing verdict.",
        },
        "structured_commands": {
            "execute_prediction": {
                "schema_version": "tablex_pipeline_request.v1",
                "operation": "execute_prediction",
                "request_id": "<unique request id>",
                "payload": {
                    "prediction_operation_job_id": job.id,
                    "decision_context": "<why execution is appropriate after inspecting this prediction context>",
                    "evidence_artifact_ids": [],
                    "execution_overrides": {},
                },
            },
            "complete_prediction_review": {
                "schema_version": "tablex_pipeline_request.v1",
                "operation": "complete_prediction_review",
                "request_id": "<unique request id>",
                "payload": {
                    "prediction_operation_job_id": job.id,
                    "verdict": "trustworthy | usable_with_caveats | rejected",
                    "summary": "<user-facing judgment grounded in the inspected evidence>",
                    "evidence_artifact_ids": [],
                    "actions": [],
                },
            },
        },
    }


def prediction_input_contract_observation(
    *,
    pipeline_metadata: dict[str, Any],
    execution_payload: dict[str, Any],
) -> dict[str, Any]:
    manifest = pipeline_metadata.get("pipeline_manifest")
    input_contract = manifest.get("input_contract") if isinstance(manifest, dict) else None
    required_tables = input_contract.get("required_tables") if isinstance(input_contract, dict) else None
    declared = [table for table in required_tables if isinstance(table, dict)] if isinstance(required_tables, list) else []
    mapping = execution_payload.get("input_artifact_ids_by_table")
    provided_names = [str(name) for name in mapping if isinstance(name, str)] if isinstance(mapping, dict) else []
    provided_normalized = {_normalize_prediction_table_name(name) for name in provided_names}
    missing_required: list[str] = []
    for table in declared:
        name = str(table.get("name") or "").strip()
        if not name or bool(table.get("optional")):
            continue
        if _normalize_prediction_table_name(name) not in provided_normalized:
            missing_required.append(name)
    return {
        "schema_version": "prediction_input_contract_observation.v1",
        "declared_tables": [
            {
                "name": str(table.get("name") or "").strip(),
                "role": table.get("role"),
                "optional": bool(table.get("optional")),
            }
            for table in declared
            if str(table.get("name") or "").strip()
        ],
        "provided_tables": provided_names,
        "missing_required_tables": missing_required,
        "has_partial_relational_input": bool(declared and missing_required),
        "interpretation_owner": "main_codex_session",
    }


def _normalize_prediction_table_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def prediction_run_context(db: Session, *, project: Project, run_ids: Any) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for run_id in run_ids if isinstance(run_ids, list) else []:
        run = db.get(ExperimentRun, run_id) if isinstance(run_id, str) else None
        if run is None or run.project_id != project.id:
            continue
        context.append(
            {
                "experiment_run_id": run.id,
                "status": run.status,
                "dataset_snapshot_id": run.dataset_snapshot_id,
                "evaluation_spec_id": run.evaluation_spec_id,
                "evaluation_candidate_id": run.evaluation_candidate_id,
                "split_manifest_id": run.split_manifest_id,
                "feature_set_id": run.feature_set_id,
                "model_version_id": run.model_version_id,
                "runner_type": run.runner_type,
                "params": prediction_safe_run_params(loads_json(run.params_json, {})),
                "metrics": loads_json(run.metrics_json, {}),
                "summary_md": run.summary_md,
            }
        )
    return context


def prediction_safe_run_params(params: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "model_id",
        "model_label",
        "model_family",
        "model_description",
        "features_used",
        "feature_summary",
        "research_plan_node_id",
        "pipeline_artifact_id",
        "model_artifact_id",
        "metrics_artifact_id",
        "oof_predictions_artifact_id",
        "validation_predictions_artifact_id",
        "feature_recipe_artifact_id",
        "model_diagnostics_artifact_ids",
        "notebook_artifact_id",
        "report_artifact_id",
    }
    return {key: params[key] for key in allowed_fields if key in params}


def prediction_input_artifact_context(
    db: Session,
    *,
    project: Project,
    execution_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    references: list[tuple[str, str]] = []
    mapping = execution_payload.get("input_artifact_ids_by_table")
    if isinstance(mapping, dict):
        references.extend(
            (str(name), str(artifact_id))
            for name, artifact_id in mapping.items()
            if isinstance(name, str) and isinstance(artifact_id, str)
        )
    input_artifact_id = execution_payload.get("input_artifact_id")
    if isinstance(input_artifact_id, str):
        references.append(("prediction_input", input_artifact_id))
    dataset_snapshot_id = execution_payload.get("dataset_snapshot_id")
    if isinstance(dataset_snapshot_id, str):
        snapshot = db.get(DatasetSnapshot, dataset_snapshot_id)
        if snapshot is not None and snapshot.project_id == project.id and snapshot.artifact_id:
            references.append(("dataset_snapshot", snapshot.artifact_id))
    output: list[dict[str, Any]] = []
    for table_name, artifact_id in references:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None or artifact.project_id != project.id:
            continue
        output.append(
            {
                "table_name": table_name,
                "artifact_id": artifact.id,
                "asset_type": artifact.asset_type,
                "name": artifact.name,
                "content_hash": artifact.content_hash,
                "size_bytes": artifact.size_bytes,
                "metadata": prediction_safe_input_metadata(loads_json(artifact.metadata_json, {})),
            }
        )
    return output


def prediction_safe_input_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "project_id",
        "table_name",
        "batch_kind",
        "dataset_snapshot_id",
        "source_ref",
        "row_count",
        "column_count",
        "schema_hash",
        "validation_report",
    }
    return {key: metadata[key] for key in allowed_fields if key in metadata}


def materialize_prediction_operation_inputs(
    db: Session,
    *,
    operation_dir: Path,
    execution_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    inputs_dir = operation_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    materialized: list[dict[str, Any]] = []
    mapping = execution_payload.get("input_artifact_ids_by_table")
    references = list(mapping.items()) if isinstance(mapping, dict) else []
    if isinstance(execution_payload.get("input_artifact_id"), str):
        references.append(("prediction_input", execution_payload["input_artifact_id"]))
    dataset_snapshot_id = execution_payload.get("dataset_snapshot_id")
    if isinstance(dataset_snapshot_id, str):
        snapshot = db.get(DatasetSnapshot, dataset_snapshot_id)
        if snapshot is not None and snapshot.artifact_id:
            references.append(("dataset_snapshot", snapshot.artifact_id))
    for table_name, artifact_id in references:
        artifact = db.get(Artifact, artifact_id) if isinstance(artifact_id, str) else None
        if artifact is None:
            continue
        source = artifact_primary_path(artifact).resolve()
        safe_name = "".join(character if character.isalnum() or character in "._-" else "_" for character in str(table_name))
        target = inputs_dir / f"{safe_name or 'input'}{source.suffix}"
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)
        materialized.append(
            {
                "table_name": table_name,
                "artifact_id": artifact.id,
                "workspace_path": str(target.relative_to(operation_dir.parent.parent.parent)),
            }
        )
    return materialized


def prediction_operation_instruction(
    *,
    job_id: str,
    context_workspace_path: str,
    materialized_inputs: list[dict[str, Any]],
    locale: str | None,
) -> str:
    inputs = ", ".join(str(item.get("workspace_path")) for item in materialized_inputs) or "see context pack"
    if str(locale or "").lower().startswith("ja"):
        return (
            f"ユーザーが予測操作 `{job_id}` を開始しました。`{context_workspace_path}` と実入力 ({inputs})、関連する実験・評価・モデル証拠を読み、"
            "この用途で必要な確認を自分で判断してください。準備ができたら `.tablex/requests/pipelines/` に `execute_prediction` を提出してcanonical pipelineを実行してください。"
            "結果通知後も同じ操作を管理し、必要なら調査・修復・再実行してから `complete_prediction_review` で最終判断とユーザー向け説明を返してください。"
        )
    return (
        f"The user started prediction operation `{job_id}`. Read `{context_workspace_path}`, the actual inputs ({inputs}), and relevant experiment, evaluation, and model evidence. "
        "Decide which checks matter for this use case. When ready, submit `execute_prediction` under `.tablex/requests/pipelines/` to run the canonical pipeline. "
        "After the result notification, keep managing the same operation; investigate, repair, or rerun when needed, then submit `complete_prediction_review` with the final judgment and user-facing explanation."
    )


def materialize_prediction_result_for_agent(
    *,
    session: AgentSession,
    job: Job,
    prediction_artifact: Artifact,
    result_context: dict[str, Any],
) -> tuple[str, str]:
    workspace = resolve_runtime_data_path(session.workspace_path)
    operation_dir = workspace / ".tablex" / "prediction_operations" / job.id
    result_dir = operation_dir / "result"
    result_dir.mkdir(parents=True, exist_ok=True)
    source = artifact_primary_path(prediction_artifact).resolve()
    prediction_path = result_dir / source.name
    if prediction_path.exists() or prediction_path.is_symlink():
        prediction_path.unlink()
    prediction_path.symlink_to(source)
    result_path = result_dir / "context.json"
    result_path.write_text(dumps_json(result_context) + "\n", encoding="utf-8")
    return str(result_path.relative_to(workspace)), str(prediction_path.relative_to(workspace))


def notify_prediction_result_to_agent(
    db: Session,
    *,
    session: AgentSession,
    job: Job,
    result_artifact: Artifact,
    prediction_artifact: Artifact,
    result_context: dict[str, Any],
) -> dict[str, Any]:
    result_context_path, prediction_path = materialize_prediction_result_for_agent(
        session=session,
        job=job,
        prediction_artifact=prediction_artifact,
        result_context={**result_context, "result_context_artifact_id": result_artifact.id},
    )
    workspace = resolve_runtime_data_path(session.workspace_path)
    message = (
        f"Prediction operation `{job.id}` finished canonical pipeline execution. Read `{result_context_path}` and inspect the actual output at `{prediction_path}` together with the project evidence. "
        "Decide what validation is material for this use case, including input/output shift against local validation or OOF evidence when relevant. "
        "Investigate, repair, or submit another `execute_prediction` request when needed. Only when you have a defensible user-facing judgment, submit `complete_prediction_review`."
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="prediction_result_available",
        role="harness",
        title="Prediction result available",
        content="A prediction result is ready for Codex review.",
        payload={
            "schema_version": "prediction_result_available.v1",
            "prediction_operation_job_id": job.id,
            "prediction_result_context_artifact_id": result_artifact.id,
            "prediction_result_context_workspace_path": result_context_path,
            "prediction_artifact_id": prediction_artifact.id,
            "prediction_workspace_path": prediction_path,
        },
        artifact_id=result_artifact.id,
        update_heartbeat=False,
    )
    inbox_path = write_inbox_entry(
        workspace,
        kind="observation",
        entry_type="prediction_result_available",
        payload={
            "schema_version": "prediction_result_available.v1",
            "prediction_operation_job_id": job.id,
            "prediction_result_context_artifact_id": result_artifact.id,
            "prediction_result_context_workspace_path": result_context_path,
            "prediction_artifact_id": prediction_artifact.id,
            "prediction_workspace_path": prediction_path,
            "transcript_event_id": event.id,
        },
        content=message + "\n",
        title="Prediction result available",
    )
    return {
        "delivered": True,
        "agent_session_id": session.id,
        "transcript_event_id": event.id,
        "inbox_path": str(inbox_path.relative_to(workspace)),
        "result_context_workspace_path": result_context_path,
        "prediction_workspace_path": prediction_path,
    }


def notify_prediction_failure_to_agent(
    db: Session,
    *,
    session: AgentSession,
    job: Job,
    result_artifact: Artifact,
    result_context: dict[str, Any],
) -> dict[str, Any]:
    workspace = resolve_runtime_data_path(session.workspace_path)
    result_dir = workspace / ".tablex" / "prediction_operations" / job.id / "result"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / "context.json"
    result_path.write_text(
        dumps_json({**result_context, "result_context_artifact_id": result_artifact.id}) + "\n",
        encoding="utf-8",
    )
    relative_result_path = str(result_path.relative_to(workspace))
    message = (
        f"Prediction operation `{job.id}` could not complete canonical execution. Read `{relative_result_path}` and inspect the operation context and actual inputs. "
        "The operation remains under your control. Explain the issue, investigate or repair the pipeline/input handling, and submit another `execute_prediction` when defensible. "
        "Use `complete_prediction_review` with verdict `rejected` only when the result should not be repaired or rerun."
    )
    event = append_session_event(
        db,
        session,
        source="tablex_sidecar",
        event_type="prediction_execution_needs_codex",
        role="harness",
        title="Prediction execution needs Codex",
        content="Prediction execution returned control to Codex for investigation or repair.",
        payload={
            "schema_version": "prediction_execution_needs_codex.v1",
            "prediction_operation_job_id": job.id,
            "prediction_result_context_artifact_id": result_artifact.id,
            "prediction_result_context_workspace_path": relative_result_path,
        },
        artifact_id=result_artifact.id,
        update_heartbeat=False,
    )
    inbox_path = write_inbox_entry(
        workspace,
        kind="observation",
        entry_type="prediction_execution_needs_codex",
        payload={
            "schema_version": "prediction_execution_needs_codex.v1",
            "prediction_operation_job_id": job.id,
            "prediction_result_context_artifact_id": result_artifact.id,
            "prediction_result_context_workspace_path": relative_result_path,
            "transcript_event_id": event.id,
        },
        content=message + "\n",
        title="Prediction execution needs Codex",
    )
    return {
        "delivered": True,
        "agent_session_id": session.id,
        "transcript_event_id": event.id,
        "inbox_path": str(inbox_path.relative_to(workspace)),
        "result_context_workspace_path": relative_result_path,
    }
