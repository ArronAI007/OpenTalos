"""Pinned Magpie Agent catalog enriched with safe discovery and adapter metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.runtime_paths import resource_root

_RESOURCE_ROOT = resource_root()
_CATALOG_PATH = _RESOURCE_ROOT / "specs" / "007-magpie-python-parity" / "agent-catalog.json"

_ALL_PLATFORMS = ("darwin", "linux", "win32")


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    commands: tuple[str, ...]
    config_paths: dict[str, tuple[str, ...]]
    config_format: str
    compatibility: str
    compatibility_path: str
    install_hint: str
    update_plan: dict[str, tuple[str, ...]]
    resource_paths: dict[str, str]
    catalog_source: str
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    app_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def supports_configuration(self) -> bool:
        return self.compatibility == "native" and self.config_format != "manual"

    def path_for_platform(self, platform_name: str) -> str | None:
        candidates = self.config_paths.get(platform_name, ())
        return candidates[0] if candidates else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "commands": list(self.commands),
            "config_format": self.config_format,
            "compatibility": self.compatibility,
            "compatibility_path": self.compatibility_path,
            "install_hint": self.install_hint,
            "supports_configuration": self.supports_configuration,
            "capabilities": list(self.capabilities),
            "config_path": self.path_for_platform(_platform_name()),
            "resource_paths": dict(self.resource_paths),
            "catalog_source": self.catalog_source,
        }


_CLAUDE = AgentDefinition(
    id="claude-code",
    name="Claude Code",
    commands=("claude", "claude-code"),
    config_paths={
        "darwin": ("~/.claude/settings.json",),
        "linux": ("~/.claude/settings.json",),
        "win32": ("~/.claude/settings.json",),
    },
    config_format="claude-settings",
    compatibility="native",
    compatibility_path=(
        "Native adapter writes Anthropic-compatible Gateway URL, local token, "
        "and model to Claude Code settings.json."
    ),
    install_hint="npm install -g @anthropic-ai/claude-code",
    update_plan={"npm": ("npm", "install", "-g", "@anthropic-ai/claude-code@latest")},
    resource_paths={
        "instructions": "~/.claude/CLAUDE.md",
        "mcp": "~/.claude.json",
        "skills": "~/.claude/skills/{name}/SKILL.md",
        "subagents": "~/.claude/agents/{name}.md",
        "commands": "~/.claude/commands/{name}.md",
        "plugins": "~/.claude/plugins/{name}.json",
    },
    catalog_source="",
    capabilities=("models", "instructions", "mcp", "skills", "subagents"),
)

_CODEX = AgentDefinition(
    id="codex",
    name="Codex",
    commands=("codex",),
    config_paths={
        "darwin": ("~/.codex/config.toml",),
        "linux": ("~/.codex/config.toml",),
        "win32": ("~/.codex/config.toml",),
    },
    config_format="codex-toml",
    compatibility="native",
    compatibility_path=(
        "Native adapter writes an OpenAI-compatible OpenTalos provider and model "
        "to Codex config.toml while preserving unrelated configuration."
    ),
    install_hint="npm install -g @openai/codex",
    update_plan={"npm": ("npm", "install", "-g", "@openai/codex@latest")},
    resource_paths={
        "instructions": "~/.codex/AGENTS.md",
        "skills": "~/.codex/skills/{name}/SKILL.md",
        "subagents": "~/.codex/agents/{name}.md",
        "commands": "~/.codex/prompts/{name}.md",
    },
    catalog_source="",
    capabilities=("models", "instructions", "mcp", "skills", "subagents"),
)

_GEMINI = AgentDefinition(
    id="gemini-cli",
    name="Gemini CLI",
    commands=("gemini",),
    config_paths={
        "darwin": ("~/.gemini/settings.json",),
        "linux": ("~/.gemini/settings.json",),
        "win32": ("~/.gemini/settings.json",),
    },
    config_format="gemini-settings",
    compatibility="native",
    compatibility_path=(
        "Native adapter writes model and OpenAI-compatible Gateway environment "
        "fields to Gemini CLI settings.json."
    ),
    install_hint="npm install -g @google/gemini-cli",
    update_plan={"npm": ("npm", "install", "-g", "@google/gemini-cli@latest")},
    resource_paths={
        "instructions": "~/.gemini/GEMINI.md",
        "skills": "~/.gemini/skills/{name}/SKILL.md",
        "subagents": "~/.gemini/agents/{name}.md",
        "commands": "~/.gemini/commands/{name}.md",
    },
    catalog_source="",
    capabilities=("models", "instructions", "mcp", "skills", "subagents"),
)

_OPENCODE = AgentDefinition(
    id="opencode",
    name="OpenCode",
    commands=("opencode",),
    config_paths={
        "darwin": (
            "~/.config/opencode/opencode.json",
            "~/.config/opencode/config.json",
        ),
        "linux": (
            "~/.config/opencode/opencode.json",
            "~/.config/opencode/config.json",
        ),
        "win32": (
            "~/.config/opencode/opencode.json",
            "~/.config/opencode/config.json",
        ),
    },
    config_format="opencode-json",
    compatibility="native",
    compatibility_path=(
        "Native adapter writes an OpenAI-compatible provider and selected model "
        "to OpenCode JSON configuration."
    ),
    install_hint="npm install -g opencode-ai",
    update_plan={"npm": ("npm", "install", "-g", "opencode-ai@latest")},
    resource_paths={
        "instructions": "~/.config/opencode/AGENTS.md",
        "skills": "~/.config/opencode/skills/{name}/SKILL.md",
        "subagents": "~/.config/opencode/agents/{name}.md",
        "commands": "~/.config/opencode/commands/{name}.md",
    },
    catalog_source="",
    capabilities=("models", "instructions", "mcp", "skills", "subagents"),
)

_KNOWN = {agent.name: agent for agent in (_CLAUDE, _CODEX, _GEMINI, _OPENCODE)}


class AgentCatalogError(RuntimeError):
    """Raised when the pinned Agent catalog cannot be loaded or validated."""


def load_catalog(path: Path | None = None) -> list[AgentDefinition]:
    catalog_path = Path(path) if path is not None else _CATALOG_PATH
    try:
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgentCatalogError(f"cannot load Agent catalog: {error}") from error

    source = str(document.get("source") or "").strip()
    names = document.get("agents")
    if not source or not isinstance(names, list):
        raise AgentCatalogError("Agent catalog must contain source and agents")

    agents: list[AgentDefinition] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name).strip()
        agent_id = _slug(name)
        if not name or not agent_id or agent_id in seen:
            raise AgentCatalogError(f"invalid or duplicate Agent name: {raw_name!r}")
        seen.add(agent_id)
        known = _KNOWN.get(name)
        if known is not None:
            agents.append(
                AgentDefinition(
                    id=known.id,
                    name=known.name,
                    commands=known.commands,
                    config_paths=known.config_paths,
                    config_format=known.config_format,
                    compatibility=known.compatibility,
                    compatibility_path=known.compatibility_path,
                    install_hint=known.install_hint,
                    update_plan=known.update_plan,
                    resource_paths=known.resource_paths,
                    catalog_source=source,
                    capabilities=known.capabilities,
                    metadata=known.metadata,
                    app_paths=known.app_paths,
                )
            )
            continue
        agents.append(
            AgentDefinition(
                id=agent_id,
                name=name,
                commands=(agent_id,),
                config_paths={},
                config_format="manual",
                compatibility="manual",
                compatibility_path=(
                    "Use the OpenTalos Gateway as an OpenAI-compatible endpoint "
                    "and configure this Agent through its native settings. "
                    "Automatic file editing is disabled until a safe adapter is verified."
                ),
                install_hint=f"Install {name} using its official package or application installer.",
                update_plan={},
                resource_paths={},
                catalog_source=source,
                app_paths={
                    "darwin": (
                        f"/Applications/{name}.app",
                        f"~/Applications/{name}.app",
                    ),
                    "win32": (
                        f"%LOCALAPPDATA%/{name}/{name}.exe",
                        f"%PROGRAMFILES%/{name}/{name}.exe",
                    ),
                },
            )
        )
    return agents


def find_agent(agent_id: str, agents: list[AgentDefinition] | None = None) -> AgentDefinition | None:
    source = list(agents) if agents is not None else load_catalog()
    return next((agent for agent in source if agent.id == agent_id), None)


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return value


def _platform_name() -> str:
    import sys

    return sys.platform
