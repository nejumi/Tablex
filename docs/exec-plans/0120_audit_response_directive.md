# 0120: Audit Response Directive（0119 監査への回答と次期指示）

前提契約: [AGENTS.md](../../AGENTS.md) / [agent_interface_spec.md](../agent_interface_spec.md) / [0119](0119_target_product_gap_closure_directive.md)。
本書は 2026-07-07 の外部監査（docs/evidence/0119_fable_audit_request.md への回答）で確定した残課題の実装指示である。
Workstream H1→H5 の順に実施する。**この文書に書かれていない新機能・新画面・新ヒューリスティックを追加しないこと。**
各 Workstream 完了時に受け入れ基準の検証結果を docs/evidence/0120_verification.md に追記する。

---

## Workstream H1: データ受け入れの自由化と TaskSpec の一級化（監査 Focus 1）

### 確定した違反
1. アップロード UI が primary table の選択を必須にしている（`App.tsx` の `canSubmitDataBundle` が `selectedPrimaryFileName` を要求。未選択時は `primaryTableRequired` 警告で送信不可）。
2. ハーネスが列名ヒューリスティックで意味推論している: `profiler.py` の `LEAKAGE_NAME_HINTS`（列名部分一致で leakage 疑い判定）と `infer_role`。その結果が UI の「target 候補チップ」（leakage バッジ・ランキング付き）としてユーザーの目的選択を誘導している。これは AGENTS.md「column-name heuristics で target/意図を推論しない」への直接違反。
3. 目的・タスク形状の一級オブジェクトが無い。`Project.target_column`（単一列・教師あり前提）が事実上の目的定義になっており、クラスタリング・複数 target・派生 target・集計粒度変更を表現できない。

### 実装指示
1. **アップロードの無条件受け入れ**: primary table 未選択でもアップロード可能にする。`canSubmitDataBundle` から primary 選択条件を外し、未選択時は「primary 未指定（Codex が後で判断します）」という中立表示にする。バックエンドは primary 未指定の DatasetSnapshot 群を正常状態として扱う。既存の `select_primary_table` ジョブ/API は「後から明示指定する手段」として残す。
2. **primary table の Codex 申告**: `.tablex/requests/data/` に `schema_version: "tablex_data_request.v1"`、operation `set_primary_table`（payload: `dataset_snapshot_id` または `artifact_id`、`rationale`）を追加。派生テーブルは operation `register_derived_table`（payload: `workspace_path`, `name`, `derivation`: {source_dataset_snapshot_ids, description}, `row_granularity`）で登録し、DatasetSnapshot として artifact 登録 + 元テーブルへの LineageEdge を張る。
3. **TaskSpec の導入**: operation `commit_task_spec`（`schema_version: "task_spec.v1"`）:
   - `objective_text`（自然言語の目的。ユーザー入力か Codex の仮定）
   - `task_shape`: enum `supervised_regression | supervised_classification | multilabel | multi_target | clustering | anomaly_detection | forecasting | distribution_prediction | aggregate_prediction | inverse_optimization | exploratory | other`
   - `targets`: `[{column, table_ref, derivation|null}]`（0個以上。派生 target は derivation 必須）
   - `granularity`: `{row_unit, aggregation|null}`
   - `assumptions`: `[string]`、`status`: `provisional | user_confirmed`
   - fixed-format 検証のみ（enum、参照テーブルの実在）。内容の妥当性判断はしない。ack 成功で `task_spec` artifact + plan node lineage。改訂は新 revision（上書き禁止、0119 絶対制約2に従う）。
   - `Project.target_column` は TaskSpec からの**表示用デノーマライズ**に降格する（TaskSpec 登録時に同期。直接編集 UI は残すが、編集は `status: user_confirmed` の TaskSpec revision として記録する）。
4. **列名ヒューリスティックの降格**: `LEAKAGE_NAME_HINTS` / `infer_role` の結果は profile artifact 内で `name_based_hints`（`"origin": "column_name_pattern"` を明記）に隔離する。UI の target 候補チップ（ランキング・leakage バッジ）は削除し、列一覧は統計値（型・欠損率・ユニーク数）のみの中立表示にする。data_quality ゲートがこのヒントを使う箇所は「hint 由来」であることを結果に明記し、ブロッカーには昇格させない。
5. **Full Auto の非停止**: target/objective 未定でループを止めるロジックが無いことを確認し（現状問題なしの見込み）、ターンプロンプトに「TaskSpec が無ければまずデータ理解から仮の TaskSpec を `commit_task_spec` で提出し、ユーザー確認を intervention window で求め、無回答なら provisional のまま続行する」を追記する。

