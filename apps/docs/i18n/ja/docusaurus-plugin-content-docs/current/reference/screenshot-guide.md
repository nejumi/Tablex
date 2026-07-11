---
id: screenshot-guide
title: スクリーンショットガイド
description: Tablexドキュメントで使うスクリーンショットの撮り方と置き場所。
---

# スクリーンショットガイド

ドキュメントでは公開またはsynthetic demo Projectのスクリーンショットを使用します。UIが大きく変わった場合もリンクが壊れないよう、安定したファイル名のまま更新します。

## 撮ると有用な画面

- Research Plan、Agent Chat、読むべき成果物が見えるHome。
- import progressと主表設定が見えるData。
- レポートpreviewが見えるInsight。
- 暫定/正式評価が分かるEvaluation。
- モデル根拠、Notebook action、予測drawerが見えるLeaderboard。
- native marimo Notebookのloadingと表示完了。
- 検索、カテゴリ、previewが見えるAssets。
- 予測batchと実測batchが見える仮運用。

## 撮影方針

- 秘密、認証情報、個人情報、本物の顧客データを含めない。
- synthetic dataまたはpublic benchmarkを使う。
- できればブラウザ幅を揃える。
- UI文言が重要なページだけ英語/日本語を撮り分ける。
- `home-workspace.png` のように安定したファイル名にする。

## 置き場所

```text
apps/docs/static/img/screenshots/
```

Markdownからは次のように参照します。

```md
![Home workspace](/img/screenshots/home-workspace.png)
```
