import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from psycopg_pool import AsyncConnectionPool

MemoryType = Literal["profile", "preference", "context"]


@dataclass
class RawMemoryRecord:
    id: str
    tenant_id: str
    session_id: str
    run_id: str
    content: str
    created_at: datetime


@dataclass
class MemoryEntry:
    id: str
    tenant_id: str
    type: MemoryType
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    last_confirmed_at: datetime


@dataclass
class NewMemory:
    type: MemoryType
    title: str
    content: str


@dataclass
class MemoryUpdate:
    id: str
    content: str


async def insert_raw_memory(
    pool: AsyncConnectionPool, tenant_id: str, session_id: str, run_id: str, content: str
) -> None:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        await conn.execute(
            "INSERT INTO raw_memories (id, tenant_id, session_id, run_id, content) VALUES (%s, %s, %s, %s, %s)",
            (str(uuid.uuid4()), tenant_id, session_id, run_id, content),
        )


async def list_tenants_with_pending(pool: AsyncConnectionPool, all_tenant_ids: list[str]) -> list[str]:
    """找出"有未处理原始记忆"的全部租户。不能直接对 raw_memories 表做一次跨租户查询——那张表受
    RLS 保护，在 opentalos_app 角色下任何没设置 app.tenant_id 的查询永远只返回空结果。调用方
    （apps/worker 的定期整合循环）先从 tenants 表拿到全部租户 id，传进来逐个检查（并行）。"""

    async def check(tenant_id: str) -> str | None:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
            cur = await conn.execute("SELECT id FROM raw_memories WHERE tenant_id = %s LIMIT 1", (tenant_id,))
            rows = await cur.fetchall()
            return tenant_id if rows else None

    results = await asyncio.gather(*(check(tenant_id) for tenant_id in all_tenant_ids))
    return [tenant_id for tenant_id in results if tenant_id is not None]


async def list_raw_memories_for_tenant(pool: AsyncConnectionPool, tenant_id: str) -> list[RawMemoryRecord]:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        cur = await conn.execute(
            "SELECT id, tenant_id, session_id, run_id, content, created_at FROM raw_memories WHERE tenant_id = %s",
            (tenant_id,),
        )
        rows = await cur.fetchall()
        return [
            RawMemoryRecord(id=r[0], tenant_id=r[1], session_id=r[2], run_id=r[3], content=r[4], created_at=r[5])
            for r in rows
        ]


async def delete_raw_memories(pool: AsyncConnectionPool, tenant_id: str, ids: list[str]) -> None:
    if not ids:
        return
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        await conn.execute("DELETE FROM raw_memories WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, ids))


async def list_memories_for_tenant(pool: AsyncConnectionPool, tenant_id: str) -> list[MemoryEntry]:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        cur = await conn.execute(
            "SELECT id, tenant_id, type, title, content, created_at, updated_at, last_confirmed_at "
            "FROM memories WHERE tenant_id = %s",
            (tenant_id,),
        )
        rows = await cur.fetchall()
        return [
            MemoryEntry(
                id=r[0], tenant_id=r[1], type=r[2], title=r[3], content=r[4],
                created_at=r[5], updated_at=r[6], last_confirmed_at=r[7],
            )
            for r in rows
        ]


async def upsert_memories(
    pool: AsyncConnectionPool, tenant_id: str, new_entries: list[NewMemory], updates: list[MemoryUpdate]
) -> None:
    """整合阶段的批量新增/更新入口。故意不用 ON CONFLICT（跟 TS 版本一致）——同一个租户的整合
    循环在这个试点里始终是单 worker 串行处理，不会有并发写同一个 title 的情况；如果未来有多个
    worker 实例并发跑整合，需要重新评估。"""
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        for entry in new_entries:
            await conn.execute(
                "INSERT INTO memories (id, tenant_id, type, title, content) VALUES (%s, %s, %s, %s, %s)",
                (str(uuid.uuid4()), tenant_id, entry.type, entry.title, entry.content),
            )
        for update in updates:
            await conn.execute(
                "UPDATE memories SET content = %s, updated_at = now(), last_confirmed_at = now() "
                "WHERE tenant_id = %s AND id = %s",
                (update.content, tenant_id, update.id),
            )


async def delete_memories(pool: AsyncConnectionPool, tenant_id: str, ids: list[str]) -> None:
    if not ids:
        return
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        await conn.execute("DELETE FROM memories WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, ids))


async def search_memories(pool: AsyncConnectionPool, tenant_id: str, query: str) -> list[dict[str, object]]:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
        pattern = f"%{query}%"
        cur = await conn.execute(
            "SELECT title, content FROM memories WHERE tenant_id = %s AND (title ILIKE %s OR content ILIKE %s)",
            (tenant_id, pattern, pattern),
        )
        rows = await cur.fetchall()
        return [{"key": r[0], "value": r[1], "score": 0.0} for r in rows]
