---
id: modeling
title: 建模和诊断
description: Tablex 如何呈现模型运行、诊断、Notebook 和更深入的特征工程。
---

# 建模和诊断

Leaderboard 是预测就绪模型候选的晋升界面。只有可下载的 pipeline 通过隔离预测冒烟测试、能在同一隔离依赖环境中启动训练入口、以数值精度匹配该 run 的主要指标，并包含 manifest、训练与预测入口、依赖和本地使用说明时，才会显示对应行。只有分数的 run 会保留在实验历史中，直到满足这项契约。

每个 Leaderboard 行都能从 UI 运行预测，也能下载为自包含的本地 pipeline bundle。显示分数、模型实现和导出 bundle 因而属于同一个版本化交付物。

![比较模型分数、评估质量、诊断和预测就绪状态的 Leaderboard](/img/screenshots/leaderboard-model-evidence.png)

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
