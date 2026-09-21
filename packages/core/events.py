import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentPhase(Enum):
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass
class PhaseSignal:
    phase: AgentPhase
    timestamp: float
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def emit(cls, phase: AgentPhase, agent_name: str, **data: Any) -> "PhaseSignal":
        return cls(phase=phase, timestamp=time.time(), agent_name=agent_name, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "timestamp": self.timestamp, "agent_name": self.agent_name, "data": self.data}


PhaseCallback = Callable[[PhaseSignal], Awaitable[None]] | None
