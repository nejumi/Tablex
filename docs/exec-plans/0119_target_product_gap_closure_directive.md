# 0119: Target Product Gap Closure Directive（マスター指示書）

この文書は Tablex を「あるべき Tabular Harness」に到達させるための包括的な実装指示である。
[agent_interface_spec.md](../agent_interface_spec.md) と [AGENTS.md](../../AGENTS.md) を上位契約とし、本書はそれを拡張する。
矛盾がある場合は AGENTS.md の禁止事項（自然言語のルール処理禁止、Codex の進路に人工的な壁を作らない、maker 語彙を UI に出さない）が常に優先する。

作業は Workstream A→G の順に行う。各 Workstream には「現状」「目標」「実装指示」「受け入れ基準」がある。
**受け入れ基準を満たさない限りその Workstream は完了ではない。** 完了報告には受け入れ基準ごとの検証結果を添えること。

---

## 0. 全体ギャップ総括（なぜこの順か）

| # | ギャップ | 現状の根本原因 | Workstream |
|---|---|---|---|
| 1 | Full Auto が沈黙したまま止まる | 無出力タイムアウトが6時間（`MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 6*60*60`）。ストールが UI に出ない | A |
| 2 | 従来知見調査がほぼ何もされない | メインセッションが network 遮断 + `mcp_servers={}` + web_search 無効で起動され、調査が物理的に不可能。research runner は意図的 no-network スタブ | B |
| 3 | テストデータへの予測・予測パイプライン自動生成が存在しない | 実装未着手。model_package.joblib はベースライン専用で Codex authored モデルには無い | C |
| 4 | 仮運用（前向き観察）→ validation scheme 検証 → 自動イテレーションのループが存在しない | 実装未着手 | D |
| 5 | リーダーボードが内部 ID の羅列で、モデルの中身が分からず、スクリプトも取得できない | `summary_md` を API が返していない。UI が run_id を主役に表示。再現スクリプトの登録契約が無い | E |
| 6 | notebook に図が無い・静的埋め込みになる | レンダリング時のデータアクセスが無保証のため Codex が自衛的に静的化する（quality_manifest の図必須化は導入済みだが、データパス保証が無い） | F |
| 7 | UI が無意味に複雑 | 116 本の exec-plan の機能が刈り込みなしで堆積。main.tsx 17,000 行超 | G |

---

## 1. 全 Workstream 共通の絶対制約

1. **自然言語のルール処理を書かない。** 許されるのは fixed-format（JSON schema、ファイルパス、metric 名、artifact id、コマンド構文）の検証のみ。
2. **Codex の申告を書き換えない。** 検証で不整合を見つけたら (a) ack でエラーを返して Codex に修正させる、(b) `*_verified: false` フラグを付けて表示する、のどちらかのみ。ハーネスが黙って修復・差し替え・隠蔽することを禁止する。
3. **長い処理を HTTP リクエスト内で実行しない。** すべて Job + LocalWorkerDaemon へ。
4. **UI に maker 語彙（AgentSession、artifact id、schema 名、sidecar 等）を出さない。** 内部 ID は詳細展開のみに置く。
5. 新しい harness↔Codex プロトコルはすべて既存の `.tablex/requests/<domain>/` + `.tablex/acks/<domain>/` ファイル方式に従い、`schema_version` を持つこと。
6. 各 Workstream で backend テスト（pytest）を追加し、`pytest apps/backend/tests -q` を全部通すこと。frontend を触ったら `npm run build` を通すこと。
7. DB スキーマ追加は `ensure_sqlite_mvp_columns` / `init_db` の既存パターンに従い、既存データを壊さないこと。

---

## 2. Workstream A: Full Auto ストールの即時可視化と自動回復

### 現状
- [services/agent_sessions.py](../../apps/backend/tabular_harness/services/agent_sessions.py) の `MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60`。
- 実例: セッション `ags_103276d6d2bd` は `thread.started` 後 69 分間無出力のまま放置され、ユーザーの電源 OFF で終了した。この間 Chat/Activity には何も表示されなかった。

