import asyncio
import json
from pathlib import Path

import pytest

from gateway.middleware import GatewayMiddlewarePipeline
from gateway.request_log import GatewayRequestLog
from gateway.service import GatewayService
from gateway.upstream import GatewayStream, GatewayUpstreamError
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor
from privacy.engine import PrivacyEngine
from privacy.store import PrivacyRule, PrivacyStore


class InspectUpstream:
    def __init__(self) -> None:
        self.payload = None

    async def complete(self, resolved, payload):
        self.payload = payload
        text = payload["messages"][0]["content"]
        token = text.split("email ")[1].split(" ")[0]
        return {
            "id": "chatcmpl-privacy",
            "object": "chat.completion",
            "created": 1,
            "model": resolved.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"sent to {token}",
                        "reasoning_content": token,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "send",
                                    "arguments": json.dumps({"to": token}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def stream(self, resolved, payload):
        self.payload = payload
        token = payload["messages"][0]["content"].split("email ")[1].split(" ")[0]

        async def body():
            event = {
                "choices": [
                    {
                        "delta": {
                            "content": f"sent to {token}",
                            "reasoning_content": token,
                            "tool_calls": [
                                {
                                    "function": {
                                        "arguments": json.dumps({"to": token})
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return GatewayStream(status_code=200, body=body())


class HeaderMiddleware:
    async def before_request(self, payload, context):
        return {**payload, "metadata": {"request_id": context["request_id"]}}

    async def on_event(self, event, context):
        return {**event, "middleware_seen": True}

    async def after_response(self, response, context):
        return {**response, "middleware_seen": True}


def _service(tmp_path: Path, upstream, privacy, *, db_name: str = "gateway.db"):
    store = ControlPlaneStore(tmp_path / db_name)
    account = store.create_account(
        provider="openai",
        name="Work",
        backend="openai-compatible",
        api_key="secret",
    )
    store.replace_models(
        account["id"],
        [
            ModelDescriptor(
                "gpt-5",
                "GPT-5",
                "openai-chat",
                200000,
                True,
                False,
                "provider",
            )
        ],
    )
    service = GatewayService(
        store,
        upstreams={"openai-compatible": upstream},
        request_log=GatewayRequestLog(store.path),
        privacy=privacy,
        middleware=GatewayMiddlewarePipeline([HeaderMiddleware()]),
    )
    return service


def test_gateway_masks_before_upstream_and_restores_complete_response(
    tmp_path: Path,
) -> None:
    upstream = InspectUpstream()
    privacy_store = PrivacyStore(tmp_path / "gateway.db")
    service = _service(
        tmp_path,
        upstream,
        PrivacyEngine(privacy_store),
    )

    response = asyncio.run(
        service.complete(
            {
                "model": "openai/gpt-5",
                "messages": [{"role": "user", "content": "email alice@example.com"}],
            },
            client="test",
            session_key="thread",
        )
    )

    sent = json.dumps(upstream.payload)
    assert "alice@example.com" not in sent
    assert upstream.payload["metadata"]["request_id"]
    message = response["choices"][0]["message"]
    assert message["content"] == "sent to alice@example.com"
    assert message["reasoning_content"] == "alice@example.com"
    assert "alice@example.com" in message["tool_calls"][0]["function"]["arguments"]
    assert response["middleware_seen"] is True


def test_gateway_restores_stream_text_reasoning_and_tool_arguments(
    tmp_path: Path,
) -> None:
    upstream = InspectUpstream()
    service = _service(
        tmp_path,
        upstream,
        PrivacyEngine(PrivacyStore(tmp_path / "gateway.db")),
    )

    async def collect() -> str:
        stream = await service.stream(
            {
                "model": "openai/gpt-5",
                "messages": [{"role": "user", "content": "email alice@example.com"}],
            },
            client="test",
            session_key="stream",
        )
        return "".join([chunk async for chunk in stream.body])

    rendered = asyncio.run(collect())
    assert "alice@example.com" in rendered
    assert "OPENTALOS_" not in rendered
    assert '"middleware_seen":true' in rendered


def test_gateway_fail_closed_and_block_policy_return_gateway_errors(
    tmp_path: Path,
) -> None:
    def broken_rules():
        raise RuntimeError("rules offline")

    unavailable = _service(
        tmp_path,
        InspectUpstream(),
        PrivacyEngine(
            PrivacyStore(tmp_path / "unavailable.db"),
            rule_loader=broken_rules,
        ),
        db_name="unavailable.db",
    )
    with pytest.raises(GatewayUpstreamError) as unavailable_error:
        asyncio.run(
            unavailable.complete(
                {
                    "model": "openai/gpt-5",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                client="test",
            )
        )
    assert unavailable_error.value.status_code == 503

    privacy_store = PrivacyStore(tmp_path / "block.db")
    privacy_store.save_rule(
        PrivacyRule(
            id="block_me",
            title="Block me",
            pattern="DO_NOT_SEND",
            action="block",
        )
    )
    blocked = _service(
        tmp_path,
        InspectUpstream(),
        PrivacyEngine(privacy_store),
        db_name="block.db",
    )
    with pytest.raises(GatewayUpstreamError) as blocked_error:
        asyncio.run(
            blocked.complete(
                {
                    "model": "openai/gpt-5",
                    "messages": [{"role": "user", "content": "DO_NOT_SEND"}],
                },
                client="test",
            )
        )
    assert blocked_error.value.status_code == 451
