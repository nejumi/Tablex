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
- Marked main-session-delivered Chat jobs as `waiting_for_agent` instead of runnable `queued` work so the main Codex session remains the response source; the job is completed when a Codex-authored `reports/chat_update.md` is registered.
- Updated the frontend so `waiting_for_agent` chat turns remain visibly active in Chat, use the Codex-delivery message returned by the backend, stay out of Research Plan task blocks, and show localized Jobs labels instead of raw status strings.
- Rendered HTML notebook previews from the preview API's inlined/reset HTML via `srcDoc` and added an explicit empty-preview warning so blank panels are distinguishable from loading or rendering.
- Added browser-download URLs for the main AgentSession raw stdout JSONL and stderr log so Raw can show a bounded tail while still giving direct access to the complete saved transcript files.
- Tightened Research Plan locale display so unlocalized Codex-authored block strings do not leak into non-English UI while the active session receives a display-language refresh request.
- Polished Japanese Home/Agent Workspace labels that remained fixed in English after the ResearchPlan locale pass, including workflow status chips, Mission Control status labels, focus action labels, target display, ResearchPlan download affordance, and Home skill tooltip leakage.
- Preserved the main AgentSession observation on paired Chat turns after a Codex-authored `reports/chat_update.md` answers a pending user instruction, so the saved Chat turn remains traceable back to Raw.
- Added a dedicated `tablex-agent-supervisor` process entrypoint and an API setting (`TABLEX_API_AGENT_SESSION_SUPERVISOR_ENABLED`) so Full Auto session recovery can be moved out of the FastAPI process when desired.
- Added an optional Compose stack that runs the API, sidecar worker, and dedicated AgentSession supervisor as separate processes sharing the same local `/data` volume.
- Kept Codex-authored Research Plan display locale-aware on the frontend by using the timeline API `response_locale` and absorbing Codex-authored aliases for the fixed upload/objective/understanding/prior-research anchors instead of showing duplicated English anchor blocks.
- Added structured Chat wait observations for delivered-to-main-session turns so the pending Chat card can show the last Codex output age, last Chat update age, whether a progress request has been sent, and raw transcript counts while still waiting for a Codex-authored `reports/chat_update.md`.
- Localized the floating Agent Activity rail title and minimize/expand affordance so the activity overlay no longer leaves fixed English control labels in Japanese UI.
- Localized high-visibility Insight / decision-report / Notebook Center shelves and table affordances so Japanese UI no longer drops back to English around the report reader and notebook surface.
- Hardened the floating Agent Activity rail so the same job/session is rendered as one card, cards without backend project names still show the current project, the live-work pill includes the visible card count, and `waiting_for_agent` remains visible as an active wait state instead of disappearing after the transient TTL.
- Hardened the backend Agent Activity contract so `waiting_for_agent` chat turns delivered to the main Codex session are active worker cards at the API level, not only a frontend interpretation.

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
| Raw transcript view must expose the actual saved Codex output, not only derived event cards | Implemented | `/agent-session/raw-transcript` now returns download URLs for full stdout JSONL and stderr log files; the Raw UI exposes those links while keeping the bounded parsed tail in view. |
| Agent Chat should not synchronously block on Codex response composition | Implemented for product path | `/agent-chat` creates an `agent_chat_turn` job and immediately returns a visible wait state; the local daemon processes concrete chat jobs and history replaces pending entries with persisted responses. |
| Chat should remember recent conversation | Implemented | `build_agent_conversation_context` includes recent `agent_chat_turn` artifacts; regression test covers a second turn seeing the first. |
| Main-session Chat updates should attach to the right user instruction | Implemented | Pairing now compares normalized UTC datetimes and has regression coverage for local-time strings that would sort incorrectly as raw strings. |
| Agent Chat pending state should not look like a dead worker when Codex already has the message | Implemented | Delivered-to-session chat turns now use human-facing "delivered to agent / next Codex reply will be saved" copy while keeping worker state in structured metadata. |
| Delivered Chat instructions should not be answered by a sidecar before main Codex replies | Implemented | Active-session chat jobs use `waiting_for_agent`, which is outside `RUNNABLE_STATUSES`, and are completed by `main_codex_session_chat_update`; regression coverage verifies the local worker skips them and the Codex-authored update pairs back to the same job. |
| Delivered Chat wait state should not leak as a raw job status in UI | Implemented | The frontend treats `waiting_for_agent` as an active Chat turn, renders localized status labels, suppresses those chat wait jobs from Research Plan blocks, and uses the backend's Codex-delivery message instead of a generic pending line. |
| Codex-authored marimo notebooks must not require fixed product markers | Implemented | Capture validation checks marimo structure rather than `Generated by Tablex` style markers. |
| Research Plan after anchors must be Codex-authored and locale-aware | Implemented with active follow-up | UI reads `research_plan.v1` `timeline_blocks`; non-English locales suppress unlocalized text and request Codex to refresh visible fields in the selected locale. |
| Home/ResearchPlan Japanese UI should not revert to fixed English labels around Codex-authored plan blocks | Implemented with browser evidence | Playwright Japanese Home snapshots verified localized workflow chips, mission action, target display, ResearchPlan summary/download affordance, and collapsed locale-refresh blocks. |
| Codex-added Research Plan blocks should respect the active display locale | Implemented with latest frontend fix | The frontend now uses `response_locale` from `/research-plan/timeline` for block/subtask display checks and suppresses duplicate Codex aliases for the fixed initial anchors. |
| Paired Agent Chat turns must remain traceable to Raw after the pending state is replaced | Implemented | The paired Chat history response now carries `agent_session_observation` in `response_brief`; regression coverage asserts the session id and observation schema persist after the Codex-authored update is paired. |
| Pending Chat turns should show whether Tablex has nudged Codex for a human-facing update | Implemented | Active Chat wait cards now include last Chat update age and progress-request-sent metadata from the backend `response_brief`, without generating a replacement natural-language answer in the harness. |
| Agent Activity should not duplicate or hide active/waiting work cards | Implemented | The frontend now deduplicates worker cards by job/session identity, preserves richer telemetry while merging duplicates, fills the current project name when missing, and treats `waiting_for_agent` as an active wait state. |
| Main-session Chat waits should stay visible in Agent Activity | Implemented | `job_active_for_activity` now treats `waiting_for_agent` as active, and the active-session chat regression asserts `/agent-activity` returns the waiting chat job as an active worker and increments `active_count`. |
| Chat/Raw latest-log visibility must be predictable | Implemented in UI | Chat and Raw sticky-bottom scroll state resets per project/session while preserving manual scroll-up within the same view. |
| Long-running Codex turns should still be prompted to explain progress | Implemented with non-blocking nudge | The supervisor now writes `.tablex/inbox/progress_request.md` during active Codex turns when the latest Codex-authored Chat update is stale; tests verify project locale and no browser polling dependency. |
| Notebook preview state should not look blank or broken while rendering | Implemented in UI | HTML/SVG preview iframes now show localized loading and slow-render states before `onLoad`, with the existing open-original fallback still available. |
| Notebook preview should not depend on a second iframe fetch for already-prepared HTML | Implemented in UI | Non-truncated HTML previews now render the API-provided inlined/reset HTML through `srcDoc`; empty previews show a visible warning and source/original fallbacks. |
| A supervisor can run out-of-process instead of depending on the API or generic worker | Implemented as an operator entrypoint and local Compose stack | `tablex-agent-supervisor` runs only AgentSession recovery/continuation. API-side supervisor startup can be disabled with `TABLEX_API_AGENT_SESSION_SUPERVISOR_ENABLED=false`, while the DB lease still prevents duplicate ownership. `docker-compose.yml` wires API, sidecar worker, and supervisor as separate local processes. |

