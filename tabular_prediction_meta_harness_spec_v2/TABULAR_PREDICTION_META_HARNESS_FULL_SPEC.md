# Tabular-first Prediction Meta-Harness Full Specification

プロダクト名は未確定です。本書では仮置き名として `PRODUCT_NAME` を使用します。候補名には `Tablex` や `Tablex Workbench` などがありますが、正式決定ではありません。



---


# 01. プロダクト仕様

## 0. 名称ポリシー

プロダクト名は未確定である。本仕様書では仮置き名として `PRODUCT_NAME` を使用する。候補名は `Tablex`, `Tablex Workbench`, `Predictive Agent Workbench` などだが、実装、DB schema、API path、package名はブランド確定まで中立名に寄せる。

- ユーザー向け表示名: 環境変数 `APP_DISPLAY_NAME` で差し替え可能にする。
- 内部アーキテクチャ名: `Tabular-first Prediction Meta-Harness` を使用する。
- コード上の仮package名: `tabular_harness` または `prediction_harness` とする。
- 将来ブランド名変更に備え、ファイル名やDB tableに `tablex` を固定で埋め込まない。

## 1. プロダクト概要

`PRODUCT_NAME` は、表データを起点とした予測課題を、Data Understanding、Reliable Evaluation、Baseline、Improvement、Deployment、Monitoring、Skill再利用まで一気通貫で扱う自己完結型のワークベンチである。

本システムは、通常のAutoMLとは異なり、単にモデル探索を行うのではなく、予測課題の成立性、評価系の妥当性、リーク、運用時のズレ、改善仮説、アセット再利用までを管理する。

## 2. プロダクトカテゴリ

内部アーキテクチャ上は `Tabular-first Prediction Meta-Harness` と定義する。

- `tabular-first`: 主対象は表形式データである。ただし、テキスト、カテゴリ、数値、時系列、グループ、外部知識、LLM特徴量も扱う。
- `prediction`: 回帰、二値分類、多クラス分類、需要予測、ランキング的予測を扱う。
- `meta-harness`: Codexなどのコード実行ハーネスを内包し、その上位で予測ライフサイクル全体を統治する。

## 3. 主要ユーザー

### 3.1 Data Scientist

- EDA、評価設計、特徴量、実験、誤差分析、モデル改善を行う。
- エージェントが生成した提案を確認、修正、承認する。
- 再利用可能なSkillを昇格する。

### 3.2 ML Engineer

- データ接続、batch prediction、monitoring、artifact管理、実行環境を管理する。
- runner、job queue、sandbox、deploymentを整える。

### 3.3 Business Owner

- 予測課題の目的、成功条件、評価指標、業務制約を入力する。
- エージェントからの質問に回答する。
- モデル採用、運用開始、リスクを判断する。

### 3.4 Admin

- 組織、チーム、権限、Googleログイン、コネクター、secret、audit logを管理する。

## 4. コア価値

### 4.1 Evaluation-first

評価系をモデルより先に扱う。時系列性、グループ構造、不均衡、予測時点可用性、リーク候補を考慮し、実運用に近いsplitとmetricを作る。

### 4.2 Understanding as Asset

EDA結果、質問、仮定、意味カタログ、リーク候補、データ品質、可視化を永続化し、後続フェーズと再利用に使う。

### 4.3 Question-driven, not Question-dependent

本プロダクトは、評価設計、データ意味、予測時点可用性、業務制約などについてエージェント側から積極的に質問する。ただし、回答がないことを理由に停止しない。

未回答事項は `Assumption` として明示し、confidence、risk、evidence、fallback policy、used-in lineageを持たせる。低リスク事項は推測して進み、高リスク事項は保守的に扱い、重要事項は複数のEvaluationCandidateでシナリオ検証する。運用後にactualsが到着したら、前向き検証結果を使って仮定と評価設計の妥当性を更新する。

### 4.4 Agent does work, Harness governs

CodexなどのAgentはコード生成、実行、修正、レポート生成を担当する。ハーネスは状態、承認、権限、評価、アーティファクト、リネージ、安全制御を担当する。

### 4.5 Cross-project Asset Library

Project固有のアセットと、横断利用するSkill、評価パターン、特徴量レシピ、可視化テンプレート、Prompt Template、Domain Taxonomyを分離する。横断アセットはコピーではなくversion固定参照で使う。

### 4.6 Self-contained UI

ユーザーは外部のW&BやMLflow画面に遷移しなくても、EDA、評価設計、実験、leaderboard、リネージ、監視をハーネス内で完結して閲覧、操作できる。外部ツール連携はoptional exportとして扱う。

## 5. プロダクトフェーズ

1. Project Intake
2. Data Understanding
3. Human Q&A
4. Assumption Intelligence
5. Evaluation Scenario Design
6. Reliable Evaluation
7. Evaluation Approval
8. Baseline
9. Baseline Sanity Check
10. Improvement Loop
11. Candidate Selection
12. Deployment
13. Monitoring
14. Forward Validation Reconciliation
15. Evaluation Reflection
16. Skillization

## 6. Product State Machine

```text
DRAFT
  -> DATA_LOADED
  -> UNDERSTANDING_RUNNING
  -> UNDERSTANDING_REVIEW
  -> QUESTIONS_PENDING
  -> ASSUMPTION_REVIEW
  -> EVALUATION_SCENARIO_RUNNING
  -> EVALUATION_REVIEW
  -> BASELINE_RUNNING
  -> BASELINE_REVIEW
  -> IMPROVEMENT_RUNNING
  -> CANDIDATE_SELECTED
  -> DEPLOYMENT_REVIEW
  -> DEPLOYED
  -> MONITORING
  -> FORWARD_VALIDATION_RECONCILIATION
  -> EVALUATION_REFLECTION
```

### 6.1 差し戻し

以下の差し戻しを正式にサポートする。

- Baseline sanity check失敗時: `BASELINE_REVIEW -> UNDERSTANDING_REVIEW`
- split妥当性に疑義が出た時: `BASELINE_REVIEW -> EVALUATION_REVIEW`
- 本番乖離発見時: `MONITORING -> EVALUATION_REFLECTION -> EVALUATION_REVIEW`
- データ定義変更時: `MONITORING -> DATA_LOADED`

## 7. Project WorkspaceとAsset Library

### 7.1 Project Workspace

個別予測課題に固有のアセットを管理する。

- DatasetSnapshot
- SemanticCatalog
- Understanding
- QuestionSet
- AssumptionSet
- EvidenceSet
- EvaluationCandidate
- EvaluationScenario
- EvaluationSpec
- SplitManifest
- MetricSpec
- BaselineReport
- FeatureSet
- ExperimentRun
- ModelVersion
- PredictionSet
- MonitoringReport
- ForwardValidationResult
- ReflectionEvent
- ProjectReport
- LineageGraph

### 7.2 Cross-project Asset Library

組織横断で再利用するアセットを管理する。

- Skill
- FeatureRecipe
- EvaluationPattern
- PromptTemplate
- VisualizationTemplate
- ReportTemplate
- DataQualityRule
- LeakageRule
- MetricPolicy
- DomainTaxonomy
- ConnectorTemplate

### 7.3 参照ポリシー

横断アセットはコピーせず、`AssetReference` として参照する。実験run時点では、versionとdigestを固定して再現性を担保する。

## 8. MVPスコープ

### 8.1 v0.1で必須

- Local auth
- Project CRUD
- CSV/Parquet upload
- SQLite metadata DB
- local artifact store
- DatasetSnapshot登録
- SemanticCatalog推定
- Data Understanding report
- Human Questions UI
- Assumptions editor
- Assumption Intelligence v0
- unanswered question fallback policy
- EvaluationCandidate primary/alternative
- Scenario comparison v0
- EvaluationSpec作成
- SplitManifest生成
- Metric recommendation
- Baseline models
- Baseline sanity check
- Leaderboard v0
- Lineage v0
- single Docker

### 8.2 v0.2で必須

- AgentRunner abstraction
- Codex CLI Runner
- task contract validation
- Codex output schema validation
- Codex生成コードのworkspace隔離
- EDA補助
- experiment implementation補助
- failed run repair
- AGENTS.md生成
- `.codex/config.toml`生成

### 8.3 v0.3で必須

- Ideas
- Insights
- Error analysis
- Slice metrics
- Feature importance
- Improvement loop
- Asset Library v0
- Skill Registry v0

### 8.4 v1.0までに必須

- Google OIDC login
- RBAC
- Data Access Broker
- Postgres read-only connector
- S3 compatible storage connector
- Audit log
- Deployment batch prediction
- Monitoring
- Drift report
- Forward validation reconciliation
- Evaluation reflection
- Assumption confidence update
- Skill promotion workflow

## 9. 非ゴール

初期MVPでは以下を行わない。

- 大規模SaaS multi-tenancy
- Kubernetes必須構成
- 本番DBへの自動書き込み
- 複雑なGenAI特徴量の完全自律生成
- GPU必須の学習
- 外部実験管理ツールをsystem of recordにすること
- Codexの深いfork

## 10. 成功指標

### 10.1 プロダクト成功指標

- ユーザーがCSVを投入してからbaseline reviewまで到達できる。
- エージェントが少なくとも10個以上の意味あるData Understanding知見を生成する。
- 評価設計の根拠がUIで説明される。
- splitとmetricがversion管理される。
- baselineの異常やリーク候補が検出される。
- 実験、モデル、レポート、可視化がリネージで辿れる。

### 10.2 技術成功指標

- single Dockerで起動できる。
- すべてのartifactにcontent hashがある。
- すべてのjobが再実行可能である。
- Agent task outputがschema validationされる。
- Codexはworkspace外のsecretを読めない設計になっている。
- Data Access Brokerを経由しないデータ取得を禁止できる。

## 11. リスク

| リスク | 影響 | 対策 |
|---|---|---|
| 評価系が間違う | 全実験が無意味になる | Evaluation approval gate、pushback、reflection |
| Codexが危険操作をする | 情報漏洩や破壊 | sandbox、Data Access Broker、secret隔離 |
| GenAI特徴量でリークする | スコア過大評価 | OOF制約、prompt lineage、leakage audit |
| UIが実験管理ツール化しすぎる | プロダクト価値が薄い | Understanding、Evaluation、Ideasを一級画面にする |
| アセット再利用がコピーになる | 再現性が壊れる | version fixed reference |
| single Dockerが肥大化する | 運用困難 | v0はPoC用、v1でcompose化 |



---


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



---


# 03. データモデル仕様

## 1. 設計原則

1. すべての成果物はArtifactとして登録する。
2. すべてのArtifactはcontent hashを持つ。
3. すべての実験runは、入力Artifact versionと出力Artifact versionを記録する。
4. 横断アセットはAssetVersionとして管理し、ProjectからAssetReferenceで参照する。
5. EvaluationSpecとSplitManifestはモデルより強い一級オブジェクトとして扱う。
6. ユーザー回答、仮定、承認履歴も再現性の一部として扱う。
7. 未回答事項はAssumptionとして保持し、confidence、risk、evidence、fallback policyを持たせる。
8. EvaluationSpecを固定する前に、EvaluationCandidateとEvaluationScenarioを保持する。

## 2. エンティティ一覧

### 2.1 Identity

- User
- Organization
- Team
- Membership
- Role
- Permission

### 2.2 Project

- Project
- ProjectMember
- ProjectSettings
- ProjectPhaseHistory

### 2.3 Data

- DataSource
- DatasetSnapshot
- DatasetColumn
- SemanticCatalog
- DataQualityFinding
- LeakageCandidate