### 受け入れ基準
- [x] primary 未選択・target 未入力・objective 未入力で CSV 2枚をアップロードし、Full Auto が開始できる（pytest: API レベル）。
- [x] `set_primary_table` / `register_derived_table` / `commit_task_spec` の正常系・schema エラー系 pytest。派生テーブルの lineage 検証を含む。
- [x] UI から target 候補チップと leakage バッジが消えている（`npm run build` + スクリーンショットを docs/evidence に保存）。
- [x] clustering を task_shape にした TaskSpec が targets 空で通る pytest（教師あり前提の排除確認）。

---

## Workstream H2: プロトコルとプロンプトの整理統合（脱線防止の本丸）

### 確定した問題
1. `build_turn_prompt` が 12,000 字超・約40箇条の平坦なルール列挙になっており、ターンごとに全文再送される。ルール追加のたびに Codex の遵守率が下がる構造。
2. inbox が **20 個の名前付きファイル**を列挙する方式になっており、プロンプトの1箇条が inbox ファイル名の羅列になっている。
3. 互換エイリアス（`run_ids`/`run_id`、`workspace_path`/`workspace_dir`、`pipeline_manifest_path` 等）が増殖中。
4. `services/agent_sessions.py` が 9,739 行の単一ファイルに肥大。

### 実装指示
1. **プロトコル文書の外部化**: ワークスペース準備時に `.tablex/PROTOCOL.md` を materialize する（内容はコード内の1定数から生成。ドメイン別: requests/acks の全 operation、schema、inbox の読み方、出力契約）。`build_turn_prompt` は次の構成に短縮する:
   - 不変の hard constraints（安全境界・評価境界・chat_update 契約）: 最大 10 箇条
   - 「詳細プロトコルは `.tablex/PROTOCOL.md` を読むこと。ターン開始時に必ず `.tablex/inbox/` を確認すること」
   - Goal / 未配達ユーザー指示 / 現在の plan 状態
   - 目標: プロンプト本文を 4,000 字以下にする。**削るのは重複と詳細であり、安全境界は削らない。**
2. **inbox の一本化**: `.tablex/inbox/` 直下の個別名ファイル方式を廃止し、`.tablex/inbox/<seq>_<kind>.json`（kind: `user_instruction | rejection | observation | request`、共通 envelope: `{schema_version: "tablex_inbox_entry.v1", kind, created_at, payload}`）に統一する。Codex への指示は「inbox のファイルを seq 順に全部読み、処理済みを `.tablex/inbox/.processed` に記録する」の1行になる。既存の書き込み箇所（rejection 系・progress_request・pilot_observation 等）を全てこの envelope に移行し、旧ファイル名の書き込みを削除する。読み手は同一セッションの Codex だけなので後方互換レイヤは**作らない**。
3. **エイリアス凍結**: 既存エイリアスは維持してよいが、**新規エイリアスの追加を禁止**する。今後 Codex の送信ミスは ack エラー（どのフィールドをどう直すかを含む）で自己修正させる。PROTOCOL.md には正式フィールド名のみ記載する。
4. **agent_sessions.py の分割**: 挙動変更なしの純リファクタとして、`services/agent_requests/`（research_plan.py / notebooks.py / experiments.py / pipelines.py / pilot.py / research.py / data.py）と `services/agent_supervisor.py`（supervisor/ターン実行）、`services/agent_workspace.py`（workspace 準備・ingest）に分割する。**リファクタ commit に機能変更を混ぜない。** 分割後も全テストが通ること。

### 受け入れ基準
- [x] `build_turn_prompt` の出力が 4,000 字以下（pytest でアサート）。`.tablex/PROTOCOL.md` が workspace に生成される。
- [x] inbox envelope の書き込み・列挙・processed 管理の pytest。旧個別ファイル名への書き込みコードが残っていない（grep で確認）。
- [x] agent_sessions.py が 2,000 行以下になり、全 393+ テストが通る。

---

## Workstream H3: Chat からの直接オープン契約（監査 Focus 3）

