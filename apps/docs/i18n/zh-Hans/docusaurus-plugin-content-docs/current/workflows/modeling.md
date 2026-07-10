---
id: modeling
title: 建模和诊断
description: Tablex 如何呈现模型运行、诊断、Notebook 和更深入的特征工程。
---

# 建模和诊断

Leaderboard 是模型候选变得可比较的地方。好的行不仅应解释分数，还应说明模型使用了什么、为什么尝试它、有哪些证据支持，以及还缺什么。

![Leaderboard placeholder](/img/screenshots/leaderboard-placeholder.svg)

## 先看基线

基线是 sanity floor。它们有助于发现目标泄漏、切分错误、不可能的指标，或模型根本没有学习。即使出现更强模型，基线也应保持可见。

## 特征工程

特征工程应由假设驱动。对于关系型数据，这通常意味着在预测实体层面聚合行为，观察个体轨迹，再把微观观察泛化为可复用特征。

## 诊断

有用诊断包括：

- 树模型的 feature importance；
- permutation importance；
- partial dependence 或相关的特征响应图；
- 可行时的 SHAP 风格摘要；
- 重要群体的 slice metrics；
- 校准和误差分析。

## Model Notebook

模型 Notebook 应能独立阅读。它应解释任务、评估、使用的数据、特征组、建模意图、分数、诊断、限制和下一步实验。

## 重复或不清楚的模型行

如果两个 leaderboard 行代表相同模型和证据，智能体应避免同时提交。Tablex 可以隐藏重复显示噪声，但更好的修复是让智能体提交干净、带版本的结果。
