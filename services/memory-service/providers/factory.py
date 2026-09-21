import os

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from providers.anthropic_provider import AnthropicProvider
from providers.base import TextCompletionProvider
from providers.mock_provider import MockProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_compatible_provider import OpenAICompatibleProvider

CHINESE_PROVIDER_PRESET_BASE_URLS = {
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "kimi": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimax.chat/v1",
}

KNOWN_PROVIDERS = {"anthropic", "openai-compatible", "ollama", "mock", *CHINESE_PROVIDER_PRESET_BASE_URLS}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required for the selected MODEL_PROVIDER")
    return value


async def _real_ollama_post(url: str, json_body: dict[str, object]) -> httpx.Response:
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await client.post(url, json=json_body)


def create_provider_from_env() -> TextCompletionProvider:
    provider_name = _require_env("MODEL_PROVIDER")
    if provider_name not in KNOWN_PROVIDERS:
        raise RuntimeError(
            f'Unknown MODEL_PROVIDER "{provider_name}" — expected one of: {", ".join(sorted(KNOWN_PROVIDERS))}'
        )

    if provider_name == "mock":
        return MockProvider()

    model = _require_env("MODEL_NAME")

    if provider_name == "anthropic":
        api_key = _require_env("MODEL_API_KEY")
        client = AsyncAnthropic(api_key=api_key, base_url=os.environ.get("MODEL_BASE_URL"))
        return AnthropicProvider(client, model=model)

    if provider_name == "ollama":
        base_url = _require_env("MODEL_BASE_URL")
        return OllamaProvider(_real_ollama_post, base_url=base_url, model=model)

    api_key = _require_env("MODEL_API_KEY")
    base_url = os.environ.get("MODEL_BASE_URL") or CHINESE_PROVIDER_PRESET_BASE_URLS.get(provider_name)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return OpenAICompatibleProvider(client, model=model)
