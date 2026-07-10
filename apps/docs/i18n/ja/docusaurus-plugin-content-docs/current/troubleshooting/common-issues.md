---
id: common-issues
title: よくある問題
description: アップロード、Full Auto、Notebook、予測、ドキュメントのよくある問題。
---

# よくある問題

## データアップロードが止まって見える

大きな関係データではprofileに時間がかかります。HomeとDataで進行状況を確認します。下流成果物ができているのにactivityが残る場合は、Projectを更新してJobsを確認します。

## ターゲットを選べない

ターゲットが意図的に保留されている、主表が未設定、または自然言語の目的指定が必要な場合があります。派生ターゲット、クラスタリング、異常検知、集約が必要なProjectでは無理にターゲットを設定しません。

## Full Autoが停止した

入力待ちになっている場合は最新のAgent Chatを読みます。完了した作業と、テスト予測、特徴量深掘り、評価承認、仮運用実測値などの次アクション例があるべきです。

## marimo Notebookが開かない

source error、依存関係不足、session再起動が原因になり得ます。失敗は表示されるべきです。静的fallbackではなく、AgentにNotebook sourceの修復を依頼します。

## Leaderboard結果が暫定扱い

暫定結果は探索には使えますが、承認済み評価契約に紐づいていません。Evaluationで指標と分割を確認・承認します。

## 予測が失敗する

入力がpipeline contractを満たしているか確認します。必要テーブル不足、target列混入、dtype不一致、categorical preprocessingの不一致などが原因になります。失敗はAgentへ返して修復や確認につなげます。

## Assetが見つけにくい

全在庫はAssetsで検索します。通常はHome、Insight、Data、Leaderboard、Notebooksの文脈リンクから開く方が早いです。
