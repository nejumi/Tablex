from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tabular_harness.agent.runners import safe_env
from tabular_harness.models.entities import Project


@dataclass(frozen=True)
class AgentResponseComposition:
    message: str
    brief: dict[str, Any]
    composer: dict[str, Any]


def compose_agent_chat_response(
    *,
    project: Project,
    user_message: str,
    intent: dict[str, Any],
    actions: list[dict[str, Any]],
    action_summary: dict[str, Any],
    locale: str | None,
    fallback_message: str,
    agent_model: str | None = None,
    utility_model: str | None = None,
) -> AgentResponseComposition:
    brief = build_human_response_brief(
        project=project,
        user_message=user_message,
        intent=intent,
        actions=actions,
        action_summary=action_summary,
        locale=locale,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    mode = os.environ.get("TABLEX_AGENT_RESPONSE_COMPOSER", "structured_fallback").strip().lower()
    if mode in {"codex_cli", "codex_cli_if_available"}:
        codex_response = compose_with_codex_cli(brief)
        if codex_response:
            return AgentResponseComposition(
                message=codex_response,
                brief=brief,
                composer={
                    "schema_version": "agent_response_composer.v1",
                    "mode": "codex_cli",
                    "status": "succeeded",
                },
            )
        if mode == "codex_cli":
            brief["composer_warning"] = "Codex CLI response composition was requested but unavailable or failed."

    return AgentResponseComposition(
        message=fallback_human_message(brief, fallback_message=fallback_message),
        brief=brief,
        composer={
            "schema_version": "agent_response_composer.v1",
            "mode": mode or "structured_fallback",
            "status": "fallback",
        },
    )


def build_human_response_brief(
    *,
    project: Project,
    user_message: str,
    intent: dict[str, Any],
    actions: list[dict[str, Any]],
    action_summary: dict[str, Any],
    locale: str | None,
    agent_model: str | None,
    utility_model: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "agent_human_response_brief.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "autonomy_mode": project.autonomy_mode,
            "current_phase": project.current_phase,
        },
        "response_locale": locale or "en-US",
        "model_preferences": {
            "agent_model": agent_model,
            "utility_model": utility_model,
            "routing": {
                "agent_model": "deep planning, notebook authoring, modeling strategy, autonomous reasoning",
                "utility_model": "translation, short summarization, UI wording, and conversation compression",
            },
        },
        "user_message": user_message,
        "detected_intent": intent,
        "interaction_role": {
            "agent": "Codex/Tablee as a data-science partner and interface, not a ticketing bot",
            "harness": "Owns state, artifacts, lineage, evaluation contracts, safety boundaries, and UI navigation",
        },
        "style": {
            "principles": [
                "Answer in the user's language.",
                "Explain what actually changed, what did not change, and why it matters.",
                "Prefer one clear next move over a list of raw events.",
                "Do not expose artifact IDs or schema names unless the user needs them.",
                "When an action only planned work, say that plainly and propose how to execute it.",
                "Keep uncertainty visible without making the user parse logs.",
            ],
            "avoid": [
                "sounding like an event log",
                "pretending a planned AgentTask is completed work",
                "hiding evaluation or SplitManifest boundaries",
                "fixed AutoML menu language",
            ],
        },
        "outcome": action_summary.get("outcome"),
        "headline": action_summary.get("headline"),
        "what_changed": action_summary.get("what_changed", []),
        "what_needs_review": action_summary.get("what_needs_review", []),
        "next_step": action_summary.get("next_step", {}),
        "boundaries": action_summary.get("boundaries", []),
        "actions": [
            {
                "type": action.get("type"),
                "status": action.get("status"),
                "label": action.get("label"),
                "detail": action.get("detail"),
                "target_tab": action.get("target_tab"),
                "target_anchor": action.get("target_anchor"),
                "job_id": action.get("job_id"),
                "artifact_id": action.get("artifact_id"),
                "artifact_ids": action.get("artifact_ids"),
                "queued_models": action.get("queued_models"),
                "results": action.get("results"),
                "failures": action.get("failures"),
            }
            for action in actions[:8]
        ],
    }


def compose_with_codex_cli(brief: dict[str, Any]) -> str | None:
    if shutil.which("codex") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="tablex-response-composer-") as tmp:
        workspace = Path(tmp)
        response_path = workspace / "response.txt"
        prompt = "\n".join(
            [
                "You are Tablex's human-facing data-science agent interface.",
                "Write one concise response to the user from the structured brief below.",
                "Use the requested response_locale. Do not sound like a log. Do not invent completed work.",
                "If the work only created a plan or contract, say so naturally and state the next useful move.",
                "",
                json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True),
            ]
        )
        cmd = [
            "codex",
            "exec",
            "--cd",
            str(workspace),
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(response_path),
            "--skip-git-repo-check",
            "-",
        ]
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=25,
                env=safe_env(workspace),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0 or not response_path.exists():
            return None
        message = response_path.read_text(encoding="utf-8").strip()
        return message[:4000] if message else None


def fallback_human_message(brief: dict[str, Any], *, fallback_message: str) -> str:
    locale = str(brief.get("response_locale") or "")
    if not locale.lower().startswith("ja"):
        return fallback_message

    changed = [str(item) for item in list_value(brief.get("what_changed")) if item][:3]
    needs_review = [str(item) for item in list_value(brief.get("what_needs_review")) if item][:2]
    next_step = dict_value(brief.get("next_step"))

    lines = ["状況を確認して、次の一手を整理しました。"]
    if changed:
        lines.append("実際に進めたこと: " + "、".join(changed) + "。")
    if needs_review:
        lines.append("確認が必要なこと: " + "、".join(needs_review) + "。")
    next_label = next_step.get("label")
    target_tab = next_step.get("target_tab")
    if next_label or target_tab:
        if target_tab:
            lines.append(f"次は {target_tab} で「{next_label or '現在の根拠'}」を見てください。")
        else:
            lines.append(f"次は「{next_label}」を見てください。")
    return "\n".join(lines)


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
