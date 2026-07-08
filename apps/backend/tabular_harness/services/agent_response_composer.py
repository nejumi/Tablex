from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tabular_harness.agent.runners import CODEX_HARNESS_CONFIG_ARGS, safe_env
from tabular_harness.models.entities import Project
from tabular_harness.services.codex_transcript import build_codex_cli_transcript
from tabular_harness.services.locales import locale_is_japanese


@dataclass(frozen=True)
class AgentResponseComposition:
    message: str
    brief: dict[str, Any]
    composer: dict[str, Any]
    handoff_to_main_session: bool = False
    handoff_reason: str | None = None


@dataclass(frozen=True)
class CodexCompositionResult:
    message: str | None
    status: str
    failure_reason: str | None = None
    prompt_preamble: list[str] | None = None
    command: str | None = None
    timeout_seconds: int | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None
    events: list[dict[str, Any]] | None = None
    event_count: int | None = None
    jsonl_tail: str | None = None


def compose_agent_chat_response(
    *,
    project: Project,
    user_message: str,
    intent: dict[str, Any],
    actions: list[dict[str, Any]],
    action_summary: dict[str, Any],
    locale: str | None,
    fallback_message: str,
    conversation_context: dict[str, Any] | None = None,
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
        conversation_context=conversation_context,
        agent_model=agent_model,
        utility_model=utility_model,
    )
    mode = os.environ.get("TABLEX_AGENT_RESPONSE_COMPOSER", "codex_cli_if_available").strip().lower()
    if mode in {"codex_cli", "codex_cli_if_available"}:
        codex_response = compose_with_codex_cli(brief)
        if codex_response.message:
            parsed_decision = parse_composer_decision(codex_response.message)
            handoff_reason = parsed_decision.get("handoff_reason")
            handoff_reason = handoff_reason if isinstance(handoff_reason, str) and handoff_reason.strip() else None
            handoff_requested = parsed_decision.get("handoff_to_main_session") is True
            response_message = parsed_decision.get("message")
            if not isinstance(response_message, str) or not response_message.strip():
                response_message = codex_response.message if not handoff_requested else response_composer_handoff_message(brief, handoff_reason)
            return AgentResponseComposition(
                message=response_message,
                brief=brief,
                composer=codex_composer_metadata(
                    mode="codex_cli",
                    status="handoff_requested" if handoff_requested else "succeeded",
                    brief=brief,
                    result=codex_response,
                    handoff_to_main_session=handoff_requested,
                    handoff_reason=handoff_reason,
                ),
                handoff_to_main_session=handoff_requested,
                handoff_reason=handoff_reason,
            )
        brief["composer_warning"] = codex_response.failure_reason or "Codex CLI response composition was unavailable."
        return AgentResponseComposition(
            message=codex_unavailable_message(brief)
            if mode == "codex_cli"
            else response_composer_fallback_message(fallback_message, brief),
            brief=brief,
            composer=codex_composer_metadata(
                mode=mode,
                status=codex_response.status if mode == "codex_cli" else "fallback",
                brief=brief,
                result=codex_response,
            ),
        )

    return AgentResponseComposition(
        message=codex_unavailable_message(brief) if mode in {"codex_cli", "codex_cli_if_available"} else fallback_message,
        brief=brief,
        composer={
            "schema_version": "agent_response_composer.v1",
            "mode": mode or "structured_fallback",
            "status": "codex_unavailable" if mode in {"codex_cli", "codex_cli_if_available"} else "fallback",
            "model": response_composer_model(brief),
            "handoff_to_main_session": False,
            "handoff_reason": None,
            "failure_reason": brief.get("composer_warning"),
        },
    )


def codex_composer_metadata(
    *,
    mode: str,
    status: str,
    brief: dict[str, Any],
    result: CodexCompositionResult,
    handoff_to_main_session: bool = False,
    handoff_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "agent_response_composer.v1",
        "mode": mode,
        "status": status,
        "handoff_to_main_session": handoff_to_main_session,
        "handoff_reason": handoff_reason,
        "failure_reason": result.failure_reason,
        "raw_surface": "codex_exec",
        "model": response_composer_model(brief),
        "command": result.command,
        "prompt_preamble": result.prompt_preamble,
        "timeout_seconds": result.timeout_seconds,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "stdout_tail": result.stdout_tail,
        "stderr_tail": result.stderr_tail,
        "events": result.events,
        "event_count": result.event_count,
        "jsonl_tail": result.jsonl_tail,
    }


