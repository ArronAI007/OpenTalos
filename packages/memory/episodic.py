"""情景记忆的真实实现：每个任务的完整对话历史，SQLite 持久化。

和 ChatStore 共用同一个物理数据库文件，但是独立的连接对象——级联删除（任务删除时自动清掉
它的消息）依赖的是 messages 表里 `ON DELETE CASCADE` 这条约束本身和执行 DELETE 的那个连接
（ChatStore._connect()）是否开着 PRAGMA foreign_keys，和这里的连接是否开无关。这里的连接刻意
不开 foreign_keys，这样可以直接插入任意 task_id 做单测，不需要先用 ChatStore 建一个真任务。
"""
import datetime
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,           -- 'user' | 'assistant' | 'tool' | 'summary' | 'stopped'
  content TEXT NOT NULL,        -- tool 行存 JSON: {"call_id","name","arguments","result","ok"}; summary 行存 Surface 快照 JSON
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


class EpisodicMemory:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def append_message(self, task_id: str, kind: str, content: str) -> dict:
        # stopped：会话被中断（前端停止/断连）的标记行，无内容，仅让刷新后仍能见到"已停止"
        if kind not in ("user", "assistant", "tool", "summary", "stopped"):
            raise ValueError(f"unknown message kind: {kind}")
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (task_id, kind, content, created_at) VALUES (?, ?, ?, ?)",
                (task_id, kind, content, now),
            )
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def list_messages(self, task_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def delete_turn(self, task_id: str, message_id: int) -> bool:
        """删除一整轮问答：目标 user 行 + 其后直到下一条 user 行之前的所有行。

        目标行必须存在、属于该任务、且 kind == 'user'，否则不删任何行返回 False。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind FROM messages WHERE id = ? AND task_id = ?", (message_id, task_id),
            ).fetchone()
            if row is None or row["kind"] != "user":
                return False
            next_user = conn.execute(
                "SELECT MIN(id) AS n FROM messages WHERE task_id = ? AND id > ? AND kind = 'user'",
                (task_id, message_id),
            ).fetchone()["n"]
            if next_user is None:
                conn.execute("DELETE FROM messages WHERE task_id = ? AND id >= ?", (task_id, message_id))
            else:
                conn.execute(
                    "DELETE FROM messages WHERE task_id = ? AND id >= ? AND id < ?",
                    (task_id, message_id, next_user),
                )
            return True
