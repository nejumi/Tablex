from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.exc import OperationalError, SQLAlchemyError
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
        job_id = job.id
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
        except OperationalError:
            db.rollback()
        except Exception as exc:
            db.rollback()
            failed_job = db.get(Job, job_id)
            if failed_job is None:
                return job
            mark_job_failed(failed_job, str(exc))
            try:
                db.commit()
            except SQLAlchemyError:
                db.rollback()
            return failed_job
        return job

    def run_next_job(
        self,
        db: Session,
        *,
        project_id: str | None = None,
        job_types: set[str] | None = None,
    ) -> Job | None:
        eligible_job_types = set(self.handlers)
        if job_types is not None:
            eligible_job_types &= job_types
        if not eligible_job_types:
            return None
        try:
            job = acquire_next_job(db, worker_id=self.worker_id, job_types=eligible_job_types, project_id=project_id)
        except OperationalError:
            db.rollback()
            return None
        if job is None:
            return None
        return self.run_job(db, job)
