# 0033 Public Benchmark Workflow Goal

## Goal

Create a one-action workflow for credential-free benchmark sources so users can validate the product path inside Tablex without visiting external dashboards or wiring manual steps.

## Scope

- Public sources only: `requires_account=false` and `supports_direct_download=true`.
- Credentialed Kaggle sources are rejected by policy and remain user-managed outside Tablex.
- The workflow composes existing harness-owned services:
  - managed public download
  - benchmark import
  - profiling and quality
  - evaluation scenario comparison, approval, and SplitManifest
  - adaptive BaselineStrategyPlan
  - baseline run
  - diagnostics and run report
  - visualization dashboard, insights, decision dashboard/report
  - BenchmarkScenarioPack/report

## Implementation Notes

- New API: `POST /api/projects/{project_id}/benchmarks/{benchmark_id}/public-workflow`.
- New job type: `run_public_benchmark_workflow`.
- UI: Benchmark cards now expose a `Flow` action for credential-free direct-download sources.
- Tests use a local HTTP server and custom catalog to keep the public workflow smoke network-independent.

## Deferred

- Kaggle API integration remains out of scope because connector credentials must not be passed into Tablex or agent workspaces.
- Long-running async execution and cancellation checkpoints remain future work; v1 executes synchronously under one job record.
- Multi-table relational feature execution remains a FeatureRecipe/AgentTask target rather than automatic joins.
