import asyncio
import json

import httpx

from gateway.resolver import ResolvedModel
from gateway.upstream import AnthropicUpstream, MockUpstream, OpenAICompatibleUpstream


def _resolved(backend: str) -> ResolvedModel:
    return ResolvedModel(
        account_id="acct",
        provider="openai" if backend == "openai-compatible" else "anthropic",
        account_name="Primary",
        backend=backend,
        base_url="https://example.test/v1",
        api_key="secret-key",
        proxy_url=None,
        model_id="upstream-model",
        protocol="openai-chat" if backend == "openai-compatible" else "anthropic-messages",
    )


def test_openai_compatible_upstream_rewrites_model_and_preserves_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-key"
        body = json.loads(request.content)
        assert body["model"] == "upstream-model"
        assert body["messages"][0]["content"] == "hello"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "model": "upstream-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "world"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    upstream = OpenAICompatibleUpstream(transport=httpx.MockTransport(handler))
    response = asyncio.run(
        upstream.complete(
            _resolved("openai-compatible"),
            {"model": "public/name", "messages": [{"role": "user", "content": "hello"}]},
        )
    )

    assert response["choices"][0]["message"]["content"] == "world"
    assert response["model"] == "upstream-model"


def test_anthropic_upstream_translates_non_streaming_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/messages"
        body = json.loads(request.content)
        assert body["model"] == "upstream-model"
        assert body["messages"][0]["content"] == "hello"
        return httpx.Response(
            200,
            json={
                "id": "msg-1",
                "content": [{"type": "text", "text": "world"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        )

    upstream = AnthropicUpstream(transport=httpx.MockTransport(handler))
    response = asyncio.run(
        upstream.complete(
            _resolved("anthropic"),
            {"model": "public/claude", "messages": [{"role": "user", "content": "hello"}]},
        )
    )

    assert response["choices"][0]["message"]["content"] == "world"
    assert response["usage"]["total_tokens"] == 5


def test_anthropic_upstream_translates_sse_to_openai_chunks() -> None:
    anthropic_events = [
        ("message_start", {"message": {"id": "msg-1", "usage": {"input_tokens": 2}}}),
        (
            "content_block_delta",
            {
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
        ),
        (
            "message_delta",
            {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
        ),
        ("message_stop", {}),
    ]
    body = "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n"
        for name, data in anthropic_events
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=body))
    upstream = AnthropicUpstream(transport=transport)

    async def collect() -> str:
        stream = await upstream.stream(
            _resolved("anthropic"),
            {"model": "public/claude", "messages": [{"role": "user", "content": "hello"}]},
        )
        parts = [chunk async for chunk in stream.body]
        return "".join(parts)

    rendered = asyncio.run(collect())

    assert '"content":"hello"' in rendered
    assert '"finish_reason":"stop"' in rendered
    assert rendered.endswith("data: [DONE]\n\n")


def test_mock_upstream_supports_completion_and_streaming() -> None:
    resolved = ResolvedModel(
        account_id="mock",
        provider="mock",
        account_name="Mock",
        backend="mock",
        base_url=None,
        api_key="mock",
        proxy_url=None,
        model_id="mock-model",
        protocol="mock",
    )
    upstream = MockUpstream()

    completion = asyncio.run(
        upstream.complete(resolved, {"model": "mock/mock-model", "messages": []})
    )

    async def collect() -> str:
        stream = await upstream.stream(
            resolved,
            {"model": "mock/mock-model", "messages": []},
        )
        return "".join([chunk async for chunk in stream.body])

    assert "mock response" in completion["choices"][0]["message"]["content"]
    rendered = asyncio.run(collect())
    assert '"content":"mock "' in rendered
    assert '"content":"response "' in rendered
