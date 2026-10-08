"""AgentRL 训练任务的独立 SQLite 仓储——不依赖本仓库任何其他包，风格参照 apps/api/db.py。"""
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
  config TEXT NOT NULL,        -- JSON
  metrics TEXT NOT NULL,       -- JSON: {"sft_loss": [...], "grpo_reward": [...]}
  result TEXT,                 -- JSON，训练完成后的样例对比；未完成/失败时为 NULL
  error TEXT                   -- 失败信息；成功/进行中为 NULL
);
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")


class RunStore:
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
            "config": json.loads(row["config"]),
            "metrics": json.loads(row["metrics"]),
            "result": json.loads(row["result"]) if row["result"] is not None else None,
            "error": row["error"],
        }

    def create_run(self, config: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        now = _now()
        metrics = {"sft_loss": [], "grpo_reward": []}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, status, config, metrics, result, error)"
                " VALUES (?, ?, 'running', ?, ?, NULL, NULL)",
                (run_id, now, json.dumps(config), json.dumps(metrics)),
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

    def append_metric(self, run_id: str, key: str, value: float) -> None:
        """key 是 'sft_loss' 或 'grpo_reward'，往对应曲线数组尾部追加一个点位。"""
        run = self.get_run(run_id)
        if run is None:
            return
        metrics = run["metrics"]
        metrics.setdefault(key, []).append(value)
        with self._connect() as conn:
            conn.execute("UPDATE runs SET metrics = ? WHERE id = ?", (json.dumps(metrics), run_id))

    def update_run(
        self, run_id: str, *, status: str | None = None, result: list | None = None, error: str | None = None
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if result is not None:
            updates["result"] = json.dumps(result)
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
