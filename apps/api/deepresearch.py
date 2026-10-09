"""DeepResearch：规划 TODO 子任务 → 并行搜索+总结 → 合成带引用报告。应用层功能，定位同
evaluation.py/suggest.py——不进 packages/*。"""
import asyncio
import json
from typing import Any

from core.model import ModelClient
from websearch.client import TavilyClient

from db import ChatStore

_MIN_TODOS = 3
_MAX_TODOS = 5
_PLAN_TIMEOUT_S = 30.0
_SUMMARY_TIMEOUT_S = 30.0
_REPORT_TIMEOUT_S = 60.0
_SEARCH_MAX_RESULTS = 5

_PLAN_SYSTEM = (
    f"你是研究规划专家。把用户给的研究主题拆解成 {_MIN_TODOS}-{_MAX_TODOS} 个具体的子任务，"
    "每个子任务配一句适合拿去搜索引擎查询的问题。只返回 JSON 字符串数组，每个元素是一句搜索"
    "查询语句，不要输出其他任何内容。"
)
_SUMMARY_SYSTEM = (
    "你是任务总结专家。根据给定的搜索结果，针对子任务问题写一段简明的中文总结，只基于给出的"
    "搜索结果内容作答，不要编造。"
)
_REPORT_SYSTEM = (
    "你是报告撰写专家。根据各个子任务的总结，撰写一份结构清晰、带来源引用的 markdown 研究"
    "报告。引用格式：正文中用 [1]、[2] 等标注，文末附\"参考链接\"列表（按编号对应标题和链接）。"
)


class PlanningError(Exception):
    """规划/报告合成阶段失败——没有可用内容，整个研究任务直接判失败。"""


def _parse_queries(text: str) -> list[str]:
    """宽松解析模型输出——和 suggest.py _parse_items 同款策略，独立实现（两个应用层模块
    互不依赖，deepresearch 不该因为 suggest 的改动被牵连）。"""
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
            return items[:_MAX_TODOS]
    return []


async def _plan(client: ModelClient, topic: str) -> list[str]:
    try:
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": _PLAN_SYSTEM},
                {"role": "user", "content": topic},
            ]),
            timeout=_PLAN_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        raise PlanningError(f"planning call failed: {exc}") from exc
    queries = _parse_queries(completion.text)
    if len(queries) < _MIN_TODOS:
        raise PlanningError(f"planner returned only {len(queries)} usable queries")
    return queries


async def _run_todo(client: ModelClient, search_client: TavilyClient, query: str) -> dict[str, Any]:
    """单条 TODO 的搜索+总结——失败不抛异常，返回 status=failed 的字典，不连累其他 TODO。"""
    try:
        search_response = await search_client.search(query, max_results=_SEARCH_MAX_RESULTS)
        if not search_response.results:
            raise ValueError("no search results")
        context = "\n\n".join(
            f"标题：{r.title}\n链接：{r.url}\n内容：{r.content}" for r in search_response.results
        )
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": f"子任务：{query}\n\n搜索结果：\n{context}"},
            ]),
            timeout=_SUMMARY_TIMEOUT_S,
        )
        return {
            "status": "completed",
            "summary": completion.text.strip(),
            "sources": [{"title": r.title, "url": r.url} for r in search_response.results],
        }
    except Exception as exc:  # noqa: BLE001 - 单条 TODO 失败不连累其他
        return {"status": "failed", "summary": str(exc), "sources": []}


async def _synthesize_report(client: ModelClient, topic: str, todos: list[dict]) -> str:
    completed = [t for t in todos if t["status"] == "completed"]
    if not completed:
        raise PlanningError("no completed todos to synthesize a report from")
    sections = "\n\n".join(f"## {t['query']}\n{t['summary']}" for t in completed)
    try:
        completion = await asyncio.wait_for(
            client.acomplete([
                {"role": "system", "content": _REPORT_SYSTEM},
                {"role": "user", "content": f"研究主题：{topic}\n\n{sections}"},
            ]),
            timeout=_REPORT_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        raise PlanningError(f"report synthesis failed: {exc}") from exc
    return completion.text.strip()


async def run_research(
    store: ChatStore, run_id: str, client: ModelClient, search_client: TavilyClient, topic: str
) -> None:
    """后台任务主体：规划 → 并行执行 → 合成报告 → 落库。main.py 的调用方是 fire-and-forget 的
    asyncio.create_task——这里必须吞掉所有异常并落成 status='failed'，否则调用方永远看不到。"""
    try:
        queries = await _plan(client, topic)
    except PlanningError as exc:
        await asyncio.to_thread(store.update_deepresearch_run, run_id, status="failed", error=str(exc))
        return

    todos = [
        {"id": i, "query": q, "status": "pending", "summary": None, "sources": []}
        for i, q in enumerate(queries)
    ]
    await asyncio.to_thread(store.update_deepresearch_run_todos, run_id, todos)

    # update_deepresearch_todo 是"整列读出来、改一条、整列写回去"——并发跑多条 TODO 时，
    # 两个协程交错的读-改-写会互相覆盖对方的更新（丢更新）。用一把锁只序列化这几次快速的
    # 数据库读写，真正慢的搜索+总结调用（_run_todo）仍然完全并发，不受影响。
    todo_lock = asyncio.Lock()

    async def _execute(todo: dict) -> None:
        async with todo_lock:
            await asyncio.to_thread(store.update_deepresearch_todo, run_id, todo["id"], status="running")
        result = await _run_todo(client, search_client, todo["query"])
        async with todo_lock:
            await asyncio.to_thread(store.update_deepresearch_todo, run_id, todo["id"], **result)

    await asyncio.gather(*(_execute(todo) for todo in todos))

    final_run = await asyncio.to_thread(store.get_deepresearch_run, run_id)
    try:
        report = await _synthesize_report(client, topic, final_run["todos"])
    except PlanningError as exc:
        await asyncio.to_thread(store.update_deepresearch_run, run_id, status="failed", error=str(exc))
        return

    await asyncio.to_thread(store.update_deepresearch_run, run_id, status="completed", report=report)
