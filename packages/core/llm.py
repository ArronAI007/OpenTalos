import asyncio
import os
from typing import Any, AsyncIterator, Iterator

from .exceptions import ConfigError
from .llm_adapters import BaseLLMAdapter, create_adapter
from .llm_response import LLMResponse, LLMToolResponse, StreamStats

DEFAULT_TIMEOUT_SECONDS = 60


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> None:
        self.provider = provider or os.getenv("MODEL_PROVIDER")
        if not self.provider:
            raise ConfigError("必须提供 provider（provider 参数或 MODEL_PROVIDER 环境变量）")

        self.model = model or os.getenv("MODEL_NAME")
        self.api_key = api_key or os.getenv("MODEL_API_KEY")
        if self.provider == "mock":
            self.model = self.model or "mock-model"
            self.api_key = self.api_key or "mock"
        else:
            if not self.model:
                raise ConfigError("必须提供模型名称（model 参数或 MODEL_NAME 环境变量）")
            if not self.api_key:
                raise ConfigError("必须提供 API 密钥（api_key 参数或 MODEL_API_KEY 环境变量）")

        self.base_url = base_url or os.getenv("MODEL_BASE_URL")
        timeout_env = os.getenv("MODEL_TIMEOUT")
        self.timeout = timeout if timeout is not None else (int(timeout_env) if timeout_env else DEFAULT_TIMEOUT_SECONDS)

        self.temperature = temperature
        self.max_tokens = max_tokens

        self._adapter: BaseLLMAdapter = create_adapter(
            self.provider, api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, model=self.model
        )
        self.last_call_stats: StreamStats | None = None

    def _call_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        call_kwargs = {"temperature": kwargs.pop("temperature", self.temperature)}
        if self.max_tokens is not None:
            call_kwargs["max_tokens"] = kwargs.pop("max_tokens", self.max_tokens)
        call_kwargs.update(kwargs)
        return call_kwargs

    async def ainvoke(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        return await self._adapter.ainvoke(messages, **self._call_kwargs(kwargs))

    async def astream_invoke(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        async for chunk in self._adapter.astream_invoke(messages, **self._call_kwargs(kwargs)):
            yield chunk
        self.last_call_stats = self._adapter.last_stats

    async def ainvoke_with_tools(
        self, messages: list[dict], tools: list[dict], tool_choice: str | dict = "auto", **kwargs: Any
    ) -> LLMToolResponse:
        call_kwargs = self._call_kwargs(kwargs)
        call_kwargs["tool_choice"] = tool_choice
        return await self._adapter.ainvoke_with_tools(messages, tools, **call_kwargs)

    def invoke(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        return asyncio.run(self.ainvoke(messages, **kwargs))

    def stream_invoke(self, messages: list[dict], **kwargs: Any) -> Iterator[str]:
        # 便捷同步包装：先在内部事件循环里把整个流收集完，再同步逐个吐出。不是真正的流式，
        # 仅供脚本/测试场景使用；服务代码请用 astream_invoke。
        async def _collect() -> list[str]:
            return [chunk async for chunk in self.astream_invoke(messages, **kwargs)]

        yield from asyncio.run(_collect())

    def invoke_with_tools(
        self, messages: list[dict], tools: list[dict], tool_choice: str | dict = "auto", **kwargs: Any
    ) -> LLMToolResponse:
        return asyncio.run(self.ainvoke_with_tools(messages, tools, tool_choice, **kwargs))
