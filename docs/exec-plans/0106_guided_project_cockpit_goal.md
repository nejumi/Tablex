# Goal 0106: Guided Project Cockpit

## Objective

Reduce project-screen cognitive load while preserving Tablex's artifact-first harness model. The user should see one next action, one readable analysis surface, and one relationship map before raw shelves, debug artifacts, or long tables.

## Current Scope

- Make Agent Chat responses action-oriented:
  - Keep the assistant message human-readable.
  - Render `action_summary.next_step` as the primary in-chat control.
  - Show what changed and what needs review before secondary action chips.
- Keep Notebook reading spatially coherent:
  - Move the current Analysis Story preview directly below story controls.
  - Keep read order, story cards, caveats, and Codex prompts below the preview.
  - Keep notebook history and raw artifacts in supporting details.
- Improve Relational Preview:
  - Render structured JSON `relational_schema_hint` uploads as an ER-style graph.
  - Continue rendering `relational_catalog` as an ER-style graph.
  - Keep raw JSON available only as supporting detail.

## Design Rules

- Simplicity is not feature reduction; it is ordering. Put the next meaningful action before artifact shelves.
- Agent Chat is the universal command surface. Specialized buttons are shortcuts, not the only way to ask Tablex for work.
- Raw artifact ids, JSON, manifests, and lineage details are supporting evidence. They should not be the main response for humans.
- ER edges, uploaded diagrams, and inferred relationships are evidence, not confirmed join contracts.
- Notebook previews must be close to the action that opens them. Do not place the viewer far below unrelated tables.

## Validation Plan

- `npm run lint`
- `npm run build`
- Existing backend API tests covering Agent Chat routing and relational hint upload.
- Browser check for:
  - Agent Chat summary next-step control.
  - Notebook story preview immediately below the story hero.
  - Structured ER JSON hint rendering as a graph before raw JSON.

## Deferred

- True chat attachment ingestion from the project-level Agent Chat.
- Persisted per-user UI focus preferences.
- Full Codex-authored notebook execution and evidence ingestion.
- Richer ER layout for very large multi-table graphs.
