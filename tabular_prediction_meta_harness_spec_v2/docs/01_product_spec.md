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
