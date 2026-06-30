# Goal 0103: Notebook Follow-Up Task Bridge

## Intent

Deprecated direction: Notebook and Analysis Story follow-up prompts must not be keyword-routed into AgentTaskContracts. Use explicit controls or future schema-validated agent proposals instead of vague guidance or artifact-only replies.

## Why

Users ask Notebook surfaces for actions such as feature importance, calibration, slice review, or worst-example analysis. Those requests should become controlled Codex runner work with Tablex-owned evaluation constraints, artifacts, lineage, and reporting. The UI should stay simple: ask in the Notebook surface, then review the generated runner handoff in Approach.

## Implementation Scope

- Deprecated and removed: `plan_notebook_followup_task` natural-language intent detection for scoped Notebook and Analysis Story prompts.
- Added `notebook_followup_diagnostics` AgentTaskContract planning with source-aware objective text.
- Added required outputs for a follow-up marimo notebook, report, diagnostics JSON, evidence bundle, visualization spec, and figure manifest.
- Added quality checks that forbid invented feature importance, calibration, slice metrics, or worst examples when model or prediction artifacts are missing.
- Added notebook/run/diagnostics artifacts to planning context.
- Routed frontend Notebook follow-up prompts to task creation while leaving pure reading questions as interactive guidance.
- Added API coverage for the new intent, action, target anchor, and contract payload.

## Product Rules Preserved

- Codex remains a runner implementation, not the product controller.
- EvaluationSpec and SplitManifest are read-only constraints for follow-up diagnostics.
- Notebook output must be artifact-backed and useful inside Tablex UI.
- Missing evidence becomes an explicit evidence-gap report, not fake diagnostics.
- The user-facing path remains one action: Notebook question to Approach handoff.

## Deferred

- Automatic execution of the generated follow-up contract.
- Full ingestion of produced notebook follow-up results into the Analysis Story surface.
- Rich visualization rendering for every diagnostic type.
