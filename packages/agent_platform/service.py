"""Application service for external Agent discovery, binding, and configuration."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from model_platform.control_plane import ControlPlaneStore

from .catalog import AgentDefinition, load_catalog
from .config import AgentConfigError, AgentConfigManager
from .discovery import AgentDiscovery
from .store import AgentPlatformStore, AgentPlatformValidationError


class AgentNotFoundError(LookupError):
    """Raised when an Agent id is not present in the pinned catalog."""


class AgentPlatformService:
    def __init__(
        self,
        store: AgentPlatformStore,
        control_store: ControlPlaneStore,
        *,
        catalog: Sequence[AgentDefinition] | None = None,
        discovery: AgentDiscovery | None = None,
        config_manager: AgentConfigManager | None = None,
        gateway_url: str = "http://127.0.0.1:3425/v1",
        command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.store = store
        self.control_store = control_store
        self.catalog = list(catalog if catalog is not None else load_catalog())
        self._definitions = {agent.id: agent for agent in self.catalog}
        if len(self._definitions) != len(self.catalog):
            raise ValueError("Agent catalog ids must be unique")
        self.discovery = discovery or AgentDiscovery(self.catalog)
        self.config = config_manager or AgentConfigManager(
            store,
            gateway_url=gateway_url,
        )
        self.gateway_url = gateway_url.rstrip("/")
        self._command_runner = command_runner or _run_command

    def refresh_installations(self) -> list[dict[str, Any]]:
        discovered = {
            item["agent_id"]: item for item in self.discovery.discover()
        }
        scan: list[dict[str, Any]] = []
        for definition in self.catalog:
            item = discovered.get(definition.id)
            if item is None:
                scan.append(
                    {
                        "agent_id": definition.id,
                        "name": definition.name,
                        "installed": False,
                        "config_path": definition.path_for_platform(_platform_name()),
                        "platform": _platform_name(),
                        "compatibility": definition.compatibility,
                        "compatibility_path": definition.compatibility_path,
                        "install_hint": definition.install_hint,
                    }
                )
            else:
                scan.append(item)
        self.store.save_installations(scan)
        return self.list_agents(installed_only=True)

    def list_agents(
        self,
        *,
        installed_only: bool = False,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        installations = {
            item["agent_id"]: item for item in self.store.list_installations()
        }
        bindings = {item["agent_id"]: item for item in self.store.list_bindings()}
        needle = (query or "").strip().casefold()
        agents: list[dict[str, Any]] = []
        for definition in self.catalog:
            installation = installations.get(definition.id, {})
            installed = bool(installation.get("installed"))
            if installed_only and not installed:
                continue
            if needle and needle not in (
                f"{definition.name} {definition.id} {definition.compatibility}"
            ).casefold():
                continue
            item = definition.to_dict()
            item.update(
                {
                    key: value
                    for key, value in installation.items()
                    if key not in {"agent_id", "name"}
                }
            )
            item["installed"] = installed
            item["binding"] = bindings.get(definition.id)
            item["configuration_ready"] = (
                definition.supports_configuration and installed
            )
            agents.append(item)
        return agents

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        item = next(
            (agent for agent in self.list_agents() if agent["id"] == agent_id),
            None,
        )
        if item is None:
            raise AgentNotFoundError(agent_id)
        return item

    def definition(self, agent_id: str) -> AgentDefinition:
        definition = self._definitions.get(agent_id)
        if definition is None:
            raise AgentNotFoundError(agent_id)
        return definition

    def model_options(self, agent_id: str) -> list[dict[str, Any]]:
        definition = self.definition(agent_id)
        accounts = {
            account["id"]: account for account in self.control_store.list_accounts()
        }
        options: list[dict[str, Any]] = []
        for model in self.control_store.list_models():
            account = accounts.get(model["account_id"], {})
            eligible = bool(account.get("enabled")) and definition.supports_configuration
            reason = None
            if not account.get("enabled"):
                reason = "Provider account is disabled"
            elif not definition.supports_configuration:
                reason = (
                    "This Agent only has a documented manual Gateway compatibility path"
                )
            options.append(
                {
                    "value": (
                        f"{model['provider']}/{model['account_name']}/"
                        f"{model['model_id']}"
                    ),
                    "label": (
                        f"{model['display_name']} · "
                        f"{model['provider']}/{model['account_name']}"
                    ),
                    "kind": "model",
                    "model_id": model["model_id"],
                    "provider": model["provider"],
                    "account_id": model["account_id"],
                    "account_name": model["account_name"],
                    "protocol": model["protocol"],
                    "context_window": model.get("context_window"),
                    "supports_tools": model.get("supports_tools"),
                    "eligible": eligible,
                    "reason": reason,
                }
            )
        for group in self.control_store.list_routing_groups():
            options.append(
                {
                    "value": f"group/{group['name']}",
                    "label": f"{group['name']} · routing group",
                    "kind": "group",
                    "model_id": None,
                    "provider": None,
                    "account_id": None,
                    "account_name": None,
                    "protocol": "openai-chat",
                    "context_window": None,
                    "supports_tools": True,
                    "eligible": definition.supports_configuration,
                    "reason": (
                        None
                        if definition.supports_configuration
                        else "Automatic Agent configuration is not available"
                    ),
                }
            )
        return options

    def update_binding(
        self,
        agent_id: str,
        *,
        model: str,
        shortlist: list[str],
        routing_preference: str | None = None,
    ) -> dict[str, Any]:
        self.definition(agent_id)
        clean_model = model.strip()
        clean_shortlist = [item.strip() for item in shortlist if item.strip()]
        if clean_model or clean_shortlist:
            options = {
                item["value"]: item
                for item in self.model_options(agent_id)
            }
            values = {clean_model, *clean_shortlist} - {""}
            unknown = sorted(value for value in values if value not in options)
            if unknown:
                raise AgentPlatformValidationError(
                    f"unknown model binding: {', '.join(unknown)}"
                )
            ineligible = sorted(
                value for value in values if not options[value]["eligible"]
            )
            if ineligible:
                raise AgentPlatformValidationError(
                    f"model binding is not eligible: {', '.join(ineligible)}"
                )
        return self.store.set_binding(
            agent_id,
            model=clean_model,
            shortlist=clean_shortlist,
            routing_preference=routing_preference,
        )

    def preview_configuration(self, agent_id: str) -> dict[str, Any]:
        definition = self.definition(agent_id)
        binding = self.store.get_binding(agent_id)
        if binding is None or not binding["model"]:
            raise AgentConfigError("configure a model binding first")
        return self.config.preview(definition, model=binding["model"])

    def apply_configuration(self, agent_id: str) -> dict[str, Any]:
        definition = self.definition(agent_id)
        binding = self.store.get_binding(agent_id)
        if binding is None or not binding["model"]:
            raise AgentConfigError("configure a model binding first")
        return self.config.apply(definition, model=binding["model"])

    def restore_configuration(self, agent_id: str) -> dict[str, Any]:
        self.definition(agent_id)
        return self.config.restore(agent_id)

    def save_profile(self, name: str) -> dict[str, Any]:
        return self.store.save_profile(name)

    def apply_profile(self, profile_id_or_name: str) -> dict[str, Any]:
        bindings = self.store.apply_profile(profile_id_or_name)
        return {"bindings": bindings}

    def update_plan(self, agent_id: str) -> dict[str, Any]:
        definition = self.definition(agent_id)
        installation = self.store.get_installation(agent_id) or {}
        source = str(installation.get("install_source") or "")
        method = _update_method(installation.get("install_path"), definition.update_plan)
        command = definition.update_plan.get(method) if method else None
        return {
            "agent_id": agent_id,
            "installed": bool(installation.get("installed")),
            "install_source": source or None,
            "update_method": method,
            "command": list(command) if command else None,
            "display_command": shlex.join(command) if command else None,
            "install_hint": definition.install_hint,
            "automatic": command is not None,
        }

    def execute_update(self, agent_id: str) -> dict[str, Any]:
        plan = self.update_plan(agent_id)
        if not plan["command"]:
            raise AgentPlatformValidationError(
                "no safe automatic update command is available"
            )
        result = self._command_runner(list(plan["command"]))
        if result.returncode != 0:
            raise AgentPlatformValidationError(
                f"update command failed with exit code {result.returncode}"
            )
        return {**plan, "status": "ok", "output": str(result.stdout or "")}

    def apply_library_item(self, agent_id: str, item_id: str) -> dict[str, Any]:
        definition = self.definition(agent_id)
        item = self.store.get_library_item(item_id)
        if item is None:
            raise AgentPlatformValidationError("library item not found")
        return self.config.apply_library_item(definition, item)

    def remove_library_item(self, agent_id: str, item_id: str) -> dict[str, Any]:
        definition = self.definition(agent_id)
        return self.config.remove_library_item(definition, item_id)

    def delete_library_item(self, item_id: str) -> bool:
        item = self.store.get_library_item(item_id)
        if item is None:
            return False
        for binding in item.get("bindings", []):
            definition = self._definitions.get(binding["agent_id"])
            if definition is not None:
                self.config.remove_library_item(definition, item_id)
        return self.store.delete_library_item(item_id)


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _platform_name() -> str:
    import sys

    return sys.platform


def _update_method(
    install_path: str | None,
    plans: dict[str, tuple[str, ...]],
) -> str | None:
    path = str(install_path or "").replace("\\", "/").lower()
    if "/cellar/" in path or "/homebrew/" in path:
        candidate = "brew"
    elif "/.local/share/uv/" in path or "/.local/bin/" in path:
        candidate = "uv"
    elif "/node_modules/" in path or "/.npm/" in path or "/npm/" in path:
        candidate = "npm"
    else:
        candidate = next((name for name in ("npm", "brew", "uv") if name in plans), None)
    return candidate if candidate in plans else None
