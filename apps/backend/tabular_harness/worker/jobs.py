from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from tabular_harness.core.json import loads_json
from tabular_harness.models.entities import Job
from tabular_harness.services.jobs import JOB_TYPES
from tabular_harness.worker.runner import JobHandler, SyncWorker

INITIAL_JOB_TYPES = tuple(sorted(JOB_TYPES))


def stub_job_handler(db: Session, job: Job) -> dict[str, Any]:
    del db
    return {
        "message": "Queued job processed by SyncWorker stub handler.",
        "job_type": job.job_type,
        "input": loads_json(job.input_json, {}),
        "context": loads_json(job.context_json, {}),
        "policy": loads_json(job.policy_json, {}),
        "attempt_count": job.attempt_count,
    }


def default_handlers() -> dict[str, JobHandler]:
    return {job_type: stub_job_handler for job_type in JOB_TYPES}


def create_default_worker(worker_id: str = "local-worker") -> SyncWorker:
    return SyncWorker(handlers=default_handlers(), worker_id=worker_id)
