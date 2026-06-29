# 0060 Home Credit Flexible Agent Handoff Goal

## Goal

Make the Home Credit project handoff self-contained for a future Codex/AgentRunner implementation. The runner should receive harness-owned context for data understanding, quality boundaries, evaluation, split, baseline strategy, baseline metrics/report, diagnostics, benchmark import, relational catalog, library assets, and reporting requirements without relying on external dashboards or fixed recipes.

## Implementation Plan

- Add `baseline_plan`, `baseline_metrics`, `baseline_report`, `evaluation_diagnostics_report`, and `run_report` to AgentTaskContract context artifacts.
- Materialize baseline metrics/report, diagnostics report, and run report into controlled agent workspaces.
- Add a persistent in-product Agent Chat dock that turns user instructions into harness-owned AgentTaskContracts instead of sending users to an external Codex UI.
- Preserve relational catalog context and library asset materialization.
- Keep runner autonomy policy open-ended: recommended approaches are evidence, not mandatory recipes.
- Verify the real Home Credit project can run agent task planning, readiness review, workspace preparation, LocalStub AgentResult ingestion, and Idea AgentContextPack preparation.

## In Scope

- AgentTaskContract context expansion.
- Controlled workspace context expansion.
- Existing LocalStub runner smoke.
- Tests for workspace materialization of baseline metrics/report.

## Out Of Scope

- Actual Codex CLI execution.
- External web research execution.
- New model training beyond the already completed local baseline.

## Verification Notes

- Home Credit `plan-agent-task` completed in about 0.09 seconds.
- The project UI now keeps an Agent Chat dock available across project tabs. Submitting a prompt creates an AgentTaskContract with the current project context and links to the latest contract artifact.
- Generated contract context roles included `eda_profile`, `understanding_report`, `data_quality_gate`, `relational_catalog`, `benchmark_import_manifest`, `evaluation_scenario_comparison`, `evaluation_approval_review`, `baseline_strategy_plan`, `baseline_plan`, `baseline_metrics`, `baseline_report`, `evaluation_diagnostics`, `evaluation_diagnostics_report`, and `run_report`.
- Readiness review completed with `ready_with_warnings`, 0 blockers, and 3 warnings.
- Controlled workspace preparation completed with 14 materialized context artifacts and 11 materialized library assets.
- Workspace files included baseline metrics/report, baseline plan/strategy, evaluation diagnostics/report, run report, data quality gate, relational catalog, and library Skill/FeatureRecipe/EvaluationPattern assets.
- LocalStub planned AgentTask run succeeded, produced an AgentResult-ingested ExperimentRun, approach decision trace, citation audit artifacts, relational context summary, report artifacts, and required human review.
- Idea AgentContextPack preparation also succeeded for the generated Home Credit idea.

## Risks and Open Questions

- LocalStub validates the handoff shape but does not execute Codex or external research.
- The workspace can become large as more reports accumulate; future work should select context by relevance and recency with explicit inclusion reasons.
- AgentContextPack for an Idea may need stronger linking to the most recent project-level AgentTaskContract recommendations.
