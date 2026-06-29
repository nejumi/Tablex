# 0066 Adaptive Strategy Brief Goal

## Goal

Add a harness-owned Adaptive Strategy Brief that guides the next modeling or Codex handoff step without turning Tablex into a fixed recipe executor.

## Rationale

The project already has ResearchPlan, ResearchSourcePack, ResearchSynthesis, Approach Ideas, AgentTaskContracts, baseline strategy plans, reports, and visualization specs. The user experience still needs one low-cognitive-load surface that explains:

- what the harness thinks should happen next
- why that step matters
- which artifacts support the recommendation
- how Codex may use open-ended reasoning while respecting evaluation and safety contracts

## Implementation Plan

- Add `adaptive_strategy_brief.v1` JSON schema.
- Add a backend service that builds a brief from the latest project state:
  - DatasetSnapshot
  - EvaluationSpec and SplitManifest
  - Assumptions and Questions
  - research artifacts
  - baseline strategy artifacts
  - AgentTaskContracts and Ideas
  - reports and visualization specs
- Add `GET /api/projects/{project_id}/approach/strategy-brief` for live guidance.
- Add `POST /api/projects/{project_id}/approach/strategy-brief` to materialize:
  - `adaptive_strategy_brief` JSON artifact
  - `adaptive_strategy_report` Markdown artifact and Report row
  - `visualization_spec` artifact and VisualizationSpec row
- Connect lineage from source artifacts to the brief/report/visualization.
- Add backend unit and API integration coverage.
- Add the Strategy Brief to the Approach tab as the first visible decision surface.

## Design Choices

- No new DB table in this milestone. Strategy Brief is artifact-first and derived from existing first-class objects.
- Baseline strategies remain advisory evidence, not mandatory recipes.
- Codex handoff explicitly allows proposing or rejecting approach classes while preserving:
  - EvaluationSpec
  - SplitManifest
  - artifact registration
  - approach decision trace
  - report and visualization outputs
  - secret and connector-credential boundaries
- Target selection is not forced at project creation. When no target exists, the recommended action becomes a Codex-assisted target-definition review after data understanding.

## Out Of Scope

- Real Codex execution.
- External web/literature retrieval from this endpoint.
- Approval workflow for adopting a Strategy Brief.
- Rich chart rendering beyond the portable VisualizationSpec payload.

## Risks and Open Questions

- The brief is heuristic and should become more evidence-weighted as real projects accumulate artifacts.
- UI should avoid becoming another dense dashboard; the top card should show only one recommended action and a small lane strip.
- The schema must stay open enough for future Skill and research-runner inputs.