### 実装指示
1. タイムアウトを2段階にする:
   - `MAIN_AGENT_IDLE_TIMEOUT_SECONDS = 900`（15分。stdout/stderr のどちらにも1行も出ない場合）
   - `MAIN_AGENT_TURN_START_SILENCE_TIMEOUT_SECONDS = 300`（5分。`thread.started` 以降 item イベントが1つも来ない場合）
   - どちらも `Settings` から環境変数（`TABLEX_AGENT_IDLE_TIMEOUT_SECONDS` 等）で上書き可能にする。
2. 発火時: 既存の terminate→15秒→kill 経路を使い、既存のリトライバックオフ（`RETRY_BACKOFF_SECONDS`）でターンを resume する。`codex_thread_id` による resume で文脈は維持される。
3. **可視化（必須）**: ストール検知・再起動・連続失敗を「attention イベント」として次の3面に同時に出す:
   - transcript event（既存）
   - Agent Activity カード（status=`recovering`、「Codex からの応答が N 分間ありません。同じセッションを再起動しています（M回目）」）
   - Chat への harness 名義の事実陳述エントリ（`agent_chat_turn` artifact、intent.type=`harness_availability_notice`）。同一原因の連続発火は1エントリに集約し、スパムしない（同じ `issue_signature` は 30 分に1回まで）。
4. `notebook_auto_capture_failed`、ResearchPlan request の連続 reject、runner バックオフ中、`session.last_error` も同じ attention チャネルに乗せる。イベント種別ごとの場当たり実装をしない。

### 受け入れ基準
- [ ] フェイク codex（`tests` 内のスクリプトで `thread.started` だけ出して沈黙するダミーバイナリ）でセッションを回し、5分相当（テストでは短縮設定）で terminate→resume が起き、attention イベントが transcript / activity / chat の3面に生成されることを pytest で検証。
- [ ] 同一 signature の attention chat エントリが 30 分窓で1件に抑制されることを検証。

---

## 3. Workstream B: Prior Knowledge Research を実体化する

### 現状
- メインセッション起動コマンドは `--sandbox workspace-write`（network 遮断）+ `--ignore-user-config` + `-c mcp_servers={}`（[agent/runners.py](../../apps/backend/tabular_harness/agent/runners.py) `CODEX_HARNESS_CONFIG_ARGS`）。**Web 検索・外部取得は構造的に不可能。**
- [services/research_runner.py](../../apps/backend/tabular_harness/services/research_runner.py) は「ネットワークなしのスタブ」であり、実際の調査は一切行われない。
- つまり「従来知見調査がほとんどされない」のは仕様であって Codex の判断ではない。これを本物にする。

### 実装指示
1. **ネットワークポリシーの導入**（fixed-format の安全境界なので harness が握ってよい）:
   - `Settings` に `agent_session_network_enabled: bool = True`、`agent_session_web_search_enabled: bool = True` を追加。
   - メインセッションの codex 起動引数を組み立てる際、有効時に以下を追加する:
     - `-c sandbox_workspace_write.network_access=true`
     - web_search ツール有効化。**インストール済み codex-cli（0.142 系）で `codex exec --help` と `codex config --help` を実際に確認し、`--enable web_search` / `-c tools.web_search=true` のうち有効な方を使うこと。両方無効ならその事実を README に記録して network_access のみで進める。**
   - `safe_env` は現状維持（secrets は渡さない）。Kaggle credential は従来どおり harness 内プローブのみで、セッションに materialize しない。
