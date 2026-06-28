# Development Guide

## Local Setup

Backend requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Frontend requires Node.js 20 or newer.

```bash
cd apps/frontend
npm install
```

## Backend

Run the API on port 8000:

```bash
source .venv/bin/activate
uvicorn tabular_harness.main:app --app-dir apps/backend --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/healthz
```

Metadata defaults to `data/metadata/app.db`. Artifacts default to `data/artifacts`.
The baseline runner uses XGBoost as the strong local baseline. It builds persisted `baseline_plan`, `feature_recipe`, `baseline_report`, `baseline_metrics`, validation prediction, and `model_package.joblib` artifacts. Successful strong baseline runs also create a `ModelVersion` record linked to the package artifact. The runner applies numeric median imputation, categorical ordinal encoding, text TF-IDF, datetime calendar features, and falls back to LogisticRegression/Ridge or majority/mean sanity baselines if the strong run fails. Lag and rolling covariate features are enabled only when the approved EvaluationSpec uses a time split.

Create a baseline strategy artifact without running the model:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/baseline/strategy-plan
```

The strategy plan records sanity-floor, strong single-table, text TF-IDF, categorical, datetime, time-series, and relational aggregation candidates. Relational aggregation is marked as AgentTask work until join semantics and prediction-time availability are validated.

Saved ModelVersion packages can be replay-validated from the Assets tab or with:

```bash
curl -X POST http://localhost:8000/api/model-versions/{model_version_id}/validate
```

The validation job reloads `model_package.joblib`, rebuilds validation features from the linked DatasetSnapshot and SplitManifest, recomputes metrics, and stores `model_validation_report`, `model_validation_metrics`, and `prediction_replay` artifacts with lineage from the ModelVersion.

Project job history is available from:

```bash
curl http://localhost:8000/api/projects/{project_id}/jobs
```

Queued job orchestration endpoints:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"infer_assumptions","project_id":"p_x","input":{"reason":"manual queue test"}}'
curl -X POST http://localhost:8000/api/jobs/{job_id}/approve
curl -X POST http://localhost:8000/api/jobs/{job_id}/cancel
curl -X POST http://localhost:8000/api/jobs/{job_id}/retry
curl -X POST http://localhost:8000/api/worker/run-once
```

Jobs can carry `context`, `policy`, `dependency_job_ids`, `priority`, `max_attempts`, and `approval_required`. `run_agent_task` and jobs with restricted/full network or production-write policy require approval before they become runnable.

Run the local worker from a shell:

```bash
tablex-worker --once
tablex-worker --interval 2 --worker-id local-worker
```

The worker currently uses MVP stub handlers for generic queued jobs. Feature-specific product endpoints still execute synchronously until the async worker layer is expanded.

ModelVersion validation history is available from:

```bash
curl http://localhost:8000/api/model-versions/{model_version_id}/validations
```

Evaluation diagnostics can be generated for any run that has prediction artifacts, a DatasetSnapshot, an EvaluationSpec, and a SplitManifest:

```bash
curl -X POST http://localhost:8000/api/runs/{run_id}/diagnostics
```

The diagnostics job stores `evaluation_diagnostics`, `evaluation_diagnostics_report`, and `visualization_spec` artifacts, then creates Evidence and an Insight linked back to the run, prediction output, EvaluationSpec, and SplitManifest. The first implementation covers classification and regression summaries, slice metrics, score/error bins, worst examples, and basic split/prediction sanity checks.

Agentic experiment lifecycle endpoints:

```bash
curl -X POST http://localhost:8000/api/ideas/{idea_id}/experiment-plan
curl http://localhost:8000/api/ideas/{idea_id}/experiment-plans
curl -X POST http://localhost:8000/api/runs/{run_id}/report
curl -X POST http://localhost:8000/api/projects/{project_id}/experiments/compare
```

ExperimentPlans are not fixed recipes. They lock the harness-owned evaluation context and safety policy while leaving approach details to the AgentRunner, Skill references, and controlled research policy. The lifecycle stores `experiment_plan`, `run_report`, `experiment_comparison`, `experiment_comparison_report`, and comparison `visualization_spec` artifacts with Evidence, Insights, Reports, and Lineage.

Data quality gate endpoints:

```bash
curl -X POST http://localhost:8000/api/datasets/{dataset_snapshot_id}/quality/run
curl http://localhost:8000/api/datasets/{dataset_snapshot_id}/quality/latest
```

The quality gate stores `data_quality_gate`, `data_quality_report`, and a quality `visualization_spec`. It materializes high-risk findings as Evidence, Assumptions, Questions, and an Insight. AgentContextPacks include `quality_gate_context` so future Codex/Skill runners can see harness-owned leakage, availability, temporal, duplicate, missingness, and evaluation-readiness constraints before generating features or code.

