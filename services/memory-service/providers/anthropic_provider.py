from typing import Any


class AnthropicProvider:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
