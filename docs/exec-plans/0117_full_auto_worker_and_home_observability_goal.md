# 0117 Full Auto Worker and Home Observability Goal

## Context

Claude Fable's review identified structural reasons Full Auto felt like whack-a-mole: worker lifecycle gaps, fake stub success paths, transcript scaling risk, and UI surfaces that could say "Full Auto is on" without showing what Codex was actually doing. The product rule remains unchanged: Tablex must not place walls or steps in Codex's path. It should run beside Codex, register outputs, expose Raw transcript, and explain progress to humans.

## Implemented

- Product worker paths now use concrete handlers only.
  - Local worker daemon, `/api/worker/run-once`, `/api/jobs/{job_id}/run`, and `tablex-worker` do not use generic MVP stub handlers.
  - Jobs without concrete handlers remain queued instead of receiving fake success.
- Agent chat pending replacement is covered by a daemon regression test.
  - A queued chat turn must be replaced by a persisted `agent_chat_turn` artifact in history.
  - The history must not stay stuck at the pending "preparing response" copy.
- Added Alembic migration `0002_agent_transcript_event_indexes`.
  - Ensures existing SQLite DBs get transcript indexes used by long-running Raw/Codex transcript polling.
- Home Research Plan no longer invents observed Codex blocks inside the plan.
  - Codex-authored or ResearchPlan-tool-authored nodes are the canonical timeline once a plan exists.
  - Runner/process presence is shown in Agent Activity and turn-state surfaces, not as a synthetic plan node.
- Project selection is persisted in the URL hash.
  - `#/projects/{project_id}` opens the project Home directly.
  - Reloading or sharing the URL no longer drops the user back to the portal.
- Home Ideas & Findings now prioritizes actionable items over generic autonomous-loop reflections.
- Mission Control uses the active Research Plan block when there is one, so the hero reflects current work instead of stale guidance.
- Removed user-visible maker wording in the Agent Activity token estimate label.

## Validation

- `pytest apps/backend/tests -q` -> 128 passed.
- `ruff check` on touched backend files -> passed.
- `npm run lint` -> passed.
- `npm run build` -> passed.
- Playwright CLI manual checks:
  - Direct `#/projects/p_9f25dd620d8c` route opens project Home.
  - F5 keeps the same project selected.
  - Research Plan shows only authored/canonical plan nodes, while Agent Activity shows whether the main Codex session is active.
  - Mission Control headline switches to active work.
  - Ideas & Findings top cards prioritize evaluation readiness, assumption risk, and concrete ideas.

## Remaining Risks

- The active `test5` project still has Codex-authored plan content with many completed blocks. The horizontal timeline is functional, but further visual compression may be needed.
- Chat quality now depends on Codex-authored `reports/chat_update.md` cadence. The prompt and ingestion path exist, but long stalls still need continued observation under real runs.
- Generic historical LocalStub APIs remain for explicit contract validation paths. They must stay clearly marked as non-executed/non-scoring and must not be used by product autoplay.
