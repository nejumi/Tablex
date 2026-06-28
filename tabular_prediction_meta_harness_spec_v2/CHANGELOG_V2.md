# CHANGELOG V2

## 方針変更

- プロダクト名は未確定として扱う。
- 仕様書内では仮置き名 `PRODUCT_NAME` を使用する。
- `Tablex` / `Tablex Workbench` は候補名としてのみ記載する。
- 実装、DB、API、package名にはブランド名を固定しない方針に変更した。

## 追加された中核仕様

- Assumption Intelligence
- Question-driven, not Question-dependent の原則
- 未回答質問へのfallback policy
- Assumption confidence / risk / evidence / used-in lineage
- EvaluationCandidateとEvaluationScenario
- Scenario-aware baseline review
- Forward Validation Reconciliation
- Evaluation Reflectionによる評価設計の自己修正
- 後知恵過適合を防ぐ次window検証ルール

## 追加されたデータモデル

- Assumption
- Evidence
- AssumptionEvidenceLink
- QuestionAssumptionLink
- EvaluationCandidate
- EvaluationScenario
- ForwardValidationResult
- ReflectionEvent

## 追加されたSchema

- `assumption.schema.json`
- `evidence.schema.json`
- `evaluation_candidate.schema.json`
- `forward_validation_result.schema.json`
- `reflection_event.schema.json`

## 更新された計画

- M2.5: Assumption Intelligence v0 を追加
- M3: Reliable EvaluationをScenario設計込みへ更新
- M4: Scenario-aware Leaderboardを追加
- M11: Forward validationとReflectionEventを追加
- 初期タスクを30個から35個へ拡張
