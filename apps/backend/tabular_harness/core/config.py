from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_display_name: str
    data_dir: Path
    database_url: str
    artifact_root: Path
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    auth_enabled: bool = False
    auth_cookie_name: str = "tablex_session"
    auth_session_days: int = 14
    auth_cookie_secure: bool = False
    bootstrap_user_email: str | None = None
    bootstrap_user_password: str | None = None
    google_auth_enabled: bool = False
    google_client_id: str | None = None
    local_worker_enabled: bool = True
    local_worker_interval_seconds: float = 1.0
    local_worker_max_jobs_per_wake: int = 3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("HARNESS_DATA_DIR", "data")).resolve()
    artifact_root = Path(os.getenv("HARNESS_ARTIFACT_ROOT", str(data_dir / "artifacts"))).resolve()
    database_url = os.getenv(
        "HARNESS_DATABASE_URL",
        f"sqlite:///{(data_dir / 'metadata' / 'app.db').resolve()}",
    )
    cors = os.getenv("HARNESS_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return Settings(
        app_display_name=os.getenv("APP_DISPLAY_NAME", "Tablex"),
        data_dir=data_dir,
        database_url=database_url,
        artifact_root=artifact_root,
        max_upload_bytes=int(os.getenv("HARNESS_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))),
        cors_origins=tuple(origin.strip() for origin in cors.split(",") if origin.strip()),
        auth_enabled=bool_env("TABLEX_AUTH_ENABLED", False),
        auth_cookie_name=os.getenv("TABLEX_AUTH_COOKIE_NAME", "tablex_session"),
        auth_session_days=int(os.getenv("TABLEX_AUTH_SESSION_DAYS", "14")),
        auth_cookie_secure=bool_env("TABLEX_AUTH_COOKIE_SECURE", False),
        bootstrap_user_email=os.getenv("TABLEX_BOOTSTRAP_EMAIL") or None,
        bootstrap_user_password=os.getenv("TABLEX_BOOTSTRAP_PASSWORD") or None,
        google_auth_enabled=bool_env("TABLEX_GOOGLE_AUTH_ENABLED", False),
        google_client_id=os.getenv("TABLEX_GOOGLE_CLIENT_ID") or None,
        local_worker_enabled=bool_env("TABLEX_LOCAL_WORKER_ENABLED", True),
        local_worker_interval_seconds=float(os.getenv("TABLEX_LOCAL_WORKER_INTERVAL_SECONDS", "1.0")),
        local_worker_max_jobs_per_wake=int(os.getenv("TABLEX_LOCAL_WORKER_MAX_JOBS_PER_WAKE", "3")),
    )


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "metadata").mkdir(parents=True, exist_ok=True)
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
