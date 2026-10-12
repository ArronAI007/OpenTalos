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
  embedding TEXT,                 -- JSON 序列化的 float 数组；升级前的旧行为 NULL，recall 时懒补齐
  importance REAL NOT NULL DEFAULT 0.5  -- 0.0-1.0，模型提取时顺带打分；旧行迁移后统一是默认值 0.5
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


class SemanticMemory:
    def __init__(self, path: Path, embedder: EmbeddingClient) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        if "embedding" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
        if "importance" not in columns:
            conn.execute("ALTER TABLE memories ADD COLUMN importance REAL NOT NULL DEFAULT 0.5")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_or_touch(self, content: str, embedding: list[float], importance: float) -> dict:
        now = _now()
        embedding_json = json.dumps(embedding)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (content, created_at, updated_at, embedding, importance) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(content) DO UPDATE SET "
                "updated_at = excluded.updated_at, embedding = excluded.embedding, importance = excluded.importance",
                (content, now, now, embedding_json, importance),
            )
            row = conn.execute("SELECT * FROM memories WHERE content = ?", (content,)).fetchone()
        return dict(row)

    async def remember(self, content: str, importance: float = 0.5) -> dict:
        # 同内容 upsert：重复提取不叠加，只刷新 updated_at/importance（和旧的 remember_memory 行为一致）。
        embedding = await self._embedder.embed(content)
        return await asyncio.to_thread(self._insert_or_touch, content, embedding, importance)

    def list_memories(self) -> list[dict]:
        # 新在前：召回同分时优先保留更新的记忆。纯同步——不涉及 embedding 调用，供 recall()
        # 用 asyncio.to_thread 包一层调用，也供测试/其它同步上下文直接调用。
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def forget(
        self, strategy: str, *, threshold: float = 0.3, max_age_days: int = 30, max_count: int = 1000
    ) -> int:
        """按策略删除记忆，返回被删除的条数。"""
        with self._connect() as conn:
            if strategy == "importance_based":
                cursor = conn.execute("DELETE FROM memories WHERE importance < ?", (threshold,))
            elif strategy == "time_based":
                cutoff = (
                    datetime.datetime.now() - datetime.timedelta(days=max_age_days)
                ).strftime("%Y-%m-%dT%H:%M:%S.%f")
                cursor = conn.execute("DELETE FROM memories WHERE updated_at < ?", (cutoff,))
            elif strategy == "capacity_based":
                cursor = conn.execute(
                    "DELETE FROM memories WHERE id NOT IN ("
                    "  SELECT id FROM memories ORDER BY importance DESC, updated_at DESC LIMIT ?"
                    ")",
                    (max_count,),
                )
            else:
                raise ValueError(f"unknown forget strategy: {strategy}")
            return cursor.rowcount

    def delete_memory(self, memory_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0

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

    def find_similar_groups(self, similarity_threshold: float = 0.9) -> list[list[dict]]:
        """贪心聚类：两两算余弦相似度（只用已存的 embedding，为 NULL 的行跳过——懒补齐是
        recall() 的职责，这里不做），相似度 >= 阈值的归到同一组。只返回成员数 >= 2 的组。"""
        rows = [row for row in self.list_memories() if row["embedding"] is not None]
        vectors = {row["id"]: json.loads(row["embedding"]) for row in rows}
        assigned: set[int] = set()
        groups: list[list[dict]] = []
        for row in rows:
            if row["id"] in assigned:
                continue
            group = [row]
            assigned.add(row["id"])
            for other in rows:
                if other["id"] in assigned:
                    continue
                if _cosine_similarity(vectors[row["id"]], vectors[other["id"]]) >= similarity_threshold:
                    group.append(other)
                    assigned.add(other["id"])
            if len(group) >= 2:
                groups.append(group)
        return groups

    def _replace_with_merged_sync(
        self, old_ids: list[int], content: str, embedding: list[float], importance: float
    ) -> dict:
        now = _now()
        embedding_json = json.dumps(embedding)
        with self._connect() as conn:
            conn.executemany("DELETE FROM memories WHERE id = ?", [(old_id,) for old_id in old_ids])
            conn.execute(
                "INSERT INTO memories (content, created_at, updated_at, embedding, importance) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(content) DO UPDATE SET "
                "updated_at = excluded.updated_at, embedding = excluded.embedding, importance = excluded.importance",
                (content, now, now, embedding_json, importance),
            )
            row = conn.execute("SELECT * FROM memories WHERE content = ?", (content,)).fetchone()
        return dict(row)

    async def replace_with_merged(self, old_ids: list[int], merged_content: str, importance: float) -> dict:
        embedding = await self._embedder.embed(merged_content)
        return await asyncio.to_thread(
            self._replace_with_merged_sync, old_ids, merged_content, embedding, importance
        )
