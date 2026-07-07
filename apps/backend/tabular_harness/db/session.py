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
    engine_kwargs: dict[str, Any] = {"connect_args": connect_args}
    if sqlite_url:
        engine_kwargs.update(
            {
                "pool_size": 30,
                "max_overflow": 30,
                "pool_timeout": 10,
            }
        )
    engine = create_engine(settings.database_url, **engine_kwargs)
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
                "primary_dataset_snapshot_id": "VARCHAR",
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

        if "artifacts" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_artifacts_project_created "
                    "ON artifacts (project_id, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_artifacts_project_type_created "
                    "ON artifacts (project_id, asset_type, created_at)"
                )
            )

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

        if "experiment_runs" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_experiment_runs_project_started "
                    "ON experiment_runs (project_id, started_at)"
                )
            )

        if "lineage_edges" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_edges_project_created "
                    "ON lineage_edges (project_id, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lineage_edges_project_relation "
                    "ON lineage_edges (project_id, relation_type)"
                )
            )

        if "agent_sessions" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_agent_sessions_project_updated "
                    "ON agent_sessions (project_id, updated_at)"
                )
            )

        if "jobs" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_jobs_project_status_updated "
                    "ON jobs (project_id, status, updated_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_jobs_project_created "
                    "ON jobs (project_id, created_at)"
                )
            )

        ensure_sqlite_project_delete_indexes(connection, table_names)


def ensure_sqlite_project_delete_indexes(connection: Any, table_names: set[str]) -> None:
    """Create indexes SQLite needs to delete project-owned rows without full FK scans."""

    index_specs = {
        "answers": {
            "ix_answers_question": ("question_id",),
        },
        "artifacts": {
            "ix_artifacts_project_id": ("project_id",),
        },
        "asset_references": {
            "ix_asset_references_source": ("source_id",),
            "ix_asset_references_target_asset": ("target_asset_id",),
            "ix_asset_references_target_asset_version": ("target_asset_version_id",),
        },
        "asset_versions": {
            "ix_asset_versions_asset": ("asset_id",),
            "ix_asset_versions_artifact": ("artifact_id",),
            "ix_asset_versions_created_from_project": ("created_from_project_id",),
        },
        "assumption_evidence_links": {
            "ix_assumption_evidence_links_assumption": ("assumption_id",),
            "ix_assumption_evidence_links_evidence": ("evidence_id",),
        },
        "assumptions": {
            "ix_assumptions_project": ("project_id",),
        },
        "agent_transcript_events": {
            "ix_agent_transcript_events_artifact": ("artifact_id",),
            "ix_agent_transcript_events_job": ("job_id",),
        },
        "dataset_snapshots": {
            "ix_dataset_snapshots_artifact": ("artifact_id",),
            "ix_dataset_snapshots_project": ("project_id",),
        },
        "evaluation_candidates": {
            "ix_evaluation_candidates_dataset": ("dataset_snapshot_id",),
            "ix_evaluation_candidates_project": ("project_id",),
        },
        "evaluation_specs": {
            "ix_evaluation_specs_candidate": ("source_evaluation_candidate_id",),
            "ix_evaluation_specs_dataset": ("dataset_snapshot_id",),
            "ix_evaluation_specs_project": ("project_id",),
        },
        "evidence": {
            "ix_evidence_project": ("project_id",),
            "ix_evidence_source_artifact": ("source_artifact_id",),
        },
        "experiment_runs": {
            "ix_experiment_runs_dataset": ("dataset_snapshot_id",),
            "ix_experiment_runs_evaluation_candidate": ("evaluation_candidate_id",),
            "ix_experiment_runs_evaluation_spec": ("evaluation_spec_id",),
            "ix_experiment_runs_split_manifest": ("split_manifest_id",),
        },
        "ideas": {
            "ix_ideas_artifact": ("artifact_id",),
            "ix_ideas_dataset": ("dataset_snapshot_id",),
            "ix_ideas_evaluation_spec": ("evaluation_spec_id",),
            "ix_ideas_project": ("project_id",),
            "ix_ideas_research_brief": ("research_brief_id",),
        },
        "insights": {
            "ix_insights_artifact": ("artifact_id",),
            "ix_insights_project": ("project_id",),
        },
        "model_versions": {
            "ix_model_versions_artifact": ("artifact_id",),
            "ix_model_versions_dataset": ("dataset_snapshot_id",),
            "ix_model_versions_evaluation_spec": ("evaluation_spec_id",),
            "ix_model_versions_experiment_run": ("experiment_run_id",),
            "ix_model_versions_project": ("project_id",),
            "ix_model_versions_split_manifest": ("split_manifest_id",),
        },
        "questions": {
            "ix_questions_project": ("project_id",),
        },
        "reports": {
            "ix_reports_artifact": ("artifact_id",),
            "ix_reports_project": ("project_id",),
        },
        "research_briefs": {
            "ix_research_briefs_artifact": ("artifact_id",),
            "ix_research_briefs_dataset": ("dataset_snapshot_id",),
            "ix_research_briefs_evaluation_spec": ("evaluation_spec_id",),
            "ix_research_briefs_project": ("project_id",),
        },
        "research_plan_current_work": {
            "ix_research_plan_current_work_plan": ("research_plan_id",),
            "ix_research_plan_current_work_revision": ("revision_id",),
        },
        "research_plan_revisions": {
            "ix_research_plan_revisions_parent": ("parent_revision_id",),
            "ix_research_plan_revisions_source_artifact": ("source_artifact_id",),
        },
        "semantic_catalogs": {
            "ix_semantic_catalogs_artifact": ("artifact_id",),
            "ix_semantic_catalogs_dataset": ("dataset_snapshot_id",),
            "ix_semantic_catalogs_project": ("project_id",),
        },
        "split_manifests": {
            "ix_split_manifests_artifact": ("artifact_id",),
            "ix_split_manifests_evaluation_spec": ("evaluation_spec_id",),
            "ix_split_manifests_project": ("project_id",),
        },
        "visualization_specs": {
            "ix_visualization_specs_artifact": ("artifact_id",),
            "ix_visualization_specs_project": ("project_id",),
            "ix_visualization_specs_source_artifact": ("source_artifact_id",),
        },
    }
    for table_name, table_index_specs in index_specs.items():
        if table_name not in table_names:
            continue
        for index_name, columns in table_index_specs.items():
            column_sql = ", ".join(columns)
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_sql})"))


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
