# Evaluation Scenario Comparison Goal

## Goal

Make EvaluationSpec adoption more deliberate by adding an artifact-backed scenario comparison step. The comparison should keep Tablex evaluation-first while avoiding a fixed "always promote this split" workflow.

## Implemented

- Added `schemas/evaluation_scenario_comparison.schema.json`.
- Added `compare_evaluation_scenarios` job type.
- Added `POST /api/projects/{project_id}/evaluation/compare`.
- The comparison reads:
  - latest DatasetSnapshot and profile
  - EvaluationCandidates, creating defaults when needed
  - DataQualityGate artifact context
  - RelationalCatalog artifact context
  - open Questions
  - high-risk Assumptions
- Stored an `evaluation_scenario_comparison` artifact with candidate comparisons, recommendation metadata, decision-support notes, and a risk register.
- Added lineage from DatasetSnapshot and compared EvaluationCandidates to the comparison artifact.
- Added Evaluation UI controls to generate, preview, and download comparison artifacts before promoting a candidate.
- Added integration coverage to the main API flow.

## Design Choices

- Scenario comparison is an artifact, not a new DB table, to keep the MVP metadata schema stable.
- The endpoint does not promote, approve, or mutate EvaluationSpec records.
- The recommendation is heuristic and transparent. It records blockers, strengths, risks, feasibility, and score so a user or future AgentRunner can challenge it.
- Relational and quality contexts are linked by artifact metadata when possible, with latest-project fallback for early MVP data.

## Deferred

- A richer visual comparison grid with per-risk filters.
- Manual candidate rejection and status editing in the UI.
- JSON Schema runtime validation for the stored comparison payload.
- Quantitative target distribution checks computed directly from candidate split assignments before SplitManifest generation.

## Risks And Open Decisions

- Current scoring is rule-based and should be replaced or augmented by evidence-backed EvaluationPatterns and Skill outputs.
- Time/group candidates still depend on profile heuristics; user confirmation and Assumption resolution should influence final approval.
- Multi-table leakage risk is detected from RelationalCatalog metadata but not yet proven with joined feature execution.
