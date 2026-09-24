"""模型调用层：各家厂商的后端适配器（ModelBackend 及其实现）+ 统一门面 ModelClient。

两者永远一起改——加一个 provider 就是"写一个 backend + 在 create_model_backend 里登记"，
所以放同一个文件，调用方只需要认识 ModelClient。
"""

import asyncio
import json
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI

from .errors import SettingsError
from .protocol import Completion, StreamSummary, ToolCompletion, ToolInvocation

DEFAULT_TIMEOUT_SECONDS = 60

# 任何构造 ModelClient 的脚本都经过这个模块，所以在这里统一加载一次 .env 里的模型配置，而不是
# 指望每个脚本自己记得 --env-file/load_dotenv。已存在于进程环境里的变量优先级更高（override
# 默认 False），跟 .env.example 里说的"shell 环境优先"保持一致；.env 不存在时静默跳过。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class ModelBackend(ABC):
    def __init__(self, *, api_key: str, base_url: str | None, timeout: int, model_name: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.model_name = model_name
        self.last_stream_summary: StreamSummary | None = None

    @abstractmethod
    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Completion: ...

    @abstractmethod
    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]: ...

    @abstractmethod
    async def acomplete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> ToolCompletion: ...

    @abstractmethod
    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion: ...


class FakeModelBackend(ModelBackend):
    def __init__(
        self,
        *,
        api_key: str = "mock",
        base_url: str | None = None,
        timeout: int = 60,
        model_name: str = "mock-model",
        response: Completion | None = None,
        responder: Callable[[list[dict]], Completion] | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
        self._response = response
        self._responder = responder

    def _resolve_response(self, messages: list[dict]) -> Completion:
        if self._responder is not None:
            return self._responder(messages)
        if self._response is not None:
            return self._response
        return Completion(text="", model_id=self.model_name)

    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Completion:
        return self._resolve_response(messages)

    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        response = self._resolve_response(messages)
        for char in response.text:
            yield char
        self.last_stream_summary = StreamSummary(
            model_id=response.model_id,
            token_usage=response.token_usage,
            duration_ms=response.duration_ms,
            thinking_trace=response.thinking_trace,
        )

    async def acomplete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> ToolCompletion:
        response = self._resolve_response(messages)
        return ToolCompletion(
            text=response.text,
            requested_tools=[],
            model_id=response.model_id,
            token_usage=response.token_usage,
            duration_ms=response.duration_ms,
        )

    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion:
        response = self._resolve_response(messages)
        if on_text_delta is not None:
            for char in response.text:
                await on_text_delta(char)
        return ToolCompletion(
            text=response.text,
            requested_tools=[],
            model_id=response.model_id,
            token_usage=response.token_usage,
            duration_ms=response.duration_ms,
        )


class OpenAICompatibleBackend(ModelBackend):
    def __init__(self, *, api_key: str, base_url: str | None, timeout: int, model_name: str) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**client_kwargs)

    @staticmethod
    def _extract_usage(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Completion:
        start = time.monotonic()
        response = await self._client.chat.completions.create(model=self.model_name, messages=messages, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        return Completion(
            text=choice.message.content or "",
            model_id=self.model_name,
            token_usage=self._extract_usage(response.usage),
            duration_ms=duration_ms,
            thinking_trace=getattr(choice.message, "reasoning_content", None),
        )

    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        start = time.monotonic()
        stream = await self._client.chat.completions.create(
            model=self.model_name, messages=messages, stream=True, **kwargs
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if content:
                yield content
        self.last_stream_summary = StreamSummary(
            model_id=self.model_name, duration_ms=int((time.monotonic() - start) * 1000)
        )

    async def acomplete_with_tools(
        self, messages: list[dict], tools: list[dict], *, tool_choice: str | dict = "auto", **kwargs: Any
    ) -> ToolCompletion:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self.model_name, messages=messages, tools=tools, tool_choice=tool_choice, **kwargs
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        requested_tools = [
            ToolInvocation(call_id=call.id, tool_name=call.function.name, arguments_json=call.function.arguments)
            for call in (choice.message.tool_calls or [])
        ]
        return ToolCompletion(
            text=choice.message.content,
            requested_tools=requested_tools,
            model_id=self.model_name,
            token_usage=self._extract_usage(response.usage),
            duration_ms=duration_ms,
        )

    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        tool_choice: str | dict = "auto",
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion:
        # 逐 chunk 累积文本增量和按 index 分片的 tool_call 增量（OpenAI 流式协议里，一次 tool_call
        # 的 name/arguments 会拆成多个 delta 陆续吐出，要按 index 拼回一个完整调用）。没有
        # stream_options={"include_usage": True}，因为不是所有 openai-compatible 供应商都支持它；
        # 跟现有的 astream() 一样，流式路径下 token_usage 留空。
        start = time.monotonic()
        stream = await self._client.chat.completions.create(
            model=self.model_name, messages=messages, tools=tools, tool_choice=tool_choice, stream=True, **kwargs
        )
        text_parts: list[str] = []
        pending_calls: dict[int, dict[str, str | None]] = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # 推理模型（kimi-k3 等）先吐 reasoning_content 增量再吐正文——单独通道转出去，
            # 不混进 text_parts（正文要原样拼回，思维链混入会污染最终回复与工具回合上下文）。
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and on_reasoning_delta is not None:
                await on_reasoning_delta(reasoning)
            content = getattr(delta, "content", None)
            if content:
                text_parts.append(content)
                if on_text_delta is not None:
                    await on_text_delta(content)
            for call_delta in getattr(delta, "tool_calls", None) or []:
                entry = pending_calls.setdefault(call_delta.index, {"id": None, "name": None, "arguments": ""})
                if call_delta.id:
                    entry["id"] = call_delta.id
                function = call_delta.function
                if function is not None:
                    if function.name:
                        entry["name"] = function.name
                    if function.arguments:
                        entry["arguments"] = (entry["arguments"] or "") + function.arguments
        duration_ms = int((time.monotonic() - start) * 1000)
        requested_tools = [
            ToolInvocation(
                call_id=pending_calls[index]["id"],
                tool_name=pending_calls[index]["name"],
                arguments_json=pending_calls[index]["arguments"] or "{}",
            )
            for index in sorted(pending_calls)
        ]
        return ToolCompletion(
            text="".join(text_parts) or None,
            requested_tools=requested_tools,
            model_id=self.model_name,
            token_usage={},
            duration_ms=duration_ms,
        )


class ClaudeBackend(ModelBackend):
    def __init__(self, *, api_key: str, base_url: str | None, timeout: int, model_name: str) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
        client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**client_kwargs)

    @staticmethod
    def _extract_system_prompt(messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        rest = [m for m in messages if m["role"] != "system"]
        return ("\n".join(system_parts) if system_parts else None), rest

    @staticmethod
    def _extract_usage(usage: Any) -> dict[str, int]:
        return {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
        }

    @staticmethod
    def _to_backend_tool_choice(tool_choice: str | dict) -> dict:
        if tool_choice == "none":
            return {"type": "none"}
        if tool_choice == "required":
            return {"type": "any"}
        if isinstance(tool_choice, dict):
            return {"type": "tool", "name": tool_choice.get("function", {}).get("name")}
        return {"type": "auto"}

    async def acomplete(self, messages: list[dict], *, max_tokens: int = 4096, **kwargs: Any) -> Completion:
        start = time.monotonic()
        system_prompt, rest = self._extract_system_prompt(messages)
        response = await self._client.messages.create(
            model=self.model_name, max_tokens=max_tokens, system=system_prompt, messages=rest, **kwargs
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text")
        return Completion(
            text=text, model_id=self.model_name, token_usage=self._extract_usage(response.usage), duration_ms=duration_ms
        )

    async def astream(self, messages: list[dict], *, max_tokens: int = 4096, **kwargs: Any) -> AsyncIterator[str]:
        start = time.monotonic()
        system_prompt, rest = self._extract_system_prompt(messages)
        async with self._client.messages.stream(
            model=self.model_name, max_tokens=max_tokens, system=system_prompt, messages=rest, **kwargs
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
        self.last_stream_summary = StreamSummary(
            model_id=self.model_name,
            token_usage=self._extract_usage(final.usage),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def acomplete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 4096,
        tool_choice: str | dict = "auto",
        **kwargs: Any,
    ) -> ToolCompletion:
        start = time.monotonic()
        system_prompt, rest = self._extract_system_prompt(messages)
        response = await self._client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=rest,
            tools=tools,
            tool_choice=self._to_backend_tool_choice(tool_choice),
            **kwargs,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        text = "".join(block.text for block in response.content if block.type == "text") or None
        requested_tools = [
            ToolInvocation(call_id=block.id, tool_name=block.name, arguments_json=json.dumps(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        return ToolCompletion(
            text=text,
            requested_tools=requested_tools,
            model_id=self.model_name,
            token_usage=self._extract_usage(response.usage),
            duration_ms=duration_ms,
        )

    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        max_tokens: int = 4096,
        tool_choice: str | dict = "auto",
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion:
        # Anthropic 的流式 SDK 已经把 tool_use 块的增量 JSON 拼好了，get_final_message() 拿到的
        # （on_reasoning_delta 仅 openai-compatible 推理模型接线；Anthropic 思考块协议不同，暂不转发）
        # content 数组跟非流式 acomplete_with_tools 的响应形状一致，直接复用同一套解析逻辑即可。
        start = time.monotonic()
        system_prompt, rest = self._extract_system_prompt(messages)
        async with self._client.messages.stream(
            model=self.model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=rest,
            tools=tools,
            tool_choice=self._to_backend_tool_choice(tool_choice),
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                if on_text_delta is not None:
                    await on_text_delta(text)
            final = await stream.get_final_message()
        duration_ms = int((time.monotonic() - start) * 1000)
        text = "".join(block.text for block in final.content if block.type == "text") or None
        requested_tools = [
            ToolInvocation(call_id=block.id, tool_name=block.name, arguments_json=json.dumps(block.input))
            for block in final.content
            if block.type == "tool_use"
        ]
        return ToolCompletion(
            text=text,
            requested_tools=requested_tools,
            model_id=self.model_name,
            token_usage=self._extract_usage(final.usage),
            duration_ms=duration_ms,
        )


def create_model_backend(
    provider: str, *, api_key: str, base_url: str | None, timeout: int, model_name: str
) -> ModelBackend:
    if provider == "anthropic":
        return ClaudeBackend(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
    if provider == "openai-compatible":
        return OpenAICompatibleBackend(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
    if provider == "mock":
        return FakeModelBackend(api_key=api_key, base_url=base_url, timeout=timeout, model_name=model_name)
    raise SettingsError(f'Unknown MODEL_PROVIDER "{provider}". Supported: anthropic, openai-compatible, mock.')


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
        reasoning_effort: str | None = None,
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

        # 没显式配置就是 None——请求里干脆不带 temperature，用服务端自己的默认值。框架不替用户
        # 挑一个采样温度：越来越多的模型（o 系列、kimi-k3 等）只接受它们自己的固定值，硬塞一个
        # 会被 400 拒掉。
        temperature_env = os.getenv("MODEL_TEMPERATURE")
        self.temperature = temperature if temperature is not None else (float(temperature_env) if temperature_env else None)
        self.max_tokens = max_tokens

        # 推理强度（kimi-k3 等 always-on thinking 模型用它控制思维链长度）：未配置就不发这个字段，
        # 让服务端用自己的默认档——跟 temperature 同一取舍，框架不替用户挑值。
        self.reasoning_effort = reasoning_effort or os.getenv("MODEL_REASONING_EFFORT") or None

        self._backend: ModelBackend = create_model_backend(
            self.provider, api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, model_name=self.model_name
        )
        self.last_stream_summary: StreamSummary | None = None

    def _build_call_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """把实例上的采样配置和单次调用的覆盖值合成一份请求参数——值为 None 的一律不发。"""
        call_kwargs: dict[str, Any] = {}
        temperature = kwargs.pop("temperature", self.temperature)
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        reasoning_effort = kwargs.pop("reasoning_effort", self.reasoning_effort)
        if reasoning_effort is not None:
            call_kwargs["reasoning_effort"] = reasoning_effort
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

    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str | dict = "auto",
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion:
        call_kwargs = self._build_call_kwargs(kwargs)
        call_kwargs["tool_choice"] = tool_choice
        return await self._backend.astream_with_tools(
            messages, tools, on_text_delta=on_text_delta, on_reasoning_delta=on_reasoning_delta, **call_kwargs
        )

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
