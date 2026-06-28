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
