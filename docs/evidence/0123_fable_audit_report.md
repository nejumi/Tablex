# 0123 Fable Audit Report: Prediction, Pilot, And Operations UX

Date: 2026-07-09
Auditor: Claude Fable 5 (external audit)
Request: `docs/evidence/0123_fable_audit_request.md`（本ファイルと同日にリポジトリへ追加されるリクエスト文書。未コミットの場合はチャット履歴を正とする）

対象コード検証済み: `apps/backend/tabular_harness/services/agent_requests/pipelines.py`, `services/prediction_input_feedback.py`, `worker/jobs.py` (`run_prediction_pipeline_handler`, `score_pilot_outcomes_handler`), `api/routes.py` (`/prediction-inputs`, `/pilot-deployments`, `prediction_input_validation_report`), `services/agent_workspace.py`（PROTOCOL 生成部）, `services/project_guidance.py` (`_recommended_focus`), `apps/frontend/src/components/LeaderboardTab.tsx`（予測ドロワーとパイロット表）。

本レポートは二部構成である。**Part 1（戦略編）**が「開発 → テスト予測 → 仮運用 → 本番運用」を貫く製品の統一モデルと段階計画を描き、**Part 2（戦術編）**が現行コードの深刻度順の指摘と受け入れ基準を示す。個別修正は Part 2 だけでも実行できるが、Part 2 の各項目は Part 1 の絵に整合するように設計してある。

---

# Part 1: 大きな絵 — 運用までを貫く統一モデル（戦略編）

## 1.1 中心テーゼ: 「あなたのモデルを作ったエージェントが、そのモデルと一緒に運用に残る」

旧世代 AutoML（DataRobot 世代）の構造的欠陥は、**デプロイを「別の製品」にしたこと**である。開発は data scientist の画面、運用は MLOps engineer の画面。モデルは開発ループから切り離されて「監視対象の静的資産」になり、drift ダッシュボードの信号が赤くなっても、それを解釈して次の手を打つ主体はもうそこにいない。だから現実の drift 対応は「数ヶ月後に人間が気づいて再学習プロジェクトを立てる」になった。

Tablex が生成 AI 時代に取れる最大の構造的優位はここにある:

> **モデルのライフサイクル全体が、一つの継続する説明責任ある会話（continuing Codex session）である。**

- 開発期にデータを理解し、評価を設計し、モデルを作ったのと**同じセッション文脈**が、テスト予測の失敗を修復し、仮運用のスコアを監査し、drift を分解し、再学習を提案する。
- Tablex はこの会話に「時間」を供給する: バッチ、as_of、遅れて届く実測値、バージョンの世代交代。
- ユーザーの心的モデルは一文で足りる: **「モデルを育てる → 現実で試す → 現実から学ぶ」の円環を、同じ画面・同じエージェント・同じ資産台帳で回す。**

これはペルソナを分割しないという製品判断でもある。Tablex は「開発者向け画面」と「運用者向け画面」を作らない。フェーズによって変わるのは流れ込むデータと人間の役割だけであり、UI の骨格（Home が語り、Leaderboard が育て、ドロワーが試し、監査が学ぶ）は不変とする。

## 1.2 三つのフェーズ、一つの不変構造

| | A. 開発 | B. 仮運用（Pilot） | C. 本番運用（Handoff/Operate） |
|---|---|---|---|
| 流れ込むデータ | 学習データ | 新規入力＋遅延実測値 | 定期バッチ＋実測値＋人間の承認 |
| ループの単位 | 実験（ExperimentRun） | 観測サイクル（予測→実測→スコア→監査） | 世話サイクル（バージョン選択・昇格・rollback） |
| 証拠 | Leaderboard / formal 評価 | scoring report / validation audit | 運用ログ / 世代交代の判断記録 |
| 人間の役割 | 目的を与え、評価を承認する | 現実（ファイル・実測値）を供給し、監査を読む | 昇格・rollback・書き込み境界を承認する |
| Codex の役割 | 分析・モデリング・報告 | 失敗修復・ギャップ分解・次イテレーション | 再学習提案・チャレンジャー提案・drift 解釈 |
| ハーネスの固定責務 | 契約検証・lineage・split 整合 | バッチ台帳・時刻整合・固定メトリクス計算 | スケジュール実行・バージョンポインタ・承認ゲート・書き込み境界 |

不変なのは分業である: **判断はすべて Codex、固定検証と記録と実行はすべて Tablex、物語は Home。** フェーズが進むほど「ハーネスが守る安全境界」は増える（本番書き込みが最たるもの）が、「ハーネスが行う判断」は増えない。ここを守れば旧 AutoML には戻らない。

## 1.3 資産モデルの核心: 生き残るのは run ではなく「運用コンテキスト」

開発から運用へ持ち越されるものは何か。run でも model バイナリでもなく、次の束である:

