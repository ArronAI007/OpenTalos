import pytest
from sqlalchemy import text

from opentalos.core_types import TraceEvent
from opentalos.tracing.postgres import PostgresEventBus, list_events_since
from opentalos.tracing.schema import metadata
from opentalos.db import create_engine


def _event(run_id="run-1", tenant_id="tenant-a") -> TraceEvent:
    return TraceEvent(
        type="node_enter", run_id=run_id, tenant_id=tenant_id, session_id="s1", timestamp="2026-09-21T00:00:00.000Z"
    )


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
        await conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON trace_events TO opentalos_app"))
        await conn.execute(text("GRANT USAGE, SELECT ON SEQUENCE trace_events_id_seq TO opentalos_app"))
        await conn.execute(text("ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text("ALTER TABLE trace_events FORCE ROW LEVEL SECURITY"))
        await conn.execute(
            text(
                "CREATE POLICY tenant_isolation ON trace_events "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
        )
    host_part = postgres_url.split("@")[-1]
    app_url = f"postgresql://opentalos_app:opentalos_app@{host_part}"
    app_engine = create_engine(app_url)
    yield admin_engine, app_engine
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP POLICY IF EXISTS tenant_isolation ON trace_events"))
        await conn.execute(text("DROP TABLE IF EXISTS trace_events"))
    await admin_engine.dispose()
    await app_engine.dispose()


@pytest.mark.asyncio
async def test_unfiltered_query_as_app_role_only_sees_own_tenant(rls_setup):
    admin_engine, app_engine = rls_setup
    admin_bus = PostgresEventBus(admin_engine)
    admin_bus.emit(_event(tenant_id="tenant-a"))
    admin_bus.emit(_event(tenant_id="tenant-b"))
    await admin_bus.flush()

    async with app_engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', 'tenant-a', true)"))
        result = await conn.execute(text("SELECT tenant_id FROM trace_events"))
        tenant_ids = {row.tenant_id for row in result}
    assert tenant_ids == {"tenant-a"}


@pytest.mark.asyncio
async def test_list_events_since_correct_for_matching_and_wrong_tenant(rls_setup):
    admin_engine, app_engine = rls_setup
    admin_bus = PostgresEventBus(admin_engine)
    admin_bus.emit(_event(tenant_id="tenant-a"))
    await admin_bus.flush()

    matching = await list_events_since(app_engine, "run-1", 0, "tenant-a")
    assert len(matching) == 1
    mismatched = await list_events_since(app_engine, "run-1", 0, "tenant-b")
    assert mismatched == []


@pytest.mark.asyncio
async def test_emit_works_against_rls_restricted_pool(rls_setup):
    _, app_engine = rls_setup
    app_bus = PostgresEventBus(app_engine)
    app_bus.emit(_event(tenant_id="tenant-a"))
    await app_bus.flush()
    events = await list_events_since(app_engine, "run-1", 0, "tenant-a")
    assert len(events) == 1
