"""Built-in media generation backends."""

from __future__ import annotations

import base64

import httpx

from .service import GeneratedMedia


class OpenAIImageBackend:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-image-1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client

    async def generate(self, prompt: str, *, size: str) -> GeneratedMedia:
        client = self._client or httpx.AsyncClient(timeout=120)
        close = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "prompt": prompt, "size": size},
            )
            response.raise_for_status()
            payload = response.json()
            encoded = payload["data"][0].get("b64_json")
            if encoded:
                data = base64.b64decode(encoded)
            else:
                image_response = await client.get(payload["data"][0]["url"])
                image_response.raise_for_status()
                data = image_response.content
            return GeneratedMedia(
                data=data,
                mime_type="image/png",
                extension="png",
            )
        finally:
            if close:
                await client.aclose()
