# Tabular-first Prediction Meta-Harness 仕様書セット

この仕様書セットは、表データを起点とした予測課題ライフサイクルを、Codex互換のAgent実行エンジンで加速する自己完結型プロダクトの開発仕様です。

## 呼称

- プロダクト名: 未確定
- 仕様書内の仮置き名: `PRODUCT_NAME`
- 候補名: `Tablex`, `Tablex Workbench`, `Predictive Agent Workbench` など
- アーキテクチャ名: `Tabular-first Prediction Meta-Harness`
- 実行層: `Agent Runner`
- 初期実装のAgent Runner: `Codex CLI Runner`
- 将来の拡張Runner: `Codex MCP Runner`, `Codex SDK Runner`, `Hermes Runner`, `Native LLM Runner`

以後の仕様書では、ブランド名を固定しないため `PRODUCT_NAME` を用いる。実装上も `APP_NAME` などの設定値で差し替えられるようにする。

## この仕様が重視するもの

1. ハーネス内でUI、認証、アセット管理、リネージ、評価設計、承認、運用監視を完結させる。
2. Codexはプロダクトの親玉ではなく、制御されたworkspace内で動く強力なコード実行Agentとして使う。
3. スコア最大化より、Data UnderstandingとReliable Evaluationを最重要資産にする。
4. ユーザーへ必要な質問を行うが、未回答でも停止せず、仮説、証拠、フォールバック、複数シナリオ、前向き検証によって段階的に詰める。
5. Project固有アセットとCross-project再利用アセットを明確に分ける。
6. すべての成果物、仮定、質問、評価仕様、実験、モデル、監視結果、Skillをリネージで追えるようにする。

## ファイル構成

- `docs/01_product_spec.md`: プロダクト仕様
- `docs/02_architecture_spec.md`: アーキテクチャ仕様
- `docs/03_data_model_spec.md`: データモデル仕様
- `docs/04_ml_lifecycle_spec.md`: MLライフサイクル仕様
- `docs/05_agent_codex_integration_spec.md`: Codex統合仕様
- `docs/06_security_connectors_spec.md`: セキュリティとコネクター仕様
- `docs/07_ui_ux_spec.md`: UI/UX仕様
- `docs/08_api_events_spec.md`: API、イベント、ジョブ仕様
- `docs/09_development_plan.md`: 詳細開発計画
- `docs/10_references.md`: 参考情報
- `docs/11_assumption_intelligence_spec.md`: 未回答、不確実性、前向き検証による自己修正仕様
- `schemas/`: 主要JSON Schema
- `project_workspace_template/`: Codex Runner向けworkspaceテンプレート

## 開発の最初のゴール

最初の縦串MVPは、以下を1つのsingle Dockerで完結させることです。

1. CSV/Parquetをアップロードする。
2. Data Understandingを実行して、EDAレポート、質問、仮定、リーク候補を生成する。
3. ユーザーが質問に回答し、理解ベースを更新する。
4. 未回答の重要事項をAssumptionとして明示し、保守的なfallback policyを適用する。
5. Reliable Evaluationを設計し、primaryとalternativeのEvaluationCandidateを作る。
6. split manifestとmetric specを作る。
7. Baselineを実行し、sanity check、scenario比較、leaderboardを表示する。
8. すべての成果物をハーネスのArtifact StoreとMetadata DBに登録する。
9. Codex CLI Runnerで、EDA補助、実験コード生成、失敗修正、レポート生成を任せられる土台を作る。
