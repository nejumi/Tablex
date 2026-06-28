# Job Orchestration & Approval Gates Goal

## Goal

Move the MVP from only synchronous request handlers toward harness-owned job orchestration. The first version should preserve existing synchronous product endpoints while adding queued jobs, approval gates, dependencies, retries, cancellation, and a local worker entrypoint.

## Implemented

- Extended `Job` metadata with:
  - `priority`
  - `attempt_count`
  - `max_attempts`
  - `context_json`
  - `policy_json`
  - `dependency_job_ids_json`
  - `approval_required`
  - `approved_by` / `approved_at`
  - `cancelled_by`
  - `run_after`
  - `locked_by` / `locked_at`
- Added lightweight SQLite schema sync for these MVP columns so existing local DBs can restart safely.
- Extended `JobCreate` and `JobRead` schemas.
- Changed generic `POST /api/jobs` to enqueue jobs rather than immediately mark them succeeded.
- Added approval, cancel, retry, and worker-run endpoints:
  - `POST /api/jobs/{job_id}/approve`
  - `POST /api/jobs/{job_id}/cancel`
  - `POST /api/jobs/{job_id}/retry`
  - `POST /api/worker/run-once`
- Added safety gating:
  - `run_agent_task` requires approval.
  - restricted/full network policies require approval.
  - production-write policies require approval.
- Extended worker runner with `run_next_job`.
- Added default MVP stub handlers for generic queued jobs.
- Added CLI entrypoint:
  - `tablex-worker --once`
  - `tablex-worker --interval 2 --worker-id local-worker`
- Extended Jobs tab with:
  - worker run-once button
  - approve/cancel/retry actions
  - attempts, priority, dependency, policy, input, and output display
- Extended integration tests for approval gates, dependency ordering, worker execution, cancellation, and retry.

## Deferred

- Real async handlers for each feature job type.
- Durable lock expiry and heartbeat.
- Multi-worker race protection beyond SQLite MVP behavior.
- Job event logs and live UI updates.
- Approval roles, comments, and audit policy beyond local-user stub.
- Scheduled recurring jobs.

## Risks And Open Decisions

- Generic queued jobs currently use stub handlers. Product-specific synchronous endpoints still run real work immediately.
- Approval gates are policy-driven but local-user only. Real auth/RBAC must be added before sensitive external execution.
- SQLite is sufficient for this MVP, but production-grade concurrent worker semantics will require stricter locking and migrations.
