# 0042 Cited Agent Evidence Ingestion Goal

## Goal

Close the loop between Research Source Packs and runner outputs. A future Codex, Skill, or controlled web/literature runner should be able to return source summaries and citations in AgentResult, and Tablex should store, audit, display, and trace those citations without relying on an external dashboard.

## Implementation

- Extended `schemas/agent_result.schema.json` and the Pydantic `AgentResult` model with optional:
  - `evidence_sources`
  - `citations`
  - `report_citations`
- Extended LocalStubAgentRunner to write:
  - `source_citation_manifest.json`
  - `citation_audit_report.md`
  - `citation_visualization_spec.json`
- LocalStub still does not execute Codex, web search, literature retrieval, model training, or scoring. Its citation audit records source policy compliance only.
- Extended AgentResult ingestion to create or register:
  - `source_citation_manifest` artifact
  - `citation_audit_report` artifact and Report record
  - citation Evidence
  - citation-audit VisualizationSpec
  - Lineage from AgentTask source, Research Source Pack, job, manifest, report, evidence, visualization, and ExperimentRun when present
- Planned AgentTask and Idea AgentTask job outputs now expose citation manifest/report/evidence/visualization ids.
- Reports and visualization surfaces can preview citation audit reports and citation-audit stage tables through existing UI paths.

## Validation Plan

- Update the API flow test so planned and Idea LocalStub runs ingest citation manifest/report/evidence/visualization outputs.
- Validate AgentResult schema compatibility with Noop and LocalStub runner tests.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for LocalStub citation ingestion.

## Validation Completed

- `python3 -m json.tool schemas/agent_result.schema.json >/dev/null`
- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a fixture-backed project in the container, generated a Research Source Pack and AgentTaskContract, ran LocalStub, downloaded `source_citation_manifest`, and previewed `citation_audit_report`.

## Deferred

- Real controlled web/literature search execution.
- Citation quality scoring and source ranking.
- Human approval workflow for promoting external citations to decision-grade Evidence.
- Rich report citation rendering beyond the current Markdown audit and visualization stage table.
