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
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

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
