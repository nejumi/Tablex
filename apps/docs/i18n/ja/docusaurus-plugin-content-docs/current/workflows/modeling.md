---
id: modeling
title: モデリングと診断
description: モデルrun、診断、Notebook、特徴量深掘りの読み方。
---

# モデリングと診断

Leaderboardは予測可能なモデル候補を昇格させる場所です。ダウンロード可能なpipelineが隔離環境の予測smoke testに合格し、同じ依存環境で学習entrypointを起動でき、runの主指標と数値精度で一致し、manifest、学習・予測entrypoint、依存関係、ローカル実行手順を含む場合にだけ行が表示されます。スコアだけのrunは、この契約を満たすまで実験履歴に残ります。

すべてのLeaderboard行はUIから予測でき、自己完結したローカルpipeline bundleとしてダウンロードできます。表示スコア、モデル実装、export bundleは、同じversioned deliverableとして管理されます。

![モデルスコア、評価品質、診断、予測準備状況を比較するLeaderboard](/img/screenshots/leaderboard-model-evidence.png)

## Baselineから始める

Baselineはsanity floorです。リーク、壊れた分割、不可能な指標、学習していないモデルを見つけるために残します。

## 特徴量エンジニアリング

特徴量は仮説に基づいて作ります。関係データでは、予測entity単位へ集約し、個別trajectoryを観察し、ミクロな気づきを一般化することが有効です。

## 診断

有用な診断:

- tree modelのfeature importance。
- permutation importance。
- partial dependenceなどの特徴量応答。
- 実行可能ならSHAP要約。
- 重要groupごとのslice metric。
- calibrationと誤差分析。

## モデルNotebook

モデルNotebookは単体で読めるべきです。タスク、評価、使用データ、特徴量群、モデル意図、スコア、診断、制約、次実験を説明します。

## 重複・不明瞭なモデル行

同じモデルと根拠を表す行を重複登録すべきではありません。Tablexが表示上の重複を隠すことはできますが、より良い解決はAgentがcleanでversionedな結果を提出することです。
