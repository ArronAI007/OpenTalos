import pytest

from db.bulk import NewMemory, insert_raw_memory, list_memories_for_tenant, list_raw_memories_for_tenant, upsert_memories

from app.consolidate import consolidate_memories_for_tenant


class FakeProvider:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._response_text


async def test_does_nothing_when_there_are_no_unconsolidated_raw_memories(pg_pool) -> None:
    provider = FakeProvider('{"add": [], "update": [], "delete": []}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-empty")
    assert await list_memories_for_tenant(pg_pool, "tenant-empty") == []


async def test_adds_a_new_memory_and_clears_the_processed_raw_memory(pg_pool) -> None:
    await insert_raw_memory(pg_pool, "tenant-add", "s1", "run-1", "喜欢简洁回复")
    provider = FakeProvider('{"add": [{"type": "preference", "title": "回复偏好", "content": "喜欢简洁回复"}], "update": [], "delete": []}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-add")

    memories = await list_memories_for_tenant(pg_pool, "tenant-add")
    assert [(m.type, m.title, m.content) for m in memories] == [("preference", "回复偏好", "喜欢简洁回复")]
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-add") == []


async def test_updates_an_existing_memory_when_a_raw_observation_refines_it(pg_pool) -> None:
    await upsert_memories(pg_pool, "tenant-update", [NewMemory(type="context", title="旅行计划", content="9 月去上海")], [])
    existing = (await list_memories_for_tenant(pg_pool, "tenant-update"))[0]
    await insert_raw_memory(pg_pool, "tenant-update", "s1", "run-2", "旅行改成 10 月了")

    provider = FakeProvider(f'{{"add": [], "update": [{{"id": "{existing.id}", "content": "10 月去上海"}}], "delete": []}}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-update")

    updated = (await list_memories_for_tenant(pg_pool, "tenant-update"))[0]
    assert updated.content == "10 月去上海"


async def test_deletes_a_memory_the_model_judges_is_no_longer_true(pg_pool) -> None:
    await upsert_memories(pg_pool, "tenant-delete", [NewMemory(type="context", title="旧计划", content="已经取消的计划")], [])
    existing = (await list_memories_for_tenant(pg_pool, "tenant-delete"))[0]
    await insert_raw_memory(pg_pool, "tenant-delete", "s1", "run-3", "计划取消了")

    provider = FakeProvider(f'{{"add": [], "update": [], "delete": ["{existing.id}"]}}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-delete")

    assert await list_memories_for_tenant(pg_pool, "tenant-delete") == []


async def test_clears_processed_raw_memories_even_when_the_model_does_nothing(pg_pool) -> None:
    await insert_raw_memory(pg_pool, "tenant-ignore", "s1", "run-4", "重复的信息")
    provider = FakeProvider('{"add": [], "update": [], "delete": []}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-ignore")
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-ignore") == []


async def test_treats_malformed_model_output_as_a_noop_but_still_clears_raw_memories(pg_pool) -> None:
    await insert_raw_memory(pg_pool, "tenant-malformed", "s1", "run-5", "some fact")
    provider = FakeProvider("not valid json")
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-malformed")
    assert await list_memories_for_tenant(pg_pool, "tenant-malformed") == []
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-malformed") == []


async def test_drops_an_add_item_with_a_hallucinated_type_and_creates_nothing(pg_pool) -> None:
    await insert_raw_memory(pg_pool, "tenant-bad-type", "s1", "run-6", "some fact")
    provider = FakeProvider('{"add": [{"type": "bogus-type", "title": "x", "content": "y"}], "update": [], "delete": []}')
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-bad-type")
    assert await list_memories_for_tenant(pg_pool, "tenant-bad-type") == []
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-bad-type") == []


async def test_applies_only_the_valid_item_from_a_mixed_batch(pg_pool) -> None:
    await insert_raw_memory(pg_pool, "tenant-mixed", "s1", "run-7", "喜欢简洁回复")
    provider = FakeProvider(
        '{"add": [{"type": "preference", "title": "回复偏好", "content": "喜欢简洁回复"}, '
        '{"type": "profile", "title": "缺 content"}], "update": [], "delete": []}'
    )
    await consolidate_memories_for_tenant(pg_pool, provider, "tenant-mixed")
    memories = await list_memories_for_tenant(pg_pool, "tenant-mixed")
    assert [(m.type, m.title, m.content) for m in memories] == [("preference", "回复偏好", "喜欢简洁回复")]


async def test_write_failure_mid_consolidation_leaves_the_raw_memory_untouched(pg_pool) -> None:
    await upsert_memories(pg_pool, "tenant-conflict", [NewMemory(type="profile", title="重复标题", content="已有内容")], [])
    await insert_raw_memory(pg_pool, "tenant-conflict", "s1", "run-8", "新的观察")

    # 模型返回一个跟已有记忆 title 撞车的 add——upsertMemories 内部 (tenant_id, title) 唯一约束
    # 会在 Postgres 里真实报错，不是伪造出来的失败。
    provider = FakeProvider('{"add": [{"type": "profile", "title": "重复标题", "content": "冲突的新内容"}], "update": [], "delete": []}')

    with pytest.raises(Exception):
        await consolidate_memories_for_tenant(pg_pool, provider, "tenant-conflict")

    raw_after = await list_raw_memories_for_tenant(pg_pool, "tenant-conflict")
    assert [r.content for r in raw_after] == ["新的观察"]
