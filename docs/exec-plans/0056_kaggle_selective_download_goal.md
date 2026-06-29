# 0056 Kaggle Selective Download Goal

## Goal

Add a harness-owned, plan-backed Kaggle download path that uses the existing credential boundary and file inventory. The default path downloads catalog-required files only, with a size cap and a secret-free manifest, so Home Credit can move from inventory to local import readiness without handing credentials to any runner.

## Implementation Plan

- Add `download_kaggle_selected_files` to the Kaggle service.
- Reuse the competition file inventory call to choose an auth candidate and file plan.
- Default to `include_required=true`, `include_recommended=false`, `include_holdout=false`.
- Enforce `max_total_bytes` before and during streaming.
- Restrict writes to the resolved benchmark root and reject unsafe relative paths.
- Store `kaggle_selective_download_manifest.v1` with downloaded files, skipped reasons, SHA-256 hashes, local status, import readiness, and safety flags.
- Add `/api/benchmarks/{benchmark_id}/kaggle/download`.
- Add Data UI `Required` action and extend the Kaggle gate from credential/probe/inventory to local download readiness.

## In Scope

- Required-file selective download for credentialed Kaggle competitions.
- Secret-free manifest artifacts.
- Existing file skip behavior unless `overwrite=true`.
- Mocked unit/integration tests.

## Out Of Scope

- Full competition download by default.
- Automatic download of supporting or holdout files.
- Unzip/extraction for nested archives.
- AgentRunner access to credentials or raw token material.

## Risks

- Kaggle download endpoint behavior can vary by competition and file naming. The service records download errors as skipped files when possible.
- Home Credit required file is large enough for useful smoke but still manageable; supporting files should be added deliberately from the inventory view.
- Future parquet-heavy competitions need selective planning by file pattern and possibly archive extraction.

## Verification Notes

- Unit/integration tests cover required-file planning, zip response extraction, SHA-256 recording, endpoint manifest storage, local status, and import-readiness output with mocked Kaggle responses.
- A real harness endpoint download was run for `kaggle_home_credit_default_risk` with `include_required=true`, `include_recommended=false`, `include_holdout=false`, `overwrite=true`, and `max_total_bytes=524288000`.
- The real download returned `download_status=completed`, `downloaded_count=1`, `downloaded_bytes=166133370`, `local_ready=true`, and artifact `art_7a6af3c0082a`.
- Kaggle returned a zip archive for `application_train.csv`; the downloader now detects zip payloads and safely extracts the expected member before writing the local CSV.
- Docker smoke passed with `docker build -t tablex-smoke:latest .` and a temporary container returning `{"status":"ok"}` from `/healthz`.
- A full import smoke was attempted after download. It was manually stopped after several minutes because the current profiler runs expensive full-column distinct/missing passes on the 166 MB Home Credit CSV. This should become the next large-dataset readiness goal: bounded/sample-first profiling with deferred deep profiling.
- While implementing this goal, the Project creation UI was corrected to create a project by name only. Target selection remains available after data upload/import context, and the UI/UX spec now records that target may be decided after Data Understanding or derived target design.
