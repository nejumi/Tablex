---
id: modeling
title: Modeling and diagnostics
description: Tablex가 model runs, diagnostics, notebooks, deeper feature engineering을 어떻게 보여주는지 설명합니다.
---

# Modeling and diagnostics

Leaderboard는 model candidates가 비교 가능한 형태가 되는 곳입니다. 좋은 row는 score뿐 아니라 model이 무엇을 사용했는지, 왜 시도했는지, 어떤 evidence가 뒷받침하는지, 무엇이 아직 없는지 설명해야 합니다.

![Model score, evaluation quality, diagnostics, prediction readiness를 비교하는 Leaderboard](/img/screenshots/leaderboard-model-evidence.png)

## Baselines first

Baselines는 sanity floors입니다. target leakage, broken splits, impossible metrics, 모델이 학습하지 않는 상황을 감지하는 데 도움이 됩니다. 더 강한 모델이 나타난 뒤에도 baselines는 계속 보이는 것이 좋습니다.

## Feature engineering

Feature engineering은 hypothesis-driven이어야 합니다. relational data에서는 prediction entity 단위로 behavior를 aggregate하고, individual trajectories를 살펴본 다음 micro-level observations를 reusable features로 일반화하는 경우가 많습니다.

## Diagnostics

유용한 diagnostics는 다음과 같습니다.

- tree models의 feature importance,
- permutation importance,
- partial dependence 또는 관련 feature-response plots,
- 가능할 때 SHAP-style summaries,
- 중요한 groups에 대한 slice metrics,
- calibration과 error analysis.

## Model notebooks

Model notebook은 단독으로 읽을 수 있어야 합니다. task, evaluation, used data, feature groups, modeling intent, score, diagnostics, limitations, next experiments를 설명해야 합니다.

## 중복되거나 불명확한 model rows

두 leaderboard row가 같은 model과 evidence를 나타낸다면 에이전트는 둘 다 제출하지 않아야 합니다. Tablex가 display noise를 숨길 수는 있지만, 더 좋은 해결은 에이전트가 깨끗하고 versioned 된 results를 제출하는 것입니다.
