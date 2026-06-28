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
SUPPORTED_FIXTURE_IDS = {
    "kaggle_home_credit_default_risk",
    "kaggle_store_sales_forecasting",
    "uci_bank_marketing",
}


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
    payload["fixture_available"] = benchmark.get("id") in SUPPORTED_FIXTURE_IDS
    payload["fixture_notes"] = fixture_notes(str(benchmark.get("id")))
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


def fixture_notes(benchmark_id: str) -> str | None:
    if benchmark_id == "kaggle_home_credit_default_risk":
        return "Generates a tiny Home Credit-like multi-table credit risk fixture for import and lineage smoke tests."
    if benchmark_id == "kaggle_store_sales_forecasting":
        return "Generates a tiny retail time-series fixture with store, holiday, oil, and transaction tables."
    if benchmark_id == "uci_bank_marketing":
        return "Generates a tiny semicolon-delimited bank marketing fixture for fast single-table smoke tests."
    return None


def generate_benchmark_fixture(settings: Settings, benchmark_id: str, *, overwrite: bool = False) -> dict[str, Any]:
    benchmark = raw_benchmark_dataset(benchmark_id)
    if benchmark_id not in SUPPORTED_FIXTURE_IDS:
        raise ValueError(f"No local fixture is available for benchmark: {benchmark_id}")
    root = default_benchmark_root(settings, benchmark_id)
    root.mkdir(parents=True, exist_ok=True)
    files = fixture_files(benchmark_id)
    generated_files: list[dict[str, Any]] = []
    skipped_files: list[dict[str, Any]] = []
    fixture_matches_expected = True
    for relative_name, content in files.items():
        destination = root / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected_sha = sha256_text(content)
        if destination.exists() and not overwrite:
            existing_sha = sha256_file(destination)
            matches_fixture = existing_sha == expected_sha
            fixture_matches_expected = fixture_matches_expected and matches_fixture
            skipped_files.append(
                {
                    "path": relative_name,
                    "reason": "exists_fixture_match" if matches_fixture else "exists_different",
                    "size_bytes": destination.stat().st_size,
                    "sha256": existing_sha,
                    "expected_sha256": expected_sha,
                }
            )
            continue
        destination.write_text(content, encoding="utf-8")
        generated_files.append(
            {"path": relative_name, "size_bytes": destination.stat().st_size, "sha256": expected_sha}
        )
    local_status = inspect_benchmark_local_files(benchmark, root)
    return {
        "schema_version": "benchmark_fixture.v1",
        "benchmark_id": benchmark_id,
        "benchmark_name": benchmark["name"],
        "root_path": str(root),
        "overwrite": overwrite,
        "generated_files": generated_files,
        "skipped_files": skipped_files,
        "fixture_matches_expected": fixture_matches_expected,
        "local_status": local_status,
        "credential_policy": {
            "external_credentials_required": False,
            "kaggle_credentials": "not_required_for_fixture",
            "secret_access": "forbidden",
        },
        "notes": fixture_notes(benchmark_id),
    }


def fixture_files(benchmark_id: str) -> dict[str, str]:
    if benchmark_id == "kaggle_home_credit_default_risk":
        return home_credit_fixture_files()
    if benchmark_id == "kaggle_store_sales_forecasting":
        return store_sales_fixture_files()
    if benchmark_id == "uci_bank_marketing":
        return uci_bank_fixture_files()
    raise ValueError(f"No local fixture is available for benchmark: {benchmark_id}")


