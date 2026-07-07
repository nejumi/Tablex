# Tablex Marimo Outputs

Use marimo as the primary medium for Tablex visual analysis and reports when the task involves data understanding, modeling diagnostics, or human-facing analysis.

## Notebook Shape

Create a marimo Python notebook, usually `notebooks/grandmaster_eda.py`.

Recommended sections:

1. Reader brief: the project, current objective belief, what to inspect first, and what changed.
2. Data map: tables, row/entity/time semantics, relationship diagram or compact relationship table.
3. Objective review: candidate targets/tasks, assumptions, rejected options, and unresolved questions.
4. Evidence ladder: high-signal EDA sections chosen for this dataset.
5. Deep dives: entity/group/trajectory examples or error examples when relevant.
6. Hypotheses and ideas: what to try next, expected impact, evidence, risk.
7. Evaluation boundary: known EvaluationSpec/SplitManifest and what claims are or are not allowed.
8. Appendix: raw profile tables, source artifacts, execution notes, and reproduction commands.

Use Plotly, matplotlib, seaborn, Altair, DuckDB, Polars, pandas, or scikit-learn as appropriate. Prefer libraries already installed in the Tablex environment. If a better library is missing, record the requested dependency and the missing analysis explicitly instead of silently degrading.

Human-facing Tablex notebooks must contain visual diagnostics. Text and tables alone are not acceptable for data understanding or model diagnostics. Choose chart types from the evidence: bar charts for categorical distributions and slice metrics, line charts for time or ordered trajectories, scatter/hexbin plots for relationships and residuals, histograms or ECDFs for target and error distributions, heatmaps for missingness/correlation/confusion matrices, and small multiples for entity/group comparisons. For model diagnostics, use the standard interpretation stack when technically supported: permutation importance, native tree-based feature importance, partial dependence for the most important features, SHAP inspection, residual/error slices, and representative prediction examples. If a diagnostic is not possible from the available artifacts or runtime, register that limitation in the fixed `quality_manifest.model_diagnostics` check list instead of leaving the gap invisible.

## UI-Ready Artifacts

Write compact JSON artifacts alongside the notebook so Tablex can render ideas and findings outside the notebook.

`artifacts/eda_hypotheses.json`:

```json
{
  "schema_version": "eda_hypotheses.v1",
  "hypotheses": [
    {
      "id": "hyp_short_slug",
      "title": "Short human-readable title",
      "claim": "What may be true",
      "why_it_matters": "Why this changes modeling, evaluation, or data collection",
      "confidence": 0.0,
      "risk_level": "low|medium|high",
      "evidence": [{"artifact_id": "art_...", "note": "What supports or challenges it"}],
      "next_check": "Concrete analysis or experiment",
      "suggested_action": "What Codex or a human should do next"
    }
  ]
}
```

`artifacts/visual_story_cards.json`:

```json
{
  "schema_version": "visual_story_cards.v1",
  "cards": [
    {
      "id": "card_short_slug",
      "kind": "finding|idea|risk|question|diagnostic",
      "title": "A title a human can understand in one glance",
      "summary": "One or two sentences, no system-log phrasing",
      "confidence": 0.0,
      "risk_level": "low|medium|high",
      "notebook_anchor": "section-or-cell-anchor",
      "evidence_artifact_ids": ["art_..."],
      "next_action": "The next useful click or agent task"
    }
  ]
}
```

`artifacts/research_source_notes.json`:

```json
{
  "schema_version": "research_source_notes.v1",
  "sources": [
    {
      "title": "Source title",
      "url": "https://...",
      "used_for": "What idea or quality bar this source informed",
      "copied_content": false
    }
  ]
}
```

## Execution And Export

- Keep notebook code reproducible and executable from the project workspace.
- Prefer deterministic sample limits and precomputed summary artifacts for expensive plots; notebooks should visualize and explain, not rerun long training loops on open.
- Marimo cells form a reactive graph. Public variables assigned or returned by cells must be unique across the notebook. Use underscore-prefixed private names for repeated temporaries such as `_mo`, `_fig`, `_ax`, `_table`, and `_data`; do not define public `fig`, `mo`, `pd`, or `np` in multiple cells.
- Keep shared imports in one setup cell and return the shared modules for downstream cells, or use private aliases inside a cell. Avoid copy-pasting the same import/temporary pattern across cells when it would create duplicate public definitions.
- Build figures from `.tablex/data` links or cached summary artifacts, with deterministic sampling for large tables. A notebook should open quickly in native marimo while still showing real visual diagnostics.
- For Japanese or other non-Latin labels, prefer Plotly/HTML-rendered text when it gives reliable glyph rendering in the Tablex viewer. If matplotlib is the right tool and `japanize_matplotlib` is available in the runtime, import it before drawing Japanese labels; if it is unavailable, keep the figure useful and state the font limitation instead of shipping garbled labels.
- Register the native marimo Python source through Tablex. Do not use static HTML snapshots as notebook previews or fallbacks.
- If native marimo fails, keep the source notebook and error note as repair targets. Do not mark the notebook as complete until the source opens.
- Do not mark a notebook as complete if cells were never executed. If execution was impossible, make that the main caveat.

## Writing Style

- Write in the user's configured language for human-facing summaries when that context is available.
- Use natural analyst prose, not ticket or system-event phrasing.
- Titles should be meaningful by themselves. Avoid titles like "Full Auto loop advanced" or "artifact summary."
- Put raw JSON in appendices or downloads, never as the primary report surface.
