from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from tabular_harness.core.ids import new_id
from tabular_harness.core.json import dumps_json

LEAKAGE_NAME_HINTS = (
    "actual",
    "result",
    "final",
    "after",
    "post",
    "label",
    "score",
    "status",
)

DEFAULT_PROFILE_SAMPLE_ROWS = 50_000
FULL_PROFILE_MAX_FILE_BYTES = 50 * 1024 * 1024
FULL_PROFILE_MAX_ROWS = 100_000
FULL_PROFILE_MAX_COLUMNS = 80


@dataclass(frozen=True)
class ProfileResult:
    profile: dict[str, Any]
    semantic_catalog: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    assumptions: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    understanding_md: str
    schema_hash: str
    row_count: int
    column_count: int


def profile_tabular_file(
    path: Path,
    project_id: str,
    target_column: str | None = None,
    *,
    profile_mode: str = "auto",
    sample_size: int = DEFAULT_PROFILE_SAMPLE_ROWS,
    full_profile_max_file_bytes: int = FULL_PROFILE_MAX_FILE_BYTES,
    full_profile_max_rows: int = FULL_PROFILE_MAX_ROWS,
    full_profile_max_columns: int = FULL_PROFILE_MAX_COLUMNS,
) -> ProfileResult:
    con = duckdb.connect(database=":memory:")
    view_name = "uploaded_dataset"
    con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM {read_sql(path)}")
    schema_rows = con.execute(f"DESCRIBE SELECT * FROM {view_name}").fetchall()
    columns = [{"name": row[0], "physical_type": row[1]} for row in schema_rows]
    row_count_result = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
    assert row_count_result is not None
    row_count = int(row_count_result[0])
    column_count = len(columns)
    file_size_bytes = path.stat().st_size if path.exists() else None
    bounded, bounded_reasons = choose_profile_mode(
        requested_mode=profile_mode,
        file_size_bytes=file_size_bytes,
        row_count=row_count,
        column_count=column_count,
        full_profile_max_file_bytes=full_profile_max_file_bytes,
        full_profile_max_rows=full_profile_max_rows,
        full_profile_max_columns=full_profile_max_columns,
    )
    stats_view_name = view_name
    stats_row_count = row_count
    sample_metadata: dict[str, Any] = {
        "enabled": False,
        "sample_row_count": None,
        "sample_limit": None,
        "sample_method": None,
        "reasons": bounded_reasons,
    }
    if bounded:
        if sample_size <= 0:
            raise ValueError("sample_size must be positive for bounded profiling")
        stats_view_name = "profile_sample"
        con.execute(f"CREATE TEMP TABLE {stats_view_name} AS SELECT * FROM {view_name} LIMIT {int(sample_size)}")
        sample_count_result = con.execute(f"SELECT COUNT(*) FROM {stats_view_name}").fetchone()
        assert sample_count_result is not None
        stats_row_count = int(sample_count_result[0])
        sample_metadata = {
            "enabled": True,
            "sample_row_count": stats_row_count,
            "sample_limit": int(sample_size),
            "sample_method": "first_rows_limit",
            "reasons": bounded_reasons,
        }

    column_profiles: list[dict[str, Any]] = []
    semantic_columns: list[dict[str, Any]] = []
    leakage_columns: list[str] = []
    name_based_leakage_hint_columns: list[str] = []
    time_candidates: list[str] = []
    group_candidates: list[str] = []
    deferred_columns: list[dict[str, Any]] = []
    missing_cell_count = 0

    for column in columns:
        name = column["name"]
        dtype = column["physical_type"]
        stats = con.execute(
            f"""
            SELECT
              COUNT(*) - COUNT({quote_ident(name)}) AS missing_count,
              COUNT(DISTINCT {quote_ident(name)}) AS unique_count
            FROM {stats_view_name}
            """
        ).fetchone()
        assert stats is not None
        scoped_missing_count = int(stats[0] or 0)
        scoped_unique_count = int(stats[1] or 0)
        missing_rate = scoped_missing_count / stats_row_count if stats_row_count else 0.0
        missing_count = int(round(missing_rate * row_count)) if bounded else scoped_missing_count
        unique_count = scoped_unique_count
        missing_cell_count += missing_count
        lower_name = name.lower()
        semantic_type = infer_semantic_type(lower_name, dtype)
        role = (
            "target"
            if target_column and name == target_column
            else infer_role(
                lower_name,
                unique_count,
                row_count,
                stats_row_count=stats_row_count,
                unique_count_is_sampled=bounded,
            )
        )
        available = "unknown"
        name_based_leakage_hint = any(hint in lower_name for hint in LEAKAGE_NAME_HINTS)
        if name == target_column:
            available = "no"
        if name_based_leakage_hint and name != target_column:
            name_based_leakage_hint_columns.append(name)
        leakage_suspect = False
        if semantic_type == "datetime":
            time_candidates.append(name)
        if role == "group":
            group_candidates.append(name)
        column_profiles.append(
            {
                "name": name,
                "physical_type": dtype,
                "semantic_type": semantic_type,
                "role": role,
                "missing_count": missing_count,
                "missing_rate": round(missing_rate, 6),
                "unique_count": unique_count,
                "stats_scope": "sample" if bounded else "full",
                "stats_row_count": stats_row_count,
                "missing_count_is_estimated": bounded,
                "unique_count_is_approximate": bounded,
                "sample_missing_count": scoped_missing_count if bounded else None,
                "sample_unique_count": scoped_unique_count if bounded else None,
                "is_leakage_suspect": leakage_suspect,
                "name_based_hints": {
                    "leakage_candidate": name_based_leakage_hint and name != target_column,
                },
            }
        )
        if bounded:
            deferred_columns.append(
                {
                    "name": name,
                    "physical_type": dtype,
                    "deferred_stats": ["exact_missing_count", "exact_unique_count"],
                    "sample_row_count": stats_row_count,
                    "sample_missing_count": scoped_missing_count,
                    "sample_unique_count": scoped_unique_count,
                    "reason": "bounded_profile_mode",
                }
            )
        semantic_columns.append(
            {
                "column_name": name,
                "physical_type": dtype,
                "semantic_type": semantic_type,
                "role": role,
                "available_at_prediction_time": available,
                "pii_level": "unknown",
                "is_leakage_suspect": leakage_suspect,
                "name_based_hints": {
                    "leakage_candidate": name_based_leakage_hint and name != target_column,
                },
                "description": None,
                "confidence": 0.55 if role != "feature" else 0.45,
                "evidence": [{"type": "schema_inference", "summary": f"{name} inferred from name/type"}],
            }
        )

    target_profile = build_target_profile(con, view_name, target_column, columns) if target_column else None
    profile = {
        "schema_version": "eda_profile.v1",
        "file": str(path),
        "file_size_bytes": file_size_bytes,
        "row_count": row_count,
        "column_count": column_count,
        "profile_mode": "bounded_sample" if bounded else "full",
        "profile_mode_requested": profile_mode,
        "profile_mode_reasons": bounded_reasons,
        "profile_sample": sample_metadata,
        "column_stat_scope": "sample" if bounded else "full",
        "missing_cell_count": missing_cell_count,
        "columns": column_profiles,
        "target_column": target_column,
        "target_profile": target_profile,
        "time_candidates": time_candidates,
        "group_candidates": group_candidates,
        "leakage_suspects": leakage_columns,
        "name_based_hints": {
            "leakage_candidate_columns": name_based_leakage_hint_columns,
        },
        "deferred_deep_profile": {
            "recommended": bounded,
            "reason": (
                "Exact per-column missing and unique counts were deferred to keep large imports responsive."
                if bounded
                else None
            ),
            "suggested_job_type": "profile_dataset_deep" if bounded else None,
            "deferred_column_count": len(deferred_columns),
            "deferred_columns": deferred_columns,
        },
        "sample_rows": sample_rows(con, view_name),
    }
    schema_hash = hashlib.sha256(dumps_json(columns).encode("utf-8")).hexdigest()
    evidence = build_evidence(
        project_id,
        leakage_columns,
        time_candidates,
        group_candidates,
        profile_mode=str(profile["profile_mode"]),
        sample_row_count=stats_row_count,
    )
    assumptions = build_assumptions(
        project_id,
        target_column,
        leakage_columns,
        time_candidates,
        group_candidates,
        bounded_profile=bounded,
    )
    questions = build_questions(project_id, target_column, leakage_columns, time_candidates, group_candidates)
    understanding_md = render_understanding(profile, assumptions, questions)
    return ProfileResult(
        profile=profile,
        semantic_catalog=semantic_columns,
        questions=questions,
        assumptions=assumptions,
        evidence=evidence,
        understanding_md=understanding_md,
        schema_hash=schema_hash,
        row_count=row_count,
        column_count=column_count,
    )


