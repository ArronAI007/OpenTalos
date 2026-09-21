from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

MessageRole = Literal["user", "assistant", "system", "tool", "summary"]


class Message(BaseModel):
    content: str
    role: MessageRole
    timestamp: datetime
    metadata: dict[str, Any] | None = None

    def __init__(self, content: str, role: MessageRole, **kwargs: Any) -> None:
        super().__init__(
            content=content,
            role=role,
            timestamp=kwargs.get("timestamp") or datetime.now(),
            metadata=kwargs.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return cls(content=data["content"], role=data["role"], timestamp=timestamp, metadata=data.get("metadata"))

    def to_text(self) -> str:
        return f"[{self.role}] {self.content}"
