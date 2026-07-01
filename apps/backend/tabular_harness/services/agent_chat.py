from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    ExperimentRun,
    Job,
    Project,
    SplitManifest,
)
from tabular_harness.services.agent_response_composer import compose_agent_chat_response
from tabular_harness.services.agent_task_planner import AgentTaskPlanResult
from tabular_harness.services.approach import store_json_artifact
from tabular_harness.services.artifacts import LocalArtifactStore, create_lineage_edge
from tabular_harness.services.project_guidance import build_project_guidance


@dataclass(frozen=True)
class AgentChatTurnResult:
    response: dict[str, Any]
    job: Job
    artifact: Artifact
    planned_agent_task: AgentTaskPlanResult | None = None


def handle_agent_chat_turn(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    job: Job,
    message: str,
    locale: str | None = None,
    agent_model: str | None = None,
    utility_model: str | None = None,
) -> AgentChatTurnResult:
    conversation_context = build_agent_conversation_context(db, project=project)
    intent = {
        "type": "agent_conversation",
        "confidence": None,
        "summary": "Natural-language chat is handled by agent reasoning, not by keyword intent routing.",
        "routing_policy": "no_keyword_or_phrase_specific_natural_language_rules",
    }
    actions: list[dict[str, Any]] = []
    planned_agent_task: AgentTaskPlanResult | None = None

    response_locale = response_locale_for_chat(locale)
    action_summary = build_conversation_action_summary(conversation_context)
    fallback_message = render_conversation_fallback_message(
        project=project,
        conversation_context=conversation_context,
        locale=response_locale,
    )
    composition = compose_agent_chat_response(
        project=project,
        user_message=message,
        intent=intent,
        actions=actions,
        action_summary=action_summary,
        locale=response_locale,
        fallback_message=fallback_message,
        conversation_context=conversation_context,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    token_series = estimate_token_series(message, actions)
    response = {
        "schema_version": "agent_chat_turn.v1",
        "project_id": project.id,
        "user_message": message,
        "assistant_message": composition.message,
        "intent": intent,
        "actions": actions,
        "action_summary": action_summary,
        "response_brief": composition.brief,
        "response_composer": composition.composer,
        "worker_events": [],
        "token_usage": {
            "source": "estimated_until_runner_telemetry",
            "is_estimate": True,
            "series": token_series,
        },
        "next_focus": conversation_next_focus(conversation_context),
    }
    artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="agent_chat_turn",
        name=f"agent_chat_turn_{job.id}",
        filename="agent_chat_turn.json",
        payload=response,
        metadata={
            "project_id": project.id,
            "job_id": job.id,
            "intent_type": intent["type"],
            "action_count": len(actions),
            "token_usage_source": "estimated_until_runner_telemetry",
            "response_locale": response_locale,
            "agent_model": agent_model,
            "utility_model": utility_model,
            "response_composer_mode": composition.composer.get("mode"),
        },
    )
    response["artifact_id"] = artifact.id
    for action in actions:
        target_id = action.get("artifact_id")
        if isinstance(target_id, str):
            create_lineage_edge(
                db,
                project_id=project.id,
                from_asset_type="artifact",
                from_asset_id=artifact.id,
                to_asset_type="artifact",
                to_asset_id=target_id,
                relation_type="records_chat_action",
            )
    return AgentChatTurnResult(
        response=response,
        job=job,
        artifact=artifact,
        planned_agent_task=planned_agent_task,
    )


def build_agent_conversation_context(db: Session, *, project: Project) -> dict[str, Any]:
    guidance = build_project_guidance(db, project)
    latest_dataset_snapshot = latest_dataset(db, project.id)
    latest_spec = latest_approved_spec_for_project(db, project.id)
    latest_split = latest_split_for_spec_id(db, latest_spec.id) if latest_spec else None
    recent_artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(Artifact.created_at.desc())
            .limit(8)
        ).all()
    )
    recent_jobs = list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project.id)
            .order_by(Job.created_at.desc())
            .limit(6)
        ).all()
    )
    counts = {
        "datasets": int(db.scalar(select(func.count()).select_from(DatasetSnapshot).where(DatasetSnapshot.project_id == project.id)) or 0),
        "evaluation_candidates": int(db.scalar(select(func.count()).select_from(EvaluationCandidate).where(EvaluationCandidate.project_id == project.id)) or 0),
        "evaluation_specs": int(db.scalar(select(func.count()).select_from(EvaluationSpec).where(EvaluationSpec.project_id == project.id)) or 0),
        "split_manifests": int(db.scalar(select(func.count()).select_from(SplitManifest).where(SplitManifest.project_id == project.id)) or 0),
        "experiment_runs": int(db.scalar(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.project_id == project.id)) or 0),
        "artifacts": int(db.scalar(select(func.count()).select_from(Artifact).where(Artifact.project_id == project.id)) or 0),
        "jobs": int(db.scalar(select(func.count()).select_from(Job).where(Job.project_id == project.id)) or 0),
    }
    return {
        "schema_version": "agent_conversation_context.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "autonomy_mode": project.autonomy_mode,
            "current_phase": project.current_phase,
            "status": project.status,
        },
        "counts": counts,
        "latest_dataset": dataset_context(latest_dataset_snapshot),
        "evaluation_contract": {
            "approved_evaluation_spec_id": latest_spec.id if latest_spec else None,
            "split_manifest_id": latest_split.id if latest_split else None,
            "ready_for_comparable_runs": bool(latest_spec and latest_split),
        },
        "recommended_focus": guidance.get("recommended_focus"),
        "autonomous_navigation": guidance.get("autonomous_navigation"),
        "recent_artifacts": [
            {
                "id": artifact.id,
                "asset_type": artifact.asset_type,
                "name": artifact.name,
                "created_at": artifact.created_at.isoformat(),
            }
            for artifact in recent_artifacts
        ],
        "recent_jobs": [
            {
                "id": recent_job.id,
                "job_type": recent_job.job_type,
                "status": recent_job.status,
                "created_at": recent_job.created_at.isoformat(),
                "updated_at": recent_job.updated_at.isoformat(),
            }
            for recent_job in recent_jobs
        ],
        "available_explicit_actions": [
            {
                "action": "set_leaderboard_metric",
                "endpoint": f"/api/projects/{project.id}/leaderboard/metric",
                "input_schema": {"metric": "built-in or validated metric identifier"},
            },
            {
                "action": "run_model_candidates",
                "endpoint": f"/api/projects/{project.id}/model-candidates/run",
                "input_schema": {"models": ["validated model candidate identifiers"]},
            },
            {
                "action": "start_autonomous_loop",
                "endpoint": f"/api/projects/{project.id}/autonomy/start",
                "input_schema": {"autonomy_mode": "approval_based|full_auto", "runner_mode": "harness_only|codex_cli|codex_cli_if_available"},
            },
        ],
        "agent_boundary": {
            "natural_language_policy": "no keyword or phrase-specific natural-language routing inside the harness",
            "state_change_policy": "state changes require explicit UI/API action or a future schema-validated agent proposal",
            "evaluation_policy": "approved EvaluationSpecs and SplitManifests are not changed by chat text",
        },
    }


