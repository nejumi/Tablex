from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.config import Settings, ensure_data_dirs
from tabular_harness.models.entities import Base


def create_engine_for_settings(settings: Settings) -> Engine:
    ensure_data_dirs(settings)
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_mvp_columns(engine)


def ensure_sqlite_mvp_columns(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("jobs")}
    additions = {
        "priority": "INTEGER NOT NULL DEFAULT 50",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "max_attempts": "INTEGER NOT NULL DEFAULT 1",
        "context_json": "TEXT NOT NULL DEFAULT '{}'",
        "policy_json": "TEXT NOT NULL DEFAULT '{}'",
        "dependency_job_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        "approval_required": "BOOLEAN NOT NULL DEFAULT 0",
        "approved_by": "VARCHAR",
        "approved_at": "DATETIME",
        "cancelled_by": "VARCHAR",
        "run_after": "DATETIME",
        "locked_by": "VARCHAR",
        "locked_at": "DATETIME",
    }
    with engine.begin() as connection:
        for column_name, ddl in additions.items():
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {column_name} {ddl}"))


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
