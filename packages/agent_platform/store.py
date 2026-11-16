"""SQLite persistence for Agent installations, bindings, profiles, and config history."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_platform_installations (
  agent_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  installed INTEGER NOT NULL,
  version TEXT,
  install_path TEXT,
  install_source TEXT,
  config_path TEXT,
  platform TEXT NOT NULL,
  compatibility TEXT NOT NULL,
  compatibility_path TEXT NOT NULL,
  install_hint TEXT NOT NULL,
  discovered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_platform_bindings (
  agent_id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  shortlist TEXT NOT NULL DEFAULT '[]',
  routing_preference TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_platform_profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_platform_snapshots (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  path TEXT NOT NULL,
  existed INTEGER NOT NULL,
  content BLOB,
  mode INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(agent_id, path)
);
CREATE TABLE IF NOT EXISTS agent_platform_transactions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  action TEXT NOT NULL,
  path TEXT NOT NULL,
  before_sha256 TEXT,
  after_sha256 TEXT,
  status TEXT NOT NULL,
  message TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_platform_library_items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(kind, name)
);
CREATE TABLE IF NOT EXISTS agent_platform_library_bindings (
  item_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  path TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  PRIMARY KEY(item_id, agent_id),
  FOREIGN KEY(item_id) REFERENCES agent_platform_library_items(id) ON DELETE CASCADE
);
"""

_LIBRARY_KINDS = {
    "instructions",
    "mcp",
    "skills",
    "hooks",
    "env",
    "subagents",
    "commands",
    "plugins",
}


class AgentPlatformValidationError(ValueError):
    """Raised when an Agent platform value violates its persistence contract."""


class AgentPlatformStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def save_installations(self, installations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = _now()
        with self._connect() as connection:
            for item in installations:
                connection.execute(
                    "INSERT INTO agent_platform_installations"
                    " (agent_id, name, installed, version, install_path, install_source,"
                    " config_path, platform, compatibility, compatibility_path, install_hint,"
                    " discovered_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(agent_id) DO UPDATE SET"
                    " name = excluded.name, installed = excluded.installed,"
                    " version = excluded.version, install_path = excluded.install_path,"
                    " install_source = excluded.install_source,"
                    " config_path = excluded.config_path, platform = excluded.platform,"
                    " compatibility = excluded.compatibility,"
                    " compatibility_path = excluded.compatibility_path,"
                    " install_hint = excluded.install_hint,"
                    " discovered_at = excluded.discovered_at",
                    (
                        item["agent_id"],
                        item["name"],
                        int(bool(item.get("installed"))),
                        item.get("version"),
                        item.get("install_path"),
                        item.get("install_source"),
                        item.get("config_path"),
                        item.get("platform") or "unknown",
                        item.get("compatibility") or "manual",
                        item.get("compatibility_path") or "",
                        item.get("install_hint") or "",
                        now,
                    ),
                )
        return self.list_installations()

    def list_installations(self, *, installed_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE installed = 1" if installed_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_platform_installations"
                f"{where} ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [_installation_row(row) for row in rows]

    def get_installation(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_installations WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return _installation_row(row) if row else None

    def set_binding(
        self,
        agent_id: str,
        *,
        model: str,
        shortlist: list[str] | None = None,
        routing_preference: str | None = None,
    ) -> dict[str, Any]:
        clean_model = model.strip()
        clean_shortlist = [str(item).strip() for item in (shortlist or []) if str(item).strip()]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_platform_bindings"
                " (agent_id, model, shortlist, routing_preference, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(agent_id) DO UPDATE SET"
                " model = excluded.model, shortlist = excluded.shortlist,"
                " routing_preference = excluded.routing_preference,"
                " updated_at = excluded.updated_at",
                (
                    agent_id,
                    clean_model,
                    json.dumps(clean_shortlist, ensure_ascii=False),
                    routing_preference.strip() if routing_preference else None,
                    _now(),
                ),
            )
        binding = self.get_binding(agent_id)
        if binding is None:
            raise RuntimeError("saved Agent binding could not be read")
        return binding

    def get_binding(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_bindings WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return _binding_row(row) if row else None

    def list_bindings(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_platform_bindings ORDER BY agent_id"
            ).fetchall()
        return [_binding_row(row) for row in rows]

    def save_profile(self, name: str) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise AgentPlatformValidationError("profile name is required")
        bindings = {item["agent_id"]: item for item in self.list_bindings()}
        payload = {"bindings": bindings}
        existing = self.get_profile_by_name(clean_name)
        profile_id = existing["id"] if existing else uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_platform_profiles"
                " (id, name, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                " payload = excluded.payload, updated_at = excluded.updated_at",
                (
                    profile_id,
                    clean_name,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        profile = self.get_profile_by_name(clean_name)
        if profile is None:
            raise RuntimeError("saved Agent profile could not be read")
        return profile

    def get_profile(self, profile_id_or_name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_profiles WHERE id = ? OR name = ?",
                (profile_id_or_name, profile_id_or_name),
            ).fetchone()
        return _profile_row(row) if row else None

    def get_profile_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_profiles WHERE name = ?", (name,)
            ).fetchone()
        return _profile_row(row) if row else None

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_platform_profiles"
                " ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [_profile_row(row) for row in rows]

    def apply_profile(self, profile_id_or_name: str) -> dict[str, dict[str, Any]]:
        profile = self.get_profile(profile_id_or_name)
        if profile is None:
            raise AgentPlatformValidationError("profile not found")
        bindings = profile["payload"].get("bindings", {})
        now = _now()
        with self._connect() as connection:
            for agent_id, binding in bindings.items():
                connection.execute(
                    "INSERT INTO agent_platform_bindings"
                    " (agent_id, model, shortlist, routing_preference, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(agent_id) DO UPDATE SET"
                    " model = excluded.model, shortlist = excluded.shortlist,"
                    " routing_preference = excluded.routing_preference,"
                    " updated_at = excluded.updated_at",
                    (
                        agent_id,
                        str(binding.get("model") or "").strip(),
                        json.dumps(
                            [
                                str(item).strip()
                                for item in binding.get("shortlist") or []
                                if str(item).strip()
                            ],
                            ensure_ascii=False,
                        ),
                        binding.get("routing_preference"),
                        now,
                    ),
                )
        restored = {
            agent_id: binding
            for agent_id in bindings
            if (binding := self.get_binding(agent_id)) is not None
        }
        return restored

    def delete_profile(self, profile_id_or_name: str) -> bool:
        profile = self.get_profile(profile_id_or_name)
        if profile is None:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_platform_profiles WHERE id = ?", (profile["id"],)
            )
            return cursor.rowcount > 0

    def capture_snapshot(self, agent_id: str, path: Path) -> dict[str, Any]:
        clean_path = str(Path(path))
        existing = self.get_snapshot(agent_id, clean_path)
        if existing is not None:
            return existing
        existed = Path(path).is_file()
        content = Path(path).read_bytes() if existed else None
        mode = os.stat(path).st_mode if existed else None
        snapshot_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO agent_platform_snapshots"
                " (id, agent_id, path, existed, content, mode, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    agent_id,
                    clean_path,
                    int(existed),
                    content,
                    mode,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_platform_snapshots"
                " WHERE agent_id = ? AND path = ?",
                (agent_id, clean_path),
            ).fetchone()
        return _snapshot_row(row)

    def get_snapshot(self, agent_id: str, path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_snapshots"
                " WHERE agent_id = ? AND path = ?",
                (agent_id, str(Path(path))),
            ).fetchone()
        return _snapshot_row(row) if row else None

    def list_snapshots(self, agent_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_platform_snapshots"
                " WHERE agent_id = ? ORDER BY path",
                (agent_id,),
            ).fetchall()
        return [_snapshot_row(row) for row in rows]

    def add_transaction(
        self,
        agent_id: str,
        *,
        action: str,
        path: Path,
        before: bytes | None,
        after: bytes | None,
        status: str,
        message: str | None = None,
    ) -> dict[str, Any]:
        transaction_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_platform_transactions"
                " (id, agent_id, action, path, before_sha256, after_sha256,"
                " status, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    agent_id,
                    action,
                    str(Path(path)),
                    _sha256(before),
                    _sha256(after),
                    status,
                    message,
                    _now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_platform_transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()
        return dict(row)

    def list_transactions(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        where = " WHERE agent_id = ?" if agent_id else ""
        values = (agent_id,) if agent_id else ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_platform_transactions"
                f"{where} ORDER BY created_at DESC, rowid DESC",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_library_item(
        self,
        *,
        kind: str,
        name: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_kind = kind.strip()
        clean_name = name.strip()
        if clean_kind not in _LIBRARY_KINDS:
            raise AgentPlatformValidationError(f"unsupported library kind: {kind}")
        if not clean_name:
            raise AgentPlatformValidationError("library item name is required")
        item_id = uuid.uuid4().hex
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO agent_platform_library_items"
                    " (id, kind, name, content, metadata, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        clean_kind,
                        clean_name,
                        content,
                        json.dumps(metadata or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise AgentPlatformValidationError(
                f"library item {clean_kind}/{clean_name} already exists"
            ) from error
        item = self.get_library_item(item_id)
        if item is None:
            raise RuntimeError("created library item could not be read")
        return item

    def get_library_item(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_library_items WHERE id = ?", (item_id,)
            ).fetchone()
            bindings = connection.execute(
                "SELECT * FROM agent_platform_library_bindings WHERE item_id = ?"
                " ORDER BY agent_id",
                (item_id,),
            ).fetchall()
        if row is None:
            return None
        item = _library_row(row)
        item["bindings"] = [dict(binding) for binding in bindings]
        return item

    def list_library_items(self, kind: str | None = None) -> list[dict[str, Any]]:
        where = " WHERE kind = ?" if kind else ""
        values = (kind,) if kind else ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM agent_platform_library_items"
                f"{where} ORDER BY updated_at DESC, rowid DESC",
                values,
            ).fetchall()
        return [
            item
            for row in rows
            if (item := self.get_library_item(row["id"])) is not None
        ]

    def delete_library_item(self, item_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_platform_library_items WHERE id = ?", (item_id,)
            )
            return cursor.rowcount > 0

    def record_library_binding(self, item_id: str, agent_id: str, path: Path) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_platform_library_bindings"
                " (item_id, agent_id, path, applied_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(item_id, agent_id) DO UPDATE SET"
                " path = excluded.path, applied_at = excluded.applied_at",
                (item_id, agent_id, str(Path(path)), _now()),
            )

    def get_library_binding(self, item_id: str, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_library_bindings"
                " WHERE item_id = ? AND agent_id = ?",
                (item_id, agent_id),
            ).fetchone()
        return dict(row) if row else None

    def remove_library_binding(self, item_id: str, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_platform_library_bindings"
                " WHERE item_id = ? AND agent_id = ?",
                (item_id, agent_id),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "DELETE FROM agent_platform_library_bindings"
                    " WHERE item_id = ? AND agent_id = ?",
                    (item_id, agent_id),
                )
        return dict(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _installation_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["installed"] = bool(value["installed"])
    return value


def _binding_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["shortlist"] = json.loads(value.get("shortlist") or "[]")
    return value


def _profile_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["payload"] = json.loads(value["payload"])
    return value


def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["existed"] = bool(value["existed"])
    return value


def _library_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["metadata"] = json.loads(value.get("metadata") or "{}")
    return value


def _sha256(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