```
運用コンテキスト（将来の ModelService の種。現 PilotDeployment がその原型）
├─ パイプラインバージョン系譜（v1 → 修復 v2 → 改良 v3、各遷移に理由: 修復/改良/監査指摘）
├─ 評価契約（EvaluationSpec + SplitManifest への固定参照 — スコアリングの物差し）
├─ 入力契約（manifest: テーブル・キー・as_of・horizon・forbidden columns）
├─ バッチ台帳（予測バッチ・実測バッチ、すべて as_of つき、(service, version) でキー付け）
└─ 判断記録（scoring report → validation audit → 昇格/修復/再学習の決定）
```

重要な設計原則が三つ:

1. **「いまこのサービスはどのバージョンで動いていて、誰がいつなぜ切り替えたか」に常に答えられること。** これが rollback・バージョン選択・監査可能性のすべての基盤であり、仮運用の段階から成立させておくべき事実である（新エンティティは不要 — 現 PilotDeployment＋lineage＋artifact バージョンで表現できる。Part 2 S3 の `superseded_by` はこの種）。
2. **バッチは (運用コンテキスト, パイプラインバージョン, as_of) でキー付けする。** これだけで champion/challenger（同一バッチを新旧バージョンで影実行して固定 join で比較）が、旧 MLOps が重いインフラで実現していたものを、artifact lineage のほぼ無料の副産物として手に入る。生成 AI 的な使い方はその先で、Codex が「新しいアンサンブルを challenger として同じバッチに流しては」と自分から提案できる。
3. **実測値（outcome）は製品のフライホイールである。** 旧 AutoML が最後まで閉じられなかったループがこれだ。実測値は遅れて届き、部分的で、訂正される。だから outcome はイベントではなく**時間軸を持つ台帳**として扱う: 累積スコアと窓別スコアを固定計算で常に再構成でき、Codex の監査は「どの窓で何が起きたか」を材料にできる。時間の意味論（as_of、遅延、累積再計算）を仮運用の今のうちに正しく敷くこと — 後のすべてがこれを継承する。

## 1.4 再学習ループ: 評価整合性を壊さずに円環を閉じる

実測値が溜まれば「新しい学習データ」になる。ここで旧 AutoML は「ワンクリック再学習」という嘘（同じ split で数字だけ更新され、比較可能性が静かに壊れる）を売った。Tablex の正しい円環はこうなる:

1. 実測値バッチが閾値ではなく **Codex の判断**で「再学習に足る」と評価される（監査レポートの next_iteration_focus として現れる）。
2. Codex が **時間前進型の評価拡張**を `propose_evaluation` で提出する（既存 J1 プロトコルがそのまま使える — 新旧モデルを同じ凍結窓で比較する split）。
3. 再学習は**同じプロジェクトの新しい run** として登録され、formal 比較で旧バージョンと並ぶ。
4. 勝てば新パイプラインバージョンとして登録され、運用コンテキストの昇格は**人間の承認ゲート**（Full Auto の intervention window と同じ形式: 期限つき、無応答なら記録して継続 — ただし本番書き込みが絡む場合のみ真のハードゲート）を通る。

つまり**再学習に新しい仕組みはほぼ要らない**。J1（評価契約）・J4（予測）・Pilot（実測値）・修復ループ（バージョン系譜）が正しく敷かれていれば、再学習はそれらの合成として自然に現れる。これが「大きな絵を先に描く」ことの実利であり、0122 で J1 を最優先にした判断は運用フェーズから見ても正しかった。

## 1.5 本番運用のあるべき姿と、Tablex がなるべきでないもの

正直な意見を述べる。**Tablex は serving platform になるべきではない。** リアルタイム推論エンドポイント、K8s、feature store、オートスケール — この領域は資本集約的で、既存プレイヤーが強く、Tablex の優位（継続する推論主体）が効かない。あるべき境界は:

- **Tablex が本番でやること**: バッチスコアリングの定期実行（パイプラインランナーは今と同一物）、バージョン管理と承認つき昇格/rollback、実測値取り込みと監査ループ、Codex による運用の世話。
- **Tablex が「本番引き渡し（Production handoff）」として外に出すこと**: パイプラインバンドル＋運用契約（manifest・評価契約・selftest）を顧客インフラへ引き渡す。バンドルが自己完結（requirements・predict.py・selftest 同梱）である現設計は、実はこの引き渡し可能性をすでに担保している。
- **予測が Tablex の外に出る唯一の経路は、ハーネス所有コードによる明示的・人間承認済みのエクスポートである。** Codex のコードが本番資格情報や書き込み先に触れる経路は永遠に作らない。これが運用フェーズで唯一増える「真のハードゲート」であり、AGENTS.md の既存原則の自然な延長。

語彙は既定路線を確定する: 「テスト予測 → 仮運用検証 → 本番引き渡し」。「デプロイ」は使わない。ローカルのバッチスコアリングを「デプロイ済み」と呼んだ瞬間、ユーザーの期待と製品の実態がずれ、その差を埋めるために作らなくてよいものを作らされる。

## 1.6 監視は「ダッシュボード」ではなく「定期監査を書くエージェント」

旧 AutoML の drift 監視は、固定統計量＋赤黄緑の閾値＋アラートである。これはハーネス側の判断そのものであり、Tablex では禁止パターンに当たる。生成 AI 時代の等価物は:

