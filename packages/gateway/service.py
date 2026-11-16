"""Gateway request orchestration, routing, and usage logging."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

from gateway.request_log import GatewayRequestLog
from gateway.resolver import ModelResolver
from gateway.inbound_anthropic import (
    anthropic_request_to_chat,
    chat_response_to_anthropic,
)
from gateway.inbound_gemini import (
    chat_response_to_gemini,
    gemini_request_to_chat,
)
from gateway.inbound_responses import (
    chat_response_to_responses,
    responses_request_to_chat,
)
from gateway.streaming import convert_chat_sse
from gateway.upstream import (
    AnthropicUpstream,
    GeminiUpstream,
    GatewayStream,
    MockUpstream,
    OpenAICompatibleUpstream,
    OpenAIResponsesUpstream,
)
from model_platform.control_plane import ControlPlaneStore


class Upstream(Protocol):
    async def complete(self, resolved, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def stream(self, resolved, payload: dict[str, Any]) -> GatewayStream: ...


class GatewayService:
    def __init__(
        self,
        store: ControlPlaneStore,
        *,
        upstreams: dict[str, Upstream] | None = None,
        request_log: GatewayRequestLog | None = None,
    ) -> None:
        self.store = store
        self.resolver = ModelResolver(store)
        self.upstreams = upstreams or {
            "openai-compatible": OpenAICompatibleUpstream(),
            "openai-responses": OpenAIResponsesUpstream(),
            "anthropic": AnthropicUpstream(),
            "gemini": GeminiUpstream(),
            "mock": MockUpstream(),
        }
        self.request_log = request_log or GatewayRequestLog(store.path)

    def models(self) -> list[dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {}
        for model in self.store.list_models():
            public_id = f"{model['provider']}/{model['model_id']}"
            models.setdefault(
                public_id,
                {
                    "id": public_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": model["provider"],
                    "protocol": model["protocol"],
                    "context_window": model["context_window"],
                    "supports_tools": model["supports_tools"],
                    "supports_thinking": model["supports_thinking"],
                },
            )
        return list(models.values())

    async def complete(
        self,
        payload: dict[str, Any],
        *,
        client: str | None,
        protocol: str = "openai-chat",
    ) -> dict[str, Any]:
        started = time.monotonic()
        requested_model = str(payload.get("model") or "")
        canonical = _request_to_chat(payload, protocol)
        logged = self.request_log.start(
            model_requested=requested_model,
            stream=False,
            client=client,
        )
        try:
            resolved = self.resolver.resolve(requested_model)
            upstream = self._upstream(resolved.backend)
            response = await upstream.complete(resolved, canonical)
            response = _response_from_chat(response, protocol, requested_model)
            usage = response.get("usage") or {}
            self.request_log.finish(
                logged["id"],
                status="ok",
                model_resolved=resolved.model_id,
                provider=resolved.provider,
                account_name=resolved.account_name,
                http_status=200,
                duration_ms=int((time.monotonic() - started) * 1000),
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            )
            return response
        except Exception as error:
            self.request_log.finish(
                logged["id"],
                status="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(error),
            )
            raise

    async def stream(
        self,
        payload: dict[str, Any],
        *,
        client: str | None,
        protocol: str = "openai-chat",
    ) -> GatewayStream:
        started = time.monotonic()
        requested_model = str(payload.get("model") or "")
        canonical = _request_to_chat(payload, protocol)
        logged = self.request_log.start(
            model_requested=requested_model,
            stream=True,
            client=client,
        )
        try:
            resolved = self.resolver.resolve(requested_model)
            upstream = self._upstream(resolved.backend)
            stream = await upstream.stream(resolved, canonical)
        except Exception as error:
            self.request_log.finish(
                logged["id"],
                status="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(error),
            )
            raise

        async def upstream_body() -> AsyncIterator[str]:
            status = "ok"
            error_text = None
            try:
                async for chunk in stream.body:
                    yield chunk
            except Exception as error:
                status = "error"
                error_text = str(error)
                raise
            finally:
                self.request_log.finish(
                    logged["id"],
                    status=status,
                    model_resolved=resolved.model_id,
                    provider=resolved.provider,
                    account_name=resolved.account_name,
                    http_status=stream.status_code,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error=error_text,
                )

        body = upstream_body()
        if protocol != "openai-chat":
            body = convert_chat_sse(
                body,
                protocol=protocol,
                requested_model=requested_model,
            )
        return GatewayStream(status_code=stream.status_code, body=body)

    def list_requests(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.request_log.list(limit=limit)

    def _upstream(self, backend: str) -> Upstream:
        upstream = self.upstreams.get(backend)
        if upstream is None:
            from gateway.upstream import GatewayUpstreamError

            raise GatewayUpstreamError(400, f"unsupported backend: {backend}")
        return upstream


def _request_to_chat(payload: dict[str, Any], protocol: str) -> dict[str, Any]:
    if protocol == "openai-chat":
        return payload
    if protocol == "openai-responses":
        return responses_request_to_chat(payload)
    if protocol == "anthropic-messages":
        return anthropic_request_to_chat(payload)
    if protocol == "gemini":
        return gemini_request_to_chat(payload, str(payload["model"]))
    raise ValueError(f"unsupported inbound protocol: {protocol}")


def _response_from_chat(
    response: dict[str, Any],
    protocol: str,
    requested_model: str,
) -> dict[str, Any]:
    if protocol == "openai-chat":
        return response
    if protocol == "openai-responses":
        return chat_response_to_responses(response, requested_model)
    if protocol == "anthropic-messages":
        return chat_response_to_anthropic(response, requested_model)
    if protocol == "gemini":
        return chat_response_to_gemini(response, requested_model)
    raise ValueError(f"unsupported inbound protocol: {protocol}")
