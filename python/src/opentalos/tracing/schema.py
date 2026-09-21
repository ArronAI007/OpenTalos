"""对应 packages/postgres-tracing/src/schema.ts。"""

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

trace_events_table = Table(
    "trace_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("payload", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default="now()"),
)
