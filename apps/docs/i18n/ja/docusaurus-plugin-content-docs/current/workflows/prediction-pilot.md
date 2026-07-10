---
id: prediction-pilot
title: 予測と仮運用評価
description: ターゲットなし入力への予測、実測値投入、仮運用評価の流れ。
---

# 予測と仮運用評価

予測は、学習済み候補を新しいターゲットなしデータに適用する段階です。仮運用評価は、後から届く実測値を使って予測と現実の差を学ぶ段階です。

![Prediction drawer placeholder](/img/screenshots/prediction-placeholder.svg)

## テスト予測

Leaderboard行を開き、Predictを選びます。Tablexはpipeline contractを表示します。必要な列・テーブル、禁止されるtarget列、self-test情報を確認します。

ターゲットを含まない予測入力をアップロードまたは選択します。複数テーブルpipelineでは、contractが要求するテーブルを提供します。

## 予測が失敗した時

失敗は行き止まりではありません。Tablexは事実としての失敗を表示し、Agentへobservationとして返します。Agentはpipeline修復、入力不足の説明、正しいデータ形状の確認を行います。

## 仮運用評価

仮運用は予測batchから始まります。後でjoin keyや観測日時を含む実測値を追加すると、Tablexがscoreし、validation auditを登録できます。

## 本番引き渡し

現段階のTablexは本番serving platformではありません。実用的な引き渡しは、再現可能なpipeline bundle、manifest、評価契約、運用メモです。

## 良い仮運用の問い

- 後続データでもスコアは維持されたか。
- どのsegmentで悪化したか。
- 入力分布は変わったか。
- 実測値は遅延・欠損・訂正を含むか。
- 修復、再校正、再学習、置き換えのどれが必要か。
