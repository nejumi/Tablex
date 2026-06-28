# 0039 Benchmark Evidence Pack Goal

## Goal

Make benchmark-driven validation easier to inspect inside the workbench. A project should be able to generate one benchmark evidence pack that collects benchmark source cards, local readiness, imports, relational catalogs, scenario packs, workflow jobs, experiment runs, reports, visualizations, AgentTask handoff state, readiness reviews, and local stub AgentResult artifacts.

## Implementation

- Added `services/benchmark_evidence.py`.
- Added `create_benchmark_evidence_pack` job type.
- Added `POST /api/projects/{project_id}/benchmarks/evidence-pack`.
- The pack creates:
  - `benchmark_evidence_pack` JSON artifact
  - `benchmark_evidence_report` Markdown artifact and Report record
  - `visualization_spec` with `stage_status` rows
  - Evidence record
  - Lineage from source artifacts/jobs to pack, report, evidence, and visualization
- The service discovers benchmark ids from artifact metadata, job input/output, and benchmark DatasetSnapshot source refs.
- The Data tab now has a Benchmark Evidence Packs panel with generate, preview, and download actions.

## Validation Plan

- API integration test for an empty project, verifying empty-state pack/report artifacts.
- API integration test after Home Credit fixture smoke, verifying multi-table benchmark evidence, job artifact resolver summary, report preview, and pack content.
- Full backend lint/type/test suite.
- Frontend lint and production build.
- Docker image build and smoke test for the evidence-pack endpoint.

## Validation Completed

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- `git diff --check`
- `docker build -t tablex:dev .`
- Docker smoke test: created a project in the container, generated a Benchmark Evidence Pack, and previewed the empty-state Markdown report.

## Deferred

- Rich benchmark comparison charts beyond the current `stage_status` visualization.
- Automatic benchmark score claims or leaderboard submission.
- Credentialed Kaggle download inside Tablex.
- Real runner execution over Home Credit supporting tables; this remains an AgentTask/FeatureRecipe target.
