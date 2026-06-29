# 0094 Portal Recent Updates Humanization Goal

## Goal

Make the cross-project Portal feel like a product dashboard, not an artifact table. Recent Updates should tell humans what happened in plain language while retaining lineage references for inspection.

## Implemented Scope

- Added backend human-readable labels for common job and artifact update types.
- Suppressed noisy `agent_chat_turn` artifacts from the visible update list; the corresponding job event remains visible as an agent-chat activity.
- Kept project routing, target tabs, artifact payloads, and `lineage_ref` metadata.
- Added regression coverage so raw `agent_chat_turn` identifiers do not leak into Portal update titles or summaries.
- Documented the first-viewport rule in `docs/dev.md`.

## Design Notes

- Portal titles are user-facing activity labels.
- Internal identifiers remain useful, but they should be secondary lineage metadata.
- The portal should bias toward team-readable signal, not exhaustiveness.

## Deferred

- Per-update icons and grouped timelines.
- Filtering by project, asset type, or runner.
- A dedicated detail drawer for lineage refs.
