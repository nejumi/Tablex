# 0064 Project Guidance API Goal

## Goal

Move next-focus decision support from frontend-only heuristics into a harness-owned Project Guidance API.

## Rationale

The previous Focus Guide reduced cognitive load, but the decision rules lived in the UI. That makes the browser a hidden workflow owner. The harness should own project state interpretation because it owns artifacts, assumptions, evaluation design, jobs, reports, lineage, and AgentRunner boundaries.

## Implementation

- Added `ProjectGuidanceRead` response schema with:
  - `recommended_focus`
  - `primary_action`
  - `secondary_actions`
  - `state_summary`
  - `supporting_counts`
  - `hidden_detail_groups`
  - `agent_guidance`
- Added `GET /api/projects/{project_id}/guidance`.
- Added `project_guidance.v1` service logic that recommends one primary focus:
  - Data upload when no DatasetSnapshot exists.
  - Data understanding when no understanding report exists.
  - Assumptions when high-risk assumptions or blocking questions remain.
  - Evaluation when no approved EvaluationSpec or SplitManifest exists.
  - Approach when evaluation context exists but no successful run exists.
  - Reports when runs exist but decision reporting is missing or ready to review.
- Kept Approach guidance flexible by returning scoped AgentTask prompts instead of forcing a fixed baseline recipe.
- Updated the frontend Focus Guide to use the guidance API first and local fallback only when guidance is unavailable.
- Primary guide actions can navigate, run a safe harness endpoint, or create a scoped AgentTaskContract.

## UX Constraints

- The UI should still show one primary recommendation, not a full decision tree.
- Supporting counts and raw tables remain behind collapsed detail surfaces.
- Signals are visually capped so the guide does not become another dashboard.

## Out Of Scope

- Persisting guidance snapshots as artifacts on every read.
- User-dismissed or accepted focus memory.
- Fully localized backend guidance action labels.
- Agent-generated coaching text.

## Risks and Open Questions

- Current focus rules are deterministic and may over-prioritize high-risk assumptions that have already been consciously accepted.
- Guidance should eventually consider user intent, dismissed recommendations, and report readiness score.
- Explicit guidance snapshot artifacts may be useful for audit trails, but should be user-triggered to avoid artifact noise.
