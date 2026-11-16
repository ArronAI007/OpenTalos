"""OpenAI-compatible and Anthropic upstream clients for the gateway."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from gateway.resolver import ResolvedModel
from gateway.inbound_gemini import (
    chat_request_to_gemini,
    gemini_response_to_chat,
    gemini_stream_to_chat,
)
from gateway.inbound_responses import (
    chat_request_to_responses,
    responses_response_to_chat,
)
from gateway.translation import (
    AnthropicStreamTranslator,
    anthropic_to_openai_response,
    openai_to_anthropic_request,
)
from model_platform.presets import get_preset


class GatewayUpstreamError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class GatewayStream:
    status_code: int
    body: AsyncIterator[str]


class MockUpstream:
    async def complete(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"mock response from {resolved.model_id}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def stream(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> GatewayStream:
        text = f"mock response from {resolved.model_id}"

        async def body() -> AsyncIterator[str]:
            for word in text.split():
                chunk = {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "model": payload.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": word + " "},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
            yield "data: [DONE]\n\n"

        return GatewayStream(status_code=200, body=body())


class OpenAICompatibleUpstream:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def complete(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = dict(payload)
        body["model"] = resolved.model_id
        body["stream"] = False
        async with self._client(resolved) as client:
            response = await client.post(
                self._endpoint(resolved),
                json=body,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
            )
        self._raise_for_status(response)
        return response.json()

    async def stream(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> GatewayStream:
        body = dict(payload)
        body["model"] = resolved.model_id
        body["stream"] = True
        client = self._client(resolved)
        response = await client.send(
            client.build_request(
                "POST",
                self._endpoint(resolved),
                json=body,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
            ),
            stream=True,
        )
        if response.status_code >= 400:
            detail = await _response_detail(response)
            await response.aclose()
            await client.aclose()
            raise GatewayUpstreamError(response.status_code, detail)

        async def iterator() -> AsyncIterator[str]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk.decode("utf-8", errors="replace")
            finally:
                await response.aclose()
                await client.aclose()

        return GatewayStream(status_code=response.status_code, body=iterator())

    def _client(self, resolved: ResolvedModel) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": 120,
            "transport": self.transport,
            "trust_env": False,
        }
        if resolved.proxy_url:
            kwargs["proxy"] = resolved.proxy_url
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def _endpoint(resolved: ResolvedModel) -> str:
        preset = get_preset(resolved.provider)
        base = resolved.base_url or (preset.default_base_url if preset else None)
        if not base:
            raise GatewayUpstreamError(
                400,
                f"provider {resolved.provider!r} requires a base_url",
            )
        return f"{base.rstrip('/')}/chat/completions"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                data = response.json()
                detail = (
                    data.get("error", {}).get("message")
                    or data.get("error")
                    or response.text
                )
            except ValueError:
                detail = response.text
            raise GatewayUpstreamError(response.status_code, str(detail))


class AnthropicUpstream(OpenAICompatibleUpstream):
    async def complete(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        translated = openai_to_anthropic_request(payload, resolved.model_id)
        translated["stream"] = False
        async with self._client(resolved) as client:
            response = await client.post(
                self._endpoint(resolved),
                json=translated,
                headers={
                    "x-api-key": resolved.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        self._raise_for_status(response)
        return anthropic_to_openai_response(response.json(), str(payload.get("model")))

    async def stream(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> GatewayStream:
        translated = openai_to_anthropic_request(payload, resolved.model_id)
        translated["stream"] = True
        client = self._client(resolved)
        response = await client.send(
            client.build_request(
                "POST",
                self._endpoint(resolved),
                json=translated,
                headers={
                    "x-api-key": resolved.api_key,
                    "anthropic-version": "2023-06-01",
                },
            ),
            stream=True,
        )
        if response.status_code >= 400:
            detail = await _response_detail(response)
            await response.aclose()
            await client.aclose()
            raise GatewayUpstreamError(response.status_code, detail)
        translator = AnthropicStreamTranslator(str(payload.get("model")))

        async def iterator() -> AsyncIterator[str]:
            try:
                event_type: str | None = None
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    event = json.loads(raw)
                    if event_type and not event.get("type"):
                        event["type"] = event_type
                    for chunk in translator.feed(event):
                        yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await response.aclose()
                await client.aclose()

        return GatewayStream(status_code=response.status_code, body=iterator())

    @staticmethod
    def _endpoint(resolved: ResolvedModel) -> str:
        preset = get_preset(resolved.provider)
        base = resolved.base_url or (preset.default_base_url if preset else None) or "https://api.anthropic.com"
        base = base.rstrip("/")
        return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"


class GeminiUpstream(OpenAICompatibleUpstream):
    async def complete(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        translated = chat_request_to_gemini(payload)
        async with self._client(resolved) as client:
            response = await client.post(self._endpoint(resolved), json=translated)
        self._raise_for_status(response)
        return gemini_response_to_chat(response.json(), str(payload.get("model")))

    async def stream(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> GatewayStream:
        translated = chat_request_to_gemini(payload)
        client = self._client(resolved)
        response = await client.send(
            client.build_request("POST", self._stream_endpoint(resolved), json=translated),
            stream=True,
        )
        if response.status_code >= 400:
            detail = await _response_detail(response)
            await response.aclose()
            await client.aclose()
            raise GatewayUpstreamError(response.status_code, detail)

        async def iterator() -> AsyncIterator[str]:
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    chunk = gemini_stream_to_chat(
                        json.loads(raw),
                        str(payload.get("model")),
                    )
                    yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await response.aclose()
                await client.aclose()

        return GatewayStream(status_code=response.status_code, body=iterator())

    @staticmethod
    def _base(resolved: ResolvedModel) -> str:
        preset = get_preset(resolved.provider)
        base = resolved.base_url or (preset.default_base_url if preset else None)
        if not base:
            raise GatewayUpstreamError(400, "Gemini provider requires a base_url")
        return base.rstrip("/")

    def _endpoint(self, resolved: ResolvedModel) -> str:
        return (
            f"{self._base(resolved)}/models/{resolved.model_id}:generateContent"
            f"?key={resolved.api_key}"
        )

    def _stream_endpoint(self, resolved: ResolvedModel) -> str:
        return (
            f"{self._base(resolved)}/models/{resolved.model_id}:streamGenerateContent"
            f"?alt=sse&key={resolved.api_key}"
        )


class OpenAIResponsesUpstream(OpenAICompatibleUpstream):
    async def complete(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        translated = chat_request_to_responses(payload)
        translated["model"] = resolved.model_id
        translated["stream"] = False
        async with self._client(resolved) as client:
            response = await client.post(
                self._endpoint(resolved),
                json=translated,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
            )
        self._raise_for_status(response)
        return responses_response_to_chat(response.json())

    async def stream(
        self,
        resolved: ResolvedModel,
        payload: dict[str, Any],
    ) -> GatewayStream:
        translated = chat_request_to_responses(payload)
        translated["model"] = resolved.model_id
        translated["stream"] = True
        client = self._client(resolved)
        response = await client.send(
            client.build_request(
                "POST",
                self._endpoint(resolved),
                json=translated,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
            ),
            stream=True,
        )
        if response.status_code >= 400:
            detail = await _response_detail(response)
            await response.aclose()
            await client.aclose()
            raise GatewayUpstreamError(response.status_code, detail)

        async def iterator() -> AsyncIterator[str]:
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    event = json.loads(raw)
                    event_type = event.get("type")
                    delta: dict[str, Any] = {}
                    finish_reason = None
                    if event_type == "response.output_text.delta":
                        delta["content"] = event.get("delta", "")
                    elif event_type == "response.function_call_arguments.delta":
                        delta["tool_calls"] = [
                            {
                                "index": int(event.get("output_index", 0)),
                                "id": event.get("item_id"),
                                "type": "function",
                                "function": {"arguments": event.get("delta", "")},
                            }
                        ]
                    elif event_type == "response.completed":
                        finish_reason = "stop"
                    else:
                        continue
                    chunk = {
                        "id": event.get("response", {}).get("id", "chatcmpl-responses"),
                        "object": "chat.completion.chunk",
                        "model": payload.get("model"),
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": finish_reason,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await response.aclose()
                await client.aclose()

        return GatewayStream(status_code=response.status_code, body=iterator())

    @staticmethod
    def _endpoint(resolved: ResolvedModel) -> str:
        preset = get_preset(resolved.provider)
        base = resolved.base_url or (preset.default_base_url if preset else None)
        if not base:
            raise GatewayUpstreamError(400, "Responses provider requires a base_url")
        return f"{base.rstrip('/')}/responses"


async def _response_detail(response: httpx.Response) -> str:
    body = (await response.aread()).decode("utf-8", errors="replace")
    try:
        data = json.loads(body)
        return str(
            data.get("error", {}).get("message")
            or data.get("error")
            or body
        )
    except ValueError:
        return body
