"""Persistent named Gateway keys with atomic budgets and scoped access."""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_keys (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active',
  scopes TEXT NOT NULL,
  allowed_models TEXT NOT NULL DEFAULT '[]',
  allowed_accounts TEXT NOT NULL DEFAULT '[]',
  allowed_groups TEXT NOT NULL DEFAULT '[]',
  allowed_mcp_servers TEXT NOT NULL DEFAULT '[]',
  read_only INTEGER NOT NULL DEFAULT 0,
  daily_requests INTEGER,
  weekly_requests INTEGER,
  monthly_requests INTEGER,
  token_limit INTEGER,
  cost_limit_micros INTEGER,
  cache_limit INTEGER,
  concurrency_limit INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS gateway_key_usage (
  key_id TEXT NOT NULL,
  period_type TEXT NOT NULL,
  period_start TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_micros INTEGER NOT NULL DEFAULT 0,
  cache_reads INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(key_id, period_type, period_start),
  FOREIGN KEY(key_id) REFERENCES gateway_keys(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS gateway_active_reservations (
  id TEXT PRIMARY KEY,
  key_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(key_id) REFERENCES gateway_keys(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS gateway_key_audit (
  id TEXT PRIMARY KEY,
  key_id TEXT,
  action TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gateway_sharing_config (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  enabled INTEGER NOT NULL,
  bind_host TEXT NOT NULL,
  port INTEGER NOT NULL,
  exposure_warning_acknowledged INTEGER NOT NULL,
  tls_mode TEXT NOT NULL,
  cert_file TEXT,
  key_file TEXT,
  ca_file TEXT,
  require_client_cert INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class GatewayAccessDeniedError(PermissionError):
    status_code = 403


class GatewayBudgetError(GatewayAccessDeniedError):
    status_code = 429


class GatewayAccessStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO gateway_sharing_config"
                " (id, enabled, bind_host, port, exposure_warning_acknowledged,"
                " tls_mode, cert_file, key_file, ca_file, require_client_cert, updated_at)"
                " VALUES (1, 0, '127.0.0.1', 3421, 0, 'off', NULL, NULL, NULL, 0, ?)",
                (_now(),),
            )
            connection.execute(
                "UPDATE gateway_sharing_config SET port = 3421"
                " WHERE id = 1 AND enabled = 0 AND port = 3425"
            )

    def create_key(
        self,
        *,
        name: str,
        scopes: list[str],
        allowed_models: list[str] | None = None,
        allowed_accounts: list[str] | None = None,
        allowed_groups: list[str] | None = None,
        allowed_mcp_servers: list[str] | None = None,
        read_only: bool = False,
        admin: bool = False,
        daily_requests: int | None = None,
        weekly_requests: int | None = None,
        monthly_requests: int | None = None,
        token_limit: int | None = None,
        cost_limit_micros: int | None = None,
        cache_limit: int | None = None,
        concurrency_limit: int | None = None,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        clean_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
        if not clean_name:
            raise ValueError("Gateway key name is required")
        if not clean_scopes:
            raise ValueError("Gateway key needs at least one scope")
        if admin and "admin" not in clean_scopes:
            clean_scopes.append("admin")
        for label, value in (
            ("daily_requests", daily_requests),
            ("weekly_requests", weekly_requests),
            ("monthly_requests", monthly_requests),
            ("token_limit", token_limit),
            ("cost_limit_micros", cost_limit_micros),
            ("cache_limit", cache_limit),
            ("concurrency_limit", concurrency_limit),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must be non-negative")
        key_id = uuid.uuid4().hex
        plaintext = _new_key()
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO gateway_keys"
                    " (id, name, key_prefix, key_hash, scopes, allowed_models,"
                    " allowed_accounts, allowed_groups, allowed_mcp_servers, read_only,"
                    " daily_requests, weekly_requests, monthly_requests, token_limit,"
                    " cost_limit_micros, cache_limit, concurrency_limit,"
                    " created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key_id,
                        clean_name,
                        plaintext[:12],
                        _hash_key(plaintext),
                        json.dumps(clean_scopes),
                        json.dumps(allowed_models or []),
                        json.dumps(allowed_accounts or []),
                        json.dumps(allowed_groups or []),
                        json.dumps(allowed_mcp_servers or []),
                        int(read_only),
                        daily_requests,
                        weekly_requests,
                        monthly_requests,
                        token_limit,
                        cost_limit_micros,
                        cache_limit,
                        concurrency_limit,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Gateway key name already exists: {clean_name}") from error
        self._audit(key_id, "create", {"name": clean_name, "scopes": clean_scopes})
        return {**self._get_key(key_id), "key": plaintext}

    def list_keys(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM gateway_keys ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [_key_row(row) for row in rows]

    def active_key_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM gateway_keys WHERE status = 'active'"
                ).fetchone()[0]
            )

    def local_principal(self) -> dict[str, Any]:
        return {
            "id": "local",
            "name": "Local administrator",
            "key_prefix": "local",
            "status": "active",
            "scopes": ["admin", "chat.read", "models.read", "mcp.read"],
            "allowed_models": [],
            "allowed_accounts": [],
            "allowed_groups": [],
            "allowed_mcp_servers": [],
            "read_only": False,
            "local": True,
        }

    def rotate_key(self, key_id: str) -> dict[str, Any]:
        plaintext = _new_key()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_keys SET key_prefix = ?, key_hash = ?,"
                " status = 'active', revoked_at = NULL, updated_at = ?"
                " WHERE id = ?",
                (plaintext[:12], _hash_key(plaintext), _now(), key_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("Gateway key not found")
        self._audit(key_id, "rotate", {})
        return {**self._get_key(key_id), "key": plaintext}

    def update_key(
        self,
        key_id: str,
        *,
        name: str | None = None,
        scopes: list[str] | None = None,
        allowed_models: list[str] | None = None,
        allowed_accounts: list[str] | None = None,
        allowed_groups: list[str] | None = None,
    ) -> dict[str, Any]:
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("name", name.strip() if name is not None else None),
            ("scopes", json.dumps(sorted(set(scopes))) if scopes is not None else None),
            (
                "allowed_models",
                json.dumps(allowed_models) if allowed_models is not None else None,
            ),
            (
                "allowed_accounts",
                json.dumps(allowed_accounts) if allowed_accounts is not None else None,
            ),
            (
                "allowed_groups",
                json.dumps(allowed_groups) if allowed_groups is not None else None,
            ),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        if not fields:
            return self._get_key(key_id)
        fields.append("updated_at = ?")
        values.extend((_now(), key_id))
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE gateway_keys SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError("Gateway key not found")
        self._audit(key_id, "update", {"fields": fields[:-1]})
        return self._get_key(key_id)

    def revoke_key(self, key_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_keys SET status = 'revoked', revoked_at = ?,"
                " updated_at = ? WHERE id = ? AND status != 'revoked'",
                (_now(), _now(), key_id),
            )
            if cursor.rowcount == 0:
                return False
            connection.execute(
                "DELETE FROM gateway_active_reservations WHERE key_id = ?",
                (key_id,),
            )
        self._audit(key_id, "revoke", {})
        return True

    def authenticate(self, authorization: str | None) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise GatewayAccessDeniedError("Gateway key is required")
        plaintext = authorization.removeprefix("Bearer ").strip()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_keys WHERE key_hash = ? AND status = 'active'",
                (_hash_key(plaintext),),
            ).fetchone()
            if row is None:
                self._audit(None, "auth_denied", {"prefix": plaintext[:8]})
                raise GatewayAccessDeniedError("invalid or revoked Gateway key")
            connection.execute(
                "UPDATE gateway_keys SET last_used_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
        return _key_row(row)

    def require(self, principal: dict[str, Any], *, scope: str) -> None:
        scopes = set(principal.get("scopes") or [])
        if scope not in scopes and "admin" not in scopes:
            raise GatewayAccessDeniedError(
                f"Gateway key lacks required scope: {scope}"
            )
        if principal.get("read_only") and scope.startswith("admin"):
            raise GatewayAccessDeniedError("read-only Gateway key cannot use admin scope")

    def allows_account(
        self,
        principal: dict[str, Any],
        *,
        account_id: str,
        account_name: str | None = None,
        provider: str | None = None,
    ) -> bool:
        patterns = principal.get("allowed_accounts") or []
        if not patterns:
            return True
        values = {
            account_id,
            account_name or "",
            f"{provider}/{account_name}" if provider and account_name else "",
        }
        return any(
            fnmatch.fnmatch(value, pattern)
            for pattern in patterns
            for value in values
            if value
        )

    def reserve(
        self,
        principal: dict[str, Any],
        *,
        model: str,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        self.require(principal, scope="chat.read")
        if principal.get("local"):
            return {
                "id": uuid.uuid4().hex,
                "key_id": "local",
                "periods": {},
                "settled": False,
                "local": True,
            }
        _check_model_access(principal, model)
        if account_id and principal.get("allowed_accounts"):
            if not self.allows_account(
                principal,
                account_id=account_id,
            ):
                raise GatewayAccessDeniedError(
                    f"Gateway key cannot access account {account_id}"
                )
        key_id = principal["id"]
        reservation_id = uuid.uuid4().hex
        periods = _periods()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM gateway_keys WHERE id = ? AND status = 'active'",
                (key_id,),
            ).fetchone()
            if row is None:
                raise GatewayAccessDeniedError("Gateway key is revoked")
            if row["concurrency_limit"] is not None:
                active = connection.execute(
                    "SELECT COUNT(*) FROM gateway_active_reservations WHERE key_id = ?",
                    (key_id,),
                ).fetchone()[0]
                if active >= row["concurrency_limit"]:
                    raise GatewayBudgetError("Gateway key concurrency limit exceeded")
            usage = {
                period_type: _get_usage(connection, key_id, period_type, period_start)
                for period_type, period_start in periods.items()
            }
            for period_type, limit in (
                ("daily", row["daily_requests"]),
                ("weekly", row["weekly_requests"]),
                ("monthly", row["monthly_requests"]),
            ):
                if limit is not None and usage[period_type]["requests"] >= limit:
                    raise GatewayBudgetError(
                        f"Gateway key {period_type} request budget exceeded"
                    )
            total_tokens = sum(
                item["input_tokens"] + item["output_tokens"]
                for item in usage.values()
            )
            if row["token_limit"] is not None and total_tokens >= row["token_limit"]:
                raise GatewayBudgetError("Gateway key token budget exceeded")
            total_cost = sum(item["cost_micros"] for item in usage.values())
            if row["cost_limit_micros"] is not None and total_cost >= row["cost_limit_micros"]:
                raise GatewayBudgetError("Gateway key cost budget exceeded")
            total_cache = sum(item["cache_reads"] for item in usage.values())
            if row["cache_limit"] is not None and total_cache >= row["cache_limit"]:
                raise GatewayBudgetError("Gateway key cache budget exceeded")
            for period_type, period_start in periods.items():
                connection.execute(
                    "INSERT INTO gateway_key_usage"
                    " (key_id, period_type, period_start, requests)"
                    " VALUES (?, ?, ?, 1)"
                    " ON CONFLICT(key_id, period_type, period_start)"
                    " DO UPDATE SET requests = requests + 1",
                    (key_id, period_type, period_start),
                )
            connection.execute(
                "INSERT INTO gateway_active_reservations (id, key_id, created_at)"
                " VALUES (?, ?, ?)",
                (reservation_id, key_id, _now()),
            )
        return {
            "id": reservation_id,
            "key_id": key_id,
            "periods": periods,
            "settled": False,
        }

    def settle(
        self,
        reservation: dict[str, Any],
        *,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_micros: int = 0,
        cache_reads: int = 0,
    ) -> None:
        if reservation.get("settled"):
            return
        if reservation.get("local"):
            reservation["settled"] = True
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT 1 FROM gateway_active_reservations WHERE id = ?",
                (reservation["id"],),
            ).fetchone()
            if row is None:
                return
            for period_type, period_start in reservation["periods"].items():
                connection.execute(
                    "UPDATE gateway_key_usage SET input_tokens = input_tokens + ?,"
                    " output_tokens = output_tokens + ?, cost_micros = cost_micros + ?,"
                    " cache_reads = cache_reads + ?"
                    " WHERE key_id = ? AND period_type = ? AND period_start = ?",
                    (
                        max(0, input_tokens),
                        max(0, output_tokens),
                        max(0, cost_micros),
                        max(0, cache_reads),
                        reservation["key_id"],
                        period_type,
                        period_start,
                    ),
                )
            connection.execute(
                "DELETE FROM gateway_active_reservations WHERE id = ?",
                (reservation["id"],),
            )
        reservation["settled"] = True

    def usage(self, key_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM gateway_key_usage WHERE key_id = ?"
                " ORDER BY period_type, period_start DESC",
                (key_id,),
            ).fetchall()
        values = [dict(row) for row in rows]
        return {
            "key_id": key_id,
            "periods": values,
            "requests": sum(item["requests"] for item in values),
            "input_tokens": sum(item["input_tokens"] for item in values),
            "output_tokens": sum(item["output_tokens"] for item in values),
            "cost_micros": sum(item["cost_micros"] for item in values),
            "cache_reads": sum(item["cache_reads"] for item in values),
        }

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM gateway_key_audit ORDER BY created_at DESC, rowid DESC"
                " LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["details"] = json.loads(value["details"])
            values.append(value)
        return values

    def get_sharing(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_sharing_config WHERE id = 1"
            ).fetchone()
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["exposure_warning_acknowledged"] = bool(
            value["exposure_warning_acknowledged"]
        )
        value["require_client_cert"] = bool(value["require_client_cert"])
        value["warning"] = _network_warning(value["bind_host"])
        return value

    def update_sharing(
        self,
        *,
        enabled: bool | None = None,
        bind_host: str | None = None,
        port: int | None = None,
        exposure_warning_acknowledged: bool | None = None,
        tls_mode: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        ca_file: str | None = None,
        require_client_cert: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get_sharing()
        next_host = (bind_host or current["bind_host"]).strip()
        next_enabled = current["enabled"] if enabled is None else enabled
        acknowledged = (
            current["exposure_warning_acknowledged"]
            if exposure_warning_acknowledged is None
            else exposure_warning_acknowledged
        )
        if next_enabled and not _is_loopback(next_host) and not acknowledged:
            raise ValueError(
                "network exposure warning must be acknowledged before binding a non-loopback interface"
            )
        next_tls = tls_mode or current["tls_mode"]
        if next_tls not in {"off", "custom", "mtls"}:
            raise ValueError("tls_mode must be off, custom, or mtls")
        next_port = port if port is not None else current["port"]
        if not 1 <= next_port <= 65535:
            raise ValueError("sharing port must be between 1 and 65535")
        next_cert = cert_file if cert_file is not None else current["cert_file"]
        next_key = key_file if key_file is not None else current["key_file"]
        next_ca = ca_file if ca_file is not None else current["ca_file"]
        if next_tls in {"custom", "mtls"} and (not next_cert or not next_key):
            raise ValueError("custom TLS requires cert_file and key_file")
        if next_tls == "mtls" and not next_ca:
            raise ValueError("mTLS requires ca_file")
        with self._connect() as connection:
            connection.execute(
                "UPDATE gateway_sharing_config SET enabled = ?, bind_host = ?,"
                " port = ?, exposure_warning_acknowledged = ?, tls_mode = ?,"
                " cert_file = ?, key_file = ?, ca_file = ?, require_client_cert = ?,"
                " updated_at = ? WHERE id = 1",
                (
                    int(next_enabled),
                    next_host,
                    next_port,
                    int(acknowledged),
                    next_tls,
                    next_cert,
                    next_key,
                    next_ca,
                    int(bool(require_client_cert or next_tls == "mtls")),
                    _now(),
                ),
            )
        self._audit(None, "sharing_config", {"bind_host": next_host, "tls_mode": next_tls})
        return self.get_sharing()

    def _get_key(self, key_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_keys WHERE id = ?", (key_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Gateway key not found")
        return _key_row(row)

    def _audit(self, key_id: str | None, action: str, details: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO gateway_key_audit (id, key_id, action, details, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, key_id, action, json.dumps(details), _now()),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _new_key() -> str:
    return f"otk_{secrets.token_urlsafe(32)}"


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key_row(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value.pop("key_hash", None)
    for field in (
        "scopes",
        "allowed_models",
        "allowed_accounts",
        "allowed_groups",
        "allowed_mcp_servers",
    ):
        value[field] = json.loads(value[field])
    value["read_only"] = bool(value["read_only"])
    return value


def _periods(now: datetime.datetime | None = None) -> dict[str, str]:
    current = now or datetime.datetime.now(datetime.timezone.utc)
    day = current.date().isoformat()
    week = (current.date() - datetime.timedelta(days=current.weekday())).isoformat()
    month = current.date().replace(day=1).isoformat()
    return {"daily": day, "weekly": week, "monthly": month}


def _get_usage(
    connection: sqlite3.Connection,
    key_id: str,
    period_type: str,
    period_start: str,
) -> dict[str, int]:
    row = connection.execute(
        "SELECT * FROM gateway_key_usage"
        " WHERE key_id = ? AND period_type = ? AND period_start = ?",
        (key_id, period_type, period_start),
    ).fetchone()
    if row is None:
        return {
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_micros": 0,
            "cache_reads": 0,
        }
    return {
        key: int(row[key])
        for key in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cost_micros",
            "cache_reads",
        )
    }


def _check_model_access(principal: dict[str, Any], model: str) -> None:
    allowed = principal.get("allowed_models") or []
    if allowed and not any(fnmatch.fnmatch(model, pattern) for pattern in allowed):
        raise GatewayAccessDeniedError(f"Gateway key cannot access model {model}")
    if model.startswith("group/"):
        group = model.removeprefix("group/")
        groups = principal.get("allowed_groups") or []
        if groups and not any(fnmatch.fnmatch(group, pattern) for pattern in groups):
            raise GatewayAccessDeniedError(
                f"Gateway key cannot access routing group {group}"
            )


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def _network_warning(host: str) -> str:
    if _is_loopback(host):
        return "Gateway is restricted to this computer."
    return f"Gateway is exposed on {host}; trusted network and firewall rules are required."


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
