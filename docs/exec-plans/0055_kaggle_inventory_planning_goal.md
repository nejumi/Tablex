# 0055 Kaggle Inventory Planning Goal

## Goal

Turn credentialed Kaggle benchmarks from opaque source cards into inspectable, secret-free file inventories. The harness should fetch file names and sizes through its controlled credential boundary, map files to catalog roles, and leave a planning artifact before any managed download is implemented.

## Implementation Plan

- Reuse the harness-only Kaggle credential candidates from `kaggle_probe.py`.
- Add `fetch_kaggle_competition_inventory` for the Kaggle competition file-list API.
- Store `kaggle_competition_file_inventory.v1` artifacts with:
  - file names
  - size bytes when available
  - required/recommended/extra requirement
  - primary/supporting/holdout role mapping from `benchmarks/catalog.json`
  - missing required file summary
  - secret-free auth source labels and attempts
- Add `/api/benchmarks/{benchmark_id}/kaggle/inventory` and `/api/benchmarks/{benchmark_id}/kaggle/inventory/latest`.
- Add `credential_inventory` to `benchmark_source_card.v1`.
- Add Data tab Inventory action and a compact inventory meter next to the Kaggle gate.

## In Scope

- Inventory/list planning only.
- Secret-free artifact and Job output.
- Home Credit-ready role mapping against required and recommended catalog files.
- Tests with mocked Kaggle responses.

## Out Of Scope

- File download.
- Rule acceptance.
- AgentRunner access to credentials.
- Treating a benchmark inventory as a fixed modeling strategy.

## Risks

- Kaggle file-list field names may vary. The parser accepts common `name`, `fileName`, `totalBytes`, and size variants.
- Some competitions may expose nested archives where file names do not exactly match catalog paths. These are surfaced as `extra` or missing required files for review.
- Actual download should be selective and plan-backed, not automatic full-archive ingestion.

## Verification Notes

- Unit/integration tests cover inventory role mapping, secret-free payloads, endpoint artifact creation, and latest-inventory retrieval with mocked Kaggle responses.
- A real harness endpoint inventory was run against `kaggle_home_credit_default_risk` using the local gitignored `.env`/process environment. It returned `inventory_status=ok`, `file_count=10`, `total_size_bytes=2684261617`, `required_missing_count=0`, and stored artifact `art_b69a0528f759`.
- The latest endpoint returned artifact `art_b69a0528f759` as `kaggle_file_inventory_kaggle_home_credit_default_risk`.
