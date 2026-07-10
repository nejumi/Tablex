---
id: prediction-pilot
title: Prediction and pilot validation
description: target-free prediction inputs를 실행하고, 나중에 outcomes를 추가해 pilot validation으로 프로젝트를 개선합니다.
---

# Prediction and pilot validation

Prediction은 학습된 후보가 새로운 target-free data를 만나는 곳입니다. Pilot validation은 나중에 outcome이 돌아왔을 때 prediction과 reality 사이의 gap에서 프로젝트가 학습하는 곳입니다.

![Prediction drawer placeholder](/img/screenshots/prediction-placeholder.svg)

## Test prediction

Leaderboard row를 열고 Predict를 선택합니다. Tablex는 pipeline contract를 보여줍니다. required columns 또는 required tables, forbidden target columns, 에이전트가 제공한 self-test information이 포함됩니다.

target-free prediction input을 업로드하거나 선택합니다. multi-table pipeline이라면 pipeline contract가 선언한 tables를 제공합니다.

## Prediction이 실패할 때

Prediction failure는 막다른 길이 아니어야 합니다. Tablex는 사실 기반 failure를 보여주고, 에이전트에게 observation으로 되돌려 pipeline을 수리하거나, missing inputs를 명확히 하거나, 올바른 data shape를 요청하게 해야 합니다.

## Pilot validation

Pilot validation은 prediction batch에서 시작합니다. 이후 가능하면 join keys와 observed-at information을 가진 outcomes를 추가합니다. Tablex는 batch를 score하고 validation audit을 등록할 수 있습니다.

## Production handoff

현재 단계에서 Tablex는 full serving platform이 되려는 것이 아닙니다. 실용적인 handoff는 다른 시스템이 실행할 수 있는 reproducible pipeline bundle, manifest, evaluation contract, operational notes입니다.

## 좋은 pilot 질문

- 이후 데이터에서도 score가 유지되었는가?
- 어떤 segment가 예상보다 나쁜가?
- input distribution이 shift되었는가?
- outcomes가 delayed 또는 partially missing인가?
- 모델을 repair, recalibrate, retrain, replace 중 무엇을 해야 하는가?
