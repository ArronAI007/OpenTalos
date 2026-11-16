"""Managed plugin installation with deterministic tree integrity checks."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .manifest import PluginManifest, PluginValidationError, validate_manifest


_SCHEMA = """
CREATE TABLE IF NOT EXISTS plugin_records (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  type TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  integrity_hash TEXT NOT NULL,
  manifest TEXT NOT NULL,
  source TEXT NOT NULL,
  installed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class PluginIntegrityError(RuntimeError):
    pass


class PluginStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "plugins.db"
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def discover(self, repository_root: Path) -> list[dict[str, Any]]:
        repository = Path(repository_root)
        found: list[dict[str, Any]] = []
        for manifest_path in sorted(repository.glob("*/plugin.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = validate_manifest(payload)
            except (OSError, json.JSONDecodeError, PluginValidationError):
                continue
            installed = self._record(manifest.id)
            found.append(
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "type": manifest.type,
                    "description": manifest.description,
                    "installed": installed is not None,
                    "path": str(manifest_path.parent),
                }
            )
        return found

    def install(self, source: Path, *, allow_update: bool = False) -> dict[str, Any]:
        source_dir = Path(source).resolve()
        manifest_path = source_dir / "plugin.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PluginValidationError(f"cannot read plugin manifest: {error}") from error
        manifest = validate_manifest(payload)
        destination = self.root / manifest.id
        existing = self._record(manifest.id)
        if existing is not None and not allow_update:
            raise PluginValidationError(f"plugin already installed: {manifest.id}")
        enabled = bool(existing["enabled"]) if existing is not None else True
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{manifest.id}.", dir=self.root)
        )
        try:
            staged = temporary / manifest.id
            shutil.copytree(source_dir, staged)
            integrity_hash = tree_hash(staged)
            if destination.exists():
                backup = temporary / "previous"
                destination.rename(backup)
                try:
                    staged.rename(destination)
                except Exception:
                    backup.rename(destination)
                    raise
            else:
                staged.rename(destination)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO plugin_records"
                " (id, name, version, type, enabled, integrity_hash, manifest,"
                " source, installed_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
                " version = excluded.version, type = excluded.type,"
                " enabled = excluded.enabled, integrity_hash = excluded.integrity_hash,"
                " manifest = excluded.manifest, source = excluded.source,"
                " updated_at = excluded.updated_at",
                (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    manifest.type,
                    int(enabled),
                    integrity_hash,
                    manifest.model_dump_json(),
                    str(source_dir),
                    now,
                    now,
                ),
            )
        return self.get_plugin(manifest.id)

    def list_plugins(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE enabled = 1" if enabled_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM plugin_records{where} ORDER BY name, id"
            ).fetchall()
        return [_row(row) for row in rows]

    def get_plugin(self, plugin_id: str) -> dict[str, Any]:
        row = self._record(plugin_id)
        if row is None:
            raise ValueError("plugin not found")
        return _row(row)

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE plugin_records SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _now(), plugin_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("plugin not found")
        return self.get_plugin(plugin_id)

    def verify(self, plugin_id: str) -> dict[str, Any]:
        record = self.get_plugin(plugin_id)
        directory = self.root / plugin_id
        if not directory.is_dir():
            raise PluginIntegrityError("plugin directory is missing")
        actual = tree_hash(directory)
        if actual != record["integrity_hash"]:
            raise PluginIntegrityError("plugin integrity check failed")
        return {"ok": True, "plugin_id": plugin_id, "hash": actual}

    def remove(self, plugin_id: str) -> bool:
        record = self._record(plugin_id)
        if record is None:
            return False
        directory = self.root / plugin_id
        if directory.exists():
            shutil.rmtree(directory)
        with self._connect() as connection:
            connection.execute("DELETE FROM plugin_records WHERE id = ?", (plugin_id,))
        return True

    def _record(self, plugin_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM plugin_records WHERE id = ?", (plugin_id,)
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["enabled"] = bool(value["enabled"])
    value["manifest"] = json.loads(value["manifest"])
    for field in ("runtime", "entrypoint", "capabilities", "ui", "description"):
        value[field] = value["manifest"].get(field)
    return value


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
