import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .exceptions import ConfigError
from .llm_response import LLMResponse, LLMToolResponse, StreamStats, ToolCall


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


class OpenAICompatibleAdapter(BaseLLMAdapter):
    def __init__(self, *, api_key: str, base_url: str | None, timeout: int, model: str) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, model=model)
        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**client_kwargs)

    @staticmethod
    def _usage_dict(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    async def ainvoke(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        start = time.monotonic()
        response = await self._client.chat.completions.create(model=self.model, messages=messages, **kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=self.model,
            usage=self._usage_dict(response.usage),
            latency_ms=latency_ms,
            reasoning_content=getattr(choice.message, "reasoning_content", None),
        )

    async def astream_invoke(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        start = time.monotonic()
        stream = await self._client.chat.completions.create(model=self.model, messages=messages, stream=True, **kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if content:
                yield content
        self.last_stats = StreamStats(model=self.model, latency_ms=int((time.monotonic() - start) * 1000))

    async def ainvoke_with_tools(
        self, messages: list[dict], tools: list[dict], *, tool_choice: str | dict = "auto", **kwargs: Any
    ) -> LLMToolResponse:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, tool_choice=tool_choice, **kwargs
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        tool_calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
            for call in (choice.message.tool_calls or [])
        ]
        return LLMToolResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            model=self.model,
            usage=self._usage_dict(response.usage),
            latency_ms=latency_ms,
        )


def create_adapter(provider: str, *, api_key: str, base_url: str | None, timeout: int, model: str) -> BaseLLMAdapter:
    if provider == "openai-compatible":
        return OpenAICompatibleAdapter(api_key=api_key, base_url=base_url, timeout=timeout, model=model)
    if provider == "mock":
        return MockAdapter(api_key=api_key, base_url=base_url, timeout=timeout, model=model)
    raise ConfigError(f'Unknown MODEL_PROVIDER "{provider}". Supported: anthropic, openai-compatible, mock.')
