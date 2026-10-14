"""运行时里流动的纯数据类型：对话消息（ChatMessage）和模型响应（Completion 家族）。
都是无行为的数据载体，不含任何模型调用/循环逻辑。
"""

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
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
class BeforeCallResult:
    """`before_tool_call` 钩子的返回值。`block=True` 时这次调用不会真正执行。"""

    block: bool = False
    reason: str | None = None
    terminate: bool = False


@dataclass
class AfterCallResult:
    """`after_tool_call` 钩子的返回值——局部覆写，`None` 字段保留工具原始执行结果。"""

    content: str | None = None
    details: Any = None
    is_error: bool | None = None
    terminate: bool = False


@dataclass
class ToolCompletion:
    text: str | None
    requested_tools: list[ToolInvocation]
    model_id: str
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    # 供应商原始结束原因（OpenAI 的 finish_reason / Anthropic 的 stop_reason）。用于区分
    # "模型自然说完" 与 "撞上 max_tokens 被截断"——后者不能当作完整答案。
    finish_reason: str | None = None
    # 覆盖外层循环默认的"有工具调用就继续、没有就停"调度：None 不覆盖；True 强制再跑一轮（即使
    # 没有工具调用，比如 follow-up 轮询注入了消息，或 finishTurn 钩子返回 "continue"）；False 强
    # 制停止（即使还有工具调用，finishTurn 返回 "end" 时用）。
    should_continue: bool | None = None


# finishTurn 钩子的返回值：None 表示不表态、维持原调度。
TurnDecision = Literal["continue", "end"] | None


@dataclass
class TurnContext:
    """`finish_turn` 钩子能看到的这一轮信息。"""

    step: int
    completion: ToolCompletion
    tool_results: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Completion:
    text: str
    model_id: str
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    thinking_trace: str | None = None
    finish_reason: str | None = None

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
    finish_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class EventKind(Enum):
    """一次运行里能观察到的事件种类（泛化自原来的 AgentPhase 三段式）。"""

    RUN_START = "run_start"
    RUN_END = "run_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    MESSAGE_START = "message_start"
    MESSAGE_UPDATE = "message_update"
    MESSAGE_END = "message_end"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"


@dataclass
class AgentEvent:
    """一次运行里发生的一件具体事情的不可变快照（泛化自原来的 PhaseSignal）。"""

    kind: EventKind
    timestamp: float
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def emit(cls, kind: EventKind, agent_name: str, **data: Any) -> "AgentEvent":
        return cls(kind=kind, timestamp=time.time(), agent_name=agent_name, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "timestamp": self.timestamp, "agent_name": self.agent_name, "data": self.data}
