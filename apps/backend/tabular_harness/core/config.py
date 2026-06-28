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
    )


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "metadata").mkdir(parents=True, exist_ok=True)
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
