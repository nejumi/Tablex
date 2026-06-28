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


def profile_tabular_file(path: Path, project_id: str, target_column: str | None = None) -> ProfileResult:
    con = duckdb.connect(database=":memory:")
    view_name = "uploaded_dataset"
    con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM {read_sql(path)}")
    schema_rows = con.execute(f"DESCRIBE SELECT * FROM {view_name}").fetchall()
    columns = [{"name": row[0], "physical_type": row[1]} for row in schema_rows]
    row_count_result = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
    assert row_count_result is not None
    row_count = int(row_count_result[0])

    column_profiles: list[dict[str, Any]] = []
    semantic_columns: list[dict[str, Any]] = []
    leakage_columns: list[str] = []
    time_candidates: list[str] = []
    group_candidates: list[str] = []

    for column in columns:
        name = column["name"]
        dtype = column["physical_type"]
        stats = con.execute(
            f"""
            SELECT
              COUNT(*) - COUNT({quote_ident(name)}) AS missing_count,
              COUNT(DISTINCT {quote_ident(name)}) AS unique_count
            FROM {view_name}
            """
        ).fetchone()
        assert stats is not None
        missing_count = int(stats[0] or 0)
        unique_count = int(stats[1] or 0)
        missing_rate = missing_count / row_count if row_count else 0.0
        lower_name = name.lower()
        semantic_type = infer_semantic_type(lower_name, dtype)
        role = "target" if target_column and name == target_column else infer_role(lower_name, unique_count, row_count)
        available = "unknown"
        leakage_suspect = any(hint in lower_name for hint in LEAKAGE_NAME_HINTS)
        if name == target_column:
            leakage_suspect = False
            available = "no"
        if leakage_suspect:
            leakage_columns.append(name)
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
                "is_leakage_suspect": leakage_suspect,
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
                "description": None,
                "confidence": 0.55 if role != "feature" else 0.45,
                "evidence": [{"type": "schema_inference", "summary": f"{name} inferred from name/type"}],
            }
        )

    target_profile = build_target_profile(con, view_name, target_column, columns) if target_column else None
    profile = {
        "file": str(path),
        "row_count": row_count,
        "column_count": len(columns),
        "columns": column_profiles,
        "target_column": target_column,
        "target_profile": target_profile,
        "time_candidates": time_candidates,
        "group_candidates": group_candidates,
        "leakage_suspects": leakage_columns,
        "sample_rows": sample_rows(con, view_name),
    }
    schema_hash = hashlib.sha256(dumps_json(columns).encode("utf-8")).hexdigest()
    evidence = build_evidence(project_id, leakage_columns, time_candidates, group_candidates)
    assumptions = build_assumptions(project_id, target_column, leakage_columns, time_candidates, group_candidates)
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
        column_count=len(columns),
    )


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
    if "id" == lower_name or lower_name.endswith("_id") or lower_name.endswith("id"):
        return "identifier"
    if "text" in lower_name or "comment" in lower_name or "description" in lower_name:
        return "text"
    if any(token in dtype.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC")):
        return "numeric"
    return "categorical"


def infer_role(lower_name: str, unique_count: int, row_count: int) -> str:
    if lower_name.endswith("_id") or lower_name in {"id", "user_id", "customer_id", "account_id"}:
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
    project_id: str, leakage_columns: list[str], time_candidates: list[str], group_candidates: list[str]
) -> list[dict[str, Any]]:
    evidence = [
        {
            "id": new_id("ev"),
            "project_id": project_id,
            "evidence_type": "schema_inference",
            "summary": "Schema, missingness, unique counts, and simple name-based semantics were profiled.",
            "strength": "medium",
            "metadata": {
                "time_candidates": time_candidates,
                "group_candidates": group_candidates,
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
    leakage = profile["leakage_suspects"] or ["None detected by name heuristic"]
    target_line = (
        f"Target column: `{profile['target_column']}`."
        if profile["target_column"]
        else "No target column was specified; profiling was still completed."
    )
    top_missing = sorted(profile["columns"], key=lambda item: item["missing_rate"], reverse=True)[:5]
    missing_lines = [
        f"- `{item['name']}`: {item['missing_rate']:.1%} missing, {item['unique_count']} unique"
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
            f"- {target_line}",
            "",
            "## Dataset Overview",
            f"The upload contains {profile['row_count']} rows and {profile['column_count']} columns.",
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
            "Missingness and uniqueness were computed for every column.",
            "",
            "## Leakage Risks",
            f"Potential leakage columns: {', '.join(leakage)}",
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
