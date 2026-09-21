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
