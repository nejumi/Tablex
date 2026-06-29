from __future__ import annotations

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
    Project,
    Report,
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


@dataclass(frozen=True)
class AnalysisNotebookResult:
    notebook: dict[str, Any]
    report: Report
    notebook_artifact: Artifact
    html_artifact: Artifact
    manifest_artifact: Artifact
    report_artifact: Artifact
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


def _latest_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def _latest_runs(db: Session, project_id: str, limit: int = 5) -> list[ExperimentRun]:
    return list(
        db.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.project_id == project_id)
            .order_by(ExperimentRun.started_at.desc().nullslast(), ExperimentRun.id.desc())
            .limit(limit)
        ).all()
    )


def _read_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


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


def _metric_card(label: str, value: object) -> str:
    return f'<div class="panel metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'


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
