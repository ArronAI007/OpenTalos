from pathlib import Path

import httpx
import pytest

from gateway.service import GatewayService
from gateway.upstream import GatewayStream
from apps.gateway.main import create_app
from model_platform.control_plane import ControlPlaneStore
from model_platform.discovery import ModelDescriptor


class FakeUpstream:
    async def complete(self, resolved, payload):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"served by {resolved.account_name}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "total_tokens": 7,
            },
        }

    async def stream(self, resolved, payload):
        async def body():
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            yield "data: [DONE]\n\n"

        return GatewayStream(status_code=200, body=body())


@pytest.fixture
async def gateway_api(tmp_path: Path):
    store = ControlPlaneStore(tmp_path / "gateway.db")
    account = store.create_account(
        provider="openai",
        name="Primary",
        backend="openai-compatible",
        base_url="https://example.test/v1",
        api_key="secret",
    )
    store.replace_models(
        account["id"],
        [
            ModelDescriptor(
                "gpt-4o",
                "GPT-4o",
                "openai-chat",
                128000,
                True,
                False,
                "provider",
            )
        ],
    )
    service = GatewayService(
        store,
        upstreams={"openai-compatible": FakeUpstream()},
    )
    app = create_app(service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


async def test_gateway_lists_models(gateway_api) -> None:
    response = await gateway_api.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "openai/gpt-4o"


async def test_gateway_completes_chat_and_logs_request(gateway_api) -> None:
    response = await gateway_api.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "served by Primary"
    logs = (await gateway_api.get("/v1/magpie/requests")).json()["requests"]
    assert logs[0]["status"] == "ok"
    assert logs[0]["total_tokens"] == 7


async def test_gateway_streams_openai_sse(gateway_api) -> None:
    response = await gateway_api.post(
        "/v1/chat/completions",
        json={
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"content":"hello"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")


async def test_gateway_returns_404_for_unknown_model(gateway_api) -> None:
    response = await gateway_api.post(
        "/v1/chat/completions",
        json={
            "model": "missing",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 404
    assert "no enabled account" in response.json()["detail"]
