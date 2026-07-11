---
id: assets-notebooks
title: 资产、报告和 Notebook
description: 理解 Tablex 如何保存输出，以及如何阅读 Notebook、报告和资产。
---

# 资产、报告和 Notebook

Tablex 会把输出保存为资产，使它们可以从相关上下文打开：Data、Insight、Leaderboard、Home 或 Assets 清单。

## Assets

Assets 是统一资产清单。它包括上传数据、profile、报告、Notebook、模型结果、预测流水线、图表、manifest 和验证输出。

当你需要搜索或审计所有存在的内容时使用 Assets。当你已经知道要读什么时，优先使用 Home、Insight、Data 或 Leaderboard 中的上下文链接。

## Reports

报告应该面向人类可读。它们最适合承载决策、摘要、有来源支持的调研、模型比较叙事和最终项目交接。

## Native marimo Notebook

Notebook 源码是记录资产。Tablex 在产品内打开 native marimo Notebook，让分析同时可由人类和智能体执行与复用。

![在 Tablex Notebook workspace 中运行的 native marimo 报告](/img/screenshots/native-marimo-report.png)

如果 Notebook 失败，Tablex 应该显示失败，并让智能体修复源码。不应使用静态 HTML fallback 来隐藏 Notebook 错误。

## 截图和图表

Notebook 内的图表能帮助人类读者理解分布、误差、特征行为和模型诊断。本文档使用公开演示项目的截图，在不暴露私有项目数据的情况下展示产品工作流。
