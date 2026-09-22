"""会话运行时：agent 装配（模型 + 技能接线）、进程内缓存、历史重建、SSE 事件生产。

工具事件没有现成回调钩子——agent 循环只调 registry.acall(name, arguments)，
所以用 EventToolRegistry 委托包装一层发射。每个 agent 一个包装实例，
sink 在每条消息开始时绑到该消息的队列（per-task 锁保证同一任务不并发）。
"""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from agents.builder import build_agent
from core.agent import Agent
from core.model import ModelClient
from core.protocol import ChatMessage
from skill.client import SkillClient, SkillServiceError
from skill.prompt import format_skills_for_system_prompt
from skill.tools import ReadSkillTool, RunSkillScriptTool
from tool.outcome import ToolOutcome
from tool.registry import ToolRegistry
from tool.tool import Tool

from db import ChatStore

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class EventToolRegistry(ToolRegistry):
    """包装 inner 注册表：acall 前后发射 tool_call / tool_result 事件。

    ToolRegistry 的公开方法必须显式覆盖并委托到 inner，不能只靠 __getattr__——
    基类方法会被 wrapper 原样继承、作用于 super().__init__() 建出的空 _tools，
    __getattr__ 根本不会触发。__getattr__ 仅作兜底（含 _inner 防递归）。
    """

    def __init__(self, inner: ToolRegistry) -> None:
        super().__init__()
        self._inner = inner
        self.sink: EventSink | None = None

    def __getattr__(self, item: str) -> Any:  # 兜底：未被覆盖的属性透传到 inner
        if item == "_inner":
            raise AttributeError(item)
        return getattr(self._inner, item)

    def register(self, tool: Tool) -> None:
        self._inner.register(tool)

    def unregister(self, name: str) -> None:
        self._inner.unregister(name)

    def get(self, name: str) -> Tool | None:
        return self._inner.get(name)

    def list_tools(self) -> list[Tool]:
        return self._inner.list_tools()

    def function_schemas(self) -> list[dict[str, Any]]:
        return self._inner.function_schemas()

    async def acall(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if self.sink is not None:
            await self.sink({"type": "tool_call", "name": name, "arguments": arguments})
        outcome = await self._inner.acall(name, arguments)
        if self.sink is not None:
            await self.sink({
                "type": "tool_result", "name": name,
                "result": outcome.output, "ok": outcome.succeeded,
            })
        return outcome


def _truncate_title(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


class ChatRuntime:
    def __init__(
        self,
        store: ChatStore,
        *,
        model_client: ModelClient | None = None,
        skill_service_url: str = "http://localhost:8321",
        trace_dir: Path | None = None,
        tool_registry_factory: Callable[[], ToolRegistry] | None = None,
    ) -> None:
        self._store = store
        self._model_client = model_client  # None → 首次需要时按 env 构造
        self._skill_service_url = skill_service_url
        self._trace_dir = trace_dir
        self._tool_registry_factory = tool_registry_factory
        self._agents: dict[str, Agent] = {}
        self._registries: dict[str, EventToolRegistry] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._skill_tools: list[Any] = []
        self._skills_suffix: str | None = None
        self._skills_reachable: bool | None = None

    @property
    def store(self) -> ChatStore:
        return self._store

    @property
    def skill_service_url(self) -> str:
        return self._skill_service_url

    @property
    def skills_reachable(self) -> bool | None:
        return self._skills_reachable

    @property
    def model_name(self) -> str:
        return self._client().model_name

    def _client(self) -> ModelClient:
        if self._model_client is None:
            self._model_client = ModelClient()
        return self._model_client

    async def _ensure_skills(self) -> None:
        if self._skills_reachable is not None:
            return
        try:
            client = SkillClient(self._skill_service_url)
            skills = await client.list_skills()
            self._skill_tools = [
                ReadSkillTool(SkillClient(self._skill_service_url)),
                RunSkillScriptTool(SkillClient(self._skill_service_url)),
            ]
            self._skills_suffix = format_skills_for_system_prompt(skills) or None
            self._skills_reachable = True
        except SkillServiceError:
            self._skills_suffix = None
            self._skills_reachable = False

    def _build_registry(self, task_id: str) -> ToolRegistry | None:
        inner = self._tool_registry_factory() if self._tool_registry_factory else ToolRegistry()
        for tool in self._skill_tools:
            inner.register(tool)
        if not inner.function_schemas():
            return None
        wrapper = EventToolRegistry(inner)
        self._registries[task_id] = wrapper
        return wrapper

    async def _get_agent(self, task: dict[str, Any]) -> Agent:
        agent = self._agents.get(task["id"])
        if agent is not None:
            return agent
        await self._ensure_skills()
        agent = build_agent(
            task["agent_type"], f"task-{task['id'][:8]}", self._client(),
            tool_registry=self._build_registry(task["id"]),
            system_prompt_suffix=self._skills_suffix,
            trace_dir=str(self._trace_dir) if self._trace_dir else None,
        )
        rows = await asyncio.to_thread(self._store.list_messages, task["id"])
        for row in rows:
            if row["kind"] in ("user", "assistant"):
                agent.record_message(ChatMessage(role=row["kind"], content=row["content"]))
        self._agents[task["id"]] = agent
        return agent

    def evict(self, task_id: str) -> None:
        # 调用方须保证该任务当前没有进行中的流：pop 掉锁对象后，新流会 setdefault 造出
        # 一把新锁，同一任务的两条流会并发跑，可能串流。
        self._agents.pop(task_id, None)
        self._registries.pop(task_id, None)
        self._task_locks.pop(task_id, None)

    async def stream_reply(self, task_id: str, content: str) -> AsyncIterator[dict[str, Any]]:
        task = await asyncio.to_thread(self._store.get_task, task_id)
        if task is None:
            yield {"type": "error", "message": f"task not found: {task_id}"}
            return
        lock = self._task_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

            async def emit(event: dict[str, Any]) -> None:
                await queue.put(event)

            # 先取 agent：此时本轮 user 消息尚未落盘，重建重放的历史不含本轮，
            # arespond 里 record_message 的 user 只出现一次（避免 transcript 重复）。
            agent = await self._get_agent(task)
            # 取舍：user 消息先落库，agent transcript 要到 arespond 末尾才补录。若流在这两步
            # 之间被取消，DB 会多出这条 user 行而缓存 agent 的 transcript 缺失；下一轮缓存命中
            # 不重放，上下文会短暂缺这一句，直到 evict/重启后从 DB 重放恢复。接受此取舍。
            await asyncio.to_thread(self._store.append_message, task_id, "user", content)
            await asyncio.to_thread(self._store.set_title_if_empty, task_id, _truncate_title(content))
            pending_calls: list[dict[str, Any]] = []
            parts: list[str] = []
            error: str | None = None
            reply: str | None = None

            async def run_agent() -> None:
                nonlocal error, reply
                registry: EventToolRegistry | None = None
                try:
                    registry = self._registries.get(task["id"])
                    if registry is not None:
                        registry.sink = emit
                    reply = await agent.arespond(
                        content,
                        on_text_delta=lambda chunk: emit({"type": "delta", "text": chunk}),
                    )
                except Exception as exc:  # noqa: BLE001 - 转成 error 事件交给前端
                    error = str(exc)
                finally:
                    if registry is not None:
                        registry.sink = None
                    await queue.put(None)

            producer = asyncio.create_task(run_agent())
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    if event["type"] == "delta":
                        parts.append(event["text"])
                    elif event["type"] == "tool_call":
                        pending_calls.append(event)
                    elif event["type"] == "tool_result":
                        match = next(
                            (i for i, call in enumerate(pending_calls) if call["name"] == event["name"]),
                            None,
                        )
                        arguments = pending_calls.pop(match)["arguments"] if match is not None else {}
                        await asyncio.to_thread(
                            self._store.append_message, task_id, "tool",
                            json.dumps({
                                "name": event["name"], "arguments": arguments,
                                "result": event["result"], "ok": event["ok"],
                            }, ensure_ascii=False),
                        )
                    yield event
                if error is not None:
                    yield {"type": "error", "message": error}
                else:
                    if not parts and reply:
                        parts.append(reply)  # 后端未流式时兜底，流式过则不重复追加
                    final_reply = "".join(parts)
                    await asyncio.to_thread(self._store.append_message, task_id, "assistant", final_reply)
                    yield {"type": "done", "reply": final_reply}
            finally:
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
