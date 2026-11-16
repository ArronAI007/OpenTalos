"""Subscription inventory adapters, import/export, and warm-up execution."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .store import SubscriptionStore


class SubscriptionValidationError(ValueError):
    pass


_ADAPTERS = (
    {
        "provider": "claude",
        "name": "Claude subscription",
        "sources": (
            "~/.claude/.credentials.json",
            "~/Library/Application Support/Claude/config.json",
        ),
        "models": ["claude-sonnet", "claude-opus"],
    },
    {
        "provider": "codex",
        "name": "ChatGPT / Codex subscription",
        "sources": (
            "~/.codex/auth.json",
        ),
        "models": ["gpt-5-codex", "gpt-5"],
    },
    {
        "provider": "github-copilot",
        "name": "GitHub Copilot",
        "sources": (
            "~/.config/gh/hosts.yml",
            "~/.config/github-copilot/hosts.json",
            "~/Library/Application Support/github-copilot/hosts.json",
        ),
        "models": ["copilot-default"],
    },
    {
        "provider": "gemini",
        "name": "Gemini Code Assist",
        "sources": (
            "~/.gemini/oauth_creds.json",
        ),
        "models": ["gemini-pro", "gemini-flash"],
    },
    {
        "provider": "antigravity",
        "name": "Antigravity",
        "sources": (
            "~/.antigravity/auth.json",
            "~/Library/Application Support/Antigravity/auth.json",
        ),
        "models": ["antigravity-default"],
    },
    {
        "provider": "grok",
        "name": "Grok subscription",
        "sources": (
            "~/.grok/auth.json",
            "~/Library/Application Support/Grok/auth.json",
        ),
        "models": ["grok-default"],
    },
    {
        "provider": "opencode",
        "name": "OpenCode auth",
        "sources": (
            "~/.local/share/opencode/auth.json",
            "~/.config/opencode/auth.json",
        ),
        "models": ["opencode-default"],
    },
)


class SubscriptionInventory:
    def __init__(
        self,
        store: SubscriptionStore,
        *,
        home: Path | None = None,
        platform_name: str | None = None,
    ) -> None:
        self.store = store
        self.home = Path(home or Path.home())
        self.platform_name = platform_name or _platform_name()

    def discover(self) -> list[dict[str, Any]]:
        active_sources: set[tuple[str, str]] = set()
        for adapter in _ADAPTERS:
            source = next(
                (
                    path
                    for candidate in adapter["sources"]
                    if (path := self._expand(candidate)).is_file()
                ),
                None,
            )
            if source is None:
                continue
            active_sources.add((adapter["provider"], str(source)))
            self.store.upsert_account(
                self._account_from_adapter(adapter, source)
            )
        self.store.mark_missing(active_sources)
        return self.store.list_accounts()

    def refresh(self, account_id: str) -> dict[str, Any]:
        internal = self.store.get_account_internal(account_id)
        if internal is None:
            raise ValueError("subscription account not found")
        path = Path(internal["credential_path"]) if internal["credential_path"] else None
        if path is None or not path.is_file():
            return self.store.upsert_account(
                {
                    **self.store.get_account(account_id),
                    "signed_in": False,
                    "quota": {"status": "unknown"},
                }
            )
        adapter = next(
            item for item in _ADAPTERS if item["provider"] == internal["provider"]
        )
        return self.store.upsert_account(self._account_from_adapter(adapter, path))

    def export_bundle(
        self,
        *,
        include_credentials: bool = False,
        acknowledge_credentials: bool = False,
    ) -> dict[str, Any]:
        if include_credentials and not acknowledge_credentials:
            raise SubscriptionValidationError(
                "you must acknowledge that the export contains credentials"
            )
        payload = {
            "schema": "opentalos-subscription-export-v1",
            "exported_at": _now(),
            "warning": (
                "Credential exports contain sign-in secrets. Store them only in a "
                "trusted encrypted location."
            ),
            "accounts": self.store.list_accounts(),
        }
        if include_credentials:
            credentials = []
            for account in self.store.list_accounts():
                internal = self.store.get_account_internal(account["id"])
                path = Path(internal["credential_path"]) if internal and internal["credential_path"] else None
                if path is not None and path.is_file():
                    credentials.append(
                        {
                            "provider": account["provider"],
                            "path": str(path),
                            "content": path.read_text(encoding="utf-8", errors="replace"),
                        }
                    )
            payload["credentials"] = credentials
        return payload

    def import_bundle(self, payload: dict[str, Any]) -> int:
        accounts = payload.get("accounts")
        if not isinstance(accounts, list):
            raise SubscriptionValidationError("invalid subscription export: accounts is required")
        imported = 0
        for account in accounts:
            if not isinstance(account, dict) or not account.get("provider"):
                continue
            provider = str(account["provider"])
            self.store.upsert_account(
                {
                    "provider": provider,
                    "name": str(account.get("name") or provider),
                    "source": str(account.get("source") or "import"),
                    "credential_path": None,
                    "signed_in": bool(account.get("signed_in", False)),
                    "project_id": account.get("project_id"),
                    "models": account.get("models") or [],
                    "quota": account.get("quota") or {"status": "unknown"},
                    "metadata": {"imported": True},
                }
            )
            imported += 1
        return imported

    def schedule_warmup(
        self,
        account_id: str,
        *,
        mode: str,
        at_time: str,
    ) -> dict[str, Any]:
        if mode not in {"daily", "reset"}:
            raise SubscriptionValidationError("warm-up mode must be daily or reset")
        if not re.fullmatch(r"\d{2}:\d{2}", at_time):
            raise SubscriptionValidationError("warm-up time must use HH:MM")
        next_run = _next_daily_run(datetime.datetime.now(datetime.timezone.utc), at_time)
        return self.store.create_warmup(
            account_id,
            mode=mode,
            at_time=at_time,
            next_run_at=next_run.isoformat(),
        )

    async def run_due_warmups(
        self,
        *,
        now: datetime.datetime | None = None,
        warm: Callable[[dict[str, Any]], Awaitable[None] | None],
    ) -> int:
        current = now or datetime.datetime.now(datetime.timezone.utc)
        ran = 0
        for schedule in self.store.due_warmups(current):
            account = self.store.get_account(schedule["account_id"])
            result = warm(account)
            if hasattr(result, "__await__"):
                await result
            next_run = _next_daily_run(current, schedule["at_time"])
            self.store.complete_warmup(
                schedule["id"],
                run_at=current,
                next_run_at=next_run,
            )
            ran += 1
        return ran

    def _account_from_adapter(
        self,
        adapter: dict[str, Any],
        source: Path,
    ) -> dict[str, Any]:
        metadata = _read_metadata(source)
        label = adapter["name"]
        if adapter["provider"] == "github-copilot":
            match = re.search(r"^\s+user:\s*(\S+)", source.read_text(errors="replace"), re.MULTILINE)
            if match:
                label = f"GitHub Copilot · {match.group(1)}"
        elif adapter["provider"] == "codex" and metadata.get("account_id"):
            label = f"ChatGPT · {str(metadata['account_id'])[:8]}"
        account_key = hashlib.sha256(
            f"{adapter['provider']}\0{source}".encode("utf-8")
        ).hexdigest()[:20]
        return {
            "id": f"sub-{account_key}",
            "provider": adapter["provider"],
            "name": label,
            "source": str(source),
            "credential_path": str(source),
            "signed_in": True,
            "project_id": metadata.get("project_id"),
            "models": adapter["models"],
            "quota": {"status": "unknown", "windows": []},
            "metadata": {
                "platform": self.platform_name,
                "adapter": adapter["provider"],
            },
        }

    def _expand(self, value: str) -> Path:
        expanded = (
            str(self.home / value.removeprefix("~/"))
            if value.startswith("~/")
            else value
        )
        path = Path(os.path.expanduser(expanded))
        if path.is_absolute():
            return path
        return self.home / path


def _read_metadata(path: Path) -> dict[str, Any]:
    if path.suffix.lower() not in {".json", ".toml"}:
        return {}
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            import tomllib

            payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    tokens = payload.get("tokens")
    if isinstance(tokens, dict) and tokens.get("account_id"):
        return {"account_id": tokens["account_id"]}
    return {
        "account_id": payload.get("account_id"),
        "project_id": payload.get("project_id") or payload.get("projectId"),
    }


def _next_daily_run(now: datetime.datetime, at_time: str) -> datetime.datetime:
    hour, minute = (int(part) for part in at_time.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def _platform_name() -> str:
    import sys

    return sys.platform


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
