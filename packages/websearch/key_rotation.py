"""Persistent search API key rotation, refusal cooldowns, and quota visibility."""

from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from .client import WebSearchServiceError
from .models import ExtractResponse, SearchResponse


_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_api_keys (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  name TEXT NOT NULL,
  api_key TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT,
  cooldown_until TEXT,
  successes INTEGER NOT NULL DEFAULT 0,
  failures INTEGER NOT NULL DEFAULT 0,
  refusals INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider, name)
);
"""


class SearchKeysExhaustedError(WebSearchServiceError):
    """Raised when every configured search key is disabled or cooling down."""


class SearchKeyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def add_key(
        self,
        *,
        provider: str,
        name: str,
        api_key: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        clean_provider = provider.strip()
        clean_name = name.strip()
        clean_key = api_key.strip()
        if not clean_provider or not clean_name or not clean_key:
            raise ValueError("provider, name, and api_key are required")
        key_id = uuid.uuid4().hex
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO search_api_keys"
                    " (id, provider, name, api_key, priority, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        key_id,
                        clean_provider,
                        clean_name,
                        clean_key,
                        priority,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("search key name already exists") from error
        return {**_public_row(self._row(key_id)), "api_key_masked": _mask(clean_key)}

    def list_keys(self, provider: str | None = None) -> list[dict[str, Any]]:
        where = " WHERE provider = ?" if provider else ""
        values = (provider,) if provider else ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM search_api_keys"
                f"{where} ORDER BY priority DESC, created_at, rowid",
                values,
            ).fetchall()
        return [_public_row(row) for row in rows]

    def set_enabled(self, key_id: str, enabled: bool) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE search_api_keys SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), _now(), key_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("search key not found")
        return _public_row(self._row(key_id))

    def delete_key(self, key_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM search_api_keys WHERE id = ?", (key_id,)
            )
            return cursor.rowcount > 0

    def select_key(
        self,
        provider: str,
        *,
        exclude_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        excluded = exclude_ids or set()
        now = _now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM search_api_keys"
                " WHERE provider = ? AND enabled = 1"
                " AND (cooldown_until IS NULL OR cooldown_until <= ?)"
                " ORDER BY priority DESC,"
                " CASE WHEN last_used_at IS NULL THEN 0 ELSE 1 END,"
                " last_used_at, created_at, rowid",
                (provider, now),
            ).fetchall()
            available = [row for row in rows if row["id"] not in excluded]
            if not available:
                raise SearchKeysExhaustedError(
                    f"no available search key for provider {provider}"
                )
            selected = available[0]
            connection.execute(
                "UPDATE search_api_keys SET last_used_at = ? WHERE id = ?",
                (now, selected["id"]),
            )
        return dict(selected)

    def mark_success(self, key_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE search_api_keys SET successes = successes + 1,"
                " cooldown_until = NULL, last_error = NULL, updated_at = ? WHERE id = ?",
                (_now(), key_id),
            )

    def mark_refused(
        self,
        key_id: str,
        *,
        status_code: int,
        cooldown_seconds: int = 60,
    ) -> None:
        cooldown = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=max(1, cooldown_seconds))
        ).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE search_api_keys SET failures = failures + 1,"
                " refusals = refusals + 1, cooldown_until = ?,"
                " last_error = ?, updated_at = ? WHERE id = ?",
                (cooldown, f"HTTP {status_code}", _now(), key_id),
            )

    def mark_failure(self, key_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE search_api_keys SET failures = failures + 1,"
                " last_error = ?, updated_at = ? WHERE id = ?",
                (error[:500], _now(), key_id),
            )

    def usage(self, key_id: str) -> dict[str, Any]:
        row = self._row(key_id)
        return {
            "id": row["id"],
            "provider": row["provider"],
            "name": row["name"],
            "successes": int(row["successes"]),
            "failures": int(row["failures"]),
            "refusals": int(row["refusals"]),
            "cooldown_until": row["cooldown_until"],
            "last_error": row["last_error"],
        }

    def _row(self, key_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM search_api_keys WHERE id = ?", (key_id,)
            ).fetchone()
        if row is None:
            raise ValueError("search key not found")
        return row

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class RotatingTavilyClient:
    def __init__(
        self,
        store: SearchKeyStore,
        *,
        provider: str = "tavily",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._store = store
        self._provider = provider
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, query: str, *, max_results: int = 5) -> SearchResponse:
        data = await self._request("/search", {"query": query, "max_results": max_results})
        try:
            return SearchResponse.model_validate(data)
        except ValidationError as error:
            raise WebSearchServiceError(f"Unexpected search response shape: {error}") from error

    async def extract(self, urls: list[str]) -> ExtractResponse:
        data = await self._request("/extract", {"urls": urls})
        try:
            return ExtractResponse.model_validate(data)
        except ValidationError as error:
            raise WebSearchServiceError(f"Unexpected extract response shape: {error}") from error

    async def _request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        excluded: set[str] = set()
        last_error: Exception | None = None
        while True:
            try:
                key = self._store.select_key(self._provider, exclude_ids=excluded)
            except SearchKeysExhaustedError as error:
                if last_error is not None:
                    raise SearchKeysExhaustedError(
                        f"all search keys failed; last error: {last_error}"
                    ) from last_error
                raise error
            excluded.add(key["id"])
            try:
                response = await self._client.post(
                    f"https://api.tavily.com{path}",
                    json=body,
                    headers={"Authorization": f"Bearer {key['api_key']}"},
                )
            except httpx.HTTPError as error:
                self._store.mark_failure(key["id"], str(error))
                last_error = error
                continue
            if response.status_code in {401, 403, 429}:
                self._store.mark_refused(
                    key["id"],
                    status_code=response.status_code,
                    cooldown_seconds=300 if response.status_code == 429 else 60,
                )
                last_error = WebSearchServiceError(
                    f"search key refused with HTTP {response.status_code}"
                )
                continue
            if response.status_code >= 500:
                self._store.mark_failure(key["id"], response.text)
                last_error = WebSearchServiceError(response.text)
                continue
            if response.status_code >= 400:
                self._store.mark_failure(key["id"], response.text)
                raise WebSearchServiceError(response.text)
            self._store.mark_success(key["id"])
            return response.json()


def _public_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    secret = value.pop("api_key")
    value["api_key_masked"] = _mask(secret)
    value["enabled"] = bool(value["enabled"])
    return value


def _mask(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}…{secret[-4:]}"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
