"""SQLite persistence for provider accounts, models, and control-plane profiles."""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from model_platform.discovery import ModelDescriptor

_SCHEMA = """
CREATE TABLE IF NOT EXISTS control_provider_accounts (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  backend TEXT NOT NULL,
  base_url TEXT,
  api_key TEXT NOT NULL,
  proxy_url TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE(provider, name)
);
CREATE TABLE IF NOT EXISTS control_models (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  protocol TEXT NOT NULL,
  context_window INTEGER,
  supports_tools INTEGER NOT NULL,
  supports_thinking INTEGER NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  UNIQUE(account_id, model_id),
  FOREIGN KEY(account_id) REFERENCES control_provider_accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS control_profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routing_groups (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL,
  sticky INTEGER NOT NULL DEFAULT 1,
  intent_model TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routing_group_members (
  id TEXT PRIMARY KEY,
  group_id TEXT NOT NULL,
  target TEXT NOT NULL,
  position INTEGER NOT NULL,
  weight REAL NOT NULL DEFAULT 1,
  FOREIGN KEY(group_id) REFERENCES routing_groups(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS quota_snapshots (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  window_name TEXT NOT NULL,
  remaining REAL NOT NULL,
  limit_value REAL NOT NULL,
  unit TEXT NOT NULL,
  reset_at TEXT,
  read_at TEXT NOT NULL,
  FOREIGN KEY(account_id) REFERENCES control_provider_accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS routing_state (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS routing_session_bindings (
  session_key TEXT PRIMARY KEY,
  target TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

_ROUTING_MODES = {"order", "rotate", "usage", "smart", "pace", "weight"}


class ControlPlaneValidationError(ValueError):
    """Raised when a control-plane value violates its persistence contract."""


class ControlPlaneStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def create_account(
        self,
        *,
        provider: str,
        name: str,
        backend: str,
        api_key: str,
        base_url: str | None = None,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        provider = provider.strip()
        name = name.strip()
        api_key = api_key.strip()
        if not provider or not name or not api_key:
            raise ControlPlaneValidationError("provider, name, and api_key are required")
        if backend not in {"openai-compatible", "openai-responses", "anthropic", "gemini", "mock"}:
            raise ControlPlaneValidationError(f"unsupported backend: {backend}")
        base_url = _validated_url(base_url, "base_url")
        proxy_url = _validated_url(proxy_url, "proxy_url", allow_socks=True)
        account_id = uuid.uuid4().hex
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO control_provider_accounts"
                    " (id, created_at, updated_at, provider, name, backend, base_url,"
                    " api_key, proxy_url, enabled)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        account_id,
                        now,
                        now,
                        provider,
                        name,
                        backend,
                        base_url,
                        api_key,
                        proxy_url,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ControlPlaneValidationError(
                f"account {provider}/{name} already exists"
            ) from error
        account = self.get_account(account_id)
        if account is None:
            raise RuntimeError("created account could not be read")
        return account

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.*, COUNT(m.id) AS model_count"
                " FROM control_provider_accounts a"
                " LEFT JOIN control_models m ON m.account_id = a.id"
                " GROUP BY a.id"
                " ORDER BY a.created_at DESC, a.rowid DESC"
            ).fetchall()
        return [_account_row(row) for row in rows]

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT a.*, COUNT(m.id) AS model_count"
                " FROM control_provider_accounts a"
                " LEFT JOIN control_models m ON m.account_id = a.id"
                " WHERE a.id = ?"
                " GROUP BY a.id",
                (account_id,),
            ).fetchone()
        return _account_row(row) if row else None

    def get_account_secret(self, account_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM control_provider_accounts WHERE id = ?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_account(
        self,
        account_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        proxy_url: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("name", name.strip() if name is not None else None),
            ("base_url", _validated_url(base_url, "base_url")),
            ("api_key", api_key.strip() if api_key is not None else None),
            (
                "proxy_url",
                _validated_url(proxy_url, "proxy_url", allow_socks=True),
            ),
            ("enabled", int(enabled) if enabled is not None else None),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        if not fields:
            return self.get_account(account_id)
        fields.append("updated_at = ?")
        values.append(_now())
        values.append(account_id)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    f"UPDATE control_provider_accounts SET {', '.join(fields)} WHERE id = ?",
                    values,
                )
                if cursor.rowcount == 0:
                    return None
        except sqlite3.IntegrityError as error:
            raise ControlPlaneValidationError("account name already exists") from error
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM control_provider_accounts WHERE id = ?", (account_id,)
            )
            return cursor.rowcount > 0

    def replace_models(
        self,
        account_id: str,
        models: list[ModelDescriptor],
    ) -> list[dict[str, Any]]:
        if self.get_account(account_id) is None:
            raise ControlPlaneValidationError("account not found")
        now = _now()
        with self._connect() as connection:
            connection.execute("DELETE FROM control_models WHERE account_id = ?", (account_id,))
            for model in models:
                connection.execute(
                    "INSERT INTO control_models"
                    " (id, account_id, model_id, display_name, protocol, context_window,"
                    " supports_tools, supports_thinking, source, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        uuid.uuid4().hex,
                        account_id,
                        model.model_id,
                        model.display_name,
                        model.protocol,
                        model.context_window,
                        int(model.supports_tools),
                        int(model.supports_thinking),
                        model.source,
                        now,
                    ),
                )
        return self.list_models(account_id=account_id)

    def list_models(
        self,
        *,
        account_id: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if account_id is not None:
            clauses.append("m.account_id = ?")
            values.append(account_id)
        if query:
            clauses.append("(m.model_id LIKE ? OR m.display_name LIKE ?)")
            like = f"%{query}%"
            values.extend((like, like))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.*, a.provider, a.name AS account_name"
                " FROM control_models m"
                " JOIN control_provider_accounts a ON a.id = m.account_id"
                f"{where}"
                " ORDER BY a.name, m.display_name, m.model_id",
                values,
            ).fetchall()
        return [_model_row(row) for row in rows]

    def list_routable_models(self) -> list[dict[str, Any]]:
        """Internal gateway view including plaintext credentials for upstream calls."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.id AS account_id, a.provider, a.name AS account_name,"
                " a.backend, a.base_url, a.api_key, a.proxy_url,"
                " m.model_id, m.protocol"
                " FROM control_provider_accounts a"
                " JOIN control_models m ON m.account_id = a.id"
                " WHERE a.enabled = 1"
                " ORDER BY a.created_at, a.rowid, m.model_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def import_legacy_configs(self, configs: list[dict[str, Any]]) -> int:
        imported = 0
        for config in configs:
            if config.get("purpose") != "chat" or not config.get("backend"):
                continue
            try:
                account = self.create_account(
                    provider=config["backend"],
                    name=config["name"],
                    backend=config["backend"],
                    base_url=config.get("base_url"),
                    api_key=config["api_key"],
                    proxy_url=None,
                )
            except ControlPlaneValidationError:
                continue
            self.replace_models(
                account["id"],
                [
                    ModelDescriptor(
                        model_id=config["model_name"],
                        display_name=config["model_name"],
                        protocol=(
                            "anthropic-messages"
                            if config["backend"] == "anthropic"
                            else "openai-chat"
                        ),
                        context_window=None,
                        supports_tools=True,
                        supports_thinking=False,
                        source="legacy",
                    )
                ],
            )
            imported += 1
        return imported

    def list_legacy_configs(self) -> list[dict[str, Any]]:
        """Read chat rows from OpenTalos' legacy provider_configs table when present."""

        with self._connect() as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'provider_configs'"
            ).fetchone()
            if table is None:
                return []
            rows = connection.execute(
                "SELECT * FROM provider_configs WHERE purpose = 'chat'"
                " ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_profile(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ControlPlaneValidationError("profile name is required")
        now = _now()
        existing = self.get_profile_by_name(name)
        profile_id = existing["id"] if existing is not None else uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO control_profiles (id, name, payload, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET payload = excluded.payload,"
                " updated_at = excluded.updated_at",
                (profile_id, name, json.dumps(payload), now, now),
            )
        profile = self.get_profile_by_name(name)
        if profile is None:
            raise RuntimeError("saved profile could not be read")
        return profile

    def get_profile_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM control_profiles WHERE name = ?", (name,)
            ).fetchone()
        return _profile_row(row) if row else None

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM control_profiles ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [_profile_row(row) for row in rows]

    def delete_profile(self, profile_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM control_profiles WHERE id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    def create_routing_group(
        self,
        *,
        name: str,
        mode: str,
        members: list[dict[str, Any]],
        sticky: bool = True,
        intent_model: str | None = None,
    ) -> dict[str, Any]:
        self._validate_routing_group(name, mode, members)
        group_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO routing_groups"
                " (id, name, mode, sticky, intent_model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (group_id, name.strip(), mode, int(sticky), intent_model, now, now),
            )
            self._replace_group_members(connection, group_id, members)
        group = self.get_routing_group(name.strip())
        if group is None:
            raise RuntimeError("created routing group could not be read")
        return group

    def update_routing_group(
        self,
        group_id_or_name: str,
        *,
        mode: str | None = None,
        members: list[dict[str, Any]] | None = None,
        sticky: bool | None = None,
        intent_model: str | None = None,
    ) -> dict[str, Any] | None:
        group = self.get_routing_group(group_id_or_name)
        if group is None:
            return None
        next_mode = mode or group["mode"]
        next_members = members or group["members"]
        self._validate_routing_group(group["name"], next_mode, next_members)
        fields = ["mode = ?", "sticky = ?", "intent_model = ?", "updated_at = ?"]
        values: list[Any] = [
            next_mode,
            int(group["sticky"] if sticky is None else sticky),
            group["intent_model"] if intent_model is None else intent_model,
            _now(),
            group["id"],
        ]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE routing_groups SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            if members is not None:
                self._replace_group_members(connection, group["id"], members)
        return self.get_routing_group(group["id"])

    def get_routing_group(self, group_id_or_name: str) -> dict[str, Any] | None:
        clean = group_id_or_name.removeprefix("group/")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM routing_groups WHERE id = ? OR name = ?",
                (clean, clean),
            ).fetchone()
            if row is None:
                return None
            members = connection.execute(
                "SELECT target, position, weight FROM routing_group_members"
                " WHERE group_id = ? ORDER BY position",
                (row["id"],),
            ).fetchall()
        return {
            "id": row["id"],
            "name": row["name"],
            "mode": row["mode"],
            "sticky": bool(row["sticky"]),
            "intent_model": row["intent_model"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "members": [
                {
                    "target": member["target"],
                    "position": member["position"],
                    "weight": member["weight"],
                }
                for member in members
            ],
        }

    def list_routing_groups(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM routing_groups ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [
            group
            for row in rows
            if (group := self.get_routing_group(row["id"])) is not None
        ]

    def delete_routing_group(self, group_id_or_name: str) -> bool:
        group = self.get_routing_group(group_id_or_name)
        if group is None:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM routing_groups WHERE id = ?", (group["id"],)
            )
            return cursor.rowcount > 0

    def record_quota_snapshot(
        self,
        account_id: str,
        *,
        window_name: str,
        remaining: float,
        limit_value: float,
        unit: str,
        reset_at: str | None,
    ) -> dict[str, Any]:
        if self.get_account(account_id) is None:
            raise ControlPlaneValidationError("account not found")
        snapshot_id = uuid.uuid4().hex
        read_at = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO quota_snapshots"
                " (id, account_id, window_name, remaining, limit_value, unit, reset_at, read_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    account_id,
                    window_name,
                    remaining,
                    limit_value,
                    unit,
                    reset_at,
                    read_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM quota_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return dict(row)

    def latest_quota_snapshots(
        self,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = "WHERE q.account_id = ?" if account_id else ""
        values = [account_id] if account_id else []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT q.* FROM quota_snapshots q"
                " JOIN ("
                "   SELECT account_id, window_name, MAX(read_at) AS read_at"
                "   FROM quota_snapshots GROUP BY account_id, window_name"
                " ) latest ON latest.account_id = q.account_id"
                " AND latest.window_name = q.window_name"
                " AND latest.read_at = q.read_at"
                f" {where}"
                " ORDER BY q.account_id, q.window_name",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def next_routing_counter(self, key: str) -> int:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO routing_state (key, value) VALUES (?, 1)"
                " ON CONFLICT(key) DO UPDATE SET value = value + 1",
                (key,),
            )
            row = connection.execute(
                "SELECT value FROM routing_state WHERE key = ?", (key,)
            ).fetchone()
        return int(row["value"])

    def get_session_binding(self, session_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT target FROM routing_session_bindings WHERE session_key = ?",
                (session_key,),
            ).fetchone()
        return row["target"] if row else None

    def set_session_binding(self, session_key: str, target: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO routing_session_bindings (session_key, target, updated_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(session_key) DO UPDATE SET"
                " target = excluded.target, updated_at = excluded.updated_at",
                (session_key, target, _now()),
            )

    @staticmethod
    def _replace_group_members(
        connection: sqlite3.Connection,
        group_id: str,
        members: list[dict[str, Any]],
    ) -> None:
        connection.execute(
            "DELETE FROM routing_group_members WHERE group_id = ?", (group_id,)
        )
        for position, member in enumerate(members):
            connection.execute(
                "INSERT INTO routing_group_members"
                " (id, group_id, target, position, weight) VALUES (?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    group_id,
                    str(member["target"]).strip(),
                    position,
                    float(member.get("weight", 1)),
                ),
            )

    @staticmethod
    def _validate_routing_group(
        name: str,
        mode: str,
        members: list[dict[str, Any]],
    ) -> None:
        if not name.strip():
            raise ControlPlaneValidationError("routing group name is required")
        if mode not in _ROUTING_MODES:
            raise ControlPlaneValidationError(f"unsupported routing mode: {mode}")
        if not members:
            raise ControlPlaneValidationError("routing group needs at least one member")
        for member in members:
            if not str(member.get("target", "")).strip():
                raise ControlPlaneValidationError("routing member target is required")
            if float(member.get("weight", 1)) <= 0:
                raise ControlPlaneValidationError("routing member weight must be positive")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _account_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "provider": row["provider"],
        "name": row["name"],
        "backend": row["backend"],
        "base_url": row["base_url"],
        "api_key_masked": _mask_key(row["api_key"]),
        "proxy_url": row["proxy_url"],
        "enabled": bool(row["enabled"]),
        "model_count": int(row["model_count"]),
    }


def _model_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "provider": row["provider"],
        "account_name": row["account_name"],
        "model_id": row["model_id"],
        "display_name": row["display_name"],
        "protocol": row["protocol"],
        "context_window": row["context_window"],
        "supports_tools": bool(row["supports_tools"]),
        "supports_thinking": bool(row["supports_thinking"]),
        "source": row["source"],
        "fetched_at": row["fetched_at"],
    }


def _profile_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return "****"
    return "*" * (len(api_key) - 4) + api_key[-4:]


def _validated_url(
    value: str | None,
    field: str,
    *,
    allow_socks: bool = False,
) -> str | None:
    if value is None or value == "":
        return None
    parsed = urlparse(value)
    schemes = {"http", "https"}
    if allow_socks:
        schemes.update({"socks5", "socks5h"})
    if parsed.scheme not in schemes or not parsed.netloc:
        raise ControlPlaneValidationError(f"{field} must be an HTTP(S) URL")
    return value.rstrip("/")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