def choose_profile_mode(
    *,
    requested_mode: str,
    file_size_bytes: int | None,
    row_count: int,
    column_count: int,
    full_profile_max_file_bytes: int,
    full_profile_max_rows: int,
    full_profile_max_columns: int,
) -> tuple[bool, list[str]]:
    if requested_mode not in {"auto", "full", "bounded_sample"}:
        raise ValueError("profile_mode must be one of: auto, full, bounded_sample")
    reasons: list[str] = []
    if requested_mode == "bounded_sample":
        return True, ["requested_bounded_sample"]
    if requested_mode == "full":
        return False, ["requested_full"]
    if file_size_bytes is not None and file_size_bytes > full_profile_max_file_bytes:
        reasons.append(f"file_size_bytes>{full_profile_max_file_bytes}")
    if row_count > full_profile_max_rows:
        reasons.append(f"row_count>{full_profile_max_rows}")
    if column_count > full_profile_max_columns:
        reasons.append(f"column_count>{full_profile_max_columns}")
    return bool(reasons), reasons or ["within_full_profile_thresholds"]


def read_sql(path: Path) -> str:
    suffix = path.suffix.lower()
    literal = sql_literal(str(path))
    if suffix == ".parquet":
        return f"read_parquet({literal})"
    if suffix == ".csv":
        return f"read_csv_auto({literal}, sample_size=-1, ignore_errors=true)"
    raise ValueError("Only CSV and Parquet uploads are supported")


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def infer_semantic_type(lower_name: str, dtype: str) -> str:
    if "date" in lower_name or "time" in lower_name or dtype.upper() in {"DATE", "TIMESTAMP"}:
        return "datetime"
    if is_identifier_name(lower_name):
        return "identifier"
    if "text" in lower_name or "comment" in lower_name or "description" in lower_name:
        return "text"
    if any(token in dtype.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC")):
        return "numeric"
    return "categorical"


def is_identifier_name(lower_name: str) -> bool:
    return (
        lower_name == "id"
        or lower_name.endswith("_id")
        or lower_name.endswith("id")
        or lower_name.startswith("sk_id_")
        or lower_name.startswith("id_")
    )


def infer_role(
    lower_name: str,
    unique_count: int,
    row_count: int,
    *,
    stats_row_count: int | None = None,
    unique_count_is_sampled: bool = False,
) -> str:
    if is_identifier_name(lower_name) or lower_name in {"user_id", "customer_id", "account_id"}:
        if unique_count_is_sampled and stats_row_count and unique_count >= int(stats_row_count * 0.98):
            return "identifier"
        if row_count and unique_count < row_count:
            return "group"
        return "identifier"
    return "feature"


def build_target_profile(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    target_column: str | None,
    columns: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not target_column or target_column not in {column["name"] for column in columns}:
        return None
    dtype = next(column["physical_type"] for column in columns if column["name"] == target_column)
    target = quote_ident(target_column)
    base = con.execute(
        f"""
        SELECT
          COUNT(*) AS row_count,
          COUNT({target}) AS non_null_count,
          COUNT(DISTINCT {target}) AS unique_count
        FROM {view_name}
        """
    ).fetchone()
    assert base is not None
    result: dict[str, Any] = {
        "physical_type": dtype,
        "non_null_count": int(base[1] or 0),
        "missing_count": int((base[0] or 0) - (base[1] or 0)),
        "unique_count": int(base[2] or 0),
    }
    if any(token in dtype.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC")):
        numeric = con.execute(
            f"""
            SELECT
              MIN({target}),
              MAX({target}),
              AVG({target}),
              STDDEV_POP({target})
            FROM {view_name}
            """
        ).fetchone()
        assert numeric is not None
        result.update(
            {
                "min": safe_number(numeric[0]),
                "max": safe_number(numeric[1]),
                "mean": safe_number(numeric[2]),
                "stddev": safe_number(numeric[3]),
            }
        )
    top_values = con.execute(
        f"""
        SELECT CAST({target} AS VARCHAR) AS value, COUNT(*) AS count
        FROM {view_name}
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 20
        """
    ).fetchall()
    result["top_values"] = [{"value": row[0], "count": int(row[1])} for row in top_values]
    return result


def safe_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, int | float):
        return value
    return float(value)


def sample_rows(con: duckdb.DuckDBPyConnection, view_name: str) -> list[dict[str, Any]]:
    cursor = con.execute(f"SELECT * FROM {view_name} LIMIT 20")
    column_names = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    return [
        {
            column_names[index]: normalize_sample_value(value)
            for index, value in enumerate(row)
        }
        for row in rows
    ]


def normalize_sample_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def build_evidence(
    project_id: str,
    leakage_columns: list[str],
    time_candidates: list[str],
    group_candidates: list[str],
    *,
    profile_mode: str,
    sample_row_count: int,
) -> list[dict[str, Any]]:
    evidence = [
        {
            "id": new_id("ev"),
            "project_id": project_id,
            "evidence_type": "schema_inference",
            "summary": (
                "Schema and row count were profiled; column missingness and unique counts used bounded sample statistics."
                if profile_mode == "bounded_sample"
                else "Schema, missingness, unique counts, and simple name-based semantics were profiled."
            ),
            "strength": "medium",
            "metadata": {
                "time_candidates": time_candidates,
                "group_candidates": group_candidates,
                "profile_mode": profile_mode,
                "sample_row_count": sample_row_count,
            },
        }
    ]
    if leakage_columns:
        evidence.append(
            {
                "id": new_id("ev"),
                "project_id": project_id,
                "evidence_type": "column_name_inference",
                "summary": f"Potential leakage columns from names: {', '.join(leakage_columns)}.",
                "strength": "medium",
                "metadata": {"columns": leakage_columns},
            }
        )
    return evidence


def build_assumptions(
    project_id: str,
    target_column: str | None,
    leakage_columns: list[str],
    time_candidates: list[str],
    group_candidates: list[str],
    *,
    bounded_profile: bool,
) -> list[dict[str, Any]]:
    assumptions = [
        {
            "id": new_id("asm"),
            "project_id": project_id,
            "topic": "target_definition",
            "subject_type": "column",
            "subject_ref": target_column,
            "statement": (
                f"{target_column} is the prediction target." if target_column else "Target column is not specified yet."
            ),
            "status": "inferred" if target_column else "unknown",
            "confidence": 0.75 if target_column else 0.25,
            "risk_level": "medium" if target_column else "blocking",
            "fallback_policy": "conservative_default" if target_column else "block_until_answered",
            "requires_user_confirmation": not bool(target_column),
        }
    ]
    if bounded_profile:
        assumptions.append(
            {
                "id": new_id("asm"),
                "project_id": project_id,
                "topic": "data_understanding",
                "subject_type": "profile",
                "subject_ref": "eda_profile",
                "statement": "Large-dataset column statistics are sample-based until a deeper profile is requested.",
                "status": "adopted",
                "confidence": 0.8,
                "risk_level": "medium",
                "fallback_policy": "infer_and_continue",
                "requires_user_confirmation": False,
            }
        )
    if leakage_columns:
        assumptions.append(
            {
                "id": new_id("asm"),
                "project_id": project_id,
                "topic": "prediction_time_availability",
                "subject_type": "columns",
                "subject_ref": ",".join(leakage_columns),
                "statement": "Leakage-suspect columns should be excluded until availability is confirmed.",
                "status": "adopted",
                "confidence": 0.65,
                "risk_level": "high",
                "fallback_policy": "exclude_until_confirmed",
                "requires_user_confirmation": True,
            }
        )
    if time_candidates:
        assumptions.append(
            {
                "id": new_id("asm"),
                "project_id": project_id,
                "topic": "evaluation_design",
                "subject_type": "columns",
                "subject_ref": ",".join(time_candidates),
                "statement": "Detected time-like columns may require time-based validation.",
                "status": "inferred",
                "confidence": 0.55,
                "risk_level": "medium",
                "fallback_policy": "scenario_compare",
                "requires_user_confirmation": False,
            }
        )
    if group_candidates:
        assumptions.append(
            {
                "id": new_id("asm"),
                "project_id": project_id,
                "topic": "evaluation_design",
                "subject_type": "columns",
                "subject_ref": ",".join(group_candidates),
                "statement": "Detected entity/group columns may require group-aware validation.",
                "status": "inferred",
                "confidence": 0.55,
                "risk_level": "medium",
                "fallback_policy": "scenario_compare",
                "requires_user_confirmation": False,
            }
        )
    return assumptions


def build_questions(
    project_id: str,
    target_column: str | None,
    leakage_columns: list[str],
    time_candidates: list[str],
    group_candidates: list[str],
) -> list[dict[str, Any]]:
    question_set_id = new_id("qs")
    questions = [
        {
            "id": new_id("q"),
            "project_id": project_id,
            "question_set_id": question_set_id,
            "topic": "row_semantics",
            "question": "What does one row in this dataset represent?",
            "why_it_matters": "Row semantics determine whether random, group, or time split is valid.",
            "default_assumption": "Rows are independent observations unless evidence suggests otherwise.",
            "impact_if_wrong": "Validation may be optimistic if repeated entities cross splits.",
            "choices": ["independent_row", "entity_event", "time_period", "unknown"],
            "priority": 30,
            "risk_level": "medium",
            "value_of_answer": "high",
            "can_proceed_without_answer": True,
            "fallback_policy": "conservative_default",
            "related_assumption_id": None,
            "blocks_next_phase": False,
        }
    ]
    if not target_column:
        questions.append(
            {
                "id": new_id("q"),
                "project_id": project_id,
                "question_set_id": question_set_id,
                "topic": "target_definition",
                "question": "Which column is the prediction target?",
                "why_it_matters": "Target is required for evaluation design and baseline runs.",
                "default_assumption": "No target is assumed until specified.",
                "impact_if_wrong": "The task can become invalid or evaluate the wrong outcome.",
                "choices": ["provide_target_column", "profile_only_for_now"],
                "priority": 100,
                "risk_level": "blocking",
                "value_of_answer": "very_high",
                "can_proceed_without_answer": False,
                "fallback_policy": "block_until_answered",
                "related_assumption_id": None,
                "blocks_next_phase": True,
            }
        )
    if leakage_columns:
        questions.append(
            {
                "id": new_id("q"),
                "project_id": project_id,
                "question_set_id": question_set_id,
                "topic": "prediction_time_availability",
                "question": f"Are these columns available at prediction time: {', '.join(leakage_columns)}?",
                "why_it_matters": "Future or post-outcome fields can leak the answer into validation.",
                "default_assumption": "Exclude them until confirmed.",
                "impact_if_wrong": "Validation score may be materially overstated.",
                "choices": ["available", "not_available", "conditional", "unknown"],
                "priority": 90,
                "risk_level": "high",
                "value_of_answer": "very_high",
                "can_proceed_without_answer": True,
                "fallback_policy": "exclude_until_confirmed",
                "related_assumption_id": None,
                "blocks_next_phase": False,
            }
        )
    if time_candidates:
        questions.append(
            {
                "id": new_id("q"),
                "project_id": project_id,
                "question_set_id": question_set_id,
                "topic": "evaluation_design",
                "question": f"Should validation respect time order using: {', '.join(time_candidates)}?",
                "why_it_matters": "Future-like validation better approximates deployment for temporal tasks.",
                "default_assumption": "Compare random/stratified and time-oriented scenarios.",
                "impact_if_wrong": "Model ranking may not transfer to future data.",
                "choices": ["time_split", "random_or_stratified", "scenario_compare", "unknown"],
                "priority": 70,
                "risk_level": "medium",
                "value_of_answer": "high",
                "can_proceed_without_answer": True,
                "fallback_policy": "scenario_compare",
                "related_assumption_id": None,
                "blocks_next_phase": False,
            }
        )
    if group_candidates:
        questions.append(
            {
                "id": new_id("q"),
                "project_id": project_id,
                "question_set_id": question_set_id,
                "topic": "evaluation_design",
                "question": f"Should validation keep entities together using: {', '.join(group_candidates)}?",
                "why_it_matters": "Repeated entities across train and validation can overstate generalization.",
                "default_assumption": "Compare a group-aware alternative when entity repetition exists.",
                "impact_if_wrong": "The leaderboard may reward memorization.",
                "choices": ["group_split", "row_split_ok", "scenario_compare", "unknown"],
                "priority": 65,
                "risk_level": "medium",
                "value_of_answer": "high",
                "can_proceed_without_answer": True,
                "fallback_policy": "scenario_compare",
                "related_assumption_id": None,
                "blocks_next_phase": False,
            }
        )
    return questions


def render_understanding(
    profile: dict[str, Any],
    assumptions: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> str:
    name_hints = profile.get("name_based_hints") if isinstance(profile.get("name_based_hints"), dict) else {}
    hint_columns = name_hints.get("leakage_candidate_columns") if isinstance(name_hints.get("leakage_candidate_columns"), list) else []
    leakage = profile["leakage_suspects"] or ["None registered as leakage by the harness"]
    target_line = (
        f"Supervised objective column: `{profile['target_column']}`."
        if profile["target_column"]
        else "No supervised objective column was specified; profiling was still completed."
    )
    top_missing = sorted(profile["columns"], key=lambda item: item["missing_rate"], reverse=True)[:5]
    missing_lines = [
        f"- `{item['name']}`: {item['missing_rate']:.1%} missing, {item['unique_count']} unique ({item['stats_scope']})"
        for item in top_missing
    ]
    question_lines = [f"- {item['question']} ({item['fallback_policy']})" for item in questions]
    assumption_lines = [
        f"- {item['statement']} confidence={item['confidence']:.2f}, risk={item['risk_level']}"
        for item in assumptions
    ]
    return "\n".join(
        [
            "# Data Understanding",
            "",
            "## Executive Summary",
            f"- Rows: {profile['row_count']}",
            f"- Columns: {profile['column_count']}",
            f"- Profile mode: {profile['profile_mode']}",
            f"- {target_line}",
            "",
            "## Dataset Overview",
            f"The upload contains {profile['row_count']} rows and {profile['column_count']} columns.",
            (
                "Column-level missingness and unique counts are based on a bounded sample; exact deep profiling is deferred."
                if profile["profile_mode"] == "bounded_sample"
                else "Column-level missingness and unique counts were computed over the full table."
            ),
            "",
            "## Target Understanding",
            target_line,
            "",
            "## Row Semantics",
            "Row meaning is not confirmed yet and is tracked as a question.",
            "",
            "## Time and Group Structure",
            f"- Time candidates: {', '.join(profile['time_candidates']) or 'none detected'}",
            f"- Group candidates: {', '.join(profile['group_candidates']) or 'none detected'}",
            "",
            "## Column Catalog Summary",
            *missing_lines,
            "",
            "## Data Quality Findings",
            (
                "Missingness and uniqueness were estimated for every column from the bounded profile sample."
                if profile["profile_mode"] == "bounded_sample"
                else "Missingness and uniqueness were computed for every column."
            ),
            f"Deferred deep-profile columns: {profile['deferred_deep_profile']['deferred_column_count']}",
            "",
            "## Leakage Risks",
            f"Potential leakage columns: {', '.join(leakage)}",
            f"Name-based availability hints for Codex review: {', '.join(str(item) for item in hint_columns) or 'none'}",
            "",
            "## Prediction Feasibility",
            "Feasibility cannot be finalized until target and prediction-time availability are confirmed.",
            "",
            "## Recommended Evaluation Direction",
            "Start with a conservative random or stratified candidate, then compare time/group alternatives when relevant.",
            "",
            "## Questions for Human",
            *question_lines,
            "",
            "## Assumptions",
            *assumption_lines,
            "",
            "## Next Steps",
            "Review high-risk assumptions, promote an EvaluationCandidate to EvaluationSpec, then generate a SplitManifest.",
        ]
    )