- Tablex: バッチ・実測値・スコアの**事実の時系列**を保持し、定期またはイベント（新実測値到着）で main session に observation を届ける（wake ポリシーは Part 2 S6）。
- Codex: 事実を読み、**監査レポートを書く**。「PSI が 0.3 を超えた」ではなく「直近 2 窓で若年層セグメントの申込構成が変わり、モデル v2 の誤差がそこに集中している。特徴量 X の再設計か、セグメント別再校正を提案する」— これが drift 対応の完成形であり、既存の validation_scheme_audit 契約（component_enum に temporal_drift / covariate_shift / target_shift が既にある）はこの絵を先取りしている。
- 人間: 監査を読み、Home の Next Decision カードで次を選ぶ。

ハーネスが持ってよいのは「新しい実測値が n 件届いた」「前回監査から m 日経過」という**トリガーの事実**までであり、良し悪しの閾値判定ではない。

## 1.7 段階計画: now / next / later

**Now（0123 サイクル = Part 2 の K1〜K6）**
- 検証パリティ（selftest・--input-dir・PROTOCOL 記載）、失敗状態の可視化と修復系譜、batch_kind 貫通、パイロット一画面 UX、Home 運用ナラティブ、wake ポリシー明文化。
- ここまでで「テスト予測と仮運用が、人間一人で一画面で回り、失敗が必ず Codex の修復会話に落ちる」が完成する。

**Next（仮運用が本物になる段階）**
- 運用コンテキストビュー: 現行バージョン・世代交代履歴と理由・(service, version) キーのバッチ台帳。Leaderboard 内のモデル詳細（master-detail 化。新タブではない）。
- 時系列スコアリング: 累積＋窓別の固定計算、パイロット指標の時系列チャート（visualization_spec の既存枠で可能）。
- 影実行（champion/challenger）: 同一バッチへの複数バージョン実行と固定 join 比較。
- 再学習ループの L 等級実証: 実測値 → 評価拡張提案 → formal 比較 → 承認つき昇格、を実プロジェクトで一周。
- 定期バッチ: スケジュールを approval つき Job ポリシーとして実装（cron 基盤の新設はまだしない。バッチ metadata に source: manual/scheduled/api を記録する形から入る）。

**Later（本番引き渡し。明示要求があってから）**
- ModelService の正式エンティティ化と承認ゲート（昇格・rollback・エクスポート）。
- ハーネス所有コネクタによる承認済みエクスポート（資格情報は runner に渡さない境界を維持）。
- 通知（人間へのアラートは「監査が出た」「承認待ちがある」という事実通知のみ）。
- 作らないもの: リアルタイム serving、K8s、feature store、閾値式 drift ダッシュボード、運用者向け別画面。

この段階計画の判定基準はただ一つ: **「その機能は判断をハーネスに移すか？」** 移すなら作らない。事実・実行・記録・境界なら作ってよい。

## 1.8 アドバイスと感想（率直に）

1. **「これで良いのか感」の正体は、修正の質ではなく、照らす絵が無かったことだと思う。** bc29dfe も d10b2bc も個々には正しい修正だ。しかし「この修正は運用ライフサイクルのどこを埋めるものか」を判定する基準文書が無いまま積むと、正しい修正の集合が正しい製品に収束する保証がない。本レポート Part 1 を土台に、`docs/agent_interface_spec.md` へ「Operations」節を追加して恒久の判定基準にすることを勧める（節の要件は Part 2 のドキュメント更新指示に含めた）。以後の手元修正は Codex に任せてよく、レビュー観点は「Operations 節に整合するか」の一点で足りる。
2. **0121→0122 の統治スタイル（小さく順序づけられた directive＋受け入れ基準＋Do not do リスト）は非常に良く機能している。** 外部監査 → 人間が directive に蒸留 → Codex が実装 → 証拠等級つき検証、というこのプロジェクト自体のループは、Tablex が顧客に売ろうとしている働き方の実演になっている。このメタ構造は保つ価値がある。失敗モードがあるとすれば「一つの directive の肥大化」なので、0123 も Part 2 の K1〜K6 程度の粒度で切ることを勧める。
3. **Leaderboard タブの責務集中は「next」で手当てが要る。** 順位表＋予測ドロワー＋パイロット表＋証拠プレビューが縦積みになっており、運用コンテキストビューまで載せると破綻する。新タブ禁止の原則は正しいが、タブ内の master-detail 再構成（行を選ぶと右/下がそのモデルの詳細＝診断・予測・パイロット・系譜になる）は 0124 あたりで検討すべき。
4. **時間の意味論に最初に投資せよ。** as_of、遅延実測、累積再計算、時間前進 split。仮運用で時間を曖昧にすると、後の本番・再学習・時系列タスクのすべてが曖昧さを継承する。逆にここが固ければ、時系列予測（horizon・future covariates）も運用も同じ土台に乗る。
5. **J5/J6（モデル多様性・LLM 特徴量）を Skill にした判断は、運用フェーズでこそ効いてくる。** パイロットのギャップ分解で「モデルファミリーが不適」「特徴が陳腐化」と判断したとき、Codex が手持ちの装備で次の手を打てる。装備と判断の分離という原則が、開発期より運用期に大きな配当を生む構図であり、原設計の勝ちだと思う。
6. **最後に肯定的な感想を一つ。** 「Full Auto は完了後も同じセッションであり、observation で目を覚ます」という 0120 以来の決定は、当時はチャット UX の話に見えたはずだが、実際には運用フェーズ全体の背骨だった。pilot observation・修復 observation・将来の drift 監査はすべてこの一つの仕組みの上に乗る。この種の「後から効く正しさ」が既にいくつも埋まっているのがこのコードベースの良さで、大きな絵は白紙に描くのではなく、すでに半分実装されているものを言語化する作業に近かった。

