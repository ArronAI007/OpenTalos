import pytest
from sqlalchemy import text

from opentalos.checkpoint.postgres import PostgresCheckpointStore
from opentalos.checkpoint.schema import metadata
from opentalos.core_types import Checkpoint
from opentalos.db import create_engine


def make_checkpoint(**overrides) -> Checkpoint:
    defaults = dict(
        graph_id="g1",
        run_id="run-1",
        tenant_id="tenant-a",
        session_id="session-1",
        node_cursor="start",
        state={},
        pending_yields=[],
        status="running",
        created_at="2026-09-21T00:00:00.000Z",
        cancel_requested=False,
    )
    defaults.update(overrides)
    return Checkpoint(**defaults)


@pytest.fixture
async def rls_setup(postgres_url):
    admin_engine = create_engine(postgres_url)
    async with admin_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'opentalos_app') THEN "
                "CREATE ROLE opentalos_app WITH LOGIN PASSWORD 'opentalos_app'; END IF; END $$;"
            )
        )
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO opentalos_app"))
        await conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints TO opentalos_app"))
        await conn.execute(text("ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text("ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY"))
        await conn.execute(
            text(
                "CREATE POLICY tenant_isolation ON checkpoints "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        )
    app_url = postgres_url.replace("postgres:", "opentalos_app:", 1).split("@")
    # postgres_url 形如 postgresql://postgres:postgres@host:port/db —— 把用户名密码换成 app 角色的。
    host_part = app_url[-1]
    app_url = f"postgresql://opentalos_app:opentalos_app@{host_part}"
    app_engine = create_engine(app_url)
    yield admin_engine, app_engine
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP POLICY IF EXISTS tenant_isolation ON checkpoints"))
        await conn.execute(text("DROP TABLE IF EXISTS checkpoints"))
    await admin_engine.dispose()
    await app_engine.dispose()


@pytest.mark.asyncio
async def test_unfiltered_query_as_app_role_only_sees_own_tenant(rls_setup):
    admin_engine, app_engine = rls_setup
    admin_store = PostgresCheckpointStore(admin_engine)
    await admin_store.save(make_checkpoint(run_id="r1", tenant_id="tenant-a"))
    await admin_store.save(make_checkpoint(run_id="r2", tenant_id="tenant-b"))

    async with app_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', 'tenant-a', true)"))
        result = await conn.execute(text("SELECT run_id FROM checkpoints"))
        run_ids = {row.run_id for row in result}
    assert run_ids == {"r1"}


@pytest.mark.asyncio
async def test_load_for_tenant_works_against_rls_restricted_pool(rls_setup):
    admin_engine, app_engine = rls_setup
    admin_store = PostgresCheckpointStore(admin_engine)
    await admin_store.save(make_checkpoint(run_id="r1", tenant_id="tenant-a"))

    app_store = PostgresCheckpointStore(app_engine)
    assert await app_store.load_for_tenant("r1", "tenant-b") is None
    loaded = await app_store.load_for_tenant("r1", "tenant-a")
    assert loaded is not None


@pytest.mark.asyncio
async def test_save_works_against_rls_restricted_pool_and_is_tenant_scoped(rls_setup):
    admin_engine, app_engine = rls_setup
    app_store = PostgresCheckpointStore(app_engine)
    await app_store.save(make_checkpoint(run_id="r1", tenant_id="tenant-a"))
    assert await app_store.load_for_tenant("r1", "tenant-b") is None
    assert await app_store.load_for_tenant("r1", "tenant-a") is not None
