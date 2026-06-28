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
curl http://localhost:8000/api/benchmarks/kaggle_home_credit_default_risk/local-status
```

Import the primary table into a project:

```bash
curl -X POST http://localhost:8000/api/projects/{project_id}/benchmarks/uci_bank_marketing/import \
  -H 'Content-Type: application/json' \
  -d '{}'
```

The import creates:

- a `dataset_snapshot` artifact copied from the benchmark primary table
- a `DatasetSnapshot` with `source_type=benchmark_catalog`
- a `benchmark_import_manifest` artifact that records required/recommended file status
- a `relational_catalog` artifact with table profiles, key candidates, time candidates, leakage-name suspects, and inferred join graph
- an `import_benchmark_dataset` job record
- lineage from the manifest artifact to the DatasetSnapshot

## Scope

v0 creates one primary-table DatasetSnapshot and a relational catalog for the local bundle. Multi-table joins remain explicit future work for FeatureRecipes and AgentTasks. The relational catalog gives future runners table profile and join-planning context without copying every supporting table into the artifact store.

These datasets are benchmarks and smoke-test fixtures, not a fixed modeling strategy. Baselines and agent tasks should still inspect the current task, data semantics, EvaluationSpec, SplitManifest, quality gates, relevant Skills, and timely research before choosing an approach.
