---
name: tablex-llm-feature-augmentation
description: Use when Codex considers adding LLM-generated row-level or text-normalization features to tabular prediction pipelines. This skill covers leakage discipline, deterministic caching, provenance, cost awareness, and pipeline packaging. It is guidance for Codex, not a harness-owned generation system.
---

# Tablex LLM Feature Augmentation

Use this skill only when the project evidence suggests that LLM-derived features may add useful external knowledge, text normalization, entity enrichment, or semantic compression beyond ordinary tabular and text features.

## Operating Principle

LLM feature augmentation is a modeling technique chosen by Codex. Tablex should not add a separate harness-owned generation workflow for it.

- Treat generated features as ordinary project artifacts with lineage.
- Compare generated-feature runs under the same EvaluationSpec and SplitManifest as non-generated baselines.
- Package the generation path with the prediction pipeline so new data can be transformed the same way.
- If cost, latency, privacy, or leakage risk is high, skip the technique and record why.

## Good Fit Signals

Consider LLM augmentation when:

- Rows contain natural-language descriptions, titles, notes, product names, job descriptions, addresses, company descriptions, incident narratives, claims, or support tickets.
- Domain knowledge can normalize noisy text into stable concepts, categories, risk tags, or entity descriptors.
- Ordinary TF-IDF/hashing captures surface text but misses semantic grouping that matters for the target.
- The row count and prompt size make generation cost and latency acceptable.

Avoid or defer it when:

- The target can be inferred from post-outcome text or labels embedded in text.
- The table is too large for cost-effective generation without sampling or staged validation.
- The prediction pipeline cannot reproduce the generated features for new data.
- The project lacks an evaluation contract and generated features would only add uncompareable numbers.

## Leakage Discipline

Never include target values or validation/test labels in prompts, examples, cache keys, summaries, or generated feature context.

- Do not pass validation or test targets to an LLM.
- Do not include target-derived examples such as "good rows" and "bad rows" unless they are restricted to the training fold and regenerated fold-safely.
- If any generated feature depends on train-fold statistics or label-derived examples, generate and cache it separately inside each training fold.
- For final prediction pipelines, use only information that would be available at prediction time.
- Treat leakage suspicion as a reason to register an explicit risk and compare a no-LLM baseline.

## Deterministic Cache Pattern

Make generation reproducible and restart-safe.

- Store prompt text in a workspace file.
- Compute a cache key such as `(model_name, prompt_hash, row_hash, schema_version)`.
- Write generated rows to parquet, JSONL, or CSV under the workspace, then register the output as an artifact.
- Include enough metadata to reproduce the cache: model name, prompt file path, prompt hash, row hash fields, cache schema, created time, and input artifact ids.
- Treat cache misses, failed rows, and retries as data quality signals and report their counts.

## Feature Design Patterns

Useful generated outputs are usually compact and typed:

- Normalized category labels from noisy text.
- Short semantic tags or risk factors.
- Extracted structured concepts with confidence or abstain flags.
- Canonicalized entity names or product families.
- Domain descriptors that are not directly present in the row but are justifiable from row text.
- Cleaned text summaries for downstream TF-IDF or embedding-free models.

Avoid verbose free-form paragraphs as direct model inputs unless a downstream text pipeline will process them consistently.

## Cost And Approval Awareness

Before large generation runs, report:

- approximate row count,
- average prompt size,
- model or provider if known,
- expected cache reuse,
- whether external network/API use is required,
- and the rollback plan if the generated features do not improve formal evaluation.

External API use may require approval under the existing Tablex network and credential policy. Never materialize secrets into prompts, workspaces, artifacts, or logs.

## Pipeline Packaging

If a generated feature improves a model enough to submit as a candidate:

- Include prompt files, generation code, cache schema, and transformation code in the prediction pipeline bundle.
- Make `predict.py` apply the same augmentation to new data or read an explicitly supplied generated-feature table with matching cache metadata.
- Record generated feature artifact ids and prompt hashes in run params or report artifacts.
- If the augmentation cannot be reproduced for new data, do not present the model as deployable; mark it as exploratory.

## Reporting

Report generated-feature work like any other model feature strategy:

- what was generated,
- why it should help,
- what baseline it is compared against,
- whether the metric moved under the same split,
- what leakage checks were performed,
- generation failure rate,
- cost/latency estimate,
- and whether the final pipeline can reproduce it.
