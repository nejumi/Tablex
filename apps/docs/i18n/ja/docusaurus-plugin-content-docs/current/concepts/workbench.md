---
id: workbench
title: Workbenchの概念
description: Project、Full Auto、Agent Chat、Codex Console、Research Plan、Skillの役割。
---

# Workbenchの概念

TablexはAgentの周辺にあるworkbenchです。Agentが推論と分析を担い、Tablexがデータ、アセット、評価状態、安全境界、UI導線を整えます。

## Project

Projectは1つの予測または分析の器です。データセット、目的、評価候補、モデル結果、Notebook、レポート、アセット、仮運用結果を保持します。

## Full Auto

Full Autoは継続するAgentセッションです。小さなチケットの連鎖ではなく、同じデータサイエンティストがProjectに残る感覚を目指します。

## Agent Chat

Agent Chatは人間向けの説明面です。何が変わったか、何が不確かか、何に注意すべきか、次にどこを見るべきかを表示します。

![Persistent Chat、Observed state、関連アクション、装備中Skillを表示するAgent workspace](/img/screenshots/agent-chat-workspace.png)

## Codex Console

Codex Consoleは実行記録を見る面です。通常の結論を読む場所ではなく、Runnerが実際に何をしたかを確認したい時に使います。

## Research Plan

Research PlanはAgentの作業計画です。完了したノードは、Notebook、レポート、モデルrun、評価候補、調査結果などの登録済み根拠へリンクしているべきです。

## Skills

SkillはAgentのための再利用可能な職人知識です。EDA、モデリング、特徴量、診断、ドメイン知識などを与えます。Skillは固定ワークフローではありません。
