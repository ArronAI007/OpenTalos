"""语义记忆的写入侧：一次对话轮次的"是否值得长期记住"提取，顺带给出重要性评分。

不做实时 tool 驱动写入，而是每轮结束后用一次模型调用判断（no-op 优先：大多数轮次应判否）。
规则写进 prompt 而非代码校验——密钥/临时问答这类判断依赖上下文理解，模型比正则更可靠。
"""

import json
from dataclasses import dataclass

EXTRACTION_SYSTEM_PROMPT = (
    "You decide whether a single chat turn contains a durable fact about the USER worth remembering "
    "in future conversations: their profile (who they are, stable background), stable preferences "
    "(language, style, format they want), or ongoing context/plans. "
    "Default to NOT saving — most turns contain nothing worth remembering. Never save: secrets "
    "(passwords, API keys, tokens), one-off questions ('what's today's date'), or facts the "
    "assistant itself computed. Reply with ONLY a JSON object "
    '{"shouldSave": true|false, "content": "<one concise sentence, in the user\'s language, describing '
    'the durable fact>", "importance": <0.0-1.0, how durably useful this fact is for future conversations; '
    'default 0.5 if unsure>}, where content is empty when shouldSave is false.'
)


@dataclass(frozen=True)
class ExtractedMemory:
    content: str
    importance: float


def build_extraction_messages(user_text: str, assistant_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"User: {user_text}\n\nAssistant: {assistant_text}"},
    ]


def parse_extraction(text: str) -> ExtractedMemory | None:
    """解析提取结果；非法 JSON / shouldSave 非 true / 空内容一律返回 None（即不记）。
    importance 缺失时默认 0.5，超出 [0.0, 1.0] 区间的被夹到边界。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("shouldSave") is not True:
        return None
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    importance = data.get("importance", 0.5)
    if not isinstance(importance, (int, float)):
        importance = 0.5
    importance = max(0.0, min(1.0, float(importance)))
    return ExtractedMemory(content=content.strip(), importance=importance)
