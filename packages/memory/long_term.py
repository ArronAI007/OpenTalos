from typing import Protocol, runtime_checkable


@runtime_checkable
class LongTermMemory(Protocol):
    """长期记忆的形状占位——这次不实现、不接入 Agent，留给后续子项目二（embedding+向量检索）
    设计实现。这里的形状不是最终约束，子项目二可以调整。
    """

    async def remember(self, text: str, *, metadata: dict | None = None) -> None: ...
    async def recall(self, query: str, *, limit: int = 5) -> list[str]: ...
