---
id: quickstart
title: 빠른 시작
description: Tablex 프로젝트를 만들고, 데이터를 업로드하고, Full Auto를 실행하고, 첫 유용한 출력을 검토합니다.
---

# 빠른 시작

이 가이드는 첫 번째 Tablex 프로젝트를 성공적으로 통과하는 흐름을 설명합니다. 목표는 모델링 워크플로를 너무 일찍 강제하는 것이 아니라, 데이터, objective, evaluation, 사람이 읽을 수 있는 output을 하나의 프로젝트에 모으는 것입니다.

## 0. 전체 런타임 시작

호스트에 최신 Codex CLI를 설치하고 인증한 뒤 Tablex launcher를 실행합니다.

```bash
codex login --device-auth  # 인증되지 않은 경우에만
scripts/tablex up
```

Launcher는 호스트 Codex 인증을 재사용하고 첫 실행에 companion runtime을 만듭니다. 호스트 `pip`와 `python3-venv`는 필요하지 않으며, digest로 고정된 공식 uv image에서 runtime을 준비합니다. Docker 시작 전에 인증과 local sandbox를 검사하며 실패하면 시작하지 않습니다. `http://localhost:8080`을 여세요. 이후에도 `scripts/tablex up`, 종료는 `scripts/tablex down`을 사용합니다.

## 1. 프로젝트 만들기

Tablex를 열고 포털에서 프로젝트를 만듭니다. 데이터셋이나 비즈니스 질문을 설명하는 짧은 이름을 사용하세요.

## 2. 데이터 업로드

단일 테이블이나 관련 테이블 묶음을 업로드할 수 있습니다. 업로드 시점에 primary table은 선택 사항입니다. 예측 행 단위, 파생 테이블, target, task type을 데이터 이해 이후에 정해야 한다면 설정하지 않고 둘 수 있습니다.

대용량 데이터셋은 페이지를 열어 둔 채 import status를 확인하세요. Tablex는 백그라운드에서 테이블 profile을 만들고 Home과 Data에 상태를 표시합니다.

## 3. 목표 설정 또는 보류

target이 명확하면 Data에서 설정합니다. 명확하지 않다면 자연어로 목표를 설명하고 에이전트가 먼저 데이터를 살펴보게 합니다.

예:

- 다음 달 고객 이탈을 예측한다.
- 검토가 필요한 이상 거래를 찾는다.
- 구매 행동으로 상품을 클러스터링한다.
- 여러 history table에서 신청자 단위 risk model을 만든다.

## 4. Full Auto 시작

Full Auto는 지속되는 에이전트 세션을 시작합니다. 에이전트는 데이터를 검사하고, Notebook과 보고서를 작성하고, research findings를 등록하고, evaluation을 제안하고, 모델을 학습하고, Tablex validation을 통해 artifacts를 제출할 수 있습니다.

Home은 현재 상태를 보여줍니다. Codex Console은 execution transcript를 보존합니다. Agent Chat은 사람을 위한 설명 화면입니다.

## 5. 첫 출력 검토

첫 pass 후에는 다음을 여세요.

- 데이터 이해를 위한 Data Notebook.
- source-backed conclusions와 summary가 담긴 Insight report.
- metric과 split assumptions를 위한 Evaluation candidates.
- 모델 비교와 evidence를 위한 Leaderboard rows.
- 전체 인벤토리가 필요할 때 Assets.

## 6. 다음 단계 결정

흔한 다음 단계는 다음과 같습니다.

- evaluation split 승인 또는 수정,
- 더 깊은 feature engineering 요청,
- target-free input으로 test prediction 실행,
- outcome data를 추가해 pilot validation 시작,
- 더 나은 report 또는 notebook 요청.
