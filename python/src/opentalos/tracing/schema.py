"""对应 packages/postgres-tracing/src/schema.ts。"""

from sqlalchemy import BigInteger, Column, DateTime, Index, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

trace_events_table = Table(
    "trace_events",
    metadata,
    # BigInteger/BIGSERIAL, not Integer/SERIAL: this table receives roughly one row per
    # streamed token, so the 32-bit SERIAL ceiling (~2.15 billion) is a reachable limit in
    # production.
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", Text, nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("session_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("payload", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default="now()"),
)

# list_events_since filters run_id AND tenant_id AND id > cursor, ordered by id -- this is the
# SSE-polling hot path, polled repeatedly per connected client.
Index("ix_trace_events_run_id_id", trace_events_table.c.run_id, trace_events_table.c.id)
