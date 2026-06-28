# 0029 Benchmark Source Cards Goal

## Goal

Add Benchmark/Data Source Harness v1 so practical benchmark datasets are represented as source cards with explicit access policy, credential handling, local import readiness, fixture availability, and official source references.

## Sources Checked

- Kaggle Home Credit Default Risk competition page: `https://www.kaggle.com/competitions/home-credit-default-risk`
- UCI Bank Marketing dataset page: `https://archive.ics.uci.edu/dataset/222/bank+marketing`
- UCI Bank Marketing public archive: `https://archive.ics.uci.edu/static/public/222/bank+marketing.zip`
- UCI Wine Quality dataset page: `https://archive.ics.uci.edu/dataset/186/wine+quality`
- UCI Wine Quality public archive: `https://archive.ics.uci.edu/static/public/186/wine+quality.zip`

## Implementation Direction

- Do not download or store credentialed benchmark data inside the repo.
- Keep Kaggle credentials and API tokens user-managed outside Tablex.
- Represent credentialed and credential-free sources differently in API/UI.
- Use fixtures only for product smoke tests, never for benchmark score claims.
- Keep import constrained to `HARNESS_DATA_DIR/benchmarks`.

## Implemented Scope

- Added `benchmark_source_card.v1` schema.
- Added `source_card` and `access` fields to benchmark catalog responses.
- Added `/api/benchmarks/{benchmark_id}/source-card`.
- Added `/api/benchmarks/{benchmark_id}/import-readiness`.
- Added source card metadata for Home Credit Default Risk and UCI Bank Marketing.
- Added UCI Wine Quality catalog entry with public archive metadata.
- Added UCI Wine Quality credential-free synthetic fixture.
- Extended Benchmark Scenario Packs and import manifests with source access context.
- Extended the Data tab benchmark cards with credentialed/credential-free badges, public archive badge, source counts, access kind, and readiness next actions.
- Added integration tests for source cards, import readiness, UCI Bank source metadata, and UCI Wine fixture/import smoke.

## Deferred Scope

- Managed public archive downloader and extractor.
- Checksum verification for downloaded public archives.
- Kaggle API integration through a user-approved connector.
- Full benchmark scoring pipelines.
- Multi-table feature generation from Home Credit supporting tables.

## Risks And Open Questions

- UCI public archive URLs were reachable at implementation time, but network availability and upstream paths can change.
- Public archives may contain files whose delimiter or naming differs from future UCI packaging.
- Source card previews are currently embedded in benchmark catalog responses; a richer dedicated UI panel may be needed as the catalog grows.
- Credentialed benchmark workflows still depend on users preparing local files correctly.

## Validation Plan

- JSON schema validation for `benchmarks/catalog.json`.
- `ruff check .`
- `mypy apps/backend`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --tb=short`
- `npm run lint`
- `npm run build`
- Docker build and `/healthz` smoke.
