from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, cast

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    DatasetSnapshot,
    Evidence,
    Insight,
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
from tabular_harness.services.profiler import quote_ident, read_sql, safe_number
from tabular_harness.services.reporting import persist_visualization_spec

MAX_ANALYZED_COLUMNS = 40
MAX_NUMERIC_COLUMNS = 12
MAX_CATEGORICAL_COLUMNS = 12
MAX_TARGET_RELATIONSHIPS = 14


@dataclass(frozen=True)
class EdaReviewResult:
    review: dict[str, Any]
    report: Report
    bundle_artifact: Artifact
    report_artifact: Artifact
    visualization: VisualizationSpec
    visualization_artifact: Artifact
    figure_artifacts: list[Artifact]
    evidence: Evidence
    insight: Insight
    artifact_ids: list[str]


def create_dataset_eda_review(
    db: Session,
    *,
    store: LocalArtifactStore,
    dataset: DatasetSnapshot,
) -> EdaReviewResult:
    project = db.get(Project, dataset.project_id)
    if project is None:
        raise ValueError("Project not found")
    dataset_artifact = db.get(Artifact, dataset.artifact_id)
    if dataset_artifact is None:
        raise ValueError("Dataset artifact not found")
    dataset_path = artifact_primary_path(dataset_artifact)
    profile_artifact = latest_dataset_artifact(db, project.id, dataset.id, "profile_json")
    quality_artifact = latest_dataset_artifact(db, project.id, dataset.id, "data_quality_gate")
    profile = read_json_artifact(profile_artifact)
    quality = read_json_artifact(quality_artifact)
    review = build_eda_review(
        project=project,
        dataset=dataset,
        dataset_artifact=dataset_artifact,
        dataset_path=dataset_path,
        profile=profile,
        quality=quality,
    )
    suffix = new_id("eda")
    bundle_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="eda_review_bundle",
        name=f"eda_review_bundle_{suffix}",
        filename="eda_review_bundle.json",
        payload=review,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "dataset_artifact_id": dataset_artifact.id,
            "schema_version": review["schema_version"],
            "target_column": review["summary"].get("target_column"),
            "quality_score": review["summary"].get("quality_score"),
        },
    )
    figure_artifacts = [
        store_text_artifact(
            db,
            store,
            project_id=project.id,
            asset_type="eda_review_svg",
            name=f"eda_review_{suffix}_{figure['figure_id']}",
            filename=f"{figure['figure_id']}.svg",
            text=str(figure["svg"]),
            metadata={
                "project_id": project.id,
                "dataset_snapshot_id": dataset.id,
                "eda_review_bundle_artifact_id": bundle_artifact.id,
                "figure_id": figure["figure_id"],
                "content_type": "image/svg+xml",
            },
        )
        for figure in cast(list[dict[str, Any]], review["figures"])
    ]
    report_md = render_eda_review_report(review, bundle_artifact.id)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="eda_review_report",
        name=f"eda_review_report_{suffix}",
        filename="eda_review_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "eda_review_bundle_artifact_id": bundle_artifact.id,
        },
    )
    report = Report(
        id=new_id("rpt"),
        project_id=project.id,
        report_type="eda_review",
        title="Data Review",
        summary=str(review["summary"]["headline"]),
        artifact_id=report_artifact.id,
        source_asset_ids_json=dumps_json(
            [{"asset_type": "dataset_snapshot", "asset_id": dataset.id}, {"asset_type": "artifact", "asset_id": bundle_artifact.id}]
        ),
        status="ready",
        created_by_type="system",
    )
    db.add(report)
    visualization_spec = build_eda_visualization_spec(review)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=visualization_spec,
        source_artifact_id=bundle_artifact.id,
    )
    evidence = Evidence(
        id=new_id("ev"),
        project_id=project.id,
        evidence_type="eda_review",
        summary=str(review["summary"]["headline"]),
        strength="medium",
        source_artifact_id=bundle_artifact.id,
        metadata_json=dumps_json(
            {
                "dataset_snapshot_id": dataset.id,
                "figure_artifact_ids": [artifact.id for artifact in figure_artifacts],
            }
        ),
    )
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="eda_review",
        title="Data review ready",
        summary=str(review["summary"]["headline"]),
        severity=review["summary"].get("severity", "info"),
        confidence=0.72,
        status="open",
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "dataset_snapshot", "asset_id": dataset.id},
                {"asset_type": "artifact", "asset_id": bundle_artifact.id},
            ]
        ),
        evidence_ids_json=dumps_json([evidence.id]),
        artifact_id=bundle_artifact.id,
        created_by_type="system",
    )
    db.add_all([evidence, insight])
    db.flush()
    for artifact in [bundle_artifact, report_artifact, visualization_artifact, *figure_artifacts]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="analyzed_into",
            metadata={"service": "eda_review"},
        )
    artifact_ids = [
        bundle_artifact.id,
        report_artifact.id,
        visualization_artifact.id,
        *[artifact.id for artifact in figure_artifacts],
    ]
    return EdaReviewResult(
        review=review,
        report=report,
        bundle_artifact=bundle_artifact,
        report_artifact=report_artifact,
        visualization=visualization,
        visualization_artifact=visualization_artifact,
        figure_artifacts=figure_artifacts,
        evidence=evidence,
        insight=insight,
        artifact_ids=artifact_ids,
    )


