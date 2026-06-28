# 0031 Managed Public Benchmark Download Goal

## Goal

Add a managed download path for credential-free benchmark archives while keeping credentialed sources such as Kaggle user-managed outside Tablex.

## Implementation Direction

- Only enable managed download when `BenchmarkSourceCard.access.supports_direct_download=true` and `requires_account=false`.
- Use only catalog-configured URLs. Do not accept arbitrary user-provided URLs.
- Download into `HARNESS_DATA_DIR/benchmarks/{benchmark_id}/_downloads`.
- Extract only configured expected zip filenames.
- Flatten expected files into the benchmark root so the existing importer can find them.
- Skip unsafe zip members with absolute paths or `..`.
- Store a `benchmark_public_download_manifest` artifact and job output for auditability.

## Implemented Scope

- Added `BenchmarkPublicDownloadRequest`.
- Added `download_public_benchmark_archive` job type.
- Added `/api/benchmarks/{benchmark_id}/public-download`.
- Added `benchmark_public_download_manifest.v1` schema.
- Added public download action to benchmark cards in the Data tab.
- Added local HTTP-server integration test with a synthetic zip archive, expected-file extraction, ignored extra files, and unsafe path skipping.

## Deferred Scope

- Checksum pinning for official archives.
- Retry/resume support.
- Tar and gzip archive support.
- User-approved connector flow for credentialed sources.
- Progress reporting for large downloads.

## Validation Plan

- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- Docker build and `/healthz` smoke.
