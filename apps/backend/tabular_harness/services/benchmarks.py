from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from tabular_harness.core.config import Settings

SUPPORTED_PRIMARY_SUFFIXES = {".csv", ".parquet"}


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
