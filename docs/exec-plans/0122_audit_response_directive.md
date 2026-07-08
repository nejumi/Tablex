# 0122: Audit Response Directive（0122 監査への回答と次期指示）

前提契約: [AGENTS.md](../../AGENTS.md) / [agent_interface_spec.md](../agent_interface_spec.md) / 0119 / 0120 / 0121。
本書は docs/evidence/0122_fable_audit_request.md への外部監査回答として確定した実装指示である。

**実施順: J1 → J2 → J3 → J4 → J8 → J7 → J5 → J6。**
J5（モデル多様性）と J6（LLM 特徴量拡張）は魅力的だが、**J1（評価契約ループ）が無い状態では比較不能な結果を増やすだけ**なので、必ず後にする。
各 Workstream 完了時に docs/evidence/0122_verification.md へ証拠等級（U/A/B/L）つきで記録する。

---

## Workstream J1: 評価契約ループ（監査 Focus 2 — 最優先）

### 確定した現状
- Codex が EvaluationSpec / SplitManifest を**提案する tool プロトコルが存在しない**（`tablex_evaluation_request` 系なし）。評価オブジェクトはレガシー UI エンドポイントからしか作られず、実プロジェクトで EvaluationSpec=0 / SplitManifest=0 のまま leaderboard に 3 run が並んだ。
- リーダーボードに **provisional（内部CV）と formal（承認済み評価）の区別表示が無い**。
- ユーザーが「stratified 5-fold で」「customer_id で group split」等を指定する自然言語→契約化の経路が無い。

### 目標の評価ヒエラルキー（UI にもこの語彙で表示する）
```
暫定（Codex 内部 CV; run 単位の自己申告 split 情報のみ）
  ↓ Codex が propose_evaluation で候補を提出
評価候補（EvaluationCandidate; ユーザー承認待ち or Full Auto 仮承認）
  ↓ 承認（明示 or intervention timeout で仮定として記録）
承認済み評価（EvaluationSpec + SplitManifest）
  ↓ 以後の run はこの split の下で登録され「正式」バッジ
正式比較（同一 SplitManifest 下の run 同士のみ順位比較を強調表示）
```

### 実装指示
1. **Codex 提案プロトコル**: `.tablex/requests/evaluation/`、`schema_version: "tablex_evaluation_request.v1"`:
   - operation `propose_evaluation`: payload = `{objective_metric: {name, direction}, secondary_metrics[], split_policy: {kind: "random|stratified|group|time|fixed_file|fold_column|rolling_forward", params: {...kind別の固定フィールド: group_column / time_column / n_folds / test_fraction / fold_column / validation_file_ref / horizon...}}, rationale, task_spec_ref, provisional_assumption}`。
   - operation `generate_split`: 承認済み spec に対する SplitManifest 生成依頼（生成自体は既存の harness 側 split 生成ロジックを worker Job で実行。乱数 seed 固定）。
   - 検証は fixed-format のみ（metric 名の正規化、列の実在、enum）。**split の良し悪しは判定しない。**
   - ack 成功で EvaluationCandidate を作成し、Full Auto 中は既存の intervention window（回答期限つき、無回答なら provisional 承認として記録）に乗せる。
2. **ユーザーの自然言語指示の経路**（Focus 9 と接続）: 「ROC-AUC で」「customer_id で group split」という Chat/Console 指示はキーワード処理**しない**。メインセッションへ配達し、Codex が現データを確認して `propose_evaluation` を提出する。Chat の返答は提案の具体的内容（メトリクス・split の実パラメータ）を報告する（J3 のペアリングで実現）。
3. **リーダーボードのラベリング**:
   - API 各エントリに `evaluation_grade: "formal" | "provisional"` を追加（判定は run.split_manifest_id が承認済み SplitManifest を指すか、という参照事実のみ）。
   - UI: provisional 行に「暫定（内部検証）」バッジ。formal と provisional の混在時はセクション分離または明確なバッジ列。Best score カードは formal 優先、無ければ「暫定ベスト」表記。
   - **過去 run の遡及再ラベルはしない**: 既存 provisional run を後から formal に付け替えない。承認後、Codex に「上位候補を承認済み split で再実行して再登録する」ことをターンプロンプト契約として求める（数値ゲートにはしない）。
4. **配置**: 評価設定の入口は Home の推奨アクション（評価未確定のとき）と Leaderboard 上部の状態行（「この表は暫定内部検証です。評価を確定する→」）。詳細タブの Evaluation は編集/履歴面として残す。
5. validation データと test データの区別を UI 語彙で固定: 「検証（モデル選択に使用）」「テスト/新規データ（予測対象。学習・選択に不使用）」。J4 の予測バッチ種別と揃える。

