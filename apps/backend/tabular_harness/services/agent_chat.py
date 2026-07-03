from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import (
    AgentSession,
    AgentTranscriptEvent,
    Artifact,
    Asset,
    AssetReference,
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
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
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
    attach_chat_delivery_context(conversation_context, job)
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


def attach_chat_delivery_context(conversation_context: dict[str, Any], job: Job) -> None:
    payload = loads_json(job.input_json, {})
    delivered_session_id = payload.get("delivered_agent_session_id")
    if not isinstance(delivered_session_id, str) or not delivered_session_id.strip():
        return
    conversation_context["current_chat_delivery"] = {
        "schema_version": "agent_chat_delivery_context.v1",
        "delivered_to_running_codex": True,
        "agent_session_id": delivered_session_id,
        "agent_transcript_event_id": payload.get("agent_transcript_event_id")
        if isinstance(payload.get("agent_transcript_event_id"), str)
        else None,
        "agent_transcript_event_index": payload.get("agent_transcript_event_index")
        if isinstance(payload.get("agent_transcript_event_index"), int)
        else None,
        "progress_update_requested_event_id": payload.get("progress_update_requested_event_id")
        if isinstance(payload.get("progress_update_requested_event_id"), str)
        else None,
    }


def build_agent_conversation_context(db: Session, *, project: Project) -> dict[str, Any]:
    guidance = build_project_guidance(db, project)
    latest_dataset_snapshot = latest_dataset(db, project.id)
    latest_spec = latest_approved_spec_for_project(db, project.id)
    latest_split = latest_split_for_spec_id(db, latest_spec.id) if latest_spec else None
    skill_context_payload = skill_context(db, project.id)
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
    recent_conversation_turns = list_recent_agent_chat_turns(db, project.id)
    agent_session_context = build_agent_session_context(db, project.id)
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
        "skill_context": skill_context_payload,
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
        "recent_conversation_turns": recent_conversation_turns,
        "agent_session_context": agent_session_context,
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
            {
                "action": "equip_existing_skill",
                "endpoint": f"/api/projects/{project.id}/asset-references",
                "input_schema": {
                    "target_asset_id": "existing skill asset id",
                    "target_asset_version_id": "latest active asset version id",
                    "relation_type": "equipped_for_agent_context",
                },
            },
            {
                "action": "create_skill",
                "endpoint": "/api/assets",
                "input_schema": {
                    "asset_type": "skill",
                    "name": "concise skill name",
                    "description": "optional human-readable purpose",
                    "tags": ["short_tag"],
                    "semantic_tags": ["skill", "short_tag"],
                    "content": {
                        "schema_version": "tablex_skill.v1",
                        "instructions": ["concise non-obvious guidance for Codex"],
                        "guidance": "Use as Codex context, not deterministic harness routing.",
                    },
                },
            },
        ],
        "agent_boundary": {
            "natural_language_policy": "no keyword or phrase-specific natural-language routing inside the harness",
            "state_change_policy": "state changes require explicit UI/API action or a future schema-validated agent proposal",
            "evaluation_policy": "approved EvaluationSpecs and SplitManifests are not changed by chat text",
        },
    }


def list_recent_agent_chat_turns(db: Session, project_id: str, limit: int = 8) -> list[dict[str, Any]]:
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
            .order_by(Artifact.created_at.desc())
            .limit(limit)
        ).all()
    )
    turns: list[dict[str, Any]] = []
    for artifact in reversed(artifacts):
        try:
            payload = loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {})
        except OSError:
            continue
        if not isinstance(payload, dict) or payload.get("schema_version") != "agent_chat_turn.v1":
            continue
        turns.append(
            {
                "artifact_id": artifact.id,
                "created_at": artifact.created_at.isoformat(),
                "user_message": text_excerpt(str(payload.get("user_message") or ""), 1600),
                "assistant_message": text_excerpt(str(payload.get("assistant_message") or ""), 2400),
                "intent_type": payload["intent"].get("type") if isinstance(payload.get("intent"), dict) else None,
                "next_focus": payload.get("next_focus") if isinstance(payload.get("next_focus"), dict) else {},
            }
        )
    return turns