### 現状
フロントに `openAgentChatAction` → `setArtifactPreviewRequest` の直接オープン機構は存在するが、(a) backend が発行する action に `artifact_id` が無いものが残る、(b) 解決不能時に無言で汎用タブに着地する。

### 実装指示
1. **契約**: artifact/run/notebook/pipeline/pilot report に言及する chat action は `artifact_id`（または `experiment_run_id` 等の entity id）+ `asset_type` を**必須**とする。backend の action 生成箇所を全数調査し、欠落を埋める。schema: `{type, label, target_tab, target_anchor, artifact_id?, asset_type?, entity_ids?}`。
2. **フォールバックの事実陳述**: フロントで id が解決できない・preview API が 404 の場合、無言でタブ遷移せず「この項目は直接開けませんでした（артifact が見つかりません）」という事実トーストを出し、リスト画面に遷移する。
3. **対象ファミリーの網羅**: Report / Notebook / Research Finding / Prediction Batch / Leaderboard Run / Pipeline Bundle / Pilot Scoring Report / Validation Audit の8種それぞれについて「chat action → 該当ビューアが開く」pytest（API レベル: action payload に id が含まれること）+ 手動確認1回（docs/evidence に記録）。

### 受け入れ基準
- [x] 8 ファミリーの action payload id 網羅 pytest。
- [x] 解決不能時の事実メッセージ表示（フロント実装 + build 通過）。

---

## Workstream H4: レポートのリッチ化（監査 Focus 2）

### 現状評価
`research_findings_markdown_preview` は Codex 著フィールドの中立整形であり合格。ただし表現力が「フィールドの箇条書き」止まりで、比較表・画像・図・抜粋を含む厚い調査レポートを表示する経路が弱い。

### 実装指示
1. `register_research_findings` payload に任意フィールド `report_workspace_path` を追加: Codex が書いた**リッチな Markdown レポート**（画像相対参照・比較表・抜粋を含んでよい）を指す。存在検証のみ行い、artifact 登録して findings artifact と lineage で結ぶ。プレビューはこの Markdown を優先表示し、無ければ現行の整形 JSON 表示にフォールバックする。
2. Markdown プレビューで相対画像（同 workspace の figures）を artifact 化して表示できるようにする（report ingest 時に参照画像も artifact 登録し、preview HTML でパスを書き換える。fixed-format の参照解決のみ）。
3. ターンプロンプト（短縮後）の research 契約に1行追加: 「調査は URL リストではなく、比較表・図・出典抜粋を含む読み物としての report_workspace_path を添えること」。
4. **禁止**: バックエンドがレポート本文の叙述・解釈・推奨を生成しないこと（ラベルと Codex 著フィールドの整形のみ）。

### 受け入れ基準
- [x] report_workspace_path 付き findings の登録 → preview が Markdown + 画像で表示される pytest（画像参照解決を含む）。
- [x] 本文生成がフィールド整形のみであることをレビューで確認（新規テンプレ散文の追加なし）。

---

## Workstream H5: 実機 E2E 検証（最優先の単一シナリオ）

コード追加より先に、**現物のフル検証を1回行い、結果を docs/evidence/0120_e2e_run.md に記録する**:

1. 新規プロジェクトで時系列性のあるデータ（既存 retail fixture か実データ）を primary 未指定でアップロードし、objective も未入力のまま Full Auto ON。
2. 観察して記録する項目: (a) TaskSpec/plan が Codex 申告で進むか、(b) web 検索を伴う research findings が出典つきで登録されるか、(c) 図入り notebook が生成・表示されるか、(d) leaderboard にモデル説明とダウンロード可能な pipeline が並ぶか、(e) pipeline で予測バッチが作れるか、(f) 実測投入で pilot scoring → validation audit → plan 次サイクルが回るか、(g) 全過程でストール・沈黙・意味不明 ID が UI に出なかったか。
3. 発見した不具合は本文書に Workstream H6+ として追記してから修正する（その場しのぎの直接修正で終わらせない）。

---

## Workstream H6: TaskSpec liveness after primary-free upload（H5で発見）

### H5で観察した問題
1. primary未指定・objective未入力のfresh H5 runで、Codexは `set_primary_table` を提出し、primary DatasetSnapshotの登録までは成功した。
2. その後、`task_spec` artifact が無いまま分析/モデリングへ入る旨をChat/Rawで述べ、観察ウィンドウ内では `commit_task_spec` が提出されなかった。
3. これは target推定や目的判断をハーネスに戻す問題ではない。問題は、TaskSpecが一級状態であるにもかかわらず、primary確定後にTaskSpec未登録のまま長い作業へ進むことを防ぐ構造的な補助線が弱い点である。

