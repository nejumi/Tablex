# AGENTS.md

This repository is building Tablex, a tabular-first prediction meta-harness. Tablex is the current working display name; keep code, package names, API paths, and database tables neutral where practical because the product name may still change.

## Core Rules

- Do not read, log, copy, or request secrets.
- Do not pass connector credentials, OAuth tokens, database passwords, or production write credentials to an agent runner.
- Kaggle credentials may only be read by harness-owned credential probe/download code in-process; never materialize values into prompts, AgentTaskContracts, runner workspaces, artifacts, or logs.
- Do not include validation or test targets in feature-generation prompts.
- Do not destructively change an approved `evaluation_spec`; create a new version or candidate instead.
- Respect `split_manifest` for all evaluation and baseline work.
- Design important outputs so they can be registered as artifacts with content hashes and lineage.
- Treat `DatasetSnapshot`, `SemanticCatalog`, `Question`, `Assumption`, `Evidence`, `EvaluationCandidate`, `EvaluationSpec`, `SplitManifest`, `ExperimentRun`, `Asset`, `AssetVersion`, `AssetReference`, `LineageEdge`, `Job`, and AgentContextPack artifacts as first-class objects.
- Keep Codex and other runners as implementations of `AgentRunner`; the harness owns UI, auth, metadata, artifacts, lineage, evaluation design, approvals, safety controls, and data access.
- Prefer evaluation-first changes: data understanding, assumptions, reliable evaluation, and baseline sanity before model optimization.
- Treat baselines as sanity floors and reusable references, not as the product's fixed modeling strategy.
- When proposing modeling approaches, create evidence-backed Ideas and AgentTaskContracts that can use project artifacts, Skill library context, and controlled web/literature research.
- Prepare and inspect AgentContextPack artifacts before real agent execution; they should carry harness-owned evaluation, split, asset, research, and safety context.
- External claims from web or literature research must be returned as Evidence or artifact-backed sources; do not leave them only in runner logs.
- Jobs with external network, production write, or agent execution policy must pass through approval gates before worker execution.
- Reports and visualization specs are first-class outputs and should be registered as artifacts with lineage.
- UI work should make complex ML workflow state feel rich, inspectable, and exciting to use; do not collapse product surfaces into plain tracker tables when a focused status gate, preview, or visualization would make the decision clearer.
- Run backend tests and lint/type checks after code changes. Run frontend build or lint when touching frontend code.

## Development Scope

- Initial runtime is single Docker, SQLite, local filesystem artifact store, DuckDB, FastAPI, React, and a Python worker skeleton.
- Do not add W&B, MLflow, Kubernetes, production connectors, Google OIDC, deployment, monitoring, or GenAI feature generation unless the task explicitly asks for that phase.
- Keep implementations understandable and avoid broad abstractions before the MVP vertical slice works.
