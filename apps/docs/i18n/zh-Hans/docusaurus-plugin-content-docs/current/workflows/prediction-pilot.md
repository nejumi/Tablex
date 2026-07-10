---
id: prediction-pilot
title: 预测和试运行验证
description: 运行不含目标值的预测输入，之后添加实际结果，并用试运行验证改进项目。
---

# 预测和试运行验证

预测是训练好的候选模型遇到新的不含目标值数据的地方。试运行验证是后续实际结果回来后，项目从预测与现实之间的差距中学习的地方。

![Prediction drawer placeholder](/img/screenshots/prediction-placeholder.svg)

## 测试预测

打开一个 leaderboard 行并选择 Predict。Tablex 会显示 pipeline 契约：必需列或必需表、禁止出现的目标列，以及智能体提供的 self-test 信息。

上传或选择不含目标值的预测输入。对于多表 pipeline，请提供 pipeline 契约声明的表。

## 预测失败时

预测失败不应是死路。Tablex 应该显示事实层面的失败，并把它作为 observation 反馈给智能体，让智能体修复 pipeline、说明缺少的输入，或请求正确的数据形状。

## 试运行验证

试运行验证从一个预测批次开始。之后，在可用时添加带 join key 和 observed-at 信息的实际结果。Tablex 可以对批次评分并注册验证审计。

## 生产交接

当前阶段 Tablex 不打算成为完整 serving platform。实用的交接物是可复现的 pipeline bundle、manifest、评估契约和运营说明，供其他系统运行。

## 好的试运行问题

- 分数在后续数据上是否保持？
- 哪些 segment 比预期更差？
- 输入分布是否发生变化？
- 结果是否延迟或部分缺失？
- 模型应该修复、重新校准、重新训练，还是替换？
