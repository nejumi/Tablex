from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tabular_harness.api.routes import router
from tabular_harness.core.config import Settings, get_settings
from tabular_harness.db.session import create_engine_for_settings, create_session_factory, init_db
from tabular_harness.services.agent_sessions import start_active_main_session_supervisors
from tabular_harness.services.artifacts import LocalArtifactStore
from tabular_harness.services.auth import ensure_bootstrap_user, user_for_session_token
from tabular_harness.services.jobs import reap_stale_running_jobs
from tabular_harness.worker.daemon import LocalWorkerDaemon


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    engine = create_engine_for_settings(app_settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        start_active_main_session_supervisors(session_factory, app.state.artifact_store)
        worker_daemon: LocalWorkerDaemon | None = None
        if app_settings.local_worker_enabled:
            worker_daemon = LocalWorkerDaemon(
                session_factory,
                app.state.artifact_store,
                interval_seconds=app_settings.local_worker_interval_seconds,
                max_jobs_per_wake=app_settings.local_worker_max_jobs_per_wake,
            )
            worker_daemon.start()
            app.state.local_worker_daemon = worker_daemon
        try:
            yield
        finally:
            if worker_daemon is not None:
                worker_daemon.stop()

    app = FastAPI(title=f"{app_settings.app_display_name} API", lifespan=lifespan)
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
        reap_stale_running_jobs(session)
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
    if path in {"/health", "/healthz", "/api/config"}:
        return True
    return path.startswith("/api/auth/")


app = create_app()
