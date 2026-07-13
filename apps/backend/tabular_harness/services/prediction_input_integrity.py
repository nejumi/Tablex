from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb


def inspect_prediction_input_integrity(
    *,
    input_dir: Path,
    input_contract: dict[str, Any],
) -> dict[str, Any]:
    tables = [item for item in input_contract.get("required_tables") or [] if isinstance(item, dict)]
    primary = next((item for item in tables if item.get("role") == "primary"), tables[0] if tables else None)
    if primary is None:
        return {
            "schema_version": "prediction_input_integrity.v1",
            "status": "not_applicable",
            "table_profiles": [],
            "hard_errors": [],
            "attention_reasons": [],
        }
    primary_name = clean_table_name(primary.get("name"))
    primary_path = table_path(input_dir, primary_name)
    if primary_path is None:
        return integrity_failure(f"Primary table `{primary_name}` is missing from the prediction input directory")

    connection = duckdb.connect()
    try:
        relation_columns: dict[str, set[str]] = {}
        for index, table in enumerate(tables):
            name = clean_table_name(table.get("name"))
            path = table_path(input_dir, name)
            if path is None:
                continue
            view_name = f"input_table_{index}"
            relation = connection.read_parquet(str(path)) if path.suffix.lower() == ".parquet" else connection.read_csv(str(path))
            relation.create_view(view_name, replace=True)
            table["_integrity_view_name"] = view_name
            relation_columns[name] = set(relation.columns)

        profiles: list[dict[str, Any]] = []
        hard_errors: list[str] = []
        attention_reasons: list[str] = []
        primary_view = str(primary.get("_integrity_view_name") or "")
        for table in tables:
            name = clean_table_name(table.get("name"))
            view_name = str(table.get("_integrity_view_name") or "")
            if not view_name:
                continue
            join_keys = [str(value).strip() for value in table.get("join_keys") or [] if str(value).strip()]
            row_count = int(connection.execute(f"SELECT count(*) FROM {quote_identifier(view_name)}").fetchone()[0])
            profile: dict[str, Any] = {
                "table_name": name,
                "role": table.get("role"),
                "row_count": row_count,
                "join_keys": join_keys,
            }
            if table is primary or not join_keys:
                profiles.append(profile)
                continue
            missing_primary_keys = [key for key in join_keys if key not in relation_columns.get(primary_name, set())]
            missing_table_keys = [key for key in join_keys if key not in relation_columns.get(name, set())]
            if missing_primary_keys or missing_table_keys:
                hard_errors.append(
                    f"Table `{name}` cannot be joined: missing primary key(s) {missing_primary_keys} and table key(s) {missing_table_keys}"
                )
                profile["status"] = "join_keys_missing"
                profiles.append(profile)
                continue
            keys_sql = ", ".join(quote_identifier(key) for key in join_keys)
            primary_entities = int(
                connection.execute(
                    f"SELECT count(*) FROM (SELECT DISTINCT {keys_sql} FROM {quote_identifier(primary_view)})"
                ).fetchone()[0]
            )
            table_entities = int(
                connection.execute(
                    f"SELECT count(*) FROM (SELECT DISTINCT {keys_sql} FROM {quote_identifier(view_name)})"
                ).fetchone()[0]
            )
            covered_entities = int(
                connection.execute(
                    f"SELECT count(*) FROM (SELECT DISTINCT {keys_sql} FROM {quote_identifier(primary_view)}) p "
                    f"INNER JOIN (SELECT DISTINCT {keys_sql} FROM {quote_identifier(view_name)}) s USING ({keys_sql})"
                ).fetchone()[0]
            )
            coverage_rate = covered_entities / primary_entities if primary_entities else None
            profile.update(
                {
                    "primary_entity_count": primary_entities,
                    "table_entity_count": table_entities,
                    "covered_primary_entity_count": covered_entities,
                    "entity_coverage_rate": coverage_rate,
                    "rows_per_table_entity": row_count / table_entities if table_entities else None,
                }
            )
            reference = table.get("coverage_reference")
            if isinstance(reference, dict) and isinstance(reference.get("entity_coverage_rate"), int | float):
                reference_rate = float(reference["entity_coverage_rate"])
                delta = coverage_rate - reference_rate if coverage_rate is not None else None
                profile["training_reference_comparison"] = {
                    "entity_coverage_rate": reference_rate,
                    "absolute_delta": delta,
                }
                review_delta = reference.get("review_if_absolute_delta_exceeds")
                if isinstance(review_delta, int | float) and delta is not None and abs(delta) > float(review_delta):
                    attention_reasons.append(
                        f"Table `{name}` entity coverage changed by {delta:+.4f}, beyond its Codex-authored review threshold {float(review_delta):.4f}"
                    )
            else:
                profile["training_reference_comparison"] = {"status": "reference_not_declared"}
            if primary_entities and covered_entities == 0:
                attention_reasons.append(f"Table `{name}` has zero join-key coverage for the prediction population")
            profiles.append(profile)
        return {
            "schema_version": "prediction_input_integrity.v1",
            "status": "failed" if hard_errors else "measured",
            "primary_table": primary_name,
            "table_profiles": profiles,
            "hard_errors": hard_errors,
            "attention_reasons": attention_reasons,
        }
    finally:
        connection.close()


def clean_table_name(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return cleaned or "table"


def table_path(input_dir: Path, table_name: str) -> Path | None:
    for suffix in (".csv", ".parquet"):
        candidate = input_dir / f"{table_name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def integrity_failure(message: str) -> dict[str, Any]:
    return {
        "schema_version": "prediction_input_integrity.v1",
        "status": "failed",
        "table_profiles": [],
        "hard_errors": [message],
        "attention_reasons": [],
    }
