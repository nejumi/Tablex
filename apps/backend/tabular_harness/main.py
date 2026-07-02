from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tabular_harness.api.routes import router
from tabular_harness.core.config import Settings, get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.auth import ensure_bootstrap_user, user_for_session_token


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
    with session_factory() as session:
        ensure_bootstrap_user(
            session,
            email=app_settings.bootstrap_user_email,
            password=app_settings.bootstrap_user_password,
        )
        session.commit()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not app_settings.auth_enabled or is_public_path(request.url.path):
            return await call_next(request)
        token = request.cookies.get(app_settings.auth_cookie_name)
        with session_factory() as session:
            user = user_for_session_token(session, token)
            if user is None:
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            request.state.user_id = user.id
        return await call_next(request)

    app.include_router(router)
    frontend_dist = Path(os.getenv("FRONTEND_DIST_DIR", "apps/frontend/dist"))
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


def is_public_path(path: str) -> bool:
    if path in {"/healthz", "/api/config"}:
        return True
    return path.startswith("/api/auth/")


app = create_app()
