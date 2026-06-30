# Initial Implementation Plan

## Read Specifications

- `tabular_prediction_meta_harness_spec_v2/TABULAR_PREDICTION_META_HARNESS_FULL_SPEC.md`
- `tabular_prediction_meta_harness_spec_v2/CHANGELOG_V2.md`
- `tabular_prediction_meta_harness_spec_v2/README.md`
- `tabular_prediction_meta_harness_spec_v2/docs/01_product_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/02_architecture_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/03_data_model_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/04_ml_lifecycle_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/05_agent_codex_integration_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/06_security_connectors_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/07_ui_ux_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/08_api_events_spec.md`
- `tabular_prediction_meta_harness_spec_v2/docs/09_development_plan.md`
- `tabular_prediction_meta_harness_spec_v2/docs/10_references.md`
- `tabular_prediction_meta_harness_spec_v2/docs/11_assumption_intelligence_spec.md`
- `tabular_prediction_meta_harness_spec_v2/schemas/*.json`
- `tabular_prediction_meta_harness_spec_v2/project_workspace_template/*`

`PREDICTIVE_AGENT_WORKBENCH_FULL_SPEC.md` was not present. The equivalent content is treated as covered by the full meta-harness specification and split docs above.

## Naming Decision

The current working display name is `Tablex`. Product naming is still kept configurable through `APP_DISPLAY_NAME`, and internal package names, API paths, database tables, and architecture docs avoid hard-coding a final brand where practical.

## Implementation Approach

Build the smallest vertical slice that proves the harness owns state, artifacts, lineage, evaluation design, and job transitions:

1. FastAPI backend with SQLite metadata and SQLAlchemy models.
2. Local artifact store with content hash manifests.
3. CSV/Parquet upload into `DatasetSnapshot`.
4. DuckDB profiling into `profile.json`, `understanding.md`, `semantic_catalog.json`, questions, assumptions, and evidence artifacts.
5. Assumption Intelligence v0 data model and UI.
6. EvaluationCandidate/EvaluationSpec separation with promote/approve flow.
7. Random and stratified split manifest generation.
8. Question answering with answer history and `user_answer` evidence.
9. Baseline v0 using a local XGBoost strong baseline with LogisticRegression/Ridge and majority-classifier or mean-regressor fallback.
10. Job model with synchronous MVP execution and explicit state transitions.
11. AgentRunner interface plus Noop/LocalStub and Codex CLI skeleton.
12. React UI for project list, detail tabs, upload, assumptions, evaluation, approach exploration, experiments, leaderboard, reports, artifacts, jobs, and lineage.

## Technology Stack

- Backend: FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite.
- Data profiling and split generation: DuckDB.
- Baseline modeling: XGBoost, scikit-learn LogisticRegression/Ridge fallback, TF-IDF text features.
- Artifact store: local filesystem under `data/artifacts`.
- Frontend: React, Vite, TypeScript, lucide-react.
- Worker: Python synchronous skeleton for now.
- Tests and quality: pytest, ruff, mypy, eslint, TypeScript build.
- Container: single Docker image serving frontend static files through FastAPI.

## Implemented Scope

