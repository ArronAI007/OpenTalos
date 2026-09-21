import pytest
from sqlalchemy import text

from opentalos.core_types import TraceEvent
from opentalos.tracing.postgres import PostgresEventBus, list_events_since
from opentalos.tracing.schema import metadata
from opentalos.db import create_engine


def _event(run_id: str = "run-1", tenant_id: str = "tenant-a", event_type: str = "node_enter", payload=None) -> TraceEvent:
    return TraceEvent(
        type=event_type,
        run_id=run_id,
        tenant_id=tenant_id,
        session_id="session-1",
        timestamp="2026-09-21T00:00:00.000Z",
        payload=payload,
    )


@pytest.fixture
async def bus_and_engine(postgres_url):
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield PostgresEventBus(engine), engine
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS trace_events"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_emit_and_flush_then_visible_via_list_events_since(bus_and_engine):
    bus, engine = bus_and_engine
    bus.emit(_event(payload={"x": 1}))
    await bus.flush()
    events = await list_events_since(engine, "run-1", 0, "tenant-a")
    assert len(events) == 1
    assert events[0].payload == {"x": 1}


@pytest.mark.asyncio
async def test_multiple_emits_preserve_order(bus_and_engine):
    bus, engine = bus_and_engine
    bus.emit(_event(event_type="node_enter"))
    bus.emit(_event(event_type="llm_call_start"))
    bus.emit(_event(event_type="node_exit"))
    await bus.flush()
    events = await list_events_since(engine, "run-1", 0, "tenant-a")
    assert [e.type for e in events] == ["node_enter", "llm_call_start", "node_exit"]


@pytest.mark.asyncio
async def test_cursor_excludes_already_seen_events(bus_and_engine):
    bus, engine = bus_and_engine
    bus.emit(_event(event_type="node_enter"))
    await bus.flush()
    first_batch = await list_events_since(engine, "run-1", 0, "tenant-a")
    bus.emit(_event(event_type="node_exit"))
    await bus.flush()
    second_batch = await list_events_since(engine, "run-1", first_batch[-1].id, "tenant-a")
    assert [e.type for e in second_batch] == ["node_exit"]


@pytest.mark.asyncio
async def test_scoped_strictly_by_run_id(bus_and_engine):
    bus, engine = bus_and_engine
    bus.emit(_event(run_id="run-1"))
    bus.emit(_event(run_id="run-2"))
    await bus.flush()
    events = await list_events_since(engine, "run-1", 0, "tenant-a")
    assert len(events) == 1


def test_subscribe_returns_noop_unsubscribe():
    bus = PostgresEventBus.__new__(PostgresEventBus)  # 不需要真实引擎就能测试这一条
    PostgresEventBus.__init__(bus, engine=None)
    unsubscribe = bus.subscribe(lambda event: None)
    unsubscribe()  # 不应该抛异常


@pytest.mark.asyncio
async def test_tenant_scoping_returns_empty_for_wrong_tenant(bus_and_engine):
    bus, engine = bus_and_engine
    bus.emit(_event(tenant_id="tenant-a"))
    await bus.flush()
    events = await list_events_since(engine, "run-1", 0, "tenant-b")
    assert events == []
