---
id: evaluation
title: 評価
description: 暫定結果、正式評価、EvaluationSpec、SplitManifestを理解します。
---

# 評価

評価はTablex Projectの背骨です。モデルスコアは、どの行を比較し、どう分割し、どの指標を使い、どのリークリスクを制御したかが分かって初めて意味を持ちます。

## 暫定結果と正式結果

暫定結果は探索に役立つ内部CVなどの結果です。方向性を見るには有用ですが、正式な比較としては扱いません。

正式結果は、承認済みの評価設計に紐づく結果です。長く残す比較にはこちらを使います。

## EvaluationSpec

EvaluationSpecは指標とスコアリング方針を定義します。二値分類ならROC-AUC、回帰ならMAE、確率品質ならlog lossなどです。

## SplitManifest

SplitManifestはtrain、validation、test、fold割当を定義します。リーク制御、グループ分割、時系列検証、再現可能な比較に必要です。

## スコアを信頼する前に見ること

- ターゲットが明確である。
- 分割が予測シナリオに合っている。
- 同じentityが不適切にfoldをまたがない。
- 未来情報が特徴量に入っていない。
- 指標が意思決定に合っている。
- Leaderboard行がNotebook、診断、レポートにリンクしている。

## 評価を変える時

承認済み評価を破壊的に書き換えず、新しい候補またはversionを作り、変更理由を残します。