---

# Part 2: 現行実装の監査と実装指示（戦術編）

## 総評（忌憚のない意見）

方向性は正しい。0122 J1〜J8 の実装は製品哲学（Codex が推論し、Tablex は固定契約を検証する）を忠実に守っており、`lgbm_relational_aggregates_v1` の失敗を「巨大トレースバックの放置」ではなく「Codex への修復 observation」に変えた `bc29dfe` は正しい進化だった。

その上で、今回の中心課題への答えを先に言う:

1. **今回の予測失敗は UX の問題ではなく、登録時検証と実行時経路の非対称の問題である。** スモークが「manifest の主張」を検証し「predict.py の実際の要求」を検証していない。UI をいくら磨いてもここが直らない限り再発する。最優先は検証パリティ（K1）であり、ドロワーの装飾ではない。
2. **DataRobot との差別化点はドロワーの見た目ではなく、失敗の先にある回復ループである。** DataRobot は失敗するとスタックトレースで止まる。Tablex は失敗が「Codex との修復会話」に落ちる。ここに投資すべきで、実装の大半はすでにある。足りないのは (a) 失敗状態の可視化（Leaderboard/Home）、(b) 修復完了までの物語の接続。
3. **旧 AutoML 化の兆候は 1 箇所だけ検出した。** `summarize_prediction_pipeline_runtime_failure` の stderr キーワード分岐は、自ら禁止した「自然言語ヒューリスティックによる解釈」の変種である。事実（exit code / stderr tail）はハーネスが述べ、解釈は Codex に返すべき。早期に除去することを勧める。
4. **パイロットは API 完備・UI 不在。** PilotDeployment を作る UI もアウトカムを投入する UI も存在しない。curl でしか回せないループは製品には存在しないのと同じ。ただし解はウィザードではなく、既存ドロワーへの「バッチ種別」1 選択と、パイロット行への「実測値を追加」1 アクションで足りる。
5. **Home は modeling 完了後の物語を持っていない。** `_recommended_focus` の梯子は「決定レポートを読む」で終わる。予測可能・修復待ち・実測値待ち・監査待ちという運用状態が Home に存在しない。これが「タブを探し回る」体験の根本原因。

## 深刻度順の指摘

### S1（最重要・correctness）: スモーク検証が実行時経路と非対称

事実:

- `smoke_validate_prediction_pipeline`（`pipelines.py:764`）は常に `predict.py --input <1行CSV>` を実行する。manifest が `required_tables` を宣言していても `--input-dir` でのスモークは行われない。実行時（`run_prediction_pipeline_handler`）は `input_artifact_ids_by_table` があれば `--input-dir` を使う。**登録時に通った経路と、ユーザーが実際に使う経路が別物。**
- スモーク入力行は manifest 宣言列のみに射影される。manifest が間違っていれば（SK_ID_CURR しか宣言していなければ）、間違った契約が検証されて green になる。
- `source_data_workspace_path` からの実データ 1 行は**学習データの先頭行**であり、外部テスト行との差（未知 ID、未知カテゴリ値、target 列の不在）を再現しない。
- さらに: **PROTOCOL/ワークスペース文書に `required_tables` と `--input-dir` の記載が一切ない**（`agent_workspace.py` の pipeline_tool_requests 例は `inference_format` と `history_requirements` のみ）。ランタイムとバリデータが対応済みの機能を、Codex は知る手段がない。マルチテーブル契約が書かれないのは Codex の怠慢ではなく契約文書の欠落。

指示（K1）:

1. **セルフテスト同梱を契約にする**: パイプラインディレクトリに `selftest/input/` を要求する。`required_tables` 宣言があるパイプラインでは必須（テーブルごとに 1 ファイル、ファイル名はテーブル名）。単一テーブルでは強く推奨（無ければ従来の合成 1 行にフォールバックし、`input_source: "synthetic_contract_values"` を弱い保証としてドロワーに表示する）。
2. **fixtures の中身は Codex が作る**（判断はモデル側）: 学習に使っていない実分布の少数行（3〜50 行）、target 列を含まない、カテゴリ/文字列列は実値を含む — これは Skill/PROTOCOL の指導として書き、ハーネスは固定検証のみ行う（ファイル実在、列が manifest と一致、`forbidden_columns` の不在、行数 >= 1）。
3. **スモークは実行時と完全に同じ形で起動する**: `required_tables` があれば `--input-dir`＋manifest.json、なければ `--input`。呼び出しコードを実行時ハンドラと共有関数にする。
4. PROTOCOL.md / pipeline_tool_requests の example に `required_tables`・`--input-dir`・`selftest/` を明記する。

