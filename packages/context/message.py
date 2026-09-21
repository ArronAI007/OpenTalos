from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MessageLike(Protocol):
    """context 包不依赖 core.ChatMessage，只要求消息满足这个最小结构。"""

    content: str
    role: str
    timestamp: datetime
    metadata: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]: ...
    def as_text(self) -> str: ...


@dataclass
class Note:
    """TranscriptStore 未注入外部 message_type 时使用的默认消息实现。"""

    content: str
    role: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "role": self.role,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Note":
        timestamp = datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now()
        return cls(content=data["content"], role=data["role"], timestamp=timestamp, metadata=data.get("metadata"))

    def as_text(self) -> str:
        return f"[{self.role}] {self.content}"
