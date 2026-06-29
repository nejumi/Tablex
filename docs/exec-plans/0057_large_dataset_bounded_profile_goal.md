# 0057 Large Dataset Bounded Profile Goal

## Goal

Make primary-table import responsive for 100 MB class and wide CSV/Parquet files such as Kaggle Home Credit. The harness should preserve exact schema, row count, artifact lineage, target profile, and Data Understanding output while deferring expensive full-table per-column distinct/missing scans into an explicit deep-profile recommendation.

## Implementation Plan

- Add automatic `profile_mode` selection to `profile_tabular_file`.
- Keep small datasets on `full` profile mode.
- Switch to `bounded_sample` when file size, row count, or column count exceeds MVP thresholds.
- Compute exact row count and DuckDB schema before mode selection.
- Compute column missingness/unique counts on a bounded sample in `bounded_sample` mode.
- Store `profile_sample`, `column_stat_scope`, `missing_count_is_estimated`, `unique_count_is_approximate`, and `deferred_deep_profile` metadata in `profile.json`.
- Preserve target profiling on the full table when a target column is supplied.
- Surface profile mode, sample rows, and deep-profile recommendation in the Data UI.
- Add an `eda_profile.v1` JSON schema and tests for both full and bounded paths.

## In Scope

- Single-table CSV/Parquet profiling.
- Bounded sample column statistics.
- Artifact metadata for UI/report/AgentTask consumption.
- Home Credit `application_train.csv` import smoke.

## Out Of Scope

- Async deep-profile job execution.
- Cost-based per-column adaptive distinct algorithms.
- Full multi-table Home Credit import.
- Automatic model training on Home Credit.

## Risks and Open Questions

- CSV type inference still relies on DuckDB sniffing and can be improved later for very large files.
- Bounded sample currently uses deterministic first rows for reproducibility. Future work should add seeded random sampling when safe for the source format.
- Exact per-column missingness may be cheap enough to separate from exact distinct counts, but v1 defers both together to keep import latency predictable.
- A future `profile_dataset_deep` job should materialize exact or approximate distinct counts for selected columns without blocking the initial import.

## Verification Notes

- Unit tests cover full small-profile behavior and bounded sample behavior with exact row count, sample column stats, deferred columns, and identifier inference.
- Direct profiler smoke on `data/benchmarks/kaggle_home_credit_default_risk/application_train.csv` completed in about 50 seconds with `row_count=307511`, `column_count=122`, `profile_mode=bounded_sample`, `sample_row_count=50000`, and `deferred_column_count=122`.
- API import smoke for `kaggle_home_credit_default_risk` completed in about 69 seconds after the selective Kaggle download path materialized `application_train.csv`. It created DatasetSnapshot `ds_681b9a213237` and profile artifact `art_f68e98b2f5c3` with `deep_profile_recommended=true`.
