from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json, loads_json
from tabular_harness.models.entities import (
    Artifact,
    Assumption,
    DatasetSnapshot,
    EvaluationCandidate,
    EvaluationSpec,
    Project,
    Question,
    SplitManifest,
)
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    StoredFile,
    artifact_primary_path,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.profiler import read_sql


def create_default_evaluation_candidates(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
) -> list[EvaluationCandidate]:
    existing = db.scalars(
        select(EvaluationCandidate).where(EvaluationCandidate.dataset_snapshot_id == dataset.id)
    ).all()
    if existing:
        return list(existing)

    profile = load_profile_for_dataset(db, dataset)
    target_column = project.target_column
    target_profile = profile.get("target_profile") or {}
    task_type = project.task_type or infer_task_type(target_profile)
    primary_metric = recommend_primary_metric(task_type, target_profile)
    secondary_metrics = recommend_secondary_metrics(task_type)
    leakage_suspects = profile.get("leakage_suspects", [])
    time_candidates = profile.get("time_candidates", [])
    group_candidates = profile.get("group_candidates", [])
    stratify_column = (
        target_column
        if target_column and task_type in {"binary_classification", "multiclass_classification"}
        else None
    )

    primary_split = "stratified" if stratify_column else "random"
    candidates = [
        EvaluationCandidate(
            id=new_id("ec"),
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            name="Primary conservative split",
            scenario_id="primary",
            split_type=primary_split,
            primary_metric=primary_metric,
            secondary_metrics_json=dumps_json(secondary_metrics),
            stratify_column=stratify_column,
            excluded_columns_json=dumps_json(leakage_suspects),
            assumption_ids_json="[]",
            rationale_md=(
                "Primary candidate keeps the first run simple while excluding columns flagged "
                "as leakage suspects. Stratification is used when the target appears categorical."
            ),
            confidence=0.72,
            risk_level="medium",
            status="primary_candidate",
        )
    ]
    candidates.append(
        EvaluationCandidate(
            id=new_id("ec"),
            project_id=project.id,
            dataset_snapshot_id=dataset.id,
            name="Reference random split",
            scenario_id="reference_random",
            split_type="random",
            primary_metric=primary_metric,
            secondary_metrics_json=dumps_json(secondary_metrics),
            excluded_columns_json=dumps_json(leakage_suspects),
            assumption_ids_json="[]",
            rationale_md="Reference candidate for comparison. It should not be treated as primary when time or group structure matters.",
            confidence=0.5,
            risk_level="medium",
            status="alternative",
        )
    )
    if time_candidates:
        candidates.append(
            EvaluationCandidate(
                id=new_id("ec"),
                project_id=project.id,
                dataset_snapshot_id=dataset.id,
                name="Time-aware candidate",
                scenario_id="time_scenario",
                split_type="time",
                primary_metric=primary_metric,
                secondary_metrics_json=dumps_json(secondary_metrics),
                time_column=time_candidates[0],
                excluded_columns_json=dumps_json(leakage_suspects),
                assumption_ids_json="[]",
                rationale_md="Time split candidate for forward-looking validation. Use when the time column reflects prediction chronology and future information must be kept out of train.",
                confidence=0.56,
                risk_level="medium",
                status="alternative",
            )
        )
    if group_candidates:
        candidates.append(
            EvaluationCandidate(
                id=new_id("ec"),
                project_id=project.id,
                dataset_snapshot_id=dataset.id,
                name="Group-aware candidate",
                scenario_id="group_scenario",
                split_type="group",
                primary_metric=primary_metric,
                secondary_metrics_json=dumps_json(secondary_metrics),
                group_column=group_candidates[0],
                excluded_columns_json=dumps_json(leakage_suspects),
                assumption_ids_json="[]",
                rationale_md="Group split candidate that keeps all rows for the same group on one side of the split. Use when repeated entities could leak across train and validation.",
                confidence=0.56,
                risk_level="medium",
                status="alternative",
            )
        )

    for candidate in candidates:
        db.add(candidate)
    db.flush()
    write_candidates_artifact(db, store, project.id, candidates, dataset.id)
    return candidates


