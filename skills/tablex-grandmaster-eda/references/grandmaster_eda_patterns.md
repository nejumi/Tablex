# Grandmaster EDA Patterns

This file is craft guidance for Codex, not a deterministic recipe. Pick the moves that match the current project evidence. Do not copy public notebook prose, code, images, or section order.

## Source Notes

- Kaggle collections such as "EDA for tabular data: Advanced Techniques" and "Data Science for tabular data: Advanced Techniques" are useful index points for strong tabular EDA examples.
- Public Home Credit notebooks such as "Home Credit Default Risk - Extensive EDA" and "Home Credit Default Risk Extensive EDA" show how a real multi-table credit-risk task benefits from table-by-table inspection, missingness review, target imbalance review, relationship-aware reasoning, and domain framing.
- NVIDIA's Kaggle Grandmasters material emphasizes deep data storytelling, careful validation, train/test distribution checks, temporal target patterns, diverse baselines, and fast feedback loops.
- marimo is a good Tablex notebook target because notebooks are Python files, reproducible, reactive, executable as scripts, exportable to HTML, and suitable for in-product viewing.

## Exploration Moves

Use these as a menu. Choose deliberately and explain why.

### Objective And Task Framing

- Infer the actual analytical objective from artifacts, data dictionary, filenames, table grain, target-like columns, sample submissions, and user messages.
- Consider supervised prediction, constructed targets, aggregate targets, interval or distributional prediction, forecasting, anomaly detection, clustering, uplift or policy decisions, inverse-problem workflows, and optimization-coupled tasks.
- Keep rejected objective candidates with evidence. A rejected objective can become useful later.
- If the objective is uncertain in Full Auto, proceed with explicit assumptions and a fallback plan instead of blocking.

### Data Map And Provenance

- Identify tables, row grain, entity keys, event times, primary/foreign-key candidates, table roles, and prediction-time availability.
- For multi-table datasets, produce a compact relationship map before feature ideas. Prefer a visual relationship diagram when possible.
- Separate training labels, scoring/submission format, lookup tables, and event/history tables. For Kaggle-style competitions, sample submission files usually define output shape rather than source evidence.

### Boundary, Leakage, And Validation

- Review what is known at prediction time and what may be post-outcome.
- Inspect train/test or train/holdout distribution shift when both sides exist.
- Inspect temporal patterns in target or core features when any timestamp or ordered event field exists.
- Inspect group/entity overlap risks before random split claims.
- Treat validation design as part of data understanding, not a postscript.

### Missingness, Duplicates, And Data Quality

- Check missingness as a possible signal, not only a cleaning nuisance.
- Look for duplicate rows, duplicate entities, near-duplicate records, repeated event patterns, and inconsistent records.
- For duplicated or repeated entities, compare target distribution, time ordering, and source table coverage.
- Distinguish impossible values, sentinel values, business-coded values, and true missing values.

### Entity Trajectories And Deep Dives

- Sample representative entities from important strata: target classes, high/low risk, unusual missingness, high activity, recent events, and model-error slices when predictions exist.
- For each sampled entity, trace supporting rows across tables and time. Look for behavior patterns that aggregate statistics hide.
- Use deep dives to generate hypotheses, not anecdotes. Convert each observed pattern into a testable aggregate or diagnostic.

### Feature Hypotheses

- Turn observations into candidate feature families: aggregations, recency/frequency/monetary style summaries, categorical interactions, temporal lags, rolling statistics, text signals, exposure-normalized quantities, stability signals, or domain transforms.
- Fit or validate feature ideas only inside the approved split boundary.
- Keep a "try later" queue for ideas that require more data, extra libraries, domain confirmation, or longer runtime.

### Baselines As Feedback

- Use baselines to learn about the data landscape, not just to fill a leaderboard row.
- Compare model families when feasible: sanity floor, linear/logistic, tree boosting, and dataset-specific alternatives.
- Use diagnostics as EDA feedback: feature importance, permutation importance, calibration, threshold curves, error slices, partial dependence, and representative false positives/false negatives when the artifacts support them.

### Visual Story

- Prefer a few decisive figures over a gallery of disconnected plots.
- Each figure should answer a question, state the evidence boundary, and change the next action.
- Use captions that say what the human should conclude, not merely what the axes are.
- Keep raw JSON as downloadable evidence, not the primary human experience.

## Strong Output Signals

- The notebook starts with "what to read first" and the current belief state.
- Findings have short human-readable titles, confidence, risk, evidence, and next checks.
- Ideas are actionable and tied to observed patterns.
- The report says what changed after analysis.
- The next agent can resume from artifacts without rereading the entire notebook.
