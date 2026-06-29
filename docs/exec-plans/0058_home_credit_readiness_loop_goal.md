# 0058 Home Credit Readiness Loop Goal

## Goal

Make the post-import readiness path work on a real Home Credit primary table after bounded profiling. Data Quality, EvaluationScenarioComparison, EvaluationApprovalReview, and SplitManifest generation should not require full-table deep profile scans, and reports/UI should preserve the sample boundary instead of hiding it.

## Implementation Plan

- Add profile-boundary metadata to `data_quality_gate.v1`.
- Run duplicate and target-proxy quality checks on a materialized quality sample when the EDA profile is `bounded_sample` or the dataset exceeds MVP row/column thresholds.
- Keep small datasets on full quality checks.
- Store `quality_check_scope`, `profile_mode`, and sample row count in quality artifact metadata.
- Show quality check scope in the Data UI.
- Fix full-row duplicate detection so `GROUP BY ALL` actually groups by row values.
- Tighten identifier-name heuristics so `SK_ID_*` is treated as an identifier but Home Credit `DAYS_ID_*` feature columns are not promoted to group candidates.
- Add integration and heuristic regression tests.

## In Scope

- Single-table large-profile Data Quality and Evaluation readiness.
- Home Credit `application_train.csv` import/quality/evaluation/split smoke.
- Schema, docs, and UI updates for quality profile boundaries.

## Out Of Scope

- Full supporting-table Home Credit import.
- Deep-profile job implementation.
- Baseline training on Home Credit.
- Relational feature execution beyond existing planning/preview surfaces.

## Verification Notes

- Bounded quality integration test confirms `quality_check_scope=sample`, `profile_statistics_sampled`, and duplicate pass behavior on a wide CSV.
- Home Credit readiness smoke on new project `p_1778fb9ab1ec`:
  - import completed in about 69 seconds with `profile_mode=bounded_sample`, `sample_row_count=50000`, and `deferred_column_count=122`.
  - profile `group_candidates=[]` after tightening ID heuristics.
  - DataQualityGate completed in about 8 seconds with `quality_check_scope=sample`; duplicate and target-proxy checks passed over 50,000 sampled rows.
  - Evaluation candidate design, scenario comparison, approval review, approval, and stratified SplitManifest generation completed; split counts were train=246008 and valid=61503.

## Risks and Open Questions

- Sample-scoped duplicate/proxy checks are readiness signals, not full-table guarantees. A future `profile_dataset_deep` or `quality_deep_checks` job should support explicit full or approximate scans.
- `first_rows_limit` sampling is deterministic and simple. Seeded random sampling should be added where file format and performance allow.
- Home Credit supporting tables still need a controlled relational import/feature workflow before benchmark-quality modeling.