### 受け入れ基準
- [ ] propose_evaluation → candidate → 承認 → generate_split → SplitManifest の一連 pytest（group/time/fold_column/fixed_file を含む）。
- [ ] 無回答 timeout で仮承認として記録され Full Auto が継続する pytest。
- [ ] leaderboard の evaluation_grade 付与 pytest + provisional バッジの browser 証拠（B等級）。
- [ ] ライブ検証（L等級）: Chat で「customer_id の group split にして」→ 提案 → 承認 → 再実行 run が formal で並ぶまでを記録。

---

## Workstream J2: Raw を「Codex Console」にする（監査 Focus 9）

### 確定した現状
Raw の入力フォームは通常チャットと同じ送信経路で、ボタン文言は「AgentTaskContract 作成」のまま（[RawAgentStream.tsx:210-221](../../apps/frontend/src/components/RawAgentStream.tsx)）。「メインセッションに直接届く」経路としての区別・保証・表示が無い。Raw は事実上ログビューアであり、製品契約（Raw = 生きたメインセッション面）に未達。

### 実装指示
1. **名称と枠づけ**: Raw タブを「Codex Console」（ja: Codexコンソール）に改名。ヘッダに「これはメインの Full Auto セッションの生の記録と直接入力です。通常の質問は Chat へ」という一文。
2. **直接入力エンドポイント**: `POST /api/projects/{id}/agent-session/console-message`:
   - 動作: user transcript event 追記 + inbox envelope（kind=user_instruction, `channel: "console"`）+ progress/result update 要求。**補助コンポーザーを一切通さない。**
   - セッションが `completed`/入力待ちのときは wake する（pilot observation と同じ経路）。`stopped`（ユーザー電源OFF）は wake しない — 電源OFFはユーザーの明示停止であり console もこれを尊重する。メインセッションが存在しない場合、入力欄は disabled + 「Full Auto を開始すると使えます」。
   - 安全境界は既存と同一（秘匿情報は送らない旨の注意書きのみ。内容フィルタは実装しない）。
   - Codex の応答はまず transcript（Console）に現れ、chat_update 経由の人間向け要約は従来どおり Chat に出る。
3. **表示の分離**: Console の入力 UI は Chat と視覚的に別（等幅・コンパクト・「上級者向け」の位置づけ）。送信ボタン文言を「メインセッションへ送信」に修正。
4. **提供範囲**: Console 送信は Full Auto の main session のみ対象。補助コンポーザー・子ジョブへの直接送信は作らない。

### 受け入れ基準
- [ ] console-message が transcript event + inbox entry を生成し、completed セッションを wake する pytest。stopped を wake しない pytest。
- [ ] フェイク runner で「console 送信 → 次ターンのプロンプトに含まれる → 応答が transcript に現れる」E2E pytest。
- [ ] Console UI の browser 証拠（B等級）。

---

## Workstream J3: Chat を実行できるインターフェースにする（監査 Focus 9 の本丸）

### 確定した現状
`agent_chat_turn` ジョブは補助コンポーザー（一時ディレクトリの `codex exec`、保存済み状態の brief のみ、**検査・実行能力なし**）で返答を生成する（[worker/jobs.py:205-243](../../apps/backend/tabular_harness/worker/jobs.py)）。このため「暫定 split は具体的にどう切られたか調べて」への返答が「スクリプトを確認してください」になる — **非実行プロキシ問題**。ユーザー指示はメインセッション inbox に配達されているが、その結果と Chat 返答のペアリングが間接的すぎる。

### 実装指示
1. **返答ポリシーの転換**（キーワード分岐は使わない。判断はモデルに委ねる）:
   - Full Auto ON のとき、補助コンポーザーの brief に次の**行動契約**を追加する: 「保存済みの project state だけで完全に答えられる場合のみ最終回答を書け。artifact の中身・コード・データの検査、状態の変更、評価の設定が必要な場合は、最終回答を書かず `handoff_to_main_session: true` と、何を確認するかの1文を返せ。」レスポンス schema に `handoff_to_main_session` フィールドを追加（fixed-format）。
   - `handoff_to_main_session: true` のとき、Chat 表示は「メインセッションが確認しています…」の待機カードになり、chat job は既存の `waiting_for_agent` 経路でメインセッションの応答（chat_update または console 応答）を待って完結する。
