"""Restore managed agent state before optionally deleting OpenTalos user data."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


SnapshotRestorer = Callable[[], list[dict[str, Any]]]


class SafeUninstaller:
    def __init__(
        self,
        *,
        data_dir: Path,
        app_dir: Path,
        resource_root: Path,
        snapshot_restorer: SnapshotRestorer | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.app_dir = Path(app_dir)
        self.resource_root = Path(resource_root)
        self.snapshot_restorer = snapshot_restorer or (
            lambda: restore_agent_snapshots(self.data_dir / "chat.db")
        )

    def run(self, *, keep_data: bool) -> dict[str, Any]:
        restored = self.snapshot_restorer()
        for snapshot in restored:
            _restore_snapshot(snapshot)

        data_removed = False
        if not keep_data and self.data_dir.exists():
            shutil.rmtree(self.data_dir)
            data_removed = True
        return {
            "ok": True,
            "restored_agents": len(restored),
            "data_removed": data_removed,
            "data_dir": str(self.data_dir),
            "app_dir": str(self.app_dir),
        }


def restore_agent_snapshots(database: Path) -> list[dict[str, Any]]:
    if not Path(database).is_file():
        return []
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table'"
            " AND name='agent_platform_snapshots'"
        ).fetchone()
        if table is None:
            return []
        rows = connection.execute(
            "SELECT path, existed, content, mode FROM agent_platform_snapshots"
            " ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def _restore_snapshot(snapshot: dict[str, Any]) -> None:
    target = Path(snapshot["path"])
    if not snapshot.get("existed"):
        target.unlink(missing_ok=True)
        return
    content = snapshot.get("content")
    if not isinstance(content, bytes):
        raise RuntimeError(f"invalid snapshot content for {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        mode = snapshot.get("mode")
        if mode:
            os.chmod(temporary, int(mode))
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