### 実装指示
1. fixed-formatの構造状態だけを見る: `Project.primary_dataset_snapshot_id` が存在し、同Projectに `task_spec` artifact が存在しない場合、ハーネスはCodex workspace inboxへ `task_spec_request` を1回だけ送れる。
2. このrequestは自然言語の目的推論・列名ヒューリスティック・target推定をしてはならない。内容は「TaskSpecがまだ登録されていない。データ理解に基づく目的/粒度/タスク形状を、必要ならprovisionalとして `commit_task_spec` で提出せよ。非教師ありなら `targets: []` を使え」という固定形式の依頼に限定する。
3. リクエストはCodexを止めるゲートではない。モデル登録・Notebook登録など既存のfixed-format validationは維持するが、TaskSpecが無いことだけでローカルの可逆分析をブロックしない。
4. 重複防止を入れる。同一セッションで同じ構造状態に対して繰り返し同じrequestを送って、ChatやRawを汚さない。

### 受け入れ基準
- [x] primary DatasetSnapshotあり・task_specなしのprojectで、Codex session workspaceに `task_spec_request` inbox entryが作られる pytest。
- [x] task_spec artifactが存在するprojectではrequestが作られない pytest。
- [x] 同一セッションで同じrequestが重複しない pytest。
- [x] request本文に特定のtarget列名推定、列名ランキング、自然言語heuristicが含まれないことをpytestまたはレビューで確認する。

---

## Workstream H7: ResearchPlan protocol examples before TaskSpec（H5 bounded rerunで発見）

### H5で観察した問題
1. primary未指定・objective未入力のfresh bounded runで、CodexはResearchPlan更新を先に試みたが、`commit_revision` と `set_current_work` のfixed-format requestを4回失敗した。
2. 失敗内容は `payload.document` 不足、`payload.node_id` 不足、完了済み `data_upload` ノードの削除、open contractを持つ `prior_knowledge_research` の削除、存在しない `rp_data_understanding` をcurrent workに指定、であった。
3. これはCodexの判断をハーネスが肩代わりすべき問題ではない。ResearchPlan substrateの仕様は正しいが、runner-facing protocolが「最小の正しいrequest形」「既存anchorを残すこと」「current_work.node_idはactive revisionに存在すること」を十分に伝えられていない。

### 実装指示
1. `.tablex/PROTOCOL.md` に、正式フィールド名だけを使ったcanonical examplesを追加する:
   - `research_plan.commit_revision` の最小accepted envelope。`payload.document.timeline_blocks` を含み、既存のcompleted/open nodesを残したうえでCodex固有ブロックを足す例にする。
   - `research_plan.set_current_work` の最小accepted envelope。`payload.node_id` は直前のactive revision内に存在するnode idを使う例にする。
2. `.tablex/context.json` に既にactive ResearchPlan document / node ids が入っている場合は、PROTOCOL側で「contextのactive node idsを使う」と明示する。新しい推論ロジックやnode aliasは追加しない。
3. ACKエラーは引き続き固定形式で返す。ハーネスがResearchPlan文書を自動修復したり、node status/current workを推測して補正したりしてはならない。
4. ターンプロンプト本文は増やさない。詳細は `.tablex/PROTOCOL.md` に置き、H2の4,000字以下契約を維持する。

### 受け入れ基準
- [x] workspaceに生成される `.tablex/PROTOCOL.md` に、`commit_revision` と `set_current_work` のaccepted request例が含まれる pytest。
- [x] `build_turn_prompt` 4,000字以下のpytestが引き続き通る。
- [x] ResearchPlan request validatorの不変条件（完了済みnode削除拒否、存在しないcurrent_work node拒否）は緩めない。
- [x] fresh primary-free H5 rerunで、ResearchPlan requestの同種schema失敗がTaskSpec提出前に繰り返されないことを docs/evidence に記録する。

---

## Workstream H8: Primary-free data-framing nudge（H7 rerunで発見）

