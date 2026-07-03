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
- Added supervisor-side progress-update nudging during Codex CLI turns. This writes `.tablex/inbox/progress_request.md` in the user's locale when the human-facing Chat update is stale, without interrupting Codex or depending on an open browser.
- Added Notebook HTML preview loading and slow-render states so a marimo/HTML preview no longer looks like a silent blank panel while the iframe is opening.
- Hardened Agent Chat history pairing so user instructions are matched to main-session progress updates by normalized datetime ordering, not raw timestamp string comparison.
- Changed queued Agent Chat copy so messages delivered to the main Codex session say that the agent has the instruction and the next Codex reply will be saved, rather than leading with worker-waiting implementation language.

## 2026-07-04 Fable Feedback Audit

| Fable item | Current status | Evidence |
| --- | --- | --- |
| Startup recovery must not depend on an open browser | Implemented | FastAPI lifespan and the local worker daemon call `start_active_main_session_supervisors`; `test_startup_supervisor_recovers_full_auto_project_without_browser_polling` and worker-daemon recovery tests cover this. |
| Unmonitored Codex PIDs after restart must not suspend Full Auto forever | Implemented | Supervisor marks stale stored PIDs as `between_turns`, clears the PID, records `stale_runner_process_recovered`, and resumes the same session. |
| Runner failure must not hot-loop | Implemented | `runner_unavailable` and non-zero exits schedule bounded retry delays via `retry_delay_seconds`; tests cover retry counting without sidecar-event inflation. |
| Idle timeout must not repeatedly SIGTERM the same process | Implemented | Streaming loop tracks `timeout_sent`, `cancel_sent`, and `terminated_at`, sends terminate once, then kills after a grace period if needed. |
| User chat instructions must not fall out of a recent-event window | Implemented | `undelivered_user_instruction_events` uses the last delivered user event index; the prompt includes all undelivered instructions and then records delivery. |
| Workspace artifact ingestion must avoid stem-only name collisions | Implemented | Session output artifact names include sanitized workspace-relative paths; regression coverage prevents alternating `summary.md` collisions. |
| Raw transcript storage must scale beyond small logs | Implemented for current Raw/Chat path | `(session_id, event_index)` indexes exist, stream events are batched, the transcript API supports `since_index`, and the Home activity poll uses that delta path after the initial load. The Raw file viewer separately reads bounded stdout/stderr tails. |
| Agent Chat should not synchronously block on Codex response composition | Implemented for product path | `/agent-chat` creates an `agent_chat_turn` job and immediately returns a visible wait state; the local daemon processes concrete chat jobs and history replaces pending entries with persisted responses. |
| Chat should remember recent conversation | Implemented | `build_agent_conversation_context` includes recent `agent_chat_turn` artifacts; regression test covers a second turn seeing the first. |
| Main-session Chat updates should attach to the right user instruction | Implemented | Pairing now compares normalized UTC datetimes and has regression coverage for local-time strings that would sort incorrectly as raw strings. |
| Agent Chat pending state should not look like a dead worker when Codex already has the message | Implemented | Delivered-to-session chat turns now use human-facing "delivered to agent / next Codex reply will be saved" copy while keeping worker state in structured metadata. |
| Codex-authored marimo notebooks must not require fixed product markers | Implemented | Capture validation checks marimo structure rather than `Generated by Tablex` style markers. |
| Research Plan after anchors must be Codex-authored and locale-aware | Implemented with active follow-up | UI reads `research_plan.v1` `timeline_blocks`; non-English locales suppress unlocalized text and request Codex to refresh visible fields in the selected locale. |
| Chat/Raw latest-log visibility must be predictable | Implemented in UI | Chat and Raw sticky-bottom scroll state resets per project/session while preserving manual scroll-up within the same view. |
| Long-running Codex turns should still be prompted to explain progress | Implemented with non-blocking nudge | The supervisor now writes `.tablex/inbox/progress_request.md` during active Codex turns when the latest Codex-authored Chat update is stale; tests verify project locale and no browser polling dependency. |
| Notebook preview state should not look blank or broken while rendering | Implemented in UI | HTML/SVG preview iframes now show localized loading and slow-render states before `onLoad`, with the existing open-original fallback still available. |

## Deferred Scope

- Do not prune historical duplicate artifacts automatically. Existing projects may still contain large artifact histories from older naming behavior; deletion or compaction needs an explicit maintenance command and user approval.
- A dedicated out-of-process supervisor/worker remains a future improvement. The current implementation is still in-process, but startup recovery and file-backed Raw transcripts reduce the worst reload failure modes.
- Full browser UX review remains necessary for Chat/Raw rendering, Research Plan centering, end-to-end Notebook rendering, and Activity overlay behavior.
- Chat quality still depends on Codex honoring `reports/chat_update.md` at a useful cadence. The harness now requests those updates from the supervisor path as well as user/chat/activity paths, but real long-running sessions should be observed to confirm the cadence feels natural.
- The product still has large frontend/backend files (`main.tsx`, `routes.py`, `analysis_notebooks.py`). Future edits should reduce risk through extraction rather than broad, unrelated edits.

## Risks

- File-backed stdout/stderr depends on Codex CLI flushing JSONL promptly. The final drain captures output at process exit, but live UI updates could lag if the CLI buffers heavily.
- The Home Raw view intentionally keeps only the recent indexed event window in React state while raw stdout/stderr tail remains available from workspace files. This is the right default for local scale, but a future dedicated transcript viewer may need virtualized history pagination.
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
