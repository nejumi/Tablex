# 0032 Benchmark & Adaptive Baseline Harness Goal

## Goal

Extend the benchmark and baseline harness so Tablex can support realistic benchmark workflows without turning any one baseline into a fixed product policy.

## Sources Checked

- Kaggle competition catalog entries already in `benchmarks/catalog.json`, especially Home Credit Default Risk and Home Credit Credit Risk Model Stability.
- UCI public source entries already in the catalog for Bank Marketing and Wine Quality.
- OpenML API checks on 2026-06-29 for `adult`, `Titanic`, and `credit-g`; `credit-g` dataset id 31 exposes public metadata, default target `class`, and a working CSV endpoint.

## Implementation

- Added `source_verification` and `table_bundle` to generated `benchmark_source_card.v1` payloads.
- Added `openml_credit_g` as a credential-free public CSV benchmark source.
- Extended managed public benchmark download from zip-only extraction to support a single direct CSV/Parquet file.
- Expanded `baseline_strategy_plan.v1` with:
  - `adaptive_baseline_planning` strategy mode
  - Skill/library semantic tag context
  - runner policy and dependency checks
  - explicit local-run versus AgentTask scope
  - reporting and visualization expectations
- Updated the UI to show benchmark verification/bundle facts and auto-preview new BaselineStrategyPlan artifacts.

## Deferred

- Full Kaggle API integration remains out of scope because credentials must stay user-managed outside Tablex.
- OpenML ARFF conversion is deferred; v0 only imports CSV/Parquet, so the catalog uses OpenML's CSV export endpoint.
- Relational feature execution remains an AgentTask/FeatureRecipe target rather than automatic joins in the local baseline runner.
- Literature-backed approach selection is represented as controlled research policy and Skill context; live runner-side web search is still future work.

## Risks

- OpenML CSV endpoint shape may change; SourceCard records official metadata/API URLs so users can verify if a download fails.
- Baseline strategy artifacts can match zero library assets until `/api/assets/seed-defaults` has been run.
- Home Credit fixture smoke validates workflow, not benchmark performance.