2. **来歴ラベル**: すべての Chat アシスタント返答に人間語の provenance を表示する:
   - 「保存済みの記録から回答」（補助コンポーザー）
   - 「メインセッションが確認して回答」（chat_update / console 応答由来)
   - ラベルから該当 artifact / transcript 位置へ直接オープン。
3. **タイムアウトの事実陳述**: メインセッション応答が15分（設定可能）返らない場合、待機カードを「まだ確認中です。Activity で進行を見られます」に更新（虚偽の完了報告をしない）。
4. **評価指示の接続**: J1-2 のとおり、「ROC-AUC で」等の指示はこの handoff 経路でメインセッションに渡り、propose_evaluation として返る。Chat の完了報告は提案の実パラメータを含む。
5. **禁止**: 補助コンポーザーに検査・実行能力を持たせない（短絡的な「ちょっとだけファイルを読む」拡張は、二つ目の推論主体を育てる誤り。検査はすべてメインセッションの仕事）。

### 受け入れ基準
- [ ] handoff フィールドの schema と待機カード遷移の pytest（フェイクコンポーザーで decision を固定）。
- [ ] フェイク runner で「検査依頼 → handoff → メインセッション応答 → Chat に provenance 付きで表示」E2E pytest。
- [ ] provenance ラベルの browser 証拠。実プロジェクトで「split の実態を調べて」に実回答が返るライブ検証（L等級）。

---

## Workstream J4: テストデータ予測 UX（監査 Focus 4）

### 確定した現状
pilot deployment / predict / outcomes の API と Job は実装済みだが、入口が leaderboard から遠く、「モデルを選ぶ→ファイルを置く→予測を受け取る」という一本道の UX が無い。マルチテーブル入力の宣言は manifest の `history_requirements` のみで、関係データ（Home Credit 型）の必要テーブル宣言が弱い。

### 実装指示
1. **入口はリーダーボード行**: 各行（pipeline 登録済み）に「このモデルで予測」ボタン → パネル（drawer）を開く:
   - manifest 由来の**期待入力スキーマ表**（列・dtype・必須/任意、target 列は「含めない」注意）
   - 必要テーブル一覧（下記 2 の宣言から）と、それぞれの D&D アップロード枠
   - アップロード後の**検証レポート**(列の過不足・dtype 不一致・行数。fixed-format 検証のみ)
   - 実行ボタン → 既存 predict Job → 完了で predictions.csv ダウンロード + prediction batch として登録（lineage: model/pipeline/入力）
   - 失敗時: 検証エラーをユーザーに表示し、同内容を inbox envelope で Codex にも返す（パイプライン側の契約不備の可能性があるため）
2. **manifest の関係データ拡張**（`pipeline_manifest.v1` に後方互換で追加）: `input_contract.required_tables: [{name, role: "primary|supporting|history", columns[], join_keys[], as_of_column|null, history_window|null, optional: bool}]`。predict.py は宣言テーブルのファイルパス群を `--input-dir` で受け取る形式を標準にする（単一テーブルは従来の `--input` も許容）。
3. **バッチ種別**: prediction batch に `batch_kind: "validation | external_test | pilot | benchmark_submission"` を必須化し、一覧・lineage・pilot 接続（pilot は従来どおり outcome ingestion へ）で区別表示。
4. **配置**: 新タブは作らない。Leaderboard 内ドロワー + Data タブの「予測バッチ」一覧（既存 related outputs の枠を再利用）。

### 受け入れ基準
- [ ] required_tables 宣言つきパイプラインの登録・検証・予測の pytest（マルチテーブル fixture）。
- [ ] 列不足/型不一致の検証レポートがユーザー表示 + Codex inbox の両方に届く pytest。
- [ ] リーダーボード行 →D&D→ 予測ダウンロードの browser 証拠（B等級）+ Home Credit 級でのライブ検証（L等級）。

---

## Workstream J8: native marimo 速度の実測と最適化（監査 Focus 3）

