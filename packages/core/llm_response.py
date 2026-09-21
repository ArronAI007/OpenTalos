from dataclasses import dataclass, field


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
        result = {
            "content": self.content,
            "model": self.model,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
        }
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        return result


@dataclass
class StreamStats:
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    reasoning_content: str | None = None

    def to_dict(self) -> dict:
        result = {
            "model": self.model,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
        }
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        return result
