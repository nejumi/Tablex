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
- Agent Skill Handoff v1 with ResearchPlan-recommended library asset ids in AgentTaskContracts, AgentContextPack asset recommendations, baseline/report context, and workspace materialization under `.harness/context/library_assets/`.
- Adaptive AgentTask Planning v1 with artifact-backed runner contracts that bundle dataset/profile context, evaluation constraints, assumptions, benchmark context, Skill/library recommendations, flexible approach candidates, research queries, reporting requirements, and artifact expectations.
- Persistent Agent Chat dock that turns in-product instructions into harness-owned AgentTaskContracts instead of requiring an external Codex UI.
- Backend-backed Portal overview and cross-project idea inbox with `portal_idea` artifacts, plus active-only Agent Activity worker cards with estimated token telemetry inside the product UI.
- Streamlined Project command center v1 with a visible Now/Why/Do focus, collapsed supporting signals, collapsed journey map, grouped secondary tabs, and concise Portal updates so the UI guides one next action without hiding deeper harness evidence.
- User Settings v0 with top-right settings access, Light/Dark display themes, built-in `en-US` and `ja-JP` LocalePacks, LocalePack-driven app chrome/tabs/common controls/chat copy, dynamic local locale-pack registration with English fallback, and localization AgentTask planning for future Codex-generated packs.
- Tier3 Codex Translation v0 with Translate actions on preview surfaces, `translate_tier3_content` jobs, Codex-ready translation AgentTaskContracts, derived translated Report/Artifact assets, and lineage back to the English source of truth.
- Planned Agent Workspace Handoff v1 for materializing planner-generated AgentTaskContracts into controlled `.harness` workspaces with context artifacts, library assets, execution policy, manifests, and lineage before runner execution.
- Agent Task Readiness Review v1 with artifact-backed pre-run blockers/warnings, Markdown report, visualization spec, and UI preview for contract/workspace safety and completeness.
- Planned LocalStub Agent Execution v1 with readiness-gated contract execution, AgentResult artifact ingestion, Report/Evidence creation, and lineage without running Codex or external research.
- Planned Codex CLI Agent Execution v0 with the same workspace/readiness/AgentResult ingestion path for controlled AgentTaskContracts, including `author_analysis_notebook` contracts that read Notebook Authoring Briefs before writing.
- AgentResult Experiment Ingestion v1 with runner-produced metrics/feature/visualization artifacts promoted into ExperimentRun and VisualizationSpec records while preserving EvaluationSpec and SplitManifest constraints.
- Cited Agent Evidence Ingestion v1 with AgentResult source/citation fields, source citation manifests, citation audit reports, Evidence, VisualizationSpec, and lineage for runner-supplied or harness-materialized citation context.
- Agent Task Results Workbench v1 with project-scoped summaries of planned and Idea-backed AgentTask runs, experiment registration, reports, citation audits, evidence, and preview/download actions in the Experiments UI.
- Benchmark Evidence Pack v1 with source cards, local status, scenario packs, workflow results, reports, visualizations, AgentTask handoff state, Evidence, and lineage summarized inside the workbench.
- Report & Visualization Workbench v1 with generated Insights, report preview/download, and typed VisualizationSpec rendering for metric cards, bars, stages, leaderboards, diagnostics, and agent checklists.
- Analysis Notebook v0 with marimo source artifacts, in-product notebook reviews, content-readiness scoring, read-this-first guidance, visual story cards, EDA/review playbooks, EDA quality rubric, target readiness, feature review queues, profile/run-backed evidence SVG/HTML/bundle artifacts, interactive Notebook guide, controlled execution planning contracts, safe static execution capture artifacts, source-backed Notebook Authoring Briefs for on-the-fly Codex notebook work, and lineage from Data Understanding and ExperimentRun context. Empty Model Diagnostics notebooks with no useful metric or prediction rows are treated as not-ready, not primary evidence.
- Data Review v1 with a harness-controlled DuckDB EDA runner over the uploaded DatasetSnapshot, producing human-readable HTML, SVG figures, JSON bundle, Markdown report, VisualizationSpec, Evidence, Insight, and lineage. It can be launched from the Notebooks tab or Agent Chat without external dashboards or connector credentials.
- Decision Dashboard & Report v1 with readiness stages, artifact completeness, risk register, next actions, benchmark fixture policy, and decision visualization specs.
- Agent Context Pack v0 for preparing schema-validated, harness-owned execution context before Codex/Skill/web-research runner tasks.
- Job Orchestration v0 with queued jobs, approval gates, dependencies, retry/cancel actions, and a local worker entrypoint.
- Evaluation Diagnostics v0 with run-level error summaries, slice metrics, score/error bins, worst examples, sanity checks, Markdown diagnostics reports, VisualizationSpecs, Evidence, and Insights.
- Agentic Experiment Lifecycle v0 with artifact-backed ExperimentPlans, run reports, diagnostics-aware experiment comparisons, comparison VisualizationSpecs, Evidence, Insights, and UI actions for flexible agent-driven approaches.
- Data Quality Gate v0 with leakage, prediction-time availability, missingness, duplicate, identity/group, temporal, and evaluation-readiness checks connected to Questions, Assumptions, Evidence, Insights, AgentContextPacks, and Evaluation UI, including sample-scoped quality boundaries for large bounded profiles.
- Controlled Agent Workspace v0 with materialized runner context, workspace manifests, AgentResult artifact ingestion, and workspace preview in the Approach UI.
- Benchmark Dataset Catalog v1 with Home Credit, fraud, retail forecasting, basket, UCI, and OpenML source cards plus harness-only Kaggle credential probes/file inventories/selective required-file downloads, managed credential-free public archive/direct-file downloads, local primary-table import, relational catalog artifacts, and inferred join-key context without exposing external credentials to agents.
- Benchmark Collection Plan v1 with project-scoped benchmark source readiness, credential policy, recommended initial suite, collection report, visualization spec, Evidence, and lineage for Home Credit-centered practical benchmark planning.
- Relational Feature Planning v1 with RelationalCatalog-derived train-fold-safe aggregation candidates, point-in-time requirements, risk register, AgentTask handoff, Report, Evidence, VisualizationSpec, Lineage, and context propagation.
- Relational Feature Recipe Preview v1 with preview-only aggregation recipe artifacts, generated feature CSV/profile artifacts, deferred safety checks, Report, Evidence, VisualizationSpec, Lineage, UI actions, and AgentTask/ContextPack propagation.
- Relational Feature Scenario Diagnostics v1 with preview feature coverage/missingness/constant checks, primary-only vs safe-relational vs deferred scenario comparison, Report, Evidence, VisualizationSpec, Lineage, UI actions, and AgentTask/ContextPack propagation.
- Relational Evidence & Reporting Surface v1 with relational recipe/diagnostics summaries folded into Benchmark Evidence Pack, Decision Dashboard/Report, and Project Report so scenario readiness is visible without chasing raw artifacts.
- Relational Runner Workspace Handoff v1 with latest relational plan, recipe, preview CSV/profile, scenario diagnostics, and scenario report materialized under `.harness/context/relational/` for controlled AgentRunner workspaces.
- Agent Runner Relational Context Consumption v1 with LocalStub AgentResult reports, metrics, feature recipes, visualization specs, and Agent Task Results UI summaries carrying relational context inventory and deferred safety checks.
- Flexible Agent Strategy Decision Trace v1 with open-ended runner autonomy policy, approach decision trace artifacts, and Agent Task Results UI summaries so Codex can reject, revise, or replace suggested recipes while the harness preserves evaluation, safety, artifacts, and lineage.
- Public Benchmark Workflow v1 for credential-free sources, running download, import, quality, evaluation approval, SplitManifest, adaptive baseline, diagnostics, reports, visualizations, decision dashboard, and BenchmarkScenarioPack from one in-product action.
- Workflow Results UX v1 with job-output artifact resolution, workflow summaries, and preview/download navigation for generated reports and artifacts inside the UI.
- Benchmark Fixture & Smoke Harness v0 with credential-free Home Credit-like, UCI Bank-like, and retail time-series fixtures plus fixture-driven import/quality/evaluation/baseline strategy smoke.
- Benchmark Scenario Pack v1 with fixture-aware benchmark_scenario_pack/report artifacts, supporting-table artifact registration for small local bundles, ResearchPlan handoff, and UI preview.
- Large Dataset Bounded Profiling v1 with exact schema/row count, sample-backed column statistics, deferred deep-profile metadata, and Data UI profile readiness for Home Credit-scale imports.
- Baseline Strategy Planner v0 with profile-driven adaptive candidate strategies, resource guards, selected/deferred rationale, Skill/library context, reporting/visualization expectations, relational AgentTask handoff notes, and baseline report integration.
- Evaluation Scenario Comparison v0 with artifact-backed split feasibility, temporal/group leakage, quality gate, relational context, open question, and assumption-risk comparison before EvaluationSpec adoption.
- Evaluation Approval Review v0 with artifact-backed approval blockers, assumption-backed proceed notes, review lineage, and UI preview before approving an EvaluationSpec.
- Controlled Research Planning v0 with ResearchPlan artifacts that turn project context, quality gates, evaluation specs, benchmark context, and cross-project Skill assets into controlled query candidates, source policy, expected evidence, and reporting requirements.
- Research Source Pack v1 with project/library/benchmark source candidates, citation requirements, freshness expectations, source risk policy, Evidence, Report, Lineage, and AgentTaskContract handoff without executing network search.
- Controlled Research Runner Stub v1 with Research Source Pack execution contracts, research run manifests, findings reports, source citation manifests, Evidence, VisualizationSpec, and lineage without external network access.
- Research Findings Synthesis v1 with runner findings, citation audit, follow-up requirements, Evidence, Report, VisualizationSpec, Lineage, AgentTaskContract inputs, AgentContextPack context, and Approach UI preview/download.
- Leaderboard backed by ExperimentRun metrics.
- React UI with project list, dataset upload, benchmark access gates, ER-style relational catalog previews, assumptions, evaluation, approach, experiments, notebooks, leaderboard, reports, assets, jobs, and lineage tabs. UI surfaces should feel rich and inspectable rather than a plain experiment tracker.
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
