"""Transactional release metadata and SQLite backup before schema migration."""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable


class DowngradeBlockedError(RuntimeError):
    """Raised when an older application would open a newer data schema."""


class ReleaseMetadataStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.data_dir / "release.json"
        self.backup_dir = self.data_dir / "backups"

    def prepare(
        self,
        *,
        app_version: str,
        schema_version: int,
        platform_name: str,
        migrate: Callable[[sqlite3.Connection, int, int], None] | None = None,
    ) -> dict[str, Any]:
        previous = self.read()
        previous_schema = int(previous.get("schema_version", 0)) if previous else 0
        if previous_schema > schema_version:
            raise DowngradeBlockedError(
                f"data uses newer data schema {previous_schema}; this app supports {schema_version}"
            )

        backup_path: str | None = None
        database = self.data_dir / "chat.db"
        needs_migration = previous is not None and previous_schema < schema_version
        if needs_migration and database.is_file():
            backup_path = str(self._backup_database(database, previous_schema, schema_version))
            if migrate is not None:
                with sqlite3.connect(database) as connection:
                    migrate(connection, previous_schema, schema_version)

        metadata = {
            "app_version": app_version,
            "schema_version": schema_version,
            "platform": platform_name,
            "updated_at": _now(),
        }
        if backup_path:
            metadata["backup_path"] = backup_path
        elif previous and previous.get("backup_path"):
            metadata["backup_path"] = previous["backup_path"]
        _atomic_json(self.metadata_path, metadata)
        return metadata

    def read(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"cannot read release metadata: {error}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("release metadata must be a JSON object")
        return payload

    def _backup_database(
        self,
        source: Path,
        from_schema: int,
        to_schema: int,
    ) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.backup_dir / f"chat-schema-{from_schema}-to-{to_schema}-{stamp}.db"
        with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
            source_db.backup(target_db)
        return target


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
