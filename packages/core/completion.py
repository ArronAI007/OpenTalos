from dataclasses import asdict, dataclass, field


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
