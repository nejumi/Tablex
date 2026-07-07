# 0121: Audit Response Directive（0121 監査への回答と次期指示）

前提契約: [AGENTS.md](../../AGENTS.md) / [agent_interface_spec.md](../agent_interface_spec.md) / [0119](0119_target_product_gap_closure_directive.md) / [0120](0120_audit_response_directive.md)。
本書は docs/evidence/0121_fable_audit_request.md への外部監査回答として確定した残課題の実装指示である。
実施順は I1 → I2 → I3 → I4 → I5 → I6。**本書に無い新機能・新画面・新ヒューリスティック・新エイリアスの追加は禁止。**
各 Workstream 完了時に docs/evidence/0121_verification.md に受け入れ基準ごとの検証結果を追記する。

---

## Workstream I1: native marimo の信頼性と速度（監査懸念 2）

### 現状（監査で確定した欠陥）
[services/marimo_sessions.py](../../apps/backend/tabular_harness/services/marimo_sessions.py) は正しい骨格（artifact 単位の再利用、TTL、起動時孤児清掃、WebSocket プロキシ）を持つが、以下が実症状（`run-page-*.js` 404、直っても直らない source エラー、遅い初回起動）の原因になっている:

1. **セッションレジストリがプロセス内メモリのみ**（`_sessions_by_id`）。バックエンド再起動で全セッション参照が消え、開いたままの iframe のプロキシ URL が全て 404 になる（`run-page-*.js` 欠落の正体）。フロントは 404 後に再取得しない。
2. **ソース変更に無反応**: `marimo run` を `--watch` なしで起動し、同一 artifact の生存セッションを無条件再利用する。Codex がソースを修復してもユーザーには**修復前のエラーが見え続ける**。
3. **同時セッション数が無制限**: notebook を開くたびに Python プロセスが増え、メモリと起動遅延を悪化させる。
4. **初回起動が常にコールド**: クリック時に `marimo run` + 依存 import が走る。`_wait_for_startup` は未使用のデッドコード。

### 実装指示
1. **フロントの自己回復**: notebook ビューアで (a) プロキシ応答が 404/502、または (b) `GET /api/marimo-sessions/{id}` が 404 のとき、無言で壊れた iframe を出し続けず、自動で `POST /api/analysis-notebooks/{artifact_id}/marimo-session` を再実行して新しい proxy_url に張り替える。再取得中は「ノートブックを再起動しています」の中立表示。2回連続失敗で runtime error パネル（後述4）へ。
2. **ソース鮮度**: セッション作成時に notebook ファイルの sha256 を記録し、`start_or_get` の再利用判定で現在のファイルハッシュと比較。不一致なら旧プロセスを terminate して新セッションを起動する（`--watch` は multi-user 挙動が不安定なため採用しない。ハッシュ比較のみ）。
3. **上限と予熱**: `Settings.marimo_max_sessions`（既定 4）を追加し、超過時は `last_accessed_at` 最古のセッションを terminate（LRU）。`register_notebook` の ack 成功後、対象 notebook のセッションを**バックグラウンド Job で予熱起動**する（上限内のみ・失敗しても ack は変えない）。これで「最初に開く人」が cold start を踏まない。
4. **失敗の見せ方**: セッション `status=failed` 時、ビューアに (a) `runtime.error_excerpt` の要約、(b)「Codex に修復を依頼」ボタン（既存の inbox envelope `notebook_runtime_failure` を書き、plan の repair 対象として表示）を出す。静的 HTML への切り替えは行わない（禁止事項）。
5. **掃除**: `_wait_for_startup` を削除（または readiness ポーリングとして実際に使用）。`_cleanup_locked` をセッション起動時だけでなく LocalWorkerDaemon の周期処理からも呼び、TTL 超過プロセスが「次に誰かが開くまで」生き残らないようにする。

### 受け入れ基準
- [ ] バックエンド再起動をシミュレートし（レジストリ clear）、ビューアが自動でセッションを再取得して表示が復帰する（フロント実装 + 手動確認を evidence に記録）。
- [ ] ソース更新後に開き直すと新プロセスで新ソースが表示される pytest（ハッシュ不一致→新セッション）。
- [ ] `marimo_max_sessions` 超過時に LRU terminate される pytest。
- [ ] 予熱 Job が register_notebook 後に走る pytest（marimo 不在環境では skip）。
- [ ] failed セッションでエラー要約と修復依頼ボタンが表示され、inbox entry が書かれる（API テスト + 手動確認）。

---

## Workstream I2: ストレージ成長の制御（監査懸念 9）

### 現状
`data/` が **79GB** に達している（前回監査時 62GB）。成長源: (a) 同名 artifact の全バージョン永久保存（chat_update.md は変更のたびに新バージョン）、(b) `data/_pipeline_envs` の隔離 venv、(c) `data/marimo_sessions` の残骸、(d) セッションワークスペースと artifact store への二重取り込み。

