---
id: modeling
title: モデリングと診断
description: モデルrun、診断、Notebook、特徴量深掘りの読み方。
---

# モデリングと診断

Leaderboardはモデル候補を比較する場所です。良い行はスコアだけでなく、何を使い、なぜ試し、どの根拠があり、何が不足しているかを説明します。

![Leaderboard placeholder](/img/screenshots/leaderboard-placeholder.svg)

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
