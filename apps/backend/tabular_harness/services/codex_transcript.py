from __future__ import annotations

import json
from typing import Any

MAX_CODEX_EVENT_COUNT = 400
MAX_CODEX_STDIO_CHARS = 200_000
MAX_CODEX_FIELD_CHARS = 24_000


def build_codex_cli_transcript(
    *,
    status: str,
    command: str,
    timeout_seconds: int | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    stdout: str = "",
    stderr: str = "",
    codex_binary: str | None = None,
) -> dict[str, Any]:
    events = parse_codex_jsonl(stdout)
    transcript: dict[str, Any] = {
        "schema_version": "codex_cli_transcript.v1",
        "status": status,
        "command": command,
        "timeout_seconds": timeout_seconds,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout_tail": tail_text(stdout, 12_000),
        "stderr_tail": tail_text(stderr, 12_000),
        "jsonl_tail": tail_text(stdout, MAX_CODEX_STDIO_CHARS),
        "events": events[-MAX_CODEX_EVENT_COUNT:],
        "event_count": len(events),
    }
    if codex_binary:
        transcript["codex_binary"] = codex_binary
    return transcript


def parse_codex_jsonl(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(compact_value(payload))
    return events


def compact_value(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_CODEX_FIELD_CHARS else value[:MAX_CODEX_FIELD_CHARS] + "\n...[truncated]"
    if isinstance(value, list):
        return [compact_value(item) for item in value[:200]]
    if isinstance(value, dict):
        return {str(key): compact_value(item) for key, item in value.items()}
    return value


def tail_text(value: str, limit: int) -> str:
    if not value:
        return ""
    return value[-limit:]