### 実装指示
1. **content-hash 再利用**: `store_existing_file` / `register_artifact` 経路で、同一 project + asset_type + name + content_hash の既存 artifact があれば新バージョンを作らず既存を返す（登録スキップのログのみ）。
2. **保持ポリシー**: `Settings.artifact_version_retention`（既定 5）。同名 artifact の古いバージョンは、(a) LineageEdge の参照がある、(b) plan の completion_evidence/attach 対象、(c) ModelVersion/pipeline/pilot が参照、のいずれかに該当しない場合に限り、ファイル実体を GC 対象にできる。**GC は自動削除しない**: `POST /api/admin/storage/gc`（dry_run 既定 true）で対象一覧レポートを artifact 化し、ユーザーが実行を確定する。
3. **一時領域の TTL 掃除**: `_pipeline_envs`（最終使用から 14 日）、`marimo_sessions` workdir（セッション終了時即時 + 起動時残骸）、`.tablex/acks`/`requests` の処理済み（90 日）を LocalWorkerDaemon の周期タスクで削除。
4. **可視化**: `GET /api/admin/storage/usage`（カテゴリ別バイト数: datasets / artifacts / workspaces / pipeline_envs / marimo / db）を追加し、設定画面に表示する。
5. **禁止**: DatasetSnapshot・EvaluationSpec・SplitManifest・登録済み pipeline bundle の実体削除を GC 対象にしない。

### 受け入れ基準
- [ ] 同一内容の再取り込みが新バージョンを作らない pytest（chat_update.md 連続 ingest で 1 バージョンのまま）。
- [ ] GC dry-run が保護条件（lineage/plan/model 参照）を尊重する pytest。
- [ ] usage API のカテゴリ集計 pytest + 設定画面表示（build 通過）。
- [ ] 実データで dry-run を実行し、削減見込みを docs/evidence/0121_verification.md に記録。

---

## Workstream I3: アセット情報設計の人間中心化（監査懸念 1）

### 現状評価
直接オープン（H3）と plan への成果物リンクは実装されたが、Assets タブは依然 **内部 asset_type 中心の在庫一覧**であり、「データ理解ノートブックを読む」「このモデルの診断を見る」という人間のタスクから出発できない。ユーザーのメンタルモデル: 「成果物は plan の各章とモデルの各行に属する」— 現 UI は「成果物は型別リストに属する」。

### 実装指示
1. **発見の主経路は文脈側に置く**: (a) Research Plan の各ノード展開に「このノードの成果物」ドロワー（既存 attach/evidence リンクの整形表示: notebook / report / run / pipeline / research findings を人間ラベルで）、(b) Leaderboard 行展開に「このモデルの成果物」（diagnostics notebook・report・pipeline bundle・prediction batches）を置く。両者は同一の `RelatedOutputsDrawer` コンポーネントを再利用する。
2. **Assets タブは「全在庫 + 検索」に再定義**: グルーピングを内部 asset_type の羅列から人間カテゴリ（`ノートブック / レポート / モデルと予測 / 調査 / データ / 計画と記録 / その他`）への固定マッピングに変更。マッピングは copy.ts の静的辞書（fixed-format）で行い、推測しない。名前検索と「plan ノードで絞る」フィルタを付ける。supporting 扱いで隠している生成物は「その他」に**見える形で**残す（隠さない）。
3. **来歴パネル**: artifact preview に既存 LineageEdge の1ホップ表示（「この成果物の元になったもの / これを使ったもの」を人間ラベルで最大10件、クリックで直接オープン）を追加。グラフ描画は作らない（1ホップリストで十分）。
4. **禁止**: 新タブ・新概念名（"evidence graph" 等）の導入。既存タブ構成のまま中身を組み替える。

### 受け入れ基準
- [ ] plan ノードと leaderboard 行から同一 drawer で成果物が開ける（コンポーネント共有、build 通過、スクリーンショット）。
- [ ] Assets の人間カテゴリ分類が静的辞書によることをレビュー確認（推測ロジックなし）。
- [ ] preview の来歴 1 ホップ表示の API pytest + 手動確認。

---

## Workstream I4: 期待成果物レジャー（監査懸念 3・7 — 非ブロッキング）

### 現状評価
plan の done には completion evidence が必須（実装済み）で「未完を完了と偽る」経路は塞がれている。しかし **active なノードの裏で leaderboard だけが埋まり、diagnostics notebook が存在しない**状態は起こり得るし、それが「隠れた失敗」ではなく「見える修復対象」として表示されない。

### 実装指示
1. **プロトコル駆動の期待値**（推測ではなく、fixed-format な因果で生成する）:
   - `register_runs` ack 成功 → 該当 run 群に `model_diagnostics_notebook` の期待エントリ
   - `register_prediction_pipeline` ack 成功 → 対象 run に `pipeline_bundle` は充足済みとして記録
   - pilot scoring report 登録 → `validation_audit` の期待エントリ
   - research 系ノードが active → `research_findings` の期待エントリ
   期待エントリは `DeliverableExpectation`（id, project_id, kind, subject_ref, status: `open | fulfilled | waived`, created_from）としてDB化。**充足判定は対応する register 系 ack の成功のみ**（内容の質は判定しない）。Codex は operation `waive_deliverable`（rationale 必須）で明示的に不要宣言できる。
