from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    AssumptionEvidenceLink,
    DatasetSnapshot,
    EvaluationSpec,
    Evidence,
    Insight,
    Project,
    Question,
    SemanticCatalog,
    SplitManifest,
)
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    artifact_primary_path,
    create_lineage_edge,
)
from tabular_harness.services.profiler import quote_ident, read_sql
from tabular_harness.services.reporting import persist_visualization_spec

QUALITY_SAMPLE_ROWS = 50_000
QUALITY_FULL_MAX_ROWS = 100_000
QUALITY_FULL_MAX_COLUMNS = 80


@dataclass(frozen=True)
class DataQualityResult:
    gate: dict[str, Any]
    artifact_ids: list[str]
    evidence_ids: list[str]
    assumption_ids: list[str]
    question_ids: list[str]
    insight_id: str


def analyze_dataset_quality(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
) -> DataQualityResult:
    dataset_artifact = require_artifact(db, dataset.artifact_id)
    profile = latest_profile_for_dataset(db, dataset)
    semantic_columns = latest_semantic_columns(db, dataset)
    evaluation_spec = latest_approved_spec(db, project.id)
    split_manifest = latest_split_for_spec(db, evaluation_spec.id) if evaluation_spec else None
    gate = build_data_quality_gate(
        project=project,
        dataset=dataset,
        dataset_artifact=dataset_artifact,
        profile=profile,
        semantic_columns=semantic_columns,
        evaluation_spec=evaluation_spec,
        split_manifest=split_manifest,
    )
    gate_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="data_quality_gate",
        name=f"data_quality_gate_{dataset.id}_{new_id('dqpart')}",
        filename="data_quality_gate.json",
        payload=gate,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "evaluation_spec_id": evaluation_spec.id if evaluation_spec else None,
            "split_manifest_id": split_manifest.id if split_manifest else None,
            "severity": gate["summary"]["severity"],
            "quality_check_scope": gate["profile_boundary"]["quality_check_scope"],
            "profile_mode": gate["profile_boundary"]["profile_mode"],
            "sample_row_count": gate["profile_boundary"]["sample_row_count"],
        },
    )
    report_md = render_data_quality_report(project=project, dataset=dataset, gate=gate)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="data_quality_report",
        name=f"data_quality_report_{dataset.id}_{new_id('dqrpt')}",
        filename="data_quality_report.md",
        text=report_md,
        metadata={"project_id": project.id, "dataset_snapshot_id": dataset.id, "gate_artifact_id": gate_artifact.id},
    )
    visualization_spec = build_quality_visualization_spec(gate)
    visualization, visualization_artifact = persist_visualization_spec(
        db,
        store=store,
        project=project,
        spec=visualization_spec,
        source_artifact_id=gate_artifact.id,
    )
    del visualization

    evidence_ids, assumption_ids, question_ids = materialize_quality_findings(
        db,
        project=project,
        dataset=dataset,
        gate=gate,
        gate_artifact=gate_artifact,
    )
    insight = Insight(
        id=new_id("ins"),
        project_id=project.id,
        insight_type="data_quality_gate",
        title="Data quality gate",
        summary=gate["summary"]["headline"],
        severity="warning" if gate["summary"]["severity"] in {"warning", "blocking"} else "info",
        confidence=0.82,
        status="open",
        source_asset_ids_json=dumps_json(
            [
                {"asset_type": "dataset_snapshot", "asset_id": dataset.id},
                {"asset_type": "artifact", "asset_id": gate_artifact.id},
            ]
        ),
        evidence_ids_json=dumps_json(evidence_ids),
        artifact_id=gate_artifact.id,
        created_by_type="system",
    )
    db.add(insight)
    db.flush()

    for artifact in [gate_artifact, report_artifact, visualization_artifact]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="quality_analyzes",
        )
    if evaluation_spec:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_spec",
            from_asset_id=evaluation_spec.id,
            to_asset_type="artifact",
            to_asset_id=gate_artifact.id,
            relation_type="constrains",
        )
    if split_manifest:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="split_manifest",
            from_asset_id=split_manifest.id,
            to_asset_type="artifact",
            to_asset_id=gate_artifact.id,
            relation_type="checked_by",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="insight",
        from_asset_id=insight.id,
        to_asset_type="artifact",
        to_asset_id=gate_artifact.id,
        relation_type="materializes",
    )
    return DataQualityResult(
        gate=gate,
        artifact_ids=[gate_artifact.id, report_artifact.id, visualization_artifact.id],
        evidence_ids=evidence_ids,
        assumption_ids=assumption_ids,
        question_ids=question_ids,
        insight_id=insight.id,
    )


