---
name: tablex-modeling-strategy
description: Use when Codex needs to choose, compare, or explain tabular modeling strategies, including baselines, linear models, tree ensembles, calibration, ensembling, foundation tabular models, time-aware models, unsupervised objectives, anomaly detection, or deployment-ready prediction pipelines. This is craft guidance, not a fixed recipe.
---

# Tablex Modeling Strategy

Use this skill when a Tablex project moves from data understanding into evaluation-backed modeling, model diagnostics, or prediction pipeline packaging.

## Operating Principle

Codex chooses the modeling path from project evidence. This skill provides craft knowledge and tradeoffs; it must not be treated as a checklist, model-family gate, or fixed execution order.

- Start from the task, row/entity/time semantics, EvaluationSpec, SplitManifest, leakage review, and prediction-time availability.
- Keep simple sanity floors visible. Do not mistake a sanity floor for the final modeling strategy when the evidence supports richer features.
- Compare models only under the same evaluation contract. If the evaluation contract is missing or provisional, make that explicit before optimizing.
- Register important runs, diagnostics, notebooks, reports, and prediction pipelines as artifacts. Do not leave modeling results only in terminal output.
- Treat serious modeling work as competition-winner-quality analysis rather than a baseline submission: explain the data-generating process, domain hypotheses, feature families, validation strategy, ablations, and why the chosen model should generalize.

## Winner-Quality Modeling Standard

For a project-best candidate, aim for the level of reasoning expected in a strong Kaggle winner solution write-up. This is a quality bar, not a fixed recipe.

- Start from domain mechanics: what real-world process creates each table, row, timestamp, missing value, categorical code, text field, or repeated entity?
- Turn domain ideas into feature hypotheses before modeling: recency, frequency, severity, trend, volatility, saturation, consistency, delinquency/default history, utilization, capacity, exposure, peer/group context, and interaction effects where they match the task.
- Make relational feature engineering deliberate. For each supporting table, explain the entity grain, join key, prediction-time availability, useful time windows, aggregation choices, and leakage risks.
- Compare feature families, not only model families. Show what application-only, each relational table, time-windowed aggregates, missingness indicators, categorical handling, text features, and interaction features add or fail to add.
- Use ablations or fold-safe deltas for important claims. Do not claim a feature family matters just because it appears in feature importance.
- Treat hyperparameter tuning, seed averaging, blending, stacking, calibration, and thresholding as modeling hypotheses tied to validation behavior, not cosmetic additions.
- Register enough evidence that another analyst can tell what was tried, why it was tried, what changed, and what the remaining uncertainty is.

## Feature Engineering Depth

Strong tabular modeling usually needs more than "join aggregates and run boosting." Choose depth according to data semantics:

- Multi-table history: counts, sums, means, extrema, quantiles, ratios, recency, first/last values, slopes, deltas, recent-vs-lifetime contrasts, event rates, missing-history flags, and table coverage indicators.
- Credit/risk style data: overdue behavior, utilization ratios, payment-to-balance ratios, approved-vs-requested amounts, bureau activity recency, prior application outcomes, contract type interactions, income-normalized amounts, annuity burdens, and stability proxies.
- Entity and group context: customer/company/group-level statistics, within-group ranks, peer baselines, target-safe encodings only inside folds, and unseen-category behavior.
- Time-aware data: rolling windows, horizon-specific features, lag features, known-future covariates, time-split diagnostics, drift checks, and leakage audits for post-event fields.
- Missingness: missingness as signal, structural missingness, "not applicable" vs unknown, missing count/rate features, and table-level coverage flags.
- Text/categorical/mixed data: controlled text ablations, high-cardinality encoders fitted inside folds, rare-category handling, domain-derived grouping, and leakage-sensitive masking.

## Strategy Map

Choose from these families based on evidence:

- Sanity floors: constant, majority class, global median/mean, simple stratified median/rate, and trivial leakage checks.
- Linear and generalized linear models: logistic/ridge/lasso/elastic-net, sparse text or high-cardinality hashing, calibrated probabilities, and coefficient inspection.
- Tree ensembles: random forest, extra trees, gradient boosting, LightGBM, XGBoost, CatBoost, histogram gradient boosting, and shallow trees for rule inspection.
- Relational aggregation models: entity-level history aggregation, time-window summaries, count/rate/recency features, and prediction-time availability audits.
- Text and mixed-type models: TF-IDF/hashing, categorical encoders, text-free/text-masked comparisons, and leakage-sensitive text ablations.
- Ensembles: multiple seeds, model-family blends, rank/average blending, stacking only when out-of-fold predictions are generated fold-safely.
- Calibration and thresholds: calibration curves, Brier/log-loss where relevant, precision/recall or cost-sensitive thresholds, and decision curves when the business objective needs them.
- Foundation tabular models: TabPFN/TabICL-style approaches when dataset size, feature count, class count, and runtime constraints fit their assumptions.
- Time-aware or forecasting models: rolling-origin validation, lag/rolling features, known-future covariates, and horizon-specific diagnostics.
- Target-free analysis: clustering, anomaly detection, density/outlier scoring, similarity search, segmentation, and inverse-problem analysis when no target exists or target construction is deferred.

## Foundation Tabular Model Guidance

Use foundation tabular models as an option, not a default.

- Consider them when the tabular task is small to medium, labels are reasonably clean, and the runtime can support the dependency.
- Avoid forcing them on very large tables, very wide sparse text matrices, heavy multi-table relational tasks without aggregation, or tasks where temporal/group leakage dominates.
- If an extra package is needed, keep experiments inside the AgentSession workspace. For registered prediction pipelines, declare the dependency in `requirements.txt` and let Tablex's existing isolated pipeline smoke run verify it.
- If the package is not available, record that as a runtime fact and compare other strong candidates rather than blocking the project.

## Ensemble Discipline

Ensembles are useful only when they are evaluation-safe and reproducible.

- Use out-of-fold predictions for stacking. Never train a stacker on validation predictions paired with validation labels outside the split discipline.
- Record constituent run ids, blend weights or stacker settings, seed policy, and metric deltas in run params or report artifacts.
- Package ensembles as ordinary prediction pipelines: include every submodel artifact and make `predict.py` combine them deterministically.
- If a simple single model is close to the ensemble, prefer the simpler model unless diagnostics justify the complexity.

## Diagnostics Expected For Serious Models

For a candidate that may become the project best model, produce or explicitly defer:

- Native feature importance when the model family supports it.
- Permutation importance on the validation split or out-of-fold predictions.
- Partial dependence or accumulated local effects for the most important features when meaningful.
- SHAP or TreeSHAP when the runtime/model supports it and the cost is justified.
- Slice metrics across important groups, missingness flags, time windows, categories, and confidence bins.
- Calibration and threshold analysis for probabilistic classification.
- Error examples and prediction examples with leakage and availability caveats.

## Pipeline Packaging

When a model is useful enough to predict on new data:

- Submit it through the existing prediction pipeline protocol rather than inventing a new registration path.
- Include preprocessing, feature generation, model artifacts, prompt files if any, and dependency declarations.
- Ensure `predict.py` can rebuild the same features from new input data without training targets.
- For multi-table data, describe required tables and join/as-of requirements in the pipeline manifest when available.

## Guardrails

- Never read secrets or connector credentials.
- Never use validation/test targets in feature generation, encoders, imputers, model selection prompts, or LLM prompts.
- Respect EvaluationSpec and SplitManifest; do not destructively change them.
- Do not hard-code a model-family sequence for every project.
- Do not add harness-side model diversity gates. Diversity is a modeling judgment for Codex, reported through artifacts and evaluation evidence.
