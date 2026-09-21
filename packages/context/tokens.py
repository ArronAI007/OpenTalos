import tiktoken

from core.chat_message import ChatMessage

_FALLBACK_ENCODING = "cl100k_base"
_ROLE_OVERHEAD_TOKENS = 4  # chat 模板给每条消息加的角色/分隔符开销的粗略估算


class TokenBudget:
    """本地 token 估算，带按消息缓存；不可用 tiktoken 时退化为字符数估算。"""

    def __init__(self, model: str = "gpt-4") -> None:
        self.model = model
        self._encoding = self._resolve_encoding()
        self._cache: dict[str, int] = {}

    def _resolve_encoding(self):
        try:
            return tiktoken.encoding_for_model(self.model)
        except KeyError:
            try:
                return tiktoken.get_encoding(_FALLBACK_ENCODING)
            except Exception:
                return None
        except Exception:
            return None

    def estimate_text(self, text: str) -> int:
        if self._encoding is None:
            return len(text) // 4
        try:
            return len(self._encoding.encode(text))
        except Exception:
            return len(text) // 4

    def estimate_message(self, message: ChatMessage) -> int:
        cache_key = f"{message.role}:{message.content}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        tokens = self.estimate_text(message.content) + _ROLE_OVERHEAD_TOKENS
        self._cache[cache_key] = tokens
        return tokens

    def estimate_messages(self, messages: list[ChatMessage]) -> int:
        return sum(self.estimate_message(message) for message in messages)

    def reset_cache(self) -> None:
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def cache_stats(self) -> dict[str, int]:
        return {
            "cached_messages": len(self._cache),
            "total_cached_tokens": sum(self._cache.values()),
        }
