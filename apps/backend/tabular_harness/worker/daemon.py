from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.config import get_settings
from tabular_harness.services.agent_sessions import start_active_main_session_supervisors
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.storage_management import cleanup_temporary_storage
from tabular_harness.worker.jobs import create_default_worker

AgentSessionSupervisorRunner = Callable[..., list[threading.Thread]]


@dataclass
class LocalWorkerDaemon:
    session_factory: sessionmaker[Session]
    store: LocalArtifactStore
    worker_id: str = "local-worker-daemon"
    interval_seconds: float = 1.0
    max_jobs_per_wake: int = 3
    agent_session_supervisor_enabled: bool = True
    agent_session_supervisor_interval_seconds: float = 15.0
    storage_cleanup_interval_seconds: float = 10 * 60
    agent_session_supervisor_runner: AgentSessionSupervisorRunner = start_active_main_session_supervisors

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_agent_session_supervisor_check_at = 0.0
        self._next_storage_cleanup_at = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=self.worker_id,
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 3.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def _run(self) -> None:
        worker = create_default_worker(worker_id=self.worker_id, store=self.store, include_stub_handlers=False)
        while not self._stop_event.is_set():
            self._maybe_recover_agent_session_supervisors()
            self._maybe_cleanup_temporary_storage()
            ran_job = False
            for _ in range(max(1, self.max_jobs_per_wake)):
                if self._stop_event.is_set():
                    break
                with self.session_factory() as db:
                    job = worker.run_next_job(db)
                    if job is None:
                        break
                    ran_job = True
            if not ran_job:
                self._stop_event.wait(max(0.1, self.interval_seconds))

    def _maybe_recover_agent_session_supervisors(self) -> None:
        if not self.agent_session_supervisor_enabled:
            return
        now = time.monotonic()
        if now < self._next_agent_session_supervisor_check_at:
            return
        interval = max(0.1, self.agent_session_supervisor_interval_seconds)
        self._next_agent_session_supervisor_check_at = now + interval
        try:
            self.agent_session_supervisor_runner(
                self.session_factory,
                self.store,
                lease_owner_id=f"worker-daemon:{self.worker_id}:thread:{threading.get_ident()}",
            )
        except Exception:
            self._next_agent_session_supervisor_check_at = now + interval

    def _maybe_cleanup_temporary_storage(self) -> None:
        now = time.monotonic()
        if now < self._next_storage_cleanup_at:
            return
        interval = max(60.0, self.storage_cleanup_interval_seconds)
        self._next_storage_cleanup_at = now + interval
        try:
            cleanup_temporary_storage(settings=get_settings())
        except Exception:
            self._next_storage_cleanup_at = now + interval
