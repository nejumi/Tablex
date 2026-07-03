# 0118 Full Auto Supervisor Hardening Goal

## Goal

Make the main Full Auto Codex session harder to lose, easier to observe, and less likely to degrade into silent stops or opaque pending states.

## Context Read

- `AGENTS.md`
- `docs/agent_interface_spec.md`
- `apps/backend/tabular_harness/services/agent_sessions.py`
- `apps/backend/tabular_harness/services/agent_chat.py`
- `apps/backend/tabular_harness/services/agent_response_composer.py`
- `apps/backend/tabular_harness/services/analysis_notebooks.py`
- `apps/backend/tabular_harness/api/routes.py`
- `apps/backend/tests/test_agent_sessions.py`
- `apps/backend/tests/test_api_flow.py`

## Implemented Scope

- Removed the misleading product-generated notebook validation name and `is_tablex_generated` flag. Notebook capture eligibility is based on marimo structure, not fixed Tablex prose or markers.
- Added a regression test that Codex-authored marimo notebooks do not require product markers.
- Added artifact query indexes for large local workspaces in the prior milestone and verified existing SQLite index creation.
- Changed Codex CLI turn streaming so stdout/stderr are written first to workspace raw transcript files, while Tablex tails those files into transcript events. This reduces pipe-loss risk and keeps Raw grounded in the saved runner output.
- Added fake-Codex tests covering file-backed stdout/stderr, transcript event ingestion, thread id capture, and process-exit recording.
- Confirmed user chat instructions are delivered by undelivered event index, not by a small recent-log window.
- Added a regression test ensuring Chat response briefs include recent conversation turns.
- Added `/health` as a public alias for `/healthz` and updated Vite proxy/docs.

## Deferred Scope

- Do not prune historical duplicate artifacts automatically. Existing projects may still contain large artifact histories from older naming behavior; deletion or compaction needs an explicit maintenance command and user approval.
- A dedicated out-of-process supervisor/worker remains a future improvement. The current implementation is still in-process, but startup recovery and file-backed Raw transcripts reduce the worst reload failure modes.
- Full browser UX review remains necessary for Chat/Raw rendering, Research Plan centering, Notebook viewer affordance, and Activity overlay behavior.

## Risks

- File-backed stdout/stderr depends on Codex CLI flushing JSONL promptly. The final drain captures output at process exit, but live UI updates could lag if the CLI buffers heavily.
- Historical sessions still contain old transcript/artifact records and may not visually represent the improved path until new turns run.
- `apps/frontend/src/main.tsx` remains very large and risky to edit. Future UI work should extract components deliberately instead of continuing broad edits in one file.

## Verification

- `.venv/bin/pytest apps/backend/tests -q`
- `.venv/bin/ruff check apps/backend`
- `npm run lint`
- `npm run build`
- Live checks after restart:
  - `curl http://127.0.0.1:8000/health`
  - `curl http://127.0.0.1:8000/healthz`
