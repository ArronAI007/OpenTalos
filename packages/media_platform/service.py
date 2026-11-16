"""Provider-neutral image/video generation with persisted media references."""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class GeneratedMedia:
    data: bytes
    mime_type: str
    extension: str


class ImageBackend(Protocol):
    async def generate(self, prompt: str, *, size: str) -> GeneratedMedia: ...


class VideoBackend(Protocol):
    async def start(self, prompt: str) -> str: ...

    async def status(self, job_id: str) -> dict[str, Any]: ...

    async def cancel(self, job_id: str) -> dict[str, Any]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  prompt TEXT NOT NULL,
  mime_type TEXT,
  path TEXT,
  provider_job_id TEXT,
  progress REAL NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class MediaStore:
    def __init__(self, database: Path, media_root: Path) -> None:
        self.database = Path(database)
        self.media_root = Path(media_root)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def create_job(
        self,
        *,
        kind: str,
        prompt: str,
        status: str = "running",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO media_jobs"
                " (id, kind, status, prompt, metadata, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    kind,
                    status,
                    prompt,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def complete_image(
        self,
        job_id: str,
        *,
        media: GeneratedMedia,
    ) -> dict[str, Any]:
        extension = media.extension.lstrip(".") or _extension(media.mime_type)
        target = self.media_root / f"{job_id}.{extension}"
        _atomic_write(target, media.data)
        with self._connect() as connection:
            connection.execute(
                "UPDATE media_jobs SET status = 'completed', mime_type = ?,"
                " path = ?, progress = 1, updated_at = ? WHERE id = ?",
                (media.mime_type, str(target), _now(), job_id),
            )
        return self.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        provider_job_id: str | None = None,
        progress: float | None = None,
        path: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields = ["updated_at = ?"]
        values: list[Any] = [_now()]
        for column, value in (
            ("status", status),
            ("provider_job_id", provider_job_id),
            ("progress", max(0.0, min(1.0, progress)) if progress is not None else None),
            ("path", path),
            ("mime_type", mime_type),
            (
                "metadata",
                json.dumps(metadata, ensure_ascii=False)
                if metadata is not None
                else None,
            ),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        values.append(job_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE media_jobs SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError("media job not found")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM media_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise ValueError("media job not found")
        value = dict(row)
        value["job_id"] = value["id"]
        value["metadata"] = json.loads(value["metadata"])
        return value

    def list_jobs(self, kind: str | None = None) -> list[dict[str, Any]]:
        where = " WHERE kind = ?" if kind else ""
        values = (kind,) if kind else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM media_jobs{where} ORDER BY created_at DESC, rowid DESC",
                values,
            ).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection


class MediaGenerationService:
    def __init__(
        self,
        store: MediaStore,
        *,
        image_backend: ImageBackend | None = None,
        video_backend: VideoBackend | None = None,
    ) -> None:
        self.store = store
        self.image_backend = image_backend
        self.video_backend = video_backend

    async def generate_image(self, prompt: str, *, size: str = "1024x1024") -> dict[str, Any]:
        if self.image_backend is None:
            raise RuntimeError("image generation backend is not configured")
        if not prompt.strip():
            raise ValueError("image prompt is required")
        job = self.store.create_job(kind="image", prompt=prompt, metadata={"size": size})
        try:
            media = await self.image_backend.generate(prompt, size=size)
            return self.store.complete_image(job["id"], media=media)
        except Exception as error:
            self.store.update_job(
                job["id"],
                status="failed",
                metadata={"error": str(error), "size": size},
            )
            raise

    async def start_video(self, prompt: str) -> dict[str, Any]:
        if self.video_backend is None:
            raise RuntimeError("video generation backend is not configured")
        if not prompt.strip():
            raise ValueError("video prompt is required")
        job = self.store.create_job(kind="video", prompt=prompt)
        try:
            provider_job_id = await self.video_backend.start(prompt)
        except Exception as error:
            self.store.update_job(
                job["id"],
                status="failed",
                metadata={"error": str(error)},
            )
            raise
        return self.store.update_job(
            job["id"],
            provider_job_id=provider_job_id,
            progress=0.01,
        )

    async def video_status(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["kind"] != "video" or not job.get("provider_job_id"):
            raise ValueError("video job not found")
        if self.video_backend is None:
            raise RuntimeError("video generation backend is not configured")
        remote = await self.video_backend.status(job["provider_job_id"])
        return self.store.update_job(
            job_id,
            status=str(remote.get("status") or job["status"]),
            progress=float(remote.get("progress") or 0),
            path=remote.get("path"),
            mime_type=remote.get("mime_type"),
            metadata={**job["metadata"], "remote": remote},
        )

    async def cancel_video(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["kind"] != "video" or not job.get("provider_job_id"):
            raise ValueError("video job not found")
        if self.video_backend is None:
            raise RuntimeError("video generation backend is not configured")
        remote = await self.video_backend.cancel(job["provider_job_id"])
        return self.store.update_job(
            job_id,
            status=str(remote.get("status") or "cancelled"),
            metadata={**job["metadata"], "remote": remote},
        )


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _extension(mime_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "video/mp4": "mp4",
    }.get(mime_type, "bin")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
