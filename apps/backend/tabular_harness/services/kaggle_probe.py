from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, cast

KAGGLE_API_BASE_URL = "https://www.kaggle.com/api/v1"
KAGGLE_ENV_KEYS = ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY")
MAX_PROBE_RESPONSE_BYTES = 512 * 1024
DEFAULT_KAGGLE_DOWNLOAD_MAX_TOTAL_BYTES = 500 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class KaggleAuthCandidate:
    credential_source: str
    auth_scheme: str
    username_available: bool
    authorization_header: str = field(repr=False)

    def safe_summary(self) -> dict[str, Any]:
        return {
            "credential_source": self.credential_source,
            "auth_scheme": self.auth_scheme,
            "username_available": self.username_available,
        }


UrlOpener = Callable[[urllib.request.Request, float], Any]


def probe_kaggle_benchmark_access(
    benchmark: dict[str, Any],
    *,
    timeout_seconds: float = 15.0,
    env: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    slug = kaggle_competition_slug(benchmark)
    if not slug:
        raise ValueError("Kaggle credential probe is only supported for Kaggle competition benchmarks with a slug")

    candidates, credential_state = build_kaggle_auth_candidates(env=env, env_files=env_files)
    checked_at = datetime.now(timezone.utc).isoformat()
    endpoint = f"{KAGGLE_API_BASE_URL}/competitions/data/list/{urllib.parse.quote(slug)}"
    if not candidates:
        return kaggle_probe_payload(
            benchmark=benchmark,
            slug=slug,
            checked_at=checked_at,
            credential_state=credential_state,
            endpoint=endpoint,
            network_accessed=False,
            probe={
                "status": "not_configured",
                "http_status": None,
                "can_access_competition_files": False,
                "file_count": None,
                "attempt_count": 0,
                "attempts": [],
            },
            next_actions=[
                "Set Kaggle credentials in the harness process environment or gitignored .env, then run the probe again.",
                "Use KAGGLE_USERNAME with KAGGLE_API_TOKEN, JSON KAGGLE_API_TOKEN, or legacy KAGGLE_USERNAME plus KAGGLE_KEY.",
                "Do not paste Kaggle credentials into prompts, AgentTaskContracts, runner workspaces, or artifacts.",
            ],
        )

    effective_opener = opener or default_urlopen
    attempts: list[dict[str, Any]] = []
    final_probe: dict[str, Any] | None = None
    for candidate in candidates:
        attempt = run_probe_attempt(
            endpoint=endpoint,
            candidate=candidate,
            timeout_seconds=timeout_seconds,
            opener=effective_opener,
        )
        attempts.append(attempt)
        status = str(attempt["status"])
        if status != "unauthorized":
            final_probe = attempt
            break

    if final_probe is None:
        final_probe = attempts[-1]
    final_status = str(final_probe["status"])
    can_access = final_status == "ok"
    probe = {
        "status": final_status,
        "http_status": final_probe.get("http_status"),
        "can_access_competition_files": can_access,
        "file_count": final_probe.get("file_count"),
        "attempt_count": len(attempts),
        "attempts": attempts,
    }
    return kaggle_probe_payload(
        benchmark=benchmark,
        slug=slug,
        checked_at=checked_at,
        credential_state=credential_state,
        endpoint=endpoint,
        network_accessed=True,
        probe=probe,
        next_actions=kaggle_probe_next_actions(final_status),
    )


def fetch_kaggle_competition_inventory(
    benchmark: dict[str, Any],
    *,
    timeout_seconds: float = 15.0,
    env: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    slug = kaggle_competition_slug(benchmark)
    if not slug:
        raise ValueError("Kaggle inventory is only supported for Kaggle competition benchmarks with a slug")

    candidates, credential_state = build_kaggle_auth_candidates(env=env, env_files=env_files)
    checked_at = datetime.now(timezone.utc).isoformat()
    endpoint = f"{KAGGLE_API_BASE_URL}/competitions/data/list/{urllib.parse.quote(slug)}"
    if not candidates:
        return kaggle_inventory_payload(
            benchmark=benchmark,
            slug=slug,
            checked_at=checked_at,
            credential_state=credential_state,
            endpoint=endpoint,
            network_accessed=False,
            inventory={
                "status": "not_configured",
                "http_status": None,
                "file_count": 0,
                "total_size_bytes": None,
                "files": [],
                "required_present_count": 0,
                "required_missing_count": len(expected_file_specs(benchmark, required=True)),
                "recommended_present_count": 0,
                "holdout_file_count": 0,
                "missing_required": expected_file_specs(benchmark, required=True),
                "attempt_count": 0,
                "attempts": [],
            },
            next_actions=[
                "Set Kaggle credentials in the harness process environment or gitignored .env, then fetch inventory again.",
                "Do not pass credentials to agents or runner workspaces.",
            ],
        )

    effective_opener = opener or default_urlopen
    attempts: list[dict[str, Any]] = []
    final_attempt: dict[str, Any] | None = None
    for candidate in candidates:
        attempt = run_inventory_attempt(
            endpoint=endpoint,
            candidate=candidate,
            timeout_seconds=timeout_seconds,
            opener=effective_opener,
        )
        attempts.append(attempt)
        if str(attempt["status"]) != "unauthorized":
            final_attempt = attempt
            break

    if final_attempt is None:
        final_attempt = attempts[-1]
    status = str(final_attempt["status"])
    raw_files = cast(list[dict[str, Any]], final_attempt.get("raw_files") or [])
    inventory = build_inventory_summary(
        benchmark=benchmark,
        status=status,
        http_status=cast(int | None, final_attempt.get("http_status")),
        files=raw_files,
        attempts=attempts,
    )
    return kaggle_inventory_payload(
        benchmark=benchmark,
        slug=slug,
        checked_at=checked_at,
        credential_state=credential_state,
        endpoint=endpoint,
        network_accessed=True,
        inventory=inventory,
        next_actions=kaggle_inventory_next_actions(inventory),
    )


def download_kaggle_selected_files(
    benchmark: dict[str, Any],
    *,
    root: Path,
    selected_files: Sequence[str] | None = None,
    include_required: bool = True,
    include_recommended: bool = False,
    include_holdout: bool = False,
    overwrite: bool = False,
    max_total_bytes: int = DEFAULT_KAGGLE_DOWNLOAD_MAX_TOTAL_BYTES,
    timeout_seconds: float = 60.0,
    env: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    slug = kaggle_competition_slug(benchmark)
    if not slug:
        raise ValueError("Kaggle download is only supported for Kaggle competition benchmarks with a slug")
    if max_total_bytes <= 0:
        raise ValueError("max_total_bytes must be positive")

    root.mkdir(parents=True, exist_ok=True)
    candidates, credential_state = build_kaggle_auth_candidates(env=env, env_files=env_files)
    checked_at = datetime.now(timezone.utc).isoformat()
    inventory_endpoint = f"{KAGGLE_API_BASE_URL}/competitions/data/list/{urllib.parse.quote(slug)}"
    selected = [item for item in (selected_files or []) if str(item).strip()]
    request_policy = {
        "selected_files": selected,
        "include_required": include_required,
        "include_recommended": include_recommended,
        "include_holdout": include_holdout,
        "overwrite": overwrite,
        "max_total_bytes": max_total_bytes,
    }
    if not candidates:
        return kaggle_download_payload(
            benchmark=benchmark,
            slug=slug,
            checked_at=checked_at,
            credential_state=credential_state,
            network_accessed=False,
            root=root,
            request_policy=request_policy,
            download={
                "status": "not_configured",
                "inventory_status": "not_configured",
                "planned_file_count": 0,
                "downloaded_count": 0,
                "skipped_count": 0,
                "downloaded_bytes": 0,
                "downloaded_files": [],
                "skipped_files": [],
                "attempts": [],
            },
            next_actions=[
                "Set Kaggle credentials in the harness process environment or gitignored .env, then retry download planning.",
            ],
        )

    effective_opener = opener or default_urlopen
    inventory_attempts: list[dict[str, Any]] = []
    active_candidate: KaggleAuthCandidate | None = None
    raw_files: list[dict[str, Any]] = []
    inventory_status = "not_configured"
    inventory_http_status: int | None = None
    for candidate in candidates:
        attempt = run_inventory_attempt(
            endpoint=inventory_endpoint,
            candidate=candidate,
            timeout_seconds=timeout_seconds,
            opener=effective_opener,
        )
        inventory_attempts.append({key: value for key, value in attempt.items() if key != "raw_files"})
        inventory_status = str(attempt["status"])
        inventory_http_status = cast(int | None, attempt.get("http_status"))
        if inventory_status == "ok":
            active_candidate = candidate
            raw_files = cast(list[dict[str, Any]], attempt.get("raw_files") or [])
            break
        if inventory_status != "unauthorized":
            break

    inventory = build_inventory_summary(
        benchmark=benchmark,
        status=inventory_status,
        http_status=inventory_http_status,
        files=raw_files,
        attempts=inventory_attempts,
    )
    if active_candidate is None:
        return kaggle_download_payload(
            benchmark=benchmark,
            slug=slug,
            checked_at=checked_at,
            credential_state=credential_state,
            network_accessed=True,
            root=root,
            request_policy=request_policy,
            download={
                "status": inventory_status,
                "inventory_status": inventory_status,
                "inventory_http_status": inventory_http_status,
                "planned_file_count": 0,
                "downloaded_count": 0,
                "skipped_count": 0,
                "downloaded_bytes": 0,
                "downloaded_files": [],
                "skipped_files": [
                    {
                        "reason": "inventory_unavailable",
                        "inventory_status": inventory_status,
                        "http_status": inventory_http_status,
                    }
                ],
                "attempts": inventory_attempts,
            },
            next_actions=kaggle_download_next_actions(inventory_status),
        )

    plan = plan_kaggle_download_files(
        inventory=inventory,
        selected_files=selected,
        include_required=include_required,
        include_recommended=include_recommended,
        include_holdout=include_holdout,
    )
    downloaded_files: list[dict[str, Any]] = []
    skipped_files: list[dict[str, Any]] = list(plan["skipped_files"])
    downloaded_bytes = 0
    for planned in plan["files"]:
        file_name = str(planned["name"])
        relative_path = safe_kaggle_relative_path(file_name)
        if relative_path is None:
            skipped_files.append({**planned, "reason": "unsafe_relative_path"})
            continue
        destination = root / relative_path
        if destination.exists() and not overwrite:
            skipped_files.append(
                {
                    **planned,
                    "reason": "exists",
                    "relative_path": str(relative_path),
                    "existing_size_bytes": destination.stat().st_size,
                }
            )
            continue
        expected_size = planned.get("size_bytes")
        if isinstance(expected_size, int) and downloaded_bytes + expected_size > max_total_bytes:
            skipped_files.append(
                {
                    **planned,
                    "reason": "would_exceed_max_total_bytes",
                    "max_total_bytes": max_total_bytes,
                    "downloaded_bytes_before_file": downloaded_bytes,
                }
            )
            continue
        remaining_bytes = max_total_bytes - downloaded_bytes
        try:
            result = download_one_kaggle_file(
                slug=slug,
                file_name=file_name,
                destination=destination,
                candidate=active_candidate,
                timeout_seconds=timeout_seconds,
                opener=effective_opener,
                max_file_bytes=remaining_bytes,
            )
        except (TimeoutError, urllib.error.URLError, OSError, urllib.error.HTTPError, ValueError) as exc:
            skipped_files.append(
                {
                    **planned,
                    "reason": "download_error",
                    "error_type": type(exc).__name__,
                    "relative_path": str(relative_path),
                }
            )
            continue
        downloaded_bytes += int(result["size_bytes"])
        downloaded_files.append(
            {
                **planned,
                **result,
                "relative_path": str(relative_path),
            }
        )

    status = "completed" if downloaded_files and not skipped_files else "partial" if downloaded_files else "no_files_downloaded"
    download = {
        "status": status,
        "inventory_status": inventory_status,
        "inventory_http_status": inventory_http_status,
        "inventory_file_count": inventory["file_count"],
        "planned_file_count": len(plan["files"]),
        "downloaded_count": len(downloaded_files),
        "skipped_count": len(skipped_files),
        "downloaded_bytes": downloaded_bytes,
        "downloaded_files": downloaded_files,
        "skipped_files": skipped_files,
        "attempts": inventory_attempts,
    }
    return kaggle_download_payload(
        benchmark=benchmark,
        slug=slug,
        checked_at=checked_at,
        credential_state=credential_state,
        network_accessed=True,
        root=root,
        request_policy=request_policy,
        download=download,
        next_actions=kaggle_download_next_actions(status),
    )


def default_urlopen(request: urllib.request.Request, timeout_seconds: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout_seconds)


def run_probe_attempt(
    *,
    endpoint: str,
    candidate: KaggleAuthCandidate,
    timeout_seconds: float,
    opener: UrlOpener,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": candidate.authorization_header,
            "User-Agent": "Tablex/0.1 KaggleCredentialProbe",
        },
        method="GET",
    )
    attempt_base = candidate.safe_summary()
    try:
        response = opener(request, timeout_seconds)
        try:
            status = int(getattr(response, "status", getattr(response, "code", 200)))
            body = cast(bytes, response.read(MAX_PROBE_RESPONSE_BYTES))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return {
            **attempt_base,
            "status": "ok" if status == 200 else "http_error",
            "http_status": status,
            "file_count": extract_kaggle_file_count(body) if status == 200 else None,
        }
    except urllib.error.HTTPError as exc:
        return {
            **attempt_base,
            "status": classify_http_status(exc.code),
            "http_status": int(exc.code),
            "file_count": None,
        }
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return {
            **attempt_base,
            "status": "network_error",
            "http_status": None,
            "file_count": None,
            "error_type": type(exc).__name__,
        }


def run_inventory_attempt(
    *,
    endpoint: str,
    candidate: KaggleAuthCandidate,
    timeout_seconds: float,
    opener: UrlOpener,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": candidate.authorization_header,
            "User-Agent": "Tablex/0.1 KaggleInventory",
        },
        method="GET",
    )
    attempt_base = candidate.safe_summary()
    try:
        response = opener(request, timeout_seconds)
        try:
            status = int(getattr(response, "status", getattr(response, "code", 200)))
            body = cast(bytes, response.read(MAX_PROBE_RESPONSE_BYTES))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        files = extract_kaggle_files(body) if status == 200 else []
        return {
            **attempt_base,
            "status": "ok" if status == 200 else "http_error",
            "http_status": status,
            "file_count": len(files) if status == 200 else None,
            "raw_files": files,
        }
    except urllib.error.HTTPError as exc:
        return {
            **attempt_base,
            "status": classify_http_status(exc.code),
            "http_status": int(exc.code),
            "file_count": None,
            "raw_files": [],
        }
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return {
            **attempt_base,
            "status": "network_error",
            "http_status": None,
            "file_count": None,
            "raw_files": [],
            "error_type": type(exc).__name__,
        }


def build_kaggle_auth_candidates(
    *,
    env: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
) -> tuple[list[KaggleAuthCandidate], dict[str, Any]]:
    values = load_kaggle_env(env=env, env_files=env_files)
    token = values.get("KAGGLE_API_TOKEN", "").strip()
    username = values.get("KAGGLE_USERNAME", "").strip()
    legacy_key = values.get("KAGGLE_KEY", "").strip()
    warnings: list[str] = []
    candidates: list[KaggleAuthCandidate] = []

    if token:
        json_pair = parse_json_api_token(token)
        pair = json_pair or parse_colon_api_token(token)
        if pair is not None:
            pair_username, pair_key = pair
            candidates.append(
                basic_candidate(
                    credential_source="kaggle_api_token_json" if json_pair else "kaggle_api_token_pair",
                    username=pair_username,
                    key=pair_key,
                )
            )
        else:
            if username:
                candidates.append(
                    basic_candidate(
                        credential_source="kaggle_username_with_api_token",
                        username=username,
                        key=token,
                    )
                )
            candidates.append(
                KaggleAuthCandidate(
                    credential_source="kaggle_api_token_bearer",
                    auth_scheme="bearer",
                    username_available=bool(username),
                    authorization_header=f"Bearer {token}",
                )
            )
            if not username:
                warnings.append(
                    "Opaque KAGGLE_API_TOKEN is available; if Kaggle expects API-key basic auth, also set KAGGLE_USERNAME."
                )

    if username and legacy_key:
        candidates.append(
            basic_candidate(
                credential_source="kaggle_username_key",
                username=username,
                key=legacy_key,
            )
        )

    candidates = dedupe_candidates(candidates)
    missing = [] if candidates else ["KAGGLE_API_TOKEN or KAGGLE_USERNAME plus KAGGLE_KEY"]
    credential_state = {
        "available": bool(candidates),
        "candidate_count": len(candidates),
        "credential_sources": [candidate.credential_source for candidate in candidates],
        "auth_schemes": sorted({candidate.auth_scheme for candidate in candidates}),
        "username_available": bool(username) or any(candidate.username_available for candidate in candidates),
        "missing": missing,
        "warnings": warnings,
        "values_exposed": False,
    }
    return candidates, credential_state


def load_kaggle_env(
    *,
    env: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    source_env = os.environ if env is None else env
    files = default_dotenv_candidates(source_env) if env_files is None else env_files
    for path in files:
        values.update(read_dotenv_values(path))
    for key in KAGGLE_ENV_KEYS:
        value = source_env.get(key)
        if value is not None:
            values[key] = value
    return {key: value for key, value in values.items() if key in KAGGLE_ENV_KEYS and value.strip()}


def default_dotenv_candidates(env: Mapping[str, str]) -> list[Path]:
    candidates: list[Path] = []
    configured = env.get("TABLEX_DOTENV_PATH")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parents[4] / ".env")
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            deduped.append(resolved)
            seen.add(resolved)
    return deduped


def read_dotenv_values(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if key not in KAGGLE_ENV_KEYS:
            continue
        values[key] = strip_dotenv_value(value.strip())
    return values


def strip_dotenv_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_json_api_token(token: str) -> tuple[str, str] | None:
    if not token.startswith("{"):
        return None
    try:
        payload = json.loads(token)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    username = payload.get("username")
    key = payload.get("key")
    if isinstance(username, str) and isinstance(key, str) and username.strip() and key.strip():
        return username.strip(), key.strip()
    return None


def parse_colon_api_token(token: str) -> tuple[str, str] | None:
    if "\n" in token or ":" not in token:
        return None
    username, key = token.split(":", 1)
    if username.strip() and key.strip():
        return username.strip(), key.strip()
    return None


def basic_candidate(*, credential_source: str, username: str, key: str) -> KaggleAuthCandidate:
    encoded = base64.b64encode(f"{username}:{key}".encode()).decode("ascii")
    return KaggleAuthCandidate(
        credential_source=credential_source,
        auth_scheme="basic",
        username_available=bool(username),
        authorization_header=f"Basic {encoded}",
    )


def dedupe_candidates(candidates: list[KaggleAuthCandidate]) -> list[KaggleAuthCandidate]:
    deduped: list[KaggleAuthCandidate] = []
    seen_headers: set[str] = set()
    for candidate in candidates:
        if candidate.authorization_header in seen_headers:
            continue
        deduped.append(candidate)
        seen_headers.add(candidate.authorization_header)
    return deduped


def kaggle_competition_slug(benchmark: dict[str, Any]) -> str | None:
    configured = benchmark.get("competition_slug")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    source_url = str(benchmark.get("source_url") or "")
    parsed = urllib.parse.urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]
    if "competitions" in parts:
        index = parts.index("competitions")
        if len(parts) > index + 1:
            return parts[index + 1]
    return None


def classify_http_status(status: int) -> str:
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden_or_rules_required"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "http_error"


def extract_kaggle_file_count(body: bytes) -> int | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        files = payload.get("files") or payload.get("items")
        if isinstance(files, list):
            return len(files)
    return None


def extract_kaggle_files(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    raw_files: Any
    if isinstance(payload, list):
        raw_files = payload
    elif isinstance(payload, dict):
        raw_files = payload.get("files") or payload.get("items") or []
    else:
        raw_files = []
    files: list[dict[str, Any]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        name = first_string(item, ["name", "fileName", "ref", "filename"])
        if not name:
            continue
        size_bytes = first_int(item, ["totalBytes", "size", "sizeBytes", "total_bytes"])
        files.append(
            {
                "name": name,
                "size_bytes": size_bytes,
                "creation_date": first_string(item, ["creationDate", "creation_date"]),
                "source": "kaggle_competition_file_list",
            }
        )
    return files


def first_string(item: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def first_int(item: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def build_inventory_summary(
    *,
    benchmark: dict[str, Any],
    status: str,
    http_status: int | None,
    files: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    required_specs = expected_file_specs(benchmark, required=True)
    recommended_specs = expected_file_specs(benchmark, required=False)
    all_specs = [*required_specs, *recommended_specs]
    matched_spec_ids: set[str] = set()
    enriched_files: list[dict[str, Any]] = []
    for file in sorted(files, key=lambda item: str(item.get("name") or "")):
        match = match_expected_file(str(file["name"]), all_specs)
        if match:
            matched_spec_ids.add(str(match["spec_id"]))
        enriched = dict(file)
        enriched.update(
            {
                "requirement": match["requirement"] if match else "extra",
                "role": match["role"] if match else "extra",
                "description": match["description"] if match else None,
                "configured_expected": bool(match),
                "match_pattern": match["pattern"] if match else None,
            }
        )
        enriched_files.append(enriched)
    missing_required = [spec for spec in required_specs if spec["spec_id"] not in matched_spec_ids]
    total_size_bytes = sum(file["size_bytes"] for file in enriched_files if isinstance(file.get("size_bytes"), int))
    holdout_file_count = sum(1 for file in enriched_files if "holdout" in str(file.get("role") or ""))
    return {
        "status": status,
        "http_status": http_status,
        "file_count": len(enriched_files),
        "total_size_bytes": total_size_bytes if enriched_files else None,
        "files": enriched_files,
        "required_present_count": len(required_specs) - len(missing_required),
        "required_missing_count": len(missing_required),
        "recommended_present_count": sum(
            1
            for spec in recommended_specs
            if spec["spec_id"] in matched_spec_ids and "holdout" not in str(spec.get("role") or "")
        ),
        "holdout_file_count": holdout_file_count,
        "missing_required": missing_required,
        "attempt_count": len(attempts),
        "attempts": [
            {key: value for key, value in attempt.items() if key != "raw_files"} for attempt in attempts
        ],
    }


def expected_file_specs(benchmark: dict[str, Any], *, required: bool) -> list[dict[str, Any]]:
    key = "required_files" if required else "recommended_files"
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(benchmark.get(key) or []):
        if not isinstance(item, dict):
            continue
        patterns = expected_patterns(item)
        if not patterns:
            continue
        specs.append(
            {
                "spec_id": f"{key}:{index}",
                "requirement": "required" if required else "recommended",
                "role": str(item.get("role") or "unspecified"),
                "description": item.get("description") if isinstance(item.get("description"), str) else None,
                "patterns": patterns,
            }
        )
    return specs


def expected_patterns(spec: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    path = spec.get("path")
    if isinstance(path, str) and path.strip():
        patterns.append(path.strip())
    candidates = spec.get("path_candidates")
    if isinstance(candidates, list):
        patterns.extend(str(candidate).strip() for candidate in candidates if str(candidate).strip())
    glob = spec.get("glob")
    if isinstance(glob, str) and glob.strip():
        patterns.append(glob.strip())
    return list(dict.fromkeys(patterns))


def match_expected_file(name: str, specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    file_basename = Path(name).name
    for spec in specs:
        for pattern in spec["patterns"]:
            pattern_basename = Path(str(pattern)).name
            if name == pattern or file_basename == pattern_basename or fnmatch(name, str(pattern)) or fnmatch(file_basename, pattern_basename):
                return {
                    "spec_id": spec["spec_id"],
                    "requirement": spec["requirement"],
                    "role": spec["role"],
                    "description": spec["description"],
                    "pattern": pattern,
                }
    return None


def plan_kaggle_download_files(
    *,
    inventory: dict[str, Any],
    selected_files: Sequence[str],
    include_required: bool,
    include_recommended: bool,
    include_holdout: bool,
) -> dict[str, Any]:
    selected = {str(item).strip() for item in selected_files if str(item).strip()}
    selected_basenames = {Path(item).name for item in selected}
    planned: list[dict[str, Any]] = []
    selected_matches: set[str] = set()
    for file in inventory.get("files", []):
        if not isinstance(file, dict):
            continue
        name = str(file.get("name") or "")
        role = str(file.get("role") or "")
        requirement = str(file.get("requirement") or "")
        is_selected = bool(selected and (name in selected or Path(name).name in selected_basenames))
        if is_selected:
            selected_matches.add(name)
            selected_matches.add(Path(name).name)
        should_include = is_selected
        should_include = should_include or (include_required and requirement == "required")
        should_include = should_include or (
            include_recommended
            and requirement == "recommended"
            and (include_holdout or "holdout" not in role)
        )
        if not should_include:
            continue
        planned.append(
            {
                "name": name,
                "size_bytes": file.get("size_bytes") if isinstance(file.get("size_bytes"), int) else None,
                "requirement": requirement,
                "role": role,
                "description": file.get("description") if isinstance(file.get("description"), str) else None,
                "match_pattern": file.get("match_pattern") if isinstance(file.get("match_pattern"), str) else None,
            }
        )
    skipped_files = [
        {"name": item, "reason": "selected_file_not_in_inventory"}
        for item in selected
        if item not in selected_matches and Path(item).name not in selected_matches
    ]
    return {"files": planned, "skipped_files": skipped_files}


def safe_kaggle_relative_path(name: str) -> Path | None:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or not pure.parts:
        return None
    if any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return Path(*pure.parts)


def download_one_kaggle_file(
    *,
    slug: str,
    file_name: str,
    destination: Path,
    candidate: KaggleAuthCandidate,
    timeout_seconds: float,
    opener: UrlOpener,
    max_file_bytes: int,
) -> dict[str, Any]:
    endpoint = (
        f"{KAGGLE_API_BASE_URL}/competitions/data/download/"
        f"{urllib.parse.quote(slug)}/{urllib.parse.quote(file_name, safe='')}"
    )
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/octet-stream",
            "Authorization": candidate.authorization_header,
            "User-Agent": "Tablex/0.1 KaggleSelectiveDownload",
        },
        method="GET",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f"{destination.name}.part")
    digest = hashlib.sha256()
    size_bytes = 0
    response = opener(request, timeout_seconds)
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_file_bytes:
                    raise ValueError("Downloaded file exceeded max_total_bytes")
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    archive_sha256 = digest.hexdigest()
    if zipfile.is_zipfile(temp_path):
        extracted = extract_expected_kaggle_zip_member(
            archive_path=temp_path,
            destination=destination,
            expected_name=file_name,
            max_extracted_bytes=max_file_bytes,
        )
        temp_path.unlink(missing_ok=True)
        return {
            **extracted,
            "archive_size_bytes": size_bytes,
            "archive_sha256": archive_sha256,
            "extracted_from_archive": True,
        }
    temp_path.replace(destination)
    return {
        "size_bytes": size_bytes,
        "sha256": archive_sha256,
        "extracted_from_archive": False,
    }


def extract_expected_kaggle_zip_member(
    *,
    archive_path: Path,
    destination: Path,
    expected_name: str,
    max_extracted_bytes: int,
) -> dict[str, Any]:
    expected_basename = Path(expected_name).name
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and safe_kaggle_relative_path(member.filename) is not None
            and (member.filename == expected_name or Path(member.filename).name == expected_basename)
        ]
        if not candidates:
            raise ValueError("Kaggle archive did not contain the expected file")
        member = sorted(candidates, key=lambda item: (Path(item.filename).name != expected_basename, item.file_size))[0]
        if member.file_size > max_extracted_bytes:
            raise ValueError("Extracted file would exceed max_total_bytes")
        digest = hashlib.sha256()
        size_bytes = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_extract = destination.with_name(f"{destination.name}.extracting")
        try:
            with archive.open(member, "r") as source, temp_extract.open("wb") as target:
                while True:
                    chunk = source.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    if size_bytes > max_extracted_bytes:
                        raise ValueError("Extracted file exceeded max_total_bytes")
                    digest.update(chunk)
                    target.write(chunk)
            temp_extract.replace(destination)
        except Exception:
            if temp_extract.exists():
                temp_extract.unlink()
            raise
    return {
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
        "archive_member": member.filename,
    }


def kaggle_probe_payload(
    *,
    benchmark: dict[str, Any],
    slug: str,
    checked_at: str,
    credential_state: dict[str, Any],
    endpoint: str,
    network_accessed: bool,
    probe: dict[str, Any],
    next_actions: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "kaggle_credential_probe.v1",
        "benchmark_id": str(benchmark.get("id") or ""),
        "benchmark_name": str(benchmark.get("name") or ""),
        "source_kind": str(benchmark.get("source_kind") or ""),
        "competition_slug": slug,
        "checked_at": checked_at,
        "credential_status": credential_state,
        "request": {
            "endpoint_kind": "competition_data_list",
            "url_host": urllib.parse.urlparse(endpoint).netloc,
            "network_accessed": network_accessed,
        },
        "probe": probe,
        "safety": {
            "secret_value_logged": False,
            "secret_value_artifacted": False,
            "connector_credentials_materialized": False,
            "agent_runner_access": False,
            "agent_task_contract_access": False,
        },
        "next_actions": next_actions,
    }


def kaggle_download_payload(
    *,
    benchmark: dict[str, Any],
    slug: str,
    checked_at: str,
    credential_state: dict[str, Any],
    network_accessed: bool,
    root: Path,
    request_policy: dict[str, Any],
    download: dict[str, Any],
    next_actions: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "kaggle_selective_download_manifest.v1",
        "benchmark_id": str(benchmark.get("id") or ""),
        "benchmark_name": str(benchmark.get("name") or ""),
        "source_kind": str(benchmark.get("source_kind") or ""),
        "competition_slug": slug,
        "checked_at": checked_at,
        "root_path": str(root),
        "request_policy": request_policy,
        "credential_status": credential_state,
        "request": {
            "endpoint_kind": "competition_data_download",
            "url_host": urllib.parse.urlparse(KAGGLE_API_BASE_URL).netloc,
            "network_accessed": network_accessed,
        },
        "download": download,
        "safety": {
            "secret_value_logged": False,
            "secret_value_artifacted": False,
            "connector_credentials_materialized": False,
            "agent_runner_access": False,
            "agent_task_contract_access": False,
        },
        "next_actions": next_actions,
    }


def kaggle_inventory_payload(
    *,
    benchmark: dict[str, Any],
    slug: str,
    checked_at: str,
    credential_state: dict[str, Any],
    endpoint: str,
    network_accessed: bool,
    inventory: dict[str, Any],
    next_actions: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "kaggle_competition_file_inventory.v1",
        "benchmark_id": str(benchmark.get("id") or ""),
        "benchmark_name": str(benchmark.get("name") or ""),
        "source_kind": str(benchmark.get("source_kind") or ""),
        "competition_slug": slug,
        "checked_at": checked_at,
        "credential_status": credential_state,
        "request": {
            "endpoint_kind": "competition_data_list",
            "url_host": urllib.parse.urlparse(endpoint).netloc,
            "network_accessed": network_accessed,
        },
        "inventory": inventory,
        "safety": {
            "secret_value_logged": False,
            "secret_value_artifacted": False,
            "connector_credentials_materialized": False,
            "agent_runner_access": False,
            "agent_task_contract_access": False,
        },
        "next_actions": next_actions,
    }


def kaggle_probe_next_actions(status: str) -> list[str]:
    if status == "ok":
        return [
            "Competition file access is available to the harness process.",
            "Download or import can be implemented as a separate harness-owned step without passing credentials to agents.",
        ]
    if status == "forbidden_or_rules_required":
        return [
            "Open the Kaggle competition page with the user account and accept rules or request access, then rerun the probe.",
            "Keep credential values in the harness environment only; do not paste them into prompts or workspaces.",
        ]
    if status == "unauthorized":
        return [
            "Check whether KAGGLE_USERNAME and the API token/key match the Kaggle account.",
            "Regenerate the Kaggle API token if needed, then rerun the probe.",
        ]
    if status == "not_found":
        return ["Check the catalog competition_slug and source URL before attempting download."]
    if status == "rate_limited":
        return ["Wait for Kaggle API rate limits to clear, then rerun the probe."]
    if status == "network_error":
        return ["Check local network access to kaggle.com, then rerun the probe."]
    return ["Inspect the stored probe artifact and rerun after resolving the reported access issue."]


def kaggle_inventory_next_actions(inventory: dict[str, Any]) -> list[str]:
    status = str(inventory.get("status") or "")
    if status == "ok":
        required_missing = int(inventory.get("required_missing_count") or 0)
        if required_missing:
            return [
                "The Kaggle file list is reachable, but catalog-required files were not found by name.",
                "Review the inventory artifact before planning download/import.",
            ]
        return [
            "Use the inventory artifact to choose required, supporting, and holdout files before any managed download.",
            "Keep download execution harness-owned and do not pass credential values to AgentRunner workspaces.",
        ]
    if status == "forbidden_or_rules_required":
        return [
            "Open the Kaggle competition page with the user account and accept rules or request access, then fetch inventory again.",
        ]
    if status == "unauthorized":
        return ["Check Kaggle credential pairing, then fetch inventory again."]
    if status == "not_configured":
        return ["Set Kaggle credentials in the harness environment or gitignored .env, then fetch inventory again."]
    return ["Resolve the Kaggle access issue shown in the inventory artifact, then retry."]


def kaggle_download_next_actions(status: str) -> list[str]:
    if status == "completed":
        return ["Run benchmark local-status or import from the resolved benchmark root."]
    if status == "partial":
        return ["Review skipped files in the download manifest before importing or requesting more files."]
    if status == "no_files_downloaded":
        return ["Review the selection policy, existing files, and size cap; adjust if a download is still needed."]
    if status == "not_configured":
        return ["Set Kaggle credentials in the harness environment or gitignored .env, then retry."]
    if status == "forbidden_or_rules_required":
        return ["Accept the competition rules in Kaggle with the user account, then retry."]
    return ["Review the download manifest and retry after resolving the reported issue."]
