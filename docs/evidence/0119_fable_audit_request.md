# Fable Audit Request: Tablex 0119 Product Gap Closure

Date: 2026-07-07

Please audit the current Tablex implementation.

## Context

Tablex is a tabular-first prediction and analysis meta-harness. The goal is not to rebuild a classical AutoML tool. The goal is to support Codex as an autonomous data science agent that can understand data, form hypotheses, design evaluation, build models, diagnose errors, report findings, generate reusable assets, and continue through prediction, pilot, and production learning loops.

Primary contracts:

- `AGENTS.md`
- `docs/agent_interface_spec.md`
- `docs/exec-plans/0119_target_product_gap_closure_directive.md`

Hard constraints:

- Do not add natural-language rule processing.
- Do not infer target, objective, modeling intent, or task shape in harness code.
- Do not silently rewrite or mask Codex-authored text or plan status.
- Do not use static HTML notebook fallback as notebook evidence.
- Do not expose maker vocabulary such as AgentSession, sidecar, schema names, or internal IDs in normal user-facing UI.
- Native marimo Python source is the notebook artifact of record.
- Harness should run alongside Codex as a sidecar: context, data access, skills, schema-validated tools, artifact registration, lineage, and UI. It must not block Codex with fake readiness gates or brittle workflow rules.

## Audit Focus 1: Data Upload, Objective, Target, and Task Shape

The current product appears to force primary table and target selection too early, possibly before upload or before Codex has understood the data. This is a core product mismatch.

Expected behavior:

- Data upload must be possible with no objective, no target, and no primary table selected.
- `target_column` is only one possible field after a supervised task is established.
- Primary table should not be fixed at upload time. Codex may choose it after understanding data, or create a derived table first.
- Objective should be specifiable in natural language.
- The task may be supervised classification/regression, but it may also be clustering, anomaly detection, multilabel prediction, multiple targets, distribution prediction, inverse optimization, aggregate-level prediction, or exploratory analysis.
- Codex may need to change row granularity, aggregate tables, join tables, create derived tables, or create derived targets before a task is well-defined.
- Full Auto should not stop when target/objective is unclear. It may open an intervention window, but if unanswered it should make explicit assumptions and continue.
- Harness must not infer target or objective from column names, UI-required fields, or statistical shortcuts.
- Consider whether Codex-authored, schema-validated artifacts such as `ObjectiveSpec`, `TaskSpec`, `DerivedTable`, and `DerivedTarget` are needed.

Please audit:

- Any UI/API requirement that blocks upload or Full Auto start on target/primary table.
- Any harness-side target/objective inference.
- Any data model or Research Plan assumption that narrows the product to 2010s-style AutoML.
- Whether derived tables/targets are first-class, lineage-linked artifacts.

## Audit Focus 2: Reports and Research Findings as Human-Readable Assets

Reports currently feel low-value or hard to read. Research findings and prior knowledge artifacts should be meaningful human-facing assets, not thin JSON or Markdown records.

Expected behavior:

- Reports should support human decision-making.
- Prior knowledge and existing research should include purpose, sources, key claims, reliability notes, implications for the project, recommended actions, and links to related assets.
- Research reports should not be just URL lists.
- When useful, reports should include images, tables, comparison matrices, charts, media, visualizations, short source excerpts, and related notebook links.
- Report narrative, hypotheses, interpretation, and recommendations should be Codex-authored, not backend template prose.
- Harness should provide schema validation, artifact registration, lineage, preview/rendering, and links.
- Reports should be shorter narrative assets that complement deeper marimo notebooks.
- Insight, Report, Notebook, ResearchPlan node, Data, Leaderboard, and Chat should be cross-linked.

Please audit:

- Whether `report`, `research_findings_report`, `insight`, and related artifacts are actually readable.
- Whether report previews render useful content or just raw structured payloads.
- Whether backend-generated prose is masquerading as analysis.
- Whether reports can contain and render rich tables/media/visual evidence.

## Audit Focus 3: Direct-Open UX from Chat to Artifacts

Chat mentions saved reports/notebooks/artifacts, but clicking "open" can land the user on a tab where the artifact is not visible or not obvious. This breaks the core workflow.

Expected behavior:

- Chat artifact actions should directly open the specific artifact/report/notebook/run/prediction batch.
- Navigating to a tab is not enough.
- After clicking, the artifact should be shown in a reader/modal or the destination should scroll to, expand, and highlight the exact item.
- Users should not have to search after clicking.
- Report, Notebook, Research Finding, Prediction Batch, Leaderboard Run, Pipeline Bundle, Pilot Scoring Report, and Validation Audit should all support direct-open behavior.
- Chat action payloads likely need `artifact_id`, `artifact_type`, `target_surface`, `anchor`, and `preferred_viewer`.
- Links that only contain `target_tab` or go to a generic list should be treated as insufficient.
- If an artifact cannot open, Chat/Activity should state the factual reason.

