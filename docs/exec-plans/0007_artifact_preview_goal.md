# Artifact Preview Goal

## Goal

Keep artifact inspection inside Tablex for the common MVP outputs: profiles, understanding reports, evaluation specs, split manifests, baseline plans, metrics, prediction CSVs, and validation reports. Users should not need to browse the filesystem to inspect first-class artifacts.

## Implemented Scope

- Added `ArtifactPreviewRead` API schema.
- Added `GET /api/artifacts/{artifact_id}/preview`.
- Reused existing `GET /api/artifacts/{artifact_id}/download`.
- Preview supports UTF-8 text-like artifacts with suffixes: `.json`, `.md`, `.csv`, `.tsv`, `.txt`, `.yaml`, `.yml`, and `.log`.
- Preview reads at most 20 KB plus one byte for truncation detection.
- JSON previews are pretty-printed when the preview is complete and valid JSON.
- Binary artifacts return a structured `preview_available=false` response rather than failing.
- Added preview and download actions to the Assets tab.
- Added an Artifact Preview panel in the UI.
- Extended API integration tests for text preview, binary preview rejection, and download response.

## Design Decision

Preview is intentionally read-only and bounded. The harness should make durable artifacts inspectable, but model packages and future sensitive connector outputs must not be blindly rendered. Binary packages remain downloadable only.

## Deferred Scope

- Rich JSON tree viewer.
- CSV table preview with row/column paging.
- Syntax highlighting.
- Artifact-specific report pages.
- Access-control filtering once real auth is added.
- Preview audit events.

## Risks And Open Decisions

- Suffix-based preview is conservative but imperfect. A later version should use stored artifact media type metadata.
- Download links are direct API links in the UI. Auth and signed download policy should be revisited before multi-user deployment.
