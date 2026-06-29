from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from html import escape
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    ExperimentRun,
    ModelVersion,
    Project,
    Report,
    VisualizationSpec,
    utc_now,
)
from tabular_harness.services.approach import (
    latest_project_artifact,
    store_json_artifact,
    store_text_artifact,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.reporting import persist_visualization_spec


@dataclass(frozen=True)
class AnalysisNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    artifact_ids: list[str]


@dataclass(frozen=True)
class ModelDiagnosticsNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    artifact_ids: list[str]


def create_data_understanding_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
) -> AnalysisNotebookResult:
    dataset = _latest_dataset(db, project.id)
    if dataset is None:
        raise ValueError("A DatasetSnapshot is required before generating an analysis notebook")

    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    profile_artifact = latest_project_artifact(db, project.id, "eda_profile")
    understanding_artifact = latest_project_artifact(db, project.id, "understanding_report")
    quality_artifact = latest_project_artifact(db, project.id, "data_quality_gate")
    baseline_metrics_artifact = latest_project_artifact(db, project.id, "baseline_metrics")
    diagnostics_artifact = latest_project_artifact(db, project.id, "evaluation_diagnostics")
    profile_payload = _read_json_artifact(profile_artifact)
    quality_payload = _read_json_artifact(quality_artifact)
    diagnostics_payload = _read_json_artifact(diagnostics_artifact)
    latest_runs = _latest_runs(db, project.id)
    summary = _profile_summary(project, dataset, profile_payload, quality_payload, diagnostics_payload, latest_runs)
    notebook = {
        "schema_version": "analysis_notebook.v1",
        "notebook_kind": "data_understanding",
        "project_id": project.id,
        "project_name": project.name,
        "dataset_snapshot_id": dataset.id,
        "generated_at": utc_now().isoformat(),
        "source_artifacts": {
            "dataset_artifact_id": dataset_artifact.id if dataset_artifact else None,
            "profile_artifact_id": profile_artifact.id if profile_artifact else None,
            "understanding_artifact_id": understanding_artifact.id if understanding_artifact else None,
            "quality_artifact_id": quality_artifact.id if quality_artifact else None,
            "baseline_metrics_artifact_id": baseline_metrics_artifact.id if baseline_metrics_artifact else None,
            "diagnostics_artifact_id": diagnostics_artifact.id if diagnostics_artifact else None,
        },
        "summary": summary,
        "execution_policy": _execution_policy(),
    }
    suffix = new_id("nb")
    notebook_source = render_marimo_notebook(notebook)
    notebook_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="analysis_notebook",
        name=f"data_understanding_notebook_{suffix}",
        filename="data_understanding_notebook.py",
        text=notebook_source,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_kind": "data_understanding",
            "engine": "marimo",
            "execution_status": "generated_not_executed",
            "source_profile_artifact_id": profile_artifact.id if profile_artifact else None,
        },
    )
    html = render_notebook_html_preview(notebook, notebook_artifact.id)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_html",
        name=f"data_understanding_notebook_preview_{suffix}",
        filename="data_understanding_notebook_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": "data_understanding",
            "render_mode": "static_preview",
            "content_type": "text/html",
        },
    )
    report_md = render_notebook_report(notebook, notebook_artifact.id, html_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_report",
        name=f"data_understanding_notebook_report_{suffix}",
        filename="data_understanding_notebook_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_kind": "data_understanding",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="analysis_notebook",
        title="Data Understanding Analysis Notebook",
        summary=summary["overview"],
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(_source_asset_ids(dataset, profile_artifact, understanding_artifact)),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    manifest = {
        "schema_version": "analysis_notebook_run_manifest.v1",
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "notebook_kind": "data_understanding",
        "engine": "marimo",
        "status": "generated_not_executed",
        "generated_at": notebook["generated_at"],
        "execution_policy": _execution_policy(),
        "libraries_referenced": ["marimo", "pandas", "matplotlib", "plotly"],
        "inputs": notebook["source_artifacts"],
        "outputs": {
            "analysis_notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_report_id": report.id,
            "notebook_report_artifact_id": report_artifact.id,
        },
        "next_execution_modes": [
            "local marimo edit/run from downloaded artifact",
            "future controlled marimo runner with artifact capture",
            "future static HTML export when marimo runtime is enabled",
        ],
        "visualization_scope": {
            "data_understanding": True,
            "model_diagnostics": bool(latest_runs),
            "prediction_analysis": diagnostics_artifact is not None,
            "feature_importance": baseline_metrics_artifact is not None,
            "partial_dependence": "planned_runner_output",
        },
    }
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_run_manifest",
        name=f"data_understanding_notebook_manifest_{suffix}",
        filename="data_understanding_notebook_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "report_id": report.id,
            "execution_status": "generated_not_executed",
        },
    )
    _record_lineage(
        db,
        project,
        dataset,
        [
            artifact
            for artifact in [
                dataset_artifact,
                profile_artifact,
                understanding_artifact,
                quality_artifact,
                baseline_metrics_artifact,
                diagnostics_artifact,
            ]
            if artifact is not None
        ],
        notebook_artifact,
        html_artifact,
        manifest_artifact,
        report,
        report_artifact,
    )
    artifact_ids = [notebook_artifact.id, html_artifact.id, manifest_artifact.id, report_artifact.id]
    return AnalysisNotebookResult(
        notebook=notebook,
        report=report,
        notebook_artifact=notebook_artifact,
        html_artifact=html_artifact,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        artifact_ids=artifact_ids,
    )


