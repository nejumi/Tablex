---
id: workbench
title: 工作台概念
description: 理解 Project、Full Auto、Agent Chat、Codex Console、Research Plan 和 Skills。
---

# 工作台概念

Tablex 是围绕智能体构建的工作台。智能体负责推理和分析；Tablex 负责让数据、资产、评估状态、安全边界和 UI 导航保持一致。

## Project

Project 是一次预测或分析工作的容器。它包含数据集、目标、评估候选、模型结果、Notebook、报告、资产和试运行验证记录。

## Full Auto

Full Auto 是持续的智能体会话。它应该像一位数据科学家持续跟进项目，而不是一串互不相干的小任务。支持任务可以训练、profile、渲染或验证，但主要推理上下文仍保留在智能体那里。

## Agent Chat

Agent Chat 用于面向人的进展和决策。它应该告诉你发生了什么变化、哪些事情仍不确定、哪里需要注意，以及下一步应该看哪里。

![包含持续聊天、观察状态、上下文操作和已装备 Skills 的 Agent workspace](/img/screenshots/agent-chat-workspace.png)

## Codex Console

Codex Console 是原始执行视图。当你需要检查 runner 实际做了什么时使用它。它不是阅读项目结论的普通界面。

## Research Plan

Research Plan 是智能体的项目计划。它应该由注册输出支撑。已完成节点应链接到证据，例如 Notebook、报告、模型运行、评估候选或有来源支持的调研发现。

## Skills

Skills 是给智能体使用的可复用经验：EDA 方法、建模策略、特征工程模式、诊断习惯或领域 playbook。Skill 会指导智能体，但不是由 harness 强加的刚性流程。
