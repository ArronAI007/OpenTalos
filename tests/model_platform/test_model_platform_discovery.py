import asyncio

import httpx

from model_platform.discovery import ModelDiscovery


def test_openai_compatible_discovery_parses_models_and_auth() -> None:
    received_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers.update(request.headers)
        assert request.url == "https://example.test/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "model-a"},
                    {"id": "gpt-4o"},
                ]
            },
        )

    discovery = ModelDiscovery()
    models = asyncio.run(
        discovery.discover(
            {
                "backend": "openai-compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-test",
            },
            transport=httpx.MockTransport(handler),
        )
    )

    assert received_headers["authorization"] == "Bearer sk-test"
    assert [model.model_id for model in models] == ["model-a", "gpt-4o"]
    assert models[1].context_window == 128000


def test_anthropic_discovery_uses_messages_headers_and_models_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.anthropic.com/v1/models"
        assert request.headers["x-api-key"] == "anthropic-key"
        assert request.headers["anthropic-version"]
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})

    models = asyncio.run(
        ModelDiscovery().discover(
            {
                "backend": "anthropic",
                "base_url": None,
                "api_key": "anthropic-key",
            },
            transport=httpx.MockTransport(handler),
        )
    )

    assert [model.model_id for model in models] == ["claude-sonnet-5"]
    assert models[0].supports_thinking is True


def test_discovery_rejects_provider_errors() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"error": {"message": "bad key"}})
    )

    try:
        asyncio.run(
            ModelDiscovery().discover(
                {
                    "backend": "openai-compatible",
                    "base_url": "https://example.test/v1",
                    "api_key": "bad",
                },
                transport=transport,
            )
        )
    except RuntimeError as error:
        assert "401" in str(error)
        assert "bad key" in str(error)
    else:
        raise AssertionError("discovery should fail")
