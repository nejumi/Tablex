from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tabular_harness.core.config import Settings
from tabular_harness.core.ids import new_id
from tabular_harness.models.entities import Artifact
from tabular_harness.services.analysis_notebooks import (
    marimo_available,
    notebook_export_env,
    source_notebook_path_for_export,
    source_notebook_working_dir_for_export,
)

MARIMO_SOURCE_ASSET_TYPES = {"analysis_notebook", "marimo_notebook"}
SESSION_TTL_SECONDS = 60 * 60
FAILED_SESSION_TTL_SECONDS = 10 * 60


@dataclass
class NativeMarimoSession:
    id: str
    artifact_id: str
    project_id: str | None
    notebook_path: Path
    port: int
    process: subprocess.Popen[bytes]
    base_url: str
    proxy_url: str
    workdir: Path
    started_at: datetime
    last_accessed_at: datetime
    stdout_path: Path
    stderr_path: Path
    source_hash: str

    def to_dict(self) -> dict[str, Any]:
        runtime_error = self.runtime_error_excerpt()
        status = self.status()
        return {
            "schema_version": "native_marimo_session.v1",
            "session_id": self.id,
            "artifact_id": self.artifact_id,
            "project_id": self.project_id,
            "proxy_url": self.proxy_url,
            "base_url": self.base_url,
            "status": status,
            "started_at": self.started_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "source_hash": self.source_hash,
            "runtime": {
                "has_error": runtime_error is not None,
                "error_excerpt": runtime_error,
            },
        }

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def status(self) -> str:
        if not self.is_alive():
            return "failed"
        return "running" if _http_ready(self) else "starting"

    def runtime_error_excerpt(self, limit: int = 4000) -> str | None:
        stderr_tail = _tail_text(self.stderr_path, max(limit * 3, limit))
        if not stderr_tail.strip() and self.is_alive():
            return None
        if not stderr_tail.strip():
            return "marimo process exited before the notebook became available."
        traceback_start = stderr_tail.rfind("Traceback (most recent call last):")
        if traceback_start >= 0:
            return _compact_error_excerpt(stderr_tail[traceback_start:].strip(), limit)
        for marker in ("An internal error occurred", '"type":"internal"', "[E "):
            start = stderr_tail.rfind(marker)
            if start >= 0:
                return _compact_error_excerpt(stderr_tail[start:].strip(), limit)
        return None


_lock = threading.RLock()
_sessions_by_id: dict[str, NativeMarimoSession] = {}
_session_id_by_artifact_id: dict[str, str] = {}


def start_or_get_native_marimo_session(
    *,
    artifact: Artifact,
    settings: Settings,
) -> NativeMarimoSession:
    if artifact.asset_type not in MARIMO_SOURCE_ASSET_TYPES:
        raise ValueError("Native marimo sessions require a marimo source notebook artifact.")
    if not marimo_available():
        raise RuntimeError("marimo is not installed in the backend environment.")
    notebook_path = source_notebook_path_for_export(artifact)
    if notebook_path is None or not notebook_path.exists():
        raise FileNotFoundError("Notebook source file was not found.")
    if notebook_path.suffix.lower() != ".py":
        raise ValueError("Native marimo sessions require a Python marimo source file.")
    source_hash = _file_sha256(notebook_path)
    notebook_cwd = source_notebook_working_dir_for_export(artifact, notebook_path) or notebook_path.parent

    with _lock:
        _cleanup_locked(settings=settings)
        existing_id = _session_id_by_artifact_id.get(artifact.id)
        existing = _sessions_by_id.get(existing_id or "")
        if existing is not None and existing.is_alive():
            if existing.source_hash == source_hash:
                existing.last_accessed_at = datetime.now(timezone.utc)
                return existing
            _terminate_process(existing.process)
            _remove_session_locked(existing)
        elif existing is not None:
            _remove_session_locked(existing)

        _enforce_session_limit_locked(settings=settings)
        session_id = new_id("mos")
        port = _free_port()
        base_url = f"/api/marimo-sessions/{session_id}/proxy"
        proxy_url = f"{base_url}/"
        workdir = (settings.data_dir / "marimo_sessions" / session_id).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        stdout_path = workdir / "stdout.log"
        stderr_path = workdir / "stderr.log"
        command = [
            sys.executable,
            "-m",
            "marimo",
            "run",
            str(notebook_path),
            "--headless",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-token",
            "--base-url",
            base_url,
            "--session-ttl",
            str(SESSION_TTL_SECONDS),
        ]
        env = notebook_export_env(workdir)
        env["PYTHONUNBUFFERED"] = "1"
        stdout_file = stdout_path.open("ab")
        stderr_file = stderr_path.open("ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(notebook_cwd),
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=(os.name != "nt"),
            )
        finally:
            stdout_file.close()
            stderr_file.close()
        session = NativeMarimoSession(
            id=session_id,
            artifact_id=artifact.id,
            project_id=artifact.project_id,
            notebook_path=notebook_path,
            port=port,
            process=process,
            base_url=base_url,
            proxy_url=proxy_url,
            workdir=workdir,
            started_at=datetime.now(timezone.utc),
            last_accessed_at=datetime.now(timezone.utc),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            source_hash=source_hash,
        )
        _sessions_by_id[session.id] = session
        _session_id_by_artifact_id[artifact.id] = session.id
        return session


