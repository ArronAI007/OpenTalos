"""create checkpoints table

Revision ID: 0001
Revises:
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checkpoints",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("graph_id", sa.Text, nullable=False),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("node_cursor", JSONB, nullable=False),
        sa.Column("state", JSONB, nullable=False),
        sa.Column("pending_yields", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("steer_message", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("checkpoints")
