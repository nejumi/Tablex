---
id: common-issues
title: 常见问题
description: 处理 Tablex 中与上传、Full Auto、Notebook、预测和文档相关的常见问题。
---

# 常见问题

## 数据上传看起来卡住了

大型关系数据集可能需要较长时间创建 profile。请在 Home 和 Data 查看导入进度。如果下游输出已经存在但活动仍长时间停留，请刷新项目并检查 Jobs。

## 无法选择目标

目标可能被有意暂缓，主表可能尚未设置，或者目标需要用自然语言表达。当项目需要先处理派生目标、聚类、异常检测或聚合时，不要强制目标。

## Full Auto 停止了

如果项目显示正在等待输入，请阅读最新的 Agent Chat 消息。它应说明已完成什么，并给出下一步示例，例如测试预测、更深入的特征工程、批准评估或添加试运行结果。

## marimo Notebook 打不开

如果源码有错误、依赖缺失或 session 需要重启，native marimo Notebook 可能失败。失败应该可见。请让智能体修复 Notebook 源码，而不是依赖静态 fallback。

## Leaderboard 结果是临时的

临时结果表示该 run 对探索有用，但尚未绑定到已批准的评估契约。打开 Evaluation 查看或批准指标和切分。

## 预测失败

检查输入是否满足 pipeline 契约。缺少表、包含目标列、不支持的 dtype 或类别预处理不匹配，都可能导致预测失败。失败应反馈给智能体进行修复或澄清。

## 资产存在但很难找到

使用 Assets 查看完整清单。普通阅读场景下，优先使用 Home、Insight、Data、Leaderboard 和 Notebooks 中的上下文链接。
