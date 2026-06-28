# 0044 Controlled Research Runner Stub Goal

## Goal

Move Research Source Packs from static handoff artifacts toward a controlled ResearchTask execution contract. The milestone should keep real web/literature retrieval disabled while proving that Tablex can run a dedicated research runner, store findings and citation artifacts, and trace them independently from AgentTask execution.

## Implementation

- Added `services/research_runner.py`.
- Added `run_research_source_pack_stub` job type.
- Added `POST /api/research-source-packs/{artifact_id}/run-local-stub`.
- The endpoint validates `research_source_pack.v1` and creates:
  - `research_run_manifest`
  - `research_findings_report` artifact and Report record
  - `source_citation_manifest`
  - `visualization_spec` and VisualizationSpec record
  - Evidence
  - Lineage from job, Research Source Pack, manifest, report, citation manifest, visualization, and Evidence
- The LocalStubResearchRunner records `external_network_accessed=false` and `connector_credentials_materialized=false`.
- The Approach UI can run the controlled research stub from Research Source Pack rows and preview the findings report.

## Validation Plan

- Extend the API flow test to execute a Research Source Pack local stub and preview the findings report.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for source pack stub execution.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a project in the container, generated a Research Source Pack, ran the controlled research local stub, downloaded `research_run_manifest`, and previewed `research_findings_report`.

## Deferred

- Real controlled network retrieval.
- Search result ranking, source deduplication, and citation verification.
- Human approval gates for enabling network access.
- Direct promotion of research findings into approach Ideas; current output is stored as artifacts, Evidence, Report, VisualizationSpec, and Lineage.
