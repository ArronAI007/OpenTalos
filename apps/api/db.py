"""SQLite 会话/消息仓储。同步实现——FastAPI 的 def/async 端点内用 asyncio.to_thread
或直接调用（操作均为毫秒级）；不引第三方 ORM。"""
import datetime
import json
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
  kind TEXT NOT NULL,           -- 'user' | 'assistant' | 'tool' | 'summary' | 'stopped'
  content TEXT NOT NULL,        -- tool 行存 JSON: {"call_id","name","arguments","result","ok"}; summary 行存 Surface 快照 JSON
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  results TEXT NOT NULL  -- JSON 序列化的 EvalResult 列表；整轮一起读写，不拆子表
);
CREATE TABLE IF NOT EXISTS deepresearch_runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,        -- 'running' | 'completed' | 'failed'
  topic TEXT NOT NULL,
  todos TEXT NOT NULL,         -- JSON: [{id, query, status, summary, sources}]
  report TEXT,                 -- 最终 markdown 报告；未完成/失败为 NULL
  error TEXT                   -- 失败信息；成功/进行中为 NULL
);
CREATE TABLE IF NOT EXISTS mcp_servers (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  transport TEXT NOT NULL,       -- 'stdio' | 'http'
  config TEXT NOT NULL,          -- JSON：{command, args} 或 {url}
  enabled INTEGER NOT NULL DEFAULT 1,
  cached_tools TEXT NOT NULL,    -- JSON 数组：[{name, description, input_schema}]
  last_error TEXT                -- 最近一次探测/刷新失败的错误信息；成功为 NULL
);
CREATE TABLE IF NOT EXISTS agent_roles (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  peer_url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1
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
        if kind not in ("user", "assistant", "tool", "summary", "stopped"):
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

    def delete_turn(self, task_id: str, message_id: int) -> bool:
        """删除一整轮问答：目标 user 行 + 其后直到下一条 user 行之前的所有行。

        目标行必须存在、属于该任务、且 kind == 'user'，否则不删任何行返回 False。
        不动 tasks.updated_at：删除是清理操作，不改变会话的活动排序。
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

    def save_eval_run(self, results: list[dict]) -> dict:
        run_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO eval_runs (id, created_at, results) VALUES (?, ?, ?)",
                (run_id, now, json.dumps(results)),
            )
        return {"id": run_id, "created_at": now, "results": results}

    def list_eval_runs(self) -> list[dict]:
        # 最新一次评估排最前；rowid 作同刻 tiebreak，与 list_projects 同款写法
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM eval_runs ORDER BY created_at DESC, rowid DESC").fetchall()
        return [{"id": row["id"], "created_at": row["created_at"], "results": json.loads(row["results"])} for row in rows]

    def delete_eval_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM eval_runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0

    def create_deepresearch_run(self, topic: str) -> dict:
        run_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO deepresearch_runs (id, created_at, status, topic, todos, report, error)"
                " VALUES (?, ?, 'running', ?, '[]', NULL, NULL)",
                (run_id, now, topic),
            )
        return self.get_deepresearch_run(run_id)

    @staticmethod
    def _deepresearch_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "status": row["status"],
            "topic": row["topic"],
            "todos": json.loads(row["todos"]),
            "report": row["report"],
            "error": row["error"],
        }

    def get_deepresearch_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM deepresearch_runs WHERE id = ?", (run_id,)).fetchone()
        return self._deepresearch_row_to_dict(row) if row else None

    def list_deepresearch_runs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM deepresearch_runs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [self._deepresearch_row_to_dict(row) for row in rows]

    def update_deepresearch_run_todos(self, run_id: str, todos: list[dict]) -> None:
        """规划阶段结束后整体替换 todos 列表（从空数组变成完整的待办列表）。"""
        with self._connect() as conn:
            conn.execute("UPDATE deepresearch_runs SET todos = ? WHERE id = ?", (json.dumps(todos), run_id))

    def update_deepresearch_todo(self, run_id: str, todo_id: int, **fields: object) -> None:
        """按 id 更新单条 TODO 的字段（status/summary/sources）；run 不存在则静默跳过。"""
        run = self.get_deepresearch_run(run_id)
        if run is None:
            return
        todos = run["todos"]
        for todo in todos:
            if todo["id"] == todo_id:
                todo.update(fields)
                break
        with self._connect() as conn:
            conn.execute("UPDATE deepresearch_runs SET todos = ? WHERE id = ?", (json.dumps(todos), run_id))

    def update_deepresearch_run(
        self, run_id: str, *, status: str | None = None, report: str | None = None, error: str | None = None
    ) -> dict | None:
        updates: dict = {}
        if status is not None:
            updates["status"] = status
        if report is not None:
            updates["report"] = report
        if error is not None:
            updates["error"] = error
        if not updates:
            return self.get_deepresearch_run(run_id)
        assignments = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE deepresearch_runs SET {assignments} WHERE id = ?", (*updates.values(), run_id)
            )
            if cursor.rowcount == 0:
                return None
        return self.get_deepresearch_run(run_id)

    def delete_deepresearch_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM deepresearch_runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0

    def create_mcp_server(
        self, *, name: str, transport: str, config: dict, cached_tools: list[dict]
    ) -> dict:
        server_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mcp_servers (id, created_at, name, transport, config, enabled, cached_tools, last_error)"
                " VALUES (?, ?, ?, ?, ?, 1, ?, NULL)",
                (server_id, now, name, transport, json.dumps(config), json.dumps(cached_tools)),
            )
        return self.get_mcp_server(server_id)

    @staticmethod
    def _mcp_server_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "transport": row["transport"],
            "config": json.loads(row["config"]),
            "enabled": bool(row["enabled"]),
            "cached_tools": json.loads(row["cached_tools"]),
            "last_error": row["last_error"],
        }

    def get_mcp_server(self, server_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        return self._mcp_server_row_to_dict(row) if row else None

    def list_mcp_servers(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM mcp_servers ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._mcp_server_row_to_dict(row) for row in rows]

    def set_mcp_server_enabled(self, server_id: str, enabled: bool) -> dict | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE mcp_servers SET enabled = ? WHERE id = ?", (1 if enabled else 0, server_id)
            )
            if cursor.rowcount == 0:
                return None
        return self.get_mcp_server(server_id)

    def update_mcp_server_probe_result(
        self, server_id: str, *, last_error: str | None, cached_tools: list[dict] | None = None
    ) -> dict | None:
        """刷新探测结果：成功时传 cached_tools（整体替换）+ last_error=None（清空旧错误）；
        失败时只传 last_error，cached_tools 保持不变（不能用"非 None 才更新"的通用模式——
        成功时必须能把 last_error 显式写回 NULL，那种模式做不到"清空"这个操作）。"""
        with self._connect() as conn:
            if cached_tools is not None:
                cursor = conn.execute(
                    "UPDATE mcp_servers SET cached_tools = ?, last_error = ? WHERE id = ?",
                    (json.dumps(cached_tools), last_error, server_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE mcp_servers SET last_error = ? WHERE id = ?", (last_error, server_id)
                )
            if cursor.rowcount == 0:
                return None
        return self.get_mcp_server(server_id)

    def delete_mcp_server(self, server_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
            return cursor.rowcount > 0

    def create_agent_role(self, *, name: str, description: str, peer_url: str) -> dict:
        role_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_roles (id, created_at, name, description, peer_url, enabled)"
                " VALUES (?, ?, ?, ?, ?, 1)",
                (role_id, now, name, description, peer_url),
            )
        return self.get_agent_role(role_id)

    @staticmethod
    def _agent_role_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "description": row["description"],
            "peer_url": row["peer_url"],
            "enabled": bool(row["enabled"]),
        }

    def get_agent_role(self, role_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agent_roles WHERE id = ?", (role_id,)).fetchone()
        return self._agent_role_row_to_dict(row) if row else None

    def list_agent_roles(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agent_roles ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._agent_role_row_to_dict(row) for row in rows]

    def set_agent_role_enabled(self, role_id: str, enabled: bool) -> dict | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_roles SET enabled = ? WHERE id = ?", (1 if enabled else 0, role_id)
            )
            if cursor.rowcount == 0:
                return None
        return self.get_agent_role(role_id)

    def delete_agent_role(self, role_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM agent_roles WHERE id = ?", (role_id,))
            return cursor.rowcount > 0
