from datetime import datetime
from typing import Any

from .message import MessageLike, Note


class TranscriptStore:
    """只追加的对话历史，按“回合”（一条 user 消息 + 后续消息）压缩为摘要。

    message_type 是用来构造/反序列化消息的具体类型（compress 的 summary 消息、restore
    时都靠它），默认是本包自带的 Note；调用方可以传自己的消息类型（比如 core.ChatMessage），
    只要它接受 content/role/metadata 关键字参数并提供 from_dict 类方法即可。
    """

    def __init__(self, min_retain_turns: int = 10, message_type: type[MessageLike] = Note) -> None:
        self.min_retain_turns = min_retain_turns
        self._message_type = message_type
        self._messages: list[MessageLike] = []

    def append(self, message: MessageLike) -> None:
        self._messages.append(message)

    def messages(self) -> list[MessageLike]:
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
        summary_message = self._message_type(
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
        self._messages = [self._message_type.from_dict(message) for message in data.get("messages", [])]