def create_model_diagnostics_notebook(
    db: Session,
    *,
    store: LocalArtifactStore,
    run: ExperimentRun,
) -> ModelDiagnosticsNotebookResult:
    project = _require_project(db, run.project_id)
    dataset = db.get(DatasetSnapshot, run.dataset_snapshot_id) if run.dataset_snapshot_id else None
    model_version = _model_version_for_run(db, run)
    source_artifacts = _model_diagnostics_source_artifacts(db, run, model_version)
    metrics_payload = _read_json_artifact(source_artifacts.get("baseline_metrics"))
    diagnostics_payload = _read_json_artifact(source_artifacts.get("evaluation_diagnostics"))
    validation_payload = _read_json_artifact(source_artifacts.get("model_validation_metrics"))
    prediction_summary = _read_prediction_summary(source_artifacts.get("prediction_output"))
    summary = _model_diagnostics_summary(
        project=project,
        run=run,
        model_version=model_version,
        dataset=dataset,
        metrics=metrics_payload or loads_json(run.metrics_json, {}),
        diagnostics=diagnostics_payload,
        validation=validation_payload,
        prediction_summary=prediction_summary,
        source_artifacts=source_artifacts,
    )
    notebook = {
        "schema_version": "analysis_notebook.v1",
        "notebook_kind": "model_diagnostics",
        "project_id": project.id,
        "project_name": project.name,
        "dataset_snapshot_id": dataset.id if dataset else run.dataset_snapshot_id,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "generated_at": utc_now().isoformat(),
        "source_artifacts": {
            key: artifact.id if artifact else None for key, artifact in source_artifacts.items()
        },
        "summary": summary,
        "execution_policy": _execution_policy(),
    }
    suffix = new_id("nb")
    notebook_source = render_model_diagnostics_marimo_notebook(notebook)
    notebook_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="analysis_notebook",
        name=f"model_diagnostics_notebook_{suffix}",
        filename="model_diagnostics_notebook.py",
        text=notebook_source,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_kind": "model_diagnostics",
            "engine": "marimo",
            "execution_status": "generated_not_executed",
        },
    )
    html = render_model_diagnostics_html_preview(notebook, notebook_artifact.id)
    html_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_html",
        name=f"model_diagnostics_notebook_preview_{suffix}",
        filename="model_diagnostics_notebook_preview.html",
        text=html,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_kind": "model_diagnostics",
            "render_mode": "static_preview",
            "content_type": "text/html",
        },
    )
    report_md = render_model_diagnostics_report(notebook, notebook_artifact.id, html_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_report",
        name=f"model_diagnostics_notebook_report_{suffix}",
        filename="model_diagnostics_notebook_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_kind": "model_diagnostics",
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="analysis_notebook",
        title="Model Diagnostics Analysis Notebook",
        summary=summary["overview"],
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(_model_source_asset_ids(run, model_version, source_artifacts)),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    db.flush()
    visualization_spec = build_model_diagnostics_visualization_spec(notebook)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=visualization_spec,
        source_artifact_id=notebook_artifact.id,
    )
    manifest = {
        "schema_version": "analysis_notebook_run_manifest.v1",
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id if dataset else None,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "notebook_kind": "model_diagnostics",
        "engine": "marimo",
        "status": "generated_not_executed",
        "generated_at": notebook["generated_at"],
        "execution_policy": _execution_policy(),
        "libraries_referenced": ["marimo", "pandas", "matplotlib", "plotly"],
        "inputs": notebook["source_artifacts"],
        "outputs": {
            "analysis_notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "notebook_report_id": report.id,
            "notebook_report_artifact_id": report_artifact.id,
            "visualization_id": visualization.id,
            "visualization_artifact_id": visualization_artifact.id,
        },
        "diagnostic_extension_points": [
            "model-native feature importance when package exposes fitted estimator metadata",
            "permutation importance against SplitManifest validation rows",
            "partial dependence for high-value numeric/categorical features",
            "prediction slice analysis from evaluation_diagnostics artifacts",
            "calibration and threshold analysis for probabilistic classifiers",
        ],
    }
    manifest_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="notebook_run_manifest",
        name=f"model_diagnostics_notebook_manifest_{suffix}",
        filename="model_diagnostics_notebook_manifest.json",
        payload=manifest,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id if dataset else None,
            "run_id": run.id,
            "model_version_id": model_version.id if model_version else run.model_version_id,
            "notebook_artifact_id": notebook_artifact.id,
            "notebook_html_artifact_id": html_artifact.id,
            "report_id": report.id,
            "visualization_id": visualization.id,
            "execution_status": "generated_not_executed",
        },
    )
    _record_model_notebook_lineage(
        db,
        project,
        run,
        model_version,
        [artifact for artifact in source_artifacts.values() if artifact is not None],
        notebook_artifact,
        html_artifact,
        manifest_artifact,
        report,
        report_artifact,
        visualization,
        visualization_artifact,
    )
    artifact_ids = [
        notebook_artifact.id,
        html_artifact.id,
        manifest_artifact.id,
        report_artifact.id,
        visualization_artifact.id,
    ]
    return ModelDiagnosticsNotebookResult(
        notebook=notebook,
        report=report,
        notebook_artifact=notebook_artifact,
        html_artifact=html_artifact,
        manifest_artifact=manifest_artifact,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        artifact_ids=artifact_ids,
    )


def render_marimo_notebook(notebook: dict[str, Any]) -> str:
    context_json = json.dumps(notebook, ensure_ascii=False, indent=2, sort_keys=True)
    return f'''# Generated by Tablex. Product name is working-name only.
# Run with: marimo edit data_understanding_notebook.py
import marimo

__generated_with = "0.1.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import matplotlib.pyplot as plt
    import plotly.express as px
    return mo, pd, plt, px


@app.cell
def _():
    context = {context_json}
    return (context,)


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        # Data Understanding Notebook

        **Project:** {{context["project_name"]}}  
        **DatasetSnapshot:** `{{context["dataset_snapshot_id"]}}`  
        **Rows:** {{summary["row_count"]}} | **Columns:** {{summary["column_count"]}}  
        **Target:** {{summary["target_column"] or "not selected"}}

        This notebook is generated as a Tablex artifact. It is intentionally editable:
        Codex, Skills, or a human analyst can revise the analysis while keeping the
        harness-owned EvaluationSpec, SplitManifest, artifacts, and lineage intact.
        """
    )
    return


@app.cell
def _(context, pd):
    columns = pd.DataFrame(context["summary"]["columns"])
    findings = pd.DataFrame(context["summary"]["findings"])
    runs = pd.DataFrame(context["summary"]["recent_runs"])
    return columns, findings, runs


@app.cell
def _(columns, mo):
    mo.md("## Column Profile")
    mo.ui.table(columns) if not columns.empty else mo.md("No profile columns are available yet.")
    return


@app.cell
def _(columns, plt):
    top_missing = columns.sort_values("missing_rate", ascending=False).head(15) if not columns.empty else columns
    fig, ax = plt.subplots(figsize=(9, 4))
    if not top_missing.empty:
        ax.barh(top_missing["name"], top_missing["missing_rate"], color="#16b8a6")
        ax.set_xlabel("Missing rate")
        ax.set_title("Top missing columns")
        ax.invert_yaxis()
    else:
        ax.text(0.5, 0.5, "No column profile", ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    fig
    return


@app.cell
def _(columns, px):
    fig = None
    if not columns.empty and "semantic_type" in columns:
        fig = px.histogram(columns, x="semantic_type", color="role", title="Semantic type and role mix")
        fig.update_layout(bargap=0.2)
    fig
    return


@app.cell
def _(findings, mo):
    mo.md("## Findings and Investigation Queue")
    mo.ui.table(findings) if not findings.empty else mo.md("No findings have been generated yet.")
    return


@app.cell
def _(context, mo):
    target = context["summary"]["target_profile"]
    mo.md("## Target Profile")
    mo.md(str(target)) if target else mo.md("No target has been selected. Keep target choice downstream of data understanding.")
    return


@app.cell
def _(runs, mo):
    mo.md("## Modeling Diagnostics")
    if runs.empty:
        mo.md(
            "No experiment runs are available yet. Once baseline or Codex-run experiments emit metrics, "
            "this notebook should add feature importance, permutation importance, partial dependence, "
            "slice diagnostics, and prediction analysis cells."
        )
    else:
        mo.ui.table(runs)
    return


if __name__ == "__main__":
    app.run()
'''


