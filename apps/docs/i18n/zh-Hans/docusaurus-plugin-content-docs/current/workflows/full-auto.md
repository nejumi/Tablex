---
id: full-auto
title: Full Auto 工作流
description: Full Auto 如何运行、何时停止，以及如何给出指令。
---

# Full Auto 工作流

Full Auto 让智能体从当前项目状态继续推进。当你希望 Tablex 从数据理解推进到评估、建模、Notebook 和报告，而不是每个小步骤都询问时，它很有用。

![显示实时活动、Research Plan 和已注册证据的 Full Auto mission control](/img/screenshots/home-workspace.png)

## Full Auto 启动后会发生什么

智能体会收到项目上下文、数据 manifest、已装备的 Skills、资产引用、评估状态和安全边界。它可以检查文件、撰写 Notebook 和报告、提交结构化请求，并对校验错误作出反应。

## 给出指令

普通指令使用 Agent Chat。如果主智能体正在运行，Tablex 应该把指令传递给该会话，并在返回时记录答案。

当你需要更直接地与执行会话交互，或检查原始执行时，使用 Codex Console。

## Full Auto 什么时候应该暂停

当本地可推进的有用工作已经完成，而需要人类输入或新数据时，Full Auto 应该暂停。

示例：

- 需要测试数据来进行预测；
- 需要实际结果来进行试运行验证；
- 评估假设需要批准；
- 用户需要在建模方向之间选择；
- 智能体已产出约定的交付物。

暂停时，Chat 应该说明已完成什么，并给出有用下一步指令的示例。

## 不应期待什么

Full Auto 不是固定的 AutoML 向导。它不应在上传时强制目标、不应从列名推断建模目标，也不应用漂亮分数掩盖不确定性。
