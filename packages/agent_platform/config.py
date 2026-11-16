"""Atomic, locked, verified Agent configuration transactions."""

from __future__ import annotations

import contextlib
import copy
import difflib
import json
import os
import re
import tempfile
import time
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from .catalog import AgentDefinition
from .store import AgentPlatformStore


class AgentConfigError(RuntimeError):
    """Raised when an Agent configuration cannot be rendered or committed safely."""


class AgentConfigManager:
    def __init__(
        self,
        store: AgentPlatformStore,
        *,
        gateway_url: str,
        replace: Callable[[str | bytes | os.PathLike[str], str | bytes | os.PathLike[str]], None]
        = os.replace,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.gateway_url = gateway_url.rstrip("/")
        self._replace = replace
        self._sleep = sleep

    def preview(
        self,
        definition: AgentDefinition,
        *,
        model: str,
        path: Path | None = None,
    ) -> dict[str, Any]:
        target = self._target_path(definition, path)
        before = target.read_text(encoding="utf-8") if target.exists() else ""
        after = _render_config(
            definition.config_format,
            before,
            model=model.strip(),
            gateway_url=self.gateway_url,
        )
        diff = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=str(target),
                tofile=str(target),
                lineterm="",
            )
        )
        return {
            "agent_id": definition.id,
            "path": str(target),
            "existed": target.exists(),
            "changed": before != after,
            "before": before,
            "after": after,
            "diff": "\n".join(diff),
        }

    def apply(
        self,
        definition: AgentDefinition,
        *,
        model: str,
        path: Path | None = None,
    ) -> dict[str, Any]:
        if not definition.supports_configuration:
            raise AgentConfigError(
                f"{definition.name} has no safe automatic configuration adapter"
            )
        if not model.strip():
            raise AgentConfigError("a model binding is required")
        target = self._target_path(definition, path)
        with self._lock(target):
            before = target.read_bytes() if target.exists() else None
            mode = target.stat().st_mode if target.exists() else None
            before_text = before.decode("utf-8") if before is not None else ""
            after_text = _render_config(
                definition.config_format,
                before_text,
                model=model.strip(),
                gateway_url=self.gateway_url,
            )
            after = after_text.encode("utf-8")
            self.store.capture_snapshot(definition.id, target)
            try:
                _atomic_write(target, after, mode=mode, replace=self._replace)
                _verify(definition.config_format, target, after)
            except Exception as error:
                with contextlib.suppress(Exception):
                    _restore_bytes(target, before, mode=mode, replace=self._replace)
                self.store.add_transaction(
                    definition.id,
                    action="configure",
                    path=target,
                    before=before,
                    after=after,
                    status="failed",
                    message=str(error),
                )
                raise AgentConfigError(str(error)) from error
            transaction = self.store.add_transaction(
                definition.id,
                action="configure",
                path=target,
                before=before,
                after=after,
                status="ok",
            )
        return {
            "status": "ok",
            "agent_id": definition.id,
            "path": str(target),
            "transaction": transaction,
        }

    def restore(self, agent_id: str) -> dict[str, Any]:
        snapshots = self.store.list_snapshots(agent_id)
        if not snapshots:
            raise AgentConfigError("no managed configuration snapshot exists")
        restored: list[dict[str, Any]] = []
        for snapshot in snapshots:
            target = Path(snapshot["path"])
            with self._lock(target):
                before = target.read_bytes() if target.exists() else None
                mode = target.stat().st_mode if target.exists() else snapshot.get("mode")
                try:
                    _restore_bytes(
                        target,
                        snapshot["content"] if snapshot["existed"] else None,
                        mode=mode,
                        replace=self._replace,
                    )
                except Exception as error:
                    self.store.add_transaction(
                        agent_id,
                        action="restore",
                        path=target,
                        before=before,
                        after=snapshot["content"],
                        status="failed",
                        message=str(error),
                    )
                    raise AgentConfigError(str(error)) from error
                self.store.add_transaction(
                    agent_id,
                    action="restore",
                    path=target,
                    before=before,
                    after=snapshot["content"],
                    status="ok",
                )
                restored.append(
                    {
                        "path": str(target),
                        "restored": True,
                        "existed": snapshot["existed"],
                    }
                )
        return {"agent_id": agent_id, "restored": restored}

    def apply_library_item(
        self,
        definition: AgentDefinition,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        if not definition.supports_configuration:
            raise AgentConfigError(
                f"{definition.name} has no safe automatic resource adapter"
            )
        target = self._resource_target(definition, item)
        with self._lock(target):
            before = target.read_bytes() if target.exists() else None
            mode = target.stat().st_mode if target.exists() else None
            before_text = before.decode("utf-8") if before is not None else ""
            after_text = _render_library_item(
                definition,
                item,
                before_text,
            )
            after = after_text.encode("utf-8")
            self.store.capture_snapshot(definition.id, target)
            try:
                _atomic_write(target, after, mode=mode, replace=self._replace)
                _verify(
                    definition.config_format
                    if item["kind"] == "mcp"
                    else "text",
                    target,
                    after,
                )
            except Exception as error:
                with contextlib.suppress(Exception):
                    _restore_bytes(target, before, mode=mode, replace=self._replace)
                self.store.add_transaction(
                    definition.id,
                    action=f"library-{item['kind']}",
                    path=target,
                    before=before,
                    after=after,
                    status="failed",
                    message=str(error),
                )
                raise AgentConfigError(str(error)) from error
            self.store.record_library_binding(item["id"], definition.id, target)
            transaction = self.store.add_transaction(
                definition.id,
                action=f"library-{item['kind']}",
                path=target,
                before=before,
                after=after,
                status="ok",
            )
        return {
            "status": "ok",
            "agent_id": definition.id,
            "item_id": item["id"],
            "path": str(target),
            "transaction": transaction,
        }

    def remove_library_item(
        self,
        definition: AgentDefinition,
        item_id: str,
    ) -> dict[str, Any]:
        item = self.store.get_library_item(item_id)
        if item is None:
            raise AgentConfigError("library item not found")
        binding = self.store.get_library_binding(item_id, definition.id)
        if binding is None:
            raise AgentConfigError("library item is not applied to this Agent")
        target = Path(binding["path"])
        with self._lock(target):
            before = target.read_bytes() if target.exists() else None
            mode = target.stat().st_mode if target.exists() else None
            if before is None:
                self.store.remove_library_binding(item_id, definition.id)
                return {
                    "status": "ok",
                    "agent_id": definition.id,
                    "item_id": item_id,
                    "path": str(target),
                    "removed": True,
                }
            before_text = before.decode("utf-8")
            after_text = _remove_library_item(definition, item, before_text)
            after = after_text.encode("utf-8") if after_text is not None else None
            try:
                if after is None:
                    target.unlink()
                else:
                    _atomic_write(target, after, mode=mode, replace=self._replace)
            except Exception as error:
                self.store.add_transaction(
                    definition.id,
                    action=f"library-{item['kind']}-remove",
                    path=target,
                    before=before,
                    after=after,
                    status="failed",
                    message=str(error),
                )
                raise AgentConfigError(str(error)) from error
            self.store.remove_library_binding(item_id, definition.id)
            self.store.add_transaction(
                definition.id,
                action=f"library-{item['kind']}-remove",
                path=target,
                before=before,
                after=after,
                status="ok",
            )
        return {
            "status": "ok",
            "agent_id": definition.id,
            "item_id": item_id,
            "path": str(target),
            "removed": True,
        }

    def _target_path(
        self,
        definition: AgentDefinition,
        explicit: Path | None,
    ) -> Path:
        if explicit is not None:
            return Path(explicit).expanduser()
        raw = definition.path_for_platform(_platform_name())
        if not raw:
            raise AgentConfigError(
                f"{definition.name} has no configuration path for this platform"
            )
        return Path(raw).expanduser()

    def _resource_target(
        self,
        definition: AgentDefinition,
        item: dict[str, Any],
    ) -> Path:
        kind = item["kind"]
        templates = definition.resource_paths
        template = templates.get(kind)
        if kind == "mcp" and not template:
            template = definition.path_for_platform(_platform_name())
        if not template:
            raise AgentConfigError(
                f"{definition.name} does not support the {kind} library"
            )
        if kind in {"skills", "subagents"}:
            template = template.format(name=_safe_name(item["name"]))
        return Path(template).expanduser()

    @contextlib.contextmanager
    def _lock(self, target: Path, timeout: float = 5.0) -> Iterator[None]:
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = target.with_name(f".{target.name}.opentalos.lock")
        deadline = time.monotonic() + timeout
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime > 30
                except FileNotFoundError:
                    continue
                if stale:
                    with contextlib.suppress(FileNotFoundError):
                        lock_path.unlink()
                    continue
                if time.monotonic() >= deadline:
                    raise AgentConfigError(f"configuration is locked: {target}")
                self._sleep(0.05)
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            descriptor = None
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()


def _render_config(
    config_format: str,
    before: str,
    *,
    model: str,
    gateway_url: str,
) -> str:
    if not model:
        raise AgentConfigError("a model binding is required")
    if config_format == "codex-toml":
        return _render_codex_toml(before, model=model, gateway_url=gateway_url)
    if config_format in {
        "json-env",
        "claude-settings",
        "gemini-settings",
        "opencode-json",
    }:
        payload = _parse_json_object(before)
        if config_format in {"json-env", "claude-settings"}:
            env = payload.setdefault("env", {})
            if not isinstance(env, dict):
                raise AgentConfigError("env must be a JSON object")
            env.update(
                {
                    "ANTHROPIC_BASE_URL": gateway_url,
                    "ANTHROPIC_AUTH_TOKEN": "opentalos-local",
                    "ANTHROPIC_MODEL": model,
                    "OPENAI_BASE_URL": gateway_url,
                    "OPENAI_API_KEY": "opentalos-local",
                    "OPENAI_MODEL": model,
                }
            )
        elif config_format == "gemini-settings":
            payload["model"] = model
            env = payload.setdefault("env", {})
            if not isinstance(env, dict):
                raise AgentConfigError("env must be a JSON object")
            env.update(
                {
                    "OPENAI_BASE_URL": gateway_url,
                    "OPENAI_API_KEY": "opentalos-local",
                    "OPENAI_MODEL": model,
                }
            )
        else:
            providers = payload.setdefault("provider", {})
            if not isinstance(providers, dict):
                raise AgentConfigError("provider must be a JSON object")
            providers["opentalos"] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "OpenTalos Gateway",
                "options": {
                    "baseURL": gateway_url,
                    "apiKey": "opentalos-local",
                },
                "models": {model: {"name": model}},
            }
            payload["model"] = f"opentalos/{model}"
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    raise AgentConfigError(f"unsupported configuration format: {config_format}")


def _render_library_item(
    definition: AgentDefinition,
    item: dict[str, Any],
    before: str,
) -> str:
    kind = item["kind"]
    if kind == "mcp":
        entry = _mcp_entry(item)
        if definition.config_format == "codex-toml":
            return _render_codex_mcp(before, item=item, entry=entry)
        if definition.config_format in {
            "json-env",
            "claude-settings",
            "gemini-settings",
            "opencode-json",
        }:
            payload = _parse_json_object(before)
            servers = payload.setdefault("mcpServers", {})
            if not isinstance(servers, dict):
                raise AgentConfigError("mcpServers must be a JSON object")
            servers[_mcp_key(item)] = entry
            return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        raise AgentConfigError(
            f"{definition.name} has no safe MCP resource format"
        )
    if kind == "instructions":
        return _upsert_markdown_block(before, item)
    if kind in {"skills", "subagents"}:
        return str(item["content"])
    raise AgentConfigError(f"unsupported library kind: {kind}")


def _remove_library_item(
    definition: AgentDefinition,
    item: dict[str, Any],
    before: str,
) -> str | None:
    kind = item["kind"]
    if kind == "instructions":
        return _remove_markdown_block(before, item["id"])
    if kind == "mcp":
        if definition.config_format == "codex-toml":
            return _remove_managed_lines(before, item["id"])
        payload = _parse_json_object(before)
        servers = payload.get("mcpServers")
        if isinstance(servers, dict):
            servers.pop(_mcp_key(item), None)
            if not servers:
                payload.pop("mcpServers", None)
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if kind in {"skills", "subagents"}:
        return None
    raise AgentConfigError(f"unsupported library kind: {kind}")


