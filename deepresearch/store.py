"""DeepResearch 研究任务的独立 SQLite 仓储——不依赖本仓库任何其他包，风格参照 agentrl/store.py。"""
import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,        -- 'running' | 'completed' | 'failed'
  topic TEXT NOT NULL,
  todos TEXT NOT NULL,         -- JSON: [{id, query, status, summary, sources}]
  report TEXT,                 -- 最终 markdown 报告；未完成/失败为 NULL
  error TEXT                   -- 失败信息；成功/进行中为 NULL
);
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


class DeepResearchStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "status": row["status"],
            "topic": row["topic"],
            "todos": json.loads(row["todos"]),
            "report": row["report"],
            "error": row["error"],
        }

    def create_run(self, topic: str) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, status, topic, todos, report, error)"
                " VALUES (?, ?, 'running', ?, '[]', NULL, NULL)",
                (run_id, now, topic),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_run_todos(self, run_id: str, todos: list[dict]) -> None:
        """规划阶段结束后整体替换 todos 列表（从空数组变成完整的待办列表）。"""
        with self._connect() as conn:
            conn.execute("UPDATE runs SET todos = ? WHERE id = ?", (json.dumps(todos), run_id))

    def update_todo(self, run_id: str, todo_id: int, **fields: object) -> None:
        """按 id 更新单条 TODO 的字段（status/summary/sources）；run 不存在则静默跳过。"""
        run = self.get_run(run_id)
        if run is None:
            return
        todos = run["todos"]
        for todo in todos:
            if todo["id"] == todo_id:
                todo.update(fields)
                break
        with self._connect() as conn:
            conn.execute("UPDATE runs SET todos = ? WHERE id = ?", (json.dumps(todos), run_id))

    def update_run(
        self, run_id: str, *, status: str | None = None, report: str | None = None, error: str | None = None
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if report is not None:
            updates["report"] = report
        if error is not None:
            updates["error"] = error
        if not updates:
            return self.get_run(run_id)
        assignments = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            cursor = conn.execute(f"UPDATE runs SET {assignments} WHERE id = ?", (*updates.values(), run_id))
            if cursor.rowcount == 0:
                return None
        return self.get_run(run_id)

    def delete_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0
