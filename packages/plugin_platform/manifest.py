"""Plugin manifest validation and capability allow-list."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ALLOWED_CAPABILITIES = {
    "network",
    "provider.complete",
    "provider.stream",
    "gateway.middleware",
    "ui.page",
    "ui.slot",
    "filesystem.read",
    "filesystem.write",
}


class PluginValidationError(ValueError):
    pass


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    type: str
    runtime: str
    entrypoint: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    ui: dict = Field(default_factory=dict)
    description: str = ""

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in {"provider", "middleware", "tool", "ui"}:
            raise ValueError("type must be provider, middleware, tool, or ui")
        return value

    @field_validator("runtime")
    @classmethod
    def validate_runtime(cls, value: str) -> str:
        if value not in {"bun", "node", "python", "binary"}:
            raise ValueError("runtime must be bun, node, python, or binary")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("entrypoint commands must not be empty")
        for item in value[1:]:
            path = Path(item)
            if ".." in path.parts:
                raise ValueError("entrypoint paths cannot escape the plugin directory")
        return value

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - _ALLOWED_CAPABILITIES)
        if unknown:
            raise ValueError(f"unsupported plugin capability: {', '.join(unknown)}")
        return sorted(set(value))


def validate_manifest(payload: dict) -> PluginManifest:
    try:
        manifest = PluginManifest.model_validate(payload)
    except Exception as error:
        message = str(error)
        if "entrypoint" in message:
            raise PluginValidationError(f"invalid plugin entrypoint: {message}") from error
        if "capability" in message:
            raise PluginValidationError(f"invalid plugin capability: {message}") from error
        raise PluginValidationError(f"invalid plugin manifest: {message}") from error
    if manifest.type == "provider" and not any(
        capability.startswith("provider.") for capability in manifest.capabilities
    ):
        raise PluginValidationError(
            "provider plugins must declare provider.complete or provider.stream"
        )
    if manifest.type == "middleware" and "gateway.middleware" not in manifest.capabilities:
        raise PluginValidationError(
            "middleware plugins must declare gateway.middleware"
        )
    return manifest
