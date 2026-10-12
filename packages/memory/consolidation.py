"""语义记忆的整合（去重/合并）：把一组语义高度相似的记忆合并成一条更简洁的。

和 extraction.py 同构：只管构造提示词和解析模型输出，不碰模型调用也不碰存储——真正的编排
（循环每个相似分组、调模型、落库）在 apps/api/runtime.py，因为那里才有 ModelClient。
"""

import json

CONSOLIDATION_SYSTEM_PROMPT = (
    "You are given several memories about the same user that are near-duplicates or closely related. "
    "Merge them into ONE concise sentence, in the same language as the memories, that preserves all the "
    "distinct facts without repetition. Reply with ONLY a JSON object "
    '{"merged": "<the merged sentence>"}.'
)


def build_consolidation_messages(contents: list[str]) -> list[dict[str, str]]:
    joined = "\n".join(f"- {content}" for content in contents)
    return [
        {"role": "system", "content": CONSOLIDATION_SYSTEM_PROMPT},
        {"role": "user", "content": joined},
    ]


def parse_consolidation(text: str) -> str | None:
    """解析合并结果；非法 JSON / 空内容一律返回 None（这一组这次就不合并）。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    merged = data.get("merged")
    if not isinstance(merged, str) or not merged.strip():
        return None
    return merged.strip()