2. **調査結果の登録プロトコル**: `.tablex/requests/research/` + `.tablex/acks/research/`、`schema_version: "tablex_research_request.v1"`、operation `register_research_findings`:
   ```json
   {
     "schema_version": "tablex_research_request.v1",
     "operation": "register_research_findings",
     "request_id": "res_001",
     "payload": {
       "research_plan_node_id": "prior_research",
       "topic": "salary prediction from job postings",
       "query_log": ["kaggle salary prediction solution writeup", "..."],
       "sources": [
         {
           "url": "https://...",
           "title": "...",
           "source_type": "kaggle_solution | arxiv | docs | blog | book | dataset_card | other",
           "retrieved_at": "2026-07-06T00:00:00Z",
           "key_claims": ["..."],
           "reliability_notes": "..."
         }
       ],
       "findings": [
         {
           "claim": "...",
           "source_indexes": [0, 2],
           "implication_for_project": "...",
           "recommended_action": "..."
         }
       ],
       "no_findings": null
     }
   }
   ```
   - `sources+findings` か、明示的な `no_findings: {searched_queries: [...], rationale: "..."}` のどちらかを必須とする（両方 null は schema エラー）。
   - `findings[].source_indexes` が `sources` の範囲内であることを検証（fixed-format 検証）。URL の実在確認や内容の真偽判定は**しない**（それは Codex の仕事）。
   - ack 成功時、harness は次を登録する: `research_findings_report` artifact（payload 全体）、`Evidence` 行（finding ごと）、plan node への `LineageEdge`。
3. **ターンプロンプト/GOAL の更新**（[agent_sessions.py](../../apps/backend/tabular_harness/services/agent_sessions.py) の `build_turn_prompt` / `build_default_goal_text`）に追記:
   - 「ネットワークと web 検索が利用可能である。prior-knowledge research は実際に外部ソースに当たること。対象領域の Kaggle 解法・論文・ドメイン知識・類似タスクのベンチマーク感覚を、`register_research_findings` で出典つきで登録するまで、prior_research 系ノードを done にしないこと。調査は一度きりでなく、モデリングや error analysis で新しい疑問が出るたびに戻ってよい。」
   - 「調査の厚さの目安: 初回 prior research では複数種別（kaggle_solution / arxiv / docs 等）にわたる実質的なソースを読み、プロジェクトの設計判断（target 定義、特徴量、validation scheme、リーク回避）に接続した findings を登録する。件数の下限は設けないが、『検索していない』と『調べたが有用な知見が無い』を混同しないこと。後者は no_findings として記録する。」
   - **注意: harness 側で「最低 N 件」の数値ゲートを実装しない。** 品質はプロンプト契約と人間のレビューで担保する（偽の readiness ゲート禁止の原則）。
4. **UI**: Notebooks/Reports と同格に、調査 findings を Home の plan node 展開と Reports タブから読めるようにする（出典リンク付きリスト表示）。表示は登録済み payload の素直な描画のみ。
5. 旧 `research_runner.py` スタブ経路と `research_source_pack` 生成 UI アクションは、新プロトコルと重複する部分を deprecated として UI から隠す（コード削除は不要、ただし新規経路から参照しない）。

### 受け入れ基準
- [ ] Full Auto を network 有効で起動したセッションのワークスペースから `curl https://example.com`（または codex 経由の web アクセス）が成功することを手動確認し、確認手順を docs/dev.md に記録。
- [ ] `register_research_findings` の正常系/schema エラー系/no_findings 系の pytest。
- [ ] ack 成功で Evidence・report artifact・plan node への lineage が作られることを検証。
- [ ] `agent_session_network_enabled=False` で従来どおり network 遮断になることを検証（後方互換）。

---

## 4. Workstream C: 予測パイプラインの自動生成と再現可能モデル

### 目標
リーダーボードに載る各モデルについて、**実運用と同じ入力形式を受け取り予測を返す、自己完結した Python パイプライン**が artifact として登録され、ダウンロード・harness 実行の両方ができる状態。時系列でも「履歴データの持ち方」「時系列派生特徴量のテスト時再計算」をパイプライン内部で完結させる。

