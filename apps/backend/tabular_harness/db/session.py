from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from tabular_harness.core.config import Settings, ensure_data_dirs
from tabular_harness.models.entities import Base


def create_engine_for_settings(settings: Settings) -> Engine:
    ensure_data_dirs(settings)
    sqlite_url = settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if sqlite_url else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)
    if sqlite_url:
        configure_sqlite_pragmas(engine)
    return engine


def configure_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_mvp_columns(engine)


def ensure_sqlite_mvp_columns(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "projects" in table_names:
            existing = {column["name"] for column in inspector.get_columns("projects")}
            additions = {
                "autonomy_mode": "VARCHAR NOT NULL DEFAULT 'approval_based'",
            }
            for column_name, ddl in additions.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE projects ADD COLUMN {column_name} {ddl}"))

        if "jobs" in table_names:
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
            for column_name, ddl in additions.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {column_name} {ddl}"))

        if "agent_transcript_events" in table_names:
            repair_agent_transcript_event_indexes(connection)
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_transcript_events_session_index "
                    "ON agent_transcript_events (session_id, event_index)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_transcript_events_project_created "
                    "ON agent_transcript_events (project_id, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_transcript_events_session_index "
                    "ON agent_transcript_events (session_id, event_index)"
                )
            )


def repair_agent_transcript_event_indexes(connection: Any) -> None:
    duplicate_groups = list(
        connection.execute(
            text(
                """
                SELECT session_id, event_index, COUNT(*) AS duplicate_count
                FROM agent_transcript_events
                GROUP BY session_id, event_index
                HAVING duplicate_count > 1
                """
            )
        ).mappings()
    )
    for group in duplicate_groups:
        session_id = str(group["session_id"])
        event_index = int(group["event_index"])
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT id
                    FROM agent_transcript_events
                    WHERE session_id = :session_id AND event_index = :event_index
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"session_id": session_id, "event_index": event_index},
            ).mappings()
        )
        if len(rows) <= 1:
            continue
        max_index = int(
            connection.execute(
                text(
                    """
                    SELECT COALESCE(MAX(event_index), -1)
                    FROM agent_transcript_events
                    WHERE session_id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).scalar_one()
        )
        for row in rows[1:]:
            max_index += 1
            connection.execute(
                text(
                    """
                    UPDATE agent_transcript_events
                    SET event_index = :event_index
                    WHERE id = :id
                    """
                ),
                {"event_index": max_index, "id": row["id"]},
            )


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
