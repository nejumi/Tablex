from __future__ import annotations

from alembic import op

revision = "0002_agent_transcript_event_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_transcript_events_session_index "
        "ON agent_transcript_events (session_id, event_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_agent_transcript_events_project_created "
        "ON agent_transcript_events (project_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_transcript_events_project_created")
    op.execute("DROP INDEX IF EXISTS ix_agent_transcript_events_session_index")
