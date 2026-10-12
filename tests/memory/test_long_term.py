import sqlite3
from pathlib import Path

from memory.embedding import EmbeddingClient
from memory.long_term import LongTermMemory


def _make_embedder(vectors: dict[str, list[float]]) -> EmbeddingClient:
    embedder = EmbeddingClient()

    async def fake_embed(text: str) -> list[float]:
        return vectors.get(text, [0.0, 0.0])

    embedder.embed = fake_embed  # type: ignore[method-assign]
    return embedder


async def test_remember_upserts_and_lists_newest_first(tmp_path: Path) -> None:
    embedder = _make_embedder({"用户叫张三": [1.0, 0.0], "用户喜欢简洁回复": [0.0, 1.0]})
    store = LongTermMemory(tmp_path / "memory.db", embedder)

    await store.remember("用户叫张三")
    await store.remember("用户喜欢简洁回复")
    await store.remember("用户叫张三")  # 同内容去重，只刷新 updated_at

    memories = store.list_memories()
    assert {m["content"] for m in memories} == {"用户叫张三", "用户喜欢简洁回复"}
    assert len(memories) == 2


async def test_recall_ranks_by_cosine_similarity(tmp_path: Path) -> None:
    embedder = _make_embedder(
        {
            "用户在做一个数据看板项目": [1.0, 0.0],
            "用户喜欢用中文": [0.0, 1.0],
            "数据看板项目进展如何": [1.0, 0.0],
        }
    )
    store = LongTermMemory(tmp_path / "memory.db", embedder)
    await store.remember("用户在做一个数据看板项目")
    await store.remember("用户喜欢用中文")

    result = await store.recall("数据看板项目进展如何")

    assert result == ["用户在做一个数据看板项目"]


async def test_recall_excludes_memories_with_zero_or_negative_similarity(tmp_path: Path) -> None:
    embedder = _make_embedder({"完全无关的记忆": [0.0, 1.0], "查询": [1.0, 0.0]})
    store = LongTermMemory(tmp_path / "memory.db", embedder)
    await store.remember("完全无关的记忆")

    assert await store.recall("查询") == []


async def test_recall_backfills_embeddings_for_legacy_rows_missing_one(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    embedder = _make_embedder({"老记忆": [1.0, 0.0], "查询": [1.0, 0.0]})
    store = LongTermMemory(db_path, embedder)
    # 模拟升级前就存在、还没有 embedding 列数据的旧行：绕过 remember() 直接插入
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (content, created_at, updated_at) VALUES (?, ?, ?)",
            ("老记忆", "2020-01-01T00:00:00", "2020-01-01T00:00:00"),
        )

    result = await store.recall("查询")

    assert result == ["老记忆"]
    backfilled = [m for m in store.list_memories() if m["content"] == "老记忆"][0]
    assert backfilled["embedding"] is not None


async def test_recall_respects_limit(tmp_path: Path) -> None:
    vectors = {f"记忆{i}": [1.0, 0.0] for i in range(10)}
    vectors["查询"] = [1.0, 0.0]
    embedder = _make_embedder(vectors)
    store = LongTermMemory(tmp_path / "memory.db", embedder)
    for i in range(10):
        await store.remember(f"记忆{i}")

    result = await store.recall("查询", limit=3)

    assert len(result) == 3
