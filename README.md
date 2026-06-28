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
- Adaptive strong local baseline v0 with XGBoost when justified by dataset signals, numeric median imputation, categorical ordinal encoding, text TF-IDF, datetime calendar features, time-split lag/rolling covariates, and majority/mean or linear fallback metrics.
- ModelVersion registration with persisted `model_package.joblib` artifacts for successful strong baseline runs.
- Model package replay validation that reloads a saved ModelVersion, regenerates validation predictions from DatasetSnapshot and SplitManifest, stores metric deltas, replay predictions, and a validation report as artifacts.
- Project Job history and ModelVersion validation history visible in the UI.
- Artifact preview and download flow for text, JSON, Markdown, CSV, and TSV artifacts.
- Approach Studio v0 with ResearchBrief, Idea, Report, and VisualizationSpec objects for flexible, evidence-backed modeling proposals.
- Idea-to-AgentTask stub execution with schema-validated AgentResult, report artifacts, evidence, and lineage.
- Cross-project Asset Library v0 for Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates with Project/Idea references.
- Cross-project Skill & FeatureRecipe Pack v1 with reusable tabular boosting, TF-IDF, time lag/rolling, relational aggregation, diagnostics, and decision reporting assets.
- Agent Skill Handoff v1 with ResearchPlan-recommended library asset ids in AgentTaskContracts, AgentContextPack asset recommendations, and workspace materialization under `.harness/context/library_assets/`.
- Adaptive AgentTask Planning v1 with artifact-backed runner contracts that bundle dataset/profile context, evaluation constraints, assumptions, benchmark context, Skill/library recommendations, flexible approach candidates, research queries, reporting requirements, and artifact expectations.
- Planned Agent Workspace Handoff v1 for materializing planner-generated AgentTaskContracts into controlled `.harness` workspaces with context artifacts, library assets, execution policy, manifests, and lineage before runner execution.
- Agent Task Readiness Review v1 with artifact-backed pre-run blockers/warnings, Markdown report, visualization spec, and UI preview for contract/workspace safety and completeness.
- Planned LocalStub Agent Execution v1 with readiness-gated contract execution, AgentResult artifact ingestion, Report/Evidence creation, and lineage without running Codex or external research.
- Report & Visualization Workbench v1 with generated Insights, report preview/download, and typed VisualizationSpec rendering for metric cards, bars, stages, leaderboards, diagnostics, and agent checklists.
- Decision Dashboard & Report v1 with readiness stages, artifact completeness, risk register, next actions, benchmark fixture policy, and decision visualization specs.
- Agent Context Pack v0 for preparing schema-validated, harness-owned execution context before Codex/Skill/web-research runner tasks.
- Job Orchestration v0 with queued jobs, approval gates, dependencies, retry/cancel actions, and a local worker entrypoint.
- Evaluation Diagnostics v0 with run-level error summaries, slice metrics, score/error bins, worst examples, sanity checks, Markdown diagnostics reports, VisualizationSpecs, Evidence, and Insights.
- Agentic Experiment Lifecycle v0 with artifact-backed ExperimentPlans, run reports, diagnostics-aware experiment comparisons, comparison VisualizationSpecs, Evidence, Insights, and UI actions for flexible agent-driven approaches.
- Data Quality Gate v0 with leakage, prediction-time availability, missingness, duplicate, identity/group, temporal, and evaluation-readiness checks connected to Questions, Assumptions, Evidence, Insights, AgentContextPacks, and Evaluation UI.
- Controlled Agent Workspace v0 with materialized runner context, workspace manifests, AgentResult artifact ingestion, and workspace preview in the Approach UI.
- Benchmark Dataset Catalog v1 with Home Credit, fraud, retail forecasting, basket, UCI, and OpenML source cards plus managed credential-free public archive/direct-file downloads, local primary-table import, relational catalog artifacts, and inferred join-key context without storing external credentials.
- Public Benchmark Workflow v1 for credential-free sources, running download, import, quality, evaluation approval, SplitManifest, adaptive baseline, diagnostics, reports, visualizations, decision dashboard, and BenchmarkScenarioPack from one in-product action.
- Workflow Results UX v1 with job-output artifact resolution, workflow summaries, and preview/download navigation for generated reports and artifacts inside the UI.
- Benchmark Fixture & Smoke Harness v0 with credential-free Home Credit-like, UCI Bank-like, and retail time-series fixtures plus fixture-driven import/quality/evaluation/baseline strategy smoke.
- Benchmark Scenario Pack v1 with fixture-aware benchmark_scenario_pack/report artifacts, supporting-table artifact registration for small local bundles, ResearchPlan handoff, and UI preview.
- Baseline Strategy Planner v0 with artifact-backed adaptive candidate strategies, selected/deferred rationale, Skill/library context, reporting/visualization expectations, relational AgentTask handoff notes, and baseline report integration.
- Evaluation Scenario Comparison v0 with artifact-backed split feasibility, temporal/group leakage, quality gate, relational context, open question, and assumption-risk comparison before EvaluationSpec adoption.
- Evaluation Approval Review v0 with artifact-backed approval blockers, assumption-backed proceed notes, review lineage, and UI preview before approving an EvaluationSpec.
- Controlled Research Planning v0 with ResearchPlan artifacts that turn project context, quality gates, evaluation specs, benchmark context, and cross-project Skill assets into controlled query candidates, source policy, expected evidence, and reporting requirements.
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
