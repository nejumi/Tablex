---
id: full-auto
title: Full Auto workflow
description: Full Autoの動き、停止条件、指示方法。
---

# Full Auto workflow

Full Autoは、現在のProject状態からAgentが継続して作業するためのモードです。データ理解、評価、モデリング、Notebook、レポートまでを細かく指示せず進めたい時に使います。

![Live Activity、Research Plan、登録済みEvidenceを表示するFull Auto Mission Control](/img/screenshots/home-workspace.png)

## 開始時に起きること

AgentはProject context、data manifest、装備中Skill、artifact参照、評価状態、安全境界を受け取ります。ファイル確認、Notebookやレポートの作成、構造化requestの提出、検証エラーへの対応ができます。

## 指示する方法

通常の指示はAgent Chatで行います。main agentが動作中なら、Tablexはそのセッションへ指示を届け、返答が戻ったらChatに保存します。

実行内容を直接確認したい場合はCodex Consoleを使います。

## Full Autoが停止すべき時

ローカルで進められる有用な作業が終わり、人間入力や追加データが必要になった時です。

例:

- テスト予測用データが必要。
- 仮運用評価の実測値が必要。
- 評価仮定の承認が必要。
- モデリング方針の選択が必要。
- 合意した成果物が出揃った。

停止時には、Chatで完了内容と次の指示例を示すべきです。

## 期待しないこと

Full Autoは固定のAutoML wizardではありません。アップロード時にターゲットを強制したり、列名から目的を決め打ちしたり、不確実性を隠してスコアだけ見せるものではありません。
