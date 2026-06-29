# Development Guide

## Local Setup

Backend requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

To run downloaded analysis notebooks locally, install the optional analysis extra:

```bash
pip install -e ".[analysis]"
```

Frontend requires Node.js 20 or newer.

```bash
cd apps/frontend
npm install
```

## Frontend Mascot Assets

Mascot assets live under `apps/frontend/public/mascot`. `Tablee` is the current mascot concept name, not a final product name. Use the SVG variants for compact surfaces and the transparent PNG only for larger guidance or empty-state moments. Keep copy in locale messages rather than baking text into graphics.

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
Dataset upload and benchmark import use DuckDB-backed profiling. Small files receive full per-column missingness and unique-count statistics. Larger or wider files automatically use `bounded_sample` mode: schema and row count remain exact, target profiling still runs when a target is supplied, and column-level missingness/unique counts are sample-backed with deferred deep-profile metadata in `profile.json`. This keeps Home Credit-scale imports responsive while making the estimation boundary visible in the UI and artifacts.
The baseline runner uses XGBoost as the strong local baseline when the dataset signals justify a single-table mixed-type run. It builds persisted `baseline_plan`, `baseline_strategy_plan`, `feature_recipe`, `baseline_report`, `baseline_metrics`, validation prediction, and `model_package.joblib` artifacts. Successful strong baseline runs also create a `ModelVersion` record linked to the package artifact. The runner applies numeric median imputation, categorical ordinal encoding, text TF-IDF, datetime calendar features, and falls back to LogisticRegression/Ridge or majority/mean sanity baselines if the strong run fails. Lag and rolling covariate features are enabled only when the approved EvaluationSpec uses a time split. Strategy planning is profile-driven and records `planning_source`, profile boundary, and `resource_guard`; it should remain fast on Home Credit-scale data while full baseline execution may take minutes and is reported as a guarded local run rather than a fixed AutoML recipe.

Create a baseline strategy artifact without running the model:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/baseline/strategy-plan
```

The strategy plan records `adaptive_baseline_planning`, sanity-floor, strong single-table, text TF-IDF, categorical, datetime, time-series, and relational aggregation candidates. It also stores runner scope, dependency checks, Skill/library semantic tag matches, next AgentTasks, and reporting/visualization expectations. Relational aggregation is marked as AgentTask work until join semantics and prediction-time availability are validated.

Saved ModelVersion packages can be replay-validated from the Assets tab or with:

```bash
curl -X POST http://localhost:8000/api/model-versions/{model_version_id}/validate
```

The validation job reloads `model_package.joblib`, rebuilds validation features from the linked DatasetSnapshot and SplitManifest, recomputes metrics, and stores `model_validation_report`, `model_validation_metrics`, and `prediction_replay` artifacts with lineage from the ModelVersion.

Project job history is available from:

```bash
curl http://localhost:8000/api/projects/{project_id}/jobs
curl http://localhost:8000/api/jobs/{job_id}/artifacts
```

`/api/jobs/{job_id}/artifacts` resolves artifact ids from job outputs, summarizes benchmark/run/model/metric context, and returns preview/download-ready Artifact records for workflow jobs.

Analysis notebooks can be generated after a DatasetSnapshot/profile exists:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/analysis-notebooks/data-understanding
curl -X POST http://localhost:8000/api/runs/{run_id}/analysis-notebook
curl http://localhost:8000/api/projects/{project_id}/analysis-notebooks
curl -X POST http://localhost:8000/api/analysis-notebooks/{analysis_notebook_artifact_id}/execution-plan
```

The Data Understanding notebook job stores `analysis_notebook`, `notebook_html`, `notebook_run_manifest`, and `notebook_report` artifacts. The run-level model diagnostics notebook adds a `visualization_spec` summary and consumes existing run/model artifacts such as `baseline_metrics`, `prediction_output`, `evaluation_diagnostics`, `model_validation_metrics`, and `model_package` references when present. The project notebook index returns grouped history, coverage flags, a recommended notebook, and preview/download artifact ids for the Notebooks tab and Reports tab Notebook Center. The source notebook is a marimo `.py` file with pandas, matplotlib, and Plotly cells. The HTML preview is rendered inside the Notebooks, Reports, and Experiments tabs through the artifact preview API, so users do not need an external notebook server for first inspection. The execution-plan endpoint stores `agent_task_contract` and `notebook_execution_plan` artifacts for a future controlled runner; it does not execute notebook code. Plans require artifact capture, human review, no secret or connector credential materialization, no external network by default, and preservation of EvaluationSpec/SplitManifest boundaries. The current milestone generates and stores notebooks and execution plans but does not execute marimo; manifests record `generated_not_executed` or `planned_not_executed`, disabled external network access, and that secrets/connector credentials are not embedded. Future controlled runners should capture executed figures, tables, feature importance, permutation importance, partial dependence, calibration, threshold analysis, slice metrics, and prediction analysis as additional artifacts.

