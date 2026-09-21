import asyncio
import os
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from dotenv import load_dotenv

from .completion import Completion, StreamSummary, ToolCompletion
from .errors import SettingsError
from .model_backends import ModelBackend, create_model_backend

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TEMPERATURE = 0.7

# 任何构造 ModelClient 的脚本都经过这个模块，所以在这里统一加载一次 .env 里的模型配置，而不是
# 指望每个脚本自己记得 --env-file/load_dotenv。已存在于进程环境里的变量优先级更高（override
# 默认 False），跟 .env.example 里说的"shell 环境优先"保持一致；.env 不存在时静默跳过。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class ModelClient:
    def __init__(
        self,
        model_name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.provider = provider or os.getenv("MODEL_PROVIDER")
        if not self.provider:
            raise SettingsError("必须提供 provider（provider 参数或 MODEL_PROVIDER 环境变量）")

        self.model_name = model_name or os.getenv("MODEL_NAME")
        self.api_key = api_key or os.getenv("MODEL_API_KEY")
        if self.provider == "mock":
            self.model_name = self.model_name or "mock-model"
            self.api_key = self.api_key or "mock"
        else:
            if not self.model_name:
                raise SettingsError("必须提供模型名称（model_name 参数或 MODEL_NAME 环境变量）")
            if not self.api_key:
                raise SettingsError("必须提供 API 密钥（api_key 参数或 MODEL_API_KEY 环境变量）")

        self.base_url = base_url or os.getenv("MODEL_BASE_URL")
        timeout_env = os.getenv("MODEL_TIMEOUT")
        self.timeout = timeout if timeout is not None else (int(timeout_env) if timeout_env else DEFAULT_TIMEOUT_SECONDS)

        temperature_env = os.getenv("MODEL_TEMPERATURE")
        self.temperature = (
            temperature if temperature is not None else (float(temperature_env) if temperature_env else DEFAULT_TEMPERATURE)
        )
        self.max_tokens = max_tokens

        self._backend: ModelBackend = create_model_backend(
            self.provider, api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, model_name=self.model_name
        )
        self.last_stream_summary: StreamSummary | None = None

    def _build_call_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        call_kwargs = {"temperature": kwargs.pop("temperature", self.temperature)}
        if self.max_tokens is not None:
            call_kwargs["max_tokens"] = kwargs.pop("max_tokens", self.max_tokens)
        call_kwargs.update(kwargs)
        return call_kwargs

    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Completion:
        return await self._backend.acomplete(messages, **self._build_call_kwargs(kwargs))

    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        async for chunk in self._backend.astream(messages, **self._build_call_kwargs(kwargs)):
            yield chunk
        self.last_stream_summary = self._backend.last_stream_summary

    async def acomplete_with_tools(
        self, messages: list[dict], tools: list[dict], tool_choice: str | dict = "auto", **kwargs: Any
    ) -> ToolCompletion:
        call_kwargs = self._build_call_kwargs(kwargs)
        call_kwargs["tool_choice"] = tool_choice
        return await self._backend.acomplete_with_tools(messages, tools, **call_kwargs)

    def complete(self, messages: list[dict], **kwargs: Any) -> Completion:
        return asyncio.run(self.acomplete(messages, **kwargs))

    def stream(self, messages: list[dict], **kwargs: Any) -> Iterator[str]:
        # 便捷同步包装：先在内部事件循环里把整个流收集完，再同步逐个吐出。不是真正的流式，
        # 仅供脚本/测试场景使用；服务代码请用 astream。
        async def _collect() -> list[str]:
            return [chunk async for chunk in self.astream(messages, **kwargs)]

        yield from asyncio.run(_collect())

    def complete_with_tools(
        self, messages: list[dict], tools: list[dict], tool_choice: str | dict = "auto", **kwargs: Any
    ) -> ToolCompletion:
        return asyncio.run(self.acomplete_with_tools(messages, tools, tool_choice, **kwargs))