def promote_candidate_to_spec(db: Session, *, store: LocalArtifactStore, candidate: EvaluationCandidate) -> EvaluationSpec:
    existing = db.scalar(
        select(EvaluationSpec).where(EvaluationSpec.source_evaluation_candidate_id == candidate.id)
    )
    if existing:
        return existing
    spec = EvaluationSpec(
        id=new_id("eval"),
        project_id=candidate.project_id,
        dataset_snapshot_id=candidate.dataset_snapshot_id,
        source_evaluation_candidate_id=candidate.id,
        name=f"EvaluationSpec from {candidate.name}",
        split_type=candidate.split_type,
        primary_metric=candidate.primary_metric,
        secondary_metrics_json=candidate.secondary_metrics_json,
        time_column=candidate.time_column,
        group_column=candidate.group_column,
        stratify_column=candidate.stratify_column,
        excluded_columns_json=candidate.excluded_columns_json,
        assumption_ids_json=candidate.assumption_ids_json,
        rationale_md=candidate.rationale_md,
        risk_level=candidate.risk_level,
        status="draft",
    )
    candidate.status = "promoted_to_spec"
    db.add(spec)
    db.flush()
    artifact = write_spec_artifact(db, store, spec)
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="evaluation_candidate",
        from_asset_id=candidate.id,
        to_asset_type="evaluation_spec",
        to_asset_id=spec.id,
        relation_type="promoted_from",
    )
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="evaluation_spec",
        from_asset_id=spec.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="produces",
    )
    return spec


def approve_spec(spec: EvaluationSpec) -> None:
    if spec.status == "deprecated":
        raise ValueError("Deprecated EvaluationSpec cannot be approved")
    spec.status = "approved"