### H7 rerunで観察した問題
1. fresh primary-free runで、CodexはResearchPlan `set_current_work` を正しく提出できた。
2. その後、データを読んで小規模なモデリング/分析へ進んだが、観察ウィンドウ内では `set_primary_table` / `register_derived_table` / `commit_task_spec` を提出しなかった。
3. H6のTaskSpec nudgeは `Project.primary_dataset_snapshot_id` が存在する場合だけ動くため、primary-free upload状態ではTaskSpec登録の補助線が発火しない。

### 実装指示
1. fixed-formatの構造状態だけを見る: 同ProjectにDatasetSnapshotが1件以上存在し、`Project.primary_dataset_snapshot_id` が空で、同Projectに `task_spec` artifact が存在しない場合、ハーネスはCodex workspace inboxへ `data_framing_request` を1回だけ送れる。
2. このrequestは自然言語の目的推論・列名ヒューリスティック・target推定をしてはならない。内容は「primary tableが未登録でTaskSpecも未登録。データ理解に基づき、必要なら `set_primary_table`、派生行粒度が必要なら `register_derived_table`、目的/粒度/タスク形状が固まったら `commit_task_spec` を提出せよ。非教師ありなら `targets: []` を使える」に限定する。
3. リクエストはCodexを止めるゲートではない。可逆なローカル分析は継続できるが、Leaderboard/Notebook/Planと紐づく成果物を出す前に登録状態を揃えるよう促す。
4. 重複防止を入れる。同一セッションの同一DatasetSnapshot集合に対して繰り返し同じrequestを送らない。

### 受け入れ基準
- [x] primaryなし・DatasetSnapshotあり・task_specなしのprojectで、Codex session workspaceに `data_framing_request` inbox entryが作られる pytest。
- [x] primaryありのprojectではH6の `task_spec_request` に任せ、`data_framing_request` は作られない pytest。
- [x] task_spec artifactが存在するprojectではrequestが作られない pytest。
- [x] 同一セッションの同一DatasetSnapshot集合でrequestが重複しない pytest。
- [x] request本文に特定のtarget列名推定、列名ランキング、自然言語heuristicが含まれないことをpytestまたはレビューで確認する。

---

## Workstream H9: Pipeline request after artifact-based model result registration（H5 fresh runで発見）

### H5 fresh runで観察した問題
1. 新規primary-free H5 runで、Codexは `set_primary_table`、`commit_task_spec`、ResearchPlan修復、research findings、native marimo notebooks、モデル診断artifact、5件のExperimentRun登録まで到達した。
2. しかしExperimentRunは `artifacts/model_results.json` の自動取り込み経路で作成され、その経路ではprediction pipeline bundle提出依頼がinboxへ書かれなかった。
3. Codexが後から `.tablex/requests/experiments/` で同じ結果を再登録した時にはduplicate扱いになり、ackの `registered_runs` が空だったため、pipeline requestが出ないままFull Autoが「利用可能な可逆作業完了」で停止した。
4. H5の要件である「Leaderboardにモデル説明とダウンロード可能なpipelineが並ぶ」「pipelineで予測バッチを作れる」は未達である。

### 実装指示
1. `model_results.v1` などのstructured result artifactからExperimentRunが新規作成された場合も、`.tablex/requests/experiments/` 経由と同じく `experiment_pipeline_registration_status` を評価し、missingなら `.tablex/inbox/` に `pipeline_registration_request` を書く。
2. 同じrun集合・同じmissing statusのpipeline / diagnostics / diagnostics-notebook requestを重複して書かない。重複判定はfixed-format payload一致で行い、自然言語やモデル名の曖昧照合を使わない。
3. 既存のdiagnostics request生成は維持し、Codexがrun idを受け取ってmodel diagnostics artifacts/notebookを再提出できる経路を壊さない。
4. この変更は可逆分析やモデル登録をブロックしない。登録済みExperimentRunに必要な後続成果物をCodexへ返す補助線に限定する。

### 受け入れ基準
- [x] structured `model_results.v1` artifactの自動取り込みでExperimentRunが作られた時、`pipeline_registration_request` inbox entryが1件作られるpytest。
- [x] 同じartifactを再スキャンしても同一pipeline requestが増えないpytest。
- [x] 実験登録・diagnostics・pipeline関連の既存テストが通る。

---

## Workstream H10: Pilot observation must wake a completed Full Auto session（H5 pilot runで発見）

