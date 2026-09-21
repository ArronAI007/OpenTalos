from typing import Awaitable, Callable

import httpx

PostFn = Callable[[str, dict[str, object]], Awaitable[httpx.Response]]


class OllamaProvider:
    def __init__(self, post_fn: PostFn, base_url: str, model: str) -> None:
        self._post_fn = post_fn
        self._base_url = base_url
        self._model = model

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._post_fn(
            f"{self._base_url}/api/chat",
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