受け入れ基準:

- [ ] required_tables 宣言つきパイプラインが selftest 無しでは登録拒否される pytest（エラーは修復手順つき fixed-format issue）。
- [ ] selftest つきマルチテーブル パイプラインの登録スモークが `--input-dir` で走る pytest（実行時ハンドラと同一関数を通ることをアサート）。
- [ ] 「manifest は SK_ID_CURR のみ・predict.py は全列要求」という再現 fixture が登録時に失敗する pytest（今回の事故の回帰テスト）。
- [ ] PROTOCOL 文書に required_tables / --input-dir / selftest 契約が載る pytest（文書生成のスナップショット検証）。

### S2（高・anti-pattern）: stderr キーワード分岐によるハーネス製の解釈

事実: `summarize_prediction_pipeline_runtime_failure`（`prediction_input_feedback.py:96`）は `"pandas dtypes must be int, float or bool"` や `"No such file or directory"` という文字列に反応して解釈文（「pipeline 側前処理が必要な列: …」「必要なファイルが見つからない」）を生成する。stderr は固定フォーマットではない。ライブラリのバージョンで文言は変わり、`No such file` 分岐はユーザー入力起因の失敗をバンドル起因と誤ラベルしうる。AGENTS.md の「固定フォーマット以外にルール/正規表現を使わない」「ハーネスが分析的散文を書かない」に反する。

指示（K2 の一部）:

1. 2 つのパターン分岐を削除する。ハーネスが述べてよいのは事実のみ: 「予測パイプラインの実行が失敗しました（exit code N）」＋ stderr tail ＋ 使用した入力の ID ＋「Codex に修復 observation を送信済み」。
2. 人間向けの**原因説明**は Codex 側から返す: inbox observation を受けた Codex が chat_update / 修復レポートで説明する（既存経路で可能。ターンプロンプトの observation 契約に「ユーザー向けの原因説明を chat_update に含める」を 1 行追加）。

受け入れ基準:

- [ ] summarize 関数からパターン分岐が消え、fixed facts のみになる pytest。
- [ ] フェイク runner で「予測失敗 → observation → Codex が chat_update で原因説明」の E2E pytest。

### S3（高・UX）: パイプラインの実行可否状態が Leaderboard/Home に存在しない

事実: 予測実行が失敗しても Leaderboard 行は何も変わらず「このモデルで予測」がそのまま出る。修復版が登録されると `run.params["pipeline_artifact_id"]` が上書きされ lineage は残るが、「修復が必要 / 修復済み / 実行可」の区別を人間が見る場所がない。同一失敗の重複 observation を抑止するキーも予測実行には無い（pilot request 失敗には `pilot_request_failure_attention_key` が既にあるのと非対称）。

指示（K2）:

1. Leaderboard entry に fixed-fact フィールドを追加: `pipeline_runtime: {last_run_status: "never_run|succeeded|failed", last_failed_job_id, last_failure_at, repair_observation_delivered: bool, superseded_by_artifact_id|null}`。判定は Job レコードと artifact バージョン参照のみ（意味推論なし）。
2. UI バッジ: 「実行可」「直近の実行が失敗（Codex に修復依頼済み）」「新バージョンあり」。ドロワーを開いた時、失敗状態なら先頭に事実バナー: **「このパイプラインは直近の実行で失敗しました。アップロードしたファイルの問題とは限りません。修復は Codex に依頼済みです。」**（ユーザー過失を示唆しない文言はリクエスト Focus 2 の要求どおり）。
3. 重複失敗の dedup: `(pipeline_artifact_id, exit_code, stderr_tail先頭列のhash)` を attention key とし、同一キーは observation を再送せずカウンタ更新。
4. `batch_kind` を prediction_batch へ貫通させる（現状 `prediction_input` にのみ保存され、`run_prediction_pipeline_handler` の batch metadata に無い。0122 J4 の「必須化」が未完）。enum は `validation|external_test|pilot|benchmark_submission` を維持し、`production` は追加しない。

受け入れ基準:

- [ ] pipeline_runtime が leaderboard API に載る pytest（失敗 Job → failed、修復版登録 → superseded 遷移）。
- [ ] 同一失敗 2 回で inbox エントリが 1 件のままの pytest。
- [ ] batch_kind が prediction_batch metadata と Assets 表示に貫通する pytest ＋ browser 証拠。
- [ ] 失敗バナーの browser 証拠（B等級）。

### S4（高・UX）: パイロットが UI から開始できない

事実: `POST /pilot-deployments` と `/outcomes` は実装済みだが、フロントに作成ボタンもアウトカム アップロード UI も無い。Leaderboard 末尾のパイロット表は読み取り専用。