def render_notebook_html_preview(notebook: dict[str, Any], notebook_artifact_id: str) -> str:
    summary = notebook["summary"]
    columns = cast(list[dict[str, Any]], summary["columns"])
    findings = cast(list[dict[str, Any]], summary["findings"])
    type_rows = _count_rows(columns, "semantic_type")
    role_rows = _count_rows(columns, "role")
    missing_rows = sorted(columns, key=lambda item: _float_value(item.get("missing_rate")), reverse=True)[:8]
    target = summary.get("target_profile")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Analysis Notebook</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #10183f;
      --muted: #53617d;
      --line: #dbe3f3;
      --panel: #ffffff;
      --wash: #f4f9fb;
      --teal: #18b8a6;
      --blue: #3867f3;
      --violet: #7b5cf0;
      --amber: #f4a62a;
    }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #f8fbff 0%, #eef8f6 100%);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ padding: 28px; display: grid; gap: 18px; }}
    header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: start; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .eyebrow {{ color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,.86); padding: 16px; box-shadow: 0 16px 42px rgba(34, 48, 88, .08); }}
    .metric strong {{ display: block; font-size: 24px; }}
    .metric span, .tiny {{ color: var(--muted); font-size: 12px; }}
    .badge-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{ border: 1px solid var(--line); border-radius: 999px; padding: 6px 9px; background: var(--wash); font-size: 12px; font-weight: 700; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(100px, 180px) 1fr 54px; gap: 10px; align-items: center; margin: 8px 0; }}
    .bar-track {{ height: 9px; border-radius: 999px; background: #e5ecf8; overflow: hidden; }}
    .bar {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--teal), var(--blue)); }}
    .findings {{ display: grid; gap: 10px; }}
    .finding {{ border-left: 4px solid var(--teal); padding: 10px 12px; background: var(--wash); border-radius: 8px; }}
    .finding.high {{ border-color: #d84c6f; }}
    .finding.medium {{ border-color: var(--amber); }}
    code {{ background: #eef3ff; border-radius: 6px; padding: 2px 5px; }}
    footer {{ color: var(--muted); font-size: 12px; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink: #eef4ff; --muted: #aab6d3; --line: #2e3a5b; --panel: #11182f; --wash: #17213a; }}
      body {{ background: #0c1225; }}
      .panel {{ background: rgba(17,24,47,.9); box-shadow: none; }}
      code {{ background: #1e2a48; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Tablex Analysis Notebook</div>
        <h1>{escape(str(summary["title"]))}</h1>
        <p>{escape(str(summary["overview"]))}</p>
      </div>
      <div class="panel">
        <div class="tiny">Notebook artifact</div>
        <code>{escape(notebook_artifact_id)}</code>
      </div>
    </header>
    <section class="grid">
      {_metric_card("Rows", summary["row_count"])}
      {_metric_card("Columns", summary["column_count"])}
      {_metric_card("Missing cells", summary["missing_cell_count"])}
      {_metric_card("Target", summary["target_column"] or "not selected")}
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Semantic mix</h2>
        <div class="badge-row">{_badge_rows(type_rows)}</div>
      </div>
      <div class="panel">
        <h2>Column roles</h2>
        <div class="badge-row">{_badge_rows(role_rows)}</div>
      </div>
    </section>
    <section class="panel">
      <h2>Missingness scan</h2>
      {_missing_rows(missing_rows)}
    </section>
    <section class="panel">
      <h2>Findings and investigation queue</h2>
      <div class="findings">{_finding_rows(findings)}</div>
    </section>
    <section class="panel">
      <h2>Target profile</h2>
      <p>{escape(json.dumps(target, ensure_ascii=False, sort_keys=True) if target else "No target selected. Target can be chosen after data understanding, or generated by aggregation before evaluation design.")}</p>
    </section>
    <section class="panel">
      <h2>Modeling diagnostics cells</h2>
      <p>The generated marimo source includes matplotlib and Plotly cells for profile visualization. It also reserves diagnostics space for feature importance, permutation importance, partial dependence, slice metrics, and prediction analysis once experiment artifacts exist.</p>
    </section>
    <footer>
      Static preview rendered inside the workbench. External dashboards are not required; secrets and connector credentials are not embedded.
    </footer>
  </main>
</body>
</html>"""


def render_notebook_report(notebook: dict[str, Any], notebook_artifact_id: str, html_artifact_id: str) -> str:
    summary = notebook["summary"]
    findings = cast(list[dict[str, Any]], summary["findings"])
    finding_lines = [
        f"- **{item['severity']}**: {item['message']} ({item['next_action']})" for item in findings[:8]
    ] or ["- No findings generated yet."]
    return "\n".join(
        [
            "# Data Understanding Analysis Notebook",
            "",
            str(summary["overview"]),
            "",
            "## Artifacts",
            "",
            f"- Notebook source: `{notebook_artifact_id}`",
            f"- HTML preview: `{html_artifact_id}`",
            "",
            "## Coverage",
            "",
            "- marimo notebook source with pandas, matplotlib, and Plotly cells.",
            "- Static in-product HTML preview for immediate inspection.",
            "- Placeholder diagnostics section for feature importance, permutation importance, partial dependence, and prediction analysis.",
            "- Execution policy keeps credentials out of notebooks and runner context.",
            "",
            "## Findings",
            "",
            *finding_lines,
        ]
    )


def render_model_diagnostics_marimo_notebook(notebook: dict[str, Any]) -> str:
    context_json = json.dumps(notebook, ensure_ascii=False, indent=2, sort_keys=True)
    return f'''# Generated by Tablex. Product name is working-name only.
# Run with: marimo edit model_diagnostics_notebook.py
import marimo

__generated_with = "0.1.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import matplotlib.pyplot as plt
    import plotly.express as px
    return mo, pd, plt, px


@app.cell
def _():
    context = {context_json}
    return (context,)


@app.cell
def _(context, mo):
    summary = context["summary"]
    mo.md(
        f"""
        # Model Diagnostics Notebook

        **Project:** {{context["project_name"]}}<br/>
        **Run:** `{{context["run_id"]}}`<br/>
        **ModelVersion:** `{{context.get("model_version_id") or "not registered"}}`<br/>
        **Primary metric:** {{summary["primary_metric_name"] or "unknown"}} = {{summary["primary_metric_value"]}}

        The harness owns EvaluationSpec, SplitManifest, artifacts, reports, and lineage. This notebook is
        editable analysis context for Codex, Skills, or a human analyst; it is not a fixed AutoML recipe.
        """
    )
    return


@app.cell
def _(context, pd):
    metrics = pd.DataFrame(context["summary"]["metric_rows"])
    features = pd.DataFrame(context["summary"]["feature_family_rows"])
    findings = pd.DataFrame(context["summary"]["findings"])
    prediction_bins = pd.DataFrame(context["summary"]["prediction_summary"].get("score_bins", []))
    return metrics, features, findings, prediction_bins


@app.cell
def _(metrics, mo):
    mo.md("## Metrics")
    mo.ui.table(metrics) if not metrics.empty else mo.md("No metrics are available.")
    return


@app.cell
def _(features, px):
    fig = None
    if not features.empty:
        fig = px.bar(features, x="family", y="count", color="status", title="Feature family inventory")
    fig
    return


@app.cell
def _(prediction_bins, plt):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    if not prediction_bins.empty:
        ax.bar(prediction_bins["bin"], prediction_bins["count"], color="#3867f3")
        ax.set_title("Prediction score bins")
        ax.set_xlabel("Score bin")
        ax.set_ylabel("Rows")
    else:
        ax.text(0.5, 0.5, "No score bins available", ha="center", va="center")
        ax.axis("off")
    fig.tight_layout()
    fig
    return


@app.cell
def _(context, mo):
    diagnostics = context["summary"].get("diagnostics_summary") or {{}}
    mo.md("## Evaluation Diagnostics")
    mo.md(str(diagnostics)) if diagnostics else mo.md("Run diagnostics are not available yet.")
    return


@app.cell
def _(findings, mo):
    mo.md("## Next Analysis Queue")
    mo.ui.table(findings) if not findings.empty else mo.md("No follow-up findings were generated.")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Extension Points

        Future controlled runners should add feature importance, permutation importance, partial dependence,
        calibration, threshold analysis, and prediction-slice drilldowns as separate artifacts. These additions
        must continue to respect EvaluationSpec and SplitManifest.
        """
    )
    return


if __name__ == "__main__":
    app.run()
'''


def render_model_diagnostics_html_preview(notebook: dict[str, Any], notebook_artifact_id: str) -> str:
    summary = notebook["summary"]
    metric_rows = cast(list[dict[str, Any]], summary.get("metric_rows", []))
    feature_rows = cast(list[dict[str, Any]], summary.get("feature_family_rows", []))
    findings = cast(list[dict[str, Any]], summary.get("findings", []))
    prediction_summary = cast(dict[str, Any], summary.get("prediction_summary", {}))
    score_bins = cast(list[dict[str, Any]], prediction_summary.get("score_bins", []))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tablex Model Diagnostics Notebook</title>
  <style>
    :root {{
      color-scheme: light dark;
      --ink: #10183f;
      --muted: #53617d;
      --line: #dbe3f3;
      --wash: #f4f9fb;
      --teal: #18b8a6;
      --blue: #3867f3;
      --violet: #7b5cf0;
      --rose: #d84c6f;
      --amber: #f4a62a;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: radial-gradient(circle at top left, rgba(24,184,166,.16), transparent 34%), linear-gradient(180deg, #f8fbff 0%, #f2f6ff 100%);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ padding: 28px; display: grid; gap: 18px; }}
    header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: start; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    p {{ color: var(--muted); line-height: 1.55; }}
    .eyebrow {{ color: var(--teal); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,.88); padding: 16px; box-shadow: 0 16px 42px rgba(34, 48, 88, .08); }}
    .metric strong {{ display: block; font-size: 23px; }}
    .metric span, .tiny {{ color: var(--muted); font-size: 12px; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(110px, 190px) 1fr 60px; gap: 10px; align-items: center; margin: 8px 0; }}
    .bar-track {{ height: 10px; border-radius: 999px; background: #e5ecf8; overflow: hidden; }}
    .bar {{ height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--teal), var(--blue)); }}
    .finding {{ border-left: 4px solid var(--teal); margin: 10px 0; padding: 10px 12px; background: var(--wash); border-radius: 8px; }}
    .finding.high {{ border-color: var(--rose); }}
    .finding.medium {{ border-color: var(--amber); }}
    code {{ background: #eef3ff; border-radius: 6px; padding: 2px 5px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--line); padding: 8px; }}
    footer {{ color: var(--muted); font-size: 12px; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink: #eef4ff; --muted: #aab6d3; --line: #2e3a5b; --wash: #17213a; }}
      body {{ background: #0c1225; }}
      .panel {{ background: rgba(17,24,47,.9); box-shadow: none; }}
      code {{ background: #1e2a48; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Tablex Model Diagnostics Notebook</div>
        <h1>{escape(str(summary["title"]))}</h1>
        <p>{escape(str(summary["overview"]))}</p>
      </div>
      <div class="panel">
        <div class="tiny">Run</div>
        <code>{escape(str(notebook.get("run_id") or "-"))}</code>
        <div class="tiny">Notebook artifact</div>
        <code>{escape(notebook_artifact_id)}</code>
      </div>
    </header>
    <section class="grid">
      {_metric_card("Primary metric", _format_metric(summary.get("primary_metric_value")))}
      {_metric_card("Metric name", summary.get("primary_metric_name") or "-")}
      {_metric_card("Predictions", prediction_summary.get("row_count", 0))}
      {_metric_card("Validation", summary.get("validation_status") or "not run")}
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Metric snapshot</h2>
        {_html_table(metric_rows, ["metric", "value"])}
      </div>
      <div class="panel">
        <h2>Feature families</h2>
        {_bar_rows(feature_rows, "family", "count")}
      </div>
    </section>
    <section class="panel">
      <h2>Prediction score bins</h2>
      {_bar_rows(score_bins, "bin", "count")}
    </section>
    <section class="panel">
      <h2>Findings and next analysis queue</h2>
      {_finding_rows(findings)}
    </section>
    <section class="panel">
      <h2>Diagnostics coverage</h2>
      <p>{escape(str(summary.get("diagnostics_coverage")))} Feature importance, permutation importance, and partial dependence are explicit extension points for the next controlled runner.</p>
    </section>
    <footer>
      Static preview rendered inside the workbench. It references existing model, prediction, validation, and diagnostics artifacts without external dashboards.
    </footer>
  </main>
</body>
</html>"""


def render_model_diagnostics_report(notebook: dict[str, Any], notebook_artifact_id: str, html_artifact_id: str) -> str:
    summary = notebook["summary"]
    findings = cast(list[dict[str, Any]], summary.get("findings", []))
    finding_lines = [
        f"- **{item['severity']}**: {item['message']} ({item['next_action']})" for item in findings[:10]
    ] or ["- No follow-up findings generated."]
    return "\n".join(
        [
            "# Model Diagnostics Analysis Notebook",
            "",
            str(summary["overview"]),
            "",
            "## Context",
            "",
            f"- Run: `{notebook.get('run_id')}`",
            f"- ModelVersion: `{notebook.get('model_version_id') or '-'}`",
            f"- Primary metric: {summary.get('primary_metric_name') or '-'} = {summary.get('primary_metric_value')}",
            f"- Prediction rows summarized: {summary.get('prediction_summary', {}).get('row_count', 0)}",
            "",
            "## Artifacts",
            "",
            f"- Notebook source: `{notebook_artifact_id}`",
            f"- HTML preview: `{html_artifact_id}`",
            "",
            "## Coverage",
            "",
            "- marimo notebook source with pandas, matplotlib, and Plotly cells.",
            "- In-product static HTML preview for immediate model diagnostic inspection.",
            "- Uses existing prediction, baseline metric, diagnostics, validation, and model package artifacts when available.",
            "- Leaves feature importance, permutation importance, partial dependence, calibration, and threshold analysis as explicit controlled-runner extension points.",
            "",
            "## Findings",
            "",
            *finding_lines,
        ]
    )


def build_model_diagnostics_visualization_spec(notebook: dict[str, Any]) -> dict[str, Any]:
    summary = notebook["summary"]
    prediction_summary = cast(dict[str, Any], summary.get("prediction_summary", {}))
    rows = [
        {
            "label": str(summary.get("primary_metric_name") or "primary metric"),
            "value": _float_value(summary.get("primary_metric_value")),
        },
        {"label": "prediction rows", "value": int(prediction_summary.get("row_count") or 0)},
        {"label": "feature families", "value": len(summary.get("feature_family_rows") or [])},
        {"label": "findings", "value": len(summary.get("findings") or [])},
    ]
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Model Diagnostics Notebook Summary",
        "chart_type": "metric_cards",
        "data": rows,
        "encoding": {"label": "label", "value": "value"},
        "empty_state": "Generate a model diagnostics notebook after a run has metrics or predictions.",
        "source": {
            "notebook_kind": notebook["notebook_kind"],
            "run_id": notebook.get("run_id"),
            "model_version_id": notebook.get("model_version_id"),
        },
    }


def _latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def _require_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def _latest_runs(db: Session, project_id: str, limit: int = 5) -> list[ExperimentRun]:
    return list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project_id)
            .order_by(ExperimentRun.started_at.desc().nullslast(), ExperimentRun.id.desc())
            .limit(limit)
        ).all()
    )


def _model_version_for_run(db: Session, run: ExperimentRun) -> ModelVersion | None:
    if run.model_version_id:
        model_version = db.get(ModelVersion, run.model_version_id)
        if model_version is not None:
            return model_version
    return db.scalar(
        select(ModelVersion)
        .where(ModelVersion.project_id == run.project_id, ModelVersion.experiment_run_id == run.id)
        .order_by(ModelVersion.created_at.desc())
    )


def _read_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _model_diagnostics_source_artifacts(
    db: Session,
    run: ExperimentRun,
    model_version: ModelVersion | None,
) -> dict[str, Artifact | None]:
    model_version_id = model_version.id if model_version else run.model_version_id
    model_package_artifact = db.get(Artifact, model_version.artifact_id) if model_version else None
    return {
        "baseline_metrics": _latest_artifact_for_metadata(db, run.project_id, "baseline_metrics", "run_id", run.id),
        "baseline_report": _latest_artifact_for_metadata(db, run.project_id, "baseline_report", "run_id", run.id),
        "baseline_plan": _latest_artifact_for_metadata(db, run.project_id, "baseline_plan", "run_id", run.id),
        "baseline_strategy_plan": _latest_artifact_for_metadata(
            db, run.project_id, "baseline_strategy_plan", "run_id", run.id
        ),
        "feature_recipe": _latest_artifact_for_metadata(db, run.project_id, "feature_recipe", "run_id", run.id),
        "prediction_output": _latest_artifact_for_metadata(db, run.project_id, "prediction_output", "run_id", run.id),
        "evaluation_diagnostics": _latest_artifact_for_metadata(
            db, run.project_id, "evaluation_diagnostics", "run_id", run.id
        ),
        "evaluation_diagnostics_report": _latest_artifact_for_metadata(
            db, run.project_id, "evaluation_diagnostics_report", "run_id", run.id
        ),
        "run_report": _latest_artifact_for_metadata(db, run.project_id, "run_report", "run_id", run.id),
        "model_package": model_package_artifact,
        "model_validation_metrics": _latest_artifact_for_metadata(
            db, run.project_id, "model_validation_metrics", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
        "model_validation_report": _latest_artifact_for_metadata(
            db, run.project_id, "model_validation_report", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
        "prediction_replay": _latest_artifact_for_metadata(
            db, run.project_id, "prediction_replay", "model_version_id", model_version_id
        )
        if model_version_id
        else None,
    }


def _latest_artifact_for_metadata(
    db: Session,
    project_id: str,
    asset_type: str,
    key: str,
    value: object,
) -> Artifact | None:
    if value is None:
        return None
    artifacts = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
            .order_by(Artifact.created_at.desc())
        ).all()
    )
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get(key) == value:
            return artifact
    return None


def _read_prediction_summary(artifact: Artifact | None, limit_rows: int = 200_000) -> dict[str, Any]:
    if artifact is None:
        return {
            "status": "missing",
            "row_count": 0,
            "target_counts": [],
            "prediction_counts": [],
            "score_bins": [],
            "accuracy": None,
        }
    path = artifact_primary_path(artifact)
    if not path.exists():
        return {"status": "missing_file", "row_count": 0, "artifact_id": artifact.id}
    row_count = 0
    correct_count = 0
    comparable_count = 0
    target_counts: dict[str, int] = {}
    prediction_counts: dict[str, int] = {}
    score_values: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row_count >= limit_rows:
                break
            row_count += 1
            target = str(row.get("target") or "")
            prediction = str(row.get("prediction") or "")
            if target:
                target_counts[target] = target_counts.get(target, 0) + 1
            if prediction:
                prediction_counts[prediction] = prediction_counts.get(prediction, 0) + 1
            if target and prediction:
                comparable_count += 1
                correct_count += int(target == prediction)
            score = _optional_float(row.get("score"))
            if score is not None:
                score_values.append(score)
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "row_count": row_count,
        "truncated_at": limit_rows if row_count >= limit_rows else None,
        "target_counts": _count_dict_rows(target_counts),
        "prediction_counts": _count_dict_rows(prediction_counts),
        "score_summary": _score_summary(score_values),
        "score_bins": _score_bins(score_values),
        "accuracy": correct_count / comparable_count if comparable_count else None,
    }


def _model_diagnostics_summary(
    *,
    project: Project,
    run: ExperimentRun,
    model_version: ModelVersion | None,
    dataset: DatasetSnapshot | None,
    metrics: dict[str, Any],
    diagnostics: dict[str, Any],
    validation: dict[str, Any],
    prediction_summary: dict[str, Any],
    source_artifacts: dict[str, Artifact | None],
) -> dict[str, Any]:
    primary_metric_name = str(metrics.get("primary_metric_name") or model_version.primary_metric_name if model_version else metrics.get("primary_metric_name") or "")
    primary_metric_value = metrics.get("primary_metric_value")
    if primary_metric_value is None and model_version is not None:
        primary_metric_value = model_version.primary_metric_value
    feature_rows = _feature_family_rows(metrics)
    diagnostics_summary = diagnostics.get("summary") if isinstance(diagnostics.get("summary"), dict) else {}
    validation_status = validation.get("validation_status") if validation else None
    artifact_coverage = {
        key: artifact.id for key, artifact in source_artifacts.items() if artifact is not None
    }
    findings = _model_diagnostics_findings(
        metrics=metrics,
        diagnostics=diagnostics,
        validation=validation,
        prediction_summary=prediction_summary,
        model_version=model_version,
    )
    overview = (
        f"Generated model diagnostics notebook for run {run.id}. "
        f"Primary metric is {primary_metric_name or 'unknown'}={_format_metric(primary_metric_value)}; "
        f"prediction rows summarized: {prediction_summary.get('row_count', 0)}."
    )
    return {
        "title": "Model Diagnostics Notebook",
        "overview": overview,
        "project_name": project.name,
        "run_id": run.id,
        "model_version_id": model_version.id if model_version else run.model_version_id,
        "dataset_snapshot_id": dataset.id if dataset else run.dataset_snapshot_id,
        "dataset_shape": {
            "row_count": dataset.row_count if dataset else None,
            "column_count": dataset.column_count if dataset else None,
        },
        "runner_type": run.runner_type,
        "run_status": run.status,
        "model_family": model_version.model_family if model_version else metrics.get("model_family"),
        "model_type": model_version.model_type if model_version else metrics.get("baseline_type"),
        "task_type": model_version.task_type if model_version else project.task_type,
        "target_column": model_version.target_column if model_version else project.target_column,
        "primary_metric_name": primary_metric_name or None,
        "primary_metric_value": _optional_float(primary_metric_value),
        "metric_rows": _metric_rows(metrics, validation),
        "feature_family_rows": feature_rows,
        "prediction_summary": prediction_summary,
        "diagnostics_summary": diagnostics_summary,
        "diagnostics_coverage": _diagnostics_coverage(diagnostics, source_artifacts),
        "validation_status": validation_status,
        "artifact_coverage": artifact_coverage,
        "findings": findings,
    }


def _feature_family_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        ("numeric", metrics.get("numeric_feature_count")),
        ("categorical", metrics.get("categorical_feature_count")),
        ("text", metrics.get("text_feature_count")),
        ("datetime", metrics.get("datetime_feature_count")),
    ]
    output = []
    for family, value in rows:
        count = int(value or 0)
        output.append({"family": family, "count": count, "status": "used" if count else "not_used"})
    return output


def _metric_rows(metrics: dict[str, Any], validation: dict[str, Any]) -> list[dict[str, Any]]:
    preferred_keys = [
        "primary_metric_value",
        "accuracy",
        "roc_auc",
        "average_precision",
        "rmse",
        "mae",
        "r2",
        "model_baseline_attempted",
    ]
    rows = [
        {"metric": key, "value": _metric_cell(metrics.get(key))}
        for key in preferred_keys
        if key in metrics
    ]
    if validation:
        rows.append({"metric": "validation_status", "value": _metric_cell(validation.get("validation_status"))})
        rows.append({"metric": "max_abs_metric_delta", "value": _metric_cell(validation.get("max_abs_metric_delta"))})
    return rows[:14]


def _model_diagnostics_findings(
    *,
    metrics: dict[str, Any],
    diagnostics: dict[str, Any],
    validation: dict[str, Any],
    prediction_summary: dict[str, Any],
    model_version: ModelVersion | None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if model_version is None:
        findings.append(
            {
                "severity": "medium",
                "message": "No ModelVersion is linked to this run.",
                "next_action": "Register or validate a model package before treating the run as reusable.",
            }
        )
    if prediction_summary.get("status") != "available":
        findings.append(
            {
                "severity": "high",
                "message": "Prediction output is unavailable for this run.",
                "next_action": "Persist validation predictions before diagnostics or reporting claims.",
            }
        )
    accuracy = prediction_summary.get("accuracy")
    if isinstance(accuracy, int | float):
        findings.append(
            {
                "severity": "info",
                "message": f"Prediction summary accuracy is {accuracy:.3f} over {prediction_summary.get('row_count', 0)} rows.",
                "next_action": "Compare this with EvaluationSpec primary metric and slice diagnostics.",
            }
        )
    sanity = diagnostics.get("sanity_checks") if isinstance(diagnostics.get("sanity_checks"), dict) else {}
    if sanity:
        if sanity.get("prediction_count_matches_split") is False or sanity.get("all_predictions_joined_to_valid_rows") is False:
            findings.append(
                {
                    "severity": "high",
                    "message": "Evaluation diagnostics found prediction coverage or join issues.",
                    "next_action": "Fix prediction artifact alignment before comparing models.",
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "message": "Evaluation diagnostics sanity checks passed for prediction coverage.",
                    "next_action": "Inspect slice metrics and worst examples for model behavior.",
                }
            )
    else:
        findings.append(
            {
                "severity": "medium",
                "message": "Evaluation diagnostics artifact is not available.",
                "next_action": "Run diagnostics to populate slice metrics, score/error bins, and worst examples.",
            }
        )
    if validation:
        status = str(validation.get("validation_status") or "unknown")
        findings.append(
            {
                "severity": "info" if status == "passed" else "medium",
                "message": f"Model package validation status is {status}.",
                "next_action": "Review metric deltas before relying on the packaged model.",
            }
        )
    else:
        findings.append(
            {
                "severity": "medium",
                "message": "Model package replay validation has not been run.",
                "next_action": "Run ModelVersion validation before deployment or benchmark claims.",
            }
        )
    if not any(key in metrics for key in ("feature_importance", "permutation_importance", "partial_dependence")):
        findings.append(
            {
                "severity": "info",
                "message": "Feature importance, permutation importance, and partial dependence are not yet materialized.",
                "next_action": "Ask a controlled runner to add these analyses as artifact-backed notebook cells.",
            }
        )
    return findings


def _diagnostics_coverage(diagnostics: dict[str, Any], source_artifacts: dict[str, Artifact | None]) -> str:
    if not diagnostics:
        return "Evaluation diagnostics are missing."
    coverage = []
    for key in ("summary", "bins", "slice_metrics", "worst_examples", "sanity_checks"):
        value = diagnostics.get(key)
        if isinstance(value, list):
            coverage.append(f"{key}:{len(value)}")
        elif isinstance(value, dict):
            coverage.append(f"{key}:available")
    if source_artifacts.get("model_validation_metrics"):
        coverage.append("model_validation:available")
    return ", ".join(coverage) or "Diagnostics artifact exists but contains no recognized sections."


def _model_source_asset_ids(
    run: ExperimentRun,
    model_version: ModelVersion | None,
    source_artifacts: dict[str, Artifact | None],
) -> list[dict[str, str]]:
    sources = [{"asset_type": "experiment_run", "asset_id": run.id}]
    if model_version:
        sources.append({"asset_type": "model_version", "asset_id": model_version.id})
    for key, artifact in source_artifacts.items():
        if artifact is not None:
            sources.append({"asset_type": "artifact", "asset_id": artifact.id, "role": key})
    return sources


def _profile_summary(
    project: Project,
    dataset: DatasetSnapshot,
    profile: dict[str, Any],
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    raw_columns = profile.get("columns")
    columns = [cast(dict[str, Any], item) for item in raw_columns] if isinstance(raw_columns, list) else []
    compact_columns = [_compact_column(item) for item in columns[:80]]
    target_profile = profile.get("target_profile") if isinstance(profile.get("target_profile"), dict) else None
    findings = _build_findings(profile, quality, diagnostics, runs)
    row_count = int(profile.get("row_count") or dataset.row_count or 0)
    column_count = int(profile.get("column_count") or dataset.column_count or len(compact_columns))
    target_column = str(profile.get("target_column") or project.target_column or "") or None
    profile_mode = str(profile.get("profile_mode") or "unknown")
    overview = (
        f"Generated analysis notebook for {row_count:,} rows and {column_count:,} columns. "
        f"Profile mode is {profile_mode}; target is {target_column or 'not selected'}."
    )
    return {
        "title": "Data Understanding Notebook",
        "overview": overview,
        "row_count": row_count,
        "column_count": column_count,
        "missing_cell_count": int(profile.get("missing_cell_count") or 0),
        "target_column": target_column,
        "target_profile": target_profile,
        "profile_mode": profile_mode,
        "profile_boundary": profile.get("deferred_deep_profile") if isinstance(profile.get("deferred_deep_profile"), dict) else {},
        "columns": compact_columns,
        "sample_rows": profile.get("sample_rows") if isinstance(profile.get("sample_rows"), list) else [],
        "time_candidates": profile.get("time_candidates") if isinstance(profile.get("time_candidates"), list) else [],
        "group_candidates": profile.get("group_candidates") if isinstance(profile.get("group_candidates"), list) else [],
        "leakage_suspects": profile.get("leakage_suspects") if isinstance(profile.get("leakage_suspects"), list) else [],
        "findings": findings,
        "recent_runs": [_run_summary(run) for run in runs],
    }


def _compact_column(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(column.get("name") or column.get("column_name") or ""),
        "physical_type": str(column.get("physical_type") or "unknown"),
        "semantic_type": str(column.get("semantic_type") or "unknown"),
        "role": str(column.get("role") or "feature"),
        "missing_rate": _float_value(column.get("missing_rate")),
        "missing_count": int(column.get("missing_count") or 0),
        "unique_count": int(column.get("unique_count") or 0),
        "stats_scope": str(column.get("stats_scope") or "unknown"),
        "is_leakage_suspect": bool(column.get("is_leakage_suspect")),
    }


def _build_findings(
    profile: dict[str, Any],
    quality: dict[str, Any],
    diagnostics: dict[str, Any],
    runs: list[ExperimentRun],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    boundary = profile.get("deferred_deep_profile")
    if isinstance(boundary, dict) and boundary.get("recommended"):
        findings.append(
            {
                "severity": "medium",
                "message": "Column statistics are sample-backed; deep profiling should be scheduled before final evaluation decisions.",
                "next_action": "Run a bounded-to-deep profile follow-up or keep the sampling boundary visible in reports.",
            }
        )
    leakage = profile.get("leakage_suspects")
    if isinstance(leakage, list) and leakage:
        findings.append(
            {
                "severity": "high",
                "message": f"Potential leakage columns detected: {', '.join(str(item) for item in leakage[:6])}.",
                "next_action": "Confirm prediction-time availability and exclude until confirmed.",
            }
        )
    if not profile.get("target_column"):
        findings.append(
            {
                "severity": "medium",
                "message": "No target column is selected; this is acceptable during data understanding.",
                "next_action": "Use profile evidence or aggregation design before creating EvaluationSpec.",
            }
        )
    gate = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    if gate:
        findings.append(
            {
                "severity": str(gate.get("severity") or "info"),
                "message": f"Latest data quality gate reports {gate.get('severity', 'unknown')} severity.",
                "next_action": "Review quality gate evidence before feature design.",
            }
        )
    if diagnostics:
        findings.append(
            {
                "severity": "info",
                "message": "Evaluation diagnostics artifact is available for prediction/error analysis cells.",
                "next_action": "Extend the notebook with diagnostic plots from the artifact.",
            }
        )
    if runs:
        findings.append(
            {
                "severity": "info",
                "message": f"{len(runs)} recent experiment run(s) are available for model comparison cells.",
                "next_action": "Add feature importance, permutation importance, PDP, and slice analysis once model artifacts expose them.",
            }
        )
    return findings or [
        {
            "severity": "info",
            "message": "Profile artifact is available and no high-priority notebook finding was generated.",
            "next_action": "Inspect column profile and decide the next evaluation question.",
        }
    ]


def _run_summary(run: ExperimentRun) -> dict[str, Any]:
    metrics = loads_json(run.metrics_json, {})
    return {
        "id": run.id,
        "status": run.status,
        "runner_type": run.runner_type,
        "evaluation_spec_id": run.evaluation_spec_id,
        "model_version_id": run.model_version_id,
        "metrics": metrics,
    }


def _source_asset_ids(
    dataset: DatasetSnapshot,
    profile_artifact: Artifact | None,
    understanding_artifact: Artifact | None,
) -> list[dict[str, str]]:
    sources = [{"asset_type": "dataset_snapshot", "asset_id": dataset.id}]
    if profile_artifact:
        sources.append({"asset_type": "artifact", "asset_id": profile_artifact.id})
    if understanding_artifact:
        sources.append({"asset_type": "artifact", "asset_id": understanding_artifact.id})
    return sources


def _record_lineage(
    db: Session,
    project: Project,
    dataset: DatasetSnapshot,
    source_artifacts: list[Artifact],
    notebook_artifact: Artifact,
    html_artifact: Artifact,
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=notebook_artifact.id,
        relation_type="informs",
    )
    for artifact in source_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in [html_artifact, manifest_artifact, report_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=notebook_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )


def _record_model_notebook_lineage(
    db: Session,
    project: Project,
    run: ExperimentRun,
    model_version: ModelVersion | None,
    source_artifacts: list[Artifact],
    notebook_artifact: Artifact,
    html_artifact: Artifact,
    manifest_artifact: Artifact,
    report: Report,
    report_artifact: Artifact,
    visualization: VisualizationSpec,
    visualization_artifact: Artifact,
) -> None:
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="experiment_run",
        from_asset_id=run.id,
        to_asset_type="artifact",
        to_asset_id=notebook_artifact.id,
        relation_type="diagnoses",
    )
    if model_version is not None:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="model_version",
            from_asset_id=model_version.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in source_artifacts:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=notebook_artifact.id,
            relation_type="informs",
        )
    for artifact in [html_artifact, manifest_artifact, report_artifact, visualization_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=notebook_artifact.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="produces",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="report",
        from_asset_id=report.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="materializes",
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=notebook_artifact.id,
        to_asset_type="visualization_spec",
        to_asset_id=visualization.id,
        relation_type="summarizes",
    )


def _execution_policy() -> dict[str, Any]:
    return {
        "external_dashboard_required": False,
        "external_network_accessed": False,
        "connector_credentials_embedded": False,
        "secrets_embedded": False,
        "notebook_execution": "not_executed_by_generation_endpoint",
        "artifact_capture_required": True,
        "runner_role": "editable_analysis_surface_under_harness_control",
    }


def _count_dict_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"label": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]


def _score_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _score_bins(values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    bins: list[dict[str, Any]] = [
        {"bin": "0.0-0.2", "count": 0},
        {"bin": "0.2-0.4", "count": 0},
        {"bin": "0.4-0.6", "count": 0},
        {"bin": "0.6-0.8", "count": 0},
        {"bin": "0.8-1.0", "count": 0},
    ]
    for value in values:
        index = min(4, max(0, int(value * 5)))
        bins[index]["count"] = int(bins[index]["count"]) + 1
    return bins


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _format_metric(value: object) -> str:
    number = _optional_float(value)
    if number is None:
        return "-"
    return f"{number:.6g}"


def _metric_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int | bool | str):
        return str(value)
    if value is None:
        return "-"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _metric_card(label: str, value: object) -> str:
    return f'<div class="panel metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'


def _html_table(rows: list[dict[str, Any]], keys: list[str]) -> str:
    if not rows:
        return "<p>No rows available.</p>"
    head = "".join(f"<th>{escape(key)}</th>" for key in keys)
    body = []
    for row in rows[:16]:
        cells = "".join(f"<td>{escape(str(row.get(key, '-')))}</td>" for key in keys)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _bar_rows(rows: list[dict[str, Any]], label_key: str, value_key: str) -> str:
    if not rows:
        return "<p>No rows available.</p>"
    values = [_float_value(row.get(value_key)) for row in rows]
    max_value = max(values, default=0.0)
    output = []
    for row, value in zip(rows, values, strict=True):
        width = 0.0 if max_value <= 0 else max(4.0, value / max_value * 100)
        output.append(
            '<div class="bar-row">'
            f'<code>{escape(str(row.get(label_key) or ""))}</code>'
            f'<div class="bar-track"><div class="bar" style="width:{width:.1f}%"></div></div>'
            f"<span>{escape(_format_metric(value))}</span>"
            "</div>"
        )
    return "".join(output)


def _badge_rows(rows: list[tuple[str, int]]) -> str:
    if not rows:
        return '<span class="badge">No data</span>'
    return "".join(f'<span class="badge">{escape(label)}: {count}</span>' for label, count in rows)


def _missing_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No missingness profile is available.</p>"
    output = []
    for row in rows:
        rate = max(0.0, min(1.0, _float_value(row.get("missing_rate"))))
        output.append(
            '<div class="bar-row">'
            f'<code>{escape(str(row.get("name") or ""))}</code>'
            f'<div class="bar-track"><div class="bar" style="width:{rate * 100:.1f}%"></div></div>'
            f"<span>{rate:.1%}</span>"
            "</div>"
        )
    return "".join(output)


def _finding_rows(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "<p>No findings generated yet.</p>"
    output = []
    for item in findings:
        severity = str(item.get("severity") or "info")
        output.append(
            f'<div class="finding {escape(severity)}">'
            f"<strong>{escape(severity.upper())}</strong>"
            f"<p>{escape(str(item.get('message') or ''))}</p>"
            f'<div class="tiny">{escape(str(item.get("next_action") or ""))}</div>'
            "</div>"
        )
    return "".join(output)


def _count_rows(rows: list[dict[str, Any]], field: str) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]


def _float_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
