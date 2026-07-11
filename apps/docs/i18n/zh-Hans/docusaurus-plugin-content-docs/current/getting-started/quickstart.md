---
id: quickstart
title: 快速开始
description: 创建 Tablex 项目、上传数据、运行 Full Auto，并查看第一批有用输出。
---

# 快速开始

本指南带你完成第一个可用的 Tablex 项目。目标不是过早强迫建模流程，而是把数据、目标、评估和人类可读输出放进同一个项目。

## 0. 启动完整运行环境

请在主机安装并认证最新 Codex CLI，然后运行 Tablex launcher。

```bash
codex login --device-auth  # 仅在尚未认证时
scripts/tablex up
```

Launcher 会复用主机 Codex 认证，并在首次运行时创建 companion runtime。无需主机安装 `pip` 或 `python3-venv`；launcher 会从 digest 固定的官方 uv image 准备 runtime。它会在 Docker 启动前检查认证和 local sandbox，失败时停止启动。打开 `http://localhost:8080`。以后仍使用 `scripts/tablex up`，停止使用 `scripts/tablex down`。

## 1. 创建项目

打开 Tablex，在门户中创建项目。项目名建议简短，并能说明数据集或业务问题。

## 2. 上传数据

你可以上传单表，也可以上传一组相关表。上传时主表是可选的。如果预测行粒度、派生表、目标或任务类型需要在数据理解之后再决定，可以先不设置主表。

对于大型数据集，请保持页面打开并查看导入状态。Tablex 会在后台为表创建 profile，并在 Home 和 Data 上显示状态。

## 3. 设置或暂缓目标

如果目标很明确，可以在 Data 中设置。如果不明确，可以用自然语言描述目标，让智能体先检查数据。

示例：

- 预测客户下个月是否流失。
- 找出需要复核的异常交易。
- 按购买行为聚类产品。
- 从多张历史表构建申请人级别的风险模型。

## 4. 启动 Full Auto

Full Auto 会启动一个持续的智能体会话。智能体可以检查数据、撰写 Notebook 和报告、注册调研发现、提出评估方案、训练模型，并通过 Tablex 校验提交资产。

Home 显示当前状态。Codex Console 保留执行 transcript。Agent Chat 是面向人的解释界面。

## 5. 查看第一批输出

第一轮完成后，建议打开：

- 用于数据理解的 Data Notebook。
- 包含来源支持结论和摘要的 Insight 报告。
- 用于检查指标和切分假设的 Evaluation 候选方案。
- 用于比较模型和查看证据的 Leaderboard 行。
- 需要完整清单时查看 Assets。

## 6. 决定下一步

常见下一步包括：

- 批准或修改评估切分；
- 要求更深入的特征工程；
- 在不含目标值的输入上运行测试预测；
- 添加实际结果以进行试运行验证；
- 要求更好的报告或 Notebook。