def build_eda_review(
    *,
    project: Project,
    dataset: DatasetSnapshot,
    dataset_artifact: Artifact,
    dataset_path: Path,
    profile: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    con = duckdb.connect(database=":memory:")
    view_name = "eda_dataset"
    con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM {read_sql(dataset_path)}")
    columns = profile_columns(profile)
    if not columns:
        schema_rows = con.execute(f"DESCRIBE SELECT * FROM {view_name}").fetchall()
        columns = [
            {
                "name": str(row[0]),
                "physical_type": str(row[1]),
                "semantic_type": infer_basic_semantic(str(row[0]), str(row[1])),
                "role": "feature",
                "missing_rate": 0.0,
                "unique_count": 0,
            }
            for row in schema_rows
        ]
    row_count = int(dataset.row_count or profile.get("row_count") or table_count(con, view_name))
    target_column = project.target_column or str(profile.get("target_column") or "") or None
    if target_column and target_column not in {str(column["name"]) for column in columns}:
        target_column = None
    numeric_columns = [
        column for column in columns if column.get("role") != "target" and str(column.get("semantic_type")) == "numeric"
    ][:MAX_NUMERIC_COLUMNS]
    categorical_columns = [
        column
        for column in columns
        if column.get("role") != "target" and str(column.get("semantic_type")) in {"categorical", "identifier", "text"}
    ][:MAX_CATEGORICAL_COLUMNS]
    numeric_profiles = [numeric_profile(con, view_name, str(column["name"])) for column in numeric_columns]
    categorical_profiles = [categorical_profile(con, view_name, str(column["name"])) for column in categorical_columns]
    missing_profiles = sorted(
        [
            {
                "column": str(column.get("name")),
                "missing_rate": float(column.get("missing_rate") or 0.0),
                "semantic_type": str(column.get("semantic_type") or "unknown"),
                "role": str(column.get("role") or "feature"),
            }
            for column in columns[:MAX_ANALYZED_COLUMNS]
        ],
        key=lambda item: as_float(item["missing_rate"]) or 0.0,
        reverse=True,
    )[:14]
    target_review = (
        target_relationships(con, view_name, target_column, numeric_columns, categorical_columns)
        if target_column
        else {"status": "target_not_selected", "relationships": [], "target_summary": None}
    )
    correlation_review = numeric_correlations(con, view_name, numeric_columns[:8])
    findings = build_findings(
        row_count=row_count,
        columns=columns,
        target_column=target_column,
        numeric_profiles=numeric_profiles,
        categorical_profiles=categorical_profiles,
        target_review=target_review,
        quality=quality,
    )
    story_cards = build_story_cards(
        row_count=row_count,
        column_count=len(columns),
        target_column=target_column,
        missing_profiles=missing_profiles,
        numeric_profiles=numeric_profiles,
        categorical_profiles=categorical_profiles,
        target_review=target_review,
        findings=findings,
    )
    read_order = build_read_order(target_column=target_column, target_review=target_review, findings=findings)
    playbook = build_playbook(target_column=target_column, target_review=target_review, correlation_review=correlation_review)
    figures = build_figures(
        project=project,
        dataset=dataset,
        missing_profiles=missing_profiles,
        numeric_profiles=numeric_profiles,
        categorical_profiles=categorical_profiles,
        target_review=target_review,
        correlation_review=correlation_review,
    )
    quality_score = eda_quality_score(
        target_column=target_column,
        figure_count=len(figures),
        finding_count=len(findings),
        relationship_count=len(target_review.get("relationships", [])),
    )
    headline = build_headline(target_column=target_column, findings=findings, quality_score=quality_score)
    return {
        "schema_version": "eda_review.v1",
        "generated_at": utc_now().isoformat(),
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "dataset_artifact_id": dataset_artifact.id,
        "summary": {
            "headline": headline,
            "severity": severity_from_findings(findings),
            "quality_score": quality_score,
            "row_count": row_count,
            "column_count": len(columns),
            "target_column": target_column,
            "figure_count": len(figures),
            "finding_count": len(findings),
        },
        "read_this_first": read_order,
        "story_cards": story_cards,
        "playbook": playbook,
        "findings": findings,
        "figures": figures,
        "tables": {
            "missing_profiles": missing_profiles,
            "numeric_profiles": numeric_profiles,
            "categorical_profiles": categorical_profiles,
            "target_review": target_review,
            "correlation_review": correlation_review,
            "quality_context": compact_quality_context(quality),
        },
        "codex_next_prompts": codex_next_prompts(target_column=target_column, target_review=target_review, findings=findings),
        "runner_notes": {
            "execution_mode": "harness_controlled_duckdb_analysis",
            "external_network_accessed": False,
            "secrets_materialized": False,
            "connector_credentials_materialized": False,
            "future_marimo_export": "This bundle is ready for controlled marimo/plotly rendering.",
        },
    }


def latest_dataset_artifact(db: Session, project_id: str, dataset_id: str, asset_type: str) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("dataset_snapshot_id") == dataset_id:
            return artifact
    return latest_project_artifact(db, project_id, asset_type)


def read_json_artifact(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], loads_json(artifact_primary_path(artifact).read_text(encoding="utf-8"), {}))
    except OSError:
        return {}


