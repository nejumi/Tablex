# Approach Studio Goal

## Goal

Move Tablex beyond a fixed-baseline workflow by adding a harness-guided but approach-flexible planning layer. The harness should guide the data science flow, own evaluation and artifacts, and let AgentRunner implementations propose, research, implement, and report approaches through explicit contracts.

## Implemented Scope

- Added `ResearchBrief` model and APIs.
- Added `Idea` model as the first Approach Candidate object.
- Added `Report` model and draft report APIs.
- Added `VisualizationSpec` model and generation APIs.
- Added synchronous Job types:
  - `generate_research_brief`
  - `generate_approach_candidates`
  - `draft_project_report`
  - `create_visualization_spec`
- Added artifact outputs:
  - `research_brief`
  - `approach_candidate`
  - `report`
  - `visualization_spec`
- Added lineage edges from dataset/evaluation context to research briefs, from briefs to ideas, and from reports/visualizations to artifacts.
- Added AgentTaskContract payloads to Ideas, including:
  - approved EvaluationSpec and SplitManifest requirements
  - allowed research modes: project artifacts, Skill library, controlled web search
  - forbidden actions for secrets, credentials, target leakage, and destructive evaluation changes
  - required report, feature recipe, metrics, and visualization outputs
- Added Approach tab to the UI.
- Added Reports tab with report listings and a simple visualization-spec preview.
- Extended API integration tests for ResearchBrief, Idea, Report, VisualizationSpec, artifact preview, and job outputs.

## Design Decision

Approach generation is intentionally a planning and contract layer in this milestone. It does not hard-code a new model recipe and does not pretend that web research has already happened. Instead, it creates explicit, artifact-backed tasks that a future Codex/Skill/web-search runner can execute while the harness keeps control over evaluation, lineage, safety, and reporting.

## Deferred Scope

- Real web/literature search execution with citations.
- Skill registry and Skill selection UI.
- AgentRunner execution from an Idea.
- Human approval workflow for Ideas before execution.
- Rich visualization rendering and artifact-specific report pages.
- Report publishing/export.

## Risks And Open Decisions

- Current ResearchBrief sources include placeholders for future Skill and web research. External claims must not be treated as verified until a runner stores citations as Evidence or artifacts.
- VisualizationSpec uses a small internal JSON format. It may later need a formal schema or compatibility with Vega-Lite, Plotly, or another portable spec.
- Ideas may duplicate if generation is run repeatedly. A later version should add deduplication and status transitions.
