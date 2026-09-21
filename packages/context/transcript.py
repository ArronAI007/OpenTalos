from datetime import datetime
from typing import Any

from core.chat_message import ChatMessage


class TranscriptStore:
    """只追加的对话历史，按“回合”（一条 user 消息 + 后续消息）压缩为摘要。"""

    def __init__(self, min_retain_turns: int = 10) -> None:
        self.min_retain_turns = min_retain_turns
        self._messages: list[ChatMessage] = []

    def append(self, message: ChatMessage) -> None:
        self._messages.append(message)

    def messages(self) -> list[ChatMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def turn_count(self) -> int:
        return len(self._turn_starts())

    def _turn_starts(self) -> list[int]:
        return [index for index, message in enumerate(self._messages) if message.role == "user"]

    def compress(self, summary: str) -> bool:
        """把 min_retain_turns 之前的回合折叠成一条 summary 消息。

        回合数不足时是 no-op，返回 False。
        """
        starts = self._turn_starts()
        if len(starts) <= self.min_retain_turns:
            return False

        keep_from = starts[-self.min_retain_turns]
        summary_message = ChatMessage(
            content=f"## Archived Session Summary\n{summary}",
            role="summary",
            metadata={"compressed_at": datetime.now().isoformat()},
        )
        self._messages = [summary_message] + self._messages[keep_from:]
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "messages": [message.to_dict() for message in self._messages],
            "saved_at": datetime.now().isoformat(),
            "turns": self.turn_count(),
        }

    def restore(self, data: dict[str, Any]) -> None:
        self._messages = [ChatMessage.from_dict(message) for message in data.get("messages", [])]
