---
id: common-issues
title: 흔한 문제
description: upload, Full Auto, notebooks, prediction, documentation과 관련된 흔한 Tablex 문제를 해결합니다.
---

# 흔한 문제

## Data upload가 멈춘 것처럼 보임

큰 relational dataset은 profile에 시간이 걸릴 수 있습니다. Home과 Data에서 import progress를 확인하세요. downstream outputs가 이미 있는데 activity가 오래 남아 있다면 project를 refresh하고 Jobs를 확인하세요.

## Target을 선택할 수 없음

Target이 의도적으로 보류되었거나, primary table이 아직 설정되지 않았거나, objective를 자연어로 표현해야 할 수 있습니다. 프로젝트가 derived targets, clustering, anomaly detection, aggregation을 먼저 필요로 한다면 target을 강제하지 마세요.

## Full Auto가 멈춤

프로젝트가 input을 기다린다고 표시되면 최신 Agent Chat 메시지를 읽으세요. 무엇이 완료되었는지 설명하고 test prediction, deeper feature engineering, evaluation approval, pilot outcomes 같은 다음 action 예시를 제공해야 합니다.

## marimo notebook이 열리지 않음

native marimo notebook은 source errors, missing dependencies, session restart 필요 때문에 실패할 수 있습니다. 실패는 보여야 합니다. static fallback에 의존하지 말고 에이전트에게 notebook source repair를 요청하세요.

## Leaderboard 결과가 provisional임

Provisional results는 run이 exploration에는 유용하지만 아직 approved evaluation contract에 묶이지 않았다는 뜻입니다. Evaluation을 열어 metric과 split을 검토하거나 승인하세요.

## Prediction 실패

입력이 pipeline contract를 만족하는지 확인하세요. missing tables, target columns, unsupported dtypes, mismatched categorical preprocessing 모두 prediction을 깨뜨릴 수 있습니다. 실패는 repair 또는 clarification을 위해 에이전트에게 전달되어야 합니다.

## Asset은 있는데 찾기 어려움

전체 인벤토리는 Assets를 사용하세요. 일반적으로 읽을 때는 Home, Insight, Data, Leaderboard, Notebooks의 contextual links를 우선 사용하세요.
