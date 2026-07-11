---
id: intro
title: Tablex 문서
slug: /
description: agentic tabular prediction, evaluation, notebooks, assets, pilot validation을 위한 Tablex 워크플로를 배웁니다.
---

# Tablex 문서

Tablex는 표 형식 예측 프로젝트를 위한 agentic 워크벤치입니다. 데이터 과학 에이전트가 데이터를 다루는 동안, 제품은 프로젝트 상태를 이해하기 쉽게 유지합니다. 데이터, 목표, 평가 계약, Notebook, 모델 결과, 예측 파이프라인, 자산, 운영 피드백이 모두 연결됩니다.

![Full Auto, Research Plan, evidence를 보여주는 Tablex Home](/img/screenshots/home-workspace.png)

## Tablex가 필요한 경우

Tablex는 표 형식 프로젝트가 단순히 “CSV를 올리고 모델을 학습한다”로 끝나지 않을 때 유용합니다. 프로젝트에는 여러 테이블, 불확실한 행 단위, 늦게 도착하는 outcome, 파생 target, leakage risk, 외부 조사, 평가 방식에 대한 사람의 판단이 있을 수 있습니다. Tablex는 Codex 또는 다른 에이전트가 이를 추론하는 동안 움직이는 요소들을 계속 보이게 합니다.

## 기본 루프

1. 하나 이상의 데이터 파일을 업로드합니다.
2. 목표를 결정하거나 보류합니다.
3. Full Auto가 데이터를 살펴보고, Notebook을 만들고, 평가를 제안하고, baseline을 학습하고, 모델 결과를 등록하게 합니다.
4. 제품 UI에서 Notebook, 보고서, Leaderboard, Assets를 검토합니다.
5. target이 없는 입력이나 이후 outcome이 있을 때 prediction batch 또는 pilot validation을 실행합니다.
6. 새 증거를 같은 프로젝트로 되돌려 에이전트가 감사, 수리, 개선할 수 있게 합니다.

## UI 읽는 법

Tablex의 주요 화면은 다음과 같습니다.

- Home: 현재 프로젝트 이야기, agent chat, research plan, 추천 다음 작업.
- Data: 업로드된 데이터셋, primary table 선택, objective 설정, profile.
- Insight: 읽기 쉬운 보고서, research findings, 사람을 위한 출력.
- Evaluation: 후보 metric과 split design.
- Leaderboard: model runs, evidence, diagnostics, prediction, pilot actions.
- Assets: 파일, Notebook, 보고서, pipeline, evidence의 정본 인벤토리.

Agent workspace는 사람이 읽는 진행 상황과 contextual action을 함께 보여주며, Codex Console에서는 underlying execution record를 확인할 수 있습니다.

![Observed state, contextual actions, equipped Skills를 보여주는 Agent Chat](/img/screenshots/agent-chat-workspace.png)

## 영어 문서가 정본입니다

영어 문서가 source of truth입니다. 일본어, 중국어 간체, 한국어 페이지는 같은 경로의 영어 페이지에서 번역되며, 영어 변경 후 함께 갱신되어야 합니다.
