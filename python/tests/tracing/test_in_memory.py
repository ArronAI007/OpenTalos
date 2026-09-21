import pytest

from opentalos.core_types import TraceEvent
from opentalos.tracing.in_memory import InMemoryEventBus


def _event(event_type: str = "node_enter") -> TraceEvent:
    return TraceEvent(
        type=event_type,
        run_id="run-1",
        tenant_id="tenant-a",
        session_id="session-1",
        timestamp="2026-09-21T00:00:00.000Z",
    )


def test_emit_delivers_to_subscribed_handler():
    bus = InMemoryEventBus()
    received = []
    bus.subscribe(received.append)
    event = _event()
    bus.emit(event)
    assert received == [event]


def test_multiple_subscribers_each_called_once():
    bus = InMemoryEventBus()
    calls_a, calls_b = [], []
    bus.subscribe(calls_a.append)
    bus.subscribe(calls_b.append)
    bus.emit(_event())
    assert len(calls_a) == 1
    assert len(calls_b) == 1


def test_unsubscribe_stops_delivery():
    bus = InMemoryEventBus()
    received = []
    unsubscribe = bus.subscribe(received.append)
    unsubscribe()
    bus.emit(_event())
    assert received == []


def test_get_events_returns_emission_order():
    bus = InMemoryEventBus()
    bus.emit(_event("node_enter"))
    bus.emit(_event("node_exit"))
    assert [e.type for e in bus.get_events()] == ["node_enter", "node_exit"]


@pytest.mark.asyncio
async def test_flush_is_a_noop():
    bus = InMemoryEventBus()
    await bus.flush()  # 不应该抛异常
