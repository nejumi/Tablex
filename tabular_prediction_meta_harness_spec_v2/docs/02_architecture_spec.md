# 02. アーキテクチャ仕様

## 1. 全体構成

```text
Browser UI
  -> Backend API
  -> Workflow Orchestrator
  -> Job Queue
  -> Worker
  -> Agent Runner Abstraction
       -> Codex CLI Runner
       -> Codex MCP Runner
       -> Native Runner
       -> Future Hermes Runner
  -> Sandboxed Project Workspace
  -> Metadata DB
  -> Artifact Store
  -> Lineage Store
  -> Data Access Broker
  -> Connectors
```

## 2. レイヤー責務

### 2.1 Frontend

- Project、Asset Library、Leaderboard、Lineage、Monitoringを表示する。
- Human Q&A、Evaluation Approval、Deployment Approvalを扱う。
- Agent実行ログ、job進捗、artifact previewを表示する。

推奨技術:

- Next.js
- React
- TanStack Query
- React Flow
- EChartsまたはPlotly
- Monaco Editor
- Markdown renderer

### 2.2 Backend API

- REST APIを提供する。
- Auth、RBAC、project scopeの検査を行う。
- Metadata DBとArtifact Storeを操作する。
- Jobをqueueへ投入する。
- SSEまたはWebSocketで進捗イベントを配信する。

推奨技術:

- FastAPI
- Pydantic
- SQLAlchemyまたはSQLModel
- Alembic
- SQLite first、Postgres later

### 2.3 Workflow Orchestrator

プロジェクト状態遷移を管理する。

責務:

- phase transition
- approval gate
- job orchestration
- retry policy
- failure handling
- artifact registration
- lineage registration
- agent task contract generation

### 2.4 Worker

jobを実行する。

job種別:

- profile_dataset
- generate_understanding
- generate_questions
- update_assumptions
- design_evaluation
- generate_split
- run_baseline
- run_sanity_checks
- run_error_analysis
- run_experiment
- generate_report
- run_batch_prediction
- run_monitoring
- invoke_agent_task

### 2.5 Agent Runner Abstraction

CodexなどのAgent実行エンジンを差し替え可能にする。

```python
class AgentRunner:
    def run_task(
        self,
        workspace_ref: WorkspaceRef,
        task_contract: AgentTaskContract,
        output_schema: dict,
        execution_policy: ExecutionPolicy,
    ) -> AgentResult:
        ...
```

### 2.6 Metadata DB

構造化メタデータを保存する。

- users
- organizations
- teams
- projects
- datasets
- artifacts
- asset_versions
- asset_references
- jobs
- runs
- models
- approvals
- lineage_edges
- audit_logs

### 2.7 Artifact Store

大きいファイルや成果物を保存する。

初期:

```text
/data/artifacts/{org_id}/{project_id}/{asset_type}/{asset_id}/{version}/...
```

将来:

- S3
- GCS
- Azure Blob
- MinIO

### 2.8 Lineage Store

初期はMetadata DB上の `lineage_edges` で十分。将来はgraph DBやOpenLineage互換exportを検討する。

### 2.9 Data Access Broker

すべての外部データアクセスを仲介する。

責務:

- secret isolation
- policy check
- row limit
- column masking
- SQL allowlist
- audit log
- approval gate
- sample materialization
- schema inspection

## 3. Single Docker構成

```text
/app
  /backend
  /frontend_static
  /worker
  /project_templates
/data
  /metadata/app.db
  /artifacts
  /workspaces
  /logs
  /cache
  /secrets
```

プロセス:

```text
supervisord or uvicorn multiprocess
  - api server
  - worker process
  - scheduler process
```

初期はRedisなしでDB polling queueを使う。v1でRedisまたはPostgres advisory lockに移行する。

## 4. Docker Compose移行設計

```text
app
worker
postgres
redis
minio
sandbox-runner
```

single Dockerでも同じ抽象を使い、後で構成を分けられるようにする。

## 5. Project Workspace

各プロジェクトにgit管理されたworkspaceを作る。

```text
/data/workspaces/{project_id}/repo/
  AGENTS.md
  harness.yaml
  .codex/config.toml
  task_contracts/
  data/
  src/
  outputs/
  reports/
  artifacts/
  tests/
  .harness/
```

### 5.1 Workspaceの原則

- Agentはworkspace内だけを編集可能にする。
- DB credentialやOAuth tokenはworkspaceに置かない。
- dataset全体ではなく、必要に応じてsampleやmaterialized splitを置く。
- 生成物はoutputs配下に保存し、ハーネスがartifact登録する。
- `AGENTS.md`にプロジェクトルールを明記する。
- `.codex/config.toml`にsandboxとMCP設定を置く。

## 6. Artifact命名規則

```text
{asset_type}_{short_id}_v{version}
```

例:

```text
dataset_snapshot_ds01_v3
evaluation_spec_eval01_v1
split_manifest_split01_v1
model_model01_v12
report_baseline_v2
skill_leakage_detection_v4
```

## 7. Job実行ライフサイクル

```text
QUEUED
  -> CLAIMED
  -> PREPARING_WORKSPACE
  -> RUNNING
  -> VALIDATING_OUTPUTS
  -> REGISTERING_ARTIFACTS
  -> SUCCEEDED

FAILED
CANCELLED
NEEDS_APPROVAL
```

各jobは以下を持つ。

- idempotency key
- input asset versions
- output contract
- timeout
- retry policy
- resource policy
- approval policy
- audit context

## 8. Event Stream

UIはjobとagent進捗を受信する。

イベント例:

```json
{
  "event_type": "job.progress",
  "job_id": "job_123",
  "project_id": "p_001",
  "phase": "RUNNING",
  "message": "baseline model is training",
  "percent": 55
}
```

Agentの内部詳細を出しすぎない。ユーザーには、成果、警告、承認要求、次アクションを中心に出す。

## 9. 設定ファイル

### 9.1 app config

```yaml
app:
  mode: single_docker
  base_url: http://localhost:8080
  artifact_store: local
  metadata_db: sqlite

agent:
  default_runner: codex_cli
  fallback_runner: native_llm
  max_task_minutes: 30

security:
  allow_external_network: false
  default_pii_policy: mask
  production_write_requires_approval: true
```

### 9.2 project harness config

```yaml
project:
  id: p_001
  target_column: churn
  task_type: binary_classification
  prediction_time: at_month_end

evaluation:
  approved_spec_id: eval_001

agent:
  allowed_tools:
    - get_schema
    - get_sample
    - write_artifact
    - run_standard_evaluation
```

## 10. Observability

最低限記録するもの。

- API request log
- job log
- agent task log
- artifact registration log
- data access audit log
- approval log
- exception log
- model metric log
- prediction run log

UIでは、一般ユーザー向けにはjob summary、開発者向けにはraw log viewerを出す。

## 11. バックアップ

single Dockerでは `/data` を丸ごとvolume backup対象にする。

必須:

- metadata DB
- artifacts
- workspaces
- secrets reference
- config
- logs

## 12. 性能目標

v0.1:

- 100MB CSVまでUI操作で扱える。
- 10万行、100列程度でEDAとbaselineを実行可能。
- 1 projectにつき数百artifactを管理可能。
- Leaderboard 100 runs程度を快適に表示可能。

v1.0:

- 1GB級ファイルはDuckDB/Polars streamingで扱う。
- 実験runはworker分離。
- Long running jobのresumeとcancelをサポートする。
