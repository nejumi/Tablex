# Benchmark Dataset Catalog

Tablex keeps benchmark metadata in `benchmarks/catalog.json` and exposes it through `/api/benchmarks`.
Benchmark data files are not committed. Place extracted files under `data/benchmarks/<benchmark_id>/` on the machine running Tablex.

Do not paste Kaggle credentials, API tokens, connector credentials, or production write credentials into Tablex, prompts, AgentTaskContracts, or runner workspaces. Kaggle downloads are user-managed outside Tablex.

## Initial Catalog

| ID | Source | Why It Is Useful |
| --- | --- | --- |
| `kaggle_home_credit_default_risk` | [Kaggle Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk) | Multi-table credit-risk benchmark with realistic joins, imbalance, leakage risk, and prediction-time availability questions. |
| `kaggle_home_credit_model_stability` | [Kaggle Home Credit Credit Risk Model Stability](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability) | Larger parquet-heavy credit-risk benchmark for stability, drift, and relational feature planning. |
| `kaggle_ieee_cis_fraud_detection` | [Kaggle IEEE-CIS Fraud Detection](https://www.kaggle.com/competitions/ieee-fraud-detection) | Fraud classification with severe imbalance, transaction time, and identity side table joins. |
| `kaggle_store_sales_forecasting` | [Kaggle Store Sales](https://www.kaggle.com/competitions/store-sales-time-series-forecasting) | Retail forecasting with date, store, family, holidays, oil, and transaction covariates. |
| `kaggle_m5_forecasting_accuracy` | [Kaggle M5 Forecasting Accuracy](https://www.kaggle.com/competitions/m5-forecasting-accuracy) | Hierarchical/wide-format retail forecasting that should be transformed by a feature recipe or AgentTask before modeling. |
| `kaggle_rossmann_store_sales` | [Kaggle Rossmann Store Sales](https://www.kaggle.com/competitions/rossmann-store-sales) | Smaller retail time-series benchmark for quick lag/calendar feature and time split smoke tests. |
| `kaggle_instacart_market_basket` | [Kaggle Instacart Market Basket Analysis](https://www.kaggle.com/competitions/instacart-market-basket-analysis) | Multi-table order history benchmark for aggregation, group validation, and recommendation-like tabular framing. |
| `uci_bank_marketing` | [UCI Bank Marketing](https://archive.ics.uci.edu/dataset/222/bank+marketing) | Compact single-table smoke test for categorical preprocessing, target profiling, and leakage discussion around `duration`. |
| `uci_wine_quality` | [UCI Wine Quality](https://archive.ics.uci.edu/dataset/186/wine+quality) | Credential-free public dataset smoke test for regression/ordinal target framing and compact numeric features. |
| `openml_credit_g` | [OpenML credit-g](https://www.openml.org/d/31) | Credential-free credit-risk smoke test with many categorical fields, asymmetric cost caveat, and public CSV download. |

## Source Cards

Every catalog entry is exposed with a generated `benchmark_source_card.v1` shape. The card separates:

- `access`: credentialed competition, public direct archive, or manual public source.
- `official_sources`: source pages and public archive URLs verified for the catalog.
- `source_verification`: verified date, source count/types, and access checks.
- `table_bundle`: primary/supporting/holdout table counts, join hints, target hints, and feature-recipe policy.
- `credential_probe`: whether a harness-only Kaggle access check is available, its endpoint, and the guarantee that secret values are not returned or artifacted.
- `credential_inventory`: whether a harness-only Kaggle file-list inventory can be stored before download planning.
- `credential_policy`: secrets and connector credentials are never stored, inserted into prompts, or materialized into runner workspaces.
- `import_readiness`: whether local files are present and what action should happen next.
- `fixture`: whether a credential-free synthetic smoke fixture is available.

Kaggle datasets remain credentialed, but Tablex can now run harness-owned access probes and file inventories before download work. The probe reads `KAGGLE_API_TOKEN`, `KAGGLE_USERNAME`, and/or `KAGGLE_KEY` from the harness process environment or gitignored `.env`, calls the Kaggle competition file-list API, and stores a `kaggle_credential_probe.v1` artifact containing only secret-free status, HTTP status, credential source labels, and next actions. The inventory endpoint stores `kaggle_competition_file_inventory.v1` with file names, sizes, catalog role mapping, and missing required file summary. Neither endpoint passes credential values to Codex, AgentRunner, AgentTaskContracts, runner workspaces, logs, or artifacts. Public UCI archives and selected OpenML CSV exports are credential-free and can be downloaded by the managed public-download endpoint when `source_card.access.supports_direct_download=true` and `requires_account=false`.

## Local Layout

The v0 importer restricts file reads to `HARNESS_DATA_DIR/benchmarks`, defaulting to `data/benchmarks`.

Example for Home Credit Default Risk:

```bash
mkdir -p data/benchmarks/kaggle_home_credit_default_risk
kaggle competitions download \
  -c home-credit-default-risk \
  -p data/benchmarks/kaggle_home_credit_default_risk \
  --unzip
```

Example for UCI Bank Marketing:

```bash
mkdir -p data/benchmarks/uci_bank_marketing
# Download bank.zip from UCI, extract it, then place bank-full.csv here:
ls data/benchmarks/uci_bank_marketing/bank-full.csv
```

## API

List catalog entries and local file status:

```bash
curl http://localhost:8000/api/benchmarks
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/source-card
curl http://localhost:8000/api/benchmarks/uci_bank_marketing/import-readiness
curl http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/local-status
```

Probe Kaggle account access without exposing secrets to agents:

```bash
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/probe
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory
curl http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/kaggle/inventory/latest
```

The probe and inventory accept modern JSON or opaque `KAGGLE_API_TOKEN` values, `KAGGLE_USERNAME` plus `KAGGLE_API_TOKEN`, and legacy `KAGGLE_USERNAME` plus `KAGGLE_KEY`. If the API returns `forbidden_or_rules_required`, open the competition in Kaggle, accept the rules with the user account, and rerun the endpoint.

Download and safely extract a credential-free public archive or direct public file:

```bash
curl -X POST http://localhost:8000/api/benchmarks/uci_wine_quality/public-download \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
curl -X POST http://localhost:8000/api/benchmarks/openml_credit_g/public-download \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
```

The public downloader only uses catalog-configured URLs. It rejects credentialed sources, enforces a size limit, extracts only configured expected zip filenames or places one configured direct CSV/Parquet file, flattens those files into `data/benchmarks/{benchmark_id}`, skips unsafe zip members such as absolute paths or `..`, and stores a `benchmark_public_download_manifest` artifact.

Run a full credential-free public benchmark workflow:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/openml_credit_g/public-workflow \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
```

The public workflow runs download, local readiness, primary-table import, profiling, quality gate, evaluation scenario comparison, approval, SplitManifest generation, adaptive BaselineStrategyPlan, baseline execution, diagnostics, run report, visualization dashboard, insights, decision dashboard/report, and BenchmarkScenarioPack. It rejects credentialed sources such as Kaggle competitions because Tablex must not receive or pass account credentials to agents.

Create a project-scoped collection plan across the full catalog:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/collection-plan
```

The collection plan creates `benchmark_collection_plan`, `benchmark_collection_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. It ranks entries by practical use:

- Home Credit Default Risk as the primary real-world multi-table credit-risk benchmark once the user downloads Kaggle files outside Tablex.
- Home Credit Model Stability as a larger parquet/stability benchmark for later stress tests.
- OpenML credit-g, UCI Bank Marketing, and UCI Wine Quality as credential-free public smoke tests.
- Store Sales, M5, Rossmann, and Instacart as time-series, hierarchical, or multi-table planning targets once local files are available.

The plan records `credentialed_manual_download_required`, `public_workflow_available`, `fixture_smoke_available`, and `ready_to_import` statuses without downloading data or storing credentials.

Generate a credential-free local fixture for supported benchmarks:

```bash
curl -X POST http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/fixtures/generate \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
```

Supported v0 fixtures:

- `kaggle_home_credit_default_risk`: tiny multi-table credit-risk fixture.
- `kaggle_store_sales_forecasting`: tiny retail time-series fixture.
- `uci_bank_marketing`: tiny single-table semicolon-delimited fixture.
- `uci_wine_quality`: tiny public-source semicolon-delimited wine quality fixture.

Import the primary table into a project:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/import \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Create a scenario pack/report for the imported benchmark context:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/scenario-pack
```

Create a train-fold-safe relational feature plan after importing a multi-table benchmark:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-plan
```

The relational feature plan reads the latest `relational_catalog`, benchmark scenario/source context, data quality and evaluation artifacts, and benchmark collection plan. It creates `relational_feature_plan`, `relational_feature_report`, and `visualization_spec` artifacts plus Report, Evidence, and Lineage. The plan proposes aggregation candidates and guardrails only; confirmed FeatureRecipes or AgentTasks still need to implement joins with SplitManifest discipline and prediction-time availability checks.

Build a preview-only relational feature recipe from the latest plan:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-recipe/build
```

The recipe builder materializes `relational_feature_recipe`, `relational_feature_preview` CSV, `relational_feature_preview_profile`, `relational_feature_recipe_report`, and `visualization_spec` artifacts plus Evidence and Lineage. It is intentionally bounded to small local supporting table artifacts and safe aggregate previews. It excludes target/leakage/holdout-suspect columns, defers point-in-time-unconfirmed candidates, and passes the recipe summary into AgentTaskContracts and AgentContextPacks as context rather than a fixed modeling strategy.

Diagnose relational feature scenarios from the latest recipe preview:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/features/relational-scenarios/diagnose
```

The diagnostics endpoint creates `relational_feature_scenario_diagnostics`, `relational_feature_scenario_report`, and `visualization_spec` artifacts plus Evidence and Lineage. It does not train XGBoost or any other fixed model. Instead it measures generated feature usability, missingness, constant/high-cardinality flags, split compatibility, deferred reasons, and recommended AgentTask scenarios so the runner can later choose an approach from evidence, Skills, and evaluation constraints.

Benchmark Evidence Packs and Decision Reports now surface the latest relational plan, recipe, and scenario diagnostics. Use them as the high-level report view when comparing Home Credit-style multi-table readiness, deferred safety checks, and runner handoff scenarios.

Run the fixture smoke harness for a project:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/kaggle_home_credit_default_risk/fixture-smoke \
  -H 'Content-Type: application/json' \
  -d '{"overwrite":false}'
```

The smoke harness generates the fixture, imports the benchmark primary table, runs DataQualityGate, creates EvaluationScenarioComparison and EvaluationApprovalReview artifacts, approves the spec when no explicit blockers remain, generates a SplitManifest, stores a BaselineStrategyPlan, creates a controlled ResearchPlan, and writes BenchmarkScenarioPack/Report artifacts. It does not run the full baseline model.

The import creates:

- a `dataset_snapshot` artifact copied from the benchmark primary table
- a `DatasetSnapshot` with `source_type=benchmark_catalog`
- a `benchmark_import_manifest` artifact that records required/recommended file status
- a `relational_catalog` artifact with table profiles, key candidates, time candidates, leakage-name suspects, and inferred join graph
- `benchmark_supporting_table` artifacts for small supporting CSV/Parquet files, with large files skipped rather than copied blindly
- an `import_benchmark_dataset` job record
- lineage from the manifest artifact to the DatasetSnapshot

The scenario pack creates:

- a `benchmark_scenario_pack` JSON artifact shaped by `schemas/benchmark_scenario_pack.schema.json`
- a `benchmark_scenario_report` Markdown artifact previewable in the UI
- runner handoff notes for SplitManifest discipline, holdout-table exclusion, fixture score policy, and recommended Skill/research query directions
- report expectations for leaderboard, assumptions, relational coverage, time-series slices, or other scenario-specific views

## Scope

v0 creates one primary-table DatasetSnapshot and a relational catalog for the local bundle. Multi-table joins remain explicit future work for FeatureRecipes and AgentTasks. The relational catalog gives future runners table profile and join-planning context without copying every supporting table into the artifact store.

Fixtures are synthetic and deliberately small. They are for product smoke tests, not benchmark scoring, leaderboard claims, model quality comparison, or literature-backed baseline selection.

These datasets are benchmarks and smoke-test fixtures, not a fixed modeling strategy. BaselineStrategyPlan artifacts now record `adaptive_baseline_planning`, candidate strategies, runner scope, Skill/library context, and reporting/visualization expectations. Baselines and agent tasks should still inspect the current task, data semantics, EvaluationSpec, SplitManifest, quality gates, relevant Skills, and timely research before choosing an approach.
