from __future__ import annotations

import hashlib
import re
from datetime import timezone
from pathlib import Path

from tabular_harness.models.entities import Artifact, utc_now
from tabular_harness.services.agent_workspace import CODEX_RAW_TRANSCRIPT_FILENAME, CODEX_STDERR_LOG_FILENAME
from tabular_harness.services.artifacts import artifact_primary_path
from tabular_harness.services.research_plans import research_plan_source_is_marimo_notebook

SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS = 30


def asset_type_for_session_output(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name == CODEX_RAW_TRANSCRIPT_FILENAME or (suffix == ".jsonl" and "transcript" in path.stem.lower()):
        return "agent_session_transcript"
    if path.name == CODEX_STDERR_LOG_FILENAME:
        return "agent_session_log"
    if suffix == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        return "analysis_notebook"
    if suffix == ".md":
        return "agent_session_report"
    if suffix == ".json" and path.stem.lower() in {"research_plan", "research_plan_timeline"}:
        return "research_plan"
    if suffix == ".json":
        return "agent_session_artifact"
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
        return "agent_session_figure"
    return "agent_session_output"


def session_output_artifact_name(session_id: str, relative_path: Path) -> str:
    relative_text = relative_path.as_posix()
    digest = hashlib.sha1(relative_text.encode("utf-8")).hexdigest()[:10]
    readable = re.sub(r"[^A-Za-z0-9]+", "_", relative_text).strip("_") or "output"
    return f"agent_session_{session_id}_{readable[:145]}_{digest}"


def should_skip_session_output(path: Path) -> bool:
    return (
        path.name.startswith(".")
        or path.name == "artifact_manifest.json"
        or path.suffix == ".pyc"
        or "__pycache__" in path.parts
    )


def session_output_rejection_reason(path: Path) -> str | None:
    if path.suffix.lower() == ".html":
        return "static_html_outputs_are_not_tablex_notebook_artifacts"
    if path.suffix.lower() == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return "notebook_python_source_is_not_readable"
        if not research_plan_source_is_marimo_notebook(source):
            return "notebook_python_source_must_be_native_marimo"
    return None


def session_output_rejection_message_kind(reason: str) -> str:
    if reason == "static_html_outputs_are_not_tablex_notebook_artifacts":
        return "static_html_output_rejected"
    if reason.startswith("notebook_python_source_"):
        return "notebook_source_rejected"
    return "workspace_output_rejected"


def should_register_session_output(path: Path, existing: Artifact | None) -> bool:
    if existing is None:
        return True
    try:
        existing_path = artifact_primary_path(existing)
        changed = hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(existing_path.read_bytes()).hexdigest()
    except OSError:
        return True
    if not changed:
        return False
    if is_chat_update_path(path):
        return True
    created_at = existing.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (utc_now() - created_at).total_seconds() >= SESSION_OUTPUT_MIN_VERSION_INTERVAL_SECONDS


def is_chat_update_path(path: Path) -> bool:
    return path.name == "chat_update.md" and path.parent.name == "reports"


def metadata_for_session_output(path: Path) -> dict[str, object]:
    if path.name == CODEX_RAW_TRANSCRIPT_FILENAME:
        return {"transcript_kind": "codex_cli_stdout_jsonl", "raw_codex_cli": True}
    if path.name == CODEX_STDERR_LOG_FILENAME:
        return {"transcript_kind": "codex_cli_stderr", "raw_codex_cli": True}
    suffix = path.suffix.lower()
    if suffix == ".py" and ("notebook" in path.parts or "notebooks" in path.parts):
        return {"notebook_kind": notebook_kind_for_session_output(path)}
    return {}


def notebook_kind_for_session_output(path: Path) -> str:
    name = path.stem.lower().replace("-", "_")
    if any(marker in name for marker in ("data_understanding", "grandmaster_eda", "eda", "exploration", "visual_story")):
        return "data_understanding"
    if any(marker in name for marker in ("model_diagnostics", "diagnostic", "leaderboard", "model", "experiment", "result")):
        return "model_diagnostics"
    return "agent_authored"
