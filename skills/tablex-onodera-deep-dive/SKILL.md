---
name: tablex-onodera-deep-dive
description: Use when a tabular project has entity, user, product, account, session, order, company, device, patient, or item identifiers and Codex should inspect raw entity trajectories or micro case studies to generate feature-engineering hypotheses, domain insights, model explanations, or winner-solution-style notebooks. This is craft guidance inspired by Kaggle Grandmaster trajectory analysis, not a fixed recipe.
---

# Tablex ONODERA Deep Dive

Use this skill when raw records can be grouped into human-readable trajectories: user-item purchases, account histories, customer applications, company job postings, sensor/device events, support tickets, medical episodes, subscriptions, fraud events, churn journeys, recommendations, or any repeated entity behavior.

The core move is:

> look microscopically at real trajectories, notice mechanisms, turn them into feature hypotheses, then test them macroscopically.

This is craft guidance for Codex. Do not turn it into harness-side rules, keyword routing, or mandatory quotas.

## When To Use

Reach for this skill when the dataset contains:

- Entity IDs: `user_id`, `customer_id`, `SK_ID_CURR`, `account_id`, `company_id`, `device_id`, `patient_id`, `session_id`, `order_id`, `product_id`, or similar.
- Repeated observations per entity, item, pair, group, or time period.
- Sequence, recency, frequency, churn, reorder, default, fraud, anomaly, recommendation, retention, or lifecycle behavior.
- A model result that is hard to explain from aggregate tables alone.
- A need for stronger feature engineering than generic joins plus gradient boosting.

## Microscope To Macro Workflow

1. **Choose trajectories deliberately**
   - Sample a few ordinary cases, target-positive cases, target-negative cases, high-activity cases, sparse-history cases, model errors, confident successes, and surprising edge cases.
   - For classification, inspect trajectories from both positive and negative classes, plus borderline or high-confidence model errors when model outputs exist.
   - For regression, bin the target into meaningful ranges such as low/mid/high, quantiles, tails, or domain thresholds, then inspect trajectories from each bin.
   - If important non-target categories exist, such as product family, geography, channel, contract type, cohort, segment, or source system, inspect representative trajectories across those categories too.
   - If labels are involved, respect the active split. Do not inspect validation or test targets to invent features.
   - Prefer examples that represent different regimes rather than only leaderboard-friendly stories.

2. **Reconstruct the raw journey**
   - Build compact, readable timelines at the natural grain: entity, entity-item pair, session, order, application, contract, device, or event.
   - Show event order, time gaps, quantities, statuses, categories, co-occurring items, missingness, and state transitions.
   - Preserve enough raw columns that a human can see what happened, not just summary statistics.

3. **Annotate mechanisms**
   - Ask: what behavior, constraint, lifecycle stage, substitution, saturation, fatigue, recovery, seasonality, opportunity, or absence is visible?
   - Separate observation from hypothesis. One trajectory can suggest a mechanism, not prove it.
   - Look for "why not" cases: expected repeat that did not happen, missing expected event, no-reorder/no-purchase/no-default/no-claim states, substitutions, or competing outcomes.

4. **Generalize into feature families**
   - Recency: days/events since last occurrence, recent-vs-lifetime contrast, time since first/last state.
   - Frequency: counts, rates, streaks, gaps, repeat ratio, opportunity-adjusted ratios.
   - Intensity: amounts, basket/order/session size, utilization, severity, exposure, burden.
   - Stability: variance, trend, slope, volatility, drift, consistency, lifecycle stage.
   - Pair behavior: entity-item counts, position, co-occurrence, replacement/substitution, affinity, chance denominator after first exposure.
   - Absence behavior: no-event features, "None" or no-repeat models, missing-history flags, structural missingness.
   - Context: day/hour/month, cohort, peer group, category, geography, product family, contract type, channel.
   - Metric-specific postprocessing: if the competition or business metric converts probabilities to decisions, reason about the decision rule instead of only raw probabilities.

5. **Validate macroscopically**
   - Plot target/metric behavior by the proposed feature, with train-only or fold-safe discipline.
   - Compare distributions across regimes, slices, and time windows.
   - Run ablations by feature family, not only by model family.
   - Check whether important features match the original micro observation. If they do not, revise the hypothesis.

## Tablex Outputs

When this skill materially influences work, leave artifact-backed evidence:

- A micro casebook section in a marimo notebook: selected trajectories, why they were selected, and what was noticed.
- Feature hypothesis records: mechanism, candidate feature family, required grain, leakage/availability risk, and validation plan.
- Macro validation plots: feature-target curves, slice metrics, ablation deltas, error examples, or diagnostics.
- A model notebook narrative that ties feature families back to observed mechanisms.

Good output should let a human follow the chain:

`raw trajectory -> behavioral hypothesis -> feature design -> validation evidence -> model effect`.

## Guardrails

- Do not copy external solution text, code, figures, or section order. Use public write-ups only as craft inspiration.
- Do not overfit stories. Micro cases generate hypotheses; macro validation decides whether they matter.
- Do not inspect validation/test labels to create features or tune examples.
- Do not let memorable anecdotes override EvaluationSpec, SplitManifest, or prediction-time availability.
- Do not hide failed hypotheses. Features that took effort but did not help are valuable modeling knowledge.
