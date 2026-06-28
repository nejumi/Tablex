# Tablex

Tablex is the current working name for a self-contained, tabular-first prediction meta-harness. It is designed to keep data understanding, assumptions, evaluation design, artifacts, lineage, jobs, and agent execution governance inside the product UI.

The product name may still change. Internal package names and database tables stay neutral where practical.

## Current MVP

- FastAPI backend with SQLite metadata.
- Local filesystem artifact store with content hashes.
- CSV/Parquet dataset upload.
- DuckDB profiling into persisted artifacts.
- Project CRUD and overview.
- Assumption, Question, Evidence, EvaluationCandidate, EvaluationSpec, SplitManifest, ModelVersion, Artifact, Asset, LineageEdge, Job model skeletons.
- Question answering with answer history and user-answer evidence.
- EvaluationCandidate promotion, EvaluationSpec approval, and random/stratified SplitManifest generation.
- Time/group SplitManifest generation with time-order and group-overlap diagnostics.
- Strong local baseline v0 with XGBoost, numeric median imputation, categorical ordinal encoding, text TF-IDF, datetime calendar features, and majority/mean or linear fallback metrics.
- ModelVersion registration with persisted `model_package.joblib` artifacts for successful strong baseline runs.
- Model package replay validation that reloads a saved ModelVersion, regenerates validation predictions from DatasetSnapshot and SplitManifest, stores metric deltas, replay predictions, and a validation report as artifacts.
- Project Job history and ModelVersion validation history visible in the UI.
- Artifact preview and download flow for text, JSON, Markdown, CSV, and TSV artifacts.
- Approach Studio v0 with ResearchBrief, Idea, Report, and VisualizationSpec objects for flexible, evidence-backed modeling proposals.
- Idea-to-AgentTask stub execution with schema-validated AgentResult, report artifacts, evidence, and lineage.
- Cross-project Asset Library v0 for Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates with Project/Idea references.
- Report & Visualization Workbench v0 with generated Insights, report preview/download, and VisualizationSpec-driven dashboard previews.
- Agent Context Pack v0 for preparing schema-validated, harness-owned execution context before Codex/Skill/web-research runner tasks.
- Job Orchestration v0 with queued jobs, approval gates, dependencies, retry/cancel actions, and a local worker entrypoint.
- Evaluation Diagnostics v0 with run-level error summaries, slice metrics, score/error bins, worst examples, sanity checks, Markdown diagnostics reports, VisualizationSpecs, Evidence, and Insights.
- Agentic Experiment Lifecycle v0 with artifact-backed ExperimentPlans, run reports, diagnostics-aware experiment comparisons, comparison VisualizationSpecs, Evidence, Insights, and UI actions for flexible agent-driven approaches.
- Data Quality Gate v0 with leakage, prediction-time availability, missingness, duplicate, identity/group, temporal, and evaluation-readiness checks connected to Questions, Assumptions, Evidence, Insights, AgentContextPacks, and Evaluation UI.
- Controlled Agent Workspace v0 with materialized runner context, workspace manifests, AgentResult artifact ingestion, and workspace preview in the Approach UI.
- Benchmark Dataset Catalog v0 with Home Credit, fraud, retail forecasting, basket, and UCI smoke-test entries plus local primary-table import, relational catalog artifacts, and inferred join-key context without storing external credentials.
- Baseline Strategy Planner v0 with artifact-backed candidate strategies, selected/deferred rationale, relational AgentTask handoff notes, and baseline report integration.
- Evaluation Scenario Comparison v0 with artifact-backed split feasibility, temporal/group leakage, quality gate, relational context, open question, and assumption-risk comparison before EvaluationSpec adoption.
- Leaderboard backed by ExperimentRun metrics.
- React UI with project list, dataset upload, assumptions, evaluation, approach, experiments, leaderboard, reports, assets, jobs, and lineage tabs.
- AgentRunner interface with Noop/LocalStub and Codex CLI skeleton.
- Single Docker image.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn tabular_harness.main:app --app-dir apps/backend --reload --port 8000
```

In another shell:

```bash
cd apps/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

See [docs/dev.md](docs/dev.md) for full setup, tests, and Docker commands.
See [docs/benchmarks.md](docs/benchmarks.md) for benchmark dataset catalog and local import workflow.