def table_count(con: duckdb.DuckDBPyConnection, view_name: str) -> int:
    row = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
    return int(row[0] if row else 0)


def profile_columns(profile: dict[str, Any]) -> list[dict[str, Any]]:
    columns = profile.get("columns")
    if not isinstance(columns, list):
        return []
    return [cast(dict[str, Any], item) for item in columns if isinstance(item, dict)]


def infer_basic_semantic(name: str, dtype: str) -> str:
    lower = name.lower()
    if "date" in lower or "time" in lower or dtype.upper() in {"DATE", "TIMESTAMP"}:
        return "datetime"
    if any(token in dtype.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC")):
        return "numeric"
    if "text" in lower or "comment" in lower or "description" in lower:
        return "text"
    return "categorical"


def numeric_profile(con: duckdb.DuckDBPyConnection, view_name: str, column: str) -> dict[str, Any]:
    q = quote_ident(column)
    row = con.execute(
        f"""
        SELECT
          COUNT({q}),
          MIN({q}),
          QUANTILE_CONT({q}, 0.25),
          MEDIAN({q}),
          QUANTILE_CONT({q}, 0.75),
          MAX({q}),
          AVG({q}),
          STDDEV_POP({q})
        FROM {view_name}
        """
    ).fetchone()
    assert row is not None
    non_null = int(row[0] or 0)
    q1 = as_float(row[2])
    q3 = as_float(row[4])
    iqr = q3 - q1 if q1 is not None and q3 is not None else None
    min_value = as_float(row[1])
    max_value = as_float(row[5])
    outlier_hint = False
    if iqr is not None and iqr > 0 and min_value is not None and max_value is not None and q1 is not None and q3 is not None:
        outlier_hint = min_value < q1 - 1.5 * iqr or max_value > q3 + 1.5 * iqr
    return {
        "column": column,
        "non_null_count": non_null,
        "min": safe_number(row[1]),
        "q1": safe_number(row[2]),
        "median": safe_number(row[3]),
        "q3": safe_number(row[4]),
        "max": safe_number(row[5]),
        "mean": safe_number(row[6]),
        "stddev": safe_number(row[7]),
        "iqr": iqr,
        "outlier_hint": outlier_hint,
    }


def categorical_profile(con: duckdb.DuckDBPyConnection, view_name: str, column: str) -> dict[str, Any]:
    q = quote_ident(column)
    rows = con.execute(
        f"""
        SELECT CAST({q} AS VARCHAR) AS value, COUNT(*) AS count
        FROM {view_name}
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 10
        """
    ).fetchall()
    count_row = con.execute(f"SELECT COUNT({q}), COUNT(DISTINCT {q}) FROM {view_name}").fetchone()
    assert count_row is not None
    total = sum(int(row[1] or 0) for row in rows)
    top_values = [{"value": stringify_value(row[0]), "count": int(row[1] or 0)} for row in rows]
    top_count = int(as_float(top_values[0]["count"]) or 0) if top_values else 0
    top_share = top_count / total if total and top_values else None
    return {
        "column": column,
        "non_null_count": int(count_row[0] or 0),
        "unique_count": int(count_row[1] or 0),
        "top_share": top_share,
        "top_values": top_values,
    }


def target_relationships(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    target_column: str,
    numeric_columns: list[dict[str, Any]],
    categorical_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    target_q = quote_ident(target_column)
    target_summary = categorical_profile(con, view_name, target_column)
    target_unique = int(target_summary["unique_count"])
    relationships: list[dict[str, Any]] = []
    binary_numeric = target_unique <= 20 and is_numeric_target(con, view_name, target_column)
    if binary_numeric:
        for column in numeric_columns[:MAX_TARGET_RELATIONSHIPS]:
            name = str(column["name"])
            q = quote_ident(name)
            rows = con.execute(
                f"""
                SELECT CAST({target_q} AS VARCHAR) AS target_value, AVG({q}) AS mean_value, COUNT({q}) AS count
                FROM {view_name}
                WHERE {target_q} IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                LIMIT 20
                """
            ).fetchall()
            means = [value for row in rows if (value := as_float(row[1])) is not None]
            spread = max(means) - min(means) if len(means) >= 2 else 0.0
            relationships.append(
                {
                    "column": name,
                    "kind": "numeric_by_target",
                    "signal_strength": spread,
                    "summary": f"Mean {name} varies by {spread:.4g} across target values.",
                    "groups": [
                        {"target_value": stringify_value(row[0]), "mean": safe_number(row[1]), "count": int(row[2] or 0)}
                        for row in rows
                    ],
                }
            )
    for column in categorical_columns[:MAX_TARGET_RELATIONSHIPS]:
        name = str(column["name"])
        q = quote_ident(name)
        rows = con.execute(
            f"""
            SELECT CAST({q} AS VARCHAR) AS value, AVG(CAST({target_q} AS DOUBLE)) AS target_mean, COUNT(*) AS count
            FROM {view_name}
            WHERE {target_q} IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 2
            ORDER BY count DESC
            LIMIT 12
            """
        ).fetchall()
        means = [value for row in rows if (value := as_float(row[1])) is not None]
        if not means:
            continue
        spread = max(means) - min(means) if len(means) >= 2 else 0.0
        relationships.append(
            {
                "column": name,
                "kind": "category_target_rate",
                "signal_strength": spread,
                "summary": f"Target mean differs by {spread:.4g} across frequent {name} values.",
                "groups": [
                    {"value": stringify_value(row[0]), "target_mean": safe_number(row[1]), "count": int(row[2] or 0)}
                    for row in rows
                ],
            }
        )
    relationships.sort(key=lambda item: abs(float(item.get("signal_strength") or 0.0)), reverse=True)
    return {
        "status": "available",
        "target_summary": target_summary,
        "relationships": relationships[:MAX_TARGET_RELATIONSHIPS],
    }


def is_numeric_target(con: duckdb.DuckDBPyConnection, view_name: str, target_column: str) -> bool:
    try:
        con.execute(f"SELECT AVG(CAST({quote_ident(target_column)} AS DOUBLE)) FROM {view_name}").fetchone()
    except duckdb.Error:
        return False
    return True


def numeric_correlations(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    numeric_columns: list[dict[str, Any]],
) -> dict[str, Any]:
    names = [str(column["name"]) for column in numeric_columns]
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            try:
                row = con.execute(
                    f"SELECT CORR({quote_ident(left)}, {quote_ident(right)}) FROM {view_name}"
                ).fetchone()
            except duckdb.Error:
                continue
            value = as_float(row[0]) if row else None
            if value is None or math.isnan(value):
                continue
            pairs.append({"left": left, "right": right, "correlation": value, "abs_correlation": abs(value)})
    pairs.sort(key=lambda item: float(item["abs_correlation"]), reverse=True)
    return {"status": "available" if pairs else "not_enough_numeric_columns", "top_pairs": pairs[:12]}


def build_findings(
    *,
    row_count: int,
    columns: list[dict[str, Any]],
    target_column: str | None,
    numeric_profiles: list[dict[str, Any]],
    categorical_profiles: list[dict[str, Any]],
    target_review: dict[str, Any],
    quality: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not target_column:
        findings.append(
            {
                "severity": "high",
                "title": "Target is not selected",
                "message": "EDA can describe the table, but target-aware modeling review is blocked.",
                "next_action": "Ask the user to select a target or define an aggregated target after understanding the data.",
            }
        )
    missing_columns = [column for column in columns if float(column.get("missing_rate") or 0.0) >= 0.3]
    if missing_columns:
        findings.append(
            {
                "severity": "medium",
                "title": "High-missingness columns need a feature policy",
                "message": f"{len(missing_columns)} column(s) have at least 30% missing values.",
                "next_action": "Separate meaningful missingness indicators from columns that should be excluded or imputed conservatively.",
            }
        )
    outlier_columns = [profile["column"] for profile in numeric_profiles if profile.get("outlier_hint")]
    if outlier_columns:
        findings.append(
            {
                "severity": "medium",
                "title": "Numeric tails may affect baseline behavior",
                "message": f"Outlier hints detected in {', '.join(outlier_columns[:5])}.",
                "next_action": "Use robust preprocessing or inspect target relationship before clipping.",
            }
        )
    high_cardinality = [profile for profile in categorical_profiles if int(profile.get("unique_count") or 0) > min(100, row_count * 0.5)]
    if high_cardinality:
        findings.append(
            {
                "severity": "medium",
                "title": "High-cardinality categoricals require deliberate encoding",
                "message": f"{len(high_cardinality)} categorical/text/id-like column(s) have high cardinality.",
                "next_action": "Prefer leakage-aware target encoding only inside folds, hashing, text featurization, or exclusion for identifiers.",
            }
        )
    relationships = cast(list[dict[str, Any]], target_review.get("relationships", []))
    if relationships:
        top = relationships[0]
        findings.append(
            {
                "severity": "info",
                "title": "Target relationship candidate found",
                "message": str(top.get("summary") or f"{top.get('column')} has the strongest current target signal."),
                "next_action": "Ask Codex to validate this relationship against leakage and split design before using it as a feature strategy.",
            }
        )
    quality_summary = quality.get("summary") if isinstance(quality.get("summary"), dict) else {}
    if quality_summary:
        findings.append(
            {
                "severity": str(quality_summary.get("severity") or "info"),
                "title": "Quality gate context exists",
                "message": str(quality_summary.get("headline") or "Data quality gate results are available."),
                "next_action": "Resolve high-risk quality findings before treating EDA signals as modeling-ready.",
            }
        )
    return findings or [
        {
            "severity": "info",
            "title": "No major EDA blockers found",
            "message": "The dataset has enough basic structure for evaluation design and first baseline planning.",
            "next_action": "Proceed to target-aware split design and a flexible baseline strategy.",
        }
    ]


def build_story_cards(
    *,
    row_count: int,
    column_count: int,
    target_column: str | None,
    missing_profiles: list[dict[str, Any]],
    numeric_profiles: list[dict[str, Any]],
    categorical_profiles: list[dict[str, Any]],
    target_review: dict[str, Any],
    findings: list[dict[str, str]],
) -> list[dict[str, str]]:
    top_missing = missing_profiles[0] if missing_profiles else None
    top_relationship = next(iter(cast(list[dict[str, Any]], target_review.get("relationships", []))), None)
    return [
        {
            "title": "Table shape",
            "status": "ready",
            "signal": f"{row_count:,} rows x {column_count:,} columns",
            "why_read": "Sets the scale for profiling, split strategy, and whether sample-scoped evidence is enough.",
        },
        {
            "title": "Target status",
            "status": "ready" if target_column else "blocked",
            "signal": target_column or "No target selected",
            "why_read": "Target choice changes every downstream chart, feature tactic, and evaluation design.",
        },
        {
            "title": "Missingness pressure",
            "status": "review" if top_missing and top_missing["missing_rate"] > 0 else "quiet",
            "signal": f"{top_missing['column']} {top_missing['missing_rate']:.1%}" if top_missing else "No missing profile",
            "why_read": "Missingness can be signal, collection bias, or a reason to defer a feature.",
        },
        {
            "title": "Feature families",
            "status": "ready",
            "signal": f"{len(numeric_profiles)} numeric, {len(categorical_profiles)} categorical/text reviewed",
            "why_read": "A good baseline should adapt encoding and diagnostics to the actual feature mix.",
        },
        {
            "title": "Strongest target signal",
            "status": "review" if top_relationship else "pending",
            "signal": str(top_relationship.get("summary")) if top_relationship else "Need target-aware analysis",
            "why_read": "Target relationships are useful only after leakage and split compatibility checks.",
        },
        {
            "title": "Attention queue",
            "status": "review",
            "signal": f"{len(findings)} finding(s)",
            "why_read": "The goal is to reduce the user's next decision to a small number of meaningful issues.",
        },
    ]


def build_read_order(*, target_column: str | None, target_review: dict[str, Any], findings: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "title": "Start with the verdict",
            "why": "Read the headline and findings first; do not scan raw tables looking for meaning.",
            "artifact_hint": "Summary + Findings",
        },
        {
            "title": "Check target status",
            "why": "A target selected after data understanding is valid, but target-aware evidence must be regenerated.",
            "artifact_hint": target_column or "No target selected yet",
        },
        {
            "title": "Inspect the strongest visual signal",
            "why": "Use figures to choose the next question, not to decorate the report.",
            "artifact_hint": "Missingness, target relationship, feature-family, and correlation figures.",
        },
        {
            "title": "Turn the top finding into one Codex task",
            "why": "The next action should be narrow and evidence-backed.",
            "artifact_hint": findings[0]["next_action"] if findings else "No finding queued.",
        },
    ]


def build_playbook(
    *,
    target_column: str | None,
    target_review: dict[str, Any],
    correlation_review: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "stage": "1. Orient",
            "reader_question": "What are rows, columns, target status, and the first risks?",
            "current_evidence": "Shape, missingness, feature families, quality context.",
            "codex_followup": "Ask Codex to explain row semantics and evaluation risk if unclear.",
        },
        {
            "stage": "2. Target-aware scan",
            "reader_question": "Which variables appear related to the target, and could that be leakage?",
            "current_evidence": f"{len(target_review.get('relationships', []))} relationship candidate(s)." if target_column else "No target selected.",
            "codex_followup": "Ask Codex to validate top relationships against availability and split design.",
        },
        {
            "stage": "3. Feature strategy",
            "reader_question": "Which feature families need numeric, categorical, text, time, or relational tactics?",
            "current_evidence": "Numeric summaries, categorical top values, cardinality and missingness.",
            "codex_followup": "Ask Codex for a flexible baseline plan based on observed feature mix, not a fixed recipe.",
        },
        {
            "stage": "4. Dependence and split risk",
            "reader_question": "Do correlations, IDs, groups, or time columns suggest validation leakage?",
            "current_evidence": f"{len(correlation_review.get('top_pairs', []))} numeric correlation pair(s).",
            "codex_followup": "Ask Codex to compare random, stratified, time, and group scenarios.",
        },
    ]


def build_figures(
    *,
    project: Project,
    dataset: DatasetSnapshot,
    missing_profiles: list[dict[str, Any]],
    numeric_profiles: list[dict[str, Any]],
    categorical_profiles: list[dict[str, Any]],
    target_review: dict[str, Any],
    correlation_review: dict[str, Any],
) -> list[dict[str, Any]]:
    relationships = cast(list[dict[str, Any]], target_review.get("relationships", []))
    target_rows: list[dict[str, Any]] = []
    if relationships:
        top = relationships[0]
        if top.get("kind") == "category_target_rate":
            target_rows = [
                {"label": str(row.get("value") or ""), "value": float(row.get("target_mean") or 0.0)}
                for row in cast(list[dict[str, Any]], top.get("groups", []))
            ]
        else:
            target_rows = [
                {"label": str(row.get("target_value") or ""), "value": float(row.get("mean") or 0.0)}
                for row in cast(list[dict[str, Any]], top.get("groups", []))
            ]
    return [
        {
            "figure_id": "missingness_top_columns",
            "title": "Missingness Top Columns",
            "description": "Columns with the highest observed missing rate.",
            "svg": svg_bar_chart(
                title="Missingness top columns",
                rows=[
                    {"label": str(row["column"]), "value": float(row["missing_rate"])}
                    for row in missing_profiles
                    if float(row["missing_rate"]) > 0
                ][:12],
                value_format="percent",
                empty_message="No missingness pressure in the reviewed columns.",
            ),
        },
        {
            "figure_id": "numeric_iqr_ranges",
            "title": "Numeric IQR Ranges",
            "description": "Median and interquartile spread for reviewed numeric columns.",
            "svg": svg_range_chart(
                title="Numeric IQR ranges",
                rows=[
                    {
                        "label": str(row["column"]),
                        "low": float(row.get("q1") or 0.0),
                        "mid": float(row.get("median") or 0.0),
                        "high": float(row.get("q3") or 0.0),
                    }
                    for row in numeric_profiles
                    if row.get("q1") is not None and row.get("q3") is not None
                ][:10],
                empty_message="No numeric columns were available for IQR review.",
            ),
        },
        {
            "figure_id": "categorical_cardinality",
            "title": "Categorical Cardinality",
            "description": "Unique counts for categorical/text/id-like columns.",
            "svg": svg_bar_chart(
                title="Categorical cardinality",
                rows=[
                    {"label": str(row["column"]), "value": int(row.get("unique_count") or 0)}
                    for row in categorical_profiles
                ][:12],
                value_format="integer",
                empty_message="No categorical/text columns were reviewed.",
            ),
        },
        {
            "figure_id": "top_target_relationship",
            "title": "Top Target Relationship",
            "description": "The strongest simple target relationship found in this review.",
            "svg": svg_bar_chart(
                title="Top target relationship",
                rows=target_rows,
                value_format="number",
                empty_message="No target relationship is available. Select a target or regenerate after target definition.",
            ),
        },
        {
            "figure_id": "numeric_correlation_pairs",
            "title": "Numeric Correlation Pairs",
            "description": "Largest absolute numeric correlations, useful for redundancy and leakage review.",
            "svg": svg_bar_chart(
                title="Numeric correlation pairs",
                rows=[
                    {
                        "label": f"{row['left']} x {row['right']}",
                        "value": float(row["abs_correlation"]),
                    }
                    for row in cast(list[dict[str, Any]], correlation_review.get("top_pairs", []))
                ][:10],
                value_format="number",
                empty_message="Not enough numeric correlation evidence.",
            ),
        },
        {
            "figure_id": "eda_review_scope",
            "title": "EDA Review Scope",
            "description": "Scope and execution boundary for the controlled review.",
            "svg": svg_message_chart(
                title="EDA review scope",
                message="DuckDB analysis rendered inside Tablex; no external network or credentials.",
                subtitle=f"Project {project.name} | Dataset {dataset.id}",
            ),
        },
    ]


def eda_quality_score(*, target_column: str | None, figure_count: int, finding_count: int, relationship_count: int) -> int:
    score = 30
    score += 20 if target_column else 0
    score += min(25, figure_count * 4)
    score += min(15, finding_count * 3)
    score += min(10, relationship_count * 2)
    return min(100, score)


def build_headline(*, target_column: str | None, findings: list[dict[str, str]], quality_score: int) -> str:
    high_count = sum(1 for item in findings if item["severity"] == "high")
    if not target_column:
        return "Data review is useful for understanding structure, but target-aware modeling remains blocked."
    if high_count:
        return f"Data review found {high_count} high-risk issue(s) to resolve before trusting target-aware modeling."
    if quality_score >= 75:
        return "Data review is ready for evaluation design and a flexible baseline plan."
    return "Data review is partially ready; inspect findings before modeling."


def severity_from_findings(findings: list[dict[str, str]]) -> str:
    if any(item["severity"] == "high" for item in findings):
        return "warning"
    if any(item["severity"] == "medium" for item in findings):
        return "info"
    return "success"


def compact_quality_context(quality: dict[str, Any]) -> dict[str, Any]:
    if not quality:
        return {"status": "missing"}
    return {
        "status": "available",
        "summary": quality.get("summary", {}),
        "finding_count": len(quality.get("findings", [])) if isinstance(quality.get("findings"), list) else None,
    }


def codex_next_prompts(
    *,
    target_column: str | None,
    target_review: dict[str, Any],
    findings: list[dict[str, str]],
) -> list[str]:
    prompts = [
        "Explain the top EDA finding and propose one concrete next harness action.",
        "Design an evaluation scenario comparison that respects row semantics, time, group, and leakage risk.",
    ]
    if not target_column:
        prompts.insert(0, "Help define the prediction target after data understanding; do not assume it from project creation.")
    if target_review.get("relationships"):
        prompts.append("Validate the strongest target relationship for leakage and prediction-time availability.")
    if findings:
        prompts.append(f"Turn this finding into an AgentTaskContract: {findings[0]['next_action']}")
    prompts.append("Propose a flexible baseline strategy from observed feature families, including text/time/categorical handling when present.")
    return prompts


def build_eda_visualization_spec(review: dict[str, Any]) -> dict[str, Any]:
    summary = cast(dict[str, Any], review["summary"])
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Data Review Summary",
        "chart_type": "metric_cards",
        "data": [
            {"label": "quality score", "value": int(summary.get("quality_score") or 0)},
            {"label": "figures", "value": int(summary.get("figure_count") or 0)},
            {"label": "findings", "value": int(summary.get("finding_count") or 0)},
            {"label": "rows", "value": int(summary.get("row_count") or 0)},
        ],
        "encoding": {"label": "label", "value": "value"},
        "source": {
            "dataset_snapshot_id": review["dataset_snapshot_id"],
            "target_column": summary.get("target_column"),
        },
    }


