# Data Quality, Leakage & Temporal Validation Intelligence Goal

## Goal

Strengthen Tablex's evaluation-first workflow before more agentic modeling. Dataset quality, leakage risk, prediction-time availability, time/group structure, duplicates, missingness, and evaluation readiness should become harness-owned artifacts that feed Questions, Assumptions, Evidence, Insights, AgentContextPacks, and UI decisions.

## Implemented

- Added schema:
  - `schemas/data_quality_gate.schema.json`
- Added job type:
  - `analyze_data_quality`
- Added endpoints:
  - `POST /api/datasets/{dataset_snapshot_id}/quality/run`
  - `GET /api/datasets/{dataset_snapshot_id}/quality/latest`
- Added `data_quality_gate` JSON artifacts with:
  - target existence checks
  - name-based leakage checks
  - prediction-time availability unknown checks
  - high missingness checks
  - constant-column checks
  - identifier/group-like column risk checks
  - duplicate full-row checks
  - near-exact target proxy checks
  - EvaluationSpec/SplitManifest readiness checks
  - time/group split scenario guidance
- Added `data_quality_report` Markdown artifact.
- Added quality VisualizationSpec for gate status.
- Materializes warning/failing findings as Evidence, Assumptions, Questions, and a `data_quality_gate` Insight.
- Added lineage from DatasetSnapshot, EvaluationSpec, SplitManifest, Insight, and quality artifacts.
- Added `quality_gate_context` to AgentContextPack.
- Added quality gate reference to ExperimentPlan runner contract.
- Extended Data UI with quality analysis, artifact table, preview, and download.
- Extended Evaluation UI with quality gate context.
- Extended integration tests across upload, quality gate, AgentContextPack, and artifact assertions.

## Deferred

- Full statistical validation suite and schema drift across multiple snapshots.
- Rich column-level distribution charts.
- Strict validation of quality-gate payloads before artifact write.
- Interactive human override flow for each check.
- Full temporal leakage validation for lag/rolling feature windows.
- Statistical significance or uncertainty checks for quality-driven split choices.

## Risks And Open Decisions

- The first implementation intentionally uses deterministic heuristics. It should raise review prompts, not silently make deployment decisions.
- Target proxy detection currently checks near-exact string equality. Correlation, mutual information, and model-based leakage probes should be added later.
- Prediction-time availability remains mostly question/assumption driven until connector metadata and user answers improve.