## Deferred Scope

- Do not prune historical duplicate artifacts automatically. Existing projects may still contain large artifact histories from older naming behavior; deletion or compaction needs an explicit maintenance command and user approval.
- systemd/supervisord unit files remain future work. Docker Compose wiring is present for local split-process operation.
- Full browser UX review remains necessary for end-to-end Notebook rendering and Activity overlay behavior under live running workloads. Chat/Raw and Research Plan Japanese rendering now have Firefox Playwright evidence for the inspected project.
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
- Playwright CLI Japanese Home snapshot for `#/projects/p_9f25dd620d8c` after locale polish
- Live checks after restart:
  - `curl http://127.0.0.1:8000/health`
  - `curl http://127.0.0.1:8000/healthz`
- 2026-07-04 follow-up:
  - `npm run lint` in `apps/frontend`
  - `npm run build` in `apps/frontend`
  - `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_agent_chat_writes_active_session_instruction_to_workspace_inbox apps/backend/tests/test_api_flow.py::test_agent_chat_history_pairs_main_session_update_to_delivered_instruction apps/backend/tests/test_api_flow.py::test_agent_chat_history_pairs_each_main_session_update_once -q`
  - `git diff --check`
  - Playwright CLI Firefox browser check for `#/projects/p_9f25dd620d8c` with `tablex.userSettings.v1.locale=ja-JP`.
  - Verified the Japanese Home snapshot renders localized project status chips, Mission Control, Research Plan anchors, collapsed display-language refresh block for unlocalized Codex-added plan blocks, Chat input-ready state, and Raw stdout/stderr download links plus JSONL tail.
  - Verified the Japanese Insight snapshot renders localized decision report labels, evidence reader action labels, supporting report shelf controls, Notebook Center empty state, and lower report/notebook shelf empty states.
  - Saved visual evidence outside git at `output/playwright/fable-hardening-chat-ja-firefox.png`, `output/playwright/fable-hardening-raw-ja-firefox.png`, and `output/playwright/fable-hardening-insight-ja-firefox.png`.
  - Console error check reported 0 browser errors.
  - Activity overlay follow-up: `npm run lint`, `npm run build`, `curl http://127.0.0.1:8000/health`, Playwright Firefox reload for `#/projects/p_9f25dd620d8c`, and console error check reported 0 browser errors.
  - Backend Activity contract follow-up: `.venv/bin/pytest apps/backend/tests/test_api_flow.py::test_agent_chat_writes_active_session_instruction_to_workspace_inbox apps/backend/tests/test_api_flow.py::test_agent_activity_turn_state_waits_for_user_when_no_agent_work_is_observed apps/backend/tests/test_api_flow.py::test_agent_activity_does_not_show_future_autonomous_heartbeat_as_active -q`, `.venv/bin/ruff check apps/backend`, `npm run lint`, and `npm run build`.