### 2.4 Understanding

- UnderstandingReport
- QuestionSet
- Question
- Answer
- AssumptionSet
- Assumption
- Evidence
- AssumptionEvidenceLink

### 2.5 Evaluation

- EvaluationCandidate
- EvaluationScenario
- EvaluationSpec
- MetricSpec
- SplitManifest
- SplitSummary
- EvaluationApproval
- PushbackRecord

### 2.6 Experiment

- ExperimentRun
- RunMetric
- RunParameter
- FeatureSet
- FeatureRecipe
- ModelVersion
- PredictionSet
- ErrorAnalysis
- SliceMetric
- LeaderboardEntry

### 2.7 Knowledge

- Insight
- ImprovementIdea
- ResearchNote
- DecisionRecord

### 2.8 Cross-project Assets

- Asset
- AssetVersion
- AssetReference
- Skill
- PromptTemplate
- VisualizationTemplate
- EvaluationPattern
- DomainTaxonomy
- DataQualityRule

### 2.9 Operations

- Deployment
- BatchPredictionJob
- MonitoringRun
- DriftFinding
- ActualsIngestion
- ForwardValidationResult
- ReflectionEvent
- EvaluationReflection

### 2.10 Platform

- Artifact
- ArtifactFile
- LineageEdge
- Job
- ApprovalRequest
- AuditLog
- SecretReference
- Connector

## 3. 主要テーブル詳細

### 3.1 projects

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  task_type TEXT,
  target_column TEXT,
  current_phase TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 3.2 artifacts

```sql
CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT,
  asset_type TEXT NOT NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  uri TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes INTEGER,
  metadata_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(project_id, asset_type, name, version)
);
```

### 3.3 dataset_snapshots

```sql
CREATE TABLE dataset_snapshots (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT,
  row_count INTEGER,
  column_count INTEGER,
  schema_hash TEXT NOT NULL,
  data_hash TEXT,
  parent_snapshot_id TEXT,
  created_at TEXT NOT NULL
);
```

### 3.4 semantic_catalog_columns

```sql
CREATE TABLE semantic_catalog_columns (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  column_name TEXT NOT NULL,
  physical_type TEXT NOT NULL,
  semantic_type TEXT,
  role TEXT,
  available_at_prediction_time TEXT,
  pii_level TEXT NOT NULL DEFAULT 'unknown',
  is_leakage_suspect INTEGER NOT NULL DEFAULT 0,
  description TEXT,
  confidence REAL,
  evidence_json TEXT NOT NULL
);
```

`available_at_prediction_time` は `yes`, `no`, `unknown`, `conditional` のいずれか。

### 3.5 questions

```sql
CREATE TABLE questions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  question_set_id TEXT NOT NULL,
  topic TEXT,
  question TEXT NOT NULL,
  why_it_matters TEXT NOT NULL,
  default_assumption TEXT,
  impact_if_wrong TEXT,
  choices_json TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL,
  risk_level TEXT NOT NULL DEFAULT 'medium',
  value_of_answer TEXT NOT NULL DEFAULT 'medium',
  can_proceed_without_answer INTEGER NOT NULL DEFAULT 1,
  fallback_policy TEXT NOT NULL DEFAULT 'conservative_default',
  related_assumption_id TEXT,
  blocks_next_phase INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
```

### 3.6 answers

```sql
CREATE TABLE answers (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  answered_by TEXT NOT NULL,
  answer_value TEXT NOT NULL,
  answer_text TEXT,
  created_at TEXT NOT NULL
);
```


### 3.6.1 assumptions

```sql
CREATE TABLE assumptions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  subject_type TEXT,
  subject_ref TEXT,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  risk_level TEXT NOT NULL,
  fallback_policy TEXT NOT NULL,
  requires_user_confirmation INTEGER NOT NULL DEFAULT 0,
  created_by_type TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

`status` は `unknown`, `inferred`, `adopted`, `confirmed`, `challenged`, `revised`, `deprecated` のいずれか。

### 3.6.2 evidence

```sql
CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  strength TEXT NOT NULL,
  source_artifact_id TEXT,
  source_run_id TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.6.3 assumption_evidence_links

```sql
CREATE TABLE assumption_evidence_links (
  id TEXT PRIMARY KEY,
  assumption_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  effect TEXT NOT NULL,
  weight REAL NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(assumption_id, evidence_id)
);
```

### 3.6.4 question_assumption_links

