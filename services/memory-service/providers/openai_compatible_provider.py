from typing import Any


class OpenAICompatibleProvider:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
