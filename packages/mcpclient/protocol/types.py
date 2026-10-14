"""MCP 协议专有类型（握手/能力/工具/资源）——对齐 pi `protocol/types.ts` 的字段。"""
from dataclasses import dataclass
from typing import Any

LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = (LATEST_PROTOCOL_VERSION, "2025-06-18", "2025-03-26", "2024-11-05")


@dataclass
class Implementation:
    name: str
    version: str
    title: str | None = None


@dataclass
class Root:
    uri: str
    name: str | None = None


@dataclass
class ClientCapabilities:
    experimental: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None


@dataclass
class ServerCapabilities:
    experimental: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    completions: dict[str, Any] | None = None


@dataclass
class InitializeResult:
    protocol_version: str
    capabilities: ServerCapabilities
    server_info: Implementation
    instructions: str | None = None


@dataclass
class ProgressNotification:
    progress_token: str | int
    progress: float
    total: float | None = None
    message: str | None = None


@dataclass
class ToolAnnotations:
    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None


@dataclass
class ToolExecution:
    task_support: str | None = None  # "forbidden" | "optional" | "required"


@dataclass
class Tool:
    name: str
    input_schema: dict[str, Any]
    title: str | None = None
    description: str | None = None
    output_schema: dict[str, Any] | None = None
    annotations: ToolAnnotations | None = None
    execution: ToolExecution | None = None


@dataclass
class Resource:
    uri: str
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None
    size: int | None = None


@dataclass
class ResourceTemplate:
    uri_template: str
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None


def is_tool(data: dict[str, Any]) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("name"), str)
        and bool(data["name"])
        and isinstance(data.get("inputSchema"), dict)
    )


def is_resource(data: dict[str, Any]) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("uri"), str)
        and bool(data["uri"])
        and isinstance(data.get("name"), str)
        and bool(data["name"])
    )


def is_resource_template(data: dict[str, Any]) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("uriTemplate"), str)
        and bool(data["uriTemplate"])
        and isinstance(data.get("name"), str)
        and bool(data["name"])
    )
