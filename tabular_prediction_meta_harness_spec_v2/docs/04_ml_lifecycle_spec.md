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
