"""checkpoints row-level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'opentalos_app') THEN
                -- 占位密码：非本地开发环境部署前必须轮换。
                CREATE ROLE opentalos_app WITH LOGIN PASSWORD 'opentalos_app';
            END IF;
        END
        $$;
        """
    )
    # GRANT ... ON DATABASE takes a literal identifier, not an expression, so CURRENT_DATABASE()
    # can't be spelled directly in the GRANT statement itself; route it through dynamic SQL instead
    # so this migration isn't hardcoded to a specific database name (the original TS migration this
    # ports from hardcodes "postgres" since it always targets that one database).
    op.execute("DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO opentalos_app', current_database()); END $$;")
    op.execute("GRANT USAGE ON SCHEMA public TO opentalos_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints TO opentalos_app")
    op.execute("ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON checkpoints
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON checkpoints")
    op.execute("ALTER TABLE checkpoints NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE checkpoints DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON checkpoints FROM opentalos_app")
