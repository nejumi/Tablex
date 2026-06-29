# Notebook Execution Planning Goal

## Goal

Turn generated marimo analysis notebooks into controlled runner work without executing arbitrary notebook code from the API/UI milestone. The harness should own the plan, safety policy, expected artifacts, and AgentTaskContract before a future runner executes or extends the notebook.

## Implemented

- Added `plan_notebook_execution` job type.
- Added `POST /api/analysis-notebooks/{artifact_id}/execution-plan`.
- Added `notebook_execution_plan.v1` artifacts with:
  - source notebook reference,
  - linked preview/manifest/report/visualization artifacts,
  - runner policy,
  - manifest summary,
  - expected output artifacts,
  - generated contract artifact id.
- Added schema-validated `execute_analysis_notebook` AgentTaskContracts for future controlled runners.
- Added lineage from the source notebook and linked notebook artifacts into the execution plan and contract.
- Added Reports tab Notebook Center actions to plan controlled notebook execution and immediately preview the plan artifact.
- Added API integration coverage for plan creation and contract/plan payload validation.

## Decisions

- Notebook execution planning is separate from notebook generation and separate from actual execution. This keeps the current milestone safe while making the next runner boundary concrete.
- The plan requires artifact capture, human review, no secret or connector credential materialization, and no external network by default.
- Required outputs include an execution report, execution manifest, HTML export, figure manifest, and updated marimo source.
- The contract preserves EvaluationSpec and SplitManifest boundaries and explicitly forbids destructive evaluation changes or validation/test target leakage.

## Deferred

- Running marimo server-side or exporting executed HTML.
- Capturing figure/table artifacts from real executed cells.
- Installing and isolating a notebook runtime environment.
- Approval UX for execution beyond plan creation.
- Comparing multiple executed notebook versions.

## Risks

- The contract is validated but not executed, so runtime package compatibility is still unverified.
- The first controlled runner must be strict about workspace paths and artifact registration so notebook code cannot bypass harness-owned lineage.
- Model diagnostics extension points such as permutation importance and partial dependence need runner-side evidence capture before being treated as findings.