def generate_split_manifest(
    db: Session,
    *,
    store: LocalArtifactStore,
    spec: EvaluationSpec,
    train_fraction: float = 0.8,
    seed: int = 42,
) -> SplitManifest:
    if spec.status != "approved":
        raise ValueError("EvaluationSpec must be approved before generating a split manifest")
    if spec.split_type not in {"random", "stratified", "time", "group"}:
        raise ValueError("Split generation supports random, stratified, time, and group split types")
    dataset = db.get(DatasetSnapshot, spec.dataset_snapshot_id)
    if dataset is None:
        raise ValueError("DatasetSnapshot not found")
    source_artifact = db.get(Artifact, dataset.artifact_id)
    if source_artifact is None:
        raise ValueError("Dataset artifact not found")
    source_path = artifact_primary_path(source_artifact)
    version = next_artifact_version(db, spec.project_id, "split_manifest", "split_manifest")
    artifact_dir = store.artifact_dir("local-org", spec.project_id, "split_manifest", "split_manifest", version)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    split_path = artifact_dir / "split_manifest.parquet"
    query = split_query(spec, source_path, train_fraction, seed)
    con = duckdb.connect(database=":memory:")
    con.execute(f"COPY ({query}) TO {sql_literal(str(split_path))} (FORMAT PARQUET)")
    counts = split_counts(con, split_path)
    stored_hash = split_path.read_bytes()
    import hashlib

    file_sha = hashlib.sha256(stored_hash).hexdigest()
    summary = {
        "split_type": spec.split_type,
        "train_fraction": train_fraction,
        "seed": seed,
        "counts": {str(key): int(value) for key, value in counts.items()},
        "stratify_column": spec.stratify_column,
        "time_column": spec.time_column,
        "group_column": spec.group_column,
    }
    summary.update(split_diagnostics(con, split_path, spec))
    store.write_manifest(
        artifact_dir,
        [StoredFile(path=split_path, sha256=file_sha, size_bytes=split_path.stat().st_size)],
        {"project_id": spec.project_id, "evaluation_spec_id": spec.id, "summary": summary},
    )
    manifest = json.loads((artifact_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    artifact = register_artifact(
        db,
        project_id=spec.project_id,
        asset_type="split_manifest",
        name="split_manifest",
        uri=str(artifact_dir),
        content_hash=manifest["content_hash"],
        size_bytes=split_path.stat().st_size,
        metadata={
            "primary_path": str(split_path),
            "project_id": spec.project_id,
            "evaluation_spec_id": spec.id,
            "summary": summary,
        },
        version=version,
    )
    split = SplitManifest(
        id=new_id("split"),
        project_id=spec.project_id,
        evaluation_spec_id=spec.id,
        artifact_id=artifact.id,
        train_count=int(counts.get("train", 0)),
        valid_count=int(counts.get("valid", 0)),
        test_count=None,
        summary_json=dumps_json(summary),
    )
    db.add(split)
    db.flush()
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="evaluation_spec",
        from_asset_id=spec.id,
        to_asset_type="split_manifest",
        to_asset_id=split.id,
        relation_type="produces",
    )
    create_lineage_edge(
        db,
        project_id=spec.project_id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="split_manifest",
        to_asset_id=split.id,
        relation_type="uses",
    )
    return split


def create_evaluation_scenario_comparison(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    dataset: DatasetSnapshot,
    candidates: list[EvaluationCandidate],
) -> Artifact:
    profile = load_profile_for_dataset(db, dataset)
    quality_artifact = latest_project_artifact(db, project.id, "data_quality_gate", dataset_id=dataset.id)
    relational_artifact = latest_project_artifact(db, project.id, "relational_catalog", dataset_id=dataset.id)
    open_questions = list(
        db.scalars(
            select(Question)
            .where(Question.project_id == project.id, Question.status == "open")
            .order_by(Question.priority.desc(), Question.created_at)
            .limit(12)
        ).all()
    )
    risky_assumptions = list(
        db.scalars(
            select(Assumption)
            .where(
                Assumption.project_id == project.id,
                Assumption.risk_level.in_(["high", "blocking", "deployment_blocking"]),
            )
            .order_by(Assumption.updated_at.desc())
            .limit(12)
        ).all()
    )
    quality_context = artifact_context(quality_artifact)
    relational_context = artifact_context(relational_artifact)
    comparisons = [
        compare_evaluation_candidate(
            candidate,
            profile=profile,
            quality_context=quality_context,
            relational_context=relational_context,
            open_questions=open_questions,
            risky_assumptions=risky_assumptions,
        )
        for candidate in candidates
    ]
    recommended = recommended_candidate(comparisons)
    recommended_candidate_id = str(recommended.get("candidate_id")) if recommended else None
    recommended_split_type = str(recommended.get("split_type")) if recommended else None
    recommendation = str(recommended.get("recommendation")) if recommended else "no_candidate"
    payload: dict[str, Any] = {
        "schema_version": "evaluation_scenario_comparison.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
        },
        "dataset": {
            "dataset_snapshot_id": dataset.id,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "source_type": dataset.source_type,
            "source_ref": dataset.source_ref,
        },
        "context": {
            "target_profile": profile.get("target_profile"),
            "time_candidates": profile.get("time_candidates", []),
            "group_candidates": profile.get("group_candidates", []),
            "leakage_suspects": profile.get("leakage_suspects", []),
            "quality_gate": quality_context,
            "relational_catalog": relational_context,
            "open_questions": [question_context(question) for question in open_questions],
            "risky_assumptions": [assumption_context(assumption) for assumption in risky_assumptions],
        },
        "candidate_comparisons": comparisons,
        "decision_support": {
            "recommended_candidate_id": recommended_candidate_id,
            "recommended_split_type": recommended_split_type,
            "recommendation": recommendation,
            "note": "Use this comparison before promoting a candidate. It does not mutate EvaluationSpec.",
        },
        "risk_register": comparison_risk_register(profile, quality_context, relational_context, open_questions),
    }
    version = next_artifact_version(db, project.id, "evaluation_scenario_comparison", "evaluation_scenario_comparison")
    artifact_dir, stored, content_hash = store.store_json(
        org_id="local-org",
        project_id=project.id,
        asset_type="evaluation_scenario_comparison",
        name="evaluation_scenario_comparison",
        version=version,
        filename="evaluation_scenario_comparison.json",
        payload=payload,
        metadata={
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "candidate_count": len(candidates),
            "recommended_candidate_id": recommended_candidate_id,
        },
    )
    artifact = register_artifact(
        db,
        project_id=project.id,
        asset_type="evaluation_scenario_comparison",
        name="evaluation_scenario_comparison",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "primary_path": str(stored.path),
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "candidate_count": len(candidates),
            "recommended_candidate_id": recommended_candidate_id,
        },
        version=version,
    )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset.id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="evaluates_scenarios",
    )
    for candidate in candidates[:20]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="evaluation_candidate",
            from_asset_id=candidate.id,
            to_asset_type="artifact",
            to_asset_id=artifact.id,
            relation_type="compared_in",
        )
    return artifact


