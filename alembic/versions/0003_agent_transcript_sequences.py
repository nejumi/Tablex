from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_agent_transcript_sequences"
down_revision = "0002_agent_transcript_event_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_transcript_sequences",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("next_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"]),
        sa.PrimaryKeyConstraint("session_id"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("agent_transcript_sequences", if_exists=True)
