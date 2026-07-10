---
id: screenshot-guide
title: Screenshot guide
description: How screenshots are used in the Tablex documentation and which captures are most useful.
---

# Screenshot guide

The docs currently include placeholder illustrations. Replace them with product screenshots as the UI stabilizes.

## Useful screenshots to capture

- Home with Research Plan, Agent Chat, and readable outputs visible.
- Data upload with import progress and primary table controls.
- Insight with a readable report preview.
- Evaluation with provisional vs formal evaluation state.
- Leaderboard with model evidence, notebook actions, and prediction drawer.
- Native marimo notebook loading and opened state.
- Assets with search, categories, and preview.
- Pilot validation with prediction and outcome batches.

## Capture guidelines

- Avoid secrets, private customer data, credentials, and real personal information.
- Prefer demo projects with synthetic or public benchmark data.
- Use consistent browser width when possible.
- Capture both English and Japanese only when UI text itself matters.
- Keep filenames stable, for example `home-workspace.png` or `leaderboard-prediction.png`.

## Where to place files

Put public documentation screenshots under:

```text
apps/docs/static/img/screenshots/
```

Then reference them from Markdown:

```md
![Home workspace](/img/screenshots/home-workspace.png)
```
