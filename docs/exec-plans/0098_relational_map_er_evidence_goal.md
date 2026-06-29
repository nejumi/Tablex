# 0098 Relational Map and ER Evidence Goal

Date: 2026-06-30

## Goal

Make relational evidence understandable without asking users to read raw JSON. The Data tab should show an ER-style map or uploaded ER evidence first, keep raw catalogs secondary, and let Agent Chat route relationship-map requests to the right in-product surface.

## Implemented

- Added `/api/projects/{project_id}/relational/schema-hints/upload`.
- Accepted PNG, JPEG, SVG, PDF, and JSON ER/schema hints.
- Stored uploaded evidence as `relational_schema_hint` artifacts with metadata, report, Evidence, and lineage.
- Extended artifact preview so image/PDF ER evidence can be displayed in-product.
- Added Agent Chat intent routing for ER/relationship map requests.
- Reworked the Data tab into a single `Relational Map` surface with:
  - relationship evidence summary,
  - ER upload control,
  - inline ER/catalog/image/PDF preview,
  - guardrails,
  - supporting artifact tables behind details.

## Design Notes

- Uploaded ER diagrams are evidence, not executable join contracts.
- Relational feature work still requires confirmed join keys, cardinality, leakage review, prediction-time availability, EvaluationSpec, and SplitManifest discipline.
- Raw JSON remains available, but it is not the first thing a human has to inspect.

## Follow-Up

- Add optional OCR/vision extraction for uploaded diagram images through a controlled AgentTaskContract.
- Add structured ER diagram editing and confirmation workflow.
- Let Agent Chat accept "attach this ER diagram" once chat attachments are part of the product shell.
