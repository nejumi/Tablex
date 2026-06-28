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
