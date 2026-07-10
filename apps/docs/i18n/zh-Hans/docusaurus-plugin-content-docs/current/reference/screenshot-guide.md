---
id: screenshot-guide
title: 截图指南
description: Tablex 文档如何使用截图，以及哪些截图最有用。
---

# 截图指南

当前文档包含占位插图。随着 UI 稳定，请用产品截图替换它们。

## 值得捕获的截图

- Home：Research Plan、Agent Chat 和可读输出同时可见。
- Data 上传：导入进度和主表控件。
- Insight：可读报告预览。
- Evaluation：临时与正式评估状态。
- Leaderboard：模型证据、Notebook 操作和预测 drawer。
- Native marimo Notebook 的加载状态和打开状态。
- Assets：搜索、分类和预览。
- Pilot validation：预测批次和实际结果批次。

## 截图原则

- 避免 secrets、私有客户数据、凭据和真实个人信息。
- 优先使用合成数据或公开 benchmark 数据的 demo 项目。
- 尽量使用一致的浏览器宽度。
- 只有当 UI 文本本身重要时，才同时捕获英文和日文。
- 保持文件名稳定，例如 `home-workspace.png` 或 `leaderboard-prediction.png`。

## 文件放置位置

把公开文档截图放在：

```text
apps/docs/static/img/screenshots/
```

然后在 Markdown 中引用：

```md
![Home workspace](/img/screenshots/home-workspace.png)
```
