from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import duckdb

from tabular_harness.core.config import Settings
from tabular_harness.services.profiler import quote_ident, read_sql

SUPPORTED_PRIMARY_SUFFIXES = {".csv", ".parquet"}
KEY_NAME_HINTS = ("id", "_id", "sk_id", "case_id", "transactionid", "order_id", "store_nbr", "user_id")
TIME_NAME_HINTS = ("date", "time", "dt", "timestamp")
LEAKAGE_NAME_HINTS = ("target", "label", "actual", "result", "final", "after", "post", "status")


@dataclass(frozen=True)
class BenchmarkFileMatch:
    spec: dict[str, Any]
    found_paths: list[Path]

    @property
    def found(self) -> bool:
        return bool(self.found_paths)


def catalog_path() -> Path:
    configured = os.getenv("TABLEX_BENCHMARK_CATALOG_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = [
        Path.cwd() / "benchmarks" / "catalog.json",
        Path(__file__).resolve().parents[4] / "benchmarks" / "catalog.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_benchmark_catalog() -> dict[str, Any]:
    path = catalog_path()
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def catalog_datasets() -> list[dict[str, Any]]:
    catalog = load_benchmark_catalog()
    datasets = catalog.get("datasets", [])
    if not isinstance(datasets, list):
        return []
    return [cast(dict[str, Any], item) for item in datasets if isinstance(item, dict)]


def list_benchmark_datasets(settings: Settings) -> list[dict[str, Any]]:
    return [benchmark_to_dict(item, settings=settings, include_status=True) for item in catalog_datasets()]


def get_benchmark_dataset(benchmark_id: str, settings: Settings) -> dict[str, Any]:
    for item in catalog_datasets():
        if item.get("id") == benchmark_id:
            return benchmark_to_dict(item, settings=settings, include_status=True)
    raise KeyError(benchmark_id)


def raw_benchmark_dataset(benchmark_id: str) -> dict[str, Any]:
    for item in catalog_datasets():
        if item.get("id") == benchmark_id:
            return item
    raise KeyError(benchmark_id)


def benchmark_to_dict(benchmark: dict[str, Any], *, settings: Settings, include_status: bool) -> dict[str, Any]:
    default_root = default_benchmark_root(settings, str(benchmark["id"]))
    payload = dict(benchmark)
    payload["default_local_path"] = str(default_root)
    payload["download_instructions"] = render_download_instructions(benchmark, default_root)
    if include_status:
        payload["local_status"] = inspect_benchmark_local_files(benchmark, default_root)
    return payload


def benchmark_data_root(settings: Settings) -> Path:
    return settings.data_dir / "benchmarks"


def default_benchmark_root(settings: Settings, benchmark_id: str) -> Path:
    return benchmark_data_root(settings) / benchmark_id


def resolve_benchmark_root(settings: Settings, benchmark_id: str, local_path: str | None) -> Path:
    allowed_root = benchmark_data_root(settings).resolve()
    if local_path and local_path.strip():
        requested = Path(local_path.strip()).expanduser()
        root = requested if requested.is_absolute() else allowed_root / requested
    else:
        root = allowed_root / benchmark_id
    root = root.resolve()
    if not root.is_relative_to(allowed_root):
        raise ValueError(
            "Benchmark imports are restricted to HARNESS_DATA_DIR/benchmarks. "
            "Copy the data under that directory instead of importing arbitrary local paths."
        )
    return root


def inspect_benchmark_local_files(benchmark: dict[str, Any], root: Path) -> dict[str, Any]:
    required_matches = [match_file_spec(root, item) for item in benchmark.get("required_files", [])]
    recommended_matches = [match_file_spec(root, item) for item in benchmark.get("recommended_files", [])]
    missing_required = [file_match_to_dict(item, root) for item in required_matches if not item.found]
    found_required = [file_match_to_dict(item, root) for item in required_matches if item.found]
    found_recommended = [file_match_to_dict(item, root) for item in recommended_matches if item.found]
    missing_recommended = [file_match_to_dict(item, root) for item in recommended_matches if not item.found]
    return {
        "root_path": str(root),
        "exists": root.exists(),
        "ready": not missing_required,
        "required_found_count": len(found_required),
        "required_missing_count": len(missing_required),
        "recommended_found_count": len(found_recommended),
        "recommended_missing_count": len(missing_recommended),
        "found_required": found_required,
        "missing_required": missing_required,
        "found_recommended": found_recommended,
        "missing_recommended": missing_recommended,
    }


def match_file_spec(root: Path, spec: dict[str, Any]) -> BenchmarkFileMatch:
    matches: list[Path] = []
    if "path" in spec:
        candidate = root / str(spec["path"])
        if candidate.is_file():
            matches.append(candidate)
    for candidate_path in spec.get("path_candidates", []):
        candidate = root / str(candidate_path)
        if candidate.is_file():
            matches.append(candidate)
    if "glob" in spec and root.exists():
        matches.extend(path for path in sorted(root.glob(str(spec["glob"]))) if path.is_file())
    return BenchmarkFileMatch(spec=spec, found_paths=dedupe_paths(matches))


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def file_match_to_dict(match: BenchmarkFileMatch, root: Path) -> dict[str, Any]:
    return {
        "role": match.spec.get("role"),
        "description": match.spec.get("description"),
        "expected": expected_file_labels(match.spec),
        "found": match.found,
        "paths": [relative_path(root, path) for path in match.found_paths],
        "size_bytes": sum(path.stat().st_size for path in match.found_paths if path.exists()),
    }


def expected_file_labels(spec: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    if "path" in spec:
        labels.append(str(spec["path"]))
    labels.extend(str(path) for path in spec.get("path_candidates", []))
    if "glob" in spec:
        labels.append(str(spec["glob"]))
    return labels


def select_primary_file(benchmark: dict[str, Any], root: Path, requested_primary_file: str | None = None) -> Path:
    if requested_primary_file and requested_primary_file.strip():
        candidate = (root / requested_primary_file.strip()).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise ValueError("primary_file must stay inside the benchmark local root")
        if not candidate.is_file():
            raise ValueError(f"primary_file does not exist: {requested_primary_file}")
        validate_primary_suffix(candidate)
        return candidate

    primary = benchmark.get("primary_table") or {}
    candidates: list[Path] = []
    if primary.get("path"):
        candidates.append(root / str(primary["path"]))
    candidates.extend(root / str(path) for path in primary.get("path_candidates", []))
    for candidate in candidates:
        if candidate.is_file():
            validate_primary_suffix(candidate)
            return candidate
    raise ValueError("No supported primary table file was found for this benchmark")


def validate_primary_suffix(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_PRIMARY_SUFFIXES:
        raise ValueError("Benchmark primary table must be CSV or Parquet for v0 import")


def validate_required_files(benchmark: dict[str, Any], root: Path) -> dict[str, Any]:
    status = inspect_benchmark_local_files(benchmark, root)
    if not status["ready"]:
        missing = ", ".join(
            "/".join(item["expected"]) for item in status["missing_required"]
        )
        raise ValueError(f"Missing required benchmark files: {missing}")
    return status


def build_import_manifest(
    *,
    benchmark: dict[str, Any],
    root: Path,
    primary_file: Path,
    local_status: dict[str, Any],
    target_column: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "benchmark_import_manifest.v1",
        "benchmark_id": benchmark["id"],
        "benchmark_name": benchmark["name"],
        "source_kind": benchmark["source_kind"],
        "source_url": benchmark["source_url"],
        "primary_table": {
            **dict(benchmark.get("primary_table") or {}),
            "selected_path": relative_path(root, primary_file),
            "target_column": target_column,
        },
        "task_types": benchmark.get("task_types", []),
        "modality_tags": benchmark.get("modality_tags", []),
        "local_root": str(root),
        "local_status": local_status,
        "evaluation_notes": benchmark.get("evaluation_notes"),
        "risk_notes": benchmark.get("risk_notes", []),
        "credential_policy": {
            "kaggle_credentials": "not_stored_or_passed_to_agent",
            "connector_credentials": "not_materialized",
            "secret_access": "forbidden",
        },
        "v0_scope": {
            "profiled_dataset": "primary_table_only",
            "supporting_tables": "recorded_in_manifest_for_future_multitable_feature_recipes",
        },
    }


def build_relational_catalog(
    *,
    benchmark: dict[str, Any],
    root: Path,
    primary_file: Path,
    local_status: dict[str, Any],
    target_column: str | None,
    max_tables: int = 30,
) -> dict[str, Any]:
    table_files = collect_benchmark_table_files(benchmark, root, primary_file, max_tables=max_tables)
    table_profiles = [
        profile_table_file(
            path=item["path"],
            root=root,
            role=str(item["role"]),
            is_primary=item["path"].resolve() == primary_file.resolve(),
            target_column=target_column,
            primary_table=benchmark.get("primary_table") or {},
        )
        for item in table_files
    ]
    relationships = infer_relationships(table_profiles, benchmark.get("primary_table") or {})
    target_locations = [
        {"table": table["table_name"], "path": table["path"]}
        for table in table_profiles
        if target_column and target_column in table.get("columns", [])
    ]
    return {
        "schema_version": "relational_catalog.v1",
        "benchmark_id": benchmark["id"],
        "benchmark_name": benchmark["name"],
        "source_url": benchmark["source_url"],
        "primary_table": {
            **dict(benchmark.get("primary_table") or {}),
            "selected_path": relative_path(root, primary_file),
            "target_column": target_column,
        },
        "local_root": str(root),
        "table_count": len(table_profiles),
        "table_limit": max_tables,
        "table_discovery_truncated": table_count_from_status(local_status) > len(table_profiles),
        "tables": table_profiles,
        "relationships": relationships,
        "target_locations": target_locations,
        "evaluation_guidance": {
            "primary_table_only_dataset_snapshot": True,
            "multi_table_features_require_feature_recipe_or_agent_task": True,
            "respect_split_manifest": True,
            "notes": benchmark.get("evaluation_notes"),
        },
        "risk_notes": build_relational_risk_notes(benchmark, table_profiles, target_locations),
        "agent_context_notes": [
            "Treat this relational catalog as planning context, not as permission to read arbitrary local files.",
            "Join keys are inferred from names and approximate cardinality; confirm semantics before relying on them.",
            "Fit joins, encoders, aggregations, TF-IDF, lag, and rolling features on training data according to SplitManifest.",
        ],
    }


def collect_benchmark_table_files(
    benchmark: dict[str, Any], root: Path, primary_file: Path, *, max_tables: int
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [{"path": primary_file, "role": "primary_table"}]
    for role_group in ("required_files", "recommended_files"):
        for spec in benchmark.get(role_group, []):
            role = str(spec.get("role") or role_group.rstrip("s"))
            match = match_file_spec(root, spec)
            for path in match.found_paths:
                if path.suffix.lower() in SUPPORTED_PRIMARY_SUFFIXES:
                    items.append({"path": path, "role": role})
    unique: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for item in items:
        resolved = cast(Path, item["path"]).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(item)
        if len(unique) >= max_tables:
            break
    return unique


def profile_table_file(
    *,
    path: Path,
    root: Path,
    role: str,
    is_primary: bool,
    target_column: str | None,
    primary_table: dict[str, Any],
) -> dict[str, Any]:
    rel_path = relative_path(root, path)
    table_name = table_name_from_path(rel_path)
    base: dict[str, Any] = {
        "table_name": table_name,
        "path": rel_path,
        "role": role,
        "is_primary": is_primary,
        "format": path.suffix.lower().lstrip("."),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "status": "succeeded",
    }
    try:
        con = duckdb.connect(database=":memory:")
        view_name = "bundle_table"
        con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM {read_sql(path)}")
        schema_rows = con.execute(f"DESCRIBE SELECT * FROM {view_name}").fetchall()
        columns = [{"name": str(row[0]), "physical_type": str(row[1])} for row in schema_rows]
        row_count_result = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
        row_count = int(row_count_result[0]) if row_count_result else 0
        column_stats = table_column_stats(con, view_name, columns, row_count)
        column_names = [column["name"] for column in columns]
        base.update(
            {
                "row_count": row_count,
                "column_count": len(columns),
                "schema_hash": hashlib.sha256(json.dumps(columns, sort_keys=True).encode("utf-8")).hexdigest(),
                "columns": column_names,
                "column_profiles": column_stats,
                "key_candidates": key_candidates(column_stats, row_count, primary_table),
                "time_candidates": time_candidates(columns),
                "target_column_present": bool(target_column and target_column in column_names),
                "leakage_name_suspects": leakage_name_suspects(column_names, target_column),
            }
        )
    except Exception as exc:
        base.update(
            {
                "status": "failed",
                "error": str(exc),
                "row_count": None,
                "column_count": None,
                "schema_hash": None,
                "columns": [],
                "column_profiles": [],
                "key_candidates": [],
                "time_candidates": [],
                "target_column_present": False,
                "leakage_name_suspects": [],
            }
        )
    return base


def table_column_stats(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
    columns: list[dict[str, str]],
    row_count: int,
) -> list[dict[str, Any]]:
    if not columns:
        return []
    if len(columns) > 80:
        return [
            {
                "name": column["name"],
                "physical_type": column["physical_type"],
                "missing_rate": None,
                "approx_unique_count": None,
                "approx_unique_ratio": None,
            }
            for column in columns
        ]
    expressions: list[str] = []
    for index, column in enumerate(columns):
        ident = quote_ident(column["name"])
        expressions.append(f"COUNT({ident}) AS non_null_{index}")
        expressions.append(f"APPROX_COUNT_DISTINCT({ident}) AS unique_{index}")
    stats = con.execute(f"SELECT {', '.join(expressions)} FROM {view_name}").fetchone()
    if stats is None:
        stats = tuple(0 for _ in expressions)
    profiles: list[dict[str, Any]] = []
    for index, column in enumerate(columns):
        non_null = int(stats[index * 2] or 0)
        approx_unique = int(stats[index * 2 + 1] or 0)
        missing_rate = ((row_count - non_null) / row_count) if row_count else 0.0
        profiles.append(
            {
                "name": column["name"],
                "physical_type": column["physical_type"],
                "missing_rate": round(missing_rate, 6),
                "approx_unique_count": approx_unique,
                "approx_unique_ratio": round(approx_unique / row_count, 6) if row_count else None,
            }
        )
    return profiles


def key_candidates(
    column_profiles: list[dict[str, Any]], row_count: int, primary_table: dict[str, Any]
) -> list[dict[str, Any]]:
    preferred = {
        str(value).lower()
        for value in [
            primary_table.get("entity_id_column"),
            primary_table.get("group_column"),
        ]
        if value
    }
    candidates = []
    for profile in column_profiles:
        name = str(profile["name"])
        lower = name.lower()
        unique_ratio = profile.get("approx_unique_ratio")
        hinted = lower in preferred or any(hint in lower for hint in KEY_NAME_HINTS)
        near_unique = isinstance(unique_ratio, float) and unique_ratio >= 0.9
        if hinted or near_unique:
            candidates.append(
                {
                    "column": name,
                    "reason": "catalog_primary_key_hint" if lower in preferred else "name_or_cardinality_hint",
                    "approx_unique_count": profile.get("approx_unique_count"),
                    "approx_unique_ratio": unique_ratio,
                    "missing_rate": profile.get("missing_rate"),
                    "row_count": row_count,
                }
            )
    return candidates[:20]


def time_candidates(columns: list[dict[str, str]]) -> list[str]:
    candidates = []
    for column in columns:
        lower = column["name"].lower()
        dtype = column["physical_type"].upper()
        if any(hint in lower for hint in TIME_NAME_HINTS) or dtype in {"DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE"}:
            candidates.append(column["name"])
    return candidates


def leakage_name_suspects(column_names: list[str], target_column: str | None) -> list[str]:
    suspects = []
    for name in column_names:
        lower = name.lower()
        if target_column and name == target_column:
            continue
        if any(hint in lower for hint in LEAKAGE_NAME_HINTS):
            suspects.append(name)
    return suspects


def infer_relationships(table_profiles: list[dict[str, Any]], primary_table: dict[str, Any]) -> list[dict[str, Any]]:
    relationships: list[dict[str, Any]] = []
    primary_entity = str(primary_table.get("entity_id_column") or "").lower()
    key_sets = {
        table["table_name"]: {str(item["column"]).lower(): item for item in table.get("key_candidates", [])}
        for table in table_profiles
        if table.get("status") == "succeeded"
    }
    for left_index, left in enumerate(table_profiles):
        if left.get("status") != "succeeded":
            continue
        for right in table_profiles[left_index + 1 :]:
            if right.get("status") != "succeeded":
                continue
            shared = sorted(set(key_sets.get(left["table_name"], {})) & set(key_sets.get(right["table_name"], {})))
            for column in shared:
                confidence = 0.78 if column == primary_entity else 0.58
                relationships.append(
                    {
                        "left_table": left["table_name"],
                        "right_table": right["table_name"],
                        "left_column": key_sets[left["table_name"]][column]["column"],
                        "right_column": key_sets[right["table_name"]][column]["column"],
                        "relation_type": "shared_key_name",
                        "confidence": confidence,
                        "evidence": "matching key-like column name with approximate cardinality profile",
                    }
                )
                if len(relationships) >= 200:
                    return relationships
    return relationships


def build_relational_risk_notes(
    benchmark: dict[str, Any], table_profiles: list[dict[str, Any]], target_locations: list[dict[str, Any]]
) -> list[str]:
    notes = list(benchmark.get("risk_notes", []))
    failed_tables = [table["path"] for table in table_profiles if table.get("status") == "failed"]
    if failed_tables:
        notes.append(f"Some supporting tables failed lightweight profiling: {', '.join(failed_tables[:5])}.")
    non_primary_targets = [item["path"] for item in target_locations if not item["table"].endswith("application_train")]
    if len(target_locations) > 1 and non_primary_targets:
        notes.append("Target-like column appears in multiple tables; confirm there is no post-outcome leakage.")
    if not any(table.get("is_primary") and table.get("time_candidates") for table in table_profiles):
        notes.append("No primary-table time column was confirmed by profiling; random split may be only a fallback.")
    return notes


def table_count_from_status(local_status: dict[str, Any]) -> int:
    return int(local_status.get("required_found_count") or 0) + int(local_status.get("recommended_found_count") or 0)


def table_name_from_path(path: str) -> str:
    normalized = []
    for char in path.rsplit(".", 1)[0]:
        normalized.append(char.lower() if char.isalnum() else "_")
    name = "".join(normalized).strip("_")
    while "__" in name:
        name = name.replace("__", "_")
    return name or "table"


def render_download_instructions(benchmark: dict[str, Any], default_root: Path) -> str:
    download = benchmark.get("download") or {}
    command = str(download.get("command") or "").replace("data/benchmarks", str(default_root.parent))
    if download.get("requires_account"):
        return (
            "Use a user-managed account outside Tablex. Do not paste Kaggle credentials into Tablex or agent prompts. "
            f"Suggested command: {command}"
        )
    return f"Place extracted files under {default_root}. Suggested source step: {command}"


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
