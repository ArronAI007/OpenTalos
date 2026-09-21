from db.bulk import (
    MemoryUpdate,
    NewMemory,
    delete_memories,
    delete_raw_memories,
    insert_raw_memory,
    list_memories_for_tenant,
    list_raw_memories_for_tenant,
    list_tenants_with_pending,
    upsert_memories,
)


async def test_insert_raw_memory_and_list_round_trips_scoped_to_tenant(pg_pool):
    await insert_raw_memory(pg_pool, "tenant-raw-a", "s1", "run-1", "喜欢简洁回复")
    await insert_raw_memory(pg_pool, "tenant-raw-b", "s1", "run-2", "住在北京")

    for_a = await list_raw_memories_for_tenant(pg_pool, "tenant-raw-a")
    assert [r.content for r in for_a] == ["喜欢简洁回复"]


async def test_list_tenants_with_pending_only_returns_tenants_with_rows(pg_pool):
    await insert_raw_memory(pg_pool, "tenant-pending", "s1", "run-3", "some fact")
    result = await list_tenants_with_pending(pg_pool, ["tenant-pending", "tenant-with-no-raw-memories"])
    assert result == ["tenant-pending"]


async def test_delete_raw_memories_removes_exactly_the_given_rows(pg_pool):
    await insert_raw_memory(pg_pool, "tenant-delete-raw", "s1", "run-4", "to be deleted")
    before = await list_raw_memories_for_tenant(pg_pool, "tenant-delete-raw")
    await delete_raw_memories(pg_pool, "tenant-delete-raw", [r.id for r in before])
    after = await list_raw_memories_for_tenant(pg_pool, "tenant-delete-raw")
    assert after == []


async def test_upsert_memories_inserts_new_entries_and_applies_updates(pg_pool):
    await upsert_memories(
        pg_pool, "tenant-upsert-bulk", [NewMemory(type="profile", title="职业", content="后端工程师")], []
    )
    existing = (await list_memories_for_tenant(pg_pool, "tenant-upsert-bulk"))[0]
    assert (existing.type, existing.title, existing.content) == ("profile", "职业", "后端工程师")

    await upsert_memories(pg_pool, "tenant-upsert-bulk", [], [MemoryUpdate(id=existing.id, content="全栈工程师")])
    updated = (await list_memories_for_tenant(pg_pool, "tenant-upsert-bulk"))[0]
    assert updated.content == "全栈工程师"
    assert updated.updated_at >= existing.updated_at


async def test_delete_memories_removes_exactly_the_given_rows(pg_pool):
    await upsert_memories(
        pg_pool, "tenant-delete-mem", [NewMemory(type="context", title="旅行计划", content="9 月去上海")], []
    )
    entry = (await list_memories_for_tenant(pg_pool, "tenant-delete-mem"))[0]
    await delete_memories(pg_pool, "tenant-delete-mem", [entry.id])
    assert await list_memories_for_tenant(pg_pool, "tenant-delete-mem") == []


async def test_list_memories_for_tenant_never_returns_another_tenants_rows(pg_pool):
    await upsert_memories(pg_pool, "tenant-iso-a", [NewMemory(type="profile", title="a-fact", content="a")], [])
    await upsert_memories(pg_pool, "tenant-iso-b", [NewMemory(type="profile", title="b-fact", content="b")], [])
    for_a = await list_memories_for_tenant(pg_pool, "tenant-iso-a")
    assert [m.title for m in for_a] == ["a-fact"]


async def test_delete_memories_cannot_delete_another_tenants_row_even_with_its_real_id(pg_pool):
    await upsert_memories(
        pg_pool, "tenant-cross-delete-owner", [NewMemory(type="profile", title="owner-fact", content="mine")], []
    )
    owned = (await list_memories_for_tenant(pg_pool, "tenant-cross-delete-owner"))[0]

    await delete_memories(pg_pool, "tenant-cross-delete-attacker", [owned.id])

    still_there = await list_memories_for_tenant(pg_pool, "tenant-cross-delete-owner")
    assert len(still_there) == 1
    assert still_there[0].id == owned.id


async def test_upsert_memories_updates_cannot_overwrite_another_tenants_row(pg_pool):
    await upsert_memories(
        pg_pool, "tenant-cross-update-owner", [NewMemory(type="profile", title="owner-fact", content="original")], []
    )
    owned = (await list_memories_for_tenant(pg_pool, "tenant-cross-update-owner"))[0]

    await upsert_memories(pg_pool, "tenant-cross-update-attacker", [], [MemoryUpdate(id=owned.id, content="hijacked")])

    still_original = await list_memories_for_tenant(pg_pool, "tenant-cross-update-owner")
    assert still_original[0].content == "original"
