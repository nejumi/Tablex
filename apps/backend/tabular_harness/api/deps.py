from __future__ import annotations

from collections.abc import Generator
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.services.artifacts import LocalArtifactStore


def get_session(request: Request) -> Generator[Session, None, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_artifact_store(request: Request) -> LocalArtifactStore:
    return cast(LocalArtifactStore, request.app.state.artifact_store)