### 実装指示
1. **登録プロトコル**: `.tablex/requests/pipelines/` + `.tablex/acks/pipelines/`、`schema_version: "tablex_pipeline_request.v1"`、operation `register_prediction_pipeline`:
   ```json
   {
     "schema_version": "tablex_pipeline_request.v1",
     "operation": "register_prediction_pipeline",
     "request_id": "pipe_001",
     "payload": {
       "pipeline_name": "median_by_pay_period_v2",
       "workspace_dir": "pipelines/median_by_pay_period_v2",
       "experiment_run_ids": ["run_..."],
       "research_plan_node_id": "modeling",
       "manifest": { "…下記 pipeline_manifest.json と同一…" }
     }
   }
   ```
2. **パイプラインディレクトリ規約**（Codex がワークスペース内に作る。ターンプロンプトに明記）:
   ```
   pipelines/<name>/
     pipeline_manifest.json
     train.py          # 生の学習データパスを引数に取り model/ 以下に成果物を保存
     predict.py        # 生の推論入力パスを引数に取り predictions.csv を出力
     requirements.txt  # 最小限の依存（バージョン固定）
     README.md         # 人間向け: モデル概要・特徴量・前提
     model/            # train.py の出力（joblib 等）。無くても predict 時に train を呼ぶ構成は不可
   ```
   `pipeline_manifest.json`（`schema_version: "pipeline_manifest.v1"`）必須フィールド:
   - `input_contract`: `{"inference_format": {"columns": [{"name","dtype","required"}], "description"}, "history_requirements": {"required": bool, "as_of_column": str|null, "history_window": str|null, "history_format": {...}|null, "notes"}}`
     - **inference_format は実運用入力（target 列なし）と完全一致であること。** 時系列の場合、予測時に必要な過去データは `history_requirements` として宣言し、lag/rolling 等の派生特徴量は **predict.py の内部で** 提供された履歴から再計算する。harness 側で特徴量を計算する経路を作らない。
   - `output_contract`: `{"columns": [{"name","dtype"}], "id_columns": [...], "prediction_column": str}`
   - `training`: `{"dataset_snapshot_id", "split_manifest_id", "evaluation_spec_id", "seed", "deterministic": bool}`
   - `expected_metrics`: `[{"name","value","split":"validation"}]`
   - `runtime`: `{"python":">=3.11","timeout_seconds_predict": int}`
3. **Harness 側検証（fixed-format のみ）**: ack 前に Job（worker 実行）で:
   - manifest schema 検証、ファイル存在検証、`requirements.txt` パース。
   - **スモーク実行**: 隔離 venv（`data/_pipeline_envs/<hash>` にキャッシュ、`pip install -r requirements.txt`）で、SplitManifest の validation 行から target 列を落とした入力を作り `predict.py` を実行。出力が `output_contract` に適合するか（列・行数・dtype・欠損）を検証。
   - 検証済み validation 予測から `evaluation_spec` の primary metric を**ハーネスの固定実装で**再計算し、`expected_metrics` との相対差を記録。差が大きくても **reject しない**。`metric_reproduced: true/false` と両値を ack と artifact metadata に記録する（Codex が自己修正できるように）。
   - schema/実行エラーは ack にエラー詳細（stderr 末尾、どのフィールドをどう直すか）を書いて Codex に返す。harness は修復しない。
   - 成功時: ディレクトリを zip 化して `prediction_pipeline` artifact として登録し、ExperimentRun（`experiment_run_ids`）と ModelVersion に lineage を張る。
4. **テストデータ予測の実行 API**: `POST /api/projects/{project_id}/pipelines/{artifact_id}/predict`（Job 化）。入力: アップロード済みの推論用ファイル（または DatasetSnapshot id）。出力: `prediction_batch` artifact（predictions.csv + 実行ログ + manifest 参照）。Workstream D がこの上に乗る。
5. **ターンプロンプト追記**: 「リーダーボードに登録する各モデルについて、`register_prediction_pipeline` で再現パイプラインを登録すること。パイプラインは学習に使った前処理・特徴量生成を predict 側で完全に再現し、実運用入力形式（target なし、宣言した履歴のみ）だけで動くこと。時系列特徴量は predict.py 内部で履歴から計算すること。」

