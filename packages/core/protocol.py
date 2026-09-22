"""运行时里流动的纯数据类型：对话消息（ChatMessage）和模型响应（Completion 家族）。
都是无行为的数据载体，不含任何模型调用/循环逻辑。
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SpeakerRole = Literal["user", "assistant", "system", "tool", "summary"]


class ChatMessage(BaseModel):
    content: str
    role: SpeakerRole
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatMessage":
        return cls.model_validate(data)

    def as_text(self) -> str:
        return f"[{self.role}] {self.content}"


@dataclass
class ToolInvocation:
    call_id: str
    tool_name: str
    arguments_json: str


@dataclass
class ToolCompletion:
    text: str | None
    requested_tools: list[ToolInvocation]
    model_id: str
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class Completion:
    text: str
    model_id: str
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    thinking_trace: str | None = None

    def __str__(self) -> str:
        return self.text

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StreamSummary:
    model_id: str
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    thinking_trace: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
