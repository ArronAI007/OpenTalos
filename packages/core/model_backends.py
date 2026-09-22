import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .completion import Completion, StreamSummary, ToolCompletion, ToolInvocation
from .errors import SettingsError


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
        **kwargs: Any,
    ) -> ToolCompletion:
        # Anthropic 的流式 SDK 已经把 tool_use 块的增量 JSON 拼好了，get_final_message() 拿到的
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
