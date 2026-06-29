from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import duckdb
from sqlalchemy import select
from sqlalchemy.orm import Session

from tabular_harness.core.config import Settings
from tabular_harness.core.ids import new_id
from tabular_harness.models.entities import Artifact, DatasetSnapshot, Project
from tabular_harness.services.approach import store_json_artifact, store_text_artifact
from tabular_harness.services.artifacts import (
    LocalArtifactStore,
    create_lineage_edge,
    next_artifact_version,
    register_artifact,
)
from tabular_harness.services.profiler import quote_ident, read_sql

SUPPORTED_PRIMARY_SUFFIXES = {".csv", ".parquet"}
MAX_SUPPORTING_TABLE_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_PUBLIC_ARCHIVE_BYTES = 100 * 1024 * 1024
KEY_NAME_HINTS = ("id", "_id", "sk_id", "case_id", "transactionid", "order_id", "store_nbr", "user_id")
TIME_NAME_HINTS = ("date", "time", "dt", "timestamp")
LEAKAGE_NAME_HINTS = ("target", "label", "actual", "result", "final", "after", "post", "status")
SUPPORTED_FIXTURE_IDS = {
    "kaggle_home_credit_default_risk",
    "kaggle_store_sales_forecasting",
    "uci_bank_marketing",
    "uci_wine_quality",
}


@dataclass(frozen=True)
class BenchmarkFileMatch:
    spec: dict[str, Any]
    found_paths: list[Path]

    @property
    def found(self) -> bool:
        return bool(self.found_paths)


@dataclass(frozen=True)
class BenchmarkScenarioPackResult:
    pack: dict[str, Any]
    report_md: str
    pack_artifact: Artifact
    report_artifact: Artifact


@dataclass(frozen=True)
class SupportingTableStoreResult:
    artifacts: list[Artifact]
    skipped: list[dict[str, Any]]


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
    local_status = inspect_benchmark_local_files(benchmark, default_root) if include_status else None
    payload["default_local_path"] = str(default_root)
    payload["download_instructions"] = render_download_instructions(benchmark, default_root)
    payload["access"] = benchmark_access(benchmark)
    payload["fixture_available"] = benchmark.get("id") in SUPPORTED_FIXTURE_IDS
    payload["fixture_notes"] = fixture_notes(str(benchmark.get("id")))
    payload["source_card"] = benchmark_source_card(
        benchmark,
        settings=settings,
        local_path=None,
        local_status=local_status,
    )
    if include_status:
        payload["local_status"] = local_status
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


