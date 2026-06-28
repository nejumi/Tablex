# Benchmark Dataset Catalog & Import Harness Goal

## Goal

Add a curated benchmark dataset catalog and a local import path so Tablex can exercise realistic tabular prediction workflows without storing external credentials. The first catalog emphasizes multi-table, time-series, imbalanced classification, and compact smoke-test datasets.

## Implemented

- Added `benchmarks/catalog.json` with Kaggle Home Credit, Home Credit Model Stability, IEEE-CIS Fraud, Store Sales, M5, Rossmann, Instacart, and UCI Bank Marketing entries.
- Added `schemas/benchmark_catalog.schema.json`.
- Added backend benchmark service for:
  - catalog loading
  - default local root calculation under `HARNESS_DATA_DIR/benchmarks`
  - required/recommended file status
  - primary table selection
  - import manifest construction
- Added API endpoints:
  - `GET /api/benchmarks`
  - `GET /api/benchmarks/{benchmark_id}`
  - `GET /api/benchmarks/{benchmark_id}/local-status`
  - `POST /api/projects/{project_id}/benchmarks/{benchmark_id}/import`
- Added `import_benchmark_dataset` as a supported Job type.
- Benchmark import copies the primary CSV/Parquet table to the artifact store, profiles it through the existing DatasetSnapshot pipeline, and stores a `benchmark_import_manifest` artifact.
- Data tab now shows a Benchmark Dataset Catalog with source links, local path, primary table, target, local readiness, and import action.
- Added integration coverage for catalog listing, missing-file validation, UCI-style local import, target propagation, manifest artifact preview, and benchmark source metadata.

## Design Choices

- Kaggle and other source credentials remain user-managed outside Tablex.
- API imports are restricted to `HARNESS_DATA_DIR/benchmarks` to avoid accidental secret or arbitrary local file ingestion.
- v0 imports only the primary table because current DatasetSnapshot and profiler are single-table. Supporting tables are recorded in the manifest for future multi-table FeatureRecipe and AgentTask work.
- The catalog is cross-project metadata rather than a DB table for now. Project-specific imports become DatasetSnapshot, Artifact, Job, and Lineage records.

## Deferred

- Native Kaggle download orchestration.
- Multi-table DatasetSnapshot bundles and relational schema inference.
- Automatic join graph discovery.
- Benchmark-specific starter FeatureRecipes.
- Built-in sample subsets for CI-friendly full pipeline benchmarks.
- UI-side local-status refresh for custom path overrides.

## Risks And Open Decisions

- Kaggle competition file names and terms can change; catalog entries should be reviewed periodically.
- Large datasets should not be copied wholesale into artifacts until bundle import and retention policies are designed.
- Home Credit Model Stability and M5 need task-specific transformations before strong baseline runs are meaningful.
- For production-like benchmark comparisons, time and group splits should replace random splits whenever row semantics support them.
