# Time And Group Split Goal

## Goal

Advance Evaluation-first behavior by allowing approved time-aware and group-aware EvaluationSpecs to produce SplitManifest artifacts. The harness should make these choices visible and store diagnostics that help users understand leakage risk without requiring external tools.

## Implemented Scope

- Added `time` SplitManifest generation.
- Added `group` SplitManifest generation.
- Kept random and stratified generation behavior.
- Added time split diagnostics:
  - train/valid time ranges
  - null time counts
  - `time_order_respected`
- Added group split diagnostics:
  - group counts by split
  - `group_overlap_count`
  - `group_leakage_check_passed`
- Updated time/group EvaluationCandidate rationale text.
- Enabled the frontend Generate SplitManifest action for random, stratified, time, and group specs.
- Added candidate UI display for selected time/group columns.
- Added API integration tests for time and group split generation.

## Safety Constraints

- `time` split requires an approved `time_column`.
- `group` split requires an approved `group_column`.
- Group split assigns complete groups to train or valid, never individual rows independently.
- Time split sorts by parsed timestamp and places later rows in validation.
- Rows with missing time are deterministically assigned by row hash and reported in summary diagnostics.

## Deferred Scope

- Grouped time split.
- Rolling-origin backtesting and multiple validation windows.
- User-editable train fraction and seed.
- Explicit UI inspection of SplitManifest diagnostics beyond artifact metadata.
- Rare-class protection for stratified/time/group split combinations.