- Project CRUD and overview.
- Dataset upload for CSV and Parquet.
- Artifact registration with content hash and manifest.
- Metadata DB models for the initial first-class objects requested.
- Profiling outputs and basic Data Understanding artifacts.
- Question, Assumption, Evidence, and evidence-link persistence.
- Fallback policy enum values represented in generated assumptions/questions.
- Question answering with answer history and user-answer evidence.
- Evaluation candidates for random, stratified, time, and group scenarios.
- EvaluationSpec promotion and approval.
- SplitManifest generation for random, stratified, time, and group splits.
- BaselinePlan, FeatureRecipe, model package, baseline report, metrics, and validation prediction artifacts for local strong baselines, with dummy sanity floor metrics.
- ModelVersion registration for successful strong baseline model packages.
- Saved ModelVersion package replay validation that stores validation report, metric deltas, replay predictions, and lineage artifacts.
- Leaderboard v0 backed by `ExperimentRun.metrics_json`.
- Project Job history and ModelVersion validation history exposed through API and UI.
- Artifact preview and download UI for text-like registered artifacts.
- Approach Studio v0 with ResearchBrief, Idea, Report, and VisualizationSpec APIs/UI/artifacts.
- Cross-project Asset Library v0 with AssetVersion artifacts and Project/Idea AssetReferences.
- Report & Visualization Workbench v0 with `Insight` records, `insight_set` artifacts, report preview/download endpoints, and dashboard-oriented VisualizationSpecs.
- Agent Context Pack v0 with schema-validated `agent_context_pack` artifacts for harness-owned runner context, research policy, safety controls, and asset references.
- Job Orchestration v0 with queued jobs, approval_required state, dependency ids, retry/cancel/approve endpoints, and a local worker CLI.
- Evaluation Diagnostics v0 with run-level prediction diagnostics, slice metrics, bins, worst examples, sanity checks, Markdown reports, VisualizationSpecs, Evidence, Insights, and lineage.
- Agentic Experiment Lifecycle v0 with `experiment_plan`, `run_report`, `experiment_comparison`, `experiment_comparison_report`, schema files, Reports, VisualizationSpecs, Evidence, Insights, and UI actions.
- Data Quality Gate v0 with `data_quality_gate`, `data_quality_report`, schema file, quality visualization, materialized Questions, Assumptions, Evidence, Insight, AgentContextPack context, and Data/Evaluation UI.
- Controlled Agent Workspace v0 with `agent_workspace_manifest`, workspace context materialization, AgentResult artifact ingestion, runner safety checks, and Approach UI preview.
- Research Findings Synthesis v1 with latest research source packs, research run manifests, source citation manifests, benchmark/baseline context, Evidence, Report, VisualizationSpec, Lineage, AgentTaskContract inputs, AgentContextPack context, and Approach UI preview/download.
- Benchmark Collection Plan v1 with Home Credit-centered benchmark source readiness, credential policy, fixture/public workflow status, source audit, recommended initial suite, Report, Evidence, VisualizationSpec, Lineage, and Data UI preview/download.
- Harness-only Kaggle Credential Probe v1 with secret-free `kaggle_credential_probe` artifacts, benchmark source-card readiness, and Data UI credential gate action.
- Relational Feature Planning v1 with RelationalCatalog-derived aggregation candidates, fold-safety guardrails, point-in-time requirements, leakage/prediction-time risk register, AgentTask handoff, Report, Evidence, VisualizationSpec, Lineage, and contract/context propagation.
- Relational Feature Recipe Preview v1 with latest-plan-driven aggregation recipe artifacts, DuckDB preview CSV/profile, deferred safety checks, Report, Evidence, VisualizationSpec, Lineage, Data UI actions, and AgentTaskContract/AgentContextPack propagation.
- Relational Feature Scenario Diagnostics v1 with recipe-preview feature diagnostics, scenario comparison, deferred reason summary, Report, Evidence, VisualizationSpec, Lineage, Data UI actions, and AgentTaskContract/AgentContextPack propagation.
- Relational Evidence & Reporting Surface v1 with relational plan/recipe/diagnostics summaries in Benchmark Evidence Pack, Decision Dashboard/Report, and Project Report.
- Relational Runner Workspace Handoff v1 with relational plan, recipe, preview CSV/profile, scenario diagnostics, and scenario report copied into controlled AgentRunner workspaces under `.harness/context/relational/`.
- Agent Runner Relational Context Consumption v1 with LocalStub reports, metrics, feature recipes, visualization specs, and AgentTaskResults summaries carrying relational context inventory and deferred safety checks.
- Flexible Agent Strategy Decision Trace v1 with open-ended runner autonomy policy, approach decision trace artifacts, and UI summaries that keep Codex/Skill runners from being constrained to predefined recipes.
- User Upload Bundle v1 with drag-and-drop CSV/Parquet multi-table intake, optional target, primary-table selection, ER image/PDF/SVG/JSON hints, `uploaded_supporting_table`, `relational_catalog`, and `relational_table_bundle_manifest` artifacts. The bundle manifest exposes tables and hints to runners while preserving the rule that Aggregate & Merge strategy is Codex/runner-designed under harness evaluation and leakage guardrails, not a fixed UI recipe.
- Home-Centered Agent Workflow v1 with mode selection, start action, mandatory Data Understanding and plan creation, current-task display, Ideas & Findings memory, equipped Skill panel, and Agent panel display modes for wrapped Tablex chat vs Raw Codex-style event inspection.
- Job skeleton for:
  - `profile_dataset`
  - `infer_assumptions`
  - `design_evaluation_candidates`
  - `build_split_manifest`
  - `run_baseline`
  - `analyze_evaluation_diagnostics`
  - `generate_insights`
  - `prepare_agent_context`
  - `run_agent_task`
  - `create_experiment_plan`
  - `compare_experiments`
  - `draft_run_report`
  - `analyze_data_quality`
