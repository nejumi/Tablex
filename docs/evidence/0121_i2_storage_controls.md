# 0121 Workstream I2 Storage Controls Evidence

Date: 2026-07-08

## Scope

Implemented the first storage-control layer for the 0121 audit response:

- Reuse an existing artifact record when the same project, asset type, artifact name, and content hash are registered again.
- Add a retention-based artifact garbage-collection dry-run planner that protects dataset, evaluation, split, model, pilot, lineage, and Research Plan references.
- Add local storage usage reporting grouped by data, registered artifacts, workspaces, pipeline environments, marimo sessions, and metadata.
- Add a local admin dry-run GC API that records the report as an artifact.
- Add periodic worker cleanup for temporary pipeline environments, stale marimo workdirs, and old request ack files.
- Show storage usage from the settings panel without introducing a destructive UI control.

## Live Local Data Observation

Command:

```bash
du -sh data apps/backend/data
```

Result:

```text
79G data
9.0G apps/backend/data
```

Storage hot spots observed with `du -sh`:

```text
73G data/artifacts
272M data/metadata
3.2G data/_pipeline_envs
688K data/marimo_sessions
8.6G apps/backend/data/artifacts
100M apps/backend/data/metadata
360M apps/backend/data/_pipeline_envs
672K apps/backend/data/marimo_sessions
```

Dry-run artifact GC summary against `data/metadata/app.db` with retention 5:

```json
{
  "dry_run": true,
  "retention": 5,
  "candidate_count": 196,
  "reclaimable_bytes": 164915379,
  "protected_count": 10680
}
```

The dry-run deliberately identifies only unprotected old versions. The large project data and active lineage-linked artifacts remain protected.

## Verification

Syntax and lint:

```bash
.venv/bin/python -m py_compile apps/backend/tabular_harness/services/storage_management.py apps/backend/tabular_harness/services/artifacts.py apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/worker/daemon.py apps/backend/tests/test_storage_management.py apps/backend/tests/test_api_flow.py
.venv/bin/ruff check apps/backend/tabular_harness/services/storage_management.py apps/backend/tabular_harness/services/artifacts.py apps/backend/tabular_harness/api/routes.py apps/backend/tabular_harness/worker/daemon.py apps/backend/tests/test_storage_management.py apps/backend/tests/test_api_flow.py
```

Result:

```text
All checks passed!
```

Targeted backend tests:

```bash
.venv/bin/python -m pytest apps/backend/tests/test_storage_management.py apps/backend/tests/test_api_flow.py::test_admin_storage_usage_api_returns_categories apps/backend/tests/test_api_flow.py::test_admin_storage_gc_api_registers_dry_run_report -q
```

Result:

```text
5 passed, 1 warning in 3.69s
```

Full backend tests:

```bash
.venv/bin/python -m pytest apps/backend/tests -q
```

Result:

```text
446 passed, 6 warnings in 147.37s
```

Frontend build:

```bash
cd apps/frontend && npm run build
```

Result:

```text
✓ built in 343ms
```