def compare_evaluation_candidate(
    candidate: EvaluationCandidate,
    *,
    profile: dict[str, Any],
    quality_context: dict[str, Any],
    relational_context: dict[str, Any],
    open_questions: list[Question],
    risky_assumptions: list[Assumption],
) -> dict[str, Any]:
    blockers: list[str] = []
    strengths: list[str] = []
    risks: list[str] = []
    time_candidates = [str(item) for item in profile.get("time_candidates", [])]
    group_candidates = [str(item) for item in profile.get("group_candidates", [])]
    leakage_suspects = [str(item) for item in profile.get("leakage_suspects", [])]
    if candidate.split_type == "time":
        if candidate.time_column:
            strengths.append(f"Uses time column `{candidate.time_column}` for forward-looking validation.")
        else:
            blockers.append("time split candidate has no time_column")
    if candidate.split_type == "group":
        if candidate.group_column:
            strengths.append(f"Keeps group `{candidate.group_column}` on one side of the split.")
        else:
            blockers.append("group split candidate has no group_column")
    if candidate.split_type in {"random", "stratified"} and time_candidates:
        risks.append("Randomized split may overstate performance because time candidates exist.")
    if candidate.split_type != "group" and group_candidates:
        risks.append("Group leakage is possible because repeated entity/group candidates exist.")
    if candidate.split_type == "stratified" and candidate.stratify_column:
        strengths.append(f"Stratifies by `{candidate.stratify_column}` for target distribution sanity.")
    if leakage_suspects:
        excluded = set(loads_json(candidate.excluded_columns_json, []))
        missed = sorted(set(leakage_suspects) - excluded)
        if missed:
            risks.append(f"Leakage-suspect columns are not excluded: {', '.join(missed[:5])}.")
        else:
            strengths.append("Excludes current leakage-suspect columns.")
    if context_metadata_value(quality_context, "severity") in {"warning", "fail"}:
        risks.append("DataQualityGate has non-pass severity; review quality artifact before adoption.")
    if context_metadata_value(relational_context, "table_count", 0) and candidate.split_type != "group":
        risks.append("Relational tables exist; entity-level leakage should be checked before adoption.")
    if open_questions:
        risks.append(f"{len(open_questions)} open questions remain; proceed via assumptions if unanswered.")
    if risky_assumptions:
        risks.append(f"{len(risky_assumptions)} high-risk assumptions remain active.")
    score = candidate.confidence * 100
    score -= 20 * len(blockers)
    score -= 7 * min(len(risks), 5)
    score += 5 * len(strengths)
    recommendation = "prefer" if not blockers and candidate.status == "primary_candidate" else "alternative"
    if blockers:
        recommendation = "reject_until_fixed"
    return {
        "candidate_id": candidate.id,
        "name": candidate.name,
        "scenario_id": candidate.scenario_id,
        "split_type": candidate.split_type,
        "status": candidate.status,
        "primary_metric": candidate.primary_metric,
        "risk_level": candidate.risk_level,
        "confidence": candidate.confidence,
        "score": round(score, 3),
        "recommendation": recommendation,
        "blockers": blockers,
        "strengths": strengths,
        "risks": risks,
        "feasibility": "blocked" if blockers else ("needs_review" if risks else "ready"),
        "candidate": candidate_to_dict(candidate),
    }


