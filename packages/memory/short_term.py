from typing import Any

from context import AssemblyConfig, ContextAssembler, MessageLike, Note, TokenBudget, TranscriptStore


def seed_messages(system_prompt: str | None, history: list[Any], user_text: str) -> list[dict[str, Any]]:
    """把 system_prompt + 历史 + 本轮 user_text 组装成合法的、OpenAI 兼容的 messages 列表。

    tool 角色的历史消息还原成 assistant(tool_calls) + tool(tool_call_id) 两条；summary 角色
    （压缩折叠产生的摘要）派生成带前缀的 system 消息，因为 summary 不是 OpenAI 兼容 role。
    """
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for message in history:
        if message.role == "tool":
            meta = message.metadata or {}
            call_id = meta.get("tool_call_id", "")
            tool_name = meta.get("tool_name", "")
            arguments = meta.get("arguments", "{}")
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": tool_name, "arguments": arguments}}
                ],
            })
            messages.append({"role": "tool", "tool_call_id": call_id, "content": message.content})
        elif message.role == "summary":
            messages.append({"role": "system", "content": f"## Archived Session Summary\n{message.content}"})
        else:
            messages.append({"role": message.role, "content": message.content})
    messages.append({"role": "user", "content": user_text})
    return messages


class ShortTermMemory:
    """短期记忆：包一层 TranscriptStore（只追加的回合记录）+ ContextAssembler（按轮次截断），
    对外暴露一个"把当前历史+本轮输入组装成合法 messages 列表"的 build_messages。
    """

    def __init__(
        self,
        min_retain_turns: int = 10,
        message_type: type[MessageLike] = Note,
        context_config: AssemblyConfig | None = None,
        token_budget: TokenBudget | None = None,
    ) -> None:
        self._transcript = TranscriptStore(min_retain_turns=min_retain_turns, message_type=message_type)
        self._config = context_config or AssemblyConfig()
        self.assembler = ContextAssembler(self._config, token_budget)

    def append(self, message: MessageLike) -> None:
        self._transcript.append(message)

    def messages(self) -> list[MessageLike]:
        return self._transcript.messages()

    def clear(self) -> None:
        self._transcript.clear()

    def compress(self, summary: str) -> bool:
        return self._transcript.compress(summary)

    def snapshot(self) -> dict:
        return self._transcript.snapshot()

    def restore(self, data: dict) -> None:
        self._transcript.restore(data)

    def build_messages(self, system_prompt: str | None, user_text: str) -> list[dict]:
        # 检索式选轮：最近若干轮保证保留，更早的轮次按与 user_text 的相关性择优补入预算。
        selected = self.assembler.select_relevant_turns(
            self.messages(),
            user_text,
            self._config.budget_tokens,
            max_recent_turns=self._config.retrieval_recent_turns,
            min_relevance=self._config.retrieval_min_relevance,
        )
        return seed_messages(system_prompt, selected, user_text)
