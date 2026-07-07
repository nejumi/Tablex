# Tablex

Tablex is the current working name for a tabular-first agentic data science workbench. It runs alongside Codex or another `AgentRunner`: the runner reasons, analyzes, models, writes reports, and authors notebooks; Tablex supplies data access, artifacts, lineage, evaluation contracts, safety boundaries, tools, memory, and the human interface.

The product name may still change. Keep code, package names, API paths, and database tables neutral where practical.

## Product Contract

Read [docs/agent_interface_spec.md](docs/agent_interface_spec.md) before changing Full Auto, Raw, Chat, Research Plan, or notebook behavior.

The most important constraints are:

- **Full Auto is one continuing main agent session.** Support jobs may train models, ingest artifacts, render notebooks, or build split manifests, but the main Codex reasoning thread must not become a chain of small tickets.
- **Raw is the runner transcript.** Harness records may be interleaved as clearly labeled sidecar events, but Raw must preserve the real Codex CLI JSONL-style execution record.
- **Chat is human accountability, not filtered Raw.** Progress, errors, and next actions should be understandable to users. Internal implementation vocabulary and maker notes do not belong in Chat.
- **Research Plan is agent-operated.** Plan structure and current work come from Codex-authored plan artifacts or schema-validated ResearchPlan requests. UI/process presence must not infer plan progress.
- **marimo source is the notebook artifact.** Native marimo Python source is first-class evidence. Static HTML snapshots are not notebook artifacts and must not hide runtime failures.
- **The harness validates fixed formats, not natural language.** JSON schemas, artifact IDs, metric IDs, credentials boundaries, EvaluationSpec, and SplitManifest consistency are harness responsibilities. Objective reasoning, analysis narrative, hypotheses, and modeling judgment belong to the agent.

## Current Architecture

- **Backend:** FastAPI, SQLite metadata, local filesystem artifact store, DuckDB-backed profiling, local worker/supervisor CLIs.
- **Frontend:** React/Vite workbench with Home, Data, Insights/Reports, Leaderboard, Notebooks, Assets, Jobs, Lineage, Agent Chat, and Raw transcript surfaces.
- **Agent execution:** persistent `AgentSession` for Full Auto, Codex CLI integration, transcript persistence, workspace materialization under `.tablex/`, inbox/ack request protocols, and supervisor recovery.
- **Artifacts and lineage:** datasets, semantic/relational catalogs, evidence, assumptions, reports, notebooks, model results, prediction pipelines, pilot runs, and generated assets are stored with hashes and lineage.
- **Evaluation and modeling:** EvaluationSpec, SplitManifest, ExperimentRun, ModelVersion, Leaderboard, model diagnostics, feature importance/permutation importance/PDP/SHAP-style diagnostic artifacts where available, and downloadable prediction pipeline bundles.
- **Research and skills:** project and cross-project Skills, controlled research requests, source-backed findings, and research reports. External claims should be stored as Evidence or source-backed artifacts, not left only in logs.
- **Pilot workflow:** registered prediction pipelines can be used for prediction batches, outcome ingestion, pilot scoring, and agent-authored validation audits that feed the same continuing Full Auto loop.

## Core Workflow

1. Create a project.
2. Upload one or more data files. A primary table and objective may be deferred when the task requires data understanding, derived tables, aggregation, clustering, anomaly detection, multi-target setup, or another non-standard objective.
3. Start Full Auto or use explicit controls.
4. Codex receives the project context, data manifest, artifacts, equipped Skills, runtime facts, evaluation boundaries, and validated tool protocols.
5. Codex updates Research Plan, writes progress reports, creates source-backed research findings, authors native marimo notebooks, registers model results, and submits pipeline or pilot artifacts through schema-validated requests.
6. Tablex validates fixed-format submissions, stores artifacts and lineage, updates Chat/Activity/Leaderboard/Notebooks/Data/Assets links, and returns structured errors to Codex when a request must be corrected.

## Important Runtime Paths

Full Auto workspaces are created under:

```text
data/artifacts/agent_sessions/<project_id>/<agent_session_id>/
```

Common workspace paths:

```text
.tablex/context.json              # project context given to Codex
.tablex/GOAL.md                   # current project goal
.tablex/data/                     # stable workspace-readable dataset paths
.tablex/requests/                 # schema-checked requests from Codex to Tablex
.tablex/acks/                     # structured success/error responses back to Codex
reports/chat_update.md            # Codex-authored human progress update
notebooks/*.py                    # native marimo notebooks
outputs/                          # structured plan/results outputs
artifacts/                        # additional generated artifacts
```

The production artifact root defaults to:

```text
data/artifacts/
```

The metadata database defaults to:

```text
data/metadata/app.db
```

## Local Setup

Backend requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Frontend requires Node.js 20 or newer.

```bash
cd apps/frontend
npm install
```

Run the backend:

```bash
source .venv/bin/activate
uvicorn tabular_harness.main:app --app-dir apps/backend --reload --port 8000
```

Run the frontend in another shell:

```bash
cd apps/frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

Health check:

```bash
curl http://localhost:8000/health
```

## Workers And Supervisors

The FastAPI app starts a lightweight local worker by default for concrete sidecar jobs. For heavier debugging or split process operation:

```bash
tablex-worker --once
tablex-worker --interval 2 --worker-id local-worker
```

Run a dedicated Full Auto supervisor:

```bash
tablex-agent-supervisor --interval 15 --owner-id local-agent-supervisor
```

If the supervisor is split out, start the API with `TABLEX_API_AGENT_SESSION_SUPERVISOR_ENABLED=false` and run worker processes with `--no-agent-session-supervisor` where appropriate.

Docker Compose starts API, worker, and agent supervisor from the same image:

```bash
docker compose up --build
```

## Auth And Settings

Password auth is optional and controlled by environment configuration. When enabled, Tablex stores user preferences such as locale, avatar, and model preferences server-side. Authentication credentials, password hashes, cookies, OAuth tokens, and connector secrets must never be passed to Codex workspaces, prompts, artifacts, logs, or reports.

## Tests And Checks

Backend tests:

```bash
source .venv/bin/activate
pytest
```

Backend type/lint checks:

```bash
source .venv/bin/activate
ruff check apps/backend
mypy apps/backend
```

Frontend build:

```bash
npm --prefix apps/frontend run build
```

Browser golden-slice smoke:

```bash
node apps/frontend/e2e/golden_slice_smoke.mjs
```

Frontend lint:

```bash
npm --prefix apps/frontend run lint
```

For README-only changes, at minimum run:

```bash
git diff --check README.md
```

## Documentation

- [Development guide](docs/dev.md)
- [Agent interface spec](docs/agent_interface_spec.md)
- [Benchmark catalog and workflows](docs/benchmarks.md)
- [Execution plans](docs/exec-plans/)
- [E2E and audit evidence](docs/evidence/)

## Development Notes

- Keep Codex autonomy intact. Do not add harness-side heuristics that infer targets, task shape, modeling intent, or analytical conclusions from column names or natural-language keywords.
- Prefer artifact-backed outputs and schema-validated request protocols over UI inference or background guessing.
- Preserve EvaluationSpec and SplitManifest integrity for comparable experiments.
- Keep user-facing text practical: what is happening, what changed, what needs attention, and how to continue.
- When a runtime or notebook fails, surface the failure and let the agent repair the source. Do not hide it behind a static fallback.
