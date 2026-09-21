class MockProvider:
    async def complete_text(self, system_prompt: str, user_prompt: str) -> str:
        return "memory-service mock response（MODEL_PROVIDER=mock，非合法的 JSON，用于本地无 key 时冒烟测试）"
