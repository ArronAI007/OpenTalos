import asyncio
import json
import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from db.bulk import (
    MemoryUpdate,
    NewMemory,
    delete_memories,
    delete_raw_memories,
    list_memories_for_tenant,
    list_raw_memories_for_tenant,
    upsert_memories,
)
from providers.base import TextCompletionProvider

logger = logging.getLogger(__name__)

CONSOLIDATION_SYSTEM_PROMPT = """你是一个记忆整合助手。你会看到某个用户"已确认的记忆"列表和一批"待处理的原始观察"，任务是把原始观察合并进已确认的记忆里，输出一组具体操作。

规则：
- 一条原始观察如果是全新信息，输出一个 add 操作。
- 一条原始观察如果是对已有记忆的补充/修正/推翻，输出一个 update（改写这条记忆）或 delete（这条记忆已经不成立了）操作，引用已有记忆的 id。
- 一条原始观察如果跟已有记忆完全重复，不用输出任何操作（忽略即可）。
- profile/preference 类型的记忆一般是稳定的，不要轻易 delete；context 类型的记忆容易过时，看起来不再成立就应该 delete。

只输出一个 JSON 对象，不要有任何其他文字，格式：
{"add": [{"type": "profile"|"preference"|"context", "title": "...", "content": "..."}], "update": [{"id": "...", "content": "..."}], "delete": ["id1", "id2"]}
如果没有任何要做的操作，输出 {"add": [], "update": [], "delete": []}"""

VALID_MEMORY_TYPES = {"profile", "preference", "context"}


def _is_valid_new_memory(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and item.get("type") in VALID_MEMORY_TYPES
        and isinstance(item.get("title"), str)
        and isinstance(item.get("content"), str)
    )


def _is_valid_memory_update(item: Any) -> bool:
    return isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("content"), str)


def _filter_valid(items: list[Any], is_valid: Any, label: str) -> list[Any]:
    valid = []
    for item in items:
        if is_valid(item):
            valid.append(item)
        else:
            logger.error(
                "memory-service: consolidation model returned an invalid %s item, dropping it: %s",
                label,
                json.dumps(item, ensure_ascii=False)[:200],
            )
    return valid


def _parse_consolidation_result(raw: str) -> tuple[list[NewMemory], list[MemoryUpdate], list[str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("memory-service: consolidation model returned non-JSON output: %s", raw[:200])
        return [], [], []
    if not isinstance(parsed, dict):
        logger.error("memory-service: consolidation model returned a non-object JSON value: %s", raw[:200])
        return [], [], []

    add_raw = parsed.get("add") if isinstance(parsed.get("add"), list) else []
    update_raw = parsed.get("update") if isinstance(parsed.get("update"), list) else []
    delete_raw = parsed.get("delete") if isinstance(parsed.get("delete"), list) else []
    if not isinstance(parsed.get("add"), list) or not isinstance(parsed.get("update"), list) or not isinstance(parsed.get("delete"), list):
        logger.error(
            "memory-service: consolidation model returned an unexpected shape (missing/non-array add/update/delete): %s",
            raw[:200],
        )

    valid_add = _filter_valid(add_raw, _is_valid_new_memory, "add")
    valid_update = _filter_valid(update_raw, _is_valid_memory_update, "update")
    valid_delete = _filter_valid(delete_raw, lambda item: isinstance(item, str), "delete")

    return (
        [NewMemory(type=item["type"], title=item["title"], content=item["content"]) for item in valid_add],
        [MemoryUpdate(id=item["id"], content=item["content"]) for item in valid_update],
        valid_delete,
    )


async def consolidate_memories_for_tenant(
    pool: AsyncConnectionPool, provider: TextCompletionProvider, tenant_id: str
) -> None:
    existing, raw = await asyncio.gather(
        list_memories_for_tenant(pool, tenant_id), list_raw_memories_for_tenant(pool, tenant_id)
    )
    if not raw:
        return

    existing_lines = "\n".join(f"- [{m.id}] [{m.type}] {m.title}: {m.content}" for m in existing) or "（无）"
    raw_lines = "\n".join(f"- {r.content}" for r in raw)
    user_prompt = f"已确认的记忆：\n{existing_lines}\n\n待处理的原始观察：\n{raw_lines}"

    raw_result = await provider.complete_text(CONSOLIDATION_SYSTEM_PROMPT, user_prompt)
    add, update, delete = _parse_consolidation_result(raw_result)

    if add or update:
        await upsert_memories(pool, tenant_id, add, update)
    if delete:
        await delete_memories(pool, tenant_id, delete)

    # 处理过的 raw_memories 全部清空，不管模型是否采纳——这批已经被完整看过一遍，留着没有增量
    # 价值。注意 upsert_memories/delete_memories/delete_raw_memories 是三个独立事务，整体不原子——
    # 如果在它们之间崩溃，重试时对同一个 title 再次 add 会撞上 (tenant_id, title) 唯一约束。
    await delete_raw_memories(pool, tenant_id, [r.id for r in raw])
