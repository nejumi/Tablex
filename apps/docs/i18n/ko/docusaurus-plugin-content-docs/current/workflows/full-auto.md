---
id: full-auto
title: Full Auto workflow
description: Full Auto가 어떻게 실행되고 언제 멈추며 어떻게 지시를 주는지 설명합니다.
---

# Full Auto workflow

Full Auto는 에이전트가 현재 프로젝트 상태에서 계속 작업하게 합니다. 매 작은 단계마다 묻지 않고 데이터 이해에서 evaluation, modeling, notebooks, reports까지 진행하고 싶을 때 유용합니다.

![Live activity, Research Plan, registered evidence를 보여주는 Full Auto mission control](/img/screenshots/home-workspace.png)

## Full Auto가 시작되면

에이전트는 project context, data manifest, equipped Skills, artifact references, evaluation state, safety boundaries를 받습니다. 파일을 검사하고, Notebook과 report를 쓰고, structured request를 제출하고, validation error에 반응할 수 있습니다.

## 지시하기

일반 지시는 Agent Chat을 사용하세요. main agent가 실행 중이면 Tablex는 그 session에 지시를 전달하고, 답변이 돌아오면 기록해야 합니다.

execution session에 더 직접 이야기하거나 raw execution을 확인해야 할 때는 Codex Console을 사용하세요.

## Full Auto가 멈춰야 할 때

로컬에서 진행할 수 있는 유용한 작업이 끝났고 사람의 입력이나 새 데이터가 필요할 때 Full Auto는 pause해야 합니다.

예:

- prediction을 위한 test data가 필요하다.
- pilot validation을 위한 outcomes가 필요하다.
- evaluation assumptions 승인이 필요하다.
- 사용자가 modeling direction 중 하나를 골라야 한다.
- 에이전트가 합의된 deliverables를 만들었다.

pause할 때 Chat은 무엇이 완료되었는지 말하고, 유용한 다음 지시 예시를 제시해야 합니다.

## 기대하지 말아야 할 것

Full Auto는 고정된 AutoML wizard가 아닙니다. upload 시점에 target을 강제하거나, column name으로 modeling objective를 추정하거나, 보기 좋은 score 뒤에 불확실성을 숨겨서는 안 됩니다.