def recommended_candidate(comparisons: list[dict[str, Any]]) -> dict[str, Any] | None:
    viable = [item for item in comparisons if item["feasibility"] != "blocked"]
    if not viable:
        return None
    return max(viable, key=lambda item: (item["recommendation"] == "prefer", item["score"]))


def comparison_risk_register(
    profile: dict[str, Any],
    quality_context: dict[str, Any],
    relational_context: dict[str, Any],
    open_questions: list[Question],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if profile.get("time_candidates"):
        risks.append(
            {
                "topic": "temporal_validation",
                "risk_level": "medium",
                "mitigation": "Prefer time split if the candidate time column is prediction chronology.",
            }
        )
    if profile.get("group_candidates"):
        risks.append(
            {
                "topic": "group_leakage",
                "risk_level": "medium",
                "mitigation": "Compare group split when repeated entities can cross train/validation.",
            }
        )
    if quality_context.get("status") == "available":
        risks.append(
            {
                "topic": "quality_gate",
                "risk_level": "medium",
                "artifact_id": quality_context.get("artifact_id"),
                "mitigation": "Review DataQualityGate leakage and readiness notes before approval.",
            }
        )
    if context_metadata_value(relational_context, "table_count", 0):
        risks.append(
            {
                "topic": "relational_context",
                "risk_level": "medium",
                "artifact_id": relational_context.get("artifact_id"),
                "mitigation": "Check entity and time availability before joining supporting tables.",
            }
        )
    if open_questions:
        risks.append(
            {
                "topic": "unanswered_questions",
                "risk_level": "medium",
                "count": len(open_questions),
                "mitigation": "Proceed with explicit assumptions or answer high-value questions before approval.",
            }
        )
    return risks


def latest_project_artifact(
    db: Session, project_id: str, asset_type: str, *, dataset_id: str | None = None
) -> Artifact | None:
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
        .order_by(Artifact.created_at.desc())
    ).all()
    if dataset_id is None:
        return artifacts[0] if artifacts else None
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("dataset_snapshot_id") == dataset_id:
            return artifact
    return artifacts[0] if artifacts else None