```sql
CREATE TABLE question_assumption_links (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  assumption_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.7 evaluation_candidates

```sql
CREATE TABLE evaluation_candidates (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  name TEXT NOT NULL,
  scenario_id TEXT,
  split_type TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  secondary_metrics_json TEXT NOT NULL,
  time_column TEXT,
  group_column TEXT,
  stratify_column TEXT,
  excluded_columns_json TEXT NOT NULL,
  assumption_ids_json TEXT NOT NULL,
  rationale_md TEXT NOT NULL,
  confidence REAL NOT NULL,
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.7.1 evaluation_scenarios

```sql
CREATE TABLE evaluation_scenarios (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  primary_candidate_id TEXT,
  status TEXT NOT NULL,
  assumptions_json TEXT NOT NULL,
  comparison_summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.7.2 evaluation_specs

```sql
CREATE TABLE evaluation_specs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_snapshot_id TEXT NOT NULL,
  source_evaluation_candidate_id TEXT,
  name TEXT NOT NULL,
  split_type TEXT NOT NULL,
  primary_metric TEXT NOT NULL,
  secondary_metrics_json TEXT NOT NULL,
  time_column TEXT,
  group_column TEXT,
  stratify_column TEXT,
  excluded_columns_json TEXT NOT NULL,
  assumption_ids_json TEXT NOT NULL DEFAULT '[]',
  rationale_md TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.8 split_manifests

```sql
CREATE TABLE split_manifests (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  evaluation_spec_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  train_count INTEGER NOT NULL,
  valid_count INTEGER NOT NULL,
  test_count INTEGER,
  summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.9 experiment_runs

```sql
CREATE TABLE experiment_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  idea_id TEXT,
  dataset_snapshot_id TEXT NOT NULL,
  evaluation_spec_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  split_manifest_id TEXT NOT NULL,
  feature_set_id TEXT,
  model_version_id TEXT,
  runner_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT,
  params_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  summary_md TEXT,
  failure_reason TEXT,
  created_by TEXT
);
```

### 3.10 leaderboard_entries

```sql
CREATE TABLE leaderboard_entries (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  experiment_run_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  model_version_id TEXT,
  primary_metric_name TEXT NOT NULL,
  primary_metric_value REAL NOT NULL,
  rank INTEGER,
  is_candidate INTEGER NOT NULL DEFAULT 0,
  decision_status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.11 assets

```sql
CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  scope TEXT NOT NULL,
  owner_user_id TEXT,
  tags_json TEXT NOT NULL,
  semantic_tags_json TEXT NOT NULL,
  latest_version_id TEXT,
  visibility TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 3.12 asset_versions

```sql
CREATE TABLE asset_versions (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  version TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  digest TEXT NOT NULL,
  inputs_schema_json TEXT NOT NULL,
  outputs_schema_json TEXT NOT NULL,
  runtime_requirements_json TEXT NOT NULL,
  created_from_project_id TEXT,
  created_from_run_id TEXT,
  status TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

### 3.13 asset_references

```sql
CREATE TABLE asset_references (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_asset_id TEXT NOT NULL,
  target_asset_version_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  locked INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
```

### 3.14 lineage_edges

```sql
CREATE TABLE lineage_edges (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT,
  from_asset_type TEXT NOT NULL,
  from_asset_id TEXT NOT NULL,
  to_asset_type TEXT NOT NULL,
  to_asset_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```


### 3.15 forward_validation_results

```sql
CREATE TABLE forward_validation_results (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  deployment_id TEXT,
  model_version_id TEXT NOT NULL,
  prediction_set_id TEXT NOT NULL,
  actuals_ingestion_id TEXT NOT NULL,
  evaluation_candidate_id TEXT,
  evaluation_spec_id TEXT,
  local_metrics_json TEXT NOT NULL,
  forward_metrics_json TEXT NOT NULL,
  metric_gap_json TEXT NOT NULL,
  rank_consistency REAL,
  slice_consistency_json TEXT NOT NULL,
  calibration_gap_json TEXT NOT NULL,
  conclusion TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 3.16 reflection_events

```sql
CREATE TABLE reflection_events (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  summary TEXT NOT NULL,
  recommended_actions_json TEXT NOT NULL,
  affected_asset_refs_json TEXT NOT NULL,
  requires_approval INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
```

## 4. Asset Type一覧

```text
dataset_snapshot
semantic_catalog
eda_profile
understanding_report
question_set
assumption_set
evidence_set
evaluation_candidate
evaluation_scenario
forward_validation_result
reflection_event
evaluation_spec
metric_spec
split_manifest
baseline_report
feature_set
feature_recipe
prompt_template
llm_feature_cache
insight_set
improvement_idea
experiment_bundle
model
prediction_output
monitoring_report
skill
visualization_template
report_template
domain_taxonomy
data_quality_rule
connector_template
```

## 5. Lineage relation type

```text
uses
produces
derived_from
evaluates_with
trained_on
predicts_with
generated_by
visualizes_with
promoted_from
supersedes
approved_by
deployed_as
monitored_by
reflects_on
supports_assumption
```

## 6. 状態定義

### 6.1 Asset status

```text
draft
active
deprecated
archived
blocked
```

### 6.2 Job status

```text
queued
claimed
running
needs_approval
succeeded
failed
cancelled
timed_out
```

### 6.3 Approval status

```text
pending
approved
rejected
expired
auto_approved
```

### 6.4 Experiment status

```text
created
running
succeeded
failed
invalidated
excluded_from_leaderboard
candidate
promoted
```


### 6.5 Assumption status

```text
unknown
inferred
adopted
confirmed
challenged
revised
deprecated
```

### 6.6 Evaluation candidate status

```text
candidate
primary_candidate
alternative
promoted_to_spec
rejected
deprecated
proposed_after_reflection
```

### 6.7 Reflection event status

```text
open
acknowledged
actioned
dismissed
resolved
```

## 7. Content hash

Artifactのcontent hashは、ファイル内容とmanifest metadataを対象にする。

```text
hash_input = sorted(file_hashes) + artifact_manifest_json
content_hash = sha256(hash_input)
```

## 8. 再現性要件

ExperimentRunは以下を必ず保持する。

- dataset_snapshot_id
- evaluation_spec_id
- split_manifest_id
- feature_set_id
- code commit
- runner_type
- Python package lock hash
- random seed
- params_json
- input asset references
- output artifacts
- metric values

## 9. 論理削除

projectやartifactは初期MVPでは物理削除しない。UI上はarchivedにする。v1でretention policyを追加する。

## 10. Migration方針

- Alembicでschema migrationする。
- Artifact manifestはJSON Schemaでversion管理する。
- 後方互換性がない変更ではmigration jobを提供する。



---


# 04. MLライフサイクル仕様

## 1. Project Intake

### 1.1 ユーザー入力

必須:

- project name
- dataset
- target column
- task type候補
- 1行の意味
- 予測時点
- 予測結果の利用方法
- 成功条件

任意:

- time column
- group column
- columns not available at prediction time
- columns always safe
- business cost
- desired metric
- deployment target
- actuals arrival timing

### 1.2 Intake出力

- Project
- DatasetSnapshot
- initial SemanticCatalog
- initial AssumptionSet
- initial QuestionSet

## 2. Data Understanding

### 2.1 実行内容

#### Schema Understanding

- column count
- row count
- dtype inference
- semantic type inference
- ID候補
- timestamp候補
- group候補
- target候補確認
- constant columns
- high cardinality columns
- duplicate columns

#### Target Understanding

分類:

- class balance
- rare classes
- label distribution by time
- label distribution by group
- missing target
- target leakage proxy

回帰:

- distribution
- skewness
- zero inflation
- negative values
- outliers
- log transform候補
- time trend

#### Data Quality

- missingness per column
- row missingness
- duplicate rows
- near duplicate候補
- impossible values
- inconsistent category
- mixed types
- date parse failures
- suspicious default values

#### Relationship Understanding

- targetとの単変量関係
- numeric correlation
- categorical target rate
- mutual information
- temporal trends
- group-level aggregation risk
- cardinalityとunknown category risk

#### Leakage Detection

- targetと完全または過度に相関する列
- target名に近い列名
- `result`, `status`, `after`, `post`, `actual`, `label`, `score` などの列名
- timestampがtarget確定後の可能性がある列
- aggregate済みの未来情報
- IDがtargetを符号化している可能性
- duplicate leakage

#### Text Understanding

- text length distribution
- language estimate
- empty text
- duplicated text
- PII候補
- template text
- targetとの粗い関係
- embedding利用候補

### 2.2 生成物

- `eda_profile.json`
- `semantic_catalog.json`
- `understanding.md`
- `eda_report.html`
- `data_quality_report.md`
- `leakage_suspects.json`
- `questions.json`
- `assumptions.yaml`
- `evidence.json`
- `evaluation_candidates_preview.json`
- `figures/`

### 2.3 understanding.md構成

```md
# Data Understanding

## Executive Summary
## Dataset Overview
## Target Understanding
## Row Semantics
## Time and Group Structure
## Column Catalog Summary
## Data Quality Findings
## Leakage Risks
## Prediction Feasibility
## Recommended Evaluation Direction
## Questions for Human
## Assumptions
## Next Steps
```

### 2.4 Human Questions

質問はすべて次の構造を持つ。

```yaml
question_id:
topic:
question:
why_it_matters:
default_assumption:
impact_if_wrong:
choices:
priority:
risk_level:
value_of_answer:
can_proceed_without_answer:
fallback_policy:
related_columns:
related_assumption_id:
blocks_next_phase:
```

## 3. Human Q&A

ユーザー回答により以下を更新する。

- SemanticCatalog
- AssumptionSet
- excluded columns
- prediction time availability
- group/time column
- evaluation constraints
- business metric preference

回答履歴は削除せず、versionとして保持する。


## 4. Assumption Intelligence

Human Q&A後、または質問未回答のまま次フェーズへ進む際にAssumption Intelligenceを実行する。

### 4.1 入力

- UnderstandingReport
- SemanticCatalog
- QuestionSet
- Answer history
- LeakageCandidate
- DataQualityFinding
- Project intake情報

### 4.2 処理

1. 未回答質問を確認する。
2. 各質問に `risk_level`, `value_of_answer`, `fallback_policy` を割り当てる。
3. 回答済み事項からconfirmed Assumptionを作る。
4. 未回答事項からinferredまたはadopted Assumptionを作る。
5. Evidenceを紐付ける。
6. 高リスク事項はEvaluationScenario化する。
7. 未来情報候補はprimary featureから除外する。
8. 本番採用前に回答必須の事項をapproval gateに登録する。

### 4.3 未回答時の動作

| リスク | 動作 |
|---|---|
| low | infer_and_continue |
| medium | conservative_default |
| high | exclude_until_confirmed または scenario_compare |
| blocking | block_until_answered |
| deployment_blocking | 実験は進めるがdeployment前にrequire_before_deployment |

### 4.4 生成物

- `assumptions.yaml`
- `evidence.json`
- `unanswered_question_fallbacks.json`
- `assumption_risk_report.md`
- `scenario_requirements.json`

## 5. Reliable Evaluation

### 5.1 Evaluation Agentの役割

- EvaluationCandidateを複数作る
- 未回答事項に応じてEvaluationScenarioを作る
- primary candidateとalternative candidatesを分ける
- split候補を複数作る
- 推奨splitを選ぶ
- 推奨metricを選ぶ
- リーク候補列の除外を提案する
- ユーザー指示が不適切ならpushbackする
- EvaluationCandidateを生成する
- シナリオ比較結果を生成する
- 承認後にEvaluationSpecへpromoteする

### 5.2 Split候補

| 条件 | 推奨 |
|---|---|
| 独立同分布に近い | stratified random split |
| 時系列あり | time holdout |
| 将来予測 | rolling validation |
| 同一entity複数行 | group split |
| 時系列かつentityあり | time + group split |
| 未知group汎化 | leave group out |
| 不均衡分類 | stratified group split |
| near duplicateあり | duplicate-aware split |

### 5.3 Metric候補

分類:

- ROC AUC
- PR AUC
- Logloss
- F1
- Recall@Precision
- Precision@K
- Lift@K
- Calibration error

回帰:

- MAE
- RMSE
- RMSLE
- MAPE
- WAPE
- Pinball loss

需要予測:

- WAPE
- sMAPE
- MASE
- service level metric

### 5.4 Pushback

不適切な指示には一度明確に反論する。

例:

```text
random splitは選択できますが、このデータでは同一顧客が複数行に出ているため、trainとvalidに同じ顧客が混ざります。実運用で未知顧客を予測するならGroup splitが妥当です。random splitでは評価が楽観的になる可能性があります。
```


### 5.5 Evaluation Scenarios

EvaluationSpecを作る前に、次の候補集合を作る。

- primary_candidate: 保守的で本番相似性が最も高い候補
- alternative_candidate: 未回答事項や評価思想の違いを比較する候補
- reference_candidate: random splitなど参考値としての候補

比較する観点:

- model ranking stability
- metric gap
- fold variance
- feature importance stability
- leakage suspect impact
- segment metric consistency

シナリオ比較で結論が大きく変わる場合、該当Assumptionのriskを上げ、ユーザーへの質問優先度を上げる。

### 6.5 生成物

- `evaluation_candidates.json`
- `evaluation_scenarios.json`
- `scenario_comparison_report.md`
- `evaluation_spec.yaml`
- `metric_spec.yaml`
- `split_manifest.parquet`
- `split_summary.json`
- `evaluation_rationale.md`
- `leakage_check_report.md`

### 5.7 Approval Gate

EvaluationSpecは、baseline実行前に承認が必要。MVPではproject editorが承認可能。v1ではreviewer roleを導入する。

## 6. Baseline

### 6.1 Baseline群

分類:

- DummyClassifier
- LogisticRegression
- HistGradientBoosting
- LightGBM if available
- CatBoost optional
- TF-IDF + LogisticRegression for text

回帰:

- DummyRegressor
- Ridge
- RandomForest or HistGradientBoosting
- LightGBM if available
- TF-IDF + Ridge for text

時系列:

- last value
- moving average
- seasonal naive

### 6.2 Sanity Check

- dummyより有意に良いか
- fold間varianceが高すぎないか
- 予測が定数化していないか
- train/valid gap
- calibration
- prediction distribution
- segment別性能
- leakage suspect列による過剰性能
- permutation target test
- target shuffled baseline

### 6.3 Baseline Review

Baselineが以下に該当する場合、改善フェーズへ進まず差し戻す。

- dummyと差がない
- suspiciously high score
- fold varianceが大きい
- 一部splitだけ異常に高い
- targetリーク候補が上位重要度
- 評価setが実運用分布と大きく違う

### 6.4 Scenario-aware Baseline Review

Baselineはprimary EvaluationSpecだけでなく、必要に応じてalternative EvaluationCandidateでも実行する。シナリオ間でモデル順位や特徴量重要度が大きく変わる場合、その原因となるAssumptionをhigh riskへ昇格し、Improvement Loopへ進む前にEvaluation Reviewへ戻す。

### 6.5 生成物

- `baseline_report.md`
- `baseline_metrics.json`
- `prediction_valid.parquet`
- `feature_importance.csv`
- `sanity_check_report.json`
- `figures/`

## 7. Improvement Loop

### 7.1 ループ

```text
Read results
  -> Error analysis
  -> Generate insights
  -> Generate ideas
  -> Prioritize ideas
  -> Implement experiment
  -> Evaluate
  -> Register result
  -> Update leaderboard
  -> Decide keep/drop/needs-review
```

### 7.2 Insight

Insightは観測された知見。

```yaml
insight_id:
title:
description:
evidence_artifacts:
source:
  - eda
  - error_analysis
  - external_research
  - user_answer
confidence:
related_columns:
related_segments:
```

### 7.3 ImprovementIdea

```yaml
idea_id:
title:
hypothesis:
expected_effect:
implementation_plan:
risk:
source_insights:
status:
experiment_runs:
decision:
```

### 7.4 Error Analysis

- slice metrics by categorical columns
- temporal slice
- numeric quantile bins
- high confidence errors
- residual distribution
- feature importance
- permutation importance
- SHAP compatible later
- cluster of errors
- OOD-like samples

### 7.5 自律停止条件

- time budget exceeded
- cost budget exceeded
- target score reached
- no improvement for N runs
- repeated failures
- human approval needed
- leakage risk triggered

## 8. GenAI Feature Engineering

### 8.1 方針

v0.5以降で導入する。初期は安全な範囲に限定する。

### 8.2 Feature種別

- text summary
- text intent classification
- text sentiment or risk labels
- category normalization
- row narrative
- external knowledge enrichment
- embedding
- domain taxonomy mapping

### 8.3 必須制約

- targetをpromptに含める場合はOOFのみ
- valid/test targetはpromptに入れない
- prompt version、model、input hash、output hashを保存
- PIIをmask
- costを記録
- 本番推論で再現可能か確認
- 大幅改善時はleakage auditを実行

## 9. Deployment

### 9.1 Batch Prediction

```text
trigger
  -> fetch data
  -> schema validation
  -> feature generation
  -> model loading
  -> prediction
  -> output write
  -> monitoring
  -> report
```

### 9.2 Output

- local file
- S3 compatible storage
- Postgres table
- API response later

### 9.3 Approval

本番書き込みは承認必須。書き込み先、schema、行数、サンプル出力を表示する。

## 10. Monitoring

### 10.1 監視対象

- schema drift
- missingness drift
- feature distribution drift
- category appearance
- prediction distribution drift
- actual distribution drift
- performance drift
- calibration drift
- segment drift
- data freshness
- job failure rate

### 10.2 Evaluation Reflection

本番での前向き評価とlocal validationを比較する。

判断:

- splitが甘かった
- group leakageがあった
- target delayを考慮していなかった
- production distributionが変わった
- feature availabilityが違った
- metricが業務目的とズレていた

必要ならEvaluationSpecへ差し戻す。

## 11. Reports

レポートはMarkdownとHTMLの両方を出す。MarkdownはGit diffやAgent再利用に強く、HTMLはGUI表示に向く。

必須レポート:

- Data Understanding Report
- Evaluation Rationale
- Baseline Report
- Improvement Report
- Model Card
- Deployment Report
- Monitoring Report
- Evaluation Reflection Report


## 12. Forward Validation Reconciliation

Deploymentまたはbatch prediction後、actualsが到着したら前向き検証を行う。

### 12.1 入力

- PredictionSet
- ActualsIngestion
- ModelVersion
- EvaluationSpec
- EvaluationCandidate
- MonitoringRun

### 12.2 処理

1. predictionとactualsをjoinする。
2. forward metricsを計算する。
3. local validation metricsとの差を計算する。
4. model ranking consistencyを計算する。
5. slice別metricの再現性を確認する。
6. calibration gapを計算する。
7. feature driftとerror増加の関係を分析する。
8. Assumptionへのsupport/contradict evidenceを生成する。
9. 必要ならReflectionEventを作る。

### 12.3 出力

- `forward_validation_result.json`
- `forward_validation_report.md`
- `assumption_updates.json`
- `reflection_events.json`

## 13. Evaluation Reflection

Forward Validationでlocal評価と本番前向き評価が乖離した場合、評価設計を見直す。

### 13.1 トリガー

- primary metric gapが閾値超過
- model rankingがlocalとforwardで逆転
- 特定segmentで性能崩壊
- validationでは強かった特徴量がforwardで効かない
- prediction distribution driftが大きい
- calibrationが大きく崩れる

### 13.2 出力

- revised EvaluationCandidate
- Evaluation Redesign Proposal
- challenged Assumptions
- leakage suspect promotion
- retraining recommendation

### 13.3 後知恵過適合防止

前向き実績を見て提案された新EvaluationCandidateは、次のfuture windowで検証されるまでconfirmedにしない。



---


# 05. AgentとCodex統合仕様

## 1. 基本方針

Codexは、ハーネスの中核ではなく、制御されたworkspaceでコード作成、コード修正、実験実装、レポート生成を担当する実行エンジンである。

ハーネスが保持するもの:

- project state
- auth
- RBAC
- metadata
- artifacts
- lineage
- evaluation spec
- approval
- data access policy
- connector secret
- UI state

Codexが担当するもの:

- EDA補助コード生成
- feature recipe実装
- baseline script修正
- experiment script実装
- failed run repair
- report draft生成
- test生成
- code review補助

## 2. Codex統合方式

### 2.1 v0.2: Codex CLI Runner

`codex exec` をsubprocessで呼ぶ。

```text
Harness Worker
  -> prepare workspace
  -> write task_contract.json
  -> write output_schema.json
  -> run codex exec
  -> collect outputs/result.json
  -> validate schema
  -> register artifacts
```

### 2.2 v0.4: Codex App ServerまたはSDK Runner

Codex app-serverはJSON-RPC風のmessage schemaでthreadとturnを扱い、CLIからschema生成もできる。長いセッションやUIへの進捗反映が必要になった時点で採用する。

### 2.3 v0.5: Codex MCP Runner

CodexをMCP serverまたはMCP client連携で使い、ハーネスのMCP toolsを提供する。

### 2.4 fork方針

初期はforkしない。CLIまたはapp-server境界で利用する。以下が必要になった時だけforkを検討する。

- 内部イベントをUIに細かく流したい
- 独自sandboxを深く統合したい
- agent memoryを独自化したい
- provider差し替えが必要
- Codex prompt policyを完全制御したい

## 3. AgentRunner Interface

```python
from pydantic import BaseModel
from typing import Any, Literal

class WorkspaceRef(BaseModel):
    project_id: str
    path: str
    git_commit: str | None = None

class ExecutionPolicy(BaseModel):
    sandbox: Literal["read_only", "workspace_write", "full_access"]
    network: Literal["disabled", "harness_only", "restricted", "full"]
    timeout_seconds: int
    max_retries: int
    allow_secret_access: bool = False
    require_approval_for_external_network: bool = True
    require_approval_for_production_write: bool = True

class AgentTaskContract(BaseModel):
    task_id: str
    task_type: str
    project_id: str
    objective: str
    inputs: dict[str, Any]
    required_outputs: list[dict[str, Any]]
    quality_checks: list[str]
    forbidden_actions: list[str]
    context_files: list[str]
    output_schema_path: str

class AgentResult(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "needs_approval"]
    final_message: str
    outputs: dict[str, Any]
    artifacts: list[dict[str, Any]]
    warnings: list[str]
    failure_reason: str | None = None
    patch_summary: str | None = None
    raw_log_path: str | None = None
```

## 4. Task Contract

Agentに自然文だけを投げない。必ずcontract化する。

```yaml
task_id: task_exp_001
task_type: implement_feature_idea
objective: idea_023を実装し、指定splitで評価する
inputs:
  project_context: .harness/project_context.json
  evaluation_spec: data/evaluation_spec.yaml
  split_manifest: data/split_manifest.parquet
  idea: data/idea_023.yaml
required_outputs:
  - path: outputs/result.json
    schema: task_contracts/experiment_result.schema.json
  - path: reports/experiment_report.md
quality_checks:
  - split_manifestを必ず使う
  - evaluation_specを変更しない
  - target encodingはOOFで行う
forbidden_actions:
  - connector secretを読む
  - validation/test targetをpromptに入れる
  - production outputへ書く
```

## 5. Workspace Template

```text
project_workspace/
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

## 6. AGENTS.md要件

必須記載:

- Project context
- Never rules
- Always rules
- Data leakage rules
- Artifact output rules
- Testing rules
- Evaluation rules
- Security rules

## 7. Codex設定

初期の推奨:

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[features]
web_search = false
```

non-interactiveでは、ハーネス側が外部sandboxを強くしたうえで `approval_policy = "never"` を使う選択肢もある。ただし初期は `on-request` を維持し、approval要求はハーネス側jobに変換する。

## 8. セキュリティ境界

Codexに渡してよいもの:

- sample data
- schema
- profile
- semantic catalog
- split manifest
- evaluation spec
- code
- sanitized logs

Codexに渡してはいけないもの:

- DB password
- OAuth refresh token
- connector secret
- unmasked PII
- production write credential
- user Codex auth token
- full production data unless approved

## 9. Harness MCP Server

将来、Codexからハーネスの安全なtoolsを呼べるようにする。

tools:

- `get_project_context`
- `search_assets`
- `read_asset_version`
- `get_dataset_schema`
- `get_dataset_sample`
- `get_evaluation_spec`
- `get_split_manifest`
- `write_artifact`
- `register_experiment_result`
- `run_standard_evaluation`
- `request_approval`

## 10. Agent Friendly CLI

MCPと並行して `harnessctl` を提供する。

```bash
harnessctl project context --project-id p_123 --json
harnessctl dataset schema --dataset-id ds_456 --json
harnessctl artifacts register outputs/result.json --type experiment_result
harnessctl evaluation run --experiment-dir .
```

AgentはこのCLIを使う。CLIは標準出力でJSONを返し、secretは返さない。

## 11. Agent出力検証

すべてのAgent taskは以下を通す。

1. file existence check
2. JSON Schema validation
3. forbidden path check
4. artifact manifest check
5. metric sanity check
6. lineage completeness check
7. security policy check
8. optional deterministic re-run

## 12. 失敗修正ループ

Codex taskが失敗した場合:

```text
failure captured
  -> summarize failure
  -> create repair task
  -> pass traceback and relevant files
  -> run repair
  -> run tests
  -> validate outputs
```

最大2回まで自動repairする。以降はhuman review。

## 13. Agent Task種別

- `draft_data_understanding`
- `generate_eda_code`
- `repair_eda_code`
- `draft_evaluation_rationale`
- `implement_baseline`
- `repair_failed_run`
- `implement_feature_idea`
- `generate_experiment_report`
- `review_leakage_risk`
- `generate_visualization`
- `promote_skill_candidate`
- `draft_monitoring_report`

## 14. Codex利用上の前提

Codex CLIはローカルで動くcoding agentとして利用でき、CLI flagでsandboxやapproval policyを制御できる。Codexのsandboxはspawned commandsにも適用され、sandboxとapprovalは異なるが連携する制御として扱われる。ハーネスではCodexの制御に加えて、Data Access Brokerとworkspace隔離を必須とする。

## 15. 実装メモ

### 15.1 CodexCliRunner疑似コード

```python
def run_task(workspace, contract, schema, policy):
    write_json(workspace / ".harness/task_contract.json", contract)
    write_json(workspace / ".harness/output_schema.json", schema)

    prompt = render_prompt(contract)
    cmd = [
        "codex", "exec",
        "--cd", workspace.path,
        "--sandbox", "workspace-write",
        "--output-schema", str(workspace / ".harness/output_schema.json"),
        "--skip-git-repo-check",
        "-"
    ]

    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=policy.timeout_seconds,
        env=safe_env(),
    )

    return validate_and_import(result)
```

### 15.2 safe_env

- OPENAI_API_KEYは実行モードによって渡す。
- DB secretsは渡さない。
- HTTP_PROXYはData Access Broker経由に限定する場合のみ渡す。
- HOMEはworkspace専用の一時HOMEにする。
- CODEX_HOMEはworkspace外の専用隔離領域にする。


## 12. Assumption-aware Agent Tasks

Codex Runnerへ渡すtask contractには、必要に応じて以下を含める。

```json
{
  "assumption_context": {
    "active_assumptions_path": "data/assumptions.yaml",
    "evidence_path": "data/evidence.json",
    "unanswered_questions_path": "data/unanswered_questions.json",
    "fallback_policy_path": "data/fallback_policies.json"
  }
}
```

CodexはAssumptionを勝手にconfirmedへ変更してはならない。疑義がある場合は `outputs/result.json` の `proposed_assumption_updates` と `warnings` に返す。

禁止:

- high-risk Assumptionを無視して特徴量を使う
- 予測時点可用性がunknownの列をprimary featureへ入れる
- EvaluationSpecを直接変更する

許可:

- 新しいEvidence候補を提案する
- 追加質問を提案する
- alternative scenarioの必要性を提案する
- leakage suspectをwarningとして返す



---


# 06. セキュリティとコネクター仕様

## 1. セキュリティ原則

1. Agentにsecretを渡さない。
2. Agentに本番DBへの直接接続を許可しない。
3. 外部データアクセスはData Access Brokerを経由する。
4. 本番書き込みはapproval必須にする。
5. workspace外のファイルアクセスを制限する。
6. PIIはmask、redact、blockのいずれかを選べるようにする。
7. すべてのdata accessとproduction writeをaudit logに残す。
8. EvaluationSpecやSplitManifestを勝手に変更できないようにする。

## 2. Auth

### 2.1 v0.1

local auth:

- email/password
- local admin
- session cookie
- CSRF protection

### 2.2 v1.0

Google OIDC login:

- authorization code flow
- server side token exchange
- ID token validation
- domain allowlist
- organization mapping
- optional email domain policy

GoogleのOAuth 2.0 APIは認証と認可に使え、OpenID Connect実装はOpenID Certifiedである。Web server application flowではclient secretを安全に保持できるサーバー側アプリを想定する。

## 3. RBAC

Role:

| Role | 権限 |
|---|---|
| owner | 全操作 |
| admin | メンバー、connector、secret管理 |
| editor | dataset、EDA、実験、モデル |
| reviewer | evaluation、deployment承認 |
| viewer | 閲覧 |
| service_account | job実行 |

Permission:

- project.read
- project.write
- dataset.upload
- dataset.read
- evaluation.create
- evaluation.approve
- experiment.run
- model.promote
- deployment.create
- deployment.approve
- connector.create
- connector.read
- connector.use
- secret.manage
- audit.read
- asset.publish
- asset.use

## 4. Data Access Broker

### 4.1 概要

```text
Agent or Worker
  -> Data Access Broker API
  -> Policy Engine
  -> Connector
  -> External Data Source
```

### 4.2 機能

- connector credentialをsecret storeから取得
- callerのRBACを検査
- project policyを検査
- SQLをparseし、危険操作を拒否
- row limitを適用
- column maskingを適用
- data sampleをmaterialize
- audit logを書く

### 4.3 SQL Policy

初期はread-only。

許可:

- SELECT
- WITH
- LIMIT
- simple aggregation

拒否:

- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- TRUNCATE
- COPY TO arbitrary path
- external function
- network function

### 4.4 Sample Materialization

AgentにはDB接続を渡さず、sample fileを渡す。

```text
broker.materialize_sample(dataset_source_id, columns, filters, max_rows)
  -> /data/workspaces/{project}/data/sample.parquet
```

### 4.5 Masking

PII policy:

| level | 処理 |
|---|---|
| none | そのまま |
| low | project policyに従う |
| medium | hashまたは部分mask |
| high | redact |
| restricted | Agent利用禁止 |

## 5. Secret Management

v0.1:

- local encrypted file
- master key via environment variable

v1:

- cloud secret manager
- HashiCorp Vault optional
- KMS envelope encryption

SecretReferenceだけDBに保存し、secret本体はMetadata DBに保存しない。

## 6. Connectors

### 6.1 v0.1

- file upload
- local directory
- DuckDB file

### 6.2 v0.4

- PostgreSQL read-only
- S3 compatible read
- S3 compatible write with approval

### 6.3 v1

- BigQuery
- Snowflake
- Google Sheets
- GCS
- Azure Blob

## 7. Connector定義

```yaml
connector_id:
name:
type:
auth_type:
secret_ref:
allowed_projects:
read_policy:
write_policy:
masking_policy:
created_by:
created_at:
```

## 8. Production Write Approval

本番書き込み前に表示する。

- destination
- schema
- row count
- sample rows
- overwrite or append
- rollback plan
- model version
- input dataset snapshot
- output hash

承認後に一度だけ使えるwrite tokenを発行する。

## 9. Audit Log

必須項目:

```yaml
audit_id:
actor_type:
actor_id:
action:
resource_type:
resource_id:
project_id:
ip_address:
user_agent:
status:
metadata:
created_at:
```

audit対象:

- login
- dataset upload
- connector test
- sample materialization
- secret access by broker
- job started
- artifact registered
- evaluation approved
- deployment approved
- production write
- asset published
- permission changed

## 10. Agent Sandbox

### 10.1 初期

- workspace-write
- network disabled
- no direct secret env
- separate temp HOME
- max runtime
- max output file size
- max artifact count

### 10.2 将来

- sandbox-runner container
- seccomp
- read-only root filesystem
- resource limits
- egress proxy
- MCP tool approval

## 11. ネットワーク

原則:

- Agentの直接外部ネットワークは禁止
- 外部検索はハーネスのSearch Tool経由
- package installはsetup phaseまたは承認制
- production connectorはBroker経由

## 12. Compliance Checklist

v1までに満たす。

- secret never logged
- PII masking
- audit retention
- role based access
- asset visibility
- project export
- project deletion request
- connector least privilege
- production approval
- dependency vulnerability scan

## 13. Threat Model

### 13.1 Agent Prompt Injection

リスク:

- データ内テキストがAgentに命令する
- レポート生成時にsecret読み取りを誘導する

対策:

- data is data policy
- AGENTS.mdに明記
- Tool call policy
- schema validation
- forbidden action check

### 13.2 Leakage through Logs

対策:

- PII redaction before log
- stdout size cap
- secret pattern scanner
- raw logs access restricted

### 13.3 Connector Misuse

対策:

- read-only first
- SQL AST inspection
- row limits
- write approval
- audit

### 13.4 Evaluation Tampering

対策:

- EvaluationSpecは承認後immutable
- 新version作成のみ許可
- runはspec versionを固定
- lineage記録



---


# 07. UI/UX仕様

## 1. UI方針

このプロダクトのUIは、単なるAutoML画面ではなく、予測課題の調査、評価、実験、運用を進めるワークベンチである。

重要なUX原則:

1. 次に何を判断すべきかが常に分かる。
2. スコアの前提が常に見える。
3. Data UnderstandingとEvaluationがLeaderboardより上位にある。
4. エージェントの作業は透明だが、低レベルログを押し付けない。
5. Project固有アセットと横断アセットの関係が見える。
6. Skillの利用履歴、効果、依存関係が見える。
7. 未回答事項、仮定、推測の根拠、前向き検証による更新が見える。

## 2. Global Navigation

```text
Projects
Asset Library
Runs
Models
Deployments
Monitoring
Settings
```

## 3. Project画面

### 3.1 Overview

表示:

- current phase
- next action
- latest warning
- primary metric
- best run
- open questions
- high-risk assumptions
- unresolved deployment blockers
- pending approvals
- recent artifacts
- recent agent activity

CTA:

- Continue Understanding
- Review Questions
- Approve Evaluation
- Run Baseline
- Start Improvement
- Deploy Candidate

### 3.2 Data

- dataset snapshots
- upload
- schema preview
- column profiles
- sample rows
- data source info
- data quality summary

### 3.3 Understanding

- executive summary
- target distribution
- schema insights
- leakage candidates
- data quality findings
- charts
- questions
- assumptions
- evidence
- unanswered fallback warnings
- regenerate understanding
- mark insight as important

### 3.4 Assumptions

- assumption list
- confidence
- risk level
- fallback policy
- status
- related questions
- supporting and contradicting evidence
- used-in lineage
- confirm / reject / mark conditional
- scenario impact

### 3.5 Evaluation

- primary EvaluationCandidate
- alternative EvaluationCandidates
- scenario comparison
- recommended split
- alternative splits
- metric recommendation
- excluded columns
- leakage risks
- rationale markdown
- pushback history
- assumption dependencies
- unanswered blockers
- approval button
- create new version

### 3.6 Baseline

- baseline metrics
- dummy comparison
- sanity check status
- prediction distribution
- calibration
- feature importance
- segment metrics
- failure warnings
- go back to evaluation button

### 3.7 Experiments

- runs table
- filters by idea, model, feature set, status
- metric comparison
- params diff
- artifact links
- run detail drawer
- failed run repair action

### 3.8 Ideas

- idea board
- proposed
- selected
- implemented
- validated
- kept
- rejected
- needs human input

Idea card:

- title
- hypothesis
- expected effect
- risk
- source insights
- linked runs
- decision

### 3.9 Insights

- insight cards
- source filter
- confidence
- related columns
- related segments
- linked ideas
- promote to asset action

### 3.10 Leaderboard

- rank
- run
- model
- primary metric
- confidence interval
- secondary metrics
- valid/test split
- model risk
- selected candidate
- promotion status

必ず表示する:

- evaluation spec version
- split manifest version
- dataset snapshot version

### 3.11 Models

- model versions
- model card
- training data lineage
- metrics
- constraints
- feature set
- deployment readiness
- promote button

### 3.12 Reports

- Data Understanding Report
- Evaluation Rationale
- Baseline Report
- Improvement Report
- Model Card
- Monitoring Report
- Evaluation Reflection Report

### 3.13 Visualizations

- chart gallery
- chart source
- generated by
- related artifact
- export

### 3.14 Deployment

- candidate model
- input source
- output destination
- schedule
- approval status
- dry run
- production write preview
- rollback

### 3.15 Monitoring

- latest prediction run
- schema drift
- feature drift
- prediction drift
- actuals status
- performance
- calibration
- segment degradation
- forward validation result
- evaluation reflection suggestions
- assumption updates from actuals

### 3.16 Forward Validation

- prediction set
- actuals ingestion status
- local vs forward metric gap
- model ranking consistency
- slice consistency
- calibration gap
- ReflectionEvents
- proposed evaluation redesigns

### 3.17 Lineage

Graph nodes:

- DatasetSnapshot
- SemanticCatalog
- EvaluationSpec
- SplitManifest
- FeatureSet
- ExperimentRun
- ModelVersion
- Report
- Deployment
- MonitoringReport
- Skill

Graph interactions:

- click node
- show metadata
- show upstream
- show downstream
- compare versions
- open artifact

### 3.18 Assets

Projectが参照している横断アセットを表示する。

- Referenced Skills
- Referenced Evaluation Patterns
- Referenced Prompt Templates
- Referenced Visualization Templates
- Referenced Domain Taxonomies
- Local assets promoted from this project


## 3.19 Assumption detail drawer

各Assumptionをクリックするとdrawerで以下を表示する。

```text
Statement
Status
Confidence
Risk level
Fallback policy
Related columns
Related questions
User answers
Evidence timeline
Used in EvaluationCandidates
Used in FeatureSets
Used in Models
Forward validation signals
Recommended actions
```

アクション:

- Confirm
- Reject
- Mark as conditional
- Request more evidence
- Create scenario
- Exclude related column
- Promote to organization rule

## 3.20 Scenario comparison UI

Evaluation画面にscenario比較表を置く。

列:

- scenario name
- split type
- metric
- excluded columns
- assumptions
- risk
- baseline score
- model ranking stability
- forward consistency if available
- status

Primary scenarioとreference scenarioを明確に区別する。random splitを参考値として出す場合、primaryではないことをbadgeで示す。

## 4. Asset Library画面

### 4.1 Asset一覧

Filter:

- type
- tag
- owner
- scope
- status
- project usage
- created from project
- semantic similarity

Columns:

- name
- type
- version
- description
- tags
- usage count
- average impact
- owner
- status

### 4.2 Asset detail

表示:

- description
- versions
- input schema
- output schema
- runtime requirements
- tests
- examples
- usage history
- lineage
- dependent projects
- changelog
- promote/deprecate

### 4.3 Skill detail

- when to use
- when not to use
- required inputs
- outputs
- implementation files
- tests
- benchmark results
- security constraints
- usage examples
- known failure modes

## 5. Approval UX

Approvalは単なるOKボタンにしない。

表示:

- what will happen
- why recommended
- risks
- alternatives
- affected assets
- rollback
- audit record

Approval対象:

- EvaluationSpec
- production write
- external network
- connector access
- asset publish
- model promotion
- full trace capture

## 6. Agent Activity UX

表示レベルを3段階にする。

### 6.1 Human summary

- 何をしたか
- 何ができたか
- 次に何が必要か

### 6.2 Technical summary

- files changed
- artifacts generated
- commands run
- tests passed
- warnings

### 6.3 Raw logs

権限者のみ。

## 7. Empty States

各画面に次アクションを出す。

例:

- Dataset未投入: `CSVまたはParquetをアップロードしてください`
- Questions未回答: `評価設計の前に3件の確認が必要です`
- Evaluation未承認: `Baseline実行にはEvaluation Designの承認が必要です`
- Runsなし: `Baselineを実行してください`

## 8. Warning System

Warning level:

- info
- warning
- high risk
- blocking

Blocking examples:

- target column missing
- split manifest invalid
- validation target included in feature generation
- production write without approval
- connector secret exposed

## 9. Accessibility

- keyboard navigation
- color independent warning
- table search
- chart text summary
- downloadable reports

## 10. UI MVP

v0.1で作る画面:

- Login
- Project list
- Project overview
- Dataset upload
- Understanding
- Questions
- Evaluation
- Baseline
- Leaderboard
- Artifact viewer
- Job status

v0.2で追加:

- Agent activity
- Codex task logs
- Experiment detail
- Lineage v0

v0.3で追加:

- Ideas
- Insights
- Asset Library v0
- Skill detail



---


# 08. API、イベント、ジョブ仕様

## 1. API設計原則

- REST API first
- JSON request/response
- large filesはmultipart upload
- long running taskはJobとして扱う
- job statusはpollingとSSEに対応
- すべての変更操作はaudit logを残す
- project scopeを必ず検査する

## 2. API一覧

### 2.1 Auth

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/google/start
GET  /api/auth/google/callback
```

### 2.2 Projects

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
POST   /api/projects/{project_id}/archive
GET    /api/projects/{project_id}/overview
```

### 2.3 Datasets

```text
POST /api/projects/{project_id}/datasets/upload
GET  /api/projects/{project_id}/datasets
GET  /api/datasets/{dataset_id}
GET  /api/datasets/{dataset_id}/schema
GET  /api/datasets/{dataset_id}/sample
POST /api/datasets/{dataset_id}/profile
```

### 2.4 Understanding

```text
POST /api/projects/{project_id}/understanding/run
GET  /api/projects/{project_id}/understanding/latest
GET  /api/projects/{project_id}/questions
POST /api/questions/{question_id}/answer
GET  /api/projects/{project_id}/assumptions
PATCH /api/projects/{project_id}/assumptions
POST /api/projects/{project_id}/assumptions/infer
POST /api/assumptions/{assumption_id}/confirm
POST /api/assumptions/{assumption_id}/reject
GET  /api/assumptions/{assumption_id}/evidence
POST /api/projects/{project_id}/evidence
```

### 2.5 Evaluation

```text
POST /api/projects/{project_id}/evaluation/design
POST /api/projects/{project_id}/evaluation/scenarios/design
GET  /api/projects/{project_id}/evaluation/candidates
POST /api/evaluation-candidates/{candidate_id}/promote
GET  /api/projects/{project_id}/evaluation/specs
GET  /api/evaluation-specs/{spec_id}
POST /api/evaluation-specs/{spec_id}/approve
POST /api/evaluation-specs/{spec_id}/generate-split
GET  /api/split-manifests/{split_id}
```

### 2.6 Baseline and Experiments

```text
POST /api/projects/{project_id}/baseline/run
GET  /api/projects/{project_id}/runs
GET  /api/runs/{run_id}
POST /api/runs/{run_id}/repair
GET  /api/projects/{project_id}/leaderboard
POST /api/projects/{project_id}/experiments/run
```

### 2.7 Ideas and Insights

```text
GET  /api/projects/{project_id}/insights
POST /api/projects/{project_id}/insights
GET  /api/projects/{project_id}/ideas
POST /api/projects/{project_id}/ideas
PATCH /api/ideas/{idea_id}
POST /api/ideas/{idea_id}/run
```

### 2.8 Artifacts and Lineage

```text
GET /api/projects/{project_id}/artifacts
GET /api/artifacts/{artifact_id}
GET /api/artifacts/{artifact_id}/download
GET /api/projects/{project_id}/lineage
```

### 2.9 Asset Library

```text
GET  /api/assets
POST /api/assets
GET  /api/assets/{asset_id}
POST /api/assets/{asset_id}/versions
POST /api/projects/{project_id}/asset-references
DELETE /api/asset-references/{reference_id}
```

### 2.10 Jobs

```text
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/cancel
GET  /api/jobs/{job_id}/events
GET  /api/projects/{project_id}/jobs
```

### 2.11 Connectors

```text
GET  /api/connectors
POST /api/connectors
POST /api/connectors/{connector_id}/test
POST /api/connectors/{connector_id}/materialize-sample
```

### 2.12 Deployment and Monitoring

```text
POST /api/projects/{project_id}/deployments
POST /api/deployments/{deployment_id}/approve
POST /api/deployments/{deployment_id}/run
GET  /api/deployments/{deployment_id}/runs
POST /api/deployments/{deployment_id}/monitor
GET  /api/projects/{project_id}/monitoring
POST /api/projects/{project_id}/forward-validation/reconcile
GET  /api/projects/{project_id}/forward-validation
GET  /api/projects/{project_id}/reflection-events
```

## 3. Job Payloads

### 3.1 Data Understanding Job

```json
{
  "job_type": "run_data_understanding",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "options": {
    "max_rows_profile": 100000,
    "generate_html_report": true,
    "generate_questions": true
  }
}
```

### 3.2 Evaluation Design Job

```json
{
  "job_type": "design_evaluation",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "understanding_id": "u_001",
  "assumption_set_id": "as_001"
}
```


### 3.2.1 Assumption Inference Job

```json
{
  "job_type": "infer_assumptions",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "understanding_id": "u_001",
  "question_set_id": "qs_001",
  "options": {
    "apply_unanswered_fallbacks": true,
    "autonomy_level": 2
  }
}
```

### 3.2.2 Evaluation Scenario Design Job

```json
{
  "job_type": "design_evaluation_scenarios",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "assumption_set_id": "as_001",
  "options": {
    "include_reference_random_split": true,
    "max_candidates": 5
  }
}
```

### 3.3 Baseline Job

```json
{
  "job_type": "run_baseline",
  "project_id": "p_001",
  "dataset_snapshot_id": "ds_001",
  "evaluation_spec_id": "eval_001",
  "split_manifest_id": "split_001"
}
```

### 3.4 Agent Task Job

```json
{
  "job_type": "invoke_agent_task",
  "project_id": "p_001",
  "runner": "codex_cli",
  "task_contract_id": "task_001",
  "execution_policy": {
    "sandbox": "workspace_write",
    "network": "disabled",
    "timeout_seconds": 1800
  }
}
```


### 3.5 Forward Validation Reconciliation Job

```json
{
  "job_type": "reconcile_forward_validation",
  "project_id": "p_001",
  "prediction_set_id": "pred_001",
  "actuals_ingestion_id": "act_001",
  "model_version_id": "model_001",
  "evaluation_spec_id": "eval_001",
  "options": {
    "update_assumption_confidence": true,
    "create_reflection_events": true
  }
}
```

## 4. Events

### 4.1 Event envelope

```json
{
  "id": "evt_001",
  "type": "job.progress",
  "project_id": "p_001",
  "job_id": "job_001",
  "created_at": "2026-06-28T00:00:00Z",
  "payload": {}
}
```

### 4.2 Event types

```text
job.queued
job.started
job.progress
job.warning
job.needs_approval
job.succeeded
job.failed
artifact.created
lineage.created
question.created
question.answered
evaluation.created
evaluation.approved
run.metric_logged
run.succeeded
leaderboard.updated
agent.task_started
agent.patch_created
agent.output_validated
approval.requested
approval.approved
approval.rejected
assumption.inferred
```

## 5. Artifact Manifest

```json
{
  "artifact_id": "art_001",
  "asset_type": "baseline_report",
  "name": "baseline_report",
  "version": 1,
  "files": [
    {
      "path": "baseline_report.md",
      "sha256": "abc",
      "size_bytes": 1000
    }
  ],
  "metadata": {
    "project_id": "p_001",
    "run_id": "run_001"
  }
}
```

## 6. Error Response

```json
{
  "error": {
    "code": "EVALUATION_SPEC_NOT_APPROVED",
    "message": "Baseline cannot run before evaluation approval.",
    "details": {
      "project_id": "p_001"
    }
  }
}
```

## 7. Idempotency

POST APIは `Idempotency-Key` を受け付ける。job作成時は同一keyで重複jobを作らない。

## 8. API Versioning

初期は `/api` のみ。v1公開時に `/api/v1` へ固定する。

## 9. OpenAPI

FastAPIからOpenAPIを生成する。schemaはUIとAgent contractで再利用する。



---


# 09. 詳細開発計画

## 1. 開発方針

最初から全自律Agentや本番connectorを作らない。まず、ハーネスが管理する予測課題ライフサイクルの背骨を作る。

優先順位:

1. データモデル
2. Artifact Store
3. Project workflow
4. Data Understanding
5. Assumption Intelligence
6. Reliable Evaluation
7. Baseline
7. UI
8. Agent Runner
9. Improvement loop
10. Connectors
11. Forward validation and monitoring
12. Skill Registry

## 2. Milestone一覧

| Milestone | 目的 | 期間目安 |
|---|---|---|
| M0 | Repoと設計土台 | 1週 |
| M1 | Core platform | 2週 |
| M2 | DatasetとUnderstanding | 2週 |
| M2.5 | Assumption Intelligence v0 | 1週 |
| M3 | Reliable EvaluationとScenario | 2週 |
| M4 | BaselineとScenario-aware Leaderboard | 2週 |
| M5 | UI縦串 | 2週 |
| M6 | Codex CLI Runner | 2週 |
| M7 | Ideas、Insights、Improvement | 3週 |
| M8 | Asset Library、Skill v0 | 2週 |
| M9 | Security、Google OIDC、RBAC | 2週 |
| M10 | Secure Connectors | 3週 |
| M11 | Deployment、Monitoring | 3週 |
| M12 | Stabilization | 2週 |

合計はおよそ26週。ただし、M0からM6までの約14週で強いMVPができる。

## 3. M0: Repoと設計土台

### 3.1 成果物

- monorepo
- Dockerfile
- backend skeleton
- frontend skeleton
- worker skeleton
- docs
- CI
- lint
- test
- migration setup

### 3.2 タスク

- `apps/backend` 作成
- `apps/frontend` 作成
- `packages/shared-schemas` 作成
- `docs/` 作成
- Dockerfile作成
- local volume構成
- ruff, mypy, pytest設定
- eslint, prettier設定
- GitHub Actions設定
- AGENTS.md作成

### 3.3 Definition of Done

- `docker build` 成功
- `docker run -p 8080:8080` でfrontendとbackendが起動
- `/healthz` が200を返す
- backend testが通る
- frontend buildが通る

## 4. M1: Core Platform

### 4.1 成果物

- local auth
- Project CRUD
- Metadata DB
- Artifact Store
- Job model
- Event stream v0

### 4.2 タスク

- users table
- sessions
- projects table
- artifacts table
- jobs table
- lineage_edges table
- local artifact store
- file hash計算
- artifact manifest
- job worker loop
- SSE endpoint
- project overview API

### 4.3 DoD

- ユーザーがログインできる
- projectを作成できる
- artifactを登録できる
- jobを作成してworkerが処理できる
- UIでjob statusを見られる

## 5. M2: DatasetとData Understanding

### 5.1 成果物

- CSV/Parquet upload
- DatasetSnapshot
- SemanticCatalog
- Data profiler
- EDA report
- QuestionSet
- AssumptionSet

### 5.2 タスク

- upload endpoint
- file validation
- DuckDB/Polars loader
- schema inference
- column profiler
- target profiler
- missingness analysis
- leakage candidate detector v0
- semantic type detector
- understanding.md generator
- eda_report.html generator
- questions.json generator
- questions UI
- assumptions UI
- evidence model v0
- question priority and value_of_answer
- fallback_policy generation

### 5.3 DoD

- CSVをuploadできる
- schemaとsampleをUIで見られる
- Data Understanding jobを実行できる
- EDA reportがartifact登録される
- 生成質問に回答できる
- assumptionsがversion更新される
- 未回答質問にrisk_levelとfallback_policyが付与される


## 5.5 M2.5: Assumption Intelligence v0

### 5.5.1 成果物

- Assumption model
- Evidence model
- QuestionAssumptionLink
- unanswered fallback engine
- conservative default policy
- Assumptions UI
- assumption_risk_report.md

### 5.5.2 タスク

- assumptions table
- evidence table
- assumption_evidence_links table
- question_assumption_links table
- assumption inference job
- fallback policy resolver
- confidence and risk scoring v0
- unanswered question batch handling
- Assumption detail API
- Evidence API
- Assumptions tab UI
- assumption risk badges
- artifact generation for assumptions.yaml and evidence.json

### 5.5.3 DoD

- Data Understanding後にAssumptionが自動生成される
- 未回答質問にfallback policyが適用される
- 高リスクAssumptionがProject Overviewに出る
- Assumptionにsupport/contradict evidenceを紐付けられる
- ユーザーがAssumptionをconfirm/rejectできる

## 6. M3: Reliable EvaluationとScenario

### 6.1 成果物

- EvaluationCandidate
- EvaluationScenario
- EvaluationSpec
- MetricSpec
- SplitManifest
- Evaluation approval
- Pushback record

### 6.2 タスク

- task type detection
- metric recommendation
- random split
- stratified split
- time split
- group split
- time + group split
- split validation
- candidate promotion to EvaluationSpec
- scenario comparison report
- primary/alternative candidate generation
- evaluation_scenarios table
- evaluation_candidates table
- leakage exclusion proposal
- evaluation rationale generator
- approval UI
- split summary UI

### 6.3 DoD

- 3種類以上のsplitが作れる
- EvaluationCandidateを複数確認できる
- primaryとalternativeをUIで比較できる
- EvaluationSpecをUIで確認できる
- ユーザー承認できる
- 承認済みspecはimmutable
- candidateからspecへのpromote履歴が残る
- SplitManifestがartifact登録される

## 7. M4: BaselineとScenario-aware Leaderboard

### 7.1 成果物

- baseline runner
- dummy model
- sklearn model
- LightGBM optional
- sanity checks
- baseline report
- leaderboard v0
- scenario-aware leaderboard
- model ranking stability report

### 7.2 タスク

- feature preprocessing pipeline
- numeric imputation
- categorical encoding
- text TF-IDF optional
- dummy baseline
- logistic/ridge baseline
- tree baseline
- metric computation
- prediction artifact
- feature importance
- calibration plot
- slice metrics
- leaderboard API
- leaderboard UI
- scenario comparison leaderboard
- model ranking stability calculation
- scenario-aware baseline execution

### 7.3 DoD

- 承認済みEvaluationSpecでbaselineを実行できる
- metricsがrunに記録される
- leaderboardに表示される
- baseline_report.mdが生成される
- sanity check warningが表示される
- scenario間で順位が大きく変わる場合にAssumption warningが表示される

## 8. M5: UI縦串

### 8.1 成果物

Project体験の縦串。

- Project Overview
- Dataset
- Understanding
- Questions
- Evaluation
- Baseline
- Leaderboard
- Evidence drawer
- Artifact Viewer
- Job status

### 8.2 タスク

- layout
- global navigation
- project nav
- data table preview
- markdown report viewer
- chart viewer
- question form
- approval panel
- leaderboard table
- artifact download
- warning banner

### 8.3 DoD

- GUIだけでuploadからbaselineまで完了できる
- 次のアクションがOverviewに出る
- 外部画面に行かずに成果物を閲覧できる

## 9. M6: Codex CLI Runner

### 9.1 成果物

- AgentRunner interface
- CodexCliRunner
- workspace template
- AGENTS.md generator
- task contract
- output schema validation
- Agent activity UI

### 9.2 タスク

- workspace作成
- git init
- task_contract writer
- output_schema writer
- subprocess runner
- safe env
- timeout
- stdout/stderr capture
- result.json validation
- artifact import
- patch summary
- failed task repair
- Agent log UI
- config option for Codex path

### 9.3 DoD

- Codex CLIが利用可能な環境でtaskを実行できる
- outputs/result.jsonをschema検証できる
- Codexの生成物をartifact登録できる
- Codexが失敗した場合にrepair taskを作れる
- Codexなしでもnative runnerへfallbackできる

## 10. M7: Ideas、Insights、Improvement

### 10.1 成果物

- Insight model
- Idea model
- Error analysis
- Improvement run
- experiment report

### 10.2 タスク

- slice error analysis
- temporal error analysis
- high confidence error analysis
- insight generation
- idea generation
- idea board UI
- idea run action
- experiment runner
- run comparison
- decision status
- improvement_report.md

### 10.3 DoD

- baseline結果からinsightが作られる
- insightからideaが作られる
- ideaを選んで実験できる
- 結果がideaに紐付く
- 採用、棄却、要確認を記録できる

## 11. M8: Asset Library、Skill v0

### 11.1 成果物

- Asset
- AssetVersion
- AssetReference
- Skill Registry
- Project asset references
- Skill promotion

### 11.2 タスク

- asset tables
- asset API
- asset library UI
- skill schema
- skill detail UI
- project uses asset UI
- promote local recipe to skill
- version lock
- deprecate asset

### 11.3 DoD

- SkillをAsset Libraryに登録できる
- ProjectからSkillをversion固定参照できる
- 参照したSkillがrun lineageに残る
- Project発のSkill候補を昇格できる

## 12. M9: Security、Google OIDC、RBAC

### 12.1 成果物

- Google login
- Organization
- Team
- RBAC
- Audit log
- Secret reference

### 12.2 タスク

- Google OIDC flow
- organization table
- membership table
- role permission table
- project permission check
- audit log middleware
- secret encryption v0
- admin settings UI

### 12.3 DoD

- Googleでログインできる
- project単位で閲覧、編集権限を分けられる
- 評価承認と本番承認をroleで制御できる
- audit logを閲覧できる

## 13. M10: Secure Connectors

### 13.1 成果物

- Data Access Broker
- Postgres read-only connector
- S3 compatible connector
- Connector UI
- Sample materialization
- Production write approval

### 13.2 タスク

- connector registry
- secret reference integration
- Postgres connection test
- SQL AST validation
- row limit
- column masking
- sample materialization
- S3 read
- S3 write preview
- approval UI
- connector audit

### 13.3 DoD

- Postgresからsampleを取得できる
- AgentにDB secretを渡さない
- S3へ承認後に出力できる
- すべてaudit logに残る

## 14. M11: Deployment、Monitoring

### 14.1 成果物

- Deployment
- Batch prediction
- Actuals ingestion
- Drift monitoring
- Monitoring report
- Evaluation reflection

### 14.2 タスク

- model package format
- deployment config
- manual batch run
- scheduled batch run
- schema validation
- feature generation pipeline reuse
- prediction output artifact
- actuals upload
- performance calculation
- drift metrics
- monitoring UI
- reflection report
- evaluation redesign proposal
- assumption confidence update from actuals
- reflection event generation
- forward validation reconciliation

### 14.3 DoD

- candidate modelをbatch predictionに使える
- outputを保存できる
- drift reportが表示される
- actualsが来たら性能を計算できる
- local評価と本番評価の差を分析できる
- 前向き検証からAssumptionとEvaluationCandidateの見直し提案が出る

## 15. M12: Stabilization

### 15.1 成果物

- E2E tests
- sample projects
- docs
- backup/export
- performance tuning
- security hardening

### 15.2 タスク

- churn sample
- regression sample
- time split sample
- E2E test
- failure injection
- artifact cleanup
- DB migration test
- Docker image size reduction
- security checklist
- release note

### 15.3 DoD

- demo projectが10分以内にbaselineまで到達
- E2E testがCIで通る
- `/data` backupから復元できる
- known security issuesがtriaged済み

## 16. 初期35タスク

1. monorepo scaffold
2. Dockerfile
3. FastAPI healthz
4. Next.js shell
5. SQLite connection
6. Alembic setup
7. User model
8. Session auth
9. Project CRUD
10. Artifact model
11. Local artifact store
12. Job model
13. Worker loop
14. Dataset upload
15. DuckDB loader
16. Schema inference
17. DatasetSnapshot registration
18. SemanticCatalog v0
19. Data profiler
20. understanding.md generator
21. questions.json generator
22. Questions UI
23. Assumptions editor
24. Evidence model
25. Unanswered fallback resolver
26. EvaluationCandidate model
27. EvaluationSpec model
28. split generator
29. Metric recommender
30. Baseline runner
31. Scenario-aware Leaderboard API
32. Project Overview UI
33. Assumptions UI
34. Scenario comparison UI
35. Single Docker demo

## 17. 技術的負債を避けるルール

- ArtifactをDB blobにしない。
- EvaluationSpecをrun paramsに埋め込まない。
- Agent出力をschemaなしで取り込まない。
- Connector secretをworkspaceに置かない。
- Project固有Skillを横断Skillに昇格する前にテストを書く。
- UIがraw log前提にならないようにする。
- Leaderboardだけを中心にしない。

## 18. テスト計画

### 18.1 Unit

- schema inference
- split generator
- metric computation
- artifact hashing
- lineage edge creation
- permission check
- SQL policy
- evaluation candidate promotion
- evidence link creation
- assumption fallback resolver

### 18.2 Integration

- upload to understanding
- evaluation approval to split
- baseline run
- artifact registration
- Codex task run
- connector sample
- actuals to reflection event flow
- scenario comparison flow
- unanswered question to assumption flow

### 18.3 E2E

- CSV uploadからbaselineまで
- time split dataset
- group split dataset
- suspicious leakage dataset
- local-forward mismatch dataset
- unanswered high-risk assumption dataset
- failed agent task repair
- model deployment dry run

### 18.4 Security

- secret not in logs
- workspace escape attempt
- forbidden SQL
- PII masking
- production write without approval
- permission denied cases

## 19. Release Plan

### alpha

- local only
- single user
- upload datasets
- baseline complete

### beta

- Codex runner
- asset library
- multiple users
- Google login
- Postgres connector

### v1

- deployment
- monitoring
- secure connector
- skill promotion
- project export



---


# 10. 参照した外部仕様

この仕様書は、以下の外部仕様や公式ドキュメントを前提確認に使っている。

## Codex

- OpenAI Codex CLI: https://developers.openai.com/codex/cli
- OpenAI Codex GitHub repository: https://github.com/openai/codex
- Codex CLI reference: https://developers.openai.com/codex/cli/reference
- Codex sandboxing: https://developers.openai.com/codex/concepts/sandboxing
- Codex agent approvals and security: https://developers.openai.com/codex/agent-approvals-security
- Codex SDK: https://developers.openai.com/codex/sdk
- Codex app-server: https://developers.openai.com/codex/app-server
- Codex config basics: https://developers.openai.com/codex/config-basic
- Codex config reference: https://developers.openai.com/codex/config-reference
- Codex subagents: https://developers.openai.com/codex/subagents

## Google Auth

- Google OpenID Connect: https://developers.google.com/identity/openid-connect/openid-connect
- OAuth 2.0 for Web Server Applications: https://developers.google.com/identity/protocols/oauth2/web-server



---


# 11. Assumption Intelligence仕様

## 1. 目的

Assumption Intelligenceは、ユーザー回答が必要な事項をエージェント側から積極的に質問しつつ、回答がない場合でも停止せず、仮説、証拠、保守的fallback、複数シナリオ、前向き検証によって段階的に不確実性を詰めるための中核機能である。

本機能の基本方針は次の通り。

```text
質問する。
ただし、質問に依存して停止しない。
推測する。
ただし、推測を確定事項として扱わない。
進める。
ただし、riskとfallbackを明示する。
前向き実績が来たら、評価設計と仮定を反省する。
```

## 2. 対象となる不確実性

### 2.1 データ意味

- 1行が何を表すか
- ID列、entity列、group列の意味
- 日付列がイベント日、登録日、締切日、実績日、更新日、予測日なのか
- カテゴリ列の業務上の意味
- テキスト列の生成タイミング

### 2.2 予測時点可用性

- その列が予測時点で利用可能か
- 未来情報、事後情報、集計済み結果、手入力結果が混ざっていないか
- 実運用でAPIやDBから同じ値を取得できるか

### 2.3 評価設計

- random splitでよいか
- time splitが必要か
- group splitが必要か
- 未知entity汎化を評価するべきか
- 不均衡に対してPR AUCやRecall@Kなどが適切か
- 業務損失に合わせたcustom metricが必要か

### 2.4 運用実態

- actualsがいつ到着するか
- 本番入力の分布が学習データと同じか
- 本番では一部列が欠損するか
- 本番対象は既知顧客か新規顧客か

## 3. コア概念

### 3.1 Question

ユーザーに聞くべき事項。質問はブロッカーではなく、仮定生成の入口である。

### 3.2 Assumption

未確定事項に対して置かれた仮説。ユーザー回答、EDA、列名、split比較、前向き検証などの証拠に基づく。

### 3.3 Evidence

Assumptionを支持または反証する観測結果。

### 3.4 Fallback Policy

回答がない場合にどう進むかを定義する。

### 3.5 EvaluationCandidate

特定のAssumption集合に基づく評価設計候補。

### 3.6 EvaluationScenario

未確定事項を変えたときの比較評価単位。primary scenarioとalternative scenariosを持つ。

### 3.7 ForwardValidationResult

学習後に後から与えられるactualsと過去predictionを照合した結果。

### 3.8 ReflectionEvent

前向き検証、drift、本番性能劣化などに基づき、Assumption、EvaluationCandidate、FeatureSet、ModelVersionの見直しを提案するイベント。

## 4. Assumption lifecycle

```text
unknown
  -> inferred
  -> adopted
  -> confirmed
  -> challenged
  -> revised
  -> deprecated
```

| 状態 | 意味 |
|---|---|
| unknown | 不明点として検出されたが仮説未設定 |
| inferred | エージェントが証拠から推測した |
| adopted | 現在のworkflowで暫定採用中 |
| confirmed | ユーザー回答または十分な前向き証拠で確認済み |
| challenged | 反証証拠が出た |
| revised | 新しいstatementへ更新された |
| deprecated | もう使わない仮定 |

## 5. Assumption schema

```yaml
assumption_id: asm_042
project_id: p_001
topic: prediction_time_availability
statement: contract_end_date は予測時点では利用不可である
subject_type: column
subject_ref: contract_end_date
status: adopted
confidence: 0.72
risk_level: high
fallback_policy: exclude_until_confirmed
requires_user_confirmation: true
used_in:
  - evaluation_candidate:ec_013
  - feature_set:fs_007
evidence:
  - evidence_101
  - evidence_128
created_by: agent
created_at: '2026-06-28T00:00:00Z'
```

## 6. Evidence model

### 6.1 Evidence type

```text
user_answer
column_name_inference
schema_inference
eda_pattern
leakage_probe
split_comparison
baseline_result
experiment_result
forward_validation
drift_monitoring
external_research
cross_project_prior
```

### 6.2 Evidence strength

```text
weak
medium
strong
decisive
```

### 6.3 Link direction

```text
supports
contradicts
weakly_supports
weakly_contradicts
```

## 7. Fallback policies

| policy | 内容 | 典型用途 |
|---|---|---|
| infer_and_continue | 低リスクなら推測して進む | semantic type, non-critical description |
| conservative_default | 安全側の仮定を採用する | metric, missingness treatment |
| exclude_until_confirmed | 使えるか不明な列を除外する | 未来情報候補 |
| scenario_compare | 複数シナリオを作る | time/group split不確実性 |
| require_before_deployment | 実験は進めるが本番前に確認必須 | 本番書き込み、業務制約 |
| block_until_answered | 続行不可 | target column不明など |

## 8. Question prioritization

質問は `value_of_answer` と `risk_level` に基づいて並べる。

```yaml
question_id: q_102
topic: prediction_time_availability
question: contract_end_date は予測時点で利用可能ですか？
why_it_matters: 未来情報ならリークになります
default_assumption: 利用不可として扱う
impact_if_wrong: validation scoreが過大評価される可能性があります
risk_level: high
value_of_answer: very_high
can_proceed_without_answer: true
fallback_policy: exclude_until_confirmed
related_assumption_id: asm_042
related_columns:
  - contract_end_date
```

質問のUI分類:

```text
今すぐ答えると大きく改善
本番化前までに必要
回答がなくても保守的に進行可能
参考情報として聞いている
```

## 9. 推測ロジック

### 9.1 列名と型による推測

- `actual`, `result`, `final`, `status`, `closed`, `after`, `post`, `label` を含む列はリーク候補として扱う。
- `created_at`, `registered_at`, `order_date` はtime column候補として扱う。
- `customer_id`, `user_id`, `store_id`, `product_id` はgroup column候補として扱う。

### 9.2 EDAによる推測

- targetとの相関が極端に高い列はleakage probeに送る。
- ID列なのにtarget rateを強く符号化する列はgroup leakage候補にする。
- 欠損がtargetと強く連動する列は欠損自体の意味を確認する。

### 9.3 split比較による推測

- random splitだけ高く、time splitで落ちる場合は時間依存または未来リークを疑う。
- random splitだけ高く、group splitで落ちる場合はentity memorizationを疑う。
- ある列を含めた時だけvalid scoreが急増し、forwardで再現しない場合は予測時点不可用を疑う。

## 10. EvaluationCandidateとScenario

EvaluationSpecをいきなり1つに固定しない。まず候補集合を生成する。

```text
EvaluationCandidate:
  評価設計候補

EvaluationScenario:
  特定の未確定仮定を変えた比較単位

EvaluationSpec:
  現在採用されたprimary評価設計
```

例:

```yaml
evaluation_candidate_id: ec_018
scenario_id: sc_conservative_001
split_type: time_group
metric_primary: pr_auc
excluded_columns:
  - contract_end_date
  - final_status
assumption_ids:
  - asm_time_available
  - asm_future_columns_excluded
confidence: 0.76
risk_level: medium
status: primary_candidate
```

Alternative scenario例:

```yaml
evaluation_candidate_id: ec_019
scenario_id: sc_reference_random_001
split_type: stratified_random
metric_primary: pr_auc
excluded_columns:
  - contract_end_date
  - final_status
purpose: random split参考値。primaryにはしない。
status: alternative
```

## 11. Scenario comparison

複数シナリオでは次を比較する。

- primary metric差
- model rankingの安定性
- feature importanceの安定性
- leakage suspect列の影響
- fold variance
- segment別metricの安定性

シナリオによって結論が大きく変わる場合、ユーザーへ高優先度で確認を求める。

```text
この未回答事項により、best modelとPR AUCが大きく変わります。
本番判断前に contract_end_date の予測時点可用性を確認してください。
```

## 12. Forward Validation Reconciliation

actualsが後から到着したら、過去predictionと照合し、ローカル評価と本番前向き評価の整合性を検証する。

### 12.1 入力

- PredictionSet
- ActualsIngestion
- ModelVersion
- EvaluationCandidate
- EvaluationSpec
- SplitManifest
- MonitoringRun

### 12.2 計算するもの

- forward metric
- local valid metricとの差
- model ranking consistency
- slice metric consistency
- calibration gap
- prediction distribution shift
- feature driftとerror増加の関係

### 12.3 判定

| 判定 | 条件例 | アクション |
|---|---|---|
| consistent | localとforwardが近い | assumption confidenceを上げる |
| mildly_degraded | 小さく劣化 | monitoring継続 |
| evaluation_mismatch | localとforwardが大きく乖離 | Evaluation Reflection起動 |
| possible_leakage | validでは強いがforwardで崩壊 | leakage suspectを昇格 |
| concept_drift | feature driftと性能劣化が対応 | retraining候補 |

## 13. Evaluation Reflection

Evaluation Reflectionは、前向き検証を使って評価設計を見直すフェーズである。

### 13.1 反省対象

- primary EvaluationSpecが本番性能を予測できたか
- alternative EvaluationCandidateの方が本番に近かったか
- model rankingがlocalとforwardで一致したか
- slice別弱点が再現したか
- どのAssumptionが反証されたか

### 13.2 後知恵過適合の防止

前向き実績を見て作り直したEvaluationSpecは、すぐconfirmedにしない。次の未来windowで再検証されるまで `proposed_after_reflection` とする。

```text
old evaluation failed
  -> new evaluation candidate proposed
  -> next forward window validates it
  -> confirmed
```

## 14. Autonomy Levels

| Level | 内容 |
|---|---|
| 0 | すべて質問。推測はreportのみ |
| 1 | 低リスク事項は推測して進む |
| 2 | 中リスク事項も保守的fallbackで進む |
| 3 | 複数シナリオを自動実行する |
| 4 | 前向き検証に基づきevaluation redesignを自動提案する |
| 5 | 承認済みポリシー範囲内で評価仕様やfeature setを自動更新する |

MVPはLevel 2まで。Monitoring導入後にLevel 4まで対応する。Level 5はenterprise向けで慎重に扱う。

## 15. UI要件

Project内に `Assumptions` タブを設ける。

表示:

- Assumption statement
- confidence
- risk level
- fallback policy
- status
- related questions
- evidence list
- used in assets
- confirm / reject / mark conditional action

Evaluation画面では、primary EvaluationSpecだけでなく、EvaluationCandidateとScenario比較を表示する。

Monitoring画面では、ForwardValidationResultとReflectionEventを表示する。

## 16. API要件

必要なAPI:

```text
GET  /api/projects/{project_id}/assumptions
POST /api/projects/{project_id}/assumptions
PATCH /api/assumptions/{assumption_id}
POST /api/assumptions/{assumption_id}/confirm
POST /api/assumptions/{assumption_id}/reject
GET  /api/assumptions/{assumption_id}/evidence
POST /api/projects/{project_id}/evidence
POST /api/projects/{project_id}/evaluation/candidates
GET  /api/projects/{project_id}/evaluation/candidates
POST /api/evaluation-candidates/{candidate_id}/promote
POST /api/projects/{project_id}/forward-validation/reconcile
GET  /api/projects/{project_id}/reflection-events
```

## 17. Job要件

```text
infer_assumptions
apply_unanswered_fallbacks
design_evaluation_scenarios
compare_evaluation_scenarios
reconcile_forward_validation
reflect_on_evaluation
update_assumption_confidence
```

## 18. Guardrails

- 推測をconfirmedとして扱わない。
- 高リスク推測は本番採用前に確認または追加証拠を要求する。
- 未来情報候補は原則primary feature setから除外する。
- 後から実績を見て作った評価設計は、次windowで再検証するまでconfirmedにしない。
- Assumptionを変更した場合、そのAssumptionに依存するExperimentRun、ModelVersion、Deploymentのrisk badgeを更新する。

## 19. MVP Scope

v0.1に含める:

- Assumption model
- QuestionとAssumptionの紐付け
- confidence, risk_level, fallback_policy
- unanswered fallback
- conservative default
- EvaluationCandidate primary/alternative
- Assumptions UI

v0.2に含める:

- scenario comparison
- split別leaderboard
- model ranking stability
- question value_of_answer

v1.0に含める:

- ForwardValidationResult
- ReflectionEvent
- Evaluation Reflection
- assumption confidence update from forward validation
- evaluation redesign proposal