Project Guidance is available from:

```bash
curl http://localhost:8000/api/projects/{project_id}/guidance
curl -X POST http://localhost:8000/api/projects/{project_id}/guidance/snapshot
curl -X POST http://localhost:8000/api/projects/{project_id}/guidance/snapshots/compare
```

The response is `project_guidance.v1`. It is harness-owned decision support for the UI Focus Guide: one recommended focus, primary/secondary actions, state summary, supporting counts, and AgentRunner guidance. Actions can navigate, call a safe harness endpoint, or create a scoped AgentTaskContract. Approach-stage guidance should preserve flexibility by giving Codex a bounded prompt and current evidence rather than forcing a fixed modeling recipe.
The same response also includes `journey_stages` and `current_stage_id` for the Guided Journey rail. Stage statuses are `done`, `current`, `next`, `blocked`, or `waiting`; stage actions reuse `ProjectGuidanceAction` so the UI can open the relevant tab, call a harness endpoint, or create a scoped AgentTaskContract while leaving approach selection open-ended.
`/guidance/snapshot` saves the current Guided Journey state as a `guided_journey_snapshot` JSON artifact, `guided_journey_report` Markdown artifact/Report, and `visualization_spec` stage-status artifact with lineage. It is useful before asking Codex for a larger next task or when capturing a decision checkpoint for review.
`/guidance/snapshots/compare` compares the latest two saved Guided Journey snapshots and stores `guided_journey_comparison`, `guided_journey_comparison_report`, and a comparison `visualization_spec` with lineage from both source snapshots. The Reports tab surfaces these in Guidance History.

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
When the source EDA profile is `bounded_sample`, duplicate and target-proxy checks run against a materialized sample table and the gate records `profile_boundary.quality_check_scope=sample`, sample row count, and deferred deep-profile status. Reports and UI metadata expose that boundary so downstream EvaluationSpec, AgentTask, and reporting steps do not confuse sample-backed checks with full-table guarantees.

Assumption review queue:

```bash
curl http://localhost:8000/api/projects/{project_id}/assumptions/review-queue
```

The response is `assumption_review_queue.v1`. It merges unresolved Assumptions and unanswered Questions into a prioritized one-item-at-a-time review queue using risk level, fallback policy, confirmation requirement, question priority, blocking flags, and confidence. The UI uses this before the full Assumptions table so users can confirm, challenge, or answer the most important item without scanning every assumption first.

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
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/source-card
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/import-readiness
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/local-status
curl -X POST http://localhost:8000/api/benchmarks/uci_wine_quality/public-download \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/benchmarks/openml_credit_g/public-download \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/probe
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory
curl http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory/latest
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/download \
  -H 'Content-Type: application/json' \
  -d '{"include_required":true,"include_recommended":false,"include_holdout":false,"overwrite":false,"max_total_bytes":524288000}'
