from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tabular_harness.api.routes import router
from tabular_harness.core.config import Settings, get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.artifacts import LocalArtifactStore


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    engine = create_engine_for_settings(app_settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    app = FastAPI(title=f"{app_settings.app_display_name} API")
    app.state.settings = app_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.artifact_store = LocalArtifactStore(app_settings.artifact_root)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    frontend_dist = Path(os.getenv("FRONTEND_DIST_DIR", "apps/frontend/dist"))
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