def build_data_quality_gate(
    *,
    project: Project,
    dataset: DatasetSnapshot,
    dataset_artifact: Artifact,
    profile: dict[str, Any],
    semantic_columns: list[dict[str, Any]],
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.extend(basic_profile_checks(project, dataset, profile, semantic_columns))
    checks.extend(duckdb_dataset_checks(project, dataset_artifact, profile))
    checks.extend(evaluation_quality_checks(evaluation_spec, split_manifest, profile))
    counts = status_counts(checks)
    blockers = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warning"]
    severity = "blocking" if blockers else "warning" if warnings else "pass"
    return {
        "schema_version": "data_quality_gate.v1",
        "id": new_id("dqg"),
        "project_id": project.id,
        "dataset_snapshot_id": dataset.id,
        "summary": {
            "severity": severity,
            "headline": quality_headline(dataset, blockers, warnings),
            "status_counts": counts,
            "risk_score": quality_risk_score(checks),
        },
        "profile_boundary": profile_boundary(profile),
        "checks": checks,
        "quality_gates": {
            "evaluation_ready": not blockers,
            "runner_ready": not blockers and counts.get("warning", 0) <= 4,
            "deployment_ready": False,
            "blockers": [check["title"] for check in blockers],
        },
        "evaluation_guidance": {
            "excluded_columns": sorted(excluded_columns_from_checks(checks)),
            "split_recommendations": split_recommendations(profile, evaluation_spec, split_manifest),
            "required_question_topics": sorted({topic for check in checks for topic in check.get("question_topics", [])}),
        },
        "agent_context_notes": [
            "Treat failed checks as blocking unless explicitly overridden by a harness-tracked answer.",
            "Do not use excluded columns in feature generation or prompts.",
            "Respect EvaluationSpec and SplitManifest; do not repair quality issues by changing them destructively.",
        ],
    }


def basic_profile_checks(
    project: Project,
    dataset: DatasetSnapshot,
    profile: dict[str, Any],
    semantic_columns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    del dataset
    columns = profile_columns(profile)
    checks = [
        make_check(
            "objective_defined",
            "objective",
            "pass" if project.target_column else "review",
            "low" if project.target_column else "medium",
            "Supervised objective column is defined" if project.target_column else "Project objective is not defined yet",
            (
                "Use the configured supervised objective for target-aware evaluation."
                if project.target_column
                else "Package the evidence for Codex to propose the task objective, prediction unit, and evaluation shape."
            ),
            [project.target_column] if project.target_column else [],
            "infer_and_continue",
            ["target_definition"] if not project.target_column else [],
        )
    ]
    column_names = {str(item.get("name")) for item in columns}
    if is_bounded_profile(profile):
        sample_raw = profile.get("profile_sample")
        sample: dict[str, Any] = sample_raw if isinstance(sample_raw, dict) else {}
        deep_raw = profile.get("deferred_deep_profile")
        deep: dict[str, Any] = deep_raw if isinstance(deep_raw, dict) else {}
        checks.append(
            make_check(
                "profile_statistics_sampled",
                "profile",
                "warning",
                "medium",
                "Column statistics are sample-backed",
                (
                    "The EDA profile used bounded_sample mode; missingness, uniqueness, duplicate, and target-proxy "
                    f"quality checks are interpreted with a sample boundary of {sample.get('sample_row_count') or 'unknown'} rows."
                ),
                [],
                "infer_and_continue",
                ["missingness_policy", "duplicate_policy"],
                evidence={
                    "profile_mode": profile.get("profile_mode"),
                    "sample_row_count": sample.get("sample_row_count"),
                    "deferred_column_count": deep.get("deferred_column_count"),
                },
            )
        )
    if project.target_column:
        checks.append(
            make_check(
                "target_exists",
                "target",
                "pass" if project.target_column in column_names else "fail",
                "blocking" if project.target_column not in column_names else "low",
                "Target column exists in dataset" if project.target_column in column_names else "Target column not found",
                "Project target_column must match an uploaded dataset column.",
                [project.target_column],
                "block_until_answered",
                ["target_definition"],
            )
        )
    leakage = [str(item.get("name")) for item in columns if item.get("is_leakage_suspect")]
    checks.append(
        make_check(
            "leakage_name_suspects",
            "leakage",
            "warning" if leakage else "pass",
            "high" if leakage else "low",
            "Potential leakage columns detected by name" if leakage else "No name-based leakage suspects detected",
            "Post-outcome or label-like columns can inflate validation metrics.",
            leakage,
            "exclude_until_confirmed" if leakage else "infer_and_continue",
            ["prediction_time_availability"] if leakage else [],
        )
    )
    high_missing = [str(item.get("name")) for item in columns if float(item.get("missing_rate") or 0.0) >= 0.5]
    moderate_missing = [str(item.get("name")) for item in columns if 0.2 <= float(item.get("missing_rate") or 0.0) < 0.5]
    checks.append(
        make_check(
            "high_missingness",
            "missingness",
            "warning" if high_missing else "pass",
            "medium" if high_missing else "low",
            "High missingness columns detected" if high_missing else "No high missingness columns detected",
            f"Columns with >=50% missingness: {', '.join(high_missing) or 'none'}. Moderate missingness columns: {', '.join(moderate_missing) or 'none'}.",
            high_missing,
            "scenario_compare" if high_missing else "infer_and_continue",
            ["missingness_policy"] if high_missing else [],
        )
    )
    constant = [str(item.get("name")) for item in columns if int(item.get("unique_count") or 0) <= 1]
    checks.append(
        make_check(
            "constant_columns",
            "schema",
            "warning" if constant else "pass",
            "low" if constant else "low",
            "Constant columns detected" if constant else "No constant columns detected",
            "Constant columns carry no predictive signal and can usually be excluded.",
            constant,
            "exclude_until_confirmed" if constant else "infer_and_continue",
            [],
        )
    )
    high_cardinality = [
        str(item.get("column_name"))
        for item in semantic_columns
        if item.get("role") in {"identifier", "group"} or item.get("semantic_type") == "identifier"
    ]
    checks.append(
        make_check(
            "id_high_cardinality_risk",
            "identity",
            "warning" if high_cardinality else "pass",
            "medium" if high_cardinality else "low",
            "Identifier or group-like columns need handling" if high_cardinality else "No identifier/group-like columns detected",
            "Identifiers can create memorization or group leakage if split incorrectly.",
            high_cardinality,
            "scenario_compare" if high_cardinality else "infer_and_continue",
            ["row_semantics", "evaluation_design"] if high_cardinality else [],
        )
    )
    unknown_availability = [
        str(item.get("column_name"))
        for item in semantic_columns
        if item.get("role") == "feature" and item.get("available_at_prediction_time") == "unknown"
    ]
    checks.append(
        make_check(
            "prediction_time_availability_unknown",
            "availability",
            "warning" if unknown_availability else "pass",
            "medium" if unknown_availability else "low",
            "Prediction-time availability is not confirmed" if unknown_availability else "Prediction-time availability has no unknown feature flags",
            "Unknown availability should be tracked as assumptions before deployment decisions.",
            unknown_availability[:25],
            "infer_and_continue" if unknown_availability else "infer_and_continue",
            ["prediction_time_availability"] if unknown_availability else [],
        )
    )
    return checks


def duckdb_dataset_checks(project: Project, dataset_artifact: Artifact, profile: dict[str, Any]) -> list[dict[str, Any]]:
    path = artifact_primary_path(dataset_artifact)
    con = duckdb.connect(database=":memory:")
    dataset_sql = read_sql(path)
    bounded = use_sample_quality_checks(profile)
    row_scope = "sample" if bounded else "full"
    checked_row_count = int(profile.get("row_count") or 0)
    table_ref = dataset_sql
    if bounded:
        sample_limit = quality_sample_limit(profile)
        table_ref = "quality_sample"
        con.execute(f"CREATE TEMP TABLE {table_ref} AS SELECT * FROM {dataset_sql} LIMIT {sample_limit}")
        sample_count = con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()
        checked_row_count = int(sample_count[0]) if sample_count else 0
    checks = []
    duplicate_count = safe_int(
        con.execute(
            f"SELECT COALESCE(SUM(cnt - 1), 0) FROM (SELECT *, COUNT(*) AS cnt FROM {table_ref} GROUP BY ALL HAVING COUNT(*) > 1)"
        ).fetchone()
    )
    checks.append(
        make_check(
            "duplicate_rows",
            "duplicates",
            "warning" if duplicate_count > 0 else "pass",
            "medium" if duplicate_count > 0 else "low",
            "Duplicate rows detected" if duplicate_count > 0 else f"No duplicate rows detected in {row_scope} check",
            (
                f"{duplicate_count} duplicate row copies were found by {row_scope}-row comparison. "
                "Full duplicate detection is deferred for this large dataset."
                if bounded
                else f"{duplicate_count} duplicate row copies were found by full-row comparison."
            ),
            [],
            "scenario_compare" if duplicate_count > 0 else "infer_and_continue",
            ["duplicate_policy"] if duplicate_count > 0 else [],
            evidence={"duplicate_row_count": duplicate_count, "row_scope": row_scope, "checked_row_count": checked_row_count},
        )
    )
    target = project.target_column
    columns = profile_columns(profile)
    exact_match_columns: list[str] = []
    if target and any(item.get("name") == target for item in columns):
        for column in [str(item.get("name")) for item in columns if item.get("name") != target]:
            matched = safe_int(
                con.execute(
                    f"""
                    SELECT SUM(
                      CASE WHEN CAST({quote_ident(column)} AS VARCHAR) = CAST({quote_ident(target)} AS VARCHAR)
                      THEN 1 ELSE 0 END
                    )
                    FROM {table_ref}
                    """
                ).fetchone()
            )
            if checked_row_count and matched / checked_row_count >= 0.98:
                exact_match_columns.append(column)
    checks.append(
        make_check(
            "target_proxy_exact_match",
            "leakage",
            "fail" if exact_match_columns else "pass",
            "blocking" if exact_match_columns else "low",
            "Columns nearly duplicate the target" if exact_match_columns else f"No exact target proxy columns detected in {row_scope} check",
            (
                "A feature that nearly equals the target is a strong leakage candidate. "
                f"This check used {row_scope} scope over {checked_row_count} rows."
            ),
            exact_match_columns,
            "exclude_until_confirmed" if exact_match_columns else "infer_and_continue",
            ["prediction_time_availability"] if exact_match_columns else [],
            evidence={"row_scope": row_scope, "checked_row_count": checked_row_count},
        )
    )
    return checks


def evaluation_quality_checks(
    evaluation_spec: EvaluationSpec | None,
    split_manifest: SplitManifest | None,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    checks = []
    time_candidates = [str(item) for item in profile.get("time_candidates", [])]
    group_candidates = [str(item) for item in profile.get("group_candidates", [])]
    checks.append(
        make_check(
            "evaluation_spec_approved",
            "evaluation",
            "pass" if evaluation_spec else "warning",
            "medium" if not evaluation_spec else "low",
            "Approved EvaluationSpec exists" if evaluation_spec else "Approved EvaluationSpec missing",
            "Quality findings should constrain a primary evaluation design before runner work.",
            [],
            "conservative_default",
            ["evaluation_design"] if not evaluation_spec else [],
        )
    )
    checks.append(
        make_check(
            "split_manifest_available",
            "evaluation",
            "pass" if split_manifest else "warning",
            "medium" if not split_manifest else "low",
            "SplitManifest exists" if split_manifest else "SplitManifest missing",
            "Modeling and diagnostics should use a harness-owned split manifest.",
            [],
            "conservative_default",
            ["evaluation_design"] if not split_manifest else [],
        )
    )
    if evaluation_spec and evaluation_spec.split_type != "time" and time_candidates:
        checks.append(
            make_check(
                "time_structure_not_primary",
                "temporal",
                "warning",
                "medium",
                "Time-like columns exist but primary split is not time-based",
                "Consider scenario-comparing time split or documenting why row-wise split is acceptable.",
                time_candidates,
                "scenario_compare",
                ["evaluation_design", "time_features"],
            )
        )
    if evaluation_spec and evaluation_spec.split_type != "group" and group_candidates:
        checks.append(
            make_check(
                "group_structure_not_primary",
                "group",
                "warning",
                "medium",
                "Group-like columns exist but primary split is not group-based",
                "Consider scenario-comparing group split or documenting row independence.",
                group_candidates,
                "scenario_compare",
                ["row_semantics", "evaluation_design"],
            )
        )
    if split_manifest:
        summary = loads_json(split_manifest.summary_json, {})
        if summary.get("time_order_respected") is False:
            checks.append(
                make_check(
                    "time_order_violation",
                    "temporal",
                    "fail",
                    "blocking",
                    "Time split order is not respected",
                    "Validation should not precede training for forward-looking temporal evaluation.",
                    [str(evaluation_spec.time_column)] if evaluation_spec and evaluation_spec.time_column else [],
                    "block_until_answered",
                    ["evaluation_design"],
                )
            )
        if summary.get("group_leakage_check_passed") is False:
            checks.append(
                make_check(
                    "group_leakage_violation",
                    "group",
                    "fail",
                    "blocking",
                    "Group leakage detected in split",
                    "A group appears in more than one split.",
                    [str(evaluation_spec.group_column)] if evaluation_spec and evaluation_spec.group_column else [],
                    "block_until_answered",
                    ["evaluation_design"],
                )
            )
    return checks


def materialize_quality_findings(
    db: Session,
    *,
    project: Project,
    dataset: DatasetSnapshot,
    gate: dict[str, Any],
    gate_artifact: Artifact,
) -> tuple[list[str], list[str], list[str]]:
    evidence_ids: list[str] = []
    assumption_ids: list[str] = []
    question_ids: list[str] = []
    findings = [check for check in gate["checks"] if check["status"] in {"fail", "warning"}]
    for check in findings[:12]:
        evidence = Evidence(
            id=new_id("ev"),
            project_id=project.id,
            evidence_type="data_quality_check",
            summary=f"{check['title']}: {check['details']}",
            strength="strong" if check["status"] == "fail" else "medium",
            source_artifact_id=gate_artifact.id,
            metadata_json=dumps_json(
                {"check_id": check["check_id"], "category": check["category"], "affected_columns": check["affected_columns"]}
            ),
        )
        db.add(evidence)
        evidence_ids.append(evidence.id)
        if check["risk_level"] in {"high", "blocking", "medium"}:
            assumption = Assumption(
                id=new_id("asm"),
                project_id=project.id,
                topic=str(check["category"]),
                subject_type="dataset_snapshot",
                subject_ref=dataset.id,
                statement=f"{check['title']}; fallback policy is {check['fallback_policy']}.",
                status="adopted" if check["status"] == "fail" else "inferred",
                confidence=0.78 if check["status"] == "fail" else 0.62,
                risk_level=str(check["risk_level"]),
                fallback_policy=str(check["fallback_policy"]),
                requires_user_confirmation=check["status"] == "fail",
                created_by_type="system",
            )
            db.add(assumption)
            db.flush()
            db.add(
                AssumptionEvidenceLink(
                    id=new_id("ael"),
                    assumption_id=assumption.id,
                    evidence_id=evidence.id,
                    effect="supports",
                    weight=1.0,
                )
            )
            assumption_ids.append(assumption.id)
    question_topics = sorted({topic for check in findings for topic in check.get("question_topics", [])})
    question_set_id = new_id("qs")
    for topic in question_topics[:8]:
        question = Question(
            id=new_id("q"),
            project_id=project.id,
            question_set_id=question_set_id,
            topic=topic,
            question=quality_question_text(topic),
            why_it_matters=quality_question_reason(topic),
            default_assumption=quality_question_default(topic),
            impact_if_wrong="Model selection, evaluation trust, or deployment readiness may be overstated.",
            choices_json=dumps_json(["confirm", "reject", "scenario_compare", "unknown"]),
            status="open",
            priority=85 if topic in {"prediction_time_availability", "target_definition"} else 65,
            risk_level="high" if topic in {"prediction_time_availability", "target_definition"} else "medium",
            value_of_answer="very_high" if topic in {"prediction_time_availability", "target_definition"} else "high",
            can_proceed_without_answer=topic != "target_definition",
            fallback_policy="exclude_until_confirmed" if topic == "prediction_time_availability" else "scenario_compare",
            blocks_next_phase=topic == "target_definition",
        )
        db.add(question)
        question_ids.append(question.id)
    return evidence_ids, assumption_ids, question_ids


def render_data_quality_report(*, project: Project, dataset: DatasetSnapshot, gate: dict[str, Any]) -> str:
    boundary_raw = gate.get("profile_boundary")
    boundary: dict[str, Any] = boundary_raw if isinstance(boundary_raw, dict) else {}
    lines = [
        "# Data Quality Gate",
        "",
        f"- Project: {project.name} ({project.id})",
        f"- DatasetSnapshot: {dataset.id}",
        f"- Severity: {gate['summary']['severity']}",
        f"- Risk score: {gate['summary']['risk_score']}",
        f"- Profile mode: {boundary.get('profile_mode', '-')}",
        f"- Quality check scope: {boundary.get('quality_check_scope', '-')}",
        f"- Sample rows: {boundary.get('sample_row_count', '-')}",
        "",
        "## Summary",
        "",
        gate["summary"]["headline"],
        "",
        "## Checks",
        "",
    ]
    for check in gate["checks"]:
        columns = ", ".join(check["affected_columns"]) if check["affected_columns"] else "-"
        lines.append(f"- {check['status']} / {check['risk_level']} / {check['category']}: {check['title']} ({columns})")
    lines.extend(["", "## Evaluation Guidance", ""])
    lines.append(f"- Excluded columns: {gate['evaluation_guidance']['excluded_columns']}")
    lines.append(f"- Split recommendations: {gate['evaluation_guidance']['split_recommendations']}")
    lines.extend(["", "## Agent Context Notes", ""])
    lines.extend([f"- {item}" for item in gate["agent_context_notes"]])
    return "\n".join(lines).strip() + "\n"


def build_quality_visualization_spec(gate: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for check in gate["checks"]:
        counts[str(check["status"])] = counts.get(str(check["status"]), 0) + 1
    return {
        "schema_version": "visualization_spec.v1",
        "title": "Data Quality Gate Status",
        "chart_type": "category_bars",
        "data": [{"label": key, "count": value} for key, value in sorted(counts.items())],
        "encoding": {"x": "label", "y": "count", "color": "label"},
        "empty_state": "Run data quality analysis to populate gate status.",
    }


def make_check(
    check_id: str,
    category: str,
    status: str,
    risk_level: str,
    title: str,
    details: str,
    affected_columns: list[str],
    fallback_policy: str,
    question_topics: list[str],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "category": category,
        "status": status,
        "risk_level": risk_level,
        "title": title,
        "details": details,
        "affected_columns": affected_columns,
        "fallback_policy": fallback_policy,
        "question_topics": question_topics,
        "evidence": evidence or {},
    }


def status_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in checks:
        counts[str(check["status"])] = counts.get(str(check["status"]), 0) + 1
    return counts


def quality_risk_score(checks: list[dict[str, Any]]) -> int:
    weights = {"pass": 0, "info": 1, "warning": 3, "fail": 7}
    return sum(weights.get(str(check["status"]), 0) for check in checks)


def quality_headline(dataset: DatasetSnapshot, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    if blockers:
        return f"DatasetSnapshot {dataset.id} has {len(blockers)} blocking quality checks and {len(warnings)} warnings."
    if warnings:
        return f"DatasetSnapshot {dataset.id} has {len(warnings)} quality warnings; runner work can continue with assumptions."
    return f"DatasetSnapshot {dataset.id} passed MVP quality checks."


def excluded_columns_from_checks(checks: list[dict[str, Any]]) -> set[str]:
    excluded: set[str] = set()
    for check in checks:
        if check["fallback_policy"] == "exclude_until_confirmed":
            excluded.update(str(column) for column in check["affected_columns"])
    return excluded


def profile_columns(profile: dict[str, Any]) -> list[dict[str, Any]]:
    columns = profile.get("columns")
    if not isinstance(columns, list):
        return []
    return [cast(dict[str, Any], item) for item in columns if isinstance(item, dict)]


def is_bounded_profile(profile: dict[str, Any]) -> bool:
    return profile.get("profile_mode") == "bounded_sample" or profile.get("column_stat_scope") == "sample"


def quality_sample_limit(profile: dict[str, Any]) -> int:
    sample = profile.get("profile_sample")
    if isinstance(sample, dict):
        for key in ("sample_row_count", "sample_limit"):
            value = sample.get(key)
            if isinstance(value, int) and value > 0:
                return min(value, QUALITY_SAMPLE_ROWS)
    return QUALITY_SAMPLE_ROWS


def use_sample_quality_checks(profile: dict[str, Any]) -> bool:
    if is_bounded_profile(profile):
        return True
    row_count = int(profile.get("row_count") or 0)
    column_count = int(profile.get("column_count") or 0)
    return row_count > QUALITY_FULL_MAX_ROWS or column_count > QUALITY_FULL_MAX_COLUMNS


def profile_boundary(profile: dict[str, Any]) -> dict[str, Any]:
    sampled = use_sample_quality_checks(profile)
    sample_raw = profile.get("profile_sample")
    sample: dict[str, Any] = sample_raw if isinstance(sample_raw, dict) else {}
    deep_raw = profile.get("deferred_deep_profile")
    deep: dict[str, Any] = deep_raw if isinstance(deep_raw, dict) else {}
    return {
        "profile_mode": profile.get("profile_mode", "unknown"),
        "profile_stat_scope": profile.get("column_stat_scope", "unknown"),
        "quality_check_scope": "sample" if sampled else "full",
        "sample_row_count": sample.get("sample_row_count") if sampled else None,
        "sample_method": sample.get("sample_method") if sampled else None,
        "deep_profile_recommended": bool(deep.get("recommended")) if deep else False,
        "deferred_column_count": deep.get("deferred_column_count") if deep else 0,
    }


def split_recommendations(
    profile: dict[str, Any], evaluation_spec: EvaluationSpec | None, split_manifest: SplitManifest | None
) -> list[str]:
    recommendations = []
    if profile.get("time_candidates"):
        recommendations.append("Scenario-compare time split or document why row-wise split is valid.")
    if profile.get("group_candidates"):
        recommendations.append("Scenario-compare group split or document row independence.")
    if evaluation_spec is None:
        recommendations.append("Approve an EvaluationSpec before accepting runner outputs.")
    if split_manifest is None:
        recommendations.append("Generate a SplitManifest before model runs.")
    return recommendations or ["Current split context is sufficient for MVP iteration."]


def quality_question_text(topic: str) -> str:
    mapping = {
        "prediction_time_availability": "Which flagged columns are available at prediction time?",
        "target_definition": "Is the task objective, prediction unit, and outcome definition correct for this project?",
        "evaluation_design": "Should the primary evaluation change or scenario-compare this quality risk?",
        "row_semantics": "Do repeated entity rows need grouped validation?",
        "time_features": "What timestamp defines prediction time and permitted historical windows?",
        "missingness_policy": "Should high-missingness columns be excluded, imputed, or scenario-compared?",
        "duplicate_policy": "Are duplicate rows expected, and should they be deduplicated before evaluation?",
    }
    return mapping.get(topic, f"How should Tablex handle the {topic} quality finding?")


def quality_question_reason(topic: str) -> str:
    if topic == "prediction_time_availability":
        return "Unavailable or post-outcome fields can leak the target into features."
    if topic == "evaluation_design":
        return "Quality risks should constrain the primary EvaluationSpec or an alternative scenario."
    return "The answer determines whether the harness can proceed by assumption or should block a later decision."


def quality_question_default(topic: str) -> str:
    if topic == "prediction_time_availability":
        return "Exclude flagged columns until confirmed."
    if topic == "target_definition":
        return "Ask Codex to propose an objective and continue only after the proposal is registered as an auditable assumption."
    return "Infer conservatively and continue with a tracked assumption."


def safe_int(row: tuple[Any, ...] | None) -> int:
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def latest_profile_for_dataset(db: Session, dataset: DatasetSnapshot) -> dict[str, Any]:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == dataset.project_id, Artifact.asset_type == "eda_profile")
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        if loads_json(artifact.metadata_json, {}).get("dataset_snapshot_id") == dataset.id:
            return cast(dict[str, Any], json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")))
    return {}


def latest_semantic_columns(db: Session, dataset: DatasetSnapshot) -> list[dict[str, Any]]:
    catalog = db.scalar(
        select(SemanticCatalog)
        .where(SemanticCatalog.dataset_snapshot_id == dataset.id)
        .order_by(SemanticCatalog.created_at.desc())
    )
    if catalog is None:
        return []
    return cast(list[dict[str, Any]], loads_json(catalog.columns_json, []))


def latest_approved_spec(db: Session, project_id: str) -> EvaluationSpec | None:
    return db.scalar(
        select(EvaluationSpec)
        .where(EvaluationSpec.project_id == project_id, EvaluationSpec.status == "approved")
        .order_by(EvaluationSpec.created_at.desc())
    )


def latest_split_for_spec(db: Session, spec_id: str) -> SplitManifest | None:
    return db.scalar(
        select(SplitManifest)
        .where(SplitManifest.evaluation_spec_id == spec_id)
        .order_by(SplitManifest.created_at.desc())
    )


def require_artifact(db: Session, artifact_id: str) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError("Artifact not found")
    return artifact
