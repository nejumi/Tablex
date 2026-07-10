---
id: screenshot-guide
title: Screenshot guide
description: Tablex 문서에서 screenshot을 사용하는 방식과 가장 유용한 capture를 설명합니다.
---

# Screenshot guide

현재 문서에는 placeholder illustration이 포함되어 있습니다. UI가 안정되면 product screenshot으로 교체하세요.

## 캡처하면 좋은 screenshot

- Research Plan, Agent Chat, readable outputs가 보이는 Home.
- Import progress와 primary table controls가 보이는 Data upload.
- Readable report preview가 보이는 Insight.
- Provisional vs formal evaluation state가 보이는 Evaluation.
- Model evidence, notebook actions, prediction drawer가 보이는 Leaderboard.
- Native marimo notebook loading과 opened state.
- Search, categories, preview가 보이는 Assets.
- Prediction batch와 outcome batch가 보이는 Pilot validation.

## Capture guidelines

- secrets, private customer data, credentials, real personal information을 피하세요.
- synthetic 또는 public benchmark data를 사용한 demo project를 선호하세요.
- 가능하면 일정한 browser width를 사용하세요.
- UI text 자체가 중요할 때만 English와 Japanese를 모두 캡처하세요.
- `home-workspace.png` 또는 `leaderboard-prediction.png`처럼 파일명을 안정적으로 유지하세요.

## 파일 위치

공개 문서 screenshot은 아래에 넣습니다.

```text
apps/docs/static/img/screenshots/
```

그런 다음 Markdown에서 참조합니다.

```md
![Home workspace](/img/screenshots/home-workspace.png)
```
