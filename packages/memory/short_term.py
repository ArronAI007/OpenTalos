from typing import Any


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
