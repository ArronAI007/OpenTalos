"""trace_events row-level security

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON trace_events TO opentalos_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE trace_events_id_seq TO opentalos_app")
    op.execute("ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE trace_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON trace_events
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON trace_events")
    op.execute("ALTER TABLE trace_events NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE trace_events DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON trace_events FROM opentalos_app")