- Agent task is stubbed at job/API level.
- Frontend tabs:
  - Overview
  - Data
  - Understanding
  - Assumptions
  - Evaluation
  - Approach
  - Experiments
  - Leaderboard
  - Reports
  - Assets
  - Library
  - Jobs
  - Lineage

## Deferred Scope

- Google OIDC and real RBAC.
- Real secure database connectors and Data Access Broker implementation.
- General prediction-serving APIs and library-version compatibility policy for model packages.
- Advanced time/group split validation, including multi-cut backtesting and grouped time splits.
- Long-running async worker, retries, resumability, and SSE.
- Production deployment, monitoring, forward validation, and reflection.
- GenAI feature generation.
- W&B, MLflow, Kubernetes, and multi-tenant SaaS support.

## Risks And Open Decisions

- The initial migration uses model metadata for a clean bootstrap. Future schema evolution should move to explicit Alembic operations.
- Profile heuristics are intentionally conservative and name/type based; they are useful for MVP but not sufficient for leakage guarantees.
- Stratified split generation assumes the target column exists and has manageable classes. More validation is needed for rare classes.
- EvaluationSpec immutability is policy-level in this version. A stricter versioning API should be added before serious experiment usage.
- Strong baseline execution is intentionally bounded and should be treated as a first defensible baseline, not a complete AutoML implementation.
- Approach Ideas are planning artifacts, not a guarantee that a runner has performed external research yet. Future runner execution must attach citations and source artifacts.
- Insight generation is deterministic and artifact-backed, but still heuristic. It should become evidence-weighted and runner-extensible before users rely on it for deployment decisions.
- AgentContextPack artifacts intentionally contain references and compact metadata, not raw secrets or connector credentials. Future runners must keep using harness-mediated data access.
- Generic queued jobs use MVP stub worker handlers for now. Feature-specific synchronous endpoints still execute real local work until durable async handlers are implemented.
- Evaluation diagnostics summarize saved validation predictions and split sanity checks, but do not yet run full leakage detection, uncertainty estimation, or multi-cut temporal backtesting.
- ExperimentPlans are artifact-backed contracts, not executable AutoML plans. Real Codex execution, Skill installation, and controlled web/literature search still need production runner integration.
- Data Quality Gate checks are deterministic MVP heuristics. They catch common leakage, missingness, duplicate, ID, time/group, and evaluation-readiness issues, but do not replace domain review or full statistical data validation.
- Controlled workspaces currently use LocalStubAgentRunner for real execution. CodexCliRunner remains a skeleton until external execution policy, approval, and result ingestion are hardened further.
- Research Findings Synthesis currently summarizes stub or artifact-backed research outputs. Verified external web/literature retrieval remains controlled-runner future work and must attach source citations before decision-grade claims.
- Benchmark Collection Plans use catalog source metadata and local readiness; they do not replace real dataset licensing review or credentialed user-managed download flows.
- Relational Feature Plans, Recipe Previews, and Scenario Diagnostics are not deployment recipes. Recipe preview materializes bounded local aggregates for inspection only, and diagnostics intentionally avoids fixed model training. Real joins and model training still need FeatureRecipe or AgentTask implementation with SplitManifest-aware fitting and prediction-time availability confirmation.
- Relational reporting surfaces summarize readiness heuristics; they should guide review and runner planning, not certify feature availability or model lift.
- Relational runner context materialization makes artifacts inspectable in controlled workspaces, but it does not yet execute model-training joins or certify point-in-time-safe relational features.
- LocalStub relational context consumption proves result ingestion and UI propagation, but real Codex/Skill runners still need implementation that reads these artifacts and produces split-respecting code.
- Structured AgentTaskContracts should preserve runner creativity. They should make decisions auditable without reducing Codex to a closed list of fixed recipes.
- Uploaded multi-table bundles should be treated as raw evidence and available data boundaries. Codex should be free to design, compare, and reject aggregate/merge approaches, but every chosen approach must record FeatureRecipe/code artifacts, lineage, split discipline, prediction-time availability assumptions, and leakage checks.
- Target selection is intentionally late-bindable. Target may be selected after Data Understanding or created from a user-described derivation, but target construction must become an auditable artifact before EvaluationSpec, SplitManifest, modeling, or leaderboard comparison depend on it.
- Auth is stubbed as local single-user behavior.