def render_eda_review_report(review: dict[str, Any], bundle_artifact_id: str) -> str:
    summary = cast(dict[str, Any], review["summary"])
    findings = cast(list[dict[str, str]], review["findings"])
    prompts = cast(list[str], review["codex_next_prompts"])
    return "\n".join(
        [
            "# Data Review",
            "",
            str(summary["headline"]),
            "",
            "## Scope",
            "",
            f"- DatasetSnapshot: `{review['dataset_snapshot_id']}`",
            f"- Bundle artifact: `{bundle_artifact_id}`",
            f"- Target: `{summary.get('target_column') or '-'}`",
            f"- Quality score: `{summary.get('quality_score')}`",
            "",
            "## Findings",
            "",
            *[f"- **{item['severity']}** {item['title']}: {item['message']} Next: {item['next_action']}" for item in findings],
            "",
            "## Ask Codex Next",
            "",
            *[f"- {item}" for item in prompts],
        ]
    )


def svg_bar_chart(
    *,
    title: str,
    rows: list[dict[str, Any]],
    value_format: str,
    empty_message: str,
) -> str:
    width = 920
    row_height = 34
    top = 74
    left = 260
    right = 80
    chart_width = width - left - right
    normalized = [
        (str(row.get("label") or ""), max(0.0, float(row.get("value") or 0.0)))
        for row in rows
        if str(row.get("label") or "")
    ][:14]
    height = max(230, top + max(1, len(normalized)) * row_height + 42)
    max_value = max((value for _, value in normalized), default=0.0)
    body: list[str] = []
    if not normalized or max_value <= 0:
        body.append(f'<text x="{left}" y="{top + 38}" fill="#52617d" font-size="18">{escape(empty_message)}</text>')
    else:
        for index, (label, value) in enumerate(normalized):
            y = top + index * row_height
            bar_width = max(4.0, value / max_value * chart_width)
            body.extend(
                [
                    f'<text x="24" y="{y + 21}" fill="#20304f" font-size="15">{escape(label[:38])}</text>',
                    f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="22" rx="6" fill="url(#bar)"/>',
                    f'<text x="{min(left + bar_width + 8, width - 70):.1f}" y="{y + 17}" fill="#52617d" font-size="13">{escape(format_number(value, value_format))}</text>',
                ]
            )
    return svg_shell(title, width, height, "\n".join(body))