### H5で観察した問題
1. H9修正後のH5 projectで、prediction pipeline bundleは登録され、未ラベル入力からprediction batchを作成できた。
2. 実測outcomeを投入してpilot scoring reportも作成できた。
3. しかし対象のmain AgentSessionはResearchPlan全章完了により `completed` / project `IDLE` になっていたため、`notify_main_agent_session_of_pilot_report` が通知対象にせず、pilot observationがCodex workspaceへ渡らなかった。
4. さらにpilot用CSVを通常アップロードしたことでproject phaseが `UNDERSTANDING_REVIEW` になり、continuation jobの条件から外れた。
5. その結果、H5要件の「実測投入で pilot scoring → validation audit → plan 次サイクルが回る」が未達になった。

### 実装指示
1. `stopped` sessionはユーザー電源OFFの可能性があるため再開対象にしない。
2. `completed` sessionは「利用可能な可逆作業を終え、新しい入力待ち」状態なので、pilot scoring reportのような新しい観測入力が来た場合はworkspace inboxへ `pilot_observation_available` を届ける。
3. projectが `full_auto` かつ通知先sessionが見つかった場合、pilot observationは新しい入力として扱い、project phaseを `AUTONOMOUS_LOOP` に戻してcontinuation jobをqueueできるようにする。
4. この再開はpilot observationという構造化入力に限定する。自然言語や列名を解釈して再開判断してはならない。
5. Chat/Activityには内部状態語ではなく、pilot scoring reportが利用可能になった事実と次に見る場所だけを出す。

### 受け入れ基準
- [x] completed main AgentSession + full_auto project + pilot scoring reportで、workspace inboxに `pilot_observation_available` が書かれるpytest。
- [x] 同条件でproject phaseが `AUTONOMOUS_LOOP` に戻り、`continue_autonomous_session` jobがqueueされるpytest。
- [x] `stopped` sessionにはpilot observationを届けず、自動再開もしないpytest。
- [x] H5 projectでprediction batch、pilot scoring report、pilot observation delivery、continuation jobを実機確認し、docs/evidenceに記録する。

---

## Workstream H11: Agent power-off must terminate active child runner processes（H10 verificationで発見）

### H10 verificationで観察した問題
1. H10のpilot observation delivery確認後、検証用projectを停止した。
2. Stop APIはmain AgentSessionを `stopped` にし、queued/running jobsをcancelledにした。
3. しかし `run_planned_agent_task_codex` のchild Codex processが1本残り、手動でterminateする必要があった。
4. 電源OFFはTablexがCodexを止めてよい数少ない境界であり、main sessionだけでなく、同projectから起動したchild runner processも残してはならない。

### 実装指示
1. Stop API / `stop_autonomous_loop` jobは、同projectに紐づくactive child runner processを停止対象に含める。
2. 停止対象の同定は固定構造に限定する:
   - DB上のrunning/queued job id
   - job workspace path
   - runner metadata
   - process command lineに含まれる既知workspace pathまたはjob id
   自然言語、モデル名、ユーザー入力文から停止対象を推測してはならない。
3. 子プロセス停止はbest-effortではなく観測可能にする。停止したprocess id、見つからなかったprocess、kill escalationの有無をjob outputまたはworker event metadataに残す。
4. 停止処理は他projectのCodex processを巻き込んではならない。
5. UI文言は「実行中の作業を停止しました」程度に留め、pidや内部job種別を既定表示しない。詳細はRaw/diagnostic metadataで確認できればよい。

### 受け入れ基準
- [x] running child Codex processを持つprojectでStop APIを呼ぶと、そのchild processがterminateされるpytestまたはintegration test。
- [x] 別projectのCodex processは停止されないpytest。
- [x] main AgentSessionがないがrunning child jobだけがあるprojectでも、Stop APIがchild processを停止するpytest。
- [x] stop job outputにchild runner cleanup結果がstructured metadataとして残るpytest。
- [x] H10/H11実機確認をdocs/evidenceに追記する。

---

## 全体禁止事項（再掲・監査で再確認されたもの）
- 自然言語ルール処理・列名からの意図推論・数値ゲートの新設禁止。
- Codex 申告の書き換え禁止（ack エラーか verified フラグのみ）。
- 静的 HTML を notebook 実体として扱わない（native marimo source が正）。
- UI に maker 語彙・内部 ID を既定表示しない。
- 本書に無い新規サーフェス・新規プロトコル・新規エイリアスの追加禁止。判断に迷ったら作らずに docs/evidence に質問として記録する。
