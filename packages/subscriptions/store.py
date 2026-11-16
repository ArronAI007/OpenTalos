"""SQLite persistence for subscription inventory and warm-up schedules."""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscription_accounts (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  credential_path TEXT,
  signed_in INTEGER NOT NULL,
  project_id TEXT,
  models TEXT NOT NULL DEFAULT '[]',
  quota TEXT NOT NULL DEFAULT '{}',
  metadata TEXT NOT NULL DEFAULT '{}',
  last_refreshed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider, source)
);
CREATE TABLE IF NOT EXISTS subscription_warmups (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL,
  at_time TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  next_run_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(account_id) REFERENCES subscription_accounts(id) ON DELETE CASCADE
);
"""


class SubscriptionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def upsert_account(self, account: dict[str, Any]) -> dict[str, Any]:
        account_id = account.get("id") or uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM subscription_accounts"
                " WHERE provider = ? AND source = ?",
                (account["provider"], account["source"]),
            ).fetchone()
            if existing is not None:
                account_id = existing["id"]
            connection.execute(
                "INSERT INTO subscription_accounts"
                " (id, provider, name, source, credential_path, signed_in,"
                " project_id, models, quota, metadata, last_refreshed_at,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(provider, source) DO UPDATE SET"
                " name = excluded.name, credential_path = excluded.credential_path,"
                " signed_in = excluded.signed_in, project_id = excluded.project_id,"
                " models = excluded.models, quota = excluded.quota,"
                " metadata = excluded.metadata,"
                " last_refreshed_at = excluded.last_refreshed_at,"
                " updated_at = excluded.updated_at",
                (
                    account_id,
                    account["provider"],
                    account["name"],
                    account["source"],
                    account.get("credential_path"),
                    int(account.get("signed_in", False)),
                    account.get("project_id"),
                    json.dumps(account.get("models", []), ensure_ascii=False),
                    json.dumps(account.get("quota", {}), ensure_ascii=False),
                    json.dumps(account.get("metadata", {}), ensure_ascii=False),
                    now,
                    now,
                    now,
                ),
            )
        return self.get_account(account_id)

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subscription_accounts"
                " ORDER BY provider, name, created_at"
            ).fetchall()
        return [_row(row) for row in rows]

    def get_account(self, account_id: str) -> dict[str, Any]:
        row = self.get_account_internal(account_id)
        if row is None:
            raise ValueError("subscription account not found")
        return _row(row)

    def get_account_internal(self, account_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM subscription_accounts WHERE id = ?", (account_id,)
            ).fetchone()

    def mark_missing(self, active_sources: set[tuple[str, str]]) -> None:
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, provider, source FROM subscription_accounts"
            ).fetchall()
            for row in rows:
                if (row["provider"], row["source"]) not in active_sources:
                    connection.execute(
                        "UPDATE subscription_accounts SET signed_in = 0, updated_at = ?"
                        " WHERE id = ?",
                        (now, row["id"]),
                    )

    def create_warmup(
        self,
        account_id: str,
        *,
        mode: str,
        at_time: str,
        next_run_at: str,
    ) -> dict[str, Any]:
        if self.get_account_internal(account_id) is None:
            raise ValueError("subscription account not found")
        now = _now()
        warmup_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO subscription_warmups"
                " (id, account_id, mode, at_time, next_run_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(account_id) DO UPDATE SET mode = excluded.mode,"
                " at_time = excluded.at_time, enabled = 1,"
                " next_run_at = excluded.next_run_at, updated_at = excluded.updated_at",
                (
                    warmup_id,
                    account_id,
                    mode,
                    at_time,
                    next_run_at,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM subscription_warmups WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return _warmup_row(row)

    def list_warmups(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subscription_warmups ORDER BY next_run_at"
            ).fetchall()
        return [_warmup_row(row) for row in rows]

    def due_warmups(self, now: datetime.datetime) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subscription_warmups"
                " WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now.isoformat(),),
            ).fetchall()
        return [_warmup_row(row) for row in rows]

    def complete_warmup(
        self,
        warmup_id: str,
        *,
        run_at: datetime.datetime,
        next_run_at: datetime.datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE subscription_warmups SET last_run_at = ?,"
                " next_run_at = ?, updated_at = ? WHERE id = ?",
                (run_at.isoformat(), next_run_at.isoformat(), _now(), warmup_id),
            )

    def set_warmup_enabled(self, warmup_id: str, enabled: bool) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE subscription_warmups SET enabled = ?, updated_at = ?"
                " WHERE id = ?",
                (int(enabled), _now(), warmup_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("warm-up schedule not found")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value.pop("credential_path", None)
    value["signed_in"] = bool(value["signed_in"])
    for field in ("models", "quota", "metadata"):
        value[field] = json.loads(value[field])
    return value


def _warmup_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["enabled"] = bool(value["enabled"])
    return value


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
