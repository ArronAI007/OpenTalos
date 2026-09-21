"""对应 packages/postgres-tracing/src/event-bus.ts。"""

import asyncio

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from opentalos.core_types import EventHandler, TraceEvent
from opentalos.tracing.schema import trace_events_table


class StoredTraceEvent(TraceEvent):
    # TraceEvent 是 Pydantic BaseModel，直接继承并加字段即可——不能用 @dataclass 装饰一个
    # BaseModel 子类，两套字段处理机制会冲突。
    id: int


class PostgresEventBus:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        # 串行化写入任务，保证插入顺序和 emit() 调用顺序一致（自增 id 被 list_events_since 当分页
        # 游标用），且一次写入失败不会让后续写入永久卡住。
        self._lock = asyncio.Lock()
        self._pending: asyncio.Task | None = None

    def emit(self, event: TraceEvent) -> None:
        previous = self._pending

        async def _write() -> None:
            async with self._lock:
                if previous is not None:
                    await asyncio.gather(previous, return_exceptions=True)
                try:
                    async with self._engine.begin() as conn:
                        await conn.execute(
                            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                            {"tenant_id": event.tenant_id},
                        )
                        await conn.execute(
                            trace_events_table.insert().values(
                                run_id=event.run_id,
                                tenant_id=event.tenant_id,
                                session_id=event.session_id,
                                type=event.type,
                                payload=event.payload,
                            )
                        )
                except Exception as error:  # noqa: BLE001 — 一次写入失败不能让链条永久卡住
                    print(f"PostgresEventBus write failed: {error}")

        self._pending = asyncio.ensure_future(_write())

    def subscribe(self, handler: EventHandler):
        # 跨进程的消费者没法通过进程内回调收到通知——实时投递走 list_events_since 轮询（由
        # apps/api 完成），这里只是满足接口形状。
        return lambda: None

    async def flush(self) -> None:
        if self._pending is not None:
            await asyncio.gather(self._pending, return_exceptions=True)


async def list_events_since(engine: AsyncEngine, run_id: str, after_id: int, tenant_id: str) -> list[StoredTraceEvent]:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
        result = await conn.execute(
            select(trace_events_table)
            .where(
                (trace_events_table.c.run_id == run_id)
                & (trace_events_table.c.tenant_id == tenant_id)
                & (trace_events_table.c.id > after_id)
            )
            .order_by(trace_events_table.c.id.asc())
        )
        return [
            StoredTraceEvent(
                id=row.id,
                type=row.type,
                run_id=row.run_id,
                tenant_id=row.tenant_id,
                session_id=row.session_id,
                timestamp=row.created_at.isoformat(),
                payload=row.payload,
            )
            for row in result
        ]
