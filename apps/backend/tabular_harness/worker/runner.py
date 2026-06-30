from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from tabular_harness.models.entities import Job
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.jobs import (
    acquire_next_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
)


class JobHandler(Protocol):
    def __call__(self, db: Session, job: Job, store: LocalArtifactStore) -> dict[str, object]:
        ...


@dataclass
class SyncWorker:
    handlers: dict[str, JobHandler]
    store: LocalArtifactStore
    worker_id: str = "local-worker"

    def run_job(self, db: Session, job: Job) -> Job:
        handler = self.handlers.get(job.job_type)
        if handler is None:
            mark_job_failed(job, f"No handler registered for {job.job_type}")
            db.commit()
            return job
        try:
            mark_job_running(job)
            db.commit()
            output = handler(db, job, self.store)
            if output.get("job_status") == "failed":
                mark_job_failed(job, str(output.get("error_message") or "Job failed"), output)
            else:
                mark_job_succeeded(job, output)
            db.commit()
        except Exception as exc:
            mark_job_failed(job, str(exc))
            db.commit()
        return job

    def run_next_job(self, db: Session) -> Job | None:
        job = acquire_next_job(db, worker_id=self.worker_id, job_types=set(self.handlers))
        if job is None:
            return None
        return self.run_job(db, job)
