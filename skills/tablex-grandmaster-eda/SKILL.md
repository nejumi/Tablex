---
name: tablex-grandmaster-eda
description: Use when Tablex or Codex needs deep tabular data understanding, Kaggle Grandmaster-inspired EDA, hypothesis extraction, multi-table relational exploration, visual storytelling, or marimo notebook/report artifacts for predictive, forecasting, anomaly, clustering, inverse-problem, or optimization-coupled data-science work. This skill raises EDA/report quality without constraining Codex to fixed recipes.
---

# Tablex Grandmaster EDA

## Operating Principle

Treat Codex as the analyst. Treat Tablex as the harness that provides context, remembers assets, preserves evaluation boundaries, and presents the work to humans.

- Do not turn this skill into deterministic column-name, metric, or chat-intent rules.
- Do not stop at profile statistics when data is available. Use code to inspect the actual tables, relationships, examples, and failure modes.
- Use the current project evidence to choose the path. The moves below are a map, not a cage.
- Ask useful questions, but in Full Auto continue with explicit assumptions and fallback policies when safe.
- Produce artifact-backed findings, hypotheses, ideas, and marimo notebooks that a human can read inside Tablex.

## Quick Workflow

1. Read `AGENTS.md`, `.harness/task_contract.json` if present, and the relevant Tablex context artifacts: DatasetSnapshot, profile, SemanticCatalog, RelationalCatalog, Assumptions, Questions, EvaluationSpec, SplitManifest, prior reports, prior notebooks, and current Ideas/Findings.
2. Read `skills/tablex-notebook-quality/SKILL.md` when authoring or revising a notebook.
3. Read `references/grandmaster_eda_patterns.md` when planning exploration depth, multi-table analysis, leakage/drift checks, entity trajectory review, or hypothesis extraction.
4. Read `references/tablex_marimo_outputs.md` before writing marimo notebooks or notebook-adjacent JSON artifacts.
5. Execute exploratory analysis in the controlled workspace. Prefer DuckDB, Polars, pandas, Plotly, matplotlib, scikit-learn, and project-approved libraries already available in the environment.
6. Turn discoveries into Tablex assets: findings, ideas, assumptions, questions, evidence, notebook source, rendered notebook/report, figure manifest, and next-analysis queue.
7. Register every important output through the AgentResult contract. Do not leave insight only in terminal logs.

## Analysis Standard

The minimum acceptable output is not "profile completed." The minimum useful output is a set of evidence-backed beliefs that changes what the next agent or human should do.

Strong EDA should normally include:

- Task/objective reasoning, including non-column, derived, aggregate, unsupervised, distributional, or optimization-coupled objectives when plausible.
- Row/entity/time semantics and prediction-time availability.
- Multi-table relationship review, join keys, table grain, and aggregation hypotheses when multiple tables exist.
- Train/validation/test, temporal, group, or deployment-boundary risks.
- Leakage, drift, duplicate, missingness, outlier, high-cardinality, text, and sparse-feature investigations chosen from evidence.
- Entity or group deep dives: trajectories, representative examples, target-split examples, edge cases, and counterexamples.
- A hypothesis queue: what likely matters, why, how to test it, and what artifact would confirm or reject it.
- Human-facing visual story: a few high-signal figures with interpretation, not a chart dump.

## Output Contract

When the task involves data understanding or notebook authoring, aim to produce these artifacts unless the task contract narrows the scope:

- `notebooks/grandmaster_eda.py`: executable marimo notebook source.
- `reports/eda_story.md`: human-readable analysis narrative and read order.
- `artifacts/eda_hypotheses.json`: hypotheses, confidence, evidence, next check, risk.
- `artifacts/visual_story_cards.json`: UI-ready cards with titles, captions, evidence links, and next actions.
- `artifacts/research_source_notes.json`: external source notes and how they shaped the analysis.
- `artifacts/notebook_figure_manifest.json`: figure/table inventory with captions and data sources.
- `artifacts/notebook_evidence_bundle.json`: evidence behind material claims.
- `artifacts/next_analysis_queue.json`: what Codex should do next without losing momentum.

If an artifact cannot be produced, say exactly what is missing and preserve useful partial outputs. Do not create empty smoke artifacts.

## Guardrails

- Never read secrets, `.env`, connector credentials, or credential-like files.
- Never pass connector credentials to an agent, prompt, notebook, or artifact.
- Never use validation/test target values in feature generation prompts, encoders, imputers, joins, or transformations.
- Respect EvaluationSpec and SplitManifest. Do not destructively modify them from EDA or notebook code.
- Do not write to production databases or external systems.
- Do not copy public Kaggle notebook prose, code, or section order. Use public work as craft inspiration and cite sources.
- Do not force supervised classification/regression if the data suggests a different analysis objective.
- Treat Give Up as a last resort after preserving partial artifacts and the next concrete unblocker.

## References

- `references/grandmaster_eda_patterns.md`: distilled EDA moves and source-inspired principles.
- `references/tablex_marimo_outputs.md`: expected marimo notebook structure, UI cards, and artifact schemas.
