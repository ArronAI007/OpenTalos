"""SQLite 会话仓储（任务/Agent/项目/评估/MCP server）。消息（情景记忆）和跨会话
记忆（语义记忆）的真实存储已经搬到 packages/memory，这里只持有它们的实例。同步实现——FastAPI
的 def/async 端点内用 asyncio.to_thread 或直接调用（操作均为毫秒级）；不引第三方 ORM。"""
import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from memory import EmbeddingClient, EpisodicMemory, SemanticMemory

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
  project_id TEXT,  -- 可空：所属项目；NULL = 未归组
  agent_id TEXT  -- 可空：用户自建 Agent（agents.id）；NULL = 默认 Agent。不设外键：删 Agent 不连带删任务
);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  system_prompt TEXT NOT NULL,  -- 角色设定：追加在默认 ReAct 提示词之后，不替换
  skills TEXT NOT NULL,         -- JSON 字符串数组：限定可用技能；空数组 = 不额外限定（用「我的技能」）
  source_prompt TEXT NOT NULL   -- 用户当初那一句话，仅供展示
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
CREATE TABLE IF NOT EXISTS provider_configs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL,         -- 'chat' | 'embedding'
  backend TEXT,                  -- 'anthropic' | 'openai-compatible' | 'mock'；purpose='embedding' 时为 NULL
  base_url TEXT,
  api_key TEXT NOT NULL,         -- 数据库存明文；序列化成 dict 时必须掩码（见 _provider_config_row_to_dict）
  model_name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0  -- 同一 purpose 下任意时刻最多一行为 1，由应用层保证
);
"""

_PROVIDER_CONFIG_PURPOSES = {"chat", "embedding"}
_PROVIDER_CONFIG_CHAT_BACKENDS = {"anthropic", "openai-compatible", "mock"}


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return "****"
    return "*" * (len(api_key) - 4) + api_key[-4:]


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


class ChatStore:
    def __init__(self, path: Path, embedder: EmbeddingClient | None = None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)
        self.episodic = EpisodicMemory(self._path)
        # 显式传入的 embedder（测试/脚本路径）永远返回它自己，不查 provider_configs；
        # 否则每次调用都重新解析一次激活的 embedding 配置（免重启生效）。
        embedder_factory = (lambda: embedder) if embedder is not None else (lambda: _resolve_embedding_client(self))
        self.semantic = SemanticMemory(self._path, embedder_factory)

    # 轻量迁移清单：CREATE TABLE IF NOT EXISTS 不会改造既有表，旧库缺列时逐条 ALTER 补上。
    # 仅列级变更需要登记在此；新表（如 projects）由 _SCHEMA 的 CREATE TABLE IF NOT EXISTS
    # 在既有库连上时直接补建，不需要进本清单。
    _MIGRATIONS = (
        ("pinned", "ALTER TABLE tasks ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"),
        ("starred", "ALTER TABLE tasks ADD COLUMN starred INTEGER NOT NULL DEFAULT 0"),
        ("archived", "ALTER TABLE tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"),
        ("project_id", "ALTER TABLE tasks ADD COLUMN project_id TEXT"),
        ("agent_id", "ALTER TABLE tasks ADD COLUMN agent_id TEXT"),
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

    def create_task(self, agent_type: str, agent_id: str | None = None) -> dict:
        task_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, agent_type, agent_id, created_at, updated_at) VALUES (?, '', ?, ?, ?, ?)",
                (task_id, agent_type, agent_id, now, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict | None:
        with self._connect() as conn:
            # agent_name：用户自建 Agent 的名字（前端输入框展示）；默认 Agent / 已删除的 Agent 为 NULL
            row = conn.execute(
                "SELECT t.*, a.name AS agent_name FROM tasks t LEFT JOIN agents a ON a.id = t.agent_id"
                " WHERE t.id = ?",
                (task_id,),
            ).fetchone()
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
        row = self.episodic.append_message(task_id, kind, content)
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (row["created_at"], task_id))
        return row

    def list_messages(self, task_id: str) -> list[dict]:
        return self.episodic.list_messages(task_id)

    def delete_turn(self, task_id: str, message_id: int) -> bool:
        return self.episodic.delete_turn(task_id, message_id)

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

    def create_provider_config(
        self, *, name: str, purpose: str, backend: str | None, base_url: str | None, api_key: str, model_name: str
    ) -> dict:
        if purpose not in _PROVIDER_CONFIG_PURPOSES:
            raise ValueError(f"purpose 必须是 {_PROVIDER_CONFIG_PURPOSES} 之一，收到 {purpose!r}")
        if purpose == "chat":
            if backend not in _PROVIDER_CONFIG_CHAT_BACKENDS:
                raise ValueError(f"purpose='chat' 时 backend 必须是 {_PROVIDER_CONFIG_CHAT_BACKENDS} 之一，收到 {backend!r}")
        elif backend is not None:
            raise ValueError("purpose='embedding' 时 backend 必须为空")

        config_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO provider_configs (id, created_at, name, purpose, backend, base_url, api_key, model_name, active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (config_id, now, name, purpose, backend, base_url, api_key, model_name),
            )
        return self.get_provider_config(config_id)

    @staticmethod
    def _provider_config_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "purpose": row["purpose"],
            "backend": row["backend"],
            "base_url": row["base_url"],
            "api_key_masked": _mask_api_key(row["api_key"]),
            "model_name": row["model_name"],
            "active": bool(row["active"]),
        }

    def get_provider_config(self, config_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM provider_configs WHERE id = ?", (config_id,)).fetchone()
        return self._provider_config_row_to_dict(row) if row else None

    def list_provider_configs(self, purpose: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if purpose is not None:
                rows = conn.execute(
                    "SELECT * FROM provider_configs WHERE purpose = ? ORDER BY created_at DESC, rowid DESC",
                    (purpose,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM provider_configs ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._provider_config_row_to_dict(row) for row in rows]

    def update_provider_config(
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> dict | None:
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (("name", name), ("base_url", base_url), ("api_key", api_key), ("model_name", model_name)):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        if not fields:
            return self.get_provider_config(config_id)
        values.append(config_id)
        with self._connect() as conn:
            cursor = conn.execute(f"UPDATE provider_configs SET {', '.join(fields)} WHERE id = ?", values)
            if cursor.rowcount == 0:
                return None
        return self.get_provider_config(config_id)

    def set_provider_config_active(self, config_id: str) -> dict | None:
        """同一事务内先把目标行所属 purpose 的其余行 active 置 0，再把目标行置 1。"""
        with self._connect() as conn:
            target = conn.execute("SELECT purpose FROM provider_configs WHERE id = ?", (config_id,)).fetchone()
            if target is None:
                return None
            conn.execute("UPDATE provider_configs SET active = 0 WHERE purpose = ?", (target["purpose"],))
            conn.execute("UPDATE provider_configs SET active = 1 WHERE id = ?", (config_id,))
        return self.get_provider_config(config_id)

    def set_provider_config_inactive(self, config_id: str) -> dict | None:
        with self._connect() as conn:
            cursor = conn.execute("UPDATE provider_configs SET active = 0 WHERE id = ?", (config_id,))
            if cursor.rowcount == 0:
                return None
        return self.get_provider_config(config_id)

    def delete_provider_config(self, config_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM provider_configs WHERE id = ?", (config_id,))
            return cursor.rowcount > 0

    def get_active_provider_config(self, purpose: str) -> dict | None:
        """内部使用：返回明文 `api_key` 的激活配置行（不经过掩码）。只供 `runtime.py`/
        embedding 工厂这类需要真正构造客户端的调用方使用，绝不能通过 HTTP API 直接暴露。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM provider_configs WHERE purpose = ? AND active = 1", (purpose,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "purpose": row["purpose"],
            "backend": row["backend"],
            "base_url": row["base_url"],
            "api_key": row["api_key"],
            "model_name": row["model_name"],
        }

    @staticmethod
    def _agent_row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "name": row["name"],
            "description": row["description"],
            "system_prompt": row["system_prompt"],
            "skills": json.loads(row["skills"]),
            "source_prompt": row["source_prompt"],
        }

    def create_agent(
        self, *, name: str, description: str, system_prompt: str, skills: list[str], source_prompt: str
    ) -> dict:
        agent_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agents (id, created_at, name, description, system_prompt, skills, source_prompt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_id, _now(), name, description, system_prompt, json.dumps(skills, ensure_ascii=False), source_prompt),
            )
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return self._agent_row_to_dict(row) if row else None

    def list_agents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._agent_row_to_dict(row) for row in rows]

    def delete_agent(self, agent_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            return cursor.rowcount > 0


def _resolve_embedding_client(store: ChatStore) -> EmbeddingClient:
    """查一次 provider_configs 表的激活 embedding 配置；没有则回退现状的环境变量构造方式。"""
    active = store.get_active_provider_config("embedding")
    if active is None:
        return EmbeddingClient()
    return EmbeddingClient(model_name=active["model_name"], api_key=active["api_key"], base_url=active["base_url"])