def artifact_context(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": loads_json(artifact.metadata_json, {}),
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def context_metadata_value(context: dict[str, Any], key: str, default: Any = None) -> Any:
    metadata = context.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return default


def question_context(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "topic": question.topic,
        "question": question.question,
        "risk_level": question.risk_level,
        "priority": question.priority,
        "fallback_policy": question.fallback_policy,
        "can_proceed_without_answer": question.can_proceed_without_answer,
    }


def assumption_context(assumption: Assumption) -> dict[str, Any]:
    return {
        "id": assumption.id,
        "topic": assumption.topic,
        "statement": assumption.statement,
        "risk_level": assumption.risk_level,
        "confidence": assumption.confidence,
        "status": assumption.status,
        "fallback_policy": assumption.fallback_policy,
    }


def split_query(spec: EvaluationSpec, source_path: Path, train_fraction: float, seed: int) -> str:
    dataset_sql = read_sql(source_path)
    if spec.split_type == "random":
        return f"""
        WITH base AS (
          SELECT row_number() OVER () - 1 AS row_index FROM {dataset_sql}
        )
        SELECT
          row_index,
          CASE WHEN hash(row_index + {seed}) % 1000000 < {int(train_fraction * 1000000)}
               THEN 'train' ELSE 'valid' END AS split
        FROM base
        """
    if spec.split_type == "time":
        return specialized_split_query(spec, source_path, train_fraction, seed)
    if spec.split_type == "group":
        return specialized_split_query(spec, source_path, train_fraction, seed)
    if spec.split_type != "stratified":
        raise ValueError(f"Unsupported split_type: {spec.split_type}")
    if not spec.stratify_column:
        raise ValueError("stratified split requires stratify_column")
    target = quote_ident(spec.stratify_column)
    return f"""
    WITH base AS (
      SELECT row_number() OVER () - 1 AS row_index, CAST({target} AS VARCHAR) AS stratify_value
      FROM {dataset_sql}
    ),
    ranked AS (
      SELECT
        row_index,
        stratify_value,
        row_number() OVER (PARTITION BY stratify_value ORDER BY hash(row_index + {seed})) AS rn,
        COUNT(*) OVER (PARTITION BY stratify_value) AS n
      FROM base
    )
    SELECT
      row_index,
      CASE WHEN rn <= n * {train_fraction} THEN 'train' ELSE 'valid' END AS split,
      stratify_value
    FROM ranked
    """


def specialized_split_query(
    spec: EvaluationSpec, source_path: Path, train_fraction: float, seed: int
) -> str:
    dataset_sql = read_sql(source_path)
    if spec.split_type == "time":
        if not spec.time_column:
            raise ValueError("time split requires time_column")
        time_column = quote_ident(spec.time_column)
        train_percent = int(train_fraction * 1000000)
        return f"""
        WITH base AS (
          SELECT
            row_number() OVER () - 1 AS row_index,
            TRY_CAST({time_column} AS TIMESTAMP) AS time_value
          FROM {dataset_sql}
        ),
        valid_time AS (
          SELECT * FROM base WHERE time_value IS NOT NULL
        ),
        missing_time AS (
          SELECT * FROM base WHERE time_value IS NULL
        ),
        ranked AS (
          SELECT
            row_index,
            time_value,
            row_number() OVER (ORDER BY time_value, row_index) AS rn,
            COUNT(*) OVER () AS n
          FROM valid_time
        ),
        assigned_valid_time AS (
          SELECT
            row_index,
            CASE WHEN rn <= n * {train_fraction} THEN 'train' ELSE 'valid' END AS split,
            time_value
          FROM ranked
        ),
        assigned_missing_time AS (
          SELECT
            row_index,
            CASE WHEN hash(row_index + {seed}) % 1000000 < {train_percent}
                 THEN 'train' ELSE 'valid' END AS split,
            time_value
          FROM missing_time
        )
        SELECT row_index, split, time_value
        FROM assigned_valid_time
        UNION ALL
        SELECT row_index, split, time_value
        FROM assigned_missing_time
        """
    if spec.split_type == "group":
        if not spec.group_column:
            raise ValueError("group split requires group_column")
        group_column = quote_ident(spec.group_column)
        return f"""
        WITH base AS (
          SELECT
            row_number() OVER () - 1 AS row_index,
            COALESCE(CAST({group_column} AS VARCHAR), '__missing_group__') AS group_value
          FROM {dataset_sql}
        ),
        ranked_groups AS (
          SELECT
            group_value,
            row_number() OVER (ORDER BY hash(group_value || ':' || CAST({seed} AS VARCHAR))) AS rn,
            COUNT(*) OVER () AS n
          FROM (SELECT DISTINCT group_value FROM base)
        ),
        assigned_groups AS (
          SELECT
            group_value,
            CASE WHEN rn <= n * {train_fraction} THEN 'train' ELSE 'valid' END AS split
          FROM ranked_groups
        )
        SELECT base.row_index, assigned_groups.split, base.group_value
        FROM base
        JOIN assigned_groups USING (group_value)
        """
    raise ValueError(f"Unsupported split_type: {spec.split_type}")


def split_counts(con: duckdb.DuckDBPyConnection, split_path: Path) -> dict[str, int]:
    counts = dict(
        con.execute(
            f"""
            SELECT split, COUNT(*)
            FROM read_parquet({sql_literal(str(split_path))})
            GROUP BY split
            """
        ).fetchall()
    )
    return {str(key): int(value) for key, value in counts.items()}


def split_diagnostics(
    con: duckdb.DuckDBPyConnection, split_path: Path, spec: EvaluationSpec
) -> dict[str, Any]:
    if spec.split_type == "time":
        rows = con.execute(
            f"""
            SELECT
              split,
              MIN(time_value) AS min_time,
              MAX(time_value) AS max_time,
              SUM(CASE WHEN time_value IS NULL THEN 1 ELSE 0 END) AS null_time_count
            FROM read_parquet({sql_literal(str(split_path))})
            GROUP BY split
            """
        ).fetchall()
        ranges: dict[str, dict[str, Any]] = {
            str(split): {
                "min_time": value_to_iso(min_time),
                "max_time": value_to_iso(max_time),
                "null_time_count": int(null_time_count or 0),
            }
            for split, min_time, max_time, null_time_count in rows
        }
        train_max = string_or_none(ranges.get("train", {}).get("max_time"))
        valid_min = string_or_none(ranges.get("valid", {}).get("min_time"))
        return {
            "time_ranges": ranges,
            "time_order_respected": train_max is None or valid_min is None or train_max <= valid_min,
        }
    if spec.split_type == "group":
        overlap_row = con.execute(
            f"""
            WITH membership AS (
              SELECT group_value, COUNT(DISTINCT split) AS split_count
              FROM read_parquet({sql_literal(str(split_path))})
              GROUP BY group_value
            )
            SELECT COUNT(*)
            FROM membership
            WHERE split_count > 1
            """
        ).fetchone()
        overlap_count = int(overlap_row[0]) if overlap_row is not None else 0
        groups = dict(
            con.execute(
                f"""
                SELECT split, COUNT(DISTINCT group_value)
                FROM read_parquet({sql_literal(str(split_path))})
                GROUP BY split
                """
            ).fetchall()
        )
        return {
            "group_counts": {str(key): int(value) for key, value in groups.items()},
            "group_overlap_count": overlap_count,
            "group_leakage_check_passed": overlap_count == 0,
        }
    return {}


def value_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def load_profile_for_dataset(db: Session, dataset: DatasetSnapshot) -> dict[str, Any]:
    artifacts = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == dataset.project_id,
            Artifact.asset_type == "eda_profile",
        )
        .order_by(Artifact.created_at.desc())
    ).all()
    for artifact in artifacts:
        metadata = loads_json(artifact.metadata_json, {})
        if metadata.get("dataset_snapshot_id") == dataset.id:
            return cast(
                dict[str, Any],
                json.loads(artifact_primary_path(artifact).read_text(encoding="utf-8")),
            )
    return {}


