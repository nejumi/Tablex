# 0070 Guided Journey Goal

## Goal

Reduce workbench cognitive load by adding a phase-aware Guided Journey surface. The journey should show where the project is, which phase is blocked/current/next/done, and how to open the relevant product surface without forcing a fixed modeling approach.

## Scope

- Extend `project_guidance.v1` with `journey_stages` and `current_stage_id`.
- Keep the single recommended focus as the primary attention budget.
- Add a compact frontend journey rail under Focus Guide across project tabs.
- Localize stable stage labels and statuses through the existing LocalePack mechanism.
- Preserve Codex flexibility: the Approach stage is a handoff readiness stage, not a fixed recipe selector.

## Implementation Notes

- Journey stages are derived from harness-owned state: DatasetSnapshots, understanding artifacts, high-risk assumptions, blocking questions, approved EvaluationSpecs, SplitManifests, Ideas/ResearchBriefs, successful runs, Reports, and VisualizationSpecs.
- Stage statuses are `done`, `current`, `next`, `blocked`, or `waiting`.
- Stage actions reuse the same `ProjectGuidanceAction` contract used by Focus Guide, so actions can navigate, call a harness endpoint, or create a scoped AgentTaskContract.
- The UI shows the journey as a compact rail with Tablee as a light guide, not as another dense dashboard.

## Deferred

- Persisted journey snapshot artifacts. The current endpoint is live decision support only.
- Per-stage rich explanations and localization from backend copy keys.
- User-customizable journey layouts for non-standard workflows such as target-after-aggregation or multi-table-only projects.

## Risks

- If too many stages become visually dominant, the rail can add cognitive load. Keep only the current stage explanation expanded.
- Backend summaries are currently English strings; stable labels/statuses are localized in the frontend, but richer summary localization should move to copy keys later.