def parse_composer_decision(raw_message: str) -> dict[str, Any]:
    text = raw_message.strip()
    if not text:
        return {"handoff_to_main_session": False, "message": raw_message, "handoff_reason": None}
    candidates = [text]
    if text.startswith("```"):
        stripped = text.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
        candidates.insert(0, stripped)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        return {
            "handoff_to_main_session": payload.get("handoff_to_main_session") is True,
            "message": payload.get("message") if isinstance(payload.get("message"), str) else None,
            "handoff_reason": payload.get("handoff_reason") if isinstance(payload.get("handoff_reason"), str) else None,
        }
    return {"handoff_to_main_session": False, "message": raw_message, "handoff_reason": None}


def build_human_response_brief(
    *,
    project: Project,
    user_message: str,
    intent: dict[str, Any],
    actions: list[dict[str, Any]],
    action_summary: dict[str, Any],
    locale: str | None,
    conversation_context: dict[str, Any] | None,
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
        "response_shortcut": response_shortcut_for_message(user_message),
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
        "conversation_context": conversation_context or {},
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


def compose_with_codex_cli(brief: dict[str, Any]) -> CodexCompositionResult:
    if shutil.which("codex") is None:
        return CodexCompositionResult(message=None, status="codex_not_found", failure_reason="Codex CLI binary was not found on PATH.")
    with tempfile.TemporaryDirectory(prefix="tablex-response-composer-") as tmp:
        workspace = Path(tmp)
        response_path = workspace / "response.txt"
        timeout_seconds = codex_response_timeout_seconds()
        model = response_composer_model(brief)
        prompt_preamble = [
            "You are Tablex's human-facing data-science agent interface.",
            "Write one concise response to the user from the structured brief below.",
            "Use the requested response_locale. Do not sound like a log. Do not invent completed work.",
            "Use agent_session_context and recent_raw_transcript_events when explaining what Codex is doing now.",
            "Use current_chat_delivery when present: the user's message has already been delivered to the running analysis, and this response should explain that state without blocking it.",
            "Use recent_conversation_turns so the reply can follow the user's ongoing conversation.",
            "If response_shortcut is btw_status_explanation, explain current progress without changing the main session.",
            "If the work only created a plan or contract, say so naturally and state the next useful move.",
            "Return exactly one JSON object with fields: handoff_to_main_session, message, handoff_reason.",
            "Set handoff_to_main_session=false and write message only when saved project state is enough.",
            "Set handoff_to_main_session=true when answering requires inspecting artifact contents, code, data, or changing project state; then set message=null and handoff_reason to one concise sentence.",
            "",
        ]
        prompt = "\n".join(prompt_preamble + [json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True)])
        config_summary = " ".join(CODEX_HARNESS_CONFIG_ARGS)
        command_summary = f"codex exec {config_summary} --json --sandbox read-only --output-last-message response.txt -"
        cmd = [
            "codex",
            "exec",
            *CODEX_HARNESS_CONFIG_ARGS,
            "--cd",
            str(workspace),
            "--sandbox",
            "read-only",
            "--json",
            "--output-last-message",
            str(response_path),
            "--skip-git-repo-check",
            "-",
        ]
        if model is not None:
            cmd[2:2] = ["--model", model]
            command_summary = (
                f"codex exec --model {model} {config_summary} --json --sandbox read-only "
                "--output-last-message response.txt -"
            )
        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                env=safe_env(workspace),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            transcript = build_codex_cli_transcript(
                status="timeout",
                command=command_summary,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=exc.stderr if isinstance(exc.stderr, str) else "",
            )
            return CodexCompositionResult(
                message=None,
                status="timeout",
                failure_reason="Codex CLI response composition timed out.",
                prompt_preamble=prompt_preamble,
                command=command_summary,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
                stdout_tail=transcript["stdout_tail"],
                stderr_tail=transcript["stderr_tail"],
                events=transcript["events"],
                event_count=transcript["event_count"],
                jsonl_tail=transcript["jsonl_tail"],
            )
        except OSError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return CodexCompositionResult(
                message=None,
                status="os_error",
                failure_reason=str(exc),
                prompt_preamble=prompt_preamble,
                command=command_summary,
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        transcript = build_codex_cli_transcript(
            status="succeeded" if completed.returncode == 0 else "failed",
            command=command_summary,
            timeout_seconds=timeout_seconds,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        stdout_tail = str(transcript["stdout_tail"])
        stderr_tail = str(transcript["stderr_tail"])
        if completed.returncode != 0:
            return CodexCompositionResult(
                message=None,
                status="failed",
                failure_reason=stderr_tail[-1200:] or f"Codex CLI exited with {completed.returncode}.",
                prompt_preamble=prompt_preamble,
                command=command_summary,
                timeout_seconds=timeout_seconds,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                events=transcript["events"],
                event_count=transcript["event_count"],
                jsonl_tail=transcript["jsonl_tail"],
            )
        if not response_path.exists():
            return CodexCompositionResult(
                message=None,
                status="missing_output",
                failure_reason="Codex CLI did not write a response file.",
                prompt_preamble=prompt_preamble,
                command=command_summary,
                timeout_seconds=timeout_seconds,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                events=transcript["events"],
                event_count=transcript["event_count"],
                jsonl_tail=transcript["jsonl_tail"],
            )
        message = response_path.read_text(encoding="utf-8").strip()
        if not message:
            return CodexCompositionResult(
                message=None,
                status="empty_output",
                failure_reason="Codex CLI returned an empty response.",
                prompt_preamble=prompt_preamble,
                command=command_summary,
                timeout_seconds=timeout_seconds,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                events=transcript["events"],
                event_count=transcript["event_count"],
                jsonl_tail=transcript["jsonl_tail"],
            )
        return CodexCompositionResult(
            message=message[:4000],
            status="succeeded",
            prompt_preamble=prompt_preamble,
            command=command_summary,
            timeout_seconds=timeout_seconds,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            events=transcript["events"],
            event_count=transcript["event_count"],
            jsonl_tail=transcript["jsonl_tail"],
        )


def codex_response_timeout_seconds() -> int:
    raw_value = os.environ.get("TABLEX_AGENT_RESPONSE_TIMEOUT_SECONDS", "90").strip()
    try:
        value = int(raw_value)
    except ValueError:
        return 90
    return min(max(value, 15), 300)


def response_composer_model(brief: dict[str, Any]) -> str | None:
    preferences = brief.get("model_preferences")
    if not isinstance(preferences, dict):
        return None
    utility_model = preferences.get("utility_model")
    if not isinstance(utility_model, str):
        return None
    normalized = utility_model.strip()
    if not normalized or normalized in {"default", "codex-default", "utility-default"}:
        return None
    return normalized


def response_shortcut_for_message(user_message: str) -> str | None:
    return "btw_status_explanation" if user_message.strip().lower() == "/btw" else None


def response_composer_fallback_message(fallback_message: str, brief: dict[str, Any]) -> str:
    locale = str(brief.get("response_locale") or "")
    if locale_is_japanese(locale):
        return (
            f"{fallback_message}\n\n"
            "補助的な返答生成は一時的に使えなかったため、保存済みのProject状態から確認できる範囲で答えています。"
        )
    return (
        f"{fallback_message}\n\n"
        "The auxiliary response composer was temporarily unavailable, so this answer is limited to saved project state."
    )


def response_composer_handoff_message(brief: dict[str, Any], reason: str | None) -> str:
    locale = str(brief.get("response_locale") or "")
    if locale_is_japanese(locale):
        if reason:
            return f"この確認は保存済みの状態だけでは完了できません。メインのCodexが確認します。理由: {reason}"
        return "この確認は保存済みの状態だけでは完了できません。メインのCodexが確認します。"
    if reason:
        return f"This needs the main Codex session to check the project directly. Reason: {reason}"
    return "This needs the main Codex session to check the project directly."


def codex_unavailable_message(brief: dict[str, Any]) -> str:
    locale = str(brief.get("response_locale") or "")
    if locale_is_japanese(locale):
        return (
            "この返答はCodexで生成できませんでした。"
            "返答生成用のCodex起動に失敗しました。\n"
            "入力は保存済みです。Full AutoがONの場合はCodexへ渡され、進行はChat、Raw、Agent Activityに反映されます。"
        )
    return (
        "I could not generate this reply with Codex. "
        "The Codex process used for response composition failed to start or complete.\n"
        "Your input was saved. If Full Auto is on, it will be delivered to Codex and reflected in Chat, Raw, and Agent Activity."
    )


def list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
