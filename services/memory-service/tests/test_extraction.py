from db.bulk import list_raw_memories_for_tenant

from app.extraction import extract_memory


class FakeProvider:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._response_text


async def test_writes_nothing_when_the_model_judges_no_durable_information(pg_pool) -> None:
    provider = FakeProvider('{"shouldSave": false}')
    await extract_memory(pg_pool, provider, "tenant-noop", "s1", "run-1", "今天几号？", "今天是 2026 年 9 月 20 日。")
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-noop") == []


async def test_writes_a_raw_memory_when_the_model_finds_durable_information(pg_pool) -> None:
    provider = FakeProvider('{"shouldSave": true, "content": "用户希望回复简洁，不要用列表"}')
    await extract_memory(
        pg_pool, provider, "tenant-save", "s1", "run-2", "以后回复别用列表，太啰嗦了", "好的，以后我会用简洁的段落回复。"
    )
    rows = await list_raw_memories_for_tenant(pg_pool, "tenant-save")
    assert [r.content for r in rows] == ["用户希望回复简洁，不要用列表"]


async def test_treats_malformed_model_output_as_a_noop_rather_than_raising(pg_pool) -> None:
    provider = FakeProvider("not valid json at all")
    await extract_memory(pg_pool, provider, "tenant-malformed", "s1", "run-3", "hi", "hello")
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-malformed") == []


async def test_treats_shouldSave_true_with_missing_content_as_a_noop(pg_pool) -> None:
    provider = FakeProvider('{"shouldSave": true}')
    await extract_memory(pg_pool, provider, "tenant-missing-content", "s1", "run-4", "hi", "hello")
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-missing-content") == []


async def test_treats_a_non_boolean_shouldSave_value_as_a_noop(pg_pool) -> None:
    provider = FakeProvider('{"shouldSave": "yes", "content": "should not be saved"}')
    await extract_memory(pg_pool, provider, "tenant-wrong-type", "s1", "run-5", "hi", "hello")
    assert await list_raw_memories_for_tenant(pg_pool, "tenant-wrong-type") == []
