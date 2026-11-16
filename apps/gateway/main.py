"""FastAPI entry point for the OpenAI-compatible local gateway."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from apps.runtime_paths import resource_root, user_data_dir

_RESOURCE_ROOT = resource_root()
_DATA_ROOT = user_data_dir()
_PACKAGES_DIR = _RESOURCE_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from gateway.resolver import ModelResolutionError  # noqa: E402
from gateway.routing import RoutingError  # noqa: E402
from gateway.middleware import GatewayMiddlewarePipeline  # noqa: E402
from gateway.service import GatewayService  # noqa: E402
from gateway.upstream import GatewayUpstreamError  # noqa: E402
from gateway_access.store import (  # noqa: E402
    GatewayAccessDeniedError,
    GatewayAccessStore,
)
from model_platform.control_plane import ControlPlaneStore  # noqa: E402
from plugin_platform.middleware import PluginMiddleware  # noqa: E402
from plugin_platform.provider import (  # noqa: E402
    PluginCommandRunner,
    PluginProviderUpstream,
)
from plugin_platform.store import PluginIntegrityError, PluginStore  # noqa: E402
from privacy.engine import PrivacyEngine  # noqa: E402
from privacy.store import PrivacyStore  # noqa: E402


class ChatCompletionBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False


class ResponsesBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    input: str | list[dict[str, Any]]
    stream: bool = False


class AnthropicMessagesBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, Any]] = Field(min_length=1)
    max_tokens: int = Field(default=4096, ge=1)
    stream: bool = False


class GeminiGenerateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    contents: list[dict[str, Any]] = Field(min_length=1)


def create_app(
    service: GatewayService | None = None,
    *,
    access_store: GatewayAccessStore | None = None,
) -> FastAPI:
    database = Path(os.environ.get("OPENTALOS_DB_PATH", _DATA_ROOT / "chat.db"))
    privacy_store = PrivacyStore(database)
    plugin_store = PluginStore(
        Path(os.environ.get("OPENTALOS_PLUGINS_DIR", _DATA_ROOT / "plugins"))
    )
    middleware_plugins = []
    plugin_upstreams = {}
    for plugin in plugin_store.list_plugins(enabled_only=True):
        try:
            plugin_store.verify(plugin["id"])
        except PluginIntegrityError:
            continue
        runner = PluginCommandRunner(plugin_store.root / plugin["id"])
        if plugin["type"] == "middleware":
            middleware_plugins.append(PluginMiddleware(plugin, runner=runner))
        elif plugin["type"] == "provider":
            plugin_upstreams[f"plugin:{plugin['id']}"] = PluginProviderUpstream(
                plugin,
                runner=runner,
            )
    gateway = service or GatewayService(
        ControlPlaneStore(database),
        upstreams=plugin_upstreams,
        privacy=PrivacyEngine(
            privacy_store,
            settings_loader=privacy_store.get_settings,
        ),
        middleware=GatewayMiddlewarePipeline(
            middleware_plugins,
            timeout_seconds=float(os.environ.get("OPENTALOS_PLUGIN_TIMEOUT", "2")),
            fail_open=True,
        ),
    )
    access = access_store or GatewayAccessStore(database)
    app = FastAPI(title="OpenTalos Gateway")
    origins = [
        origin.strip()
        for origin in os.environ.get(
            "GATEWAY_CORS_ORIGINS",
            "http://127.0.0.1:3010,http://localhost:3010",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.gateway = gateway
    app.state.access_store = access
    app.state.privacy_store = privacy_store
    app.state.plugin_store = plugin_store

    def principal(request: Request, scope: str) -> dict[str, Any]:
        authorization = request.headers.get("authorization")
        sharing = access.get_sharing()
        require_key = (
            os.environ.get("OPENTALOS_GATEWAY_REQUIRE_KEY", "0") == "1"
            or sharing["enabled"]
        )
        if authorization:
            current = access.authenticate(authorization)
        elif require_key and not _is_loopback_client(request):
            raise GatewayAccessDeniedError("Gateway key is required")
        else:
            current = access.local_principal()
        access.require(current, scope=scope)
        return current

    def candidate_filter(current: dict[str, Any]):
        return lambda resolved: access.allows_account(
            current,
            account_id=resolved.account_id,
            account_name=resolved.account_name,
            provider=resolved.provider,
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "gateway"}

    @app.get("/v1/models")
    async def models(request: Request) -> dict:
        try:
            principal(request, "models.read")
        except GatewayAccessDeniedError as error:
            raise HTTPException(error.status_code, str(error)) from error
        return {"object": "list", "data": gateway.models()}

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        reservation = None
        try:
            current = principal(request, "chat.read")
            reservation = access.reserve(
                current,
                model=body.model,
            )
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="openai-chat",
                    session_key=session_key,
                    candidate_filter=candidate_filter(current),
                )
                body_iterator = _settled_stream(
                    stream.body,
                    access,
                    reservation,
                )
                return StreamingResponse(
                    body_iterator,
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
            response = await gateway.complete(
                payload,
                client=client,
                protocol="openai-chat",
                session_key=session_key,
                candidate_filter=candidate_filter(current),
            )
            _settle_complete(access, reservation, response)
            return response
        except GatewayAccessDeniedError as error:
            if reservation is not None:
                access.settle(reservation, status="denied")
            raise HTTPException(error.status_code, str(error)) from error
        except ModelResolutionError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(error.status_code, error.detail) from error

    @app.post("/v1/responses")
    async def responses(body: ResponsesBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        reservation = None
        try:
            current = principal(request, "chat.read")
            reservation = access.reserve(current, model=body.model)
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="openai-responses",
                    session_key=session_key,
                    candidate_filter=candidate_filter(current),
                )
                return StreamingResponse(
                    _settled_stream(stream.body, access, reservation),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            response = await gateway.complete(
                payload,
                client=client,
                protocol="openai-responses",
                session_key=session_key,
                candidate_filter=candidate_filter(current),
            )
            _settle_complete(access, reservation, response)
            return response
        except GatewayAccessDeniedError as error:
            if reservation is not None:
                access.settle(reservation, status="denied")
            raise HTTPException(error.status_code, str(error)) from error
        except ModelResolutionError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(error.status_code, error.detail) from error

    @app.post("/v1/messages")
    async def anthropic_messages(body: AnthropicMessagesBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        reservation = None
        try:
            current = principal(request, "chat.read")
            reservation = access.reserve(current, model=body.model)
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="anthropic-messages",
                    session_key=session_key,
                    candidate_filter=candidate_filter(current),
                )
                return StreamingResponse(
                    _settled_stream(stream.body, access, reservation),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            response = await gateway.complete(
                payload,
                client=client,
                protocol="anthropic-messages",
                session_key=session_key,
                candidate_filter=candidate_filter(current),
            )
            _settle_complete(access, reservation, response)
            return response
        except GatewayAccessDeniedError as error:
            if reservation is not None:
                access.settle(reservation, status="denied")
            raise HTTPException(error.status_code, str(error)) from error
        except ModelResolutionError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(error.status_code, error.detail) from error

    @app.post("/v1beta/models/{model_path:path}")
    async def gemini_generate(
        model_path: str,
        body: GeminiGenerateBody,
        request: Request,
    ):
        if model_path.endswith(":streamGenerateContent"):
            model = model_path[: -len(":streamGenerateContent")]
            stream_request = True
        elif model_path.endswith(":generateContent"):
            model = model_path[: -len(":generateContent")]
            stream_request = False
        else:
            raise HTTPException(404, "unknown Gemini endpoint")
        payload = body.model_dump(exclude_none=True)
        payload["model"] = model
        payload["stream"] = stream_request
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        reservation = None
        try:
            current = principal(request, "chat.read")
            reservation = access.reserve(current, model=model)
            if stream_request:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="gemini",
                    session_key=session_key,
                    candidate_filter=candidate_filter(current),
                )
                return StreamingResponse(
                    _settled_stream(stream.body, access, reservation),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            response = await gateway.complete(
                payload,
                client=client,
                protocol="gemini",
                session_key=session_key,
                candidate_filter=candidate_filter(current),
            )
            _settle_complete(access, reservation, response)
            return response
        except GatewayAccessDeniedError as error:
            if reservation is not None:
                access.settle(reservation, status="denied")
            raise HTTPException(error.status_code, str(error)) from error
        except ModelResolutionError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            if reservation is not None:
                access.settle(reservation, status="error")
            raise HTTPException(error.status_code, error.detail) from error

    @app.get("/v1/magpie/requests")
    async def requests(limit: int = 50) -> dict:
        return {"requests": gateway.list_requests(limit=limit)}

    @app.get("/v1/magpie/usage")
    async def usage() -> dict:
        return gateway.usage_summary()

    return app


def _session_key(request: Request) -> str | None:
    return (
        request.headers.get("x-magpie-session")
        or request.headers.get("x-session-id")
    )


def _is_loopback_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _settle_complete(
    access: GatewayAccessStore,
    reservation: dict[str, Any],
    response: dict[str, Any],
) -> None:
    usage = response.get("usage") or {}
    access.settle(
        reservation,
        status="ok",
        input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        output_tokens=int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        ),
    )


async def _settled_stream(
    source,
    access: GatewayAccessStore,
    reservation: dict[str, Any],
):
    status = "ok"
    try:
        async for chunk in source:
            yield chunk
    except Exception:
        status = "error"
        raise
    finally:
        access.settle(reservation, status=status)


app = create_app()
