"""回复完成后的跟进问题推荐：独立一次小调用，不进 agent transcript，任何失败静默为空。

推荐是锦上添花——缺失绝不影响主会话，所以本模块出口只有 list[str]，没有异常。
"""
import asyncio
import json
from typing import Any

from core.model import ModelClient

FOLLOWUP_COUNT = 3
# 整体超时独立于客户端默认（60s）：推荐不能拖住流收尾
_SUGGEST_TIMEOUT_S = 15.0
# 送入模型的对话窗口：最近 N 条 user/assistant + 每条内容截断，控制 prompt 体量
_CONTEXT_TAIL = 6
_ROW_SNIPPET_CHARS = 500

_SYSTEM = (
    "你是跟进问题推荐器。根据给出的对话，推荐用户接下来最可能想问的 "
    f"{FOLLOWUP_COUNT} 个问题。要求：以用户口吻提问、每条一句话、彼此不重复、"
    "与对话内容相关且能从对话自然延伸。只输出 JSON 字符串数组，不要输出任何其他内容。"
)


def _parse_items(text: str) -> list[str]:
    """宽松解析模型输出：整串 JSON → 截取首个 [...] 片段 → 放弃。只留非空字符串，最多 3 条。"""
    candidates = [text.strip()]
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        items = [item.strip() for item in data if isinstance(item, str) and item.strip()]
        if items:
            return items[:FOLLOWUP_COUNT]
    return []


async def suggest_followups(
    client: ModelClient,
    history: list[dict[str, Any]],
    *,
    timeout: float = _SUGGEST_TIMEOUT_S,
) -> list[str]:
    """history = ChatStore.list_messages 的行。无对话内容或调用失败都返回 []。"""
    tail = [row for row in history if row["kind"] in ("user", "assistant")][-_CONTEXT_TAIL:]
    if not tail:
        return []
    transcript = "\n".join(
        f"{'用户' if row['kind'] == 'user' else '助手'}: {row['content'][:_ROW_SNIPPET_CHARS]}"
        for row in tail
    )
    try:
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"对话如下：\n{transcript}"},
            ]),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 - 推荐失败静默降级，绝不影响已完成的回复
        return []
    return _parse_items(completion.text)