def _upsert_markdown_block(before: str, item: dict[str, Any]) -> str:
    cleaned = _remove_markdown_block(before, item["id"]).rstrip()
    begin = f"<!-- BEGIN OPENTALOS {item['id']} -->"
    end = f"<!-- END OPENTALOS {item['id']} -->"
    block = f"{begin}\n{str(item['content']).rstrip()}\n{end}"
    return f"{cleaned}\n\n{block}\n" if cleaned else f"{block}\n"


def _remove_markdown_block(before: str, item_id: str) -> str:
    begin = re.escape(f"<!-- BEGIN OPENTALOS {item_id} -->")
    end = re.escape(f"<!-- END OPENTALOS {item_id} -->")
    cleaned = re.sub(
        rf"\n*{begin}.*?{end}\n*",
        "\n",
        before,
        flags=re.DOTALL,
    )
    return cleaned.strip() + "\n" if cleaned.strip() else ""


def _render_codex_mcp(
    before: str,
    *,
    item: dict[str, Any],
    entry: dict[str, Any],
) -> str:
    cleaned = _remove_managed_lines(before, item["id"]).rstrip()
    name = _mcp_key(item)
    lines = [
        f"# BEGIN OPENTALOS {item['id']}",
        f"[mcp_servers.{json.dumps(name)}]",
    ]
    if entry.get("command"):
        lines.append(f"command = {_toml_string(str(entry['command']))}")
    if entry.get("args"):
        args = ", ".join(_toml_string(str(value)) for value in entry["args"])
        lines.append(f"args = [{args}]")
    if entry.get("url"):
        lines.append(f"url = {_toml_string(str(entry['url']))}")
    if entry.get("env"):
        values = ", ".join(
            f"{key} = {_toml_string(str(value))}"
            for key, value in entry["env"].items()
        )
        lines.append(f"env = {{ {values} }}")
    lines.append(f"# END OPENTALOS {item['id']}")
    rendered = f"{cleaned}\n\n{'\n'.join(lines)}\n" if cleaned else f"{'\n'.join(lines)}\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise AgentConfigError(f"invalid MCP TOML after update: {error}") from error
    return rendered


