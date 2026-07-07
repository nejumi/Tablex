from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tabular_harness.models.entities import utc_now

INBOX_ENTRY_SCHEMA_VERSION = "tablex_inbox_entry.v1"
INBOX_PROCESSED_FILENAME = ".processed"
INBOX_ENTRY_KINDS = {"user_instruction", "rejection", "observation", "request"}


def agent_inbox_dir(workspace: Path) -> Path:
    return workspace / ".tablex" / "inbox"


def inbox_processed_path(workspace: Path) -> Path:
    return agent_inbox_dir(workspace) / INBOX_PROCESSED_FILENAME


def list_inbox_entries(workspace: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    inbox = agent_inbox_dir(workspace)
    if not inbox.exists():
        return []
    for path in sorted(inbox.glob("[0-9][0-9][0-9][0-9][0-9][0-9]_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema_version") != INBOX_ENTRY_SCHEMA_VERSION:
            continue
        payload["_path"] = str(path)
        payload["_filename"] = path.name
        entries.append(payload)
    return entries


def latest_inbox_entry_path(workspace: Path, *, entry_type: str, kind: str) -> Path:
    inbox = agent_inbox_dir(workspace)
    latest: Path | None = None
    for entry in list_inbox_entries(workspace):
        if entry.get("type") == entry_type and entry.get("kind") == kind and isinstance(entry.get("_path"), str):
            latest = Path(str(entry["_path"]))
    if latest is not None:
        return latest
    return inbox / f"{next_inbox_sequence(workspace):06d}_{kind}.json"


def write_inbox_entry(
    workspace: Path,
    *,
    kind: str,
    entry_type: str,
    payload: dict[str, Any],
    content: str | None = None,
    title: str | None = None,
) -> Path:
    if kind not in INBOX_ENTRY_KINDS:
        raise ValueError(f"invalid inbox kind: {kind}")
    inbox = agent_inbox_dir(workspace)
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{next_inbox_sequence(workspace):06d}_{kind}.json"
    envelope: dict[str, Any] = {
        "schema_version": INBOX_ENTRY_SCHEMA_VERSION,
        "kind": kind,
        "type": entry_type,
        "created_at": utc_now().isoformat(),
        "payload": payload,
    }
    if title:
        envelope["title"] = title
    if content is not None:
        envelope["content"] = content
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
    return path


def mark_inbox_entry_processed(workspace: Path, entry_path: Path | str, *, processed_by: str = "codex") -> None:
    path = Path(entry_path)
    record = {
        "schema_version": "tablex_inbox_processed_entry.v1",
        "processed_at": utc_now().isoformat(),
        "processed_by": processed_by,
        "entry": path.name,
    }
    processed = inbox_processed_path(workspace)
    processed.parent.mkdir(parents=True, exist_ok=True)
    with processed.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def next_inbox_sequence(workspace: Path) -> int:
    inbox = agent_inbox_dir(workspace)
    max_sequence = 0
    if inbox.exists():
        for path in inbox.glob("[0-9][0-9][0-9][0-9][0-9][0-9]_*.json"):
            match = re.match(r"^(\d{6})_", path.name)
            if match:
                max_sequence = max(max_sequence, int(match.group(1)))
    return max_sequence + 1