def native_marimo_session(session_id: str) -> NativeMarimoSession | None:
    with _lock:
        session = _sessions_by_id.get(session_id)
        if session is None:
            return None
        session.last_accessed_at = datetime.now(timezone.utc)
        return session


def native_marimo_target_url(session: NativeMarimoSession, path: str, query: str = "") -> str:
    normalized_path = path.strip("/")
    suffix = f"/{normalized_path}" if normalized_path else "/"
    url = f"http://127.0.0.1:{session.port}{session.base_url}{suffix}"
    if query:
        url = f"{url}?{query}"
    return url


def stop_native_marimo_session(session_id: str) -> bool:
    with _lock:
        session = _sessions_by_id.get(session_id)
        if session is None:
            return False
        _terminate_process(session.process)
        _remove_session_locked(session)
        return True


def cleanup_native_marimo_sessions(*, settings: Settings) -> int:
    with _lock:
        before = len(_sessions_by_id)
        _cleanup_locked(settings=settings)
        _enforce_session_limit_locked(settings=settings)
        return max(0, before - len(_sessions_by_id))


def stop_native_marimo_session_for_artifact(artifact_id: str) -> bool:
    with _lock:
        session_id = _session_id_by_artifact_id.get(artifact_id)
        session = _sessions_by_id.get(session_id or "")
        if session is None:
            return False
        _terminate_process(session.process)
        _remove_session_locked(session)
        return True


def stop_native_marimo_sessions_for_project(project_id: str) -> int:
    stopped = 0
    with _lock:
        sessions = [session for session in _sessions_by_id.values() if session.project_id == project_id]
        for session in sessions:
            _terminate_process(session.process)
            _remove_session_locked(session)
            stopped += 1
    return stopped


def stop_orphaned_native_marimo_processes(*, settings: Settings) -> int:
    """Stop Tablex-owned marimo processes left behind by a previous backend process."""
    agent_session_root = (settings.artifact_root / "agent_sessions").resolve()
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    current_pid = os.getpid()
    stopped = 0
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        if " -m marimo run " not in f" {command} ":
            continue
        if "/api/marimo-sessions/" not in command:
            continue
        if str(agent_session_root) not in command:
            continue
        if _terminate_pid(pid):
            stopped += 1
    return stopped


def _http_ready(session: NativeMarimoSession, timeout: float = 0.05) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{session.port}{session.base_url}/",
            timeout=timeout,
        ) as response:
            return response.status < 500
    except Exception:
        return False


def _cleanup_locked(*, settings: Settings) -> None:
    del settings
    now = datetime.now(timezone.utc)
    for session in list(_sessions_by_id.values()):
        age = (now - session.last_accessed_at).total_seconds()
        if session.is_alive() and age > SESSION_TTL_SECONDS:
            _terminate_process(session.process)
            _remove_session_locked(session)
        elif not session.is_alive() and age > FAILED_SESSION_TTL_SECONDS:
            _remove_session_locked(session)


def _enforce_session_limit_locked(*, settings: Settings) -> None:
    max_sessions = max(1, int(settings.marimo_max_sessions))
    alive_sessions = [session for session in _sessions_by_id.values() if session.is_alive()]
    if len(alive_sessions) < max_sessions:
        return
    removable = sorted(alive_sessions, key=lambda session: session.last_accessed_at)
    for session in removable[: max(0, len(alive_sessions) - max_sessions + 1)]:
        _terminate_process(session.process)
        _remove_session_locked(session)


def _remove_session_locked(session: NativeMarimoSession) -> None:
    _sessions_by_id.pop(session.id, None)
    if _session_id_by_artifact_id.get(session.artifact_id) == session.id:
        _session_id_by_artifact_id.pop(session.artifact_id, None)
    shutil.rmtree(session.workdir, ignore_errors=True)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _terminate_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return not _pid_alive(pid)
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _tail_text(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()[-limit:]
    return data.decode("utf-8", errors="replace")


def _compact_error_excerpt(text: str, limit: int) -> str:
    compacted = "\n".join(_compact_error_line(line) for line in text.splitlines()).strip()
    if len(compacted) <= limit:
        return compacted
    separator = "\n...\n"
    head_limit = min(1200, max(400, limit // 3))
    tail_limit = max(400, limit - head_limit - len(separator))
    return f"{compacted[:head_limit].rstrip()}{separator}{compacted[-tail_limit:].lstrip()}"


def _compact_error_line(line: str, limit: int = 420) -> str:
    line = re.sub(r"(.)\1{32,}", lambda match: f"{match.group(1) * 32}<repeated {len(match.group(0)) - 32} chars>", line)
    if len(line) <= limit:
        return line
    omitted = len(line) - limit
    head_limit = max(180, limit // 2)
    tail_limit = max(120, limit - head_limit - 40)
    head = line[:head_limit].rstrip()
    tail = line[-tail_limit:].lstrip()
    return f"{head} ... <{omitted} chars omitted> ... {tail}"