def write_candidates_artifact(
    db: Session,
    store: LocalArtifactStore,
    project_id: str,
    candidates: list[EvaluationCandidate],
    dataset_snapshot_id: str,
) -> None:
    payload = [candidate_to_dict(candidate) for candidate in candidates]
    version = next_artifact_version(db, project_id, "evaluation_candidate", "evaluation_candidates")
    artifact_dir, stored, content_hash = store.store_json(
        org_id="local-org",
        project_id=project_id,
        asset_type="evaluation_candidate",
        name="evaluation_candidates",
        version=version,
        filename="evaluation_candidates.json",
        payload=payload,
        metadata={"project_id": project_id, "dataset_snapshot_id": dataset_snapshot_id},
    )
    artifact = register_artifact(
        db,
        project_id=project_id,
        asset_type="evaluation_candidate",
        name="evaluation_candidates",
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={
            "primary_path": str(stored.path),
            "project_id": project_id,
            "dataset_snapshot_id": dataset_snapshot_id,
        },
        version=version,
    )
    create_lineage_edge(
        db,
        project_id=project_id,
        from_asset_type="dataset_snapshot",
        from_asset_id=dataset_snapshot_id,
        to_asset_type="artifact",
        to_asset_id=artifact.id,
        relation_type="produces",
    )


