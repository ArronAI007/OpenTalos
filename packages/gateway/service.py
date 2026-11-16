"""Gateway request orchestration, routing, and usage logging."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, Protocol

from gateway.request_log import GatewayRequestLog
from gateway.routing import RoutingEngine
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
        self.upstreams = upstreams or {
            "openai-compatible": OpenAICompatibleUpstream(),
            "openai-responses": OpenAIResponsesUpstream(),
            "anthropic": AnthropicUpstream(),
            "gemini": GeminiUpstream(),
            "mock": MockUpstream(),
        }
        self.request_log = request_log or GatewayRequestLog(store.path)
        self.routing = RoutingEngine(store, request_log=self.request_log)

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
        session_key: str | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        requested_model = str(payload.get("model") or "")
        canonical = _request_to_chat(payload, protocol)
        logged = self.request_log.start(
            model_requested=requested_model,
            stream=False,
            client=client,
        )
        attempts: list[dict[str, Any]] = []
        decision = None
        try:
            decision = self.routing.decide(requested_model, session_key=session_key)
            last_error: Exception | None = None
            for resolved in decision.candidates:
                try:
                    upstream = self._upstream(resolved.backend)
                    response = await upstream.complete(resolved, canonical)
                except Exception as error:
                    attempts.append(_attempt(resolved, error=error))
                    last_error = error
                    if not _retryable(error):
                        raise
                    continue
                response = _response_from_chat(response, protocol, requested_model)
                attempts.append(_attempt(resolved))
                self._remember_session(decision, resolved, session_key)
                self.request_log.set_routing_trace(
                    logged["id"],
                    _routing_trace(decision, attempts, resolved),
                )
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
            if last_error is not None:
                raise last_error
            raise RuntimeError("no routing candidate was available")
        except Exception as error:
            self.request_log.set_routing_trace(
                logged["id"],
                _routing_trace(decision, attempts, None, error),
            )
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
        session_key: str | None = None,
    ) -> GatewayStream:
        started = time.monotonic()
        requested_model = str(payload.get("model") or "")
        canonical = _request_to_chat(payload, protocol)
        logged = self.request_log.start(
            model_requested=requested_model,
            stream=True,
            client=client,
        )
        attempts: list[dict[str, Any]] = []
        decision = None
        try:
            decision = self.routing.decide(requested_model, session_key=session_key)
            stream = None
            resolved = None
            last_error: Exception | None = None
            for candidate in decision.candidates:
                try:
                    upstream = self._upstream(candidate.backend)
                    stream = await upstream.stream(candidate, canonical)
                except Exception as error:
                    attempts.append(_attempt(candidate, error=error))
                    last_error = error
                    if not _retryable(error):
                        raise
                    continue
                resolved = candidate
                attempts.append(_attempt(candidate))
                break
            if stream is None or resolved is None:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("no routing candidate was available")
            self._remember_session(decision, resolved, session_key)
            self.request_log.set_routing_trace(
                logged["id"],
                _routing_trace(decision, attempts, resolved),
            )
        except Exception as error:
            self.request_log.set_routing_trace(
                logged["id"],
                _routing_trace(decision, attempts, None, error),
            )
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

    def usage_summary(self) -> dict[str, Any]:
        return self.request_log.usage_summary()

    def _upstream(self, backend: str) -> Upstream:
        upstream = self.upstreams.get(backend)
        if upstream is None:
            from gateway.upstream import GatewayUpstreamError

            raise GatewayUpstreamError(400, f"unsupported backend: {backend}")
        return upstream

    def _remember_session(self, decision, resolved, session_key: str | None) -> None:
        if not session_key:
            return
        scope = decision.group_name or str(decision.trace["requested_model"])
        self.store.set_session_binding(
            f"{scope}:{session_key}",
            f"{resolved.account_id}:{resolved.model_id}",
        )


def _attempt(resolved, error: Exception | None = None) -> dict[str, Any]:
    attempt = {
        "account_id": resolved.account_id,
        "provider": resolved.provider,
        "account": resolved.account_name,
        "model": resolved.model_id,
        "status": "ok" if error is None else "error",
    }
    if error is not None:
        attempt["error"] = str(error)
        status = getattr(error, "status_code", None)
        if status is not None:
            attempt["status_code"] = status
    return attempt


def _retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    if status is None:
        return True
    return status in {401, 403, 408, 409, 425, 429} or status >= 500


def _routing_trace(decision, attempts, selected, error=None) -> dict[str, Any]:
    if decision is None:
        return {
            "attempts": attempts,
            "selected_account": None,
            "error": str(error) if error else None,
        }
    trace = dict(decision.trace)
    trace.update(
        {
            "attempts": attempts,
            "selected_account": selected.account_name if selected else None,
            "selected_model": selected.model_id if selected else None,
            "error": str(error) if error else None,
        }
    )
    return trace


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