指示（K4）— ウィザードにしない一画面設計:

1. **開始は予測ドロワーの 1 選択**: ドロワーに「この予測の扱い」セレクタを置く — 「テスト予測（既定）」「仮運用検証（後で実測値を照合する）」「ベンチマーク提出」。仮運用を選んで実行すると、ハーネスが PilotDeployment を暗黙作成（無ければ）し、バッチを `batch_kind: "pilot"` で deployment に接続する。新しい画面・タブは作らない。
2. **実測値投入はパイロット行の 1 アクション**: パイロット表の各行に「実測値を追加」→ ファイル D&D ＋ join keys / outcome 列 / as_of のフィールド（初期値は pipeline `output_contract.id_columns` と EvaluationSpec の目的メトリクスから prefill。prefill は固定参照であり推論ではない）。投入で既存 `score_pilot_outcomes` Job が走る。
3. 使用メトリクスを事前に表示: 「スコアリングには承認済み評価（<metric>）を使用します」— EvaluationSpec への固定参照。formal 評価が無い場合は「暫定メトリクス」と明示。
4. 文言境界: パイロット表の見出し直下に恒常の一文 — **「これはローカルの仮運用検証です。本番デプロイではありません。」** UI 語彙は「テスト予測 / 仮運用検証 / 本番引き渡し」に固定し、「デプロイ」を人間向けコピーから排除する（内部 ID の `PilotDeployment` は改名不要）。
5. 完了後の Codex 側は現行契約（scoring report → observation → `register_validation_audit`）のままで良い。wake ポリシーは S6 参照。

受け入れ基準:

- [ ] ドロワーから pilot 種別で実行 → deployment 自動作成 → バッチ接続の pytest。
- [ ] 実測値 D&D → scoring Job → report → Codex observation の E2E pytest（フェイク runner）。
- [ ] 「予測 → 実測値 → スコア → 監査」を一画面で追える browser 証拠（B等級）＋ ライブ検証（L等級）。

### S5（高・UX）: Home に運用状態の物語が無い

事実: `_recommended_focus` の梯子は data → understanding → assumptions → evaluation → split → approach → notebooks → reports で終端。予測・修復・パイロットの状態が Home に出ない。0123 リクエスト Focus 6 の「Next Decision カード」は未実装。

指示（K5）— すべて DB の固定事実から導出できる状態のみ追加（意味推論なし）:

1. reports 終端の先に運用フェーズの focus を追加する（優先順）:
   - a. 失敗パイプラインがあり修復版未登録 → 「予測パイプラインの修復を Codex が担当中」→ Leaderboard 該当行へ。
   - b. formal（無ければ暫定ベスト）run に実行可パイプラインがあり予測バッチ 0 → 「テストデータで予測を実行できます」→ ドロワーへ。
   - c. pilot deployment に予測バッチあり・アウトカム 0 → 「実測値の投入待ち」。
   - d. scoring report あり・validation audit 無し → 「Codex の検証監査待ち」。
   - e. audit あり → 「次のイテレーション提案を確認」→ 該当 chat_update / plan へ。
2. モデル運用状態の 1 行サマリ（「最良モデル: <name>（formal/暫定）・パイプライン: 実行可・予測バッチ: 2・仮運用: 実測値待ち」）を Home のモデルカードに追加。値はすべて既存 API の集計。
3. Chat の完了メッセージ（`093b0f4` の文言）は良い。ただし列挙が固定コピーで長くなり始めている — 状態依存の次アクションは Home focus カードに寄せ、Chat 側は focus への参照＋Codex authored 提案に任せる方向を維持する。

受け入れ基準:

- [ ] 各運用 focus 状態遷移の pytest（fixture で状態を作り focus_key をアサート）。
- [ ] modeling 完了 → 予測 → 失敗 → 修復 → pilot の各段階で Home カードが変わる browser 証拠。

### S6（中・policy）: wake ポリシーの明文化と統一

事実: 入力検証失敗の wake は `starting|between_turns|waiting_for_runner` のみ（`routes.py:8258` 付近）で、`completed` を起こさない。Console メッセージ（J2）と pilot observation は completed を起こす。予測ランタイム失敗（worker 側）は inbox に書くが wake 経路が不明瞭。

指示: ポリシーを一つに固定して spec に書く —

> **ユーザー起点の操作に由来する observation（予測実行失敗・入力検証失敗・アウトカム投入・スコアリング完了）は、Full Auto が ON（プロジェクトが full_auto/AUTONOMOUS_LOOP 系）である限り completed セッションを wake する。`stopped`（電源 OFF）は絶対に wake しない。** Codex 起点のバックグラウンド失敗は inbox 記録のみとし、次ターンで自然に読まれる。

これは「Full Auto は継続する一つのセッション」という製品契約の帰結であり、J2 console の前例と一致する。

受け入れ基準:

- [ ] 予測失敗 → completed セッション wake の pytest。stopped は wake しない pytest。

### S7（中・UX）: ドロワーの事前情報と事後検証の不足

