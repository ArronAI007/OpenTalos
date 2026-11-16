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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES_DIR = _REPO_ROOT / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from gateway.resolver import ModelResolutionError  # noqa: E402
from gateway.routing import RoutingError  # noqa: E402
from gateway.service import GatewayService  # noqa: E402
from gateway.upstream import GatewayUpstreamError  # noqa: E402
from model_platform.control_plane import ControlPlaneStore  # noqa: E402


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


def create_app(service: GatewayService | None = None) -> FastAPI:
    database = Path(os.environ.get("OPENTALOS_DB_PATH", _REPO_ROOT / ".data" / "chat.db"))
    gateway = service or GatewayService(ControlPlaneStore(database))
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

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "gateway"}

    @app.get("/v1/models")
    async def models() -> dict:
        return {"object": "list", "data": gateway.models()}

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        try:
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="openai-chat",
                    session_key=session_key,
                )
                return StreamingResponse(
                    stream.body,
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
            return await gateway.complete(
                payload,
                client=client,
                protocol="openai-chat",
                session_key=session_key,
            )
        except ModelResolutionError as error:
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            raise HTTPException(error.status_code, error.detail) from error

    @app.post("/v1/responses")
    async def responses(body: ResponsesBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        try:
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="openai-responses",
                    session_key=session_key,
                )
                return StreamingResponse(
                    stream.body,
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            return await gateway.complete(
                payload,
                client=client,
                protocol="openai-responses",
                session_key=session_key,
            )
        except ModelResolutionError as error:
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
            raise HTTPException(error.status_code, error.detail) from error

    @app.post("/v1/messages")
    async def anthropic_messages(body: AnthropicMessagesBody, request: Request):
        payload = body.model_dump(exclude_none=True)
        client = request.client.host if request.client else None
        session_key = _session_key(request)
        try:
            if body.stream:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="anthropic-messages",
                    session_key=session_key,
                )
                return StreamingResponse(
                    stream.body,
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            return await gateway.complete(
                payload,
                client=client,
                protocol="anthropic-messages",
                session_key=session_key,
            )
        except ModelResolutionError as error:
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
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
        try:
            if stream_request:
                stream = await gateway.stream(
                    payload,
                    client=client,
                    protocol="gemini",
                    session_key=session_key,
                )
                return StreamingResponse(
                    stream.body,
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            return await gateway.complete(
                payload,
                client=client,
                protocol="gemini",
                session_key=session_key,
            )
        except ModelResolutionError as error:
            raise HTTPException(404, str(error)) from error
        except RoutingError as error:
            raise HTTPException(404, str(error)) from error
        except GatewayUpstreamError as error:
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


app = create_app()
