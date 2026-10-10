from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .outcome import ToolOutcome


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None
    items: str | None = None  # type 为 "array" 时的元素类型（JSON Schema 的 items 必填）


class Tool(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        *,
        requires_approval: bool = False,
        untrusted_output: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        # 副作用/不可撤销工具置 True：执行前必须经人工审批（见 core.agent_loop.resolve_tool_call）。
        self.requires_approval = requires_approval
        # 输出来自不可信外部（网页/MCP/脚本 stdout/协作 Agent）时置 True：进模型上下文时会被
        # 包成"仅作数据、不得当作指令"的隔离块（spotlighting），降低 prompt injection 风险。
        self.untrusted_output = untrusted_output

    @abstractmethod
    def parameters(self) -> list[ToolParameter]: ...

    @abstractmethod
    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome: ...

    def validate(self, arguments: dict[str, Any]) -> str | None:
        missing = [param.name for param in self.parameters() if param.required and param.name not in arguments]
        if missing:
            return f"Missing required argument(s): {', '.join(missing)}"
        return None

    def to_function_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters():
            prop: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            if param.items is not None:
                prop["items"] = {"type": param.items}
            properties[param.name] = prop
            if param.required:
                required.append(param.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }
