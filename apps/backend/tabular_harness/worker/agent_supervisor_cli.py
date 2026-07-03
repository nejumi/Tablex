from __future__ import annotations

import argparse
import os
import threading
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.config import get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.agent_sessions import start_active_main_session_supervisors
from tabular_harness.services.artifacts import LocalArtifactStore

AgentSessionSupervisorRunner = Callable[..., list[threading.Thread]]


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
    while True:
        supervisor_runner(
            session_factory,
            store,
            agent_model=agent_model,
            lease_owner_id=owner_id,
        )
        if once:
            return
        if stop_event is not None:
            if stop_event.wait(interval):
                return
        else:
            time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Tablex Full Auto AgentSession supervisor.")
    parser.add_argument("--once", action="store_true", help="Recover active sessions once and exit.")
    parser.add_argument("--interval", type=float, default=15.0, help="Recovery scan interval in seconds.")
    parser.add_argument("--owner-id", default=None, help="Stable lease owner id for this supervisor process.")
    parser.add_argument("--agent-model", default=None, help="Optional Codex model override for resumed sessions.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    engine = create_engine_for_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    artifact_store = LocalArtifactStore(settings.artifact_root)
    run_agent_session_supervisor_loop(
        session_factory,
        artifact_store,
        once=args.once,
        interval_seconds=args.interval,
        lease_owner_id=args.owner_id,
        agent_model=args.agent_model,
    )


if __name__ == "__main__":
    main()