def svg_range_chart(*, title: str, rows: list[dict[str, Any]], empty_message: str) -> str:
    width = 920
    top = 74
    left = 260
    right = 80
    row_height = 36
    numeric_rows = rows[:10]
    height = max(230, top + max(1, len(numeric_rows)) * row_height + 42)
    lows = [as_float(row.get("low")) or 0.0 for row in numeric_rows]
    highs = [as_float(row.get("high")) or 0.0 for row in numeric_rows]
    min_value = min(lows, default=0.0)
    max_value = max(highs, default=0.0)
    span = max_value - min_value
    body: list[str] = []
    if not numeric_rows or span == 0:
        body.append(f'<text x="{left}" y="{top + 38}" fill="#52617d" font-size="18">{escape(empty_message)}</text>')
    else:
        for index, row in enumerate(numeric_rows):
            y = top + index * row_height
            low = as_float(row.get("low")) or 0.0
            mid = as_float(row.get("mid")) or 0.0
            high = as_float(row.get("high")) or 0.0
            x1 = left + (low - min_value) / span * (width - left - right)
            x2 = left + (high - min_value) / span * (width - left - right)
            xm = left + (mid - min_value) / span * (width - left - right)
            body.extend(
                [
                    f'<text x="24" y="{y + 22}" fill="#20304f" font-size="15">{escape(str(row["label"])[:38])}</text>',
                    f'<line x1="{x1:.1f}" x2="{x2:.1f}" y1="{y + 12}" y2="{y + 12}" stroke="#18b8a6" stroke-width="10" stroke-linecap="round"/>',
                    f'<circle cx="{xm:.1f}" cy="{y + 12}" r="6" fill="#3867f3"/>',
                    f'<text x="{x2 + 8:.1f}" y="{y + 17}" fill="#52617d" font-size="12">{escape(format_number(mid, "number"))}</text>',
                ]
            )
    return svg_shell(title, width, height, "\n".join(body))


def svg_message_chart(*, title: str, message: str, subtitle: str) -> str:
    body = (
        f'<text x="42" y="108" fill="#20304f" font-size="22">{escape(message)}</text>'
        f'<text x="42" y="146" fill="#52617d" font-size="14">{escape(subtitle)}</text>'
    )
    return svg_shell(title, 920, 220, body)


def svg_shell(title: str, width: int, height: int, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop stop-color="#f8fbff"/>
      <stop offset="1" stop-color="#eef8f6"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" x2="1">
      <stop stop-color="#18b8a6"/>
      <stop offset="1" stop-color="#3867f3"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="url(#bg)"/>
  <text x="24" y="42" fill="#10183f" font-size="24" font-weight="700">{escape(title)}</text>
  {body}
</svg>'''


def as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        output = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    if math.isnan(output) or math.isinf(output):
        return None
    return output


def stringify_value(value: object) -> str:
    if value is None:
        return "null"
    return str(value)


def format_value(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def format_number(value: float, value_format: str) -> str:
    if value_format == "percent":
        return f"{value:.1%}"
    if value_format == "integer":
        return f"{int(round(value)):,}"
    return f"{value:.4g}"