def benchmark_source_card(
    benchmark: dict[str, Any],
    *,
    settings: Settings,
    local_path: str | None = None,
    local_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmark_id = str(benchmark["id"])
    root = resolve_benchmark_root(settings, benchmark_id, local_path)
    status = local_status or inspect_benchmark_local_files(benchmark, root)
    source_card = as_dict(benchmark.get("source_card"))
    return {
        "schema_version": "benchmark_source_card.v1",
        "benchmark_id": benchmark_id,
        "name": benchmark["name"],
        "source_kind": benchmark["source_kind"],
        "source_url": benchmark["source_url"],
        "access": benchmark_access(benchmark),
        "source_verification": benchmark_source_verification(benchmark, source_card),
        "official_sources": official_sources(benchmark, source_card),
        "download": benchmark_download_card(benchmark, source_card),
        "table_bundle": benchmark_table_bundle(benchmark),
        "local_layout": {
            "default_root": str(default_benchmark_root(settings, benchmark_id)),
            "resolved_root": str(root),
            "primary_table": benchmark.get("primary_table") or {},
            "required_files": benchmark.get("required_files", []),
            "recommended_files": benchmark.get("recommended_files", []),
        },
        "import_readiness": benchmark_import_readiness(benchmark, root, status),
        "fixture": {
            "available": benchmark_id in SUPPORTED_FIXTURE_IDS,
            "notes": fixture_notes(benchmark_id),
            "policy": "Fixtures are synthetic smoke data and must not be used for benchmark score claims.",
        },
        "credential_probe": benchmark_credential_probe(benchmark),
        "credential_inventory": benchmark_credential_inventory(benchmark),
        "credential_policy": benchmark_credential_policy(benchmark),
        "safety_notes": benchmark_safety_notes(benchmark),
    }


def benchmark_access(benchmark: dict[str, Any]) -> dict[str, Any]:
    download = as_dict(benchmark.get("download"))
    configured = as_dict(benchmark.get("access"))
    requires_account = bool(configured.get("requires_account", download.get("requires_account", False)))
    download_urls = configured.get("download_urls") or download.get("download_urls") or []
    if configured.get("kind"):
        kind = str(configured["kind"])
    elif requires_account:
        kind = "credentialed_competition"
    elif download_urls:
        kind = "public_direct_download"
    else:
        kind = "manual_public"
    return {
        "kind": kind,
        "requires_account": requires_account,
        "requires_secret": bool(configured.get("requires_secret", requires_account)),
        "supports_direct_download": bool(configured.get("supports_direct_download", bool(download_urls))),
        "supports_fixture": benchmark.get("id") in SUPPORTED_FIXTURE_IDS,
        "data_files_committed": False,
        "agent_receives_credentials": False,
        "download_urls": download_urls,
    }


def as_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def official_sources(benchmark: dict[str, Any], source_card: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = source_card.get("official_sources")
    if isinstance(raw_sources, list) and raw_sources:
        return [cast(dict[str, Any], item) for item in raw_sources if isinstance(item, dict)]
    return [
        {
            "title": benchmark["name"],
            "url": benchmark["source_url"],
            "source_type": benchmark["source_kind"],
        }
    ]


def benchmark_source_verification(benchmark: dict[str, Any], source_card: dict[str, Any]) -> dict[str, Any]:
    sources = official_sources(benchmark, source_card)
    verified_at = source_card.get("verified_at") or benchmark.get("generated_at")
    return {
        "status": "verified_from_catalog_sources" if sources else "catalog_entry_only",
        "verified_at": verified_at,
        "source_count": len(sources),
        "source_types": sorted({str(source.get("source_type") or "unknown") for source in sources}),
        "access_checked": {
            "requires_account": benchmark_access(benchmark)["requires_account"],
            "supports_direct_download": benchmark_access(benchmark)["supports_direct_download"],
            "agent_receives_credentials": False,
        },
        "notes": source_card.get(
            "verification_notes",
            "Source metadata is catalog-verified; actual benchmark files remain user-managed unless a credential-free public downloader is enabled.",
        ),
    }


def benchmark_table_bundle(benchmark: dict[str, Any]) -> dict[str, Any]:
    primary = benchmark.get("primary_table") or {}
    required = [item for item in benchmark.get("required_files", []) if isinstance(item, dict)]
    recommended = [item for item in benchmark.get("recommended_files", []) if isinstance(item, dict)]
    all_specs = [*required, *recommended]
    roles: dict[str, int] = {}
    for spec in all_specs:
        role = str(spec.get("role") or "unspecified")
        roles[role] = roles.get(role, 0) + 1
    supporting_count = sum(count for role, count in roles.items() if "supporting" in role)
    holdout_count = sum(count for role, count in roles.items() if "holdout" in role or "test" in role)
    return {
        "kind": "multi_table_bundle" if supporting_count else "single_table_bundle",
        "primary_table": primary,
        "required_file_count": len(required),
        "recommended_file_count": len(recommended),
        "supporting_table_count": supporting_count,
        "holdout_table_count": holdout_count,
        "roles": roles,
        "join_key_hints": [
            value
            for value in [
                primary.get("entity_id_column"),
                primary.get("group_column"),
            ]
            if value
        ],
        "time_column_hint": primary.get("time_column"),
        "target_column": primary.get("target_column"),
        "feature_recipe_policy": (
            "supporting tables require a FeatureRecipe or AgentTask with prediction-time availability checks"
            if supporting_count
            else "single-table features can be planned from the profiled DatasetSnapshot"
        ),
    }


def benchmark_download_card(benchmark: dict[str, Any], source_card: dict[str, Any]) -> dict[str, Any]:
    download = dict(as_dict(benchmark.get("download")))
    configured_download = as_dict(source_card.get("download"))
    if configured_download:
        download.update(configured_download)
    download.setdefault("requires_account", benchmark_access(benchmark)["requires_account"])
    download.setdefault("download_urls", benchmark_access(benchmark)["download_urls"])
    return download


def benchmark_import_readiness(benchmark: dict[str, Any], root: Path, status: dict[str, Any]) -> dict[str, Any]:
    local_ready = bool(status.get("ready"))
    next_actions: list[str] = []
    access = benchmark_access(benchmark)
    if local_ready:
        next_actions.append("Import can run now from the resolved local root.")
    elif access["supports_fixture"]:
        next_actions.append("Generate the credential-free fixture for product smoke testing.")
    if not local_ready:
        if access["requires_account"]:
            if benchmark_credential_probe(benchmark)["supported"]:
                next_actions.append(
                    "Run the harness-only Kaggle credential probe to verify account access without exposing secrets to agents."
                )
                next_actions.append(
                    "Fetch the Kaggle file inventory before planning selective download or import."
                )
            next_actions.append("Download the benchmark outside Tablex with user-managed credentials, then place files under the local root.")
        elif access["supports_direct_download"]:
            next_actions.append("Download the public archive from the official URL, extract it, then place files under the local root.")
        else:
            next_actions.append("Prepare the required files manually under the local root.")
    return {
        "benchmark_id": benchmark["id"],
        "benchmark_name": benchmark["name"],
        "root_path": str(root),
        "local_ready": local_ready,
        "can_import_now": local_ready,
        "missing_required_count": int(status.get("required_missing_count") or 0),
        "missing_recommended_count": int(status.get("recommended_missing_count") or 0),
        "required_files": status.get("missing_required", []),
        "recommended_files": status.get("missing_recommended", []),
        "next_actions": next_actions,
        "credential_probe": benchmark_credential_probe(benchmark),
        "credential_inventory": benchmark_credential_inventory(benchmark),
        "credential_policy": benchmark_credential_policy(benchmark),
    }


def benchmark_credential_probe(benchmark: dict[str, Any]) -> dict[str, Any]:
    access = benchmark_access(benchmark)
    source_url = str(benchmark.get("source_url") or "")
    supports_kaggle_probe = (
        bool(access["requires_account"])
        and str(benchmark.get("source_kind") or "") == "kaggle_competition"
        and "kaggle.com/competitions/" in source_url
    )
    benchmark_id = str(benchmark.get("id") or "")
    return {
        "supported": supports_kaggle_probe,
        "status": "not_run",
        "job_type": "probe_kaggle_benchmark_access" if supports_kaggle_probe else None,
        "endpoint": f"/api/benchmarks/{benchmark_id}/kaggle/probe" if supports_kaggle_probe else None,
        "secret_boundary": "harness_process_only",
        "credential_sources": ["KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"] if supports_kaggle_probe else [],
        "credential_values_returned": False,
        "agent_receives_credentials": False,
        "artifact_contains_secret_values": False,
    }


def benchmark_credential_inventory(benchmark: dict[str, Any]) -> dict[str, Any]:
    probe = benchmark_credential_probe(benchmark)
    benchmark_id = str(benchmark.get("id") or "")
    return {
        "supported": bool(probe["supported"]),
        "status": "not_fetched",
        "job_type": "fetch_kaggle_competition_inventory" if probe["supported"] else None,
        "endpoint": f"/api/benchmarks/{benchmark_id}/kaggle/inventory" if probe["supported"] else None,
        "latest_endpoint": f"/api/benchmarks/{benchmark_id}/kaggle/inventory/latest" if probe["supported"] else None,
        "secret_boundary": "harness_process_only",
        "stores_file_names_and_sizes": bool(probe["supported"]),
        "credential_values_returned": False,
        "agent_receives_credentials": False,
        "artifact_contains_secret_values": False,
    }


def benchmark_credential_policy(benchmark: dict[str, Any]) -> dict[str, Any]:
    access = benchmark_access(benchmark)
    return {
        "secret_access": "harness_process_only_for_credential_probe" if benchmark_credential_probe(benchmark)["supported"] else "forbidden",
        "connector_credentials": "never_materialized",
        "dataset_credentials": "user_managed_outside_tablex" if access["requires_account"] else "not_required",
        "agent_task_contract_policy": "credentials are never inserted into prompts, AgentTaskContracts, or workspaces",
        "credential_probe_policy": "probe may read Kaggle env vars inside the harness process only; secret values are not returned or artifacted",
    }


def benchmark_safety_notes(benchmark: dict[str, Any]) -> list[str]:
    notes = [
        "Benchmark data files are user-managed and are not committed to the repository.",
        "Do not paste credentials into Tablex, prompts, AgentTaskContracts, or runner workspaces.",
        "Fixture data is for product smoke only and cannot support model quality claims.",
    ]
    notes.extend(str(item) for item in benchmark.get("risk_notes", []))
    return notes


def download_public_benchmark_archive(
    settings: Settings,
    benchmark_id: str,
    *,
    overwrite: bool = False,
    max_archive_bytes: int = MAX_PUBLIC_ARCHIVE_BYTES,
) -> dict[str, Any]:
    benchmark = raw_benchmark_dataset(benchmark_id)
    access = benchmark_access(benchmark)
    if access["requires_account"] or not access["supports_direct_download"]:
        raise ValueError("Managed public download is only available for credential-free direct-download benchmarks")
    url_entry = select_public_download_url(access)
    url = str(url_entry["url"])
    validate_public_download_url(url)
    root = default_benchmark_root(settings, benchmark_id)
    root.mkdir(parents=True, exist_ok=True)
    downloads_dir = root / "_downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    archive_type = str(url_entry.get("archive_type") or "zip").lower()
    archive_path = downloads_dir / public_archive_filename(benchmark_id, url, archive_type=archive_type)
    archive = download_file_limited(url, archive_path, max_bytes=max_archive_bytes)
    expected_files = expected_archive_filenames(benchmark, url_entry)
    if not expected_files:
        raise ValueError("No expected files are configured for public archive extraction")
    if archive_type == "zip":
        extracted, skipped = extract_expected_zip_files(
            archive_path=archive_path,
            root=root,
            expected_files=expected_files,
            overwrite=overwrite,
        )
    elif archive_type in {"csv", "parquet"}:
        extracted, skipped = place_direct_public_file(
            downloaded_path=archive_path,
            root=root,
            expected_files=expected_files,
            overwrite=overwrite,
        )
    else:
        raise ValueError(f"Unsupported public download archive_type: {archive_type}")
    local_status = inspect_benchmark_local_files(benchmark, root)
    if not extracted and not local_status["ready"]:
        raise ValueError("Public archive did not contain required benchmark files")
    return {
        "schema_version": "benchmark_public_download_manifest.v1",
        "benchmark_id": benchmark_id,
        "benchmark_name": benchmark["name"],
        "source_url": benchmark["source_url"],
        "download_url": url,
        "root_path": str(root),
        "overwrite": overwrite,
        "archive_type": archive_type,
        "archive": archive,
        "expected_files": sorted(expected_files),
        "extracted_files": extracted,
        "skipped_files": skipped,
        "local_status": local_status,
        "credential_policy": benchmark_credential_policy(benchmark),
        "safety": {
            "path_traversal": "zip members with absolute paths or '..' are skipped",
            "extraction_policy": "only configured expected zip members or one direct public file are flattened into the benchmark root",
            "max_archive_bytes": max_archive_bytes,
        },
    }


def select_public_download_url(access: dict[str, Any]) -> dict[str, Any]:
    urls = access.get("download_urls")
    if not isinstance(urls, list) or not urls:
        raise ValueError("No public download URL is configured for this benchmark")
    for item in urls:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            return cast(dict[str, Any], item)
    raise ValueError("No valid public download URL is configured for this benchmark")


def validate_public_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Public benchmark download URL must be http(s)")


def public_archive_filename(benchmark_id: str, url: str, *, archive_type: str) -> str:
    name = Path(urlparse(url).path).name or "archive.zip"
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in name)
    if archive_type == "zip" and not cleaned.lower().endswith(".zip"):
        cleaned = f"{cleaned}.zip"
    return f"{benchmark_id}_{cleaned}"


def download_file_limited(url: str, target_path: Path, *, max_bytes: int) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=30) as response, target_path.open("wb") as output:
        status = getattr(response, "status", None)
        if status is not None and int(status) >= 400:
            raise ValueError(f"Public download failed with HTTP status {status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"Public archive exceeds size limit of {max_bytes} bytes")
            digest.update(chunk)
            output.write(chunk)
    return {
        "path": str(target_path),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def expected_archive_filenames(benchmark: dict[str, Any], url_entry: dict[str, Any]) -> set[str]:
    filenames: set[str] = set()
    expected_files = url_entry.get("expected_files")
    if isinstance(expected_files, list):
        filenames.update(Path(str(item)).name for item in expected_files if str(item).strip())
    for spec in [*benchmark.get("required_files", []), *benchmark.get("recommended_files", [])]:
        if not isinstance(spec, dict):
            continue
        if spec.get("path"):
            filenames.add(Path(str(spec["path"])).name)
        for candidate in spec.get("path_candidates", []):
            filenames.add(Path(str(candidate)).name)
    return {name for name in filenames if name}


def extract_expected_zip_files(
    *,
    archive_path: Path,
    root: Path,
    expected_files: set[str],
    overwrite: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    extracted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Public archive is not a valid zip file") from exc
    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                skipped.append({"member": member.filename, "reason": "unsafe_path"})
                continue
            filename = member_path.name
            if filename not in expected_files:
                skipped.append({"member": member.filename, "reason": "not_expected"})
                continue
            target = root / filename
            if target.exists() and not overwrite:
                skipped.append({"member": member.filename, "path": filename, "reason": "exists"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with archive.open(member, "r") as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            extracted.append(
                {
                    "member": member.filename,
                    "path": filename,
                    "size_bytes": size,
                    "sha256": digest.hexdigest(),
                }
            )
    return extracted, skipped


def place_direct_public_file(
    *,
    downloaded_path: Path,
    root: Path,
    expected_files: set[str],
    overwrite: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(expected_files) != 1:
        raise ValueError("Direct public file downloads must configure exactly one expected file")
    filename = next(iter(expected_files))
    target = root / Path(filename).name
    if target.exists() and not overwrite:
        return [], [{"member": downloaded_path.name, "path": target.name, "reason": "exists"}]
    digest = hashlib.sha256()
    size = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with downloaded_path.open("rb") as source, target.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            output.write(chunk)
    return [
        {
            "member": downloaded_path.name,
            "path": target.name,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }
    ], []


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
        "source_access": benchmark_access(benchmark),
        "official_sources": official_sources(
            benchmark,
            as_dict(benchmark.get("source_card")),
        ),
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


def store_benchmark_supporting_table_artifacts(
    db: Session,
    *,
    store: LocalArtifactStore,
    project_id: str,
    benchmark: dict[str, Any],
    root: Path,
    primary_file: Path,
    relational_catalog_artifact: Artifact,
    max_files: int = 12,
    max_bytes: int = MAX_SUPPORTING_TABLE_ARTIFACT_BYTES,
) -> SupportingTableStoreResult:
    artifacts: list[Artifact] = []
    skipped: list[dict[str, Any]] = []
    table_files = collect_benchmark_table_files(benchmark, root, primary_file, max_tables=max_files + 1)
    for item in table_files:
        path = cast(Path, item["path"])
        if path.resolve() == primary_file.resolve():
            continue
        relative = relative_path(root, path)
        if path.suffix.lower() not in SUPPORTED_PRIMARY_SUFFIXES:
            skipped.append({"path": relative, "reason": "unsupported_format", "size_bytes": path.stat().st_size})
            continue
        size_bytes = path.stat().st_size
        if size_bytes > max_bytes:
            skipped.append({"path": relative, "reason": "exceeds_size_limit", "size_bytes": size_bytes})
            continue
        table_name = table_name_from_path(relative)
        artifact_name = f"{benchmark['id']}_{table_name}"
        version = next_artifact_version(db, project_id, "benchmark_supporting_table", artifact_name)
        artifact_dir, stored, content_hash = store.store_existing_file(
            org_id="local-org",
            project_id=project_id,
            asset_type="benchmark_supporting_table",
            name=artifact_name,
            version=version,
            source_path=path,
            filename=path.name,
            metadata={
                "project_id": project_id,
                "benchmark_id": benchmark["id"],
                "benchmark_name": benchmark.get("name"),
                "source_url": benchmark.get("source_url"),
                "relative_path": relative,
                "table_name": table_name,
                "role": item.get("role"),
                "relational_catalog_artifact_id": relational_catalog_artifact.id,
            },
        )
        artifact = register_artifact(
            db,
            project_id=project_id,
            asset_type="benchmark_supporting_table",
            name=artifact_name,
            uri=str(artifact_dir),
            content_hash=content_hash,
            size_bytes=stored.size_bytes,
            metadata={
                "primary_path": str(stored.path),
                "project_id": project_id,
                "benchmark_id": benchmark["id"],
                "benchmark_name": benchmark.get("name"),
                "source_url": benchmark.get("source_url"),
                "relative_path": relative,
                "table_name": table_name,
                "role": item.get("role"),
                "relational_catalog_artifact_id": relational_catalog_artifact.id,
            },
            version=version,
        )
        artifacts.append(artifact)
        create_lineage_edge(
            db,
            project_id=project_id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=relational_catalog_artifact.id,
            relation_type="cataloged_by",
        )
    return SupportingTableStoreResult(artifacts=artifacts, skipped=skipped)


def create_benchmark_scenario_pack(
    db: Session,
    *,
    store: LocalArtifactStore,
    project: Project,
    benchmark: dict[str, Any],
    local_status: dict[str, Any] | None = None,
    fixture: dict[str, Any] | None = None,
    dataset: DatasetSnapshot | None = None,
    supporting_table_artifacts: list[Artifact] | None = None,
    skipped_supporting_tables: list[dict[str, Any]] | None = None,
) -> BenchmarkScenarioPackResult:
    benchmark_id = str(benchmark["id"])
    dataset = dataset or latest_benchmark_dataset(db, project.id, benchmark_id) or latest_project_dataset(db, project.id)
    artifact_context = {
        "dataset_snapshot": latest_project_artifact(db, project.id, "dataset_snapshot"),
        "benchmark_import_manifest": latest_project_artifact(db, project.id, "benchmark_import_manifest", benchmark_id),
        "relational_catalog": latest_project_artifact(db, project.id, "relational_catalog", benchmark_id),
        "data_quality_gate": latest_project_artifact(db, project.id, "data_quality_gate"),
        "evaluation_scenario_comparison": latest_project_artifact(db, project.id, "evaluation_scenario_comparison"),
        "evaluation_approval_review": latest_project_artifact(db, project.id, "evaluation_approval_review"),
        "evaluation_spec": latest_project_artifact(db, project.id, "evaluation_spec"),
        "split_manifest": latest_project_artifact(db, project.id, "split_manifest"),
        "baseline_strategy_plan": latest_project_artifact(db, project.id, "baseline_strategy_plan"),
        "research_plan": latest_project_artifact(db, project.id, "research_plan"),
    }
    stored_supporting = supporting_table_artifacts
    if stored_supporting is None:
        stored_supporting = list(
            db.scalars(
                select(Artifact)
                .where(
                    Artifact.project_id == project.id,
                    Artifact.asset_type == "benchmark_supporting_table",
                    Artifact.metadata_json.contains(benchmark_id),
                )
                .order_by(Artifact.created_at.desc())
            ).all()
        )
    skipped_supporting_tables = skipped_supporting_tables or []
    scenario = scenario_metadata(benchmark)
    relational_metadata = artifact_metadata(artifact_context["relational_catalog"])
    pack: dict[str, Any] = {
        "schema_version": "benchmark_scenario_pack.v1",
        "project": {
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "target_column": project.target_column,
            "current_phase": project.current_phase,
        },
        "benchmark": benchmark_summary(benchmark),
        "scenario": scenario,
        "dataset": dataset_summary(dataset),
        "local_status": compact_local_status(local_status),
        "fixture": compact_fixture(fixture),
        "artifact_context": {key: artifact_ref(value) for key, value in artifact_context.items()},
        "supporting_table_artifacts": [artifact_ref(artifact) for artifact in stored_supporting],
        "skipped_supporting_tables": skipped_supporting_tables,
        "relational_summary": {
            "table_count": relational_metadata.get("table_count"),
            "relationship_count": relational_metadata.get("relationship_count"),
            "table_discovery_truncated": relational_metadata.get("table_discovery_truncated"),
        },
        "recommended_workflow": benchmark_workflow_steps(benchmark, scenario),
        "agent_handoff": benchmark_agent_handoff(benchmark, scenario),
        "reporting_expectations": benchmark_reporting_expectations(benchmark, scenario),
    }
    pack_artifact = store_json_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_scenario_pack",
        name=f"benchmark_scenario_pack_{benchmark_id}_{new_id('bsp')}",
        filename="benchmark_scenario_pack.json",
        payload=pack,
        metadata={
            "project_id": project.id,
            "benchmark_id": benchmark_id,
            "benchmark_name": benchmark.get("name"),
            "dataset_snapshot_id": dataset.id if dataset else None,
            "scenario_kind": scenario["kind"],
            "table_count": relational_metadata.get("table_count"),
            "relationship_count": relational_metadata.get("relationship_count"),
            "supporting_table_artifact_count": len(stored_supporting),
            "fixture_available": benchmark_id in SUPPORTED_FIXTURE_IDS,
        },
    )
    report_md = render_benchmark_scenario_report(pack)
    report_artifact = store_text_artifact(
        db,
        store,
        project_id=project.id,
        asset_type="benchmark_scenario_report",
        name=f"benchmark_scenario_report_{benchmark_id}_{new_id('bsr')}",
        filename="benchmark_scenario_report.md",
        text=report_md,
        metadata={
            "project_id": project.id,
            "benchmark_id": benchmark_id,
            "benchmark_name": benchmark.get("name"),
            "dataset_snapshot_id": dataset.id if dataset else None,
            "scenario_kind": scenario["kind"],
            "pack_artifact_id": pack_artifact.id,
        },
    )
    create_benchmark_scenario_lineage(
        db,
        project=project,
        dataset=dataset,
        pack_artifact=pack_artifact,
        report_artifact=report_artifact,
        context_artifacts=[artifact for artifact in artifact_context.values() if artifact is not None],
        supporting_artifacts=stored_supporting,
    )
    return BenchmarkScenarioPackResult(
        pack=pack,
        report_md=report_md,
        pack_artifact=pack_artifact,
        report_artifact=report_artifact,
    )


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


def latest_benchmark_dataset(db: Session, project_id: str, benchmark_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(
            DatasetSnapshot.project_id == project_id,
            DatasetSnapshot.source_type == "benchmark_catalog",
            DatasetSnapshot.source_ref.like(f"{benchmark_id}:%"),
        )
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_project_dataset(db: Session, project_id: str) -> DatasetSnapshot | None:
    return db.scalar(
        select(DatasetSnapshot)
        .where(DatasetSnapshot.project_id == project_id)
        .order_by(DatasetSnapshot.created_at.desc())
    )


def latest_project_artifact(
    db: Session, project_id: str, asset_type: str, benchmark_id: str | None = None
) -> Artifact | None:
    statement = select(Artifact).where(Artifact.project_id == project_id, Artifact.asset_type == asset_type)
    if benchmark_id is not None:
        statement = statement.where(Artifact.metadata_json.contains(benchmark_id))
    return db.scalar(statement.order_by(Artifact.created_at.desc()))


def artifact_metadata(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    try:
        return cast(dict[str, Any], json.loads(artifact.metadata_json))
    except json.JSONDecodeError:
        return {}


def artifact_ref(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None:
        return {"status": "missing", "artifact_id": None}
    metadata = artifact_metadata(artifact)
    return {
        "status": "available",
        "artifact_id": artifact.id,
        "asset_type": artifact.asset_type,
        "name": artifact.name,
        "version": artifact.version,
        "metadata": {
            key: metadata.get(key)
            for key in [
                "benchmark_id",
                "dataset_snapshot_id",
                "evaluation_spec_id",
                "split_manifest_id",
                "table_count",
                "relationship_count",
                "scenario_kind",
                "relative_path",
            ]
            if key in metadata
        },
        "preview_url": f"/api/artifacts/{artifact.id}/preview",
        "download_url": f"/api/artifacts/{artifact.id}/download",
    }


def benchmark_summary(benchmark: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": benchmark["id"],
        "name": benchmark["name"],
        "source_kind": benchmark["source_kind"],
        "source_url": benchmark["source_url"],
        "access": benchmark_access(benchmark),
        "official_sources": official_sources(
            benchmark,
            as_dict(benchmark.get("source_card")),
        ),
        "task_types": benchmark.get("task_types", []),
        "modality_tags": benchmark.get("modality_tags", []),
        "recommended_uses": benchmark.get("recommended_uses", []),
        "primary_table": benchmark.get("primary_table") or {},
        "evaluation_notes": benchmark.get("evaluation_notes"),
        "risk_notes": benchmark.get("risk_notes", []),
        "fixture_available": benchmark["id"] in SUPPORTED_FIXTURE_IDS,
        "fixture_notes": fixture_notes(str(benchmark["id"])),
    }


def dataset_summary(dataset: DatasetSnapshot | None) -> dict[str, Any]:
    if dataset is None:
        return {"status": "missing", "dataset_snapshot_id": None}
    return {
        "status": "available",
        "dataset_snapshot_id": dataset.id,
        "artifact_id": dataset.artifact_id,
        "source_type": dataset.source_type,
        "source_ref": dataset.source_ref,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema_hash": dataset.schema_hash,
        "data_hash": dataset.data_hash,
    }


def compact_local_status(local_status: dict[str, Any] | None) -> dict[str, Any]:
    if local_status is None:
        return {"status": "unknown"}
    return {
        "status": "ready" if local_status.get("ready") else "incomplete",
        "root_path": local_status.get("root_path"),
        "required_found_count": local_status.get("required_found_count"),
        "required_missing_count": local_status.get("required_missing_count"),
        "recommended_found_count": local_status.get("recommended_found_count"),
        "recommended_missing_count": local_status.get("recommended_missing_count"),
    }


def compact_fixture(fixture: dict[str, Any] | None) -> dict[str, Any]:
    if fixture is None:
        return {"status": "not_generated_in_this_pack"}
    return {
        "schema_version": fixture.get("schema_version"),
        "status": "available",
        "fixture_matches_expected": fixture.get("fixture_matches_expected"),
        "generated_file_count": len(fixture.get("generated_files", [])),
        "skipped_file_count": len(fixture.get("skipped_files", [])),
        "notes": fixture.get("notes"),
    }


def scenario_metadata(benchmark: dict[str, Any]) -> dict[str, Any]:
    explicit = benchmark.get("scenario")
    if isinstance(explicit, dict):
        return cast(dict[str, Any], explicit)
    tags = {str(tag) for tag in benchmark.get("modality_tags", [])}
    if "time_series" in tags:
        return {
            "kind": "time_series_forecasting",
            "validation_focus": "time_split_or_rolling_origin",
            "feature_focus": ["calendar_features", "lag_features", "rolling_statistics", "known_future_covariates"],
            "report_focus": ["forecast_horizon_errors", "time_slice_metrics", "leaderboard"],
        }
    if "multi_table" in tags:
        return {
            "kind": "multi_table_tabular",
            "validation_focus": "entity_or_time_aware_split_when_available",
            "feature_focus": ["relational_aggregations", "prediction_time_availability", "leakage_controls"],
            "report_focus": ["relationship_coverage", "feature_scenario_comparison", "leaderboard"],
        }
    return {
        "kind": "single_table_tabular",
        "validation_focus": "stratified_or_random_split_sanity",
        "feature_focus": ["categorical_encoding", "numeric_imputation", "leakage_controls"],
        "report_focus": ["baseline_sanity", "slice_metrics", "leaderboard"],
    }


def benchmark_workflow_steps(benchmark: dict[str, Any], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [
        {
            "step": "import_and_profile",
            "owner": "harness",
            "expected_artifacts": ["dataset_snapshot", "semantic_catalog", "profile_json", "understanding_md"],
        },
        {
            "step": "data_quality_gate",
            "owner": "harness",
            "expected_artifacts": ["data_quality_gate", "data_quality_report"],
        },
        {
            "step": "evaluation_design",
            "owner": "harness",
            "expected_artifacts": ["evaluation_scenario_comparison", "evaluation_approval_review", "evaluation_spec", "split_manifest"],
        },
        {
            "step": "research_and_strategy",
            "owner": "harness_with_future_runner",
            "expected_artifacts": ["research_plan", "baseline_strategy_plan"],
        },
    ]
    if scenario.get("kind") in {"multi_table_credit_risk", "multi_table_tabular"}:
        steps.append(
            {
                "step": "relational_feature_recipe",
                "owner": "agent_runner",
                "expected_artifacts": ["feature_recipe", "agent_task_report", "visualization_spec"],
                "guardrails": [
                    "aggregate supporting tables inside train folds",
                    "exclude holdout/test tables from training features",
                    "confirm prediction-time availability before joins",
                ],
            }
        )
    if scenario.get("kind") in {"retail_time_series", "time_series_forecasting"}:
        steps.append(
            {
                "step": "time_series_feature_recipe",
                "owner": "agent_runner",
                "expected_artifacts": ["feature_recipe", "run_report", "visualization_spec"],
                "guardrails": [
                    "derive lag and rolling features causally",
                    "respect forecast horizon and split manifest",
                    "separate known-future covariates from historical observations",
                ],
            }
        )
    steps.append(
        {
            "step": "report_and_visualize",
            "owner": "harness",
            "expected_artifacts": ["benchmark_scenario_report", "report", "visualization_spec", "insight_set"],
        }
    )
    return steps


def benchmark_agent_handoff(benchmark: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    primary_table = benchmark.get("primary_table") or {}
    return {
        "may_use_benchmark_context": True,
        "may_claim_external_benchmark_score": False,
        "fixture_score_policy": "Fixture results are product smoke checks, not benchmark performance claims.",
        "must_respect_split_manifest": True,
        "must_not_use_holdout_tables_for_training": True,
        "primary_entity_id_column": primary_table.get("entity_id_column"),
        "time_column": primary_table.get("time_column"),
        "group_column": primary_table.get("group_column"),
        "scenario_kind": scenario.get("kind"),
        "recommended_skill_queries": [
            f"{scenario.get('kind')} feature recipe leakage validation",
            f"{benchmark.get('name')} common validation pitfalls",
        ],
    }


def benchmark_reporting_expectations(benchmark: dict[str, Any], scenario: dict[str, Any]) -> list[str]:
    expectations = [
        "Separate fixture smoke results from real benchmark or production performance claims.",
        "Show which EvaluationSpec and SplitManifest constrained every metric.",
        "Report unresolved assumptions and whether they block deployment.",
        "Keep reports understandable inside Tablex without external dashboards.",
    ]
    expectations.extend(str(item).replace("_", " ") for item in scenario.get("report_focus", []))
    if benchmark.get("risk_notes"):
        expectations.append("Explicitly address benchmark risk notes and prediction-time availability.")
    return expectations


def render_benchmark_scenario_report(pack: dict[str, Any]) -> str:
    benchmark = pack["benchmark"]
    scenario = pack["scenario"]
    dataset = pack["dataset"]
    relational = pack["relational_summary"]
    lines = [
        f"# Benchmark Scenario Report: {benchmark['name']}",
        "",
        f"- Scenario kind: {scenario.get('kind')}",
        f"- Project: {pack['project']['name']} ({pack['project']['id']})",
        f"- DatasetSnapshot: {dataset.get('dataset_snapshot_id') or 'missing'}",
        f"- Local status: {pack['local_status'].get('status')}",
        f"- Access: {benchmark.get('access', {}).get('kind', benchmark.get('source_kind'))}",
        f"- Relational tables: {relational.get('table_count') or 'unknown'}",
        f"- Inferred relationships: {relational.get('relationship_count') or 0}",
        f"- Supporting table artifacts: {len(pack['supporting_table_artifacts'])}",
        "",
        "## Intended Use",
        "",
    ]
    uses = benchmark.get("recommended_uses") or []
    lines.extend([f"- {use}" for use in uses] or ["- Benchmark smoke and workflow validation."])
    lines.extend(["", "## Recommended Workflow", ""])
    for step in pack["recommended_workflow"]:
        lines.append(f"- {step['step']}: {', '.join(step.get('expected_artifacts', []))}")
    lines.extend(["", "## Agent Handoff", ""])
    handoff = pack["agent_handoff"]
    for key in [
        "fixture_score_policy",
        "must_respect_split_manifest",
        "must_not_use_holdout_tables_for_training",
        "scenario_kind",
    ]:
        lines.append(f"- {key}: {handoff.get(key)}")
    lines.extend(["", "## Artifact Context", ""])
    for key, ref in pack["artifact_context"].items():
        lines.append(f"- {key}: {ref.get('status')} {ref.get('artifact_id') or ''}".rstrip())
    lines.extend(["", "## Reporting Expectations", ""])
    lines.extend([f"- {item}" for item in pack["reporting_expectations"]])
    risk_notes = benchmark.get("risk_notes") or []
    if risk_notes:
        lines.extend(["", "## Risk Notes", ""])
        lines.extend([f"- {item}" for item in risk_notes])
    return "\n".join(lines).strip() + "\n"


def create_benchmark_scenario_lineage(
    db: Session,
    *,
    project: Project,
    dataset: DatasetSnapshot | None,
    pack_artifact: Artifact,
    report_artifact: Artifact,
    context_artifacts: list[Artifact],
    supporting_artifacts: list[Artifact],
) -> None:
    if dataset:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="dataset_snapshot",
            from_asset_id=dataset.id,
            to_asset_type="artifact",
            to_asset_id=pack_artifact.id,
            relation_type="informs",
        )
    for artifact in [*context_artifacts, *supporting_artifacts]:
        create_lineage_edge(
            db,
            project_id=project.id,
            from_asset_type="artifact",
            from_asset_id=artifact.id,
            to_asset_type="artifact",
            to_asset_id=pack_artifact.id,
            relation_type="informs",
        )
    create_lineage_edge(
        db,
        project_id=project.id,
        from_asset_type="artifact",
        from_asset_id=pack_artifact.id,
        to_asset_type="artifact",
        to_asset_id=report_artifact.id,
        relation_type="summarizes",
    )


def render_download_instructions(benchmark: dict[str, Any], default_root: Path) -> str:
    download = benchmark.get("download") or {}
    command = str(download.get("command") or "").replace("data/benchmarks", str(default_root.parent))
    if download.get("requires_account"):
        return (
            "Use a user-managed account outside Tablex. Do not paste Kaggle credentials into prompts, AgentTaskContracts, "
            "or runner workspaces. A harness-only probe can read KAGGLE_API_TOKEN or KAGGLE_USERNAME/KAGGLE_KEY from "
            "the process environment or gitignored .env without returning the values. "
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
    if benchmark_id == "uci_wine_quality":
        return "Generates a tiny semicolon-delimited wine quality fixture for credential-free public dataset smoke tests."
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
    if benchmark_id == "uci_wine_quality":
        return uci_wine_quality_fixture_files()
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


def uci_wine_quality_fixture_files() -> dict[str, str]:
    return {
        "winequality-red.csv": "\n".join(
            [
                "fixed acidity;volatile acidity;citric acid;residual sugar;chlorides;free sulfur dioxide;total sulfur dioxide;density;pH;sulphates;alcohol;quality",
                "7.4;0.70;0.00;1.9;0.076;11;34;0.9978;3.51;0.56;9.4;5",
                "7.8;0.88;0.00;2.6;0.098;25;67;0.9968;3.20;0.68;9.8;5",
                "7.8;0.76;0.04;2.3;0.092;15;54;0.9970;3.26;0.65;9.8;5",
                "11.2;0.28;0.56;1.9;0.075;17;60;0.9980;3.16;0.58;9.8;6",
                "7.4;0.66;0.00;1.8;0.075;13;40;0.9978;3.51;0.56;9.4;5",
                "7.9;0.60;0.06;1.6;0.069;15;59;0.9964;3.30;0.46;9.4;5",
                "7.3;0.65;0.00;1.2;0.065;15;21;0.9946;3.39;0.47;10.0;7",
                "7.8;0.58;0.02;2.0;0.073;9;18;0.9968;3.36;0.57;9.5;7",
            ]
        )
        + "\n",
        "winequality-white.csv": "\n".join(
            [
                "fixed acidity;volatile acidity;citric acid;residual sugar;chlorides;free sulfur dioxide;total sulfur dioxide;density;pH;sulphates;alcohol;quality",
                "7.0;0.27;0.36;20.7;0.045;45;170;1.0010;3.00;0.45;8.8;6",
                "6.3;0.30;0.34;1.6;0.049;14;132;0.9940;3.30;0.49;9.5;6",
                "8.1;0.28;0.40;6.9;0.050;30;97;0.9951;3.26;0.44;10.1;6",
            ]
        )
        + "\n",
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