### 受け入れ基準
- [ ] 正常パイプライン・出力契約違反・requirements 不正・タイムアウトの4系統の pytest（フィクスチャのダミーパイプラインで）。
- [ ] 時系列フィクスチャ（既存の retail time-series fixture を利用）で「履歴を与えると lag 特徴量を predict 内で再計算して予測が出る」e2e テスト。
- [ ] スモーク実行が worker Job として走り、HTTP リクエストをブロックしないこと。
- [ ] metric 再計算の不一致が reject にならず ack と metadata に記録されること。

---

## 5. Workstream D: 仮運用（前向き観察研究）フェーズと自動イテレーション

### 目標
実運用と同一形式で予測を出す「仮運用」を挟み、前向きに集めた実測とモデル予測を突き合わせて、
(1) validation scheme が正しかったかの検証、(2) validation/test 乖離の分解、(3) 原因仮説と改善案の立案、
(4) データ理解 → 文献調査 → モデリングへの自動再イテレーション、を Full Auto のまま回す。

### 実装指示
1. **DB エンティティ追加**（[models/entities.py](../../apps/backend/tabular_harness/models/entities.py)）:
   - `PilotDeployment`: id, project_id, pipeline_artifact_id, model_version_id?, experiment_run_id?, status(`active|paused|closed`), started_at, notes
   - `PilotPredictionBatch`: id, deployment_id, as_of(datetime), input_artifact_id, predictions_artifact_id, row_count, created_at
   - `PilotOutcomeBatch`: id, deployment_id, outcomes_artifact_id, join_keys_json, matched_rows, ingested_at
   - 突合結果はテーブルにせず `pilot_scoring_report` artifact（`schema_version: "pilot_scoring_report.v1"`: batch ごとの metric、予測-実測ペアの所在、期間情報）とする。
2. **API / UI**:
   - `POST /api/projects/{id}/pilot-deployments`（pipeline artifact を指定して開始。明示的 UI アクション）
   - `POST /api/pilot-deployments/{id}/predict`（推論入力アップロード → Workstream C の predict Job → PilotPredictionBatch 登録）
   - `POST /api/pilot-deployments/{id}/outcomes`（実測アップロード。`join_keys` は manifest の `id_columns` を既定とし、payload で上書き可）
   - outcomes 取り込み Job: 予測と実測を join_keys で突合し、EvaluationSpec の metric を**固定実装で**計算して `pilot_scoring_report` artifact を登録。解釈はしない。
   - UI: Leaderboard タブ内に「仮運用」セクション（デプロイ中モデル、バッチ履歴、期間別スコアの素直な表示）。
3. **Codex への還流（ここが本丸）**:
   - `pilot_scoring_report` が新規登録されたら、harness はメインセッションの inbox に `pilot_observation_available.md`（report の所在、validation 時の metric、pilot の metric、期間、行数）を書き、Full Auto が ON なら通常の supervisor 経路でターンが回る。**新しい専用ジョブ種を作って Codex を小間切れにしない。**
   - ターンプロンプト/GOAL に追記: 「仮運用の観察結果が届いたら、前向き観察研究として扱うこと: (a) validation scheme の妥当性を検証し、(b) validation/pilot 乖離を temporal drift / covariate shift / target 定義のずれ / リーク / 標本ノイズ等に分解し、(c) 各仮説に検証計画を付け、(d) `register_validation_audit` で登録した上で、ResearchPlan に次イテレーション（データ理解の深掘り、追加の文献調査、モデリング改訂）のノードを `commit_revision` で追加して作業を続けること。乖離が小さい場合もその判断と根拠を audit として登録すること。」
4. **監査の登録プロトコル**: `.tablex/requests/pilot/`、`schema_version: "tablex_pilot_request.v1"`、operation `register_validation_audit`:
   - payload: `deployment_id`, `scoring_report_artifact_ids`, `scheme_verdict`(`confirmed|partially_confirmed|refuted`), `gap_decomposition`: `[{component: "temporal_drift|covariate_shift|target_shift|leakage|sample_noise|data_quality|other", evidence: "...", magnitude: "...", confidence: "..."}]`, `hypotheses`: `[{id, statement, test_plan, expected_evidence}]`, `next_iteration_focus`
   - fixed-format 検証のみ（component の enum、参照 artifact の実在）。verdict の内容判断はしない。
   - ack 成功で `validation_scheme_audit` artifact + Evidence + plan node lineage を登録。UI は Reports と plan node 展開から読めるようにする。