def dataset_context(dataset: DatasetSnapshot | None) -> dict[str, Any] | None:
    if dataset is None:
        return None
    return {
        "id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "created_at": dataset.created_at.isoformat(),
    }


def build_conversation_action_summary(conversation_context: dict[str, Any]) -> dict[str, Any]:
    focus = conversation_next_focus(conversation_context)
    return {
        "schema_version": "agent_action_summary.v1",
        "outcome": "answered",
        "headline": "Agent response composed from project context",
        "what_changed": [],
        "what_needs_review": [],
        "next_step": {
            "label": focus.get("label"),
            "target_tab": focus.get("target_tab"),
            "target_anchor": focus.get("target_anchor"),
            "status": focus.get("status"),
        },
        "boundaries": [
            "Natural-language chat is answered by the response composer; harness state changes still require explicit UI/API actions or schema-validated agent proposals.",
            "No EvaluationSpec, SplitManifest, leaderboard metric, model training job, or artifact-producing workflow was changed by chat text alone.",
        ],
        "actions": [],
        "conversation_context": conversation_context,
    }


def render_conversation_fallback_message(
    *,
    project: Project,
    conversation_context: dict[str, Any],
    locale: str | None,
) -> str:
    focus = conversation_next_focus(conversation_context)
    counts = dict_value(conversation_context.get("counts"))
    target = str(project.target_column or "not selected")
    dataset_count = int(counts.get("datasets") or 0)
    run_count = int(counts.get("experiment_runs") or 0)
    next_label = str(focus.get("label") or "review the current project focus")
    target_tab = str(focus.get("target_tab") or "Home")
    if (locale or "").lower().startswith("ja"):
        return (
            f"現在の状態を見ました。データセットは {dataset_count} 件、実験 run は {run_count} 件、"
            f"ターゲットは {target} です。次に見るなら {target_tab} の「{next_label}」です。"
            "このチャットだけでは評価設計・SplitManifest・学習ジョブ・リーダーボード設定は変更していません。"
        )
    return (
        f"I checked the project state. There are {dataset_count} dataset snapshot(s), {run_count} experiment run(s), "
        f"and the target is {target}. The next useful surface is {target_tab}: {next_label}. "
        "This chat turn did not mutate evaluation, split, training, leaderboard, or artifact-producing workflows by text alone."
    )


def conversation_next_focus(conversation_context: dict[str, Any]) -> dict[str, Any]:
    focus = dict_value(conversation_context.get("recommended_focus"))
    primary_action = dict_value(focus.get("primary_action"))
    return {
        "target_tab": primary_action.get("target_tab") or focus.get("target_tab") or "Home",
        "target_anchor": primary_action.get("target_anchor") or focus.get("target_anchor"),
        "label": primary_action.get("label") or focus.get("title") or "Review project focus",
        "status": "suggested",
    }


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}




def latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_approved_spec_for_project(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec_id(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest).where(SplitManifest.evaluation_spec_id == spec_id).order_by(SplitManifest.created_at.desc())
    )





def response_locale_for_chat(locale: str | None) -> str:
    return locale or "en-US"


def estimate_token_series(message: str, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = max(12, len(message.split()) * 2)
    context = base + 180 + 30 * len(actions)
    plan = context + 120
    output = plan + 80 + 35 * len(actions)
    return [
        {"step": "read request", "tokens": base},
        {"step": "load context", "tokens": context},
        {"step": "compose response", "tokens": plan},
        {"step": "write response", "tokens": output},
    ]
