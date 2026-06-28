# AGENTS.md

このworkspaceはPRODUCT_NAMEによって管理されています。PRODUCT_NAMEは仮置き名であり、正式名称ではありません。

## 目的

表データ予測課題のData Understanding、評価設計、特徴量生成、実験、レポート生成を支援してください。

## Never

- connector secretsを読まない。
- validation/test targetを特徴量生成promptに含めない。
- `evaluation_spec.yaml` を勝手に変更しない。
- Assumptionを勝手にconfirmedへ変更しない。
- `split_manifest.parquet` を無視して評価しない。
- production outputへ直接書き込まない。
- workspace外のファイルを変更しない。
- DBやstorageへ直接接続しない。
- PIIをログやレポートに露出しない。

## Always

- `task_contract.json` を読んでから作業する。
- すべての成果物を `outputs/` または `reports/` に保存する。
- 最終結果は `outputs/result.json` にschema通り出力する。
- 実験コードにはrandom seedを入れる。
- 失敗した場合は `failure_reason` を構造化して返す。
- 評価には `split_manifest.parquet` を使う。
- `data/assumptions.yaml` と `data/evidence.json` がある場合は必ず参照する。
- target encodingはOOFで行う。
- 生成したartifactをresult.jsonに列挙する。

## Evaluation Rules

- 承認済みEvaluationSpecを尊重する。
- Metricを勝手に変更しない。
- Splitを勝手に再生成しない。
- リークが疑われる場合は警告として返す。
- 予測時点可用性がunknownまたはnoの列は、指示がない限りprimary featureに入れない。
- 未回答事項に関する提案はproposed_assumption_updatesとして返す。

## Security Rules

- secretは存在しないものとして扱う。
- 外部ネットワークは使わない。
- 必要な外部情報はハーネスへapproval requestとして返す。
