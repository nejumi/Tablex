---
id: common-issues
title: 흔한 문제
description: upload, Full Auto, notebooks, prediction, documentation과 관련된 흔한 Tablex 문제를 해결합니다.
---

# 흔한 문제

## Tablex는 열리지만 Codex 기능이 작동하지 않음

웹 화면만 열리는 것은 Full Auto 준비 완료를 의미하지 않습니다. `scripts/tablex setup`으로 host companion과 Codex runtime을 확인하세요. 인증에 실패하면 `codex login --device-auth`를 실행합니다. Linux sandbox 검사에 실패하면 공식 Codex bubblewrap/AppArmor prerequisites를 설치하고 호스트 보안 제한을 전역으로 끄지 마세요. 이후 `scripts/tablex up`을 실행합니다. 상태는 `scripts/tablex status`, 로그는 `scripts/tablex logs`로 확인합니다. 기본 Codex 경로에는 `OPENAI_API_KEY`가 필요하지 않습니다.

Ubuntu 24.04에서는 배포판이 제공하는 bubblewrap profile을 설치하고 로드한 뒤 모델 호출 없는 검사를 다시 실행합니다.

```bash
sudo apt-get update
sudo apt-get install -y apparmor-profiles apparmor-utils bubblewrap
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
scripts/tablex setup
```

다른 Linux 배포판은 [Codex 공식 sandbox prerequisites](https://learn.chatgpt.com/docs/sandboxing)를 따르세요.

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