事実: 契約表・テーブル別 D&D・列過不足レポートは実装済み（良い）。不足: (a) パイプライン準備状態（スモークの provenance — 実データ selftest 検証か合成 1 行か）、(b) アップロード後の行数・join key の null/重複数、(c) target 列を含むファイルへの扱い、(d) 過去アップロードの再利用。

指示(K3):

1. ドロワー先頭に readiness 行: 「登録時検証: selftest（実データ n 行）/ 合成 1 行のみ」「直近実行: 成功/失敗/未実行」。すべて既存 metadata（`smoke_validation.input_source` 等）の表示。
2. 検証レポートに固定チェックを追加: 行数、宣言 join_keys/entity_keys の null 数・重複数、（parquet も含め）dtype の実測。判定はせず数字を出す。dtype `not_available` の解消。
3. **target 列の扱い**: manifest に `input_contract.forbidden_columns: [..]`（任意、Codex が宣言）を追加。アップロードに該当列があれば validation report に `forbidden_columns_present` として事実表示し、既定は**警告＋そのまま実行可**（predict.py が無視すべき）。ハーネスは剥がさない・拒否しない・列名から target を推測しない。拒否するのは Codex/ユーザーが契約で明示した場合のみ。
4. **列マッピング UI は作らない。** 列名不一致は事実として表示し、次の 2 アクションを出す: 「ファイルを修正して再アップロード」/「Codex に相談する」（既存 observation 経路）。ドロップダウンで列を貼り替える UI は DataRobot 世代の再発明であり、リネームの意味判断をハーネスに持ち込む。
5. **アップロードの再利用**: `prediction_input` はプロジェクト水準で保存済み（正しい）。ドロワーに「最近の予測入力」リストを出し、選択時に**その pipeline の契約で再検証**する（検証は安価な固定チェック）。DatasetSnapshot 化はしない — 学習・評価データ空間を汚さない現設計が正しい。

受け入れ基準:

- [ ] forbidden_columns の宣言→警告表示→実行可の pytest。
- [ ] join key null/重複/行数チェックの pytest。
- [ ] 再利用リスト選択→別パイプライン契約で再検証の pytest ＋ browser 証拠。

### S8（中・protocol）: manifest 拡張は最小限に

`required_tables`（name/role/columns/join_keys/as_of_column/history_window/optional）は既に十分近い。リクエスト Focus 2 の 11 フィールド案は過剰。後方互換の追加は以下のみ:

```json
"input_contract": {
  "inference_format": { ... },
  "required_tables": [
    {"name": "application", "role": "primary",  "columns": [...], "join_keys": ["SK_ID_CURR"], "optional": false},
    {"name": "bureau",      "role": "history",  "columns": [...], "join_keys": ["SK_ID_CURR"], "history_window": "all", "optional": true},
    {"name": "calendar",    "role": "future",   "columns": [...], "join_keys": ["date"],       "optional": false}
  ],
  "entity_keys": ["SK_ID_CURR"],
  "as_of_column": null,
  "prediction_horizon": {"length": 28, "unit": "day"},
  "forbidden_columns": ["TARGET"]
}
```

- 追加は 4 点のみ: role enum に `"future"`、`entity_keys`、`prediction_horizon`、`forbidden_columns`（すべて任意）。
- `optional_quality_improving_inputs` / `minimum_viable_inputs` は **`optional: true` の意味そのもの**なので追加しない。「optional テーブル無しでも動くが精度が落ちる」ことの説明は README/Codex の仕事。
- 意味的十分性（この履歴窓で足りるか、将来共変量が本当に将来既知か）はハーネスは判定しない。列・型・キー・行数・target 不在の固定検証のみ。

### S9（低〜中）: 失敗の各サーフェス表現

- **Chat**: ユーザー起点の実行失敗のみ、1 回だけ事実メッセージ（固定コピー: 失敗事実＋Job リンク＋「Codex に修復依頼済み」）。原因説明は Codex authored が後続。Codex 起点（pilot 定期バッチ等）は Chat に流さない。
- **Activity**: 全失敗を常時表示（現行どおり）。
- **Leaderboard**: S3 のバッジ。
- **Assets**: 失敗レコードを artifact 化**しない**（Job＋transcript event で十分。artifact スパムを避ける）。
- **Codex Console**: observation が transcript event として見える（実装済み・正しい）。

### S10（低）: 本番運用境界 — now / next / later

- **Now（このまま）**: テスト予測・仮運用検証・語彙の規律（「デプロイ」禁止）。本番コネクタ・スケジューラ・監視・承認ゲートは作らない。
- **Next（仮運用が回った後）**: `prediction_horizon`/as_of の運用（時系列パイロット）、pilot の複数バッチ時系列表示、repaired lineage の可視化強化。
- **Later（明示要求があってから）**: スケジュール実行、モデルバージョン選択と rollback、drift 監視、本番書き込み境界、承認ゲート。**現時点で予約すべき概念は「PilotDeployment はモデルバージョン参照＋コンテキストの汎用箱である」という現設計だけで足りる**。新エンティティの先行追加は不要。

## リクエスト個別質問への回答（要点）

