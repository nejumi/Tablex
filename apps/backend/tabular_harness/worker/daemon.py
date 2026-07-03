from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.worker.jobs import create_default_worker


@dataclass
class LocalWorkerDaemon:
    session_factory: sessionmaker[Session]
    store: LocalArtifactStore
    worker_id: str = "local-worker-daemon"
    interval_seconds: float = 1.0
    max_jobs_per_wake: int = 3

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
        worker = create_default_worker(worker_id=self.worker_id, store=self.store)
        while not self._stop_event.is_set():
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
