import asyncio
from pathlib import Path

import pytest

from gateway.request_log import GatewayRequestLog
from gateway.service import GatewayService
from gateway.upstream import GatewayStream, GatewayUpstreamError
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor


class FailThenSucceedUpstream:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, resolved, payload):
        self.calls += 1
        if self.calls == 1:
            raise GatewayUpstreamError(429, "quota exhausted")
        return _completion(resolved.account_name)

    async def stream(self, resolved, payload):
        self.calls += 1
        if self.calls == 1:
            raise GatewayUpstreamError(429, "quota exhausted")

        async def body():
            yield 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            yield "data: [DONE]\n\n"

        return GatewayStream(status_code=200, body=body())


class BadRequestUpstream:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, resolved, payload):
        self.calls += 1
        raise GatewayUpstreamError(400, "bad request")

    async def stream(self, resolved, payload):
        self.calls += 1
        raise GatewayUpstreamError(400, "bad request")


def _setup(tmp_path: Path):
    store = ControlPlaneStore(tmp_path / "failover.db")
    for name in ("Primary", "Backup"):
        account = store.create_account(
            provider="openai",
            name=name,
            backend="openai-compatible",
            base_url="https://example.test/v1",
            api_key=f"{name}-key",
        )
        store.replace_models(
            account["id"],
            [
                ModelDescriptor(
                    "gpt-4o",
                    "GPT-4o",
                    "openai-chat",
                    None,
                    True,
                    False,
                    "provider",
                )
            ],
        )
    store.create_routing_group(
        name="failover",
        mode="order",
        members=[
            {"target": "openai/Primary/gpt-4o"},
            {"target": "openai/Backup/gpt-4o"},
        ],
    )
    return store


def test_complete_fails_over_retryable_errors_and_records_trace(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    upstream = FailThenSucceedUpstream()
    service = GatewayService(
        store,
        upstreams={"openai-compatible": upstream},
        request_log=GatewayRequestLog(store.path),
    )

    response = asyncio.run(
        service.complete(
            {
                "model": "group/failover",
                "messages": [{"role": "user", "content": "hello"}],
            },
            client="test",
            session_key="thread",
        )
    )

    assert response["choices"][0]["message"]["content"] == "served by Backup"
    assert upstream.calls == 2
    request = service.list_requests()[0]
    assert request["account_name"] == "Backup"
    assert request["routing_trace"]["attempts"][0]["status_code"] == 429
    assert request["routing_trace"]["selected_account"] == "Backup"
    assert store.get_session_binding("failover:thread").endswith(":gpt-4o")


def test_stream_fails_over_before_sending_bytes(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    upstream = FailThenSucceedUpstream()
    service = GatewayService(
        store,
        upstreams={"openai-compatible": upstream},
        request_log=GatewayRequestLog(store.path),
    )

    async def collect() -> str:
        result = await service.stream(
            {"model": "group/failover", "messages": [{"role": "user", "content": "hi"}]},
            client="test",
            session_key="thread-2",
        )
        return "".join([chunk async for chunk in result.body])

    rendered = asyncio.run(collect())
    assert "ok" in rendered
    assert service.list_requests()[0]["status"] == "ok"


def test_non_retryable_400_does_not_try_next_candidate(tmp_path: Path) -> None:
    store = _setup(tmp_path)
    upstream = BadRequestUpstream()
    service = GatewayService(
        store,
        upstreams={"openai-compatible": upstream},
        request_log=GatewayRequestLog(store.path),
    )

    with pytest.raises(GatewayUpstreamError):
        asyncio.run(
            service.complete(
                {"model": "group/failover", "messages": [{"role": "user", "content": "hi"}]},
                client="test",
            )
        )
    assert upstream.calls == 1


def _completion(account_name: str) -> dict:
    return {
        "id": "chatcmpl-failover",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"served by {account_name}",
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
