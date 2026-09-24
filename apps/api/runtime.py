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
from suggest import suggest_followups

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

    async def acall(self, name: str, arguments: dict[str, Any], *, call_id: str | None = None) -> ToolOutcome:
        if self.sink is not None:
            await self.sink({"type": "tool_call", "call_id": call_id, "name": name, "arguments": arguments})
        outcome = await self._inner.acall(name, arguments)
        if self.sink is not None:
            await self.sink({
                "type": "tool_result", "call_id": call_id, "name": name,
                "result": outcome.output, "ok": outcome.succeeded,
            })
        return outcome


# 消费循环等不到事件时的空闲上限：超时发 ping，让真实 HTTP 层的断连在 ≤1s 内
# 暴露（starlette/uvicorn 只在写响应时才发现客户端断开），同时给停止信号兜底响应时延。
_STREAM_IDLE_S = 1.0


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
        compaction_token_limit: int | None = None,
    ) -> None:
        self._store = store
        self._model_client = model_client  # None → 首次需要时按 env 构造
        self._skill_service_url = skill_service_url
        self._trace_dir = trace_dir
        self._tool_registry_factory = tool_registry_factory
        self._compaction_token_limit = compaction_token_limit
        self._agents: dict[str, Agent] = {}
        self._registries: dict[str, EventToolRegistry] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        # 活动流的停止信号：stream_reply 入流时登记、finally 清理，生命周期与流一致。
        self._active_stops: dict[str, asyncio.Event] = {}
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
            compaction_token_limit=self._compaction_token_limit,
        )

        # 压缩成功后落一份 Surface 快照（summary + 保留近期）到 DB：重启据此恢复、不重新压。
        async def _persist_checkpoint() -> None:
            await asyncio.to_thread(
                self._store.append_message, task["id"], "summary",
                json.dumps(agent.snapshot_history(), ensure_ascii=False),
            )

        agent.on_compression = _persist_checkpoint

        rows = await asyncio.to_thread(self._store.list_messages, task["id"])
        # 若存在 summary 检查点：恢复其快照，只重放它之后的新行（被折叠的早期行不再进 Surface）。
        last_summary = max((i for i, r in enumerate(rows) if r["kind"] == "summary"), default=-1)
        if last_summary >= 0:
            try:
                agent.restore_history(json.loads(rows[last_summary]["content"]))
            except json.JSONDecodeError:
                pass  # 快照损坏：按无检查点处理，退回全量重放
            else:
                rows = rows[last_summary + 1:]
        for row in rows:
            if row["kind"] in ("user", "assistant"):
                agent.record_message(ChatMessage(role=row["kind"], content=row["content"]))
            elif row["kind"] == "tool":
                # tool 行还原成 record_tool_result 进 transcript：老数据（无 call_id）或内容
                # 解析失败时跳过——本就不进上下文，保持现状，不做伪 call_id 兜底。
                try:
                    data = json.loads(row["content"])
                except json.JSONDecodeError:
                    continue
                call_id = data.get("call_id")
                if not call_id:
                    continue
                agent.record_tool_result(
                    call_id, data.get("name", ""), json.dumps(data.get("arguments", {})), data.get("result", "")
                )
        self._agents[task["id"]] = agent
        return agent

    def request_stop(self, task_id: str) -> None:
        # 无活动流时幂等 no-op：事件只在流存活期间登记（流结束即随 finally 清理），
        # 停止一个已结束/未开始的流没有意义。
        event = self._active_stops.get(task_id)
        if event is not None:
            event.set()

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
            user_row = await asyncio.to_thread(self._store.append_message, task_id, "user", content)
            await asyncio.to_thread(self._store.set_title_if_empty, task_id, _truncate_title(content))
            # 回送落库行的身份：前端据此把 live-N user 泡换成 row-N（删除轮次需要服务端 id），
            # completedAt 也校准为服务端写入时间。事件发生在 producer 启动前，必为流内首事件。
            yield {"type": "user_stored", "id": user_row["id"], "created_at": user_row["created_at"]}
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
                        on_reasoning_delta=lambda chunk: emit({"type": "reasoning", "text": chunk}),
                    )
                except Exception as exc:  # noqa: BLE001 - 转成 error 事件交给前端
                    error = str(exc)
                finally:
                    if registry is not None:
                        registry.sink = None
                    await queue.put(None)

            producer = asyncio.create_task(run_agent())
            # 跟进问题推荐并行预发：与回复生成同时起跑（此刻 history 含本轮提问、尚无
            # 回复正文——推荐语义=从历史+提问延伸）。回复流完时推荐通常已就绪，done 后
            # 不再串行空等第二次模型调用（实测串行耗时 ~4s：TTFT+思维链+输出）。
            # 停止/error 路径不产生推荐：统一在 finally 里 cancel，任务不泄漏。
            suggest_task = asyncio.create_task(
                suggest_followups(
                    self._client(),
                    await asyncio.to_thread(self._store.list_messages, task_id),
                )
            )
            persisted = False
            stopped_by_user = False
            stop_event = self._active_stops[task_id] = asyncio.Event()
            try:
                while True:
                    # 每轮先查停止信号：即使队列里还压着已产事件也立即止步——"停止"就是不再往后播。
                    if stop_event.is_set():
                        stopped_by_user = True
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=_STREAM_IDLE_S)
                    except TimeoutError:
                        # 空闲心跳：ping 由编码层转成 SSE comment 帧，意义仅在于让断连尽早
                        # 通过下次写失败暴露；不进 parts，也不落库。
                        yield {"type": "ping"}
                        continue
                    if event is None:
                        break
                    if event["type"] == "delta":
                        parts.append(event["text"])
                    elif event["type"] == "tool_call":
                        pending_calls.append(event)
                    elif event["type"] == "tool_result":
                        call_id = event.get("call_id")
                        match = next(
                            (i for i, call in enumerate(pending_calls) if call.get("call_id") == call_id),
                            None,
                        ) if call_id is not None else None
                        arguments = pending_calls.pop(match)["arguments"] if match is not None else {}
                        await asyncio.to_thread(
                            self._store.append_message, task_id, "tool",
                            json.dumps({
                                "call_id": call_id, "name": event["name"], "arguments": arguments,
                                "result": event["result"], "ok": event["ok"],
                            }, ensure_ascii=False),
                        )
                    yield event
                if stopped_by_user:
                    # 跳到 finally 的统一兜底（partial + stopped 标记落库），不发 done/error
                    return
                if error is not None:
                    yield {"type": "error", "message": error}
                else:
                    if not parts and reply:
                        parts.append(reply)  # 后端未流式时兜底，流式过则不重复追加
                    final_reply = "".join(parts)
                    await asyncio.to_thread(self._store.append_message, task_id, "assistant", final_reply)
                    persisted = True
                    yield {"type": "done", "reply": final_reply}
                    # 推荐已在 producer 旁并行预发——回复流式期间它跑完了大半，这里通常直接
                    # 拿到结果；失败静默为空（suggest_followups 出口无异常）。
                    suggestions = await suggest_task
                    if suggestions:
                        yield {"type": "suggestions", "items": suggestions}
                    # 压缩是优化、失败不影响对话：assistant 已落库，此处触发折叠+快照落库，
                    # DB 顺序 user → tool → assistant → summary，重放时 summary 之后无重复行。
                    try:
                        await agent.maybe_compress_history()
                    except Exception:  # noqa: BLE001 - 摘要失败静默跳过，下轮继续
                        pass
            finally:
                self._active_stops.pop(task_id, None)
                if not producer.done():
                    # 不等收敛：断连时 starlette 用 anyio cancel scope 取消响应，scope 内任何
                    # await（含 gather/to_thread）都会再抛 CancelledError（真机实测），
                    # 连用 await 达成的落库都会半路夭折——所以下端落库必须同步调用；
                    # producer 是独立 task，不在该 scope 内，自行收尾。
                    producer.cancel()
                if not suggest_task.done():
                    suggest_task.cancel()
                # 客户端中途断开 / 用户停止（消费循环被 GeneratorExit/CancelledError 打断、
                # 或 stopped_by_user 提前 return）：正常完成路径的 assistant 落库不可达。
                # 这里兜底：①有已流出内容则落 assistant partial；②无条件落一行
                # kind="stopped" 标记——否则立即停止（0 delta）刷新后这次提问像从未发生过。
                # error 场景前端已有错误泡，保持既有的不落语义（test_agent_error_* 守护）。
                # parts 在消费循环里随 yield 累积 = 恰好用户实际看到的部分。
                if not persisted and error is None:
                    if not parts and reply:
                        parts.append(reply)
                    partial = "".join(parts)
                    if partial:
                        self._store.append_message(task_id, "assistant", partial)
                    self._store.append_message(task_id, "stopped", "")
