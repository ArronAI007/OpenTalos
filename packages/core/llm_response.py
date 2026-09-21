from dataclasses import asdict, dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMToolResponse:
    content: str | None
    tool_calls: list[ToolCall]
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    reasoning_content: str | None = None

    def __str__(self) -> str:
        return self.content

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StreamStats:
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    reasoning_content: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