def build_agent_session_context(db: Session, project_id: str) -> dict[str, Any]:
    session = db.scalar(
        select(AgentSession)
        .where(AgentSession.project_id == project_id, AgentSession.session_type == "main_autonomous")
        .order_by(AgentSession.updated_at.desc(), AgentSession.created_at.desc())
        .limit(1)
    )
    latest_chat_artifact = db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == "agent_chat_turn")
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    if session is None:
        return {
            "schema_version": "agent_session_context.v1",
            "available": False,
            "latest_agent_chat_artifact_id": latest_chat_artifact.id if latest_chat_artifact else None,
        }
    events = list(
        db.scalars(
            select(AgentTranscriptEvent)
            .where(AgentTranscriptEvent.session_id == session.id)
            .order_by(AgentTranscriptEvent.event_index.desc())
            .limit(80)
        ).all()
    )
    ordered_events = list(reversed(events))
    live_pid = pid_is_alive(session.pid)
    latest_chat_created_at = latest_chat_artifact.created_at if latest_chat_artifact else None
    events_after_chat = [
        event for event in ordered_events if latest_chat_created_at is None or event.created_at > latest_chat_created_at
    ]
    codex_events_after_chat = [
        event for event in events_after_chat if event.source in {"codex_cli", "codex_cli_stderr"}
    ]
    agent_messages_after_chat = [
        event for event in codex_events_after_chat if transcript_item_type(event) == "agent_message"
    ]
    tool_events_after_chat = [
        event
        for event in codex_events_after_chat
        if "tool" in transcript_item_type(event) or "exec" in transcript_item_type(event)
    ]
    return {
        "schema_version": "agent_session_context.v1",
        "available": True,
        "session": {
            "id": session.id,
            "status": session.status,
            "autonomy_mode": session.autonomy_mode,
            "runner_kind": session.runner_kind,
            "turn_index": session.turn_index,
            "pid": session.pid,
            "pid_is_alive": live_pid,
            "observed_runner_state": observed_runner_state(session.status, live_pid),
            "codex_thread_id": session.codex_thread_id,
            "last_heartbeat_at": session.last_heartbeat_at.isoformat() if session.last_heartbeat_at else None,
            "last_error": session.last_error,
            "workspace_path": session.workspace_path,
            "updated_at": session.updated_at.isoformat(),
        },
        "chat_raw_drift": {
            "latest_agent_chat_artifact_id": latest_chat_artifact.id if latest_chat_artifact else None,
            "latest_agent_chat_created_at": latest_chat_created_at.isoformat()
            if latest_chat_created_at
            else None,
            "raw_events_after_latest_chat": len(events_after_chat),
            "codex_events_after_latest_chat": len(codex_events_after_chat),
            "codex_agent_messages_after_latest_chat": len(agent_messages_after_chat),
            "codex_tool_events_after_latest_chat": len(tool_events_after_chat),
        },
        "recent_raw_transcript_events": [transcript_event_context(event) for event in ordered_events[-40:]],
    }


def transcript_event_context(event: AgentTranscriptEvent) -> dict[str, Any]:
    payload = loads_json(event.payload_json, {})
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    return {
        "id": event.id,
        "event_index": event.event_index,
        "source": event.source,
        "event_type": event.event_type,
        "role": event.role,
        "title": event.title,
        "content_excerpt": text_excerpt(event.content, 1200),
        "codex_item_type": item.get("type") if isinstance(item.get("type"), str) else None,
        "artifact_id": event.artifact_id,
        "job_id": event.job_id,
        "created_at": event.created_at.isoformat(),
    }


def transcript_item_type(event: AgentTranscriptEvent) -> str:
    payload = loads_json(event.payload_json, {})
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    return str(item.get("type") or "")


def text_excerpt(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped[:limit] if stripped else None


def pid_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def observed_runner_state(status: str, live_pid: bool) -> str:
    if live_pid:
        return "codex_process_running"
    if status == "running":
        return "stale_running_state_without_process"
    if status in {"starting", "between_turns", "waiting_for_runner"}:
        return "supervisor_should_continue"
    return status


def skill_context(db: Session, project_id: str) -> dict[str, Any]:
    references = list(
        db.scalars(
            select(AssetReference).where(
                AssetReference.source_type == "project",
                AssetReference.source_id == project_id,
            )
        ).all()
    )
    referenced_ids = {reference.target_asset_id for reference in references}
    skill_assets = list(
        db.scalars(
            select(Asset)
            .where(Asset.asset_type == "skill", Asset.status == "active")
            .order_by(Asset.name)
            .limit(30)
        ).all()
    )
    reference_by_asset_id = {reference.target_asset_id: reference for reference in references}
    equipped = [
        skill_asset_context(asset, reference=reference_by_asset_id.get(asset.id))
        for asset in skill_assets
        if asset.id in referenced_ids
    ]
    available = [skill_asset_context(asset) for asset in skill_assets if asset.id not in referenced_ids][:12]
    return {
        "schema_version": "skill_context.v1",
        "purpose": "Skills are reusable Codex context/equipment, not fixed harness recipes.",
        "equipped": equipped,
        "available": available,
        "create_and_equip_policy": "Use explicit UI/API action or schema-validated agent proposal; do not keyword-route chat text.",
    }


def skill_asset_context(asset: Asset, *, reference: AssetReference | None = None) -> dict[str, Any]:
    return {
        "asset_id": asset.id,
        "latest_version_id": asset.latest_version_id,
        "name": asset.name,
        "description": asset.description,
        "tags": loads_json(asset.tags_json, []),
        "semantic_tags": loads_json(asset.semantic_tags_json, []),
        "relation_type": reference.relation_type if reference else None,
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
