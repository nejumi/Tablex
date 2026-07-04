from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tabular_harness.models.entities import Job, utc_now
from tabular_harness.services.locales import locale_is_japanese


def format_elapsed_for_agent_chat(seconds: int, *, japanese: bool) -> str:
    if seconds < 60:
        return f"{seconds}秒" if japanese else f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分" if japanese else f"{minutes}m"
    hours = minutes // 60
    remainder = minutes % 60
    if japanese:
        return f"{hours}時間{remainder}分" if remainder else f"{hours}時間"
    return f"{hours}h {remainder}m" if remainder else f"{hours}h"


def seconds_since_timestamp(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds()))


def agent_chat_wait_state(
    job: Job,
    *,
    delivered_to_running_codex: bool,
    locale: str | None,
    response_worker_status: str | None = None,
) -> dict[str, Any]:
    japanese = locale_is_japanese(locale)
    now = utc_now()
    job_age_seconds = seconds_since_timestamp(job.created_at, now=now) or 0
    updated_age_seconds = seconds_since_timestamp(job.updated_at, now=now) or 0
    age_label = format_elapsed_for_agent_chat(job_age_seconds, japanese=japanese)
    update_label = format_elapsed_for_agent_chat(updated_age_seconds, japanese=japanese)
    status = response_worker_status or job.status
    if status == "waiting_for_agent":
        stale = job_age_seconds >= 60
        worker_state = "waiting_for_main_agent_reply"
        assistant_message = (
            f"受け取りました。入力は進行中の分析エージェントに届いています。Codexの返答が届き次第、このチャットに残します（待機 {age_label}）。"
            if japanese
            else f"Received. The running analysis agent has the message. The next Codex reply will be saved here when it arrives ({age_label})."
        )
        if stale:
            assistant_message += (
                " まだ返答が戻っていません。Agent Workspaceで現在の進行を確認できます。"
                if japanese
                else " No reply has returned yet; Agent Workspace shows the current progress."
            )
        headline = "Agentに伝達済み" if japanese else "Delivered to agent"
        detail = (
            f"Codexの次の返答を待っています。待機 {age_label}。"
            if japanese
            else f"Waiting for the next Codex reply. Waiting {age_label}."
        )
    elif status == "queued":
        stale = job_age_seconds >= 60
        if delivered_to_running_codex:
            worker_state = "waiting_for_main_agent_reply"
            assistant_message = (
                f"受け取りました。入力は進行中の分析エージェントに届いています。Codexの返答が届き次第、このチャットに残します（待機 {age_label}）。"
                if japanese
                else f"Received. The running analysis agent has the message. The next Codex reply will be saved here when it arrives ({age_label})."
            )
        else:
            worker_state = "waiting_for_local_worker"
            assistant_message = (
                f"受け取りました。返答を準備しています（待機 {age_label}）。"
                if japanese
                else f"Received. The reply is being prepared ({age_label})."
            )
        if stale:
            assistant_message += (
                " まだ返答が戻っていません。ActivityまたはJobsで処理状態を確認できます。"
                if japanese
                else " No reply has returned yet; Activity or Jobs shows the processing state."
            )
        if delivered_to_running_codex:
            headline = "Agentに伝達済み" if japanese else "Delivered to agent"
            detail = (
                f"Codexの返答が届き次第、このチャットに保存します。待機 {age_label}。"
                if japanese
                else f"The next Codex reply will be saved here. Waiting {age_label}."
            )
        else:
            headline = "返答準備中" if japanese else "Preparing reply"
            detail = (
                f"返答準備はまだ開始していません。待機 {age_label}。"
                if japanese
                else f"This reply has not started yet. Waiting {age_label}."
            )
    elif status == "running":
        worker_state = "worker_processing"
        stale = updated_age_seconds >= 300
        assistant_message = (
            f"受け取りました。返信を整理してチャットに保存中です（開始から {age_label}、最終更新 {update_label}前）。"
            if japanese
            else f"Received. The reply is being processed (started {age_label} ago, last update {update_label} ago)."
        )
        if delivered_to_running_codex:
            assistant_message = (
                f"受け取りました。入力は進行中の分析エージェントに届いており、返信をチャットに保存中です（開始から {age_label}、最終更新 {update_label}前）。"
                if japanese
                else f"Received. The running analysis agent has the message, and the reply is being saved (started {age_label} ago, last update {update_label} ago)."
            )
        if stale:
            assistant_message += (
                " 更新がしばらくありません。進行状況を確認し、必要なら自動的に再開します。"
                if japanese
                else " There has been no recent update; Tablex will check progress and resume automatically if needed."
            )
        headline = "返答を処理中" if japanese else "Processing reply"
        detail = (
            f"返信を整理しています。最終更新 {update_label}前。"
            if japanese
            else f"The reply is being organized. Last update {update_label} ago."
        )
    else:
        worker_state = f"job_{status}"
        stale = False
        assistant_message = (
            f"返答の状態は {status} です。"
            if japanese
            else f"The reply status is {status}."
        )
        headline = status.replace("_", " ").title()
        detail = assistant_message
    return {
        "assistant_message": assistant_message,
        "headline": headline,
        "detail": detail,
        "brief": {
            "schema_version": "agent_chat_wait_state.v1",
            "worker_state": worker_state,
            "status": status,
            "job_age_seconds": job_age_seconds,
            "updated_age_seconds": updated_age_seconds,
            "possibly_stale": stale,
        },
    }