2. **表示**: Leaderboard 行に「診断ノートブック未提出」チップ、plan ノードに「期待成果物 n 件未提出」バッジ。クリックで何が期待されているかの中立説明。**ブロックしない**（run は表示され続け、plan 進行も止めない）。
3. **Codex への還流**: open のまま 30 分経過した期待エントリを inbox observation としてまとめて1通知（既存 envelope。連続通知は同一 kind+subject で 1 回のみ）。
4. **禁止**: 期待未充足を理由に plan commit・run 登録・セッション継続を拒否しない。数・質のゲート化をしない。

### 受け入れ基準
- [ ] register_runs → 期待エントリ生成 → register_notebook(model_diagnostics, 該当 run 参照) → fulfilled になる pytest。
- [ ] waive_deliverable の正常系/rationale 欠落エラー系 pytest。
- [ ] 未充足チップの表示（build + スクリーンショット）と inbox 通知の重複抑制 pytest。

---

## Workstream I5: Chat/Activity の反復・停滞の仕上げ（監査懸念 5）

### 実装指示
1. **通知の再発防止を横断検証**: モデル登録通知・resume 文言・attention の3系統について「同一内容が3ターン連続で Chat に現れない」ことを検証する pytest を追加（現行 dedupe 実装が仕様を満たすかをテストで固定する。満たさない場合のみ修正）。
2. **完了後の静穏**: `pause_main_session_after_completed_plan` 到達後、supervisor がターンを再開しないこと・progress nudge が停止すること・Activity が「入力待ち（次にできること: テストデータ投入 / 実測投入 / 指示）」を表示することを pytest + 手動で確認。pilot observation での wake は既存テストを維持。
3. **古い Activity 行の整理**: 終了済み upload/import ジョブのカードは最新5件に制限し、それ以前は Jobs（詳細タブ）のみに残す。削除はしない。
4. 文言監査: Activity/Chat の固定文言から実装語彙（worker、retry、session 等）を copy.ts レベルで洗い、ユーザー語彙に置換する（機械的な文言置換のみ。新しい説明文の生成はしない）。

### 受け入れ基準
- [ ] 3系統の反復抑制 pytest。
- [ ] 完了後静穏（ターン再開なし・nudge 停止・入力待ち表示）の pytest。
- [ ] Activity 上限と Jobs への退避の pytest + build。

---

## Workstream I6: ブラウザ実機 E2E と証拠等級の明示（監査懸念 10）

### 現状評価
0120 の証拠は「unit + API + 限定的なライブ検証」であり、ユーザーが見る UX（iframe、直接オープン、チップ、進捗表示）はブラウザ層の証拠が無い。実際、監査で確定した marimo 問題群はすべてブラウザ層でしか再現しない。

### 実装指示
1. **Playwright スモークの整備**: `apps/frontend/e2e/` に golden slice の自動ブラウザテストを作る:
   アップロード（primary 未指定）→ Full Auto ON → chat から notebook 直接オープン（iframe 内に marimo UI 要素が現れるまで）→ leaderboard 行のモデル説明表示 → pipeline ダウンロード応答 200 → 予測バッチ作成 → pilot scoring 表示。Codex 実行はフェイク runner（既存のダミーバイナリ機構）で決定的にする。CI 相当のコマンドを docs/dev.md に記録。
2. **証拠等級の宣言**: docs/evidence/0121_verification.md 以降、各主張に等級を明記する: `U`（unit）/ `A`（API smoke）/ `B`(browser)/ `L`（live Full Auto with real Codex）。0120 までの主要主張を遡って等級づけした一覧表を作る。
3. **ライブ調査ランの実施**: network 有効の実 Codex セッションを1回回し、出典つき research findings + リッチ report が登録される様子を等級 `L` として記録する（未実施のため現状 B 相当の主張しかない）。

### 受け入れ基準
- [ ] Playwright スモークがローカルで再現可能（コマンドと結果を evidence に記録、スクリーンショット保存）。
- [ ] 証拠等級表が存在し、`L` が pilot ループと research の両方に付く。

---

## Do not do（表面的修正の禁止）
- 静的 HTML notebook フォールバックの再導入（いかなる形でも）。
- ハーネスによる分析散文・notebook 叙述・レポート解釈の生成。
- 期待成果物レジャー（I4）のゲート化・数値しきい値化。充足判定は register 系 ack の成功のみ。
- 新しい自然言語/列名/統計ヒューリスティックの追加。新規エイリアスの追加。
- 新タブ・新サーフェスの追加。I3 は既存タブの中身の組み替えに限る。
- marimo 問題への「開けないときは画像を出す」等の隠蔽的回避。失敗は修復対象として見せる。