- **予測は Leaderboard 行起点で正しいか** → 正しい。モデル/パイプライン文脈なしの予測入口は契約参照を失う。プロジェクト水準の「Predictions」タブは作らない（断片化）。一覧性は Assets のカテゴリ（実装済み）と Data の関連出力枠で足りる。
- **アップロードは `prediction_input` で正しいか** → 正しい。DatasetSnapshot 化は学習/評価空間の汚染。ただし S7-5 の再利用導線を足す。
- **予測 5 種の区別** → `batch_kind` enum（S3-4 で貫通）＋ pilot は deployment 接続で区別。`production` は enum に入れない。
- **`--input` と `--input-dir`** → マルチテーブルは `--input-dir` を標準必須、単一テーブルは `--input` 継続。登録スモークも同形（S1）。
- **チャット/コンソール** → J2/J3 の方針は正しく実装されている。予測運用指示（「このモデルで application_test.csv を推論して」）も handoff 経路で main session に渡り、キーワードルータは存在しない（良い）。唯一の違反が S2 の stderr 分岐。
- **Codex の自律性** → 修復戦略（前処理修正/manifest 修正/不足テーブル要求/不適合宣言）の選択は inbox observation の事実だけ渡せば Codex が判断できる。ハーネスに修復戦略の分岐を書かないこと。
- **ヒーロー デモ** → Home Credit ミニ（3 テーブル・数千行）で: Full Auto → formal 評価 → パイプライン登録（selftest 同梱）→ ドロワーで application_test アップロード → 故意に壊した旧版で失敗 → 失敗バナー＋observation → Codex 修復 → 新バージョン → 再実行成功 → pilot 種別で再予測 → 実測値投入 → scoring report → validation audit → Home の focus カードが各段階で変化。これ一本で K1〜K5 の受け入れを横断する。

## Codex 推論 / Skill に残すもの（ハーネスに書かないもの）

- selftest fixture の中身の設計（分布・未知カテゴリ・行選択）。
- 入力の意味的十分性の判断、列名不一致時の対処方針、履歴窓・将来共変量の妥当性。
- 失敗原因の説明文、修復戦略の選択、修復レポート。
- パイロット監査（verdict / gap 分解 / 次イテレーション）— 既存契約どおり。
- パッケージング規律（前処理の学習/推論同一性、カテゴリ処理、target-free 入力対応）→ `tablex-modeling-strategy` Skill に「予測パイプライン包装」節を追加、または独立 Skill `tablex-prediction-pipeline-packaging`。

## 削除・回避リスト

- `summarize_prediction_pipeline_runtime_failure` の stderr パターン分岐（S2）。
- 列マッピング ウィザード、target 列の自動剥離・列名からの target 推測。
- `batch_kind` のファイル名からの推測。
- 「デプロイ」という人間向け語彙。新タブ。予測失敗の artifact 化。
- manifest の過剰拡張（11 フィールド案）。
- 本番運用機構の先行実装。

## 実施順の提案

**K1（スモーク/セルフテスト パリティ）→ K2（失敗状態の表現と S2 除去）→ K3（ドロワー完成）→ K4（パイロット一画面）→ K5（Home 運用ナラティブ）→ K6（spec/AGENTS 更新＋ヒーロー デモ L 証拠）。**

K1 が先である理由: K3〜K5 の UI はすべて「パイプラインが契約どおり動く」という前提の上に立つ。前提が壊れたまま UI を完成させると、美しいドロワーが嘘をつく製品になる。

## ドキュメント更新指示

- `docs/agent_interface_spec.md`: 新節「Operations」を追加し、Part 1 の骨子を製品契約として固定する。最低限含めるもの:
  - 三フェーズ表（1.2）と「フェーズが進んでも判断はハーネスに移らない」原則。
  - 運用コンテキストの定義（1.3）: バージョン系譜・評価契約参照・バッチ台帳 (service, version, as_of)・判断記録。
  - wake ポリシー（S6 の文言）。
  - 予測バッチ種別の語彙（テスト予測/仮運用検証/本番引き渡し。「デプロイ」を人間向けコピーに使わない）。
  - 「ハーネスは実行時失敗の事実のみを述べ、原因解釈は Codex が chat_update で行う」。
  - 「予測が Tablex の外に出る唯一の経路は、ハーネス所有コードによる明示的・人間承認済みエクスポートである」（1.5 のハードゲート）。
  - 監視の形（1.6）: ハーネスはトリガーの事実まで、閾値判定・drift 解釈は Codex の監査レポート。
- `AGENTS.md`: Core Rules に 2 行 — 「予測パイプラインの登録時検証は、実行時とまったく同じ呼び出し形(--input / --input-dir)で行う。stderr 等の非固定テキストへのパターン分岐で人間向け解釈を生成しない。」「本番書き込み・エクスポートはハーネス所有コードと人間承認ゲートのみを経由し、runner のコードには開放しない。」
- PROTOCOL 生成（`agent_workspace.py`）: required_tables / --input-dir / selftest / forbidden_columns の契約と例を追加（S1-4）。
