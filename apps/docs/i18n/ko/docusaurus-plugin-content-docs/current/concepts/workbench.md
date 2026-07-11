---
id: workbench
title: 워크벤치 개념
description: Projects, Full Auto, Agent Chat, Codex Console, Research Plan, Skills를 이해합니다.
---

# 워크벤치 개념

Tablex는 에이전트를 둘러싼 워크벤치입니다. 에이전트가 추론과 분석을 수행하고, Tablex는 데이터, artifacts, evaluation state, safety boundaries, UI navigation을 일관되게 유지합니다.

## Project

Project는 하나의 예측 또는 분석 작업을 담는 컨테이너입니다. datasets, objectives, evaluation candidates, model results, notebooks, reports, assets, pilot validation records를 보관합니다.

## Full Auto

Full Auto는 지속되는 에이전트 세션입니다. 서로 관련 없는 job의 연쇄가 아니라, 한 명의 데이터 과학자가 프로젝트에 계속 붙어 있는 느낌이어야 합니다. 지원 job이 training, profiling, rendering, validation을 할 수 있지만, main reasoning context는 에이전트에게 남아 있습니다.

## Agent Chat

Agent Chat은 사람을 위한 progress와 decision의 공간입니다. 무엇이 바뀌었는지, 무엇이 불확실한지, 무엇이 주의가 필요한지, 다음에 어디를 봐야 하는지 알려줘야 합니다.

![Persistent chat, observed state, contextual actions, equipped Skills가 있는 Agent workspace](/img/screenshots/agent-chat-workspace.png)

## Codex Console

Codex Console은 raw execution view입니다. runner가 실제로 무엇을 했는지 확인해야 할 때 사용합니다. 프로젝트 결론을 읽는 기본 화면은 아닙니다.

## Research Plan

Research Plan은 에이전트의 프로젝트 계획입니다. 등록된 output으로 뒷받침되어야 합니다. 완료된 node는 Notebook, report, model run, evaluation candidate, source-backed research finding 같은 evidence에 연결되어야 합니다.

## Skills

Skills는 에이전트가 사용하는 재사용 가능한 craft knowledge입니다. EDA approaches, modeling strategies, feature engineering patterns, diagnostic habits, domain-specific playbooks 등이 여기에 해당합니다. Skill은 에이전트를 안내하지만 harness가 강제하는 rigid workflow는 아닙니다.
