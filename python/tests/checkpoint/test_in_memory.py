import pytest

from opentalos.core_types import Checkpoint, CheckpointQuery
from opentalos.checkpoint.in_memory import InMemoryCheckpointStore


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


@pytest.mark.asyncio
async def test_save_and_load_round_trip():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint())
    loaded = await store.load("run-1")
    assert loaded.run_id == "run-1"


@pytest.mark.asyncio
async def test_load_unknown_run_id_returns_none():
    store = InMemoryCheckpointStore()
    assert await store.load("does-not-exist") is None


@pytest.mark.asyncio
async def test_resave_same_run_id_overwrites_ordinary_fields():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(status="running"))
    await store.save(make_checkpoint(status="done"))
    loaded = await store.load("run-1")
    assert loaded.status == "done"


@pytest.mark.asyncio
async def test_list_filters_by_tenant_and_session():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(run_id="r1", tenant_id="a", session_id="s1"))
    await store.save(make_checkpoint(run_id="r2", tenant_id="a", session_id="s2"))
    await store.save(make_checkpoint(run_id="r3", tenant_id="b", session_id="s1"))
    by_tenant = await store.list_checkpoints(CheckpointQuery(tenant_id="a"))
    assert {c.run_id for c in by_tenant} == {"r1", "r2"}
    by_both = await store.list_checkpoints(CheckpointQuery(tenant_id="a", session_id="s1"))
    assert {c.run_id for c in by_both} == {"r1"}


@pytest.mark.asyncio
async def test_request_cancel_sets_flag():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint())
    await store.request_cancel("run-1")
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is True


@pytest.mark.asyncio
async def test_request_cancel_unknown_run_id_is_noop():
    store = InMemoryCheckpointStore()
    await store.request_cancel("does-not-exist")  # 不应该抛异常


@pytest.mark.asyncio
async def test_save_does_not_clobber_concurrently_set_cancel_flag():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(cancel_requested=False))
    await store.request_cancel("run-1")
    # 模拟引擎自己拿着旧的、cancel_requested=False 的内存对象再存一次
    await store.save(make_checkpoint(cancel_requested=False, status="done"))
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is True
    assert loaded.status == "done"


@pytest.mark.asyncio
async def test_request_steer_sets_message():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint())
    await store.request_steer("run-1", "换个说法")
    loaded = await store.load("run-1")
    assert loaded.steer_message == "换个说法"


@pytest.mark.asyncio
async def test_request_steer_unknown_run_id_is_noop():
    store = InMemoryCheckpointStore()
    await store.request_steer("does-not-exist", "x")


@pytest.mark.asyncio
async def test_clear_steer_message_resets_to_none():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint())
    await store.request_steer("run-1", "x")
    await store.clear_steer_message("run-1")
    loaded = await store.load("run-1")
    assert loaded.steer_message is None


@pytest.mark.asyncio
async def test_save_does_not_clobber_concurrently_set_steer_message():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint())
    await store.request_steer("run-1", "x")
    await store.save(make_checkpoint(status="done"))
    loaded = await store.load("run-1")
    assert loaded.steer_message == "x"


@pytest.mark.asyncio
async def test_failed_checkpoint_is_terminal_and_cannot_be_downgraded():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(status="failed", error="boom"))
    await store.save(make_checkpoint(status="running"))
    loaded = await store.load("run-1")
    assert loaded.status == "failed"
    assert loaded.error == "boom"


@pytest.mark.asyncio
async def test_failed_to_failed_resave_with_same_data_succeeds():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(status="failed", error="boom"))
    await store.save(make_checkpoint(status="failed", error="boom"))
    loaded = await store.load("run-1")
    assert loaded.status == "failed"
    assert loaded.error == "boom"


@pytest.mark.asyncio
async def test_failed_to_failed_resave_with_new_error_applies():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(status="failed", error="first"))
    await store.save(make_checkpoint(status="failed", error="second"))
    loaded = await store.load("run-1")
    assert loaded.error == "second"


@pytest.mark.asyncio
async def test_load_for_tenant_matching():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    loaded = await store.load_for_tenant("run-1", "tenant-a")
    assert loaded is not None


@pytest.mark.asyncio
async def test_load_for_tenant_mismatch_returns_none():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    assert await store.load_for_tenant("run-1", "tenant-b") is None


@pytest.mark.asyncio
async def test_load_for_tenant_unknown_run_id_returns_none():
    store = InMemoryCheckpointStore()
    assert await store.load_for_tenant("does-not-exist", "tenant-a") is None


@pytest.mark.asyncio
async def test_request_cancel_for_tenant_gates_on_tenant():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    await store.request_cancel_for_tenant("run-1", "tenant-b")
    loaded = await store.load("run-1")
    assert loaded.cancel_requested is False


@pytest.mark.asyncio
async def test_request_steer_for_tenant_gates_on_tenant():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    await store.request_steer_for_tenant("run-1", "x", "tenant-b")
    loaded = await store.load("run-1")
    assert loaded.steer_message is None


@pytest.mark.asyncio
async def test_clear_steer_message_for_tenant_gates_on_tenant():
    store = InMemoryCheckpointStore()
    await store.save(make_checkpoint(tenant_id="tenant-a"))
    await store.request_steer("run-1", "x")
    await store.clear_steer_message_for_tenant("run-1", "tenant-b")
    loaded = await store.load("run-1")
    assert loaded.steer_message == "x"
