from typing import Protocol, runtime_checkable


@runtime_checkable
class LongTermMemory(Protocol):
    """长期记忆的形状声明——跨会话记住用户的稳定信息（profile/preference/context）。"""

    async def remember(self, text: str, *, metadata: dict | None = None) -> None: ...
    async def recall(self, query: str, *, limit: int = 5) -> list[str]: ...


def _bigrams(text: str) -> set[str]:
    normalized = "".join(ch for ch in text.lower() if not ch.isspace())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def rank_memories(query: str, memories: list[str], limit: int = 5) -> list[str]:
    """按查询与记忆的字符二元组重叠度排序，取前 limit 条（零重叠的不返回）。

    刻意不引入 embedding/向量库：单用户记忆量很小，二元组对中英文都适用（中文无空格分词
    也能命中），命中数即可作为相关性代理。memory 列表按"新在前"传入时，同分者保留新者。
    """
    query_grams = _bigrams(query)
    if not query_grams:
        return []
    scored: list[tuple[int, str]] = []
    for memory in memories:
        overlap = len(query_grams & _bigrams(memory))
        if overlap > 0:
            scored.append((overlap, memory))
    # stable sort：先按命中的二元组数降序，同分保持传入顺序（调用方按 updated_at desc 传入）。
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:limit]]