### 実装指示
1. **プロファイル計測を先に行う**: 代表 notebook 3 種（データ理解・診断・レポート）で cold / prewarmed / reopen の3条件について、(a) marimo サーバ起動、(b) notebook import（依存 import 含む）、(c) データ読み込み、(d) フロント資産ロード、の所要時間を計測し docs/evidence/0122_marimo_profile.md に記録する。**計測前に最適化しない。**
2. 計測結果に応じて以下の優先実装（見込み順）:
   - **authoring 契約の強化**（プロンプト/notebook-quality Skill）: トップレベルで全データを読まない。`.tablex/cache/dataset_samples` を既定に使い、全件処理はボタン起動セルにする。重い import は使用セル内に置く。
   - **prewarm の適用範囲拡大**: 登録直後だけでなく、Chat/Leaderboard/Plan で notebook リンクが**表示された時点**で該当 notebook を予熱（上限内・LRU）。プロジェクトを開いた時点で最新のデータ理解 notebook を予熱。
   - **warm プール維持**: `marimo_max_sessions` の範囲でセッションを TTL まで維持し、reopen を常に warm にする（既存実装の確認と TTL 調整）。
   - フロント資産の再取得（iframe 再ロード）を避けるため、タブ切替で iframe を unmount しない（display 切替にする）。
3. 静的 HTML フォールバックは実装しない（恒久禁止)。

### 受け入れ基準
- [ ] プロファイル記録が存在し、ボトルネック上位2つに対策が紐づいている。
- [ ] 対策後の同一計測で cold→open が体感目標（プロジェクト内の予熱済み notebook で 3 秒以内、cold で 15 秒以内。未達なら理由と次の一手を記録）。

---

## Workstream J7: アセットの正典リスト化（監査 Focus 1・7）

### 実装指示
1. Assets タブを**正典インベントリ**として完成させる: 全行に「人間タイトル / カテゴリタグ（0121 の静的辞書）/ 作成時刻 / 由来（plan ノード・run・dataset へのリンク）/ 主アクション（開く・ダウンロード）」を必ず表示。internal `asset_type` は詳細展開のみ。時系列ソート既定・タイプ/カテゴリ/plan ノードのフィルタ・名前検索。
2. Insights/Reports の一覧機能を Assets のフィルタプリセット（「レポートだけ見る」）に統合し、重複サーフェスを畳む（タブ自体は詳細トグル内に残してよいが中身は同一コンポーネント）。
3. 「supporting records」の既定非表示をやめ、「その他」カテゴリとして折りたたみ表示（隠さない）。
4. lineage は 0121 の1ホップパネルを維持（ブラウジンググラフ化はしない）。
5. レポート行は Markdown レンダリング（図インライン）で開けること（J系既存実装の確認と欠落補修）。JSON を「レポート」として見せない — JSON は「記録」カテゴリに置き、人間向けはレポート/notebook のみ。

### 受け入れ基準
- [ ] 「データ理解 notebook はどこ」「最終レポートはどこ」「pipeline はどこ」が Assets 検索 1 回で見つかる browser 証拠。
- [ ] 全行のメタデータ完備を保証する API pytest。

---

## Workstream J5: モデル多様性を Skill 装備として実現する（監査 Focus 5）

### 原則（2026-07-09 のユーザー決定で確定）
LightGBM 偏重の原因はハーネスの強制ではなく**装備の欠如**である（プロンプトにモデル指定は無い。Skill が EDA と notebook 品質の2つしか無い）。解は**本体実装ではなく Skill**であり、ハーネス側の変更は最小限の事実提供に限る。

### 実装指示
1. **Skill 追加**: `skills/tablex-modeling-strategy/SKILL.md` — 「探索方針の職人知識」: 線形/ロジスティックのベースライン床、GBM 系、RF/ET、calibration、stacking/blending の使いどころ、**TabPFN/TabICL 系 foundation model の適用条件**（行数・列数・クラス数の目安と、合う場合の優先試行）、時系列モデル、target 不在時の clustering/anomaly。**「必ずこの順で試せ」とは書かない**（判断材料として書く）。
2. **ライブラリ調達も Skill の知識で解決する**（本体依存は追加しない）: 追加ライブラリ（tabpfn 等）が必要なとき、(a) 実験はワークスペース内に Codex 自身が venv を作って導入する、(b) 提出する pipeline は `requirements.txt` に宣言すれば既存の隔離スモーク実行が自動で解決する — この2経路を Skill に明記する。pyproject への追加や approval 付きインストール Job は**作らない**。
3. **runtime facts の拡充のみ本体で行う**: context.json に既存 Python 環境のインストール済み主要ライブラリと GPU 有無を事実として記載する（Codex が「今すぐ使えるか / venv が要るか」を事実で判断できるように）。
4. **アンサンブルは既存基盤で表現可能なことを確認する**: ExperimentRun（`model_family: "ensemble"`、構成 run ids を params に）と pipeline bundle（model/ 配下に複数サブモデル + predict.py が合成）が現 manifest で通ることをテストで固定し、PROTOCOL.md に例を1つ追加する。新しい登録種は作らない。
5. **リーダーボード表示**: manifest/params の任意フィールド `model_family` を表示に追加（自己申告値。検証しない）。
6. **禁止**: harness 側の「モデルファミリー網羅チェック」「多様性スコア」等の数値ゲート、モデル選択ロジックの本体実装。

