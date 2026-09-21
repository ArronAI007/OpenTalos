from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, AsyncIterator

from .exceptions import ConfigError
from .llm_response import LLMResponse, LLMToolResponse, StreamStats


class BaseLLMAdapter(ABC):
    def __init__(self, *, api_key: str, base_url: str | None, timeout: int, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.model = model
        self.last_stats: StreamStats | None = None

    @abstractmethod
    async def ainvoke(self, messages: list[dict], **kwargs: Any) -> LLMResponse: ...

    @abstractmethod
    async def astream_invoke(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]: ...

    @abstractmethod
    async def ainvoke_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> LLMToolResponse: ...


class MockAdapter(BaseLLMAdapter):
    def __init__(
        self,
        *,
        api_key: str = "mock",
        base_url: str | None = None,
        timeout: int = 60,
        model: str = "mock-model",
        response: LLMResponse | None = None,
        responder: Callable[[list[dict]], LLMResponse] | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, model=model)
        self._response = response
        self._responder = responder

    def _resolve_response(self, messages: list[dict]) -> LLMResponse:
        if self._responder is not None:
            return self._responder(messages)
        if self._response is not None:
            return self._response
        return LLMResponse(content="", model=self.model)

    async def ainvoke(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        return self._resolve_response(messages)

    async def astream_invoke(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        response = self._resolve_response(messages)
        for char in response.content:
            yield char
        self.last_stats = StreamStats(
            model=response.model,
            usage=response.usage,
            latency_ms=response.latency_ms,
            reasoning_content=response.reasoning_content,
        )

    async def ainvoke_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> LLMToolResponse:
        response = self._resolve_response(messages)
        return LLMToolResponse(
            content=response.content,
            tool_calls=[],
            model=response.model,
            usage=response.usage,
            latency_ms=response.latency_ms,
        )


def create_adapter(provider: str, *, api_key: str, base_url: str | None, timeout: int, model: str) -> BaseLLMAdapter:
    if provider == "mock":
        return MockAdapter(api_key=api_key, base_url=base_url, timeout=timeout, model=model)
    raise ConfigError(f'Unknown MODEL_PROVIDER "{provider}". Supported: anthropic, openai-compatible, mock.')
