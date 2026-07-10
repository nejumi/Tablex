---
id: evaluation
title: 평가
description: provisional results, formal evaluation contracts, EvaluationSpec, SplitManifest를 이해합니다.
---

# 평가

Evaluation은 Tablex 프로젝트의 척추입니다. 어떤 행을 비교했는지, split이 어떻게 만들어졌는지, 어떤 metric을 썼는지, 어떤 leakage risk를 통제했는지 알아야 model score가 의미를 갖습니다.

## Provisional vs formal results

Provisional results는 탐색에 유용합니다. 에이전트가 만든 internal cross-validation run에서 올 수 있습니다. evaluation contract가 승인되기 전까지는 방향성 있는 결과로 보세요.

Formal results는 승인된 evaluation design에 등록됩니다. 지속적인 비교에 사용해야 하는 숫자입니다.

## EvaluationSpec

EvaluationSpec은 metric과 scoring policy를 정의합니다. 예를 들어 binary classification의 ROC-AUC, regression의 MAE, probability quality의 log loss, domain-specific metric이 있습니다.

## SplitManifest

SplitManifest는 어떤 행이 train, validation, test 또는 fold assignment에 속하는지 정의합니다. leakage control, grouped entities, time-aware validation, repeatable comparison에 중요합니다.

## 점수를 믿기 전에 확인할 것

- target이 명확하게 정의되어 있다.
- split이 prediction scenario와 맞다.
- fold를 넘나들면 안 되는 entity가 함께 유지된다.
- future information이 training features에 들어가지 않는다.
- metric이 관심 있는 decision과 맞다.
- leaderboard row가 notebooks, diagnostics, reports에 연결되어 있다.

## 평가 변경

승인된 evaluation을 제자리에서 덮어쓰지 마세요. 새 candidate 또는 version을 만들고 비교한 뒤, 변경 이유를 보이게 남깁니다.
