# 0041 Research Source Pack Goal

## Goal

Create a harness-owned source pack between ResearchPlan and runner execution. The pack should let a future Codex, Skill, or controlled web/literature runner use timely sources without making external research invisible to the product. It must preserve Tablex's evaluation-first flow, avoid connector credentials, and hand source policy into AgentTaskContracts without hard-coding a modeling recipe.

## Implementation

- Added `services/research_sources.py`.
- Added `create_research_source_pack` job type.
- Added `POST /api/projects/{project_id}/approach/research-source-pack`.
- The endpoint creates:
  - `research_source_pack` JSON artifact
  - `research_source_report` Markdown artifact and Report record
  - Evidence record
  - Lineage from ResearchPlan, context artifacts, library assets, benchmark source cards, report, and job
- The pack includes:
  - latest ResearchPlan reference, creating one if needed
  - controlled query candidates
  - project artifact source candidates
  - recommended cross-project Skill/FeatureRecipe/EvaluationPattern/VisualizationTemplate sources
  - benchmark source-card candidates
  - citation requirements
  - freshness expectations
  - network and credential policy
  - runner handoff notes
- AgentTaskContract planning inputs now include the latest source pack policy, citation requirements, freshness expectations, and artifact id.
- The Approach UI can generate, preview, and download Research Source Packs and reports.

## Validation Plan

- Extend the API flow test to generate a Research Source Pack, preview the report, and assert the subsequent AgentTaskContract carries the source pack policy.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for the source-pack endpoint.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a project in the container, seeded default assets, generated a Research Source Pack, and previewed the Markdown source report.

## Deferred

- Real network search execution.
- Literature retrieval, ranking, and citation verification beyond source policy and required fields.
- Runner-produced source ingestion into the pack after Codex execution.
- Human approval workflow for treating external claims as decision-grade Evidence.
