from typing import Protocol


class TextCompletionProvider(Protocol):
    async def complete_text(self, system_prompt: str, user_prompt: str) -> str: ...
