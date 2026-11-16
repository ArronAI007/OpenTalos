import asyncio
import json

import httpx

from gateway.resolver import ResolvedModel
from gateway.upstream import GeminiUpstream, OpenAIResponsesUpstream


def test_gemini_upstream_complete_and_stream() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if ":streamGenerateContent" in request.url.path:
            body = (
                'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}\n\n'
                'data: {"candidates":[{"content":{"parts":[]},"finishReason":"STOP"}]}\n\n'
            )
            return httpx.Response(200, text=body)
        payload = json.loads(request.content)
        assert payload["contents"][0]["parts"][0]["text"] == "hello"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "world"},
                                {
                                    "functionCall": {
                                        "name": "read_file",
                                        "args": {"path": "README.md"},
                                    }
                                },
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 2,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 5,
                },
            },
        )

    resolved = ResolvedModel(
        account_id="acct",
        provider="google-gemini-native",
        account_name="Gemini",
        backend="gemini",
        base_url="https://example.test/v1beta",
        api_key="secret",
        proxy_url=None,
        model_id="gemini-test",
        protocol="gemini",
    )
    upstream = GeminiUpstream(transport=httpx.MockTransport(handler))
    response = asyncio.run(
        upstream.complete(
            resolved,
            {"model": "google/gemini", "messages": [{"role": "user", "content": "hello"}]},
        )
    )

    assert response["choices"][0]["message"]["content"] == "world"
    assert response["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "read_file"
    assert response["usage"]["total_tokens"] == 5
    assert "key=secret" in calls[0]

    async def collect() -> str:
        stream = await upstream.stream(
            resolved,
            {"model": "google/gemini", "messages": [{"role": "user", "content": "hello"}]},
        )
        return "".join([chunk async for chunk in stream.body])

    rendered = asyncio.run(collect())
    assert '"content":"hello"' in rendered
    assert rendered.endswith("data: [DONE]\n\n")


def test_openai_responses_upstream_translates_to_chat() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == "gpt-5"
        assert body["instructions"] == "Be brief"
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "status": "completed",
                "model": "gpt-5",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "world"}],
                    }
                ],
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "total_tokens": 5,
                },
            },
        )

    resolved = ResolvedModel(
        account_id="acct",
        provider="openai",
        account_name="OpenAI",
        backend="openai-responses",
        base_url="https://example.test/v1",
        api_key="secret",
        proxy_url=None,
        model_id="gpt-5",
        protocol="openai-responses",
    )
    upstream = OpenAIResponsesUpstream(transport=httpx.MockTransport(handler))
    response = asyncio.run(
        upstream.complete(
            resolved,
            {
                "model": "openai/gpt-5",
                "messages": [
                    {"role": "system", "content": "Be brief"},
                    {"role": "user", "content": "hello"},
                ],
            },
        )
    )

    assert response["choices"][0]["message"]["content"] == "world"
    assert response["usage"]["total_tokens"] == 5


def test_openai_responses_upstream_stream_translates_to_chat_sse() -> None:
    body = (
        "event: response.output_text.delta\n"
        'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
        "event: response.completed\n"
        'data: {"type":"response.completed","response":{"id":"resp_1"}}\n\n'
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=body))
    resolved = ResolvedModel(
        account_id="acct",
        provider="openai-responses",
        account_name="OpenAI",
        backend="openai-responses",
        base_url="https://example.test/v1",
        api_key="secret",
        proxy_url=None,
        model_id="gpt-5",
        protocol="openai-responses",
    )

    async def collect() -> str:
        stream = await OpenAIResponsesUpstream(transport=transport).stream(
            resolved,
            {"model": "openai/gpt-5", "messages": [{"role": "user", "content": "hello"}]},
        )
        return "".join([chunk async for chunk in stream.body])

    rendered = asyncio.run(collect())
    assert '"content":"hello"' in rendered
    assert '"finish_reason":"stop"' in rendered
    assert rendered.endswith("data: [DONE]\n\n")
