---
id: quickstart
title: クイックスタート
description: Project作成、データアップロード、Full Auto、最初の成果物確認までの流れ。
---

# クイックスタート

このページでは、Tablexで最初のProjectを成功させる流れを説明します。目的は早すぎるモデリングではなく、データ、目的、評価、人間が読める成果物を1つのProjectに集めることです。

## 0. 完全なランタイムを起動する

ホストに最新のCodex CLIをインストールして認証し、Tablex launcherを実行します。

```bash
codex login --device-auth  # 未認証の場合のみ
scripts/tablex up
```

launcherはホストのCodex認証を再利用し、初回にcompanion runtimeを作成します。ホストの`pip`と`python3-venv`は不要で、digest固定した公式uv imageからruntimeを準備します。Docker起動前に認証とlocal sandboxを検査し、失敗時は起動を中止します。`http://localhost:8080`を開きます。2回目以降も`scripts/tablex up`、停止は`scripts/tablex down`です。

## 1. Projectを作る

PortalからProjectを作成します。データセットやビジネス課題が分かる短い名前を付けます。

## 2. データをアップロードする

単一テーブルでも、関連テーブルの束でもアップロードできます。アップロード時点で主表は任意です。行粒度、派生テーブル、ターゲット、タスク形状をデータ理解後に決める場合は未指定のまま進めます。

大きなデータではprofile作成に時間がかかります。HomeとDataで取り込み状況を確認します。

## 3. 目的を決める、または保留する

ターゲットが明確ならDataで設定します。不明なら自然言語で目的を伝え、Agentにデータを見てもらいます。

例:

- 来月の解約を予測する。
- レビューすべき異常取引を見つける。
- 購買行動で商品をクラスタリングする。
- 複数履歴テーブルから申込単位のリスクモデルを作る。

## 4. Full Autoを開始する

Full Autoは継続するAgentセッションです。Agentはデータ確認、Notebook、レポート、評価提案、モデル結果、パイプラインをTablexの検証付きで登録できます。

## 5. 最初の成果物を読む

- データ理解Notebook。
- Insightのレポートと調査。
- Evaluationの指標・分割候補。
- Leaderboardのモデル比較。
- Assetsの全成果物一覧。

## 6. 次を決める

よくある次の一手は、評価分割の承認、特徴量エンジニアリングの深掘り、テスト予測、実測値による仮運用評価、より良いレポートやNotebookの依頼です。
