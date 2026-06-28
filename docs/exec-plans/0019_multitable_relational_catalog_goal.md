# Multi-table Benchmark Bundle & Relational Profiling Goal

## Goal

Make benchmark imports useful for Home Credit-style multi-table datasets by creating artifact-backed relational context, while keeping Project DatasetSnapshot semantics simple and controlled.

## Implemented

- Added lightweight multi-table bundle profiling for benchmark local roots.
- Import now creates a `relational_catalog` artifact alongside the primary `DatasetSnapshot` and `benchmark_import_manifest`.
- The relational catalog records:
  - discovered required/recommended CSV/Parquet files
  - per-table row count, column count, schema hash, column profiles, key candidates, time candidates, and leakage-name suspects
  - inferred shared-key relationships and confidence notes
  - target locations, evaluation guidance, risk notes, and AgentContext notes
- Added `schemas/relational_catalog.schema.json`.
- Added `relational_context` to AgentContextPack and copies `relational_catalog.json` into controlled runner workspaces.
- Extended import job output with `relational_catalog_artifact_id`, `table_count`, and `relationship_count`.
- Added Data tab panels for relational catalog listing and preview.
- Added tests for UCI single-table import and Home Credit-style shared-key inference.

## Design Choices

- No Kaggle credentials are handled by Tablex or agent runners.
- The importer reads benchmark files under `HARNESS_DATA_DIR/benchmarks` only.
- The primary table remains the only DatasetSnapshot in v0; supporting tables are artifact-backed context.
- Supporting table profiling is best effort. A failed supporting table records an error in the catalog rather than blocking the primary import.
- Join graph edges are inference, not truth. They require human or agent validation before being used in modeling.

## Deferred

- First-class DatasetBundle DB model.
- Materialized multi-table feature matrices.
- Join validation with cardinality checks and leakage scenario comparison.
- Bundle-level preview UI beyond JSON artifact preview.
- Benchmark-specific starter FeatureRecipes.

## Risks And Open Decisions

- Approximate distinct counts can be expensive on very wide or very large files; the v0 profiler skips detailed column stats beyond 80 columns.
- Name-based key inference can over-link unrelated ID columns.
- Relational catalogs should be refreshed if source files change.
