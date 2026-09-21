import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    AGENT_START = "agent_start"
    AGENT_FINISH = "agent_finish"
    AGENT_ERROR = "agent_error"


@dataclass
class AgentEvent:
    type: EventType
    timestamp: float
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, event_type: EventType, agent_name: str, **data: Any) -> "AgentEvent":
        return cls(type=event_type, timestamp=time.time(), agent_name=agent_name, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "timestamp": self.timestamp, "agent_name": self.agent_name, "data": self.data}


LifecycleHook = Callable[[AgentEvent], Awaitable[None]] | None