curl -X POST http://localhost:8000/api/benchmarks/uci_bank_marketing/fixtures/generate \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/import \
  -H 'Content-Type: application/json' \
  -d '{}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/openml_credit_g/public-workflow \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/collection-plan
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-plan
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-recipe/build
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-scenarios/diagnose
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/evidence-pack
```

Place extracted benchmark files under `data/benchmarks/{benchmark_id}` or another path below `HARNESS_DATA_DIR/benchmarks`. Kaggle credentials and API tokens are user-managed by the harness process only and must not be pasted into prompts, AgentTaskContracts, or runner workspaces. The Kaggle probe endpoint can read `KAGGLE_API_TOKEN`, `KAGGLE_USERNAME`, and/or `KAGGLE_KEY` from the process environment or a gitignored `.env`, checks competition file-list access, and stores only a secret-free `kaggle_credential_probe` artifact. The inventory endpoint uses the same boundary to store a `kaggle_competition_file_inventory` artifact with file names, sizes, catalog role mapping, and missing required file summary before any download is attempted. The selective download endpoint uses that same harness-only boundary to download catalog-required or explicitly selected files under the benchmark root with a size cap, SHA-256 hashes, skipped reasons, local status, and import readiness in a secret-free manifest. It supports JSON API tokens, `username:key` tokens, `KAGGLE_USERNAME` plus `KAGGLE_API_TOKEN`, and legacy `KAGGLE_USERNAME` plus `KAGGLE_KEY`; token values are not returned, logged, artifacted, or passed to Codex/AgentRunner. Source-card endpoints distinguish credentialed competition datasets from credential-free public archives or direct files such as UCI Bank Marketing, UCI Wine Quality, and OpenML credit-g. Public-download endpoints are only enabled for credential-free direct sources; they flatten configured expected zip members or one configured direct CSV/Parquet file into the benchmark root, skip unsafe paths, and store a `benchmark_public_download_manifest` artifact. Public-workflow endpoints run the credential-free path end to end: download, import, profile, quality, evaluation approval, SplitManifest, adaptive baseline strategy, baseline run, diagnostics, run report, visualization dashboard, insights, decision dashboard/report, and BenchmarkScenarioPack. The importer profiles one primary CSV/Parquet table, stores a `benchmark_import_manifest`, creates a `relational_catalog` artifact with table profiles and inferred join-key context for supporting files, and registers small supporting CSV/Parquet tables as `benchmark_supporting_table` artifacts with a size cap. `scenario-pack` creates `benchmark_scenario_pack` and `benchmark_scenario_report` artifacts that summarize benchmark intent, fixture status, artifact readiness, runner guardrails, and report expectations. Fixture endpoints generate tiny synthetic files for smoke tests only; they do not download or store external benchmark data. See `docs/benchmarks.md`.

`/api/projects/{project_id}/benchmarks/evidence-pack` creates `benchmark_evidence_pack`, `benchmark_evidence_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage records. It aggregates benchmark source cards, local status, imports, relational catalogs, scenario packs, public/fixture workflow jobs, experiment runs, reports, visualizations, AgentTaskContracts, readiness reviews, and local stub AgentResults into an in-product summary. It does not download data or call external dashboards.

`/api/projects/{project_id}/benchmarks/collection-plan` creates `benchmark_collection_plan`, `benchmark_collection_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. It ranks Home Credit and other practical benchmarks by source readiness, credential policy, local file status, fixture availability, public workflow availability, multi-table/time-series shape, and recommended next action. It does not download data and never stores Kaggle credentials.

`/api/projects/{project_id}/features/relational-plan` requires a `relational_catalog` artifact, then creates `relational_feature_plan`, `relational_feature_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. It proposes train-fold-safe relational aggregation candidates, point-in-time requirements, leakage and prediction-time availability risks, deferred AgentTask questions, and FeatureRecipe/Skill references. It is a planning artifact, not executable join code. AgentTaskContracts, ResearchPlans, ResearchBriefs, Ideas, and AgentContextPacks include the latest relational feature plan when available.

`/api/projects/{project_id}/features/relational-recipe/build` requires the latest `relational_feature_plan`, `relational_catalog`, primary DatasetSnapshot, and small registered supporting table artifacts. It creates a preview-only `relational_feature_recipe`, `relational_feature_preview` CSV, `relational_feature_preview_profile`, `relational_feature_recipe_report`, `visualization_spec`, Evidence, and Lineage. v1 executes safe count/nunique/numeric aggregate previews with DuckDB, excludes target/leakage/holdout-suspect columns, defers point-in-time-unconfirmed candidates, and records that production training must fit aggregations inside training folds. AgentTaskContracts, ResearchBriefs, Ideas, and AgentContextPacks include the latest recipe summary when available.

