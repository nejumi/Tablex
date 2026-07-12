---
id: modeling
title: Modeling and diagnostics
description: Tablex가 model runs, diagnostics, notebooks, deeper feature engineering을 어떻게 보여주는지 설명합니다.
---

# Modeling and diagnostics

Leaderboard는 예측 준비가 끝난 model candidate를 승격하는 화면입니다. 등록된 모든 candidate는 각각 고유한 downloadable pipeline으로 완성해야 하며, 불완전한 candidate를 제거해서 완료로 처리하지 않습니다. 모든 bundle이 isolated prediction smoke test를 통과하고 같은 dependency environment에서 training entrypoint를 시작하며 run의 primary metric과 수치 정밀도로 일치하고 해당 model의 전체 feature construction, fitted estimator, manifest, training/prediction entrypoint, dependencies, local usage instructions를 포함할 때까지 Full Auto가 계속됩니다. Score만 있는 run은 이 필수 작업이 진행되는 동안에만 experiment history에 남습니다.

모든 Leaderboard row는 UI에서 prediction에 사용할 수 있고 self-contained local pipeline bundle로 다운로드할 수 있습니다. 표시 score, model implementation, exported bundle은 하나의 versioned deliverable로 관리됩니다.

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