5. **時系列の as-of 規律**: PilotPredictionBatch の `as_of` を必須にし、outcomes 突合時に `as_of` より後の実測のみを対象とする検証を入れる（fixed-format な時系列整合チェック。違反は reject ではなく `as_of_violations` として report に記録)。

### 受け入れ基準
- [ ] フィクスチャで「pipeline 登録 → pilot 開始 → 予測バッチ2回 → 実測取り込み → scoring report 生成 → inbox 通知ファイル生成」の一連を通す pytest。
- [ ] `register_validation_audit` の正常/schema エラー系 pytest。
- [ ] scoring report・audit が Leaderboard の仮運用セクションと Reports から開けること（frontend build + 手動確認手順を docs に記録）。
- [ ] [agent_interface_spec.md](../agent_interface_spec.md) に「Pilot Phase」セクションを追加し、上記ループを製品契約として記述。

---

## 6. Workstream E: リーダーボードの人間語化とスクリプトダウンロード

### 現状
- API（[routes.py](../../apps/backend/tabular_harness/api/routes.py) `leaderboard`）が `ExperimentRun.summary_md` を返していない。UI は `run_id` を主役に、`evaluation_spec_id` / 「no model version」等の内部情報を並べている。

### 実装指示
1. API 拡張: 各エントリに `summary_md`、`model_description`（params から）、`features_used`、`pipeline_artifact_id`（Workstream C の登録があれば）を追加。
2. `tablex_experiment_result_request.v1` の `register_runs` payload に **必須フィールド** `model_description`（このモデルが何をどう学習したかの1〜3文、ユーザー locale）と `features_used`（文字列配列）を追加。schema エラーは ack で返す。既存データは `model_description: null` を許容して表示側でフォールバック。
3. UI 列再設計: `Rank / モデル（model_label + model_description）/ スコア（display metric + 補助 metric）/ 根拠（notebook・diagnostics リンク）/ 操作`。`run_id`・spec id・model_version_id は行の詳細展開のみに移す。「no model version」「no split」等の文字列を UI から排除。
4. **ダウンロードボタン**: 各行に配置。
   - `GET /api/experiment-runs/{run_id}/pipeline-bundle` を追加: run にリンクされた `prediction_pipeline` artifact の zip を `FileResponse` で返す。未登録なら 404 と「pipeline 未登録」メッセージ。
   - UI: pipeline 登録済みの行はダウンロードボタン（zip: train.py / predict.py / requirements.txt / README.md / pipeline_manifest.json / model/）。未登録の行は無効状態ボタン + ツールチップ「再現スクリプトは未登録です」。
   - ターンプロンプトの Workstream C 追記により、以後の run は原則 pipeline 付きになる。過去 run への遡及生成は Codex の通常作業に任せる（harness で自動生成しない)。

### 受け入れ基準
- [ ] leaderboard API レスポンスに summary_md / model_description / pipeline_artifact_id が含まれる pytest。
- [ ] `register_runs` の model_description 欠落が schema エラーとして ack される pytest。
- [ ] bundle ダウンロード（登録あり/なし）の pytest。
- [ ] UI で内部 ID が既定表示に現れないこと（スクリーンショットを docs/evidence に記録）。

---

## 7. Workstream F: Notebook 品質契約の残り（データアクセス保証）

### 現状
- `quality_manifest`（figure_count 等）と「図必須・text/table-only は reject」は導入済み。
- しかし notebook 実行/レンダリング時のデータパスが保証されておらず、Codex は集計値をハードコードした静的 notebook を書く（実例: `ags_103276d6d2bd` の data_understanding notebook は図ゼロ・全セル静的 md）。