### 受け入れ基準
- [ ] modeling-strategy Skill が新規プロジェクトに既定装備され context に載る pytest。
- [ ] runtime facts（ライブラリ一覧・GPU 有無）の記載 pytest。
- [ ] tabpfn を requirements.txt に宣言したダミー pipeline が既存スモーク実行で解決される pytest（ネットワーク不可の CI では skip 可）。
- [ ] ensemble pipeline の登録→予測 E2E pytest（既存 manifest のまま通ること）。
- [ ] ライブ検証（L等級）: 適合形状のデータセットで Codex が TabPFN ないし ensemble を自発的に試行し leaderboard に登録した記録。

---

## Workstream J6: LLM 特徴量拡張 Skill（監査 Focus 6 — 最後）

### 原則（2026-07-09 のユーザー決定で確定）
LLM 拡張は**本体実装ではなく Skill**。新エンティティ・新リクエスト種・ハーネス所有の生成実行系は**作らない**。既存の境界（ターンプロンプトの「validation/test target を特徴量生成プロンプトに入れない」hard constraint、SplitManifest 遵守、pipeline スモーク実行による再現性検証）が安全枠として既に機能する。

### 実装指示
1. **Skill 追加**: `skills/tablex-llm-feature-augmentation/SKILL.md` — 職人知識として記載:
   - 行テキスト/行全体を LLM に渡して世界知識由来の特徴量や正規化テキストを横持ちで足す設計パターンと、効果が出やすい/出にくいデータの見分け方。
   - **リーク規律**: プロンプトに target 値・validation/test 行の target を絶対に含めない。fold 安全な生成（train fold の統計に依存する要素は fold 内で閉じる）。
   - **決定論とキャッシュ**: `(model, prompt_hash, row_hash)` をキーにワークスペース内 parquet/JSON でキャッシュし、再実行を冪等にするパターン。
   - **来歴**: 生成特徴 artifact の metadata にプロンプトファイルパス・モデル名・キャッシュキー方式を記録する規約（既存 artifact metadata の慣習であり新 schema ではない）。
   - **pipeline 同梱**: 拡張を使うモデルを提出するときは、プロンプトファイルと生成コードを bundle に含め、predict.py が同一経路で新規データにも拡張を適用すること（さもないと既存のスモーク実行/出力契約検証で落ちる、と明記）。
   - **コスト意識**: 対象行数×プロンプト長の概算を実行前に chat_update で報告する習慣。
2. **本体変更は原則ゼロ**。唯一の例外として、既存ターンプロンプトの hard constraint（validation/test target の混入禁止）が feature 生成の文脈でも読めることを確認し、不足なら1行の文言調整のみ行う。
3. **判断は Codex**: 拡張を試すか・どの列で・どんなプロンプトかは Codex の判断。効果検証は通常の run 比較（J1 の formal 評価下）として Codex が行う。

### 受け入れ基準
- [ ] Skill がライブラリに登録され、装備時に context へ載る pytest。
- [ ] Skill の記載内容がリーク規律・キャッシュ・pipeline 同梱・来歴規約を含むことのレビュー確認。
- [ ] ライブ検証（L等級）: テキスト列を持つデータセットで Codex が拡張を試行し、生成特徴つき run と pipeline（拡張同梱）が登録された記録。効果の有無自体は問わない。

---

## Do not do
- 静的 HTML notebook フォールバック（恒久禁止）。
- 補助コンポーザーへの検査・実行能力の付与（推論主体は main session の一つだけ）。
- 自然言語のキーワード分岐（評価指示・handoff 判定を含む — 判断は常にモデル側）。
- provisional run の遡及 formal 化、モデル多様性・調査量・拡張効果の数値ゲート。
- 新タブの追加。J4/J7 は既存サーフェス内の再構成で行う。
- J5/J6 を J1〜J4 より先に着手すること。
- J5/J6 のためにハーネス本体へ新エンティティ・新リクエスト種・モデル選択ロジック・生成実行系を追加すること（両者は Skill + 既存プロトコルで実現する。2026-07-09 ユーザー決定）。
