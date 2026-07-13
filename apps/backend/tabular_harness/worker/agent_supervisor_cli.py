from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.agent.runners import safe_env
from tabular_harness.core.config import get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.agent_sessions import start_active_main_session_supervisors
from tabular_harness.services.artifacts import LocalArtifactStore

AgentSessionSupervisorRunner = Callable[..., list[threading.Thread]]
logger = logging.getLogger(__name__)


def check_codex_runtime() -> None:
    codex = shutil.which("codex")
    if codex is None:
        raise RuntimeError("Codex CLI is not installed or is not on PATH.")
    with tempfile.TemporaryDirectory(prefix="tablex_codex_check_") as tmp:
        workspace = Path(tmp)
        env = safe_env(workspace)
        runtime_codex = shutil.which("codex", path=env.get("PATH")) or codex
        login = subprocess.run(
            [runtime_codex, "login", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
        if login.returncode != 0:
            detail = (login.stderr or login.stdout).strip()
            raise RuntimeError(f"Codex is not authenticated. {detail}".strip())
        probe = subprocess.run(
            [
                runtime_codex,
                "sandbox",
                "-P",
                "workspace",
                "-C",
                str(workspace),
                "--",
                "sh",
                "-c",
                "touch runtime-check && rm -f runtime-check",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout).strip()
            raise RuntimeError(f"Codex local sandbox is unavailable. {detail}".strip())


def run_agent_session_supervisor_loop(
    session_factory: sessionmaker[Session],
    store: LocalArtifactStore,
    *,
    once: bool = False,
    interval_seconds: float = 15.0,
    lease_owner_id: str | None = None,
    agent_model: str | None = None,
    stop_event: threading.Event | None = None,
    supervisor_runner: AgentSessionSupervisorRunner = start_active_main_session_supervisors,
) -> None:
    owner_id = lease_owner_id or f"agent-supervisor:pid:{os.getpid()}"
    interval = max(0.1, interval_seconds)
    active_threads: set[threading.Thread] = set()
    while True:
        try:
            active_threads = {thread for thread in active_threads if thread.is_alive()}
            started_threads = supervisor_runner(
                session_factory,
                store,
                agent_model=agent_model,
                lease_owner_id=owner_id,
                shutdown_event=stop_event,
            )
            if started_threads:
                active_threads.update(started_threads)
        except Exception:
            if once:
                raise
            logger.exception("AgentSession supervisor scan failed; retrying after the configured interval.")
        if once:
            return
        if stop_event is not None:
            if stop_event.wait(interval):
                break
        else:
            time.sleep(interval)
    for thread in active_threads:
        thread.join(timeout=20)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Tablex Full Auto AgentSession supervisor.")
    parser.add_argument("--once", action="store_true", help="Recover active sessions once and exit.")
    parser.add_argument("--interval", type=float, default=15.0, help="Recovery scan interval in seconds.")
    parser.add_argument("--owner-id", default=None, help="Stable lease owner id for this supervisor process.")
    parser.add_argument("--agent-model", default=None, help="Optional Codex model override for resumed sessions.")
    parser.add_argument("--check-runtime", action="store_true", help="Check Codex auth and sandbox, then exit.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.check_runtime:
        try:
            check_codex_runtime()
        except RuntimeError as exc:
            print(f"Tablex: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        print("Codex runtime is ready.")
        return
    settings = get_settings()
    engine = create_engine_for_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    artifact_store = LocalArtifactStore(settings.artifact_root)
    stop_event = threading.Event()

    def request_shutdown(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    run_agent_session_supervisor_loop(
        session_factory,
        artifact_store,
        once=args.once,
        interval_seconds=args.interval,
        lease_owner_id=args.owner_id,
        agent_model=args.agent_model,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    main()
