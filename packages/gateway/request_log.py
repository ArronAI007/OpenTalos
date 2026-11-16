"""Persistent request log for the local model gateway."""

from __future__ import annotations

import datetime
import sqlite3
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_requests (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  model_requested TEXT NOT NULL,
  model_resolved TEXT,
  provider TEXT,
  account_name TEXT,
  stream INTEGER NOT NULL,
  client TEXT,
  status TEXT NOT NULL,
  http_status INTEGER,
  duration_ms INTEGER,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
"""


class GatewayRequestLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def start(
        self,
        *,
        model_requested: str,
        stream: bool,
        client: str | None,
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO gateway_requests"
                " (id, created_at, model_requested, stream, client, status)"
                " VALUES (?, ?, ?, ?, ?, 'running')",
                (request_id, _now(), model_requested, int(stream), client),
            )
        return self.get(request_id)

    def finish(
        self,
        request_id: str,
        *,
        status: str,
        model_resolved: str | None = None,
        provider: str | None = None,
        account_name: str | None = None,
        http_status: int | None = None,
        duration_ms: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE gateway_requests SET finished_at = ?, status = ?,"
                " model_resolved = ?, provider = ?, account_name = ?,"
                " http_status = ?, duration_ms = ?, input_tokens = ?,"
                " output_tokens = ?, error = ? WHERE id = ?",
                (
                    _now(),
                    status,
                    model_resolved,
                    provider,
                    account_name,
                    http_status,
                    duration_ms,
                    input_tokens,
                    output_tokens,
                    error,
                    request_id,
                ),
            )

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _row(row) if row else None

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM gateway_requests"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["stream"] = bool(value["stream"])
    value["total_tokens"] = int(value["input_tokens"]) + int(value["output_tokens"])
    return value


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
