import pytest
from sqlalchemy import text

from opentalos.checkpoint.postgres import PostgresCheckpointStore
from opentalos.checkpoint.schema import metadata
from opentalos.core_types import Checkpoint, CheckpointQuery
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
async def store(postgres_url):
    engine = create_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield PostgresCheckpointStore(engine)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS checkpoints"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_load_round_trip(store):
    await store.save(make_checkpoint())
    loaded = await store.load("run-1")
    assert loaded.run_id == "run-1"
    assert loaded.status == "running"


@pytest.mark.asyncio
async def test_node_cursor_round_trips_arbitrary_json(store):
    parallel_cursor = {"type": "parallel", "branches": ["a", "b"], "joinTo": "join"}
    await store.save(make_checkpoint(node_cursor=parallel_cursor))
    loaded = await store.load("run-1")
    assert loaded.node_cursor == parallel_cursor


@pytest.mark.asyncio
async def test_load_unknown_run_id_returns_none(store):
    assert await store.load("does-not-exist") is None


@pytest.mark.asyncio
async def test_list_filters_by_tenant_and_session(store):
    await store.save(make_checkpoint(run_id="r1", tenant_id="a", session_id="s1"))
    await store.save(make_checkpoint(run_id="r2", tenant_id="a", session_id="s2"))
    await store.save(make_checkpoint(run_id="r3", tenant_id="b", session_id="s1"))
    by_tenant = await store.list_checkpoints(CheckpointQuery(tenant_id="a"))
    assert {c.run_id for c in by_tenant} == {"r1", "r2"}


@pytest.mark.asyncio
async def test_request_cancel_does_not_disturb_other_columns(store):
    await store.save(make_checkpoint(state={"count": 1}, status="running"))
    await store.request_cancel("run-1")
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is True
    assert loaded.state == {"count": 1}
    assert loaded.status == "running"


@pytest.mark.asyncio
async def test_request_cancel_unknown_run_id_is_noop(store):
    await store.request_cancel("does-not-exist")


@pytest.mark.asyncio
async def test_save_does_not_clobber_concurrent_cancel_flag(store):
    await store.save(make_checkpoint(cancel_requested=False))
    await store.request_cancel("run-1")
    await store.save(make_checkpoint(cancel_requested=False, status="done"))
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is True
    assert loaded.status == "done"


@pytest.mark.asyncio
async def test_request_steer_and_clear(store):
    await store.save(make_checkpoint())
    await store.request_steer("run-1", "换个说法")
    assert (await store.load("run-1")).steer_message == "换个说法"
    await store.clear_steer_message("run-1")
    assert (await store.load("run-1")).steer_message is None


@pytest.mark.asyncio
async def test_save_does_not_clobber_concurrent_steer_message(store):
    await store.save(make_checkpoint())
    await store.request_steer("run-1", "x")
    await store.save(make_checkpoint(status="done"))
    loaded = await store.load("run-1")
    assert loaded.steer_message == "x"


@pytest.mark.asyncio
async def test_failed_checkpoint_cannot_be_downgraded(store):
    await store.save(make_checkpoint(status="failed", error="boom"))
    await store.save(make_checkpoint(status="running"))
    loaded = await store.load("run-1")
    assert loaded.status == "failed"
    assert loaded.error == "boom"


@pytest.mark.asyncio
async def test_failed_to_failed_resave_applies_new_error(store):
    await store.save(make_checkpoint(status="failed", error="first"))
    await store.save(make_checkpoint(status="failed", error="second"))
    loaded = await store.load("run-1")
    assert loaded.error == "second"


@pytest.mark.asyncio
async def test_load_for_tenant_mismatch_returns_none(store):
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    assert await store.load_for_tenant("run-1", "tenant-b") is None
    assert (await store.load_for_tenant("run-1", "tenant-a")) is not None


@pytest.mark.asyncio
async def test_request_cancel_for_tenant_gates_on_tenant(store):
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    await store.request_cancel_for_tenant("run-1", "tenant-b")
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is False
    await store.request_cancel_for_tenant("run-1", "tenant-a")
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is True
