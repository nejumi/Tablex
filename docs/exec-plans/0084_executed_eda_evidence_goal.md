# Executed EDA Evidence v1 Goal

## Objective

Turn generated notebook artifacts from static scaffolds into readable, artifact-backed EDA evidence inside Tablex. The UI should make it obvious where the result appears after a user clicks an action, and Codex should help users navigate what to inspect next instead of exposing a raw artifact shelf.

## Current Scope

- Add controlled `notebook_evidence_bundle`, `notebook_evidence_html`, and `notebook_evidence_svg` artifacts during safe notebook execution capture.
- Render profile-backed SVG evidence without executing arbitrary marimo cells.
- Make the Data Understanding notebook review more like a human-readable EDA article:
  - analysis brief,
  - read-this-first order,
  - visual story cards,
  - EDA playbook,
  - feature family map,
  - Codex follow-up prompts.
- Move the Notebook tab result viewer next to the primary action so click target and response are spatially connected.
- Add an interactive Notebook guide that routes questions through harness-owned Agent Chat and returns notebook-specific reading guidance.
- Keep source notebooks, static review previews, profile-backed evidence, and future executed marimo output clearly separated.

## Deferred UX / Product Requests Captured

- Agent Chat should be the universal project-level command surface. Users should be able to ask for uploads, visualization, ER diagrams, notebook guidance, evaluation changes, or runner work in natural language without hunting for a specialized field. Specialized controls can remain as shortcuts, but the Agent should mediate between the user and the meta-harness by selecting the right safe harness action, asking focused follow-up questions only when useful, and recording assumptions when the user does not answer.
- Deprecated: do not add natural-language intent routing. Use explicit controls or future schema-validated proposals for:
  - dataset or ER diagram upload guidance,
  - relational ER visualization requests,
  - chart/visualization generation requests,
  - notebook reading and evidence-capture requests,
  - safe artifact preview/open actions.
- Relational Preview should not default to raw JSON for users. Add an ER diagram view derived from `relational_catalog` tables and inferred relationships.
- Add ER diagram upload/import:
  - accept image files such as PNG/JPEG/SVG/PDF and structured diagram exports where possible,
  - register them as artifacts,
  - optionally extract table/entity/relationship candidates into a `relational_schema_hint` asset,
  - keep original images visible in-product,
  - do not pass connector credentials or secrets into extraction prompts/runners.
- Relational feature planning should show a visual table graph first, with JSON available only as an advanced artifact.

## Quality Bar

- Do not claim a notebook was fully executed unless a controlled runner actually executed cells and captured outputs.
- Users should see a meaningful review immediately inside the workbench.
- The next action should be local and obvious: open review, capture evidence, inspect a figure, or ask Codex for targeted guidance.
- Notebook evidence must remain lineage-tracked and artifact-backed.
