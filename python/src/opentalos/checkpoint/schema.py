"""对应 packages/postgres-checkpoint/src/schema.ts。"""

from sqlalchemy import Boolean, Column, DateTime, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

checkpoints_table = Table(
    "checkpoints",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("graph_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("node_cursor", JSONB, nullable=False),
    Column("state", JSONB, nullable=False),
    Column("pending_yields", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("cancel_requested", Boolean, nullable=False, server_default="false"),
    Column("steer_message", Text, nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default="now()"),
)
