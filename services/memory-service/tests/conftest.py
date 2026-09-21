import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from testcontainers.postgres import PostgresContainer

# testcontainers-python 的 get_connection_url() 默认返回 SQLAlchemy 风格的
# "postgresql+psycopg2://..." —— psycopg3 不认识 "+psycopg2" 这个 dialect 后缀，必须去掉。
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
"""


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    with PostgresContainer("postgres:16-alpine") as container:
        database_url = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        pool = AsyncConnectionPool(database_url, open=False)
        # wait=True：不加这个参数时 open() 立即返回，连接是在后台异步建立的——在这个仓库实测过
        # 至少一例（见 test_rls.py 同样的坑）这种"火后不理"的后台建连有时会在 pytest-asyncio 的
        # 事件循环生命周期下卡住，导致第一次真正用到连接时 PoolTimeout。显式等池子真正建好，避免
        # 这个坑重演。
        await pool.open(wait=True, timeout=10)
        async with pool.connection() as conn:
            await conn.execute(DDL)
            await conn.commit()
        yield pool
        await pool.close()