`/api/projects/{project_id}/features/relational-scenarios/diagnose` requires the latest relational recipe preview artifacts. It creates `relational_feature_scenario_diagnostics`, `relational_feature_scenario_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. The endpoint does not train a model; it compares primary-table-only, safe relational preview, deferred relational feature, and evaluation-readiness scenarios through feature coverage, missingness, constant/high-cardinality flags, split compatibility, deferred reasons, and AgentTask scenario recommendations. AgentTaskContracts, ResearchBriefs, Ideas, and AgentContextPacks include the latest diagnostics summary when available.

Benchmark Evidence Packs, Decision Dashboards/Reports, and drafted Project Reports include the latest relational plan, recipe, and scenario diagnostics when available. This keeps relational feature readiness, deferred reasons, and recommended AgentTask scenarios visible in normal in-product reports without requiring users to manually inspect raw artifacts.

Artifact preview and download are available from:

```bash
curl http://localhost:8000/api/artifacts/{artifact_id}/preview
curl -L -o artifact.bin http://localhost:8000/api/artifacts/{artifact_id}/download
```

Preview is intentionally limited to UTF-8 text-like artifacts such as JSON, Markdown, CSV, TSV, YAML, TXT, and log files. Binary artifacts such as `model_package.joblib` are downloadable but not previewed.

Approach Studio endpoints:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/research-plan
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/research-source-pack
curl -X POST http://localhost:8000/api/research-source-packs/{artifact_id}/run-local-stub
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/research-synthesis
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

`/approach/research-source-pack` writes `research_source_pack` and `research_source_report` artifacts, a Report record, Evidence, and Lineage. It turns the latest ResearchPlan, project artifacts, recommended cross-project library assets, and benchmark source cards into a controlled source handoff for future Codex, Skill, or web/literature research runners. The endpoint does not execute network search; it records controlled query candidates, required citation fields, source risk policy, freshness expectations, and connector-credential restrictions. New AgentTaskContracts include the latest source pack id, source policy, citation requirements, and freshness expectations in their planning inputs.

`/api/research-source-packs/{artifact_id}/run-local-stub` executes a ResearchTask stub, not an AgentTask. It validates the Research Source Pack and stores `research_run_manifest`, `research_findings_report`, `source_citation_manifest`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. The stub records `external_network_accessed=false` and `connector_credentials_materialized=false`; it exists to harden the future controlled web/literature/Skill research runner contract before real retrieval is enabled.

`/approach/research-synthesis` writes `research_finding_synthesis`, `research_finding_synthesis_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. It consolidates the latest ResearchPlan, Research Source Pack, ResearchRunManifest, source citation manifest, benchmark context, and baseline strategy context into a compact handoff for flexible approach planning. AgentTaskContracts and AgentContextPacks include the latest synthesis artifact id, summary, citation audit, follow-up requirements, and runner handoff notes. Stub-only findings remain marked as weak evidence and must not be treated as verified external research.

`prepare-agent-context` writes an `agent_context_pack` artifact validated by `schemas/agent_context_pack.schema.json`. The pack includes harness-owned data/evaluation references, SplitManifest context, artifact preview/download references, locked cross-project asset references, ResearchPlan-recommended library assets, research policy, safety controls, and the required output contract. Library assets are recommendations and citations for runner planning, not fixed recipes that the harness forces the runner to execute. It does not pass secrets or connector credentials to the agent.

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

The Reports tab renders `visualization_spec.v1` records with typed UI previews for metric cards, category bars, stage status tables, leaderboard/diagnostic/experiment bars, and agent artifact checklists. Unknown specs still fall back to a compact data table so users do not need to inspect raw JSON first.

`/decision-dashboard/generate` creates a `decision_dashboard` JSON artifact shaped by `schemas/decision_dashboard.schema.json`, a `decision_report` Markdown artifact, a Report record, and three decision `visualization_spec` records. It summarizes readiness stages, artifact completeness, high-risk assumptions/questions, benchmark fixture policy, next actions, and report/visualization expectations.

Approach Ideas are not fixed recipes. They are evidence-backed proposals with `AgentTaskContract` payloads for future Codex, Skill-library, and controlled web or literature research runners. The harness still owns EvaluationSpec, SplitManifest, artifacts, lineage, safety controls, and report outputs.

The project UI includes a persistent Agent Chat dock across project tabs. Submitting text there does not send users to an external Codex surface; it creates a harness-owned `AgentTaskContract` using the current project context, so later Codex/LocalStub runners still operate through Tablex approvals, artifacts, lineage, safety policy, and reporting requirements.

The top-right User Settings icon stores local workbench preferences in browser `localStorage`. Display theme supports Light and Dark through `document.documentElement.dataset.theme`. Language settings are LocalePack-based rather than a fixed language enum: built-in packs are `en-US` and `ja-JP`, and any missing locale can be added as a local dynamic pack that falls back to English for untranslated keys. App shell, tabs, common actions, create-project controls, settings, and persistent Agent Chat copy are LocalePack-driven. Creating a localization task from settings posts `task_type=generate_locale_pack` to `/api/projects/{project_id}/approach/agent-task-plan`; it produces a harness-owned AgentTaskContract and must not include secrets or connector credentials.