### 実装指示
1. `prepare_session_workspace` で `.tablex/data/` を作り、プロジェクトの各 DatasetSnapshot の主ファイルへの **symlink** を `<dataset_snapshot_id>__<元ファイル名>` として張る。context.json に `data_access: {"root": ".tablex/data", "files": [{"dataset_snapshot_id", "path", "rows", "columns"}], "guarantee": "このパスは notebook のレンダリング実行時にも同一に読める"}` を追加。
2. marimo export / native marimo 実行の cwd をワークスペースに固定し（現状の notebook 親ディレクトリ cwd から変更）、symlink が解決できることを保証する。export 実行環境の env に読み取り許可が足りない場合は symlink でなくコピーにフォールバック（サイズ上限 `Settings.notebook_data_copy_max_bytes`、超過時は symlink のまま）。
3. ターンプロンプト追記: 「notebook は `.tablex/data/` の実データを読み込んで図を描くこと。集計値のハードコード埋め込みは、実行コストが高い集計結果のキャッシュ（`artifacts/` 下の中間 JSON/parquet を読み込む形）に限る。」
4. native marimo セッション表示を notebook の唯一の正規ビューにする。静的 HTML export は notebook evidence、preview fallback、失敗隠蔽として使わない。起動が遅い場合は native marimo セッションのライフサイクル、キャッシュ、データ読み込み、事前検証を改善し、失敗は Chat/Activity に repair target として出す。

### 受け入れ基準
- [ ] workspace 準備後に `.tablex/data/` の symlink が存在し context.json に記載される pytest。
- [ ] `.tablex/data/` の CSV を読んで matplotlib 図を出すフィクスチャ notebook が capture 経路で HTML に図入りで出力される pytest。
- [ ] Notebooks タブの既定ビューが native marimo source を開き、static HTML fallback を生成・表示しないこと。

---

## 8. Workstream G: UI の刈り込み

### 実装指示
1. 既定表示タブを **Home（Chat + Activity + Research Plan）/ Data / Notebooks / Leaderboard / Raw** の5つに絞る。Assumptions / Evaluation / Approach / Experiments / Reports / Assets / Jobs / Lineage / Portal は「詳細」トグル（ユーザー設定で常時表示可）配下に移す。機能削除はしない。
2. main.tsx から最低限 `LeaderboardTab`・`ResearchPlan` 関連・`AgentChatDock` 関連を別ファイル（`src/components/…`）へ抽出する。**このリファクタは挙動変更と同一コミットにしないこと。**

### 受け入れ基準
- [ ] 既定5タブ + 詳細トグルが機能し、`npm run build` が通る。
- [ ] main.tsx の行数が有意に減少（目安 12,000 行未満）し、抽出コンポーネントが独立ファイルになっている。

---

## 9. 実施順序と全体 Definition of Done

実施順: **A → E → F → B → C → D → G**（A/E/F は即効性、B は C/D の前提となる調査文化の確立、C は D の前提、G は随時並行可）。

最終検証シナリオ（全 Workstream 完了の定義）:
1. 新規プロジェクトに時系列性のある CSV をアップロードし、Full Auto を ON にして放置する。
2. 数時間後: 図入りのデータ理解 notebook、出典つきの調査 findings、意味の分かるリーダーボード（各行にモデル説明とダウンロード可能な pipeline zip）が揃っている。途中でストールがあれば Chat に理由と再起動の記録が残っている。
3. リーダーボード上位モデルで仮運用を開始し、推論入力を与えると実運用形式の予測が出る。後日実測を取り込むと期間別スコアが表示され、Codex が validation scheme の検証・乖離分解・仮説・次イテレーション計画を audit として登録し、Research Plan に次サイクルのノードが追加されて作業が続いている。
4. この間、ユーザーが内部 ID や maker 語彙を読まされる場面がない。

各 Workstream の完了時に、本ファイルの該当セクションへ `Status: done (YYYY-MM-DD, commit)` を追記し、受け入れ基準のチェックボックスを埋めること。