def _remove_managed_lines(before: str, item_id: str) -> str:
    begin = re.escape(f"# BEGIN OPENTALOS {item_id}")
    end = re.escape(f"# END OPENTALOS {item_id}")
    cleaned = re.sub(
        rf"\n*{begin}.*?{end}\n*",
        "\n",
        before,
        flags=re.DOTALL,
    )
    return cleaned.strip() + "\n" if cleaned.strip() else ""


def _mcp_entry(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    if metadata:
        return dict(metadata)
    try:
        entry = json.loads(item.get("content") or "{}")
    except json.JSONDecodeError as error:
        raise AgentConfigError(f"MCP content must be a JSON object: {error}") from error
    if not isinstance(entry, dict) or not entry:
        raise AgentConfigError("MCP metadata or JSON content is required")
    return entry


def _mcp_key(item: dict[str, Any]) -> str:
    return f"opentalos-{_safe_name(item['name'])}-{str(item['id'])[:8]}"


def _safe_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return name or "item"


def _render_codex_toml(before: str, *, model: str, gateway_url: str) -> str:
    managed_start = "# BEGIN OPENTALOS MANAGED"
    managed_end = "# END OPENTALOS MANAGED"
    lines = before.splitlines()
    if managed_start in lines and managed_end in lines:
        start = lines.index(managed_start)
        end = lines.index(managed_end)
        lines = lines[:start] + lines[end + 1 :]

    top_level_end = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    top = lines[:top_level_end]
    rest = lines[top_level_end:]
    replacements = {
        "model": f'model = {_toml_string(model)}',
        "model_provider": 'model_provider = "opentalos"',
    }
    found: set[str] = set()
    next_top: list[str] = []
    for line in top:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            if key not in found:
                next_top.append(replacements[key])
                found.add(key)
            continue
        next_top.append(line)
    missing = [replacements[key] for key in ("model_provider", "model") if key not in found]
    if missing:
        insertion = 0
        while insertion < len(next_top) and (
            not next_top[insertion].strip() or next_top[insertion].lstrip().startswith("#")
        ):
            insertion += 1
        next_top[insertion:insertion] = missing
    while next_top and not next_top[-1].strip():
        next_top.pop()

    managed = [
        managed_start,
        "[model_providers.opentalos]",
        'name = "OpenTalos Gateway"',
        f"base_url = {_toml_string(gateway_url)}",
        'wire_api = "responses"',
        'http_headers = { Authorization = "Bearer opentalos-local" }',
        managed_end,
    ]
    rendered = "\n".join([*next_top, "", *rest, "", *managed]).strip() + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise AgentConfigError(f"invalid Codex TOML after update: {error}") from error
    return rendered


def _parse_json_object(before: str) -> dict[str, Any]:
    if not before.strip():
        return {}
    try:
        payload = json.loads(before)
    except json.JSONDecodeError as error:
        raise AgentConfigError(f"invalid JSON configuration: {error}") from error
    if not isinstance(payload, dict):
        raise AgentConfigError("Agent JSON configuration must be an object")
    return copy.deepcopy(payload)


def _atomic_write(
    target: Path,
    content: bytes,
    *,
    mode: int | None,
    replace: Callable[[str | bytes | os.PathLike[str], str | bytes | os.PathLike[str]], None],
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".opentalos.tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        replace(temporary, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _restore_bytes(
    target: Path,
    content: bytes | None,
    *,
    mode: int | None,
    replace: Callable[[str | bytes | os.PathLike[str], str | bytes | os.PathLike[str]], None],
) -> None:
    if content is None:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        return
    _atomic_write(target, content, mode=mode, replace=replace)


def _verify(config_format: str, target: Path, expected: bytes) -> None:
    actual = target.read_bytes()
    if actual != expected:
        raise AgentConfigError("configuration verification failed: bytes differ")
    if config_format == "codex-toml":
        try:
            tomllib.loads(actual.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise AgentConfigError(f"configuration verification failed: {error}") from error
    elif config_format.endswith("-json") or config_format.endswith("-settings"):
        try:
            json.loads(actual.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentConfigError(f"configuration verification failed: {error}") from error


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _platform_name() -> str:
    import sys

    return sys.platform