Please audit:

- All chat action payloads and destination handlers.
- Whether direct-open works across Home, Insight, Data, Leaderboard, Assets, and Notebook surfaces.
- Whether DOM anchors and artifact preview requests are consistent.
- Whether any "Open report" action lands on a generic page instead of the actual report.

## Audit Focus 4: Test Prediction, Pilot, and Production Lifecycle

Tablex must not end at model evaluation and leaderboard ranking. Prediction, pilot, and production learning loops are core product requirements.

Expected behavior:

- Each leaderboard model should have a reproducible prediction pipeline that accepts target-free inference input.
- Users should be able to upload test/inference data, select a pipeline, and generate prediction batches.
- Predictions should be saved as artifacts and visible from Chat, Leaderboard, Assets, Data, Notebook, and Report surfaces.
- Inference schema should follow the Codex-defined real-world input contract, not necessarily training-table-minus-target.
- For temporal/history features, `predict.py` should recompute features from as-of history internally. Harness must not invent features.
- Pilot phase should join prediction batches with later outcomes, calculate fixed metrics, and generate pilot scoring reports.
- Codex should consume pilot scoring reports, audit validation scheme quality, investigate leakage, distribution shift, feature gaps, objective mismatch, and model defects, then extend Research Plan and continue.
- Production phase should support pipeline bundles, input/output contracts, monitoring, drift detection, retraining plans, audit/reporting, and rollback concepts.
- Prediction/pilot/production should feed the main Full Auto session, not fragment the work into unrelated tiny Codex jobs.

Please audit:

- Workstream C and D implementation coverage.
- Whether pipeline bundles are actually usable for prediction.
- Whether test prediction UI/API exists and is understandable.
- Whether pilot scoring feeds back into Codex and Research Plan.
- Whether production-phase concepts exist in spec/UI/API or are still missing.

## Audit Focus 5: Workstream A-G Completion Against 0119 Directive

Please classify each workstream in `docs/exec-plans/0119_target_product_gap_closure_directive.md` as:

- implemented and verified
- partially implemented
- implemented but weakly verified
- contradicted by current behavior
- missing

Specific checks:

- Full Auto should not silently stall, stop, or show stale UI state.
- Research Plan state must come from Codex-authored plan artifacts or schema-validated tool substrate, not UI inference or process presence.
- Leaderboard, Pipeline, Model Diagnostics, and Pilot tools should return structured self-repair errors to Codex when submissions are incomplete or invalid.
- Native marimo notebooks should not have static HTML fallback or backend-authored notebook prose.
- Report, Insight, Research Finding, and Notebook direct-open flows should work.
- Home should show the state clearly; Data, Insight, Leaderboard, and Assets should not be unnecessarily complex.
- Natural-language rule processing, harness-side inference, fake readiness gates, and maker vocabulary should not remain.

## Evidence to Inspect

Please inspect current code and runtime evidence directly. Important files and directories include:

- `AGENTS.md`
- `docs/agent_interface_spec.md`
- `docs/exec-plans/0119_target_product_gap_closure_directive.md`
- `docs/evidence/0119_current_verification.md`
- `apps/backend/tabular_harness/services/agent_sessions.py`
- `apps/backend/tabular_harness/services/research_plans.py`
- `apps/backend/tabular_harness/services/research_plan_timeline.py`
- `apps/backend/tabular_harness/services/analysis_notebooks.py`
- `apps/backend/tabular_harness/services/agent_session_results.py`
- `apps/backend/tabular_harness/api/routes.py`
- `apps/backend/tabular_harness/worker/jobs.py`
- `apps/frontend/src/App.tsx`
- `apps/frontend/src/components/`
- `apps/frontend/src/copy.ts`
- `apps/frontend/src/styles.css`
- relevant backend tests under `apps/backend/tests/`
- live SQLite/runtime state under `data/metadata/app.db` and `data/artifacts/`

## Requested Output

Please return:

1. Severity-ordered findings.
2. Root cause for each issue.
3. File/code/API/UI/runtime evidence for each issue.
4. Assessment against Tablex product philosophy.
5. Recommended fix order.
6. Acceptance criteria for each fix.
7. Tests that should be added or strengthened.
8. UI or workflow surfaces that should be removed, hidden, or simplified.
9. The single highest-value end-to-end scenario to run next.

Do not focus only on whether tests pass. Audit whether the product behaves like a Codex-native tabular workbench rather than a brittle AutoML UI.
