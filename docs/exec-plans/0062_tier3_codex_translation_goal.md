# 0062 Tier3 Codex Translation Goal

## Goal

Add Tier3 translation affordances for Report and Artifact content. Tier3 content should remain English as the source of truth, while user-requested translations become explicit derived assets with lineage.

## Implementation Plan

- Add backend translation endpoints for artifacts and reports:
  - `POST /api/artifacts/{artifact_id}/translate`
  - `POST /api/reports/{report_id}/translate`
- Treat translation as a harness-owned Codex AgentTask, not as invisible UI-only text replacement.
- Store a `translate_tier3_content` Job for every translation request.
- Store an `agent_task_contract` artifact describing the Codex translation task.
- Store translated preview/report artifacts as derived assets and link them to the source artifact/report with lineage.
- Add Translate buttons to preview surfaces so the active LocalePack language can request an on-demand translation.

## Codex Boundary

Codex is the intended Tier3 translator runner. The current MVP creates a Codex-ready translation contract and a local draft/fallback artifact immediately. It does not silently execute Codex CLI from the UI button yet, because runner execution requires explicit sandbox, network, approval, credential, and artifact ingestion policy. The UI/API contract is shaped so `CodexCliRunner` can replace the fallback without changing the user-facing Translate button.

## In Scope

- Translation request API shape.
- Job, artifact, report, and lineage registration.
- Codex translation AgentTaskContract payloads.
- UI Translate button on preview surfaces.
- Local fallback draft for immediate self-contained preview.

## Out Of Scope

- Production-quality machine translation.
- Silent external API calls.
- Passing connector credentials or secrets to a translation runner.
- Mutating the original English report/artifact.
- Translating dataset values, column names, IDs, metric keys, JSON keys, or code blocks in a way that breaks traceability.

## Risks and Open Questions

- The local fallback is only a preview draft. Real translations should be produced by a configured Codex/LLM runner and marked with runner provenance.
- For non-Japanese dynamic locales, the MVP currently records a pending translation notice with the English source until a runner is configured.
- Translation review workflow and acceptance/rejection states should become first-class before using translated reports externally.
