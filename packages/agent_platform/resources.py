"""Read-only discovery of instructions and Agent-owned resource files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog import AgentDefinition


_SCANNABLE_KINDS = ("instructions", "subagents", "commands")
_MAX_CONTENT_BYTES = 128 * 1024


def discover_resources(
    definitions: list[AgentDefinition],
    installed_agents: list[dict[str, Any]],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    home_path = Path(home or Path.home()).expanduser()
    resources: list[dict[str, Any]] = []
    for definition in definitions:
        for kind in _SCANNABLE_KINDS:
            template = definition.resource_paths.get(kind)
            if not template:
                continue
            for path in _template_paths(template, home_path):
                item = _file_resource(
                    path,
                    kind=kind,
                    agent_id=definition.id,
                    agent_name=definition.name,
                    home=home_path,
                )
                if item is not None:
                    resources.append(item)

    resources.extend(_claude_plugins(home_path))
    resources.extend(_pi_packages(home_path))
    resources.extend(_special_agent_resources(home_path))
    resources.sort(key=lambda item: (item["kind"], item["name"].casefold()))
    return {
        "home": str(home_path),
        "resources": resources,
        "agents": [
            {
                "id": item["id"],
                "name": item["name"],
                "version": item.get("version"),
                "compatibility": item.get("compatibility"),
                "configuration_ready": bool(item.get("configuration_ready")),
                "capabilities": item.get("capabilities") or [],
                "resource_paths": item.get("resource_paths") or {},
            }
            for item in installed_agents
            if item.get("installed")
        ],
    }


def _template_paths(template: str, home: Path) -> list[Path]:
    raw = Path(template.replace("${HOME}", str(home))).expanduser()
    if "{name}" not in raw.name:
        return [raw] if raw.is_file() else []
    parent = raw.parent
    if not parent.is_dir():
        return []
    return sorted(
        (path for path in parent.glob(raw.name.replace("{name}", "*")) if path.is_file()),
        key=lambda path: path.name.casefold(),
    )


def _file_resource(
    path: Path,
    *,
    kind: str,
    agent_id: str,
    agent_name: str,
    home: Path,
) -> dict[str, Any] | None:
    content = _read_content(path)
    if content is None or not content.strip():
        return None
    description = _description(content)
    return {
        "id": _resource_id("local", kind, agent_id, str(path)),
        "kind": kind,
        "name": _display_name(path),
        "description": description,
        "content": content,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "path": _tilde(path, home),
        "source": "local",
        "metadata": {
            "size": path.stat().st_size,
        },
    }


def _claude_plugins(home: Path) -> list[dict[str, Any]]:
    root = home / ".claude" / "plugins" / "marketplaces"
    if not root.is_dir():
        return []
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for manifest in root.glob("**/.claude-plugin/plugin.json"):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(payload.get("name") or manifest.parent.parent.name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        description = str(payload.get("description") or "").strip()
        version = str(payload.get("version") or "").strip()
        resources.append(
            {
                "id": _resource_id("claude-plugin", "plugins", name, str(manifest)),
                "kind": "plugins",
                "name": name,
                "description": description or "Claude Code plugin",
                "content": manifest.read_text(encoding="utf-8", errors="replace")[
                    :_MAX_CONTENT_BYTES
                ],
                "agent_id": "claude-code",
                "agent_name": "Claude Code",
                "path": _tilde(manifest.parent.parent, home),
                "source": "local",
                "metadata": {
                    "group": "claude-plugins",
                    "version": version or None,
                },
            }
        )
    return resources


def _pi_packages(home: Path) -> list[dict[str, Any]]:
    manifest = home / ".pi" / "agent" / "install" / "managed-install.json"
    if not manifest.is_file():
        return []
    current = home / ".pi" / "agent" / "install" / "current-version"
    version = None
    try:
        version = current.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    return [
        {
            "id": _resource_id("pi-package", "plugins", "pi-runtime", str(manifest)),
            "kind": "plugins",
            "name": "Pi Runtime",
            "description": f"Managed Pi package{f' {version}' if version else ''}",
            "content": manifest.read_text(encoding="utf-8", errors="replace")[
                :_MAX_CONTENT_BYTES
            ],
            "agent_id": "pi",
            "agent_name": "Pi",
            "path": _tilde(manifest.parent, home),
            "source": "local",
            "metadata": {
                "group": "pi-packages",
                "version": version,
            },
        }
    ]


def _special_agent_resources(home: Path) -> list[dict[str, Any]]:
    candidates = (
        (
            "magpie",
            "Magpie",
            (
                home / ".config" / "magpie" / "library.json",
                home / ".config" / "magpie" / "plugins.yml",
            ),
        ),
        (
            "rtk",
            "RTK",
            tuple(_directory_files(home / ".config" / "rtk"))
            + tuple(_directory_files(home / ".rtk")),
        ),
        (
            "billion-context",
            "billion-context",
            tuple(_directory_files(home / ".config" / "billion-context"))
            + tuple(_directory_files(home / ".billion-context")),
        ),
    )
    resources: list[dict[str, Any]] = []
    for agent_id, agent_name, paths in candidates:
        for path in paths:
            content = _read_content(path)
            if content is None or not content.strip():
                continue
            resources.append(
                {
                    "id": _resource_id("special", "plugins", agent_id, str(path)),
                    "kind": "plugins",
                    "name": path.name,
                    "description": _description(content) or f"{agent_name} resource",
                    "content": content,
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "path": _tilde(path, home),
                    "source": "local",
                    "metadata": {"group": agent_id},
                }
            )
    return resources


def _directory_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: str(path).casefold(),
    )[:200]


def _read_content(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_CONTENT_BYTES * 4:
            return None
        return path.read_text(encoding="utf-8", errors="replace")[
            :_MAX_CONTENT_BYTES
        ]
    except OSError:
        return None


def _description(content: str) -> str:
    for line in content.splitlines():
        text = line.strip()
        if not text or text.startswith(("---", "#", "//")):
            continue
        if text.lower().startswith("description:"):
            return text.split(":", 1)[1].strip().strip("\"'")
        return text[:220]
    return ""


def _display_name(path: Path) -> str:
    if path.name.upper() in {"AGENTS.MD", "CLAUDE.MD", "GEMINI.MD"}:
        return path.name
    return path.stem if path.suffix else path.name


def _resource_id(*parts: str) -> str:
    digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{parts[0]}:{digest}"


def _tilde(path: Path, home: Path) -> str:
    try:
        relative = path.resolve().relative_to(home.resolve())
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


__all__ = ["discover_resources"]