def write_spec_artifact(db: Session, store: LocalArtifactStore, spec: EvaluationSpec) -> Artifact:
    payload = spec_to_dict(spec)
    version = next_artifact_version(db, spec.project_id, "evaluation_spec", spec.id)
    artifact_dir, stored, content_hash = store.store_json(
        org_id="local-org",
        project_id=spec.project_id,
        asset_type="evaluation_spec",
        name=spec.id,
        version=version,
        filename="evaluation_spec.json",
        payload=payload,
        metadata={"project_id": spec.project_id, "evaluation_spec_id": spec.id},
    )
    return register_artifact(
        db,
        project_id=spec.project_id,
        asset_type="evaluation_spec",
        name=spec.id,
        uri=str(artifact_dir),
        content_hash=content_hash,
        size_bytes=stored.size_bytes,
        metadata={"primary_path": str(stored.path), "project_id": spec.project_id, "evaluation_spec_id": spec.id},
        version=version,
    )


def infer_task_type(target_profile: dict[str, Any]) -> str:
    unique_count = int(target_profile.get("unique_count") or 0)
    if 0 < unique_count <= 2:
        return "binary_classification"
    if 2 < unique_count <= 20:
        return "multiclass_classification"
    return "regression"


def recommend_primary_metric(task_type: str, target_profile: dict[str, Any]) -> str:
    if task_type == "binary_classification":
        positive_rate = estimate_positive_rate(target_profile)
        return "pr_auc" if positive_rate is not None and positive_rate < 0.2 else "roc_auc"
    if task_type == "multiclass_classification":
        return "macro_f1"
    return "rmse"


def recommend_secondary_metrics(task_type: str) -> list[str]:
    if task_type == "binary_classification":
        return ["log_loss", "f1", "calibration_error"]
    if task_type == "multiclass_classification":
        return ["accuracy", "log_loss"]
    return ["mae", "r2"]


def estimate_positive_rate(target_profile: dict[str, Any]) -> float | None:
    values = target_profile.get("top_values") or []
    counts = [int(item.get("count") or 0) for item in values]
    total = sum(counts)
    if len(counts) != 2 or total == 0:
        return None
    return min(counts) / total


def candidate_to_dict(candidate: EvaluationCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "project_id": candidate.project_id,
        "dataset_snapshot_id": candidate.dataset_snapshot_id,
        "name": candidate.name,
        "scenario_id": candidate.scenario_id,
        "split_type": candidate.split_type,
        "primary_metric": candidate.primary_metric,
        "secondary_metrics": loads_json(candidate.secondary_metrics_json, []),
        "time_column": candidate.time_column,
        "group_column": candidate.group_column,
        "stratify_column": candidate.stratify_column,
        "excluded_columns": loads_json(candidate.excluded_columns_json, []),
        "assumption_ids": loads_json(candidate.assumption_ids_json, []),
        "rationale_md": candidate.rationale_md,
        "confidence": candidate.confidence,
        "risk_level": candidate.risk_level,
        "status": candidate.status,
        "created_at": candidate.created_at.isoformat(),
    }


def spec_to_dict(spec: EvaluationSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "project_id": spec.project_id,
        "dataset_snapshot_id": spec.dataset_snapshot_id,
        "source_evaluation_candidate_id": spec.source_evaluation_candidate_id,
        "name": spec.name,
        "split_type": spec.split_type,
        "primary_metric": spec.primary_metric,
        "secondary_metrics": loads_json(spec.secondary_metrics_json, []),
        "time_column": spec.time_column,
        "group_column": spec.group_column,
        "stratify_column": spec.stratify_column,
        "excluded_columns": loads_json(spec.excluded_columns_json, []),
        "assumption_ids": loads_json(spec.assumption_ids_json, []),
        "rationale_md": spec.rationale_md,
        "risk_level": spec.risk_level,
        "status": spec.status,
        "created_at": spec.created_at.isoformat(),
    }


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
