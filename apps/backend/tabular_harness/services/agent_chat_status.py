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
    if status == "queued":
        worker_state = "waiting_for_local_worker"
        stale = job_age_seconds >= 60
        if delivered_to_running_codex:
            assistant_message = (
                f"受け取りました。入力は進行中の分析エージェントに届いています。チャットへの返信保存はworker待ちです（待機 {age_label}）。"
                if japanese
                else f"Received. The running analysis agent has the message; the reply-saving job is waiting for the local worker ({age_label})."
            )
        else:
            assistant_message = (
                f"受け取りました。返信を作成するworker待ちです（待機 {age_label}）。"
                if japanese
                else f"Received. The reply job is waiting for the local worker ({age_label})."
            )
        if stale:
            assistant_message += (
                " workerが拾えていない可能性があります。ActivityまたはJobsでworker状態を確認できます。"
                if japanese
                else " The worker may not have picked it up yet; Activity or Jobs shows the worker state."
            )
        headline = "worker待ち" if japanese else "Waiting for local worker"
        detail = (
            f"返信処理はまだ開始していません。待機 {age_label}。"
            if japanese
            else f"This reply job has not started yet. Waiting {age_label}."
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
                " 更新がしばらくありません。完了しなければworker再起動またはretry対象です。"
                if japanese
                else " There has been no recent update; if it does not complete, the worker should be restarted or retried."
            )
        headline = "返答を処理中" if japanese else "Processing reply"
        detail = (
            f"workerが返信処理を実行中です。最終更新 {update_label}前。"
            if japanese
            else f"The worker is running this reply job. Last update {update_label} ago."
        )
    else:
        worker_state = f"job_{status}"
        stale = False
        assistant_message = (
            f"返答ジョブの状態は {status} です。"
            if japanese
            else f"The reply job status is {status}."
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
