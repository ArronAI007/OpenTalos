"""SQLite persistence for privacy rules, placeholder mappings, and audit records."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS privacy_rules (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  pattern TEXT NOT NULL,
  action TEXT NOT NULL,
  category TEXT NOT NULL,
  builtin INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_placeholders (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  token TEXT NOT NULL,
  secret_value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  UNIQUE(scope, rule_id, secret_value),
  UNIQUE(scope, token)
);
CREATE TABLE IF NOT EXISTS privacy_audit (
  id TEXT PRIMARY KEY,
  request_id TEXT,
  scope TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  category TEXT NOT NULL,
  action TEXT NOT NULL,
  placeholder TEXT,
  restored INTEGER NOT NULL DEFAULT 0,
  details TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_settings (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  enabled INTEGER NOT NULL DEFAULT 0,
  fail_closed INTEGER NOT NULL DEFAULT 1,
  placeholder_ttl_seconds INTEGER NOT NULL DEFAULT 86400,
  updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class PrivacyRule:
    id: str
    title: str
    pattern: str
    action: str
    category: str = "custom"
    builtin: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.action not in {"mask", "warn", "block"}:
            raise ValueError("privacy action must be mask, warn, or block")
        try:
            re.compile(self.pattern)
        except re.error as error:
            raise ValueError(f"invalid privacy regex: {error}") from error


_BUILTIN_RULES = (
    PrivacyRule(
        id="email",
        title="Email address",
        pattern=r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        action="mask",
        category="pii",
        builtin=True,
    ),
    PrivacyRule(
        id="phone",
        title="Phone number",
        pattern=r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)",
        action="mask",
        category="pii",
        builtin=True,
    ),
    PrivacyRule(
        id="openai_key",
        title="OpenAI style secret key",
        pattern=r"\bsk-[A-Za-z0-9_-]{20,}\b",
        action="mask",
        category="credential",
        builtin=True,
    ),
    PrivacyRule(
        id="github_token",
        title="GitHub token",
        pattern=r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
        action="mask",
        category="credential",
        builtin=True,
    ),
    PrivacyRule(
        id="aws_access_key",
        title="AWS access key",
        pattern=r"\bAKIA[0-9A-Z]{16}\b",
        action="mask",
        category="credential",
        builtin=True,
    ),
    PrivacyRule(
        id="bearer_token",
        title="Bearer token",
        pattern=r"(?i)\bBearer\s+[A-Za-z0-9._~-]{20,}",
        action="mask",
        category="credential",
        builtin=True,
    ),
    PrivacyRule(
        id="private_key",
        title="Private key block",
        pattern=r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        action="mask",
        category="credential",
        builtin=True,
    ),
)


class PrivacyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO privacy_settings"
                " (id, enabled, fail_closed, placeholder_ttl_seconds, updated_at)"
                " VALUES (1, 0, 1, 86400, ?)",
                (_now(),),
            )

    def list_rules(self) -> list[PrivacyRule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM privacy_rules ORDER BY created_at, rowid"
            ).fetchall()
        custom = [
            PrivacyRule(
                id=row["id"],
                title=row["title"],
                pattern=row["pattern"],
                action=row["action"],
                category=row["category"],
                builtin=bool(row["builtin"]),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]
        return [*[rule for rule in _BUILTIN_RULES if rule.enabled], *[rule for rule in custom if rule.enabled]]

    def save_rule(self, rule: PrivacyRule) -> PrivacyRule:
        if not rule.id.strip() or not rule.title.strip():
            raise ValueError("privacy rule id and title are required")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO privacy_rules"
                " (id, title, pattern, action, category, builtin, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET title = excluded.title,"
                " pattern = excluded.pattern, action = excluded.action,"
                " category = excluded.category, enabled = excluded.enabled,"
                " updated_at = excluded.updated_at",
                (
                    rule.id,
                    rule.title,
                    rule.pattern,
                    rule.action,
                    rule.category,
                    0,
                    int(rule.enabled),
                    now,
                    now,
                ),
            )
        return PrivacyRule(**{**rule.__dict__, "builtin": False})

    def delete_rule(self, rule_id: str) -> bool:
        if any(rule.id == rule_id for rule in _BUILTIN_RULES):
            raise ValueError("built-in privacy rules cannot be deleted")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM privacy_rules WHERE id = ?", (rule_id,)
            )
            return cursor.rowcount > 0

    def get_or_create_placeholder(
        self,
        *,
        scope: str,
        rule_id: str,
        value: str,
        ttl_seconds: int,
    ) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT token, expires_at FROM privacy_placeholders"
                " WHERE scope = ? AND rule_id = ? AND secret_value = ?",
                (scope, rule_id, value),
            ).fetchone()
            if row is not None and _parse_time(row["expires_at"]) > now:
                return row["token"]
            if row is not None:
                connection.execute(
                    "DELETE FROM privacy_placeholders WHERE scope = ? AND rule_id = ?"
                    " AND secret_value = ?",
                    (scope, rule_id, value),
                )
            digest = hashlib.sha256(
                f"{scope}\0{rule_id}\0{value}".encode("utf-8")
            ).hexdigest()[:16].upper()
            token = f"[[OPENTALOS_{_token_label(rule_id)}_{digest}]]"
            connection.execute(
                "INSERT INTO privacy_placeholders"
                " (id, scope, rule_id, token, secret_value, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    scope,
                    rule_id,
                    token,
                    value,
                    now.isoformat(),
                    (now + datetime.timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )
        return token

    def mappings(self, scope: str) -> dict[str, str]:
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT token, secret_value, expires_at FROM privacy_placeholders"
                " WHERE scope = ?",
                (scope,),
            ).fetchall()
            expired = [
                row["token"]
                for row in rows
                if _parse_time(row["expires_at"]) <= now
            ]
            if expired:
                connection.executemany(
                    "DELETE FROM privacy_placeholders WHERE scope = ? AND token = ?",
                    [(scope, token) for token in expired],
                )
        return {
            row["token"]: row["secret_value"]
            for row in rows
            if row["token"] not in expired
        }

    def record_audit(
        self,
        *,
        request_id: str | None,
        scope: str,
        rule_id: str,
        category: str,
        action: str,
        placeholder: str | None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO privacy_audit"
                " (id, request_id, scope, rule_id, category, action, placeholder,"
                " details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_id,
                    request_id,
                    scope,
                    rule_id,
                    category,
                    action,
                    placeholder,
                    json.dumps(details or {}, ensure_ascii=False),
                    _now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM privacy_audit WHERE id = ?", (audit_id,)
            ).fetchone()
        value = dict(row)
        value["restored"] = bool(value["restored"])
        value["details"] = json.loads(value["details"])
        return value

    def mark_restored(self, scope: str, tokens: list[str]) -> None:
        if not tokens:
            return
        with self._connect() as connection:
            connection.executemany(
                "UPDATE privacy_audit SET restored = 1"
                " WHERE scope = ? AND placeholder = ?",
                [(scope, token) for token in tokens],
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM privacy_audit ORDER BY created_at DESC, rowid DESC"
                " LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["restored"] = bool(value["restored"])
            value["details"] = json.loads(value["details"])
            values.append(value)
        return values

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM privacy_settings WHERE id = 1"
            ).fetchone()
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["fail_closed"] = bool(value["fail_closed"])
        return value

    def update_settings(
        self,
        *,
        enabled: bool | None = None,
        fail_closed: bool | None = None,
        placeholder_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        current = self.get_settings()
        ttl = (
            current["placeholder_ttl_seconds"]
            if placeholder_ttl_seconds is None
            else placeholder_ttl_seconds
        )
        if ttl < 1:
            raise ValueError("placeholder TTL must be positive")
        with self._connect() as connection:
            connection.execute(
                "UPDATE privacy_settings SET enabled = ?, fail_closed = ?,"
                " placeholder_ttl_seconds = ?, updated_at = ? WHERE id = 1",
                (
                    int(current["enabled"] if enabled is None else enabled),
                    int(current["fail_closed"] if fail_closed is None else fail_closed),
                    ttl,
                    _now(),
                ),
            )
        return self.get_settings()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _token_label(rule_id: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", rule_id.upper()).strip("_")


def _parse_time(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
