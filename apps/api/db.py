"""SQLite 会话/消息仓储。同步实现——FastAPI 的 def/async 端点内用 asyncio.to_thread
或直接调用（操作均为毫秒级）；不引第三方 ORM。"""
import datetime
import sqlite3
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  agent_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,  -- SQLite 布尔：0 未固定 / 1 已固定
  starred INTEGER NOT NULL DEFAULT 0,  -- SQLite 布尔：0 未收藏 / 1 已收藏
  archived INTEGER NOT NULL DEFAULT 0,  -- SQLite 布尔：0 未归档 / 1 已归档
  project_id TEXT  -- 可空：所属项目；NULL = 未归组
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,           -- 'user' | 'assistant' | 'tool' | 'stopped'
  content TEXT NOT NULL,        -- tool 行存 JSON: {"name","arguments","result","ok"}
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


class ChatStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    # 轻量迁移清单：CREATE TABLE IF NOT EXISTS 不会改造既有表，旧库缺列时逐条 ALTER 补上。
    # 仅列级变更需要登记在此；新表（如 projects）由 _SCHEMA 的 CREATE TABLE IF NOT EXISTS
    # 在既有库连上时直接补建，不需要进本清单。
    _MIGRATIONS = (
        ("pinned", "ALTER TABLE tasks ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"),
        ("starred", "ALTER TABLE tasks ADD COLUMN starred INTEGER NOT NULL DEFAULT 0"),
        ("archived", "ALTER TABLE tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"),
        ("project_id", "ALTER TABLE tasks ADD COLUMN project_id TEXT"),
    )

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        for column, statement in ChatStore._MIGRATIONS:
            if column not in columns:
                conn.execute(statement)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_task(self, agent_type: str) -> dict:
        task_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, agent_type, created_at, updated_at) VALUES (?, '', ?, ?, ?)",
                (task_id, agent_type, now, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self) -> list[dict]:
        # 主列表只含未归档任务
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE archived = 0"
                " ORDER BY pinned DESC, starred DESC, updated_at DESC, rowid DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_archived_tasks(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE archived = 1 ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_task(self, task_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0

    def append_message(self, task_id: str, kind: str, content: str) -> dict:
        # stopped：会话被中断（前端停止/断连）的标记行，无内容，仅让刷新后仍能见到"已停止"
        if kind not in ("user", "assistant", "tool", "stopped"):
            raise ValueError(f"unknown message kind: {kind}")
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (task_id, kind, content, created_at) VALUES (?, ?, ?, ?)",
                (task_id, kind, content, now),
            )
            conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id))
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def list_messages(self, task_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def update_task(self, task_id: str, **fields: str | int | None) -> dict | None:
        """通用字段更新通道，返回更新后的任务；任务不存在返回 None。

        落地 title / pinned / starred / archived / project_id 列；后续新字段经同一通道扩展：
        在 _UPDATABLE_COLUMNS 白名单中加列名即可（列名须已存在于 schema）。白名单同时
        保证 SQL 列名不可注入。project_id 可传 None，置 NULL 表示移出项目。
        """
        _UPDATABLE_COLUMNS = {"title", "pinned", "starred", "archived", "project_id"}
        updates = {k: v for k, v in fields.items() if k in _UPDATABLE_COLUMNS}
        if not updates:
            return self.get_task(task_id)
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                (*updates.values(), task_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_task(task_id)

    def set_title_if_empty(self, task_id: str, title: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET title = ? WHERE id = ? AND title = ''", (title, task_id))

    def create_project(self, name: str) -> dict:
        project_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, _now()),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self) -> list[dict]:
        # 最新创建的项目在前；rowid 作同刻 tiebreak，与 list_tasks 同款写法
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC, rowid DESC").fetchall()
        return [dict(row) for row in rows]