Locale scope is intentionally tiered:

- Tier 1: App chrome, navigation tabs, global controls, form placeholders, settings, and chat affordances should be LocalePack-driven.
- Tier 2: Reusable panel titles, table headers, tooltips, and empty-state guidance should move into LocalePacks as components are split out.
- Tier 3: Artifact/report/runner-generated content should not be silently UI-translated. It should be localized by creating explicit translated Report/Artifact assets with lineage.
- Tier 4: Dataset values, column names, status enum values, IDs, artifact names, schema names, and runner contract fields remain source data unless a task explicitly creates a mapped display layer.

Tier3 Translate buttons on preview surfaces call harness-owned translation endpoints:

```bash
curl -X POST http://localhost:8000/api/artifacts/{artifact_id}/translate \
  -H 'Content-Type: application/json' \
  -d '{"source_locale":"en-US","target_locale":"ja-JP"}'
curl -X POST http://localhost:8000/api/reports/{report_id}/translate \
  -H 'Content-Type: application/json' \
  -d '{"source_locale":"en-US","target_locale":"ja-JP"}'
```

Each request creates a `translate_tier3_content` Job, a Codex-ready `agent_task_contract` artifact, a derived translated artifact/report, and lineage back to the English source artifact/report. The MVP does not silently execute Codex CLI from the button yet; the generated contract is the handoff point for a configured Codex translation runner. Until that runner is enabled, the endpoint returns a local draft/fallback artifact so the UI can show an on-demand preview without mutating the source.

`/api/projects/{project_id}/approach/agent-task-plan` creates a runner-ready `agent_task_contract` artifact without executing Codex or any external network call:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/approach/agent-task-plan \
  -H 'Content-Type: application/json' \
  -d '{}'
