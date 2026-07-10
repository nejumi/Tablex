---
id: assets-notebooks
title: Assets, reports, notebooks
description: Tablex가 output을 저장하는 위치와 Notebook, report, artifact를 읽는 법을 이해합니다.
---

# Assets, reports, notebooks

Tablex는 output을 asset으로 저장해, 그것이 중요한 context에서 열 수 있게 합니다. Data, Insight, Leaderboard, Home 또는 Assets inventory에서 접근할 수 있습니다.

## Assets

Assets는 정본 인벤토리입니다. uploaded data, profiles, reports, notebooks, model results, prediction pipelines, figures, manifests, validation outputs가 포함됩니다.

존재하는 모든 것을 검색하거나 감사해야 할 때 Assets를 사용하세요. 이미 무엇을 읽고 싶은지 알고 있다면 Home, Insight, Data, Leaderboard의 contextual links를 우선 사용하세요.

## Reports

Reports는 사람이 읽을 수 있어야 합니다. decisions, summaries, source-backed research, model comparison narratives, final project handoffs에 가장 적합합니다.

## Native marimo notebooks

Notebook source가 artifact of record입니다. Tablex는 product 안에서 native marimo notebooks를 열어 분석을 사람과 에이전트 모두가 실행하고 재사용할 수 있게 합니다.

Notebook이 실패하면 Tablex는 실패를 보여주고 에이전트가 source를 고치게 해야 합니다. static HTML fallback으로 notebook error를 숨겨서는 안 됩니다.

## Screenshots and figures

Notebook 안의 figure는 사람이 distributions, errors, feature behavior, model diagnostics를 이해하는 데 도움이 됩니다. 이 문서의 screenshot은 product UI를 설명합니다. UI가 안정되면 placeholder screenshot을 교체하세요.