Evaluation scenario comparison endpoint:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/evaluation/compare
```

This creates or reuses EvaluationCandidates, compares random/stratified/time/group scenarios against the latest DatasetSnapshot, DataQualityGate, RelationalCatalog, open Questions, and high-risk Assumptions, then stores an `evaluation_scenario_comparison` artifact. It is decision support only; it does not mutate or approve an EvaluationSpec.

Evaluation approval review endpoint:

```bash
curl -X POST http://localhost:8000/api/evaluation-specs/{evaluation_spec_id}/approval-review
curl -X POST http://localhost:8000/api/evaluation-specs/{evaluation_spec_id}/approve
```

The review stores an `evaluation_approval_review` artifact before approval. It blocks only explicit blockers such as unanswered `block_until_answered` questions or deployment-blocking assumptions. Other unresolved questions and assumptions are recorded as assumption-backed proceed context so work can continue without hiding risk.

Benchmark catalog endpoints:

```bash
curl http://localhost:8000/api/benchmarks
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/local-status
curl -X POST http://localhost:8000/api/benchmarks/uci_bank_marketing/fixtures/generate \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/import \
  -H 'Content-Type: application/json' \
  -d '{}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
```

Place extracted benchmark files under `data/benchmarks/{benchmark_id}` or another path below `HARNESS_DATA_DIR/benchmarks`. Kaggle credentials and API tokens are user-managed outside Tablex and must not be pasted into Tablex, AgentTaskContracts, or runner workspaces. The importer profiles one primary CSV/Parquet table, stores a `benchmark_import_manifest`, creates a `relational_catalog` artifact with table profiles and inferred join-key context for supporting files, and registers small supporting CSV/Parquet tables as `benchmark_supporting_table` artifacts with a size cap. `scenario-pack` creates `benchmark_scenario_pack` and `benchmark_scenario_report` artifacts that summarize benchmark intent, fixture status, artifact readiness, runner guardrails, and report expectations. Fixture endpoints generate tiny synthetic files for smoke tests only; they do not download or store external benchmark data. See `docs/benchmarks.md`.

Artifact preview and download are available from:

```bash
curl http://localhost:8000/api/artifacts/{artifact_id}/preview
curl -L -o artifact.bin http://localhost:8000/api/artifacts/{artifact_id}/download
```

Preview is intentionally limited to UTF-8 text-like artifacts such as JSON, Markdown, CSV, TSV, YAML, TXT, and log files. Binary artifacts such as `model_package.joblib` are downloadable but not previewed.

Approach Studio endpoints:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/research-plan
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/research-briefs \
  -H 'Content-Type: application/json' \
  -d '{}'
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/ideas/generate
curl http://localhost:8000/api/projects/{project_id}/approach/research-briefs
curl http://localhost:8000/api/projects/{project_id}/approach/ideas
curl -X POST http://localhost:8000/api/ideas/{idea_id}/prepare-agent-context
curl http://localhost:8000/api/ideas/{idea_id}/context-packs
curl -X POST http://localhost:8000/api/ideas/{idea_id}/run-agent-task
```

`/approach/research-plan` writes a `research_plan` artifact shaped by `schemas/research_plan.schema.json`. It does not execute network search. It records controlled web/literature query candidates, available and recommended cross-project Skill/FeatureRecipe/EvaluationPattern references, missing asset suggestions, source and credential policy, expected Evidence shape, and report/visualization expectations. ResearchBriefs and generated Ideas reference the latest ResearchPlan when one exists.

`prepare-agent-context` writes an `agent_context_pack` artifact validated by `schemas/agent_context_pack.schema.json`. The pack includes harness-owned data/evaluation references, SplitManifest context, artifact preview/download references, locked cross-project asset references, research policy, safety controls, and the required output contract. It does not pass secrets or connector credentials to the agent.

Report and visualization endpoints:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/reports/draft \
  -H 'Content-Type: application/json' \
  -d '{"report_type":"project_summary"}'
curl -X POST http://localhost:8000/api/projects/{project_id}/visualizations/generate
curl -X POST http://localhost:8000/api/projects/{project_id}/insights/generate
curl -X POST http://localhost:8000/api/projects/{project_id}/decision-dashboard/generate
curl http://localhost:8000/api/projects/{project_id}/reports
curl http://localhost:8000/api/projects/{project_id}/visualizations
curl http://localhost:8000/api/projects/{project_id}/insights
curl http://localhost:8000/api/reports/{report_id}/preview
curl -L -o report.md http://localhost:8000/api/reports/{report_id}/download
```

`/visualizations/generate` creates a small dashboard set, not just one chart: project readiness metric cards, assumption risk bars, evaluation readiness stages, and leaderboard primary-metric bars. `/insights/generate` stores an `insight_set` artifact, `Insight` records, Evidence records, and lineage edges so report statements remain inspectable in the workbench.

`/decision-dashboard/generate` creates a `decision_dashboard` JSON artifact shaped by `schemas/decision_dashboard.schema.json`, a `decision_report` Markdown artifact, a Report record, and three decision `visualization_spec` records. It summarizes readiness stages, artifact completeness, high-risk assumptions/questions, benchmark fixture policy, next actions, and report/visualization expectations.

Approach Ideas are not fixed recipes. They are evidence-backed proposals with `AgentTaskContract` payloads for future Codex, Skill-library, and controlled web or literature research runners. The harness still owns EvaluationSpec, SplitManifest, artifacts, lineage, safety controls, and report outputs.

`/api/ideas/{idea_id}/run-agent-task` currently uses `LocalStubAgentRunner`. It validates the AgentResult schema and persists `agent_task_report`, `agent_result`, and `visualization_spec` artifacts plus Evidence and Lineage. It does not run real Codex code or external web research yet. Prepare and inspect an AgentContextPack first when validating future runner behavior.

Agent task execution now materializes a controlled workspace under the local artifact root before invoking the runner. The workspace receives harness-owned context files such as AgentContextPack, ResearchPlan, ExperimentPlan, DataQualityGate, and diagnostics when present. The run stores an `agent_workspace_manifest` artifact, then ingests relative paths declared in `AgentResult.artifacts` into the artifact store. Absolute paths and `..` escapes are rejected.

Cross-project Asset Library endpoints:

```bash
curl -X POST http://localhost:8000/api/assets/seed-defaults
curl http://localhost:8000/api/assets
curl http://localhost:8000/api/assets/{asset_id}/versions
curl -X POST http://localhost:8000/api/projects/{project_id}/asset-references \
  -H 'Content-Type: application/json' \
  -d '{"target_asset_id":"asset_x","target_asset_version_id":"av_x","relation_type":"uses"}'