curl -X POST http://localhost:8000/api/agent-task-contracts/{artifact_id}/prepare-workspace
curl -X POST http://localhost:8000/api/agent-task-contracts/{artifact_id}/readiness-review
curl -X POST http://localhost:8000/api/agent-task-contracts/{artifact_id}/run-local-stub
curl http://localhost:8000/api/jobs/{job_id}/artifacts
curl http://localhost:8000/api/projects/{project_id}/agent-task-results
```

The generated contract carries `agent_task_planning.v1` inputs: dataset/profile context, approved evaluation and SplitManifest constraints, open assumptions/questions, benchmark and relational context, Skill/library recommendations, flexible approach candidates, controlled research queries, reporting requirements, and artifact expectations. It is planning context, not a fixed baseline recipe.

`/api/agent-task-contracts/{artifact_id}/prepare-workspace` materializes a controlled workspace from the contract without starting a runner. The workspace contains `.harness/task_contract.json`, `.harness/agent_result.schema.json`, `.harness/execution_policy.json`, context artifacts, recommended library asset artifacts, and a README. Baseline strategy/plan/metrics/report, evaluation diagnostics/report, run report, DataQualityGate, benchmark import manifest, and relational context are copied when present so Codex, LocalStub, or future runners can inspect the current evidence without receiving secrets or connector credentials. Relational plan, recipe, preview CSV/profile, scenario diagnostics, and scenario reports are copied under `.harness/context/relational/` when present. It stores an `agent_workspace_manifest` artifact with source counts, relational source counts, skipped sources, safety policy, and lineage.

`/api/agent-task-contracts/{artifact_id}/readiness-review` checks whether the contract and optional workspace are ready for runner execution. It stores `agent_task_readiness_review`, `agent_task_readiness_report`, and `visualization_spec` artifacts plus a Report record. The review separates blockers from warnings across evaluation locks, target context, required outputs, safety policy, assumptions/questions, context artifacts, relational runner context, library assets, workspace manifest, and reporting expectations.

`/api/agent-task-contracts/{artifact_id}/run-local-stub` prepares a workspace if needed, regenerates readiness review, refuses execution when blockers exist, then runs `LocalStubAgentRunner` with network disabled. It ingests declared `AgentResult.artifacts` into the artifact store and registers a Report, Evidence, ExperimentRun, VisualizationSpec, and Lineage when metrics/visualization artifacts are present. If relational context was materialized in the workspace, LocalStub also writes `relational_runner_context_summary` and a relational context `visualization_spec` artifact, and includes the same inventory, scenario recommendations, and deferred safety checks in the report, metrics, and feature recipe. LocalStub also writes `approach_decision_trace`, which records open-ended runner autonomy, approaches considered, rejected fixed-recipe behavior, unverified hypotheses, and additional research/Skill needs. The LocalStub path writes `experiment_metrics.v1` with `execution_status=not_executed`; it does not execute Codex, external research, model training, or benchmark scoring.

AgentResults may include optional `evidence_sources`, `citations`, and `report_citations`. Ingestion stores or materializes a `source_citation_manifest`, `citation_audit_report`, citation Evidence, and a citation-audit `visualization_spec` so runner-side research claims remain inspectable inside Tablex. LocalStub emits a citation audit with `external_network_accessed=false` and `connector_credentials_materialized=false`; it records source policy compliance only, not model evidence.

`/api/projects/{project_id}/agent-task-results` returns a project-scoped workbench summary for `run_planned_agent_task_stub` and `run_agent_task` jobs. It resolves AgentResult artifacts, workspace/readiness artifacts, ExperimentRun registration, agent reports, citation audit reports, Evidence, citation visualizations, citation manifest counts, relational context summary counts, and approach decision trace status so the UI can show runner results without forcing users into raw job JSON or external dashboards.

`/api/ideas/{idea_id}/run-agent-task` currently uses `LocalStubAgentRunner`. It validates the AgentResult schema and persists `agent_task_report`, `feature_recipe`, `experiment_metrics`, `agent_result`, `source_citation_manifest`, `citation_audit_report`, and `visualization_spec` artifacts plus Evidence, ExperimentRun, VisualizationSpec, and Lineage. It does not run real Codex code or external web research yet. Prepare and inspect an AgentContextPack first when validating future runner behavior.

Agent task execution now materializes a controlled workspace under the local artifact root before invoking the runner. The workspace receives harness-owned context files such as AgentContextPack, ResearchPlan, ExperimentPlan, DataQualityGate, diagnostics, and recommended cross-project library asset artifacts under `.harness/context/library_assets/` when present. The run stores an `agent_workspace_manifest` artifact with source asset/version/reason metadata, then ingests relative paths declared in `AgentResult.artifacts` into the artifact store. Absolute paths and `..` escapes are rejected.

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

The default seed pack includes reusable assets for controlled approach research, mixed-type XGBoost-style tabular baselines, train-fold TF-IDF text features, causal time lag/rolling features, relational aggregation, time/entity validation reviews, evaluation diagnostics interpretation, decision reports, and readiness dashboard visualizations. ResearchPlan and AgentTask planning recommend these assets from data signals and available artifacts such as RelationalCatalog, BenchmarkScenarioPack, EvaluationDiagnostics, and DecisionDashboard. AgentTaskContracts carry recommended asset ids plus source policy, while AgentContextPacks and controlled workspaces materialize the corresponding asset version artifacts for runner handoff.

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
9. Review the Adaptive Strategy Brief in the Approach tab, use the quick actions, then open supporting Research context, Runner handoff, or Preview groups as needed.
10. Seed or attach reusable assets from the Library tab.
11. Prepare and preview AgentContextPacks or planned AgentTask workspaces from the Approach tab before agent execution.
12. Create and preview ExperimentPlans from the Approach tab.
13. Review, approve, cancel, retry, or process queued jobs from the Jobs tab.
14. Plan Agent Task or Plan Baseline from the Experiments tab to inspect flexible runner contracts, candidate strategies, and deferred AgentTask work.
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

## Adaptive Strategy Brief

The Approach tab can request live strategy guidance:

```bash
curl -s http://localhost:8000/api/projects/{project_id}/approach/strategy-brief
```

To persist the current strategy state as assets:

```bash
curl -s -X POST http://localhost:8000/api/projects/{project_id}/approach/strategy-brief
```

This creates an `adaptive_strategy_brief` JSON artifact, an `adaptive_strategy_report` Markdown artifact and Report row, and a `visualization_spec` artifact. The brief treats baseline plans as advisory evidence and keeps Codex handoff open-ended while preserving EvaluationSpec, SplitManifest, artifact registration, reporting, and credential boundaries.

When an AgentTaskContract is planned after an Adaptive Strategy Brief exists, the planner includes a compact `adaptive_strategy_brief` summary in the contract and copies the full Strategy Brief artifacts through `available_context_artifacts` during planned workspace preparation. AgentTask readiness includes an `adaptive_strategy_context` check.
