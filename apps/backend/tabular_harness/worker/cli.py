from __future__ import annotations

import argparse
import os
import time

from tabular_harness.core.config import get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.agent_sessions import start_active_main_session_supervisors
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.worker.jobs import create_default_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Tablex worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds.")
    parser.add_argument("--worker-id", default="local-worker", help="Worker identifier for job locks.")
    parser.add_argument(
        "--no-agent-session-supervisor",
        action="store_true",
        help="Disable worker-side recovery for active Full Auto Codex sessions.",
    )
    parser.add_argument(
        "--job-type",
        action="append",
        default=[],
        help="Only acquire this job type. Repeat to allow multiple types.",
    )
    parser.add_argument(
        "--exclude-job-type",
        action="append",
        default=[],
        help="Do not acquire this job type. Repeat to exclude multiple types.",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine_for_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    worker = create_default_worker(worker_id=args.worker_id, include_stub_handlers=False)
    selected_job_types = set(args.job_type) if args.job_type else set(worker.handlers)
    selected_job_types.difference_update(args.exclude_job_type)
    artifact_store = LocalArtifactStore(settings.artifact_root)
    supervisor_recovery_interval_seconds = 15.0
    next_supervisor_recovery_at = 0.0
    if not args.once and not args.no_agent_session_supervisor:
        start_active_main_session_supervisors(
            session_factory,
            artifact_store,
            lease_owner_id=f"worker:{args.worker_id}:pid:{os.getpid()}",
            turn_timeout_seconds=settings.agent_idle_timeout_seconds,
            turn_start_silence_timeout_seconds=settings.agent_turn_start_silence_timeout_seconds,
        )
        next_supervisor_recovery_at = time.monotonic() + supervisor_recovery_interval_seconds

    while True:
        if (
            not args.once
            and not args.no_agent_session_supervisor
            and time.monotonic() >= next_supervisor_recovery_at
        ):
            start_active_main_session_supervisors(
                session_factory,
                artifact_store,
                lease_owner_id=f"worker:{args.worker_id}:pid:{os.getpid()}",
                turn_timeout_seconds=settings.agent_idle_timeout_seconds,
                turn_start_silence_timeout_seconds=settings.agent_turn_start_silence_timeout_seconds,
            )
            next_supervisor_recovery_at = time.monotonic() + supervisor_recovery_interval_seconds
        with session_factory() as session:
            job = worker.run_next_job(session, job_types=selected_job_types)
            session.commit()
            if args.once:
                return
        if job is None:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
