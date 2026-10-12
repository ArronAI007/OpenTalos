"""长期记忆的真实实现：跨会话记住用户的稳定信息，SQLite 持久化 + embedding 语义检索。

和 EpisodicMemory 一样，持自己的 sqlite3 连接，物理上和 ChatStore 共用同一个数据库文件。
"""
import asyncio
import datetime
import json
import sqlite3
from pathlib import Path

from .embedding import EmbeddingClient

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL UNIQUE,  -- 一条跨会话的稳定用户信息；同内容去重
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  embedding TEXT                 -- JSON 序列化的 float 数组；升级前的旧行为 NULL，recall 时懒补齐
);
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LongTermMemory:
    def __init__(self, path: Path, embedder: EmbeddingClient) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_or_touch(self, content: str, embedding: list[float]) -> dict:
        now = _now()
        embedding_json = json.dumps(embedding)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (content, created_at, updated_at, embedding) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(content) DO UPDATE SET updated_at = excluded.updated_at, embedding = excluded.embedding",
                (content, now, now, embedding_json),
            )
            row = conn.execute("SELECT * FROM memories WHERE content = ?", (content,)).fetchone()
        return dict(row)

    async def remember(self, content: str) -> dict:
        # 同内容 upsert：重复提取不叠加，只刷新 updated_at（和旧的 remember_memory 行为一致）。
        embedding = await self._embedder.embed(content)
        return await asyncio.to_thread(self._insert_or_touch, content, embedding)

    def list_memories(self) -> list[dict]:
        # 新在前：召回同分时优先保留更新的记忆。纯同步——不涉及 embedding 调用，供 recall()
        # 用 asyncio.to_thread 包一层调用，也供测试/其它同步上下文直接调用。
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def _save_embedding(self, memory_id: int, embedding: list[float]) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE memories SET embedding = ? WHERE id = ?", (json.dumps(embedding), memory_id))

    async def recall(self, query: str, limit: int = 5) -> list[str]:
        query_vector = await self._embedder.embed(query)
        rows = await asyncio.to_thread(self.list_memories)
        scored: list[tuple[float, str]] = []
        for row in rows:
            if row["embedding"] is None:
                # 懒补齐：升级前就存在、还没算过 embedding 的旧行，现算一次存回去。
                vector = await self._embedder.embed(row["content"])
                await asyncio.to_thread(self._save_embedding, row["id"], vector)
            else:
                vector = json.loads(row["embedding"])
            similarity = _cosine_similarity(query_vector, vector)
            if similarity > 0:
                scored.append((similarity, row["content"]))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [content for _, content in scored[:limit]]
