from urllib.parse import urlsplit, urlunsplit

import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from testcontainers.postgres import PostgresContainer

from db.bulk import NewMemory, insert_raw_memory, list_memories_for_tenant, list_raw_memories_for_tenant, upsert_memories

OPENTALOS_APP_PASSWORD = "opentalos_app"

DDL = """
CREATE TABLE raw_memories (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
  content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE memories (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, type TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'private',
  title TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX memories_tenant_id_title_idx ON memories (tenant_id, title);

CREATE ROLE opentalos_app WITH LOGIN PASSWORD '{password}';
GRANT CONNECT ON DATABASE {dbname} TO opentalos_app;
GRANT USAGE ON SCHEMA public TO opentalos_app;

ALTER TABLE raw_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_memories FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON raw_memories
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON raw_memories TO opentalos_app;

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memories
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON memories TO opentalos_app;
"""


@pytest_asyncio.fixture(scope="module")
async def rls_pools():
    with PostgresContainer("postgres:16-alpine") as container:
        superuser_url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        superuser_pool = AsyncConnectionPool(superuser_url, open=False)
        await superuser_pool.open(wait=True, timeout=10)
        dbname = urlsplit(superuser_url).path.lstrip("/")
        async with superuser_pool.connection() as conn, conn.transaction():
            await conn.execute(DDL.format(password=OPENTALOS_APP_PASSWORD, dbname=dbname))

        # 不能假设 testcontainers 的默认用户名/密码是什么（实测是 "test:test"，不是
        # "postgres:postgres"）——解析原始 URL 后只替换 netloc 的用户名/密码部分，而不是对整个
        # URL 字符串做字面 replace，这样不管 testcontainers 默认凭据是什么都不会悄悄失效。
        parsed = urlsplit(superuser_url)
        app_netloc = f"opentalos_app:{OPENTALOS_APP_PASSWORD}@{parsed.hostname}:{parsed.port}"
        app_url = urlunsplit((parsed.scheme, app_netloc, parsed.path, "", ""))
        app_pool = AsyncConnectionPool(app_url, open=False)
        await app_pool.open(wait=True, timeout=10)

        yield superuser_pool, app_pool

        await app_pool.close()
        await superuser_pool.close()


async def test_raw_query_with_no_tenant_filter_still_cant_see_another_tenants_row(rls_pools):
    superuser_pool, app_pool = rls_pools
    async with superuser_pool.connection() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO memories (id, tenant_id, type, title, content) VALUES ('rls-mem-a', 'tenant-a', 'profile', 't', 'content-a')"
        )
        await conn.execute(
            "INSERT INTO memories (id, tenant_id, type, title, content) VALUES ('rls-mem-b', 'tenant-b', 'profile', 't', 'content-b')"
        )

    async with app_pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", ("tenant-a",))
        cur = await conn.execute("SELECT id FROM memories ORDER BY id")
        rows = await cur.fetchall()
        ids = [r[0] for r in rows]
        assert "rls-mem-a" in ids
        assert "rls-mem-b" not in ids


async def test_insert_and_list_raw_memories_work_under_the_rls_restricted_role(rls_pools):
    _, app_pool = rls_pools
    await insert_raw_memory(app_pool, "tenant-rls-raw", "s1", "run-1", "喜欢简洁回复")
    rows = await list_raw_memories_for_tenant(app_pool, "tenant-rls-raw")
    assert [r.content for r in rows] == ["喜欢简洁回复"]
    assert await list_raw_memories_for_tenant(app_pool, "tenant-other") == []


async def test_upsert_and_list_memories_work_under_the_rls_restricted_role(rls_pools):
    _, app_pool = rls_pools
    await upsert_memories(app_pool, "tenant-rls-mem", [NewMemory(type="profile", title="职业", content="工程师")], [])
    rows = await list_memories_for_tenant(app_pool, "tenant-rls-mem")
    assert [(r.title, r.content) for r in rows] == [("职业", "工程师")]
    assert await list_memories_for_tenant(app_pool, "tenant-other") == []