curl -X POST http://localhost:8000/api/ideas/{idea_id}/asset-references \
  -H 'Content-Type: application/json' \
  -d '{"target_asset_id":"asset_x","target_asset_version_id":"av_x","relation_type":"uses_for_agent_task"}'
```

Project workspaces keep project-specific outputs. Reusable Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates live in the cross-project Asset Library and are attached through locked `AssetReference` records.

Useful environment variables:

```bash
export APP_DISPLAY_NAME=Tablex
export HARNESS_DATA_DIR=data
export HARNESS_DATABASE_URL=sqlite:///data/metadata/app.db
export HARNESS_ARTIFACT_ROOT=data/artifacts
```

## Frontend

Run Vite on port 5173:

```bash
cd apps/frontend
npm run dev
```

The dev server proxies `/api` and `/healthz` to `http://localhost:8000`.

## Tests And Checks

Backend:

```bash
ruff check .
mypy apps/backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

Frontend:

```bash
cd apps/frontend
npm run lint
npm run build
```

## Alembic

The application creates tables on startup for MVP convenience. Alembic is configured for explicit migration workflows:

```bash
alembic upgrade head
```

Use `HARNESS_DATABASE_URL` to point Alembic at a non-default SQLite database.

## Docker

Build:

```bash
docker build -t tablex:dev .
```

Run:

```bash
docker run --rm -p 8080:8080 -v "$PWD/data:/data" tablex:dev
```

Open `http://localhost:8080`.

## API Smoke Flow

```bash
curl -s -X POST http://localhost:8000/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"name":"Demo","target_column":"target"}'
```

Upload CSV or Parquet through the UI, or import a locally prepared benchmark primary table from the Data tab, then run evaluation design from the Evaluation tab.

The current UI flow is:

1. Create a project with a target column.
2. Upload a CSV or Parquet file from the Data tab, or import from the Benchmark Dataset Catalog.
3. Run Data Quality analysis from the Data tab and inspect quality gates.
4. Review or answer generated questions in the Understanding tab.
5. Review assumptions in the Assumptions tab.
6. Design evaluation candidates in the Evaluation tab, using the quality gate context.
7. Promote and approve an EvaluationSpec.
8. Generate a SplitManifest.
9. Generate a Research Brief and flexible Approach Ideas from the Approach tab.
10. Seed or attach reusable assets from the Library tab.
11. Prepare and preview AgentContextPacks from the Approach tab before agent execution.
12. Create and preview ExperimentPlans from the Approach tab.
13. Review, approve, cancel, retry, or process queued jobs from the Jobs tab.
14. Plan Baseline from the Experiments tab to inspect candidate strategies and deferred AgentTask work.
15. Run Baseline from the Experiments tab as a sanity floor or reference run.
16. Draft run reports and compare experiments from the Experiments tab.
17. Generate Insights, draft Reports, and create Visualization Dashboard specs from the Reports tab.
18. Generate run diagnostics from the Leaderboard tab and inspect the diagnostics preview.
19. Preview or download report artifacts from the Reports tab.
20. Review the run in Experiments, Leaderboard, Assets, and Lineage.
21. Inspect ModelVersions in the Assets tab.
22. Validate a saved model package replay from the ModelVersions table.
23. Review all project jobs in the Jobs tab and validation history in the Assets tab.
24. Preview or download registered artifacts from the Assets tab.

Supported SplitManifest generation modes:

- `random`: deterministic hash split by row index.
- `stratified`: deterministic per-class hash ranking using the stratify column.
- `time`: chronological split by the approved time column; summary includes train/valid time ranges and `time_order_respected`.
- `group`: group-level split that keeps each group on one side; summary includes group counts and `group_leakage_check_passed`.
