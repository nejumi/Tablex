from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

KAGGLE_API_BASE_URL = "https://www.kaggle.com/api/v1"
KAGGLE_ENV_KEYS = ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY")
MAX_PROBE_RESPONSE_BYTES = 512 * 1024


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