def home_credit_fixture_files() -> dict[str, str]:
    return {
        "application_train.csv": csv_text(
            [
                "SK_ID_CURR,TARGET,AMT_INCOME_TOTAL,AMT_CREDIT,NAME_CONTRACT_TYPE,DAYS_BIRTH,DAYS_DECISION,post_approval_status",
                "100001,1,120000,450000,Cash loans,-12000,-20,late_default",
                "100002,0,90000,210000,Cash loans,-16000,-30,current",
                "100003,0,145000,320000,Revolving loans,-14000,-25,current",
                "100004,1,70000,180000,Cash loans,-13000,-15,late_default",
                "100005,0,200000,500000,Cash loans,-17000,-45,current",
                "100006,0,110000,260000,Revolving loans,-15000,-35,current",
                "100007,1,80000,220000,Cash loans,-11800,-10,charged_off",
                "100008,0,175000,420000,Cash loans,-16200,-50,current",
                "100009,0,130000,300000,Revolving loans,-15200,-40,current",
                "100010,1,60000,160000,Cash loans,-12500,-12,late_default",
                "100011,0,155000,360000,Cash loans,-14600,-33,current",
                "100012,0,98000,240000,Revolving loans,-13600,-22,current",
            ]
        ),
        "bureau.csv": csv_text(
            [
                "SK_ID_CURR,SK_ID_BUREAU,CREDIT_ACTIVE,DAYS_CREDIT,AMT_CREDIT_SUM",
                "100001,200001,Active,-500,80000",
                "100001,200002,Closed,-1000,50000",
                "100002,200003,Closed,-700,30000",
                "100004,200004,Active,-200,60000",
                "100007,200005,Active,-100,75000",
                "100010,200006,Closed,-900,20000",
            ]
        ),
        "previous_application.csv": csv_text(
            [
                "SK_ID_CURR,SK_ID_PREV,DAYS_DECISION,NAME_CONTRACT_STATUS,AMT_APPLICATION",
                "100001,300001,-400,Approved,200000",
                "100002,300002,-500,Approved,120000",
                "100004,300003,-300,Refused,90000",
                "100007,300004,-80,Refused,110000",
                "100010,300005,-120,Approved,70000",
            ]
        ),
        "installments_payments.csv": csv_text(
            [
                "SK_ID_CURR,SK_ID_PREV,NUM_INSTALMENT_NUMBER,DAYS_INSTALMENT,DAYS_ENTRY_PAYMENT,AMT_PAYMENT",
                "100001,300001,1,-390,-388,5000",
                "100001,300001,2,-360,-355,5200",
                "100004,300003,1,-290,-260,3100",
                "100007,300004,1,-70,-50,4000",
                "100010,300005,1,-110,-109,2800",
            ]
        ),
        "application_test.csv": csv_text(
            [
                "SK_ID_CURR,AMT_INCOME_TOTAL,AMT_CREDIT,NAME_CONTRACT_TYPE,DAYS_BIRTH,DAYS_DECISION",
                "110001,125000,250000,Cash loans,-15100,-8",
                "110002,180000,410000,Revolving loans,-16900,-11",
            ]
        ),
    }


def store_sales_fixture_files() -> dict[str, str]:
    return {
        "train.csv": csv_text(
            [
                "id,date,store_nbr,family,sales,onpromotion",
                "1,2026-01-01,1,GROCERY,120.0,0",
                "2,2026-01-02,1,GROCERY,131.0,1",
                "3,2026-01-03,1,GROCERY,118.0,0",
                "4,2026-01-04,1,GROCERY,140.0,1",
                "5,2026-01-05,1,GROCERY,150.0,0",
                "6,2026-01-06,1,GROCERY,147.0,0",
                "7,2026-01-01,2,GROCERY,90.0,0",
                "8,2026-01-02,2,GROCERY,95.0,0",
                "9,2026-01-03,2,GROCERY,102.0,1",
                "10,2026-01-04,2,GROCERY,108.0,1",
                "11,2026-01-05,2,GROCERY,111.0,0",
                "12,2026-01-06,2,GROCERY,109.0,0",
                "13,2026-01-01,1,PRODUCE,80.0,0",
                "14,2026-01-02,1,PRODUCE,82.0,0",
                "15,2026-01-03,1,PRODUCE,91.0,1",
                "16,2026-01-04,1,PRODUCE,96.0,1",
                "17,2026-01-05,1,PRODUCE,99.0,0",
                "18,2026-01-06,1,PRODUCE,97.0,0",
            ]
        ),
        "stores.csv": csv_text(
            [
                "store_nbr,city,state,type,cluster",
                "1,Quito,Pichincha,A,13",
                "2,Guayaquil,Guayas,B,8",
            ]
        ),
        "oil.csv": csv_text(
            [
                "date,dcoilwtico",
                "2026-01-01,68.2",
                "2026-01-02,68.5",
                "2026-01-03,69.1",
                "2026-01-04,68.7",
                "2026-01-05,70.0",
                "2026-01-06,70.4",
            ]
        ),
        "holidays_events.csv": csv_text(
            [
                "date,type,locale,locale_name,description,transferred",
                "2026-01-01,Holiday,National,Ecuador,New Year,false",
                "2026-01-04,Event,Local,Quito,Fixture Promo,false",
            ]
        ),
        "transactions.csv": csv_text(
            [
                "date,store_nbr,transactions",
                "2026-01-01,1,900",
                "2026-01-02,1,950",
                "2026-01-03,1,930",
                "2026-01-01,2,700",
                "2026-01-02,2,720",
                "2026-01-03,2,760",
            ]
        ),
        "test.csv": csv_text(
            [
                "id,date,store_nbr,family,onpromotion",
                "100,2026-01-07,1,GROCERY,0",
                "101,2026-01-07,2,GROCERY,1",
            ]
        ),
    }


def uci_bank_fixture_files() -> dict[str, str]:
    return {
        "bank-full.csv": "\n".join(
            [
                "age;job;marital;education;balance;duration;campaign;y",
                "40;admin.;married;secondary;1200;300;1;yes",
                "41;technician;single;tertiary;800;120;2;no",
                "42;admin.;married;secondary;1500;90;1;no",
                "43;services;divorced;primary;400;240;3;yes",
                "35;management;single;tertiary;2200;180;2;yes",
                "50;blue-collar;married;primary;300;80;4;no",
                "29;student;single;secondary;200;210;1;yes",
                "55;retired;married;secondary;3200;130;2;no",
            ]
        )
        + "\n"
    }


def csv_text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
