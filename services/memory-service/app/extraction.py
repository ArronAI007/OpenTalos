import json
import logging

from psycopg_pool import AsyncConnectionPool

from db.bulk import insert_raw_memory
from providers.base import TextCompletionProvider

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """你是一个记忆提取助手。你会看到一轮用户和 AI 助手之间的对话，任务是判断这段对话里有没有出现值得长期记住的、跨对话仍然成立的用户信息（比如用户的身份背景、对回复方式的偏好、正在进行的长期计划）。

不该提取的内容：
- 单次性、临时性的问答本身（比如"今天几号""汇率多少"），除非其中体现了跨对话仍然成立的用户信息。
- 助手自己算出来的、不是关于用户的事实性输出。
- 用户消息里出现的密钥/密码/token 等敏感信息——发现了就跳过，绝不能输出。

大多数对话都不包含值得记住的信息，这种情况下应该判断为不需要保存，不要为了"总有点什么"而勉强总结。

只输出一个 JSON 对象，不要有任何其他文字：
- 如果没有值得记住的信息：{"shouldSave": false}
- 如果有：{"shouldSave": true, "content": "一句话描述这条信息"}"""


def _parse_extraction_result(raw: str) -> tuple[bool, str | None]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("memory-service: extraction model returned non-JSON output: %s", raw[:200])
        return False, None
    if isinstance(parsed, dict) and parsed.get("shouldSave") is True:
        content = parsed.get("content")
        if isinstance(content, str):
            return True, content
        logger.error(
            "memory-service: extraction model returned shouldSave:true with an invalid content field: %s", raw[:200]
        )
        return False, None
    return False, None


async def extract_memory(
    pool: AsyncConnectionPool,
    provider: TextCompletionProvider,
    tenant_id: str,
    session_id: str,
    run_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    user_prompt = f"用户：{user_message}\n助手：{assistant_reply}"
    raw = await provider.complete_text(EXTRACTION_SYSTEM_PROMPT, user_prompt)
    should_save, content = _parse_extraction_result(raw)
    if not should_save or not content:
        return
    await insert_raw_memory(pool, tenant_id, session_id, run_id, content)
