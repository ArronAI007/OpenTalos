"""会话运行时：agent 装配（模型 + 技能接线）、进程内缓存、历史重建、SSE 事件生产。

工具事件没有现成回调钩子——agent 循环只调 registry.acall(name, arguments)，
所以用 EventToolRegistry 委托包装一层发射。每个 agent 一个包装实例，
sink 在每条消息开始时绑到该消息的队列（per-task 锁保证同一任务不并发）。
"""
import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.builder import build_agent
from agents.subagent_tool import DispatchSubagentTool
from core.agent import Agent
from core.cancellation import CancellationToken
from core.model import ModelClient
from core.protocol import ChatMessage, ToolInvocation
from memory import build_extraction_messages, parse_extraction, rank_memories
from skill.client import SkillClient, SkillServiceError
from skill.prompt import format_skills_for_system_prompt
from skill.tools import ReadSkillTool, RunSkillScriptTool
from tool.outcome import ToolOutcome
from tool.registry import CircuitBreaker, ToolRegistry
from tool.tool import Tool
from websearch.client import TavilyClient
from websearch.tools import WebExtractorTool, WebSearchTool
from mcpclient.client import MCPServerConfig, MCPToolInfo
from mcpclient.tools import MCPTool
from a2apeer.tools import A2ATool

from db import ChatStore
from suggest import suggest_followups, suggest_skill_usage_examples, suggest_title

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


def _drain_queue(queue: asyncio.Queue[str]) -> list[str]:
    """同步排空队列（单事件循环内安全）：供 agent 每步开头取走待注入的 steer 消息。"""
    items: list[str] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _mcp_tool_info_from_dict(data: dict) -> MCPToolInfo:
    return MCPToolInfo(name=data["name"], description=data["description"], input_schema=data["input_schema"])


@dataclass
class _LiveRun:
    """一轮运行的可续传状态：producer/事件日志与连接生命周期解耦。

    断连只让消费者不再跟随，运行本身照常跑到完成并落库；重连锁定同一份事件日志，
    从 after 下标补发后继续跟随。运行结束后事件保留 run_ttl_seconds 供迟到重连。
    """

    task_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    steer: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    steer_event: asyncio.Event = field(default_factory=asyncio.Event)
    done: bool = False
    finished_at: float | None = None
    runner: asyncio.Task[None] | None = None


class ChatRuntime:
    def __init__(
        self,
        store: ChatStore,
        *,
        model_client: ModelClient | None = None,
        skill_service_url: str = "http://localhost:8321",
        tavily_api_key: str | None = None,
        a2a_peer_url: str | None = None,
        trace_dir: Path | None = None,
        tool_registry_factory: Callable[[], ToolRegistry] | None = None,
        compaction_token_limit: int | None = None,
        tool_timeout_seconds: float | None = 120.0,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 300.0,
        approval_timeout_seconds: float = 300.0,
        run_ttl_seconds: float = 300.0,
        memory_enabled: bool = False,
        budget_tokens: int | None = None,
    ) -> None:
        self._store = store
        self._model_client = model_client  # None → 首次需要时按 env 构造
        self._skill_service_url = skill_service_url
        self._trace_dir = trace_dir
        self._tool_registry_factory = tool_registry_factory
        self._compaction_token_limit = compaction_token_limit
        # 工具可靠性的安全网：单个工具 120s 上限（各工具自身超时更短，这是兵底），
        # 连续失败到阈值就对该工具开路。熔断器进程级共享——跨 task 不再反复重试同一坏工具。
        self._tool_timeout_seconds = tool_timeout_seconds
        self._circuit_breaker = (
            CircuitBreaker(failure_threshold=circuit_failure_threshold, recovery_seconds=circuit_recovery_seconds)
            if circuit_failure_threshold > 0
            else None
        )
        # 待审批的副作用工具调用：approval_id -> (task_id, future[bool])。超时/流结束按拒绝。
        self._approval_timeout_seconds = approval_timeout_seconds
        self._pending_approvals: dict[str, tuple[str, asyncio.Future[bool]]] = {}
        self._agents: dict[str, Agent] = {}
        self._registries: dict[str, EventToolRegistry] = {}
        self._task_locks: dict[str, asyncio.Lock] = {}
        # 每 task 的活动运行：事件日志/停止信号与连接解耦（断连不中止、可续传）。
        self._runs: dict[str, _LiveRun] = {}
        self._run_ttl_seconds = run_ttl_seconds
        # 长期记忆（跨会话）：默认关闭，避免给所有会话平添一次提取模型调用。
        self._memory_enabled = memory_enabled
        # 每轮 token 预算：超过即中止该轮（默认无限制）。
        self._budget_tokens = budget_tokens
        self._skill_tools: list[Any] = []
        self._skills_suffix: str | None = None
        self._skills_reachable: bool | None = None
        self._websearch_tools: list[Any] = []
        self._mcp_tools: list[Any] = []
        self._a2a_tools: list[Any] = [A2ATool(a2a_peer_url)] if a2a_peer_url else []
        self._search_client: TavilyClient | None = None
        if tavily_api_key:
            self._search_client = TavilyClient(tavily_api_key)
            self._websearch_tools = [WebSearchTool(self._search_client), WebExtractorTool(self._search_client)]

    @property
    def store(self) -> ChatStore:
        return self._store

    @property
    def search_client(self) -> TavilyClient | None:
        return self._search_client

    @property
    def skill_service_url(self) -> str:
        return self._skill_service_url

    @property
    def skills_reachable(self) -> bool | None:
        return self._skills_reachable

    @property
    def model_name(self) -> str:
        return self._client().model_name

    @property
    def model_client(self) -> ModelClient:
        return self._client()

    def _client(self) -> ModelClient:
        if self._model_client is None:
            self._model_client = ModelClient()
        return self._model_client

    async def aclose(self) -> None:
        """释放运行时持有的模型客户端（httpx 连接池）；未构造过则 no-op。

        由应用 lifespan 在进程关闭时调用；ModelClient.aclose 自身幂等，重复调用安全。
        """
        if self._model_client is not None:
            await self._model_client.aclose()

    async def suggest_skill_usage(self, name: str, description: str) -> list[str]:
        return await suggest_skill_usage_examples(self._client(), name, description)

    async def _ensure_skills(self) -> None:
        # 不做"只算一次"的永久缓存——只有这样，我的技能里添加/移除才能在下一个新建的 task 里
        # 立刻生效，不用重启进程。_get_agent() 只在新建 agent 时才调用这里，不是每条消息都拉。
        try:
            client = SkillClient(self._skill_service_url)
            skills = await client.list_skills()
            self._skill_tools = [
                ReadSkillTool(SkillClient(self._skill_service_url)),
                RunSkillScriptTool(SkillClient(self._skill_service_url)),
            ]
            added_skills = [s for s in skills if s.added]
            self._skills_suffix = format_skills_for_system_prompt(added_skills) or None
            self._skills_reachable = True
        except SkillServiceError:
            self._skills_suffix = None
            self._skills_reachable = False

    async def _ensure_mcp_tools(self) -> None:
        # 和 _ensure_skills 同样的取舍：不做"只算一次"的永久缓存，每次新建 agent 时都重新
        # 查一遍库——这样 /mcp 页面上启用/禁用某个 server 才能在下一个新建的 task 里立刻
        # 生效，不用重启进程。
        servers = await asyncio.to_thread(self._store.list_mcp_servers)
        self._mcp_tools = [
            MCPTool(
                MCPServerConfig(transport=server["transport"], **server["config"]),
                _mcp_tool_info_from_dict(tool),
            )
            for server in servers
            if server["enabled"]
            for tool in server["cached_tools"]
        ]

    def _collect_base_tools(self, registry: ToolRegistry) -> None:
        for tool in self._skill_tools:
            registry.register(tool)
        for tool in self._websearch_tools:
            registry.register(tool)
        for tool in self._mcp_tools:
            registry.register(tool)
        for tool in self._a2a_tools:
            registry.register(tool)

    def _build_registry(self, task_id: str) -> ToolRegistry:
        # subagent_tools 必须是和 main_tools 物理上不同的 ToolRegistry 实例——dispatch_subagent
        # 只注册进 main_tools，否则子 agent 会连带看到它自己，能够递归再分派。
        subagent_tools = self._new_registry()
        self._collect_base_tools(subagent_tools)

        main_tools = self._new_registry()
        self._collect_base_tools(main_tools)
        main_tools.register(DispatchSubagentTool(self._client(), subagent_tools, approval_gate=self._gate_for(task_id)))

        wrapper = EventToolRegistry(main_tools)
        self._registries[task_id] = wrapper
        return wrapper

    def _new_registry(self) -> ToolRegistry:
        # 注入的 factory（测试）自行决定配置；默认路径挂上超时安全网与共享熔断器。
        if self._tool_registry_factory is not None:
            return self._tool_registry_factory()
        return ToolRegistry(circuit_breaker=self._circuit_breaker, timeout_seconds=self._tool_timeout_seconds)

    def _gate_for(self, task_id: str) -> Callable[[ToolInvocation], Awaitable[bool]]:
        async def gate(invocation: ToolInvocation) -> bool:
            return await self._request_approval(task_id, invocation)

        return gate

    async def _request_approval(self, task_id: str, invocation: ToolInvocation) -> bool:
        """挂起一次副作用工具调用，向当前流发 approval_required，等前端回传决定。

        无活动流（sink 未挂）或超时一律按拒绝处理——审批是安全闸门，宁可拒绝。
        """
        registry = self._registries.get(task_id)
        sink = registry.sink if registry is not None else None
        if sink is None:
            return False
        approval_id = uuid.uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending_approvals[approval_id] = (task_id, future)
        try:
            arguments = json.loads(invocation.arguments_json) if invocation.arguments_json else {}
        except json.JSONDecodeError:
            arguments = {}
        await sink({"type": "approval_required", "approval_id": approval_id, "name": invocation.tool_name, "arguments": arguments})
        try:
            approved = await asyncio.wait_for(future, timeout=self._approval_timeout_seconds)
        except asyncio.TimeoutError:
            approved = False
        finally:
            self._pending_approvals.pop(approval_id, None)
        try:
            await sink({"type": "approval_resolved", "approval_id": approval_id, "approved": approved})
        except Exception:  # noqa: BLE001 - 流已断开时不再下发结果
            pass
        return approved

    def resolve_approval(self, task_id: str, approval_id: str, approved: bool) -> bool:
        """前端回传审批决定。未知/已解决的 approval_id 或被篡改的 task_id 返回 False。"""
        entry = self._pending_approvals.get(approval_id)
        if entry is None:
            return False
        pending_task, future = entry
        if pending_task != task_id:
            return False
        if not future.done():
            future.set_result(approved)
        return True

    async def _get_agent(self, task: dict[str, Any]) -> Agent:
        agent = self._agents.get(task["id"])
        if agent is not None:
            return agent
        await self._ensure_skills()
        await self._ensure_mcp_tools()
        agent = build_agent(
            f"task-{task['id'][:8]}", self._client(),
            tool_registry=self._build_registry(task["id"]),
            system_prompt_suffix=self._skills_suffix,
            trace_dir=str(self._trace_dir) if self._trace_dir else None,
            trace_metadata={"task_id": task["id"]},
            compaction_token_limit=self._compaction_token_limit,
            approval_gate=self._gate_for(task["id"]),
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
        # 置位停止信号：runner 的消费循环每轮首查，随后取消 producer、落 partial+stopped。
        # 无活动运行/已结束时幂等 no-op。
        run = self._runs.get(task_id)
        if run is not None and not run.done:
            run.stop_event.set()

    def evict(self, task_id: str) -> None:
        # 调用方须保证该任务当前没有进行中的流：pop 掉锁对象后，新流会 setdefault 造出
        # 一把新锁，同一任务的两条流会并发跑，可能串流。
        self._agents.pop(task_id, None)
        self._registries.pop(task_id, None)
        self._task_locks.pop(task_id, None)

    async def steer(self, task_id: str, content: str) -> bool:
        """运行中注入一条用户消息（打断纠偏）：落 user 行、下发 user_stored、入队待 agent 下一步采用。

        无进行中的运行返回 False（前端据此改走普通发送）。
        """
        run = self._runs.get(task_id)
        if run is None or run.done:
            return False
        user_row = await asyncio.to_thread(self._store.append_message, task_id, "user", content)
        await self._append(run, {"type": "user_stored", "id": user_row["id"], "created_at": user_row["created_at"]})
        run.steer.put_nowait(content)
        run.steer_event.set()  # 唤醒在飞的模型调用，令其立即打断重跑
        return True

    async def _recall_memories(self, query: str) -> list[str]:
        if not self._memory_enabled:
            return []
        rows = await asyncio.to_thread(self._store.list_memories)
        return rank_memories(query, [row["content"] for row in rows])

    async def _extract_and_remember(self, user_text: str, assistant_text: str) -> None:
        # 记忆是锦上添花：任何失败静默吞掉，不影响对话主流程。
        try:
            completion = await self._client().acomplete(build_extraction_messages(user_text, assistant_text))
            content = parse_extraction(completion.text)
            if content:
                await asyncio.to_thread(self._store.remember_memory, content)
        except Exception:  # noqa: BLE001 - 提取失败不影响本轮
            pass

    def _sweep_runs(self) -> None:
        now = time.monotonic()
        for task_id, run in list(self._runs.items()):
            if run.done and run.finished_at is not None and now - run.finished_at > self._run_ttl_seconds:
                self._runs.pop(task_id, None)

    async def _append(self, run: _LiveRun, event: dict[str, Any]) -> None:
        async with run.condition:
            run.events.append(event)
            run.condition.notify_all()

    async def _finish(self, run: _LiveRun) -> None:
        async with run.condition:
            run.done = True
            run.finished_at = time.monotonic()
            run.condition.notify_all()

    async def _start_run(
        self,
        task: dict[str, Any],
        content: str,
        skip_suggestions: bool,
        cancellation: CancellationToken | None,
    ) -> _LiveRun:
        task_id = task["id"]
        # 先取 agent：此时本轮 user 消息尚未落盘，重建重放的历史不含本轮，
        # arespond 里 record_message 的 user 只出现一次（避免 transcript 重复）。
        agent = await self._get_agent(task)
        run = _LiveRun(task_id=task_id)
        # 取舍：user 消息先落库，agent transcript 要到 arespond 末尾才补录。若在两步之间
        # 中断，DB 多出这条 user 行而缓存 agent 的 transcript 缺失；下一轮缓存命中不重放，
        # 上下文短暂缺这一句，直到 evict/重启后从 DB 重放恢复。接受此取舍。
        is_first_message = task["title"] == ""
        user_row = await asyncio.to_thread(self._store.append_message, task_id, "user", content)
        truncated_title = _truncate_title(content)
        await asyncio.to_thread(self._store.set_title_if_empty, task_id, truncated_title)
        # 首事件回送落库行身份（前端据此把 live user 泡换成 row-N）；首条消息再推截断版兜底标题。
        run.events.append({"type": "user_stored", "id": user_row["id"], "created_at": user_row["created_at"]})
        if is_first_message:
            run.events.append({"type": "title", "title": truncated_title})
        self._runs[task_id] = run
        # 预算：调用方没给 cancellation 时，按配置的 token 上限建一个（超限时循环内自然中止）。
        effective_cancellation = cancellation
        if effective_cancellation is None and self._budget_tokens is not None:
            effective_cancellation = CancellationToken(token_budget=self._budget_tokens)
        run.runner = asyncio.create_task(
            self._run_turn(run, task, agent, content, is_first_message, skip_suggestions, effective_cancellation)
        )
        return run

    async def _run_turn(
        self,
        run: _LiveRun,
        task: dict[str, Any],
        agent: Agent,
        content: str,
        is_first_message: bool,
        skip_suggestions: bool,
        cancellation: CancellationToken | None,
    ) -> None:
        """把一轮"生成到落库"的消费循环跑在独立 task 里，事件写入 run.events。

        与旧 stream_reply 的差别：不再 yield，而是 append 到事件日志；因此连接断开不会
        取消它，turn 会跑完并落完整 assistant。
        """
        task_id = task["id"]
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        registry = self._registries.get(task_id)
        if registry is not None:
            registry.sink = emit

        error: str | None = None
        reply: str | None = None
        # 本轮累计用量/成本（多步模型调用相加）；无价目时不带 cost 字段。
        turn_usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def record_usage(usage: dict[str, Any]) -> None:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                turn_usage[key] += usage.get(key, 0)
            if "cost" in usage:
                turn_usage["cost"] = turn_usage.get("cost", 0.0) + usage["cost"]

        async def produce() -> None:
            nonlocal error, reply
            try:
                recalled = await self._recall_memories(content)
                reply = await agent.arespond_with_callbacks(
                    content,
                    on_text_delta=lambda chunk: emit({"type": "delta", "text": chunk}),
                    on_reasoning_delta=lambda chunk: emit({"type": "reasoning", "text": chunk}),
                    cancellation=cancellation,
                    drain_steer=lambda: _drain_queue(run.steer),
                    steer_event=run.steer_event,
                    on_steer_interrupt=lambda: emit({"type": "steer_interrupt"}),
                    recalled=recalled,
                    on_usage=record_usage,
                )
            except Exception as exc:  # noqa: BLE001 - 转成 error 事件交给前端
                error = str(exc)
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        # 推荐/标题并行预发（语义同旧实现）：与回复生成同时起跑，done 后通常已就绪。
        suggest_task = (
            asyncio.create_task(
                suggest_followups(self._client(), await asyncio.to_thread(self._store.list_messages, task_id))
            )
            if not skip_suggestions
            else None
        )
        title_task = (
            asyncio.create_task(suggest_title(self._client(), content))
            if is_first_message and not skip_suggestions
            else None
        )
        pending_calls: list[dict[str, Any]] = []
        parts: list[str] = []
        try:
            while True:
                if run.stop_event.is_set():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_STREAM_IDLE_S)
                except TimeoutError:
                    continue  # ping 由 _tail 合成，这里不发
                if event is None:
                    break
                if event["type"] == "delta":
                    parts.append(event["text"])
                elif event["type"] == "steer_interrupt":
                    parts.clear()  # 被打断的部分丢弃，重新生成的文本随后重新累计
                elif event["type"] == "tool_call":
                    pending_calls.append(event)
                elif event["type"] == "tool_result":
                    call_id = event.get("call_id")
                    match = next(
                        (i for i, call in enumerate(pending_calls) if call.get("call_id") == call_id), None
                    ) if call_id is not None else None
                    arguments = pending_calls.pop(match)["arguments"] if match is not None else {}
                    await asyncio.to_thread(
                        self._store.append_message, task_id, "tool",
                        json.dumps({
                            "call_id": call_id, "name": event["name"], "arguments": arguments,
                            "result": event["result"], "ok": event["ok"],
                        }, ensure_ascii=False),
                    )
                await self._append(run, event)

            if run.stop_event.is_set():
                # 用户停止：落 partial + stopped 标记（与旧实现一致），并发终结事件。
                if not parts and reply:
                    parts.append(reply)
                partial = "".join(parts)
                if partial:
                    await asyncio.to_thread(self._store.append_message, task_id, "assistant", partial)
                await asyncio.to_thread(self._store.append_message, task_id, "stopped", "")
                await self._append(run, {"type": "stopped"})
            elif error is not None:
                await self._append(run, {"type": "error", "message": error})
            else:
                if not parts and reply:
                    parts.append(reply)  # 后端未流式时兜底，流式过则不重复追加
                final_reply = "".join(parts)
                await asyncio.to_thread(self._store.append_message, task_id, "assistant", final_reply)
                done_payload: dict[str, Any] = {"type": "done", "reply": final_reply}
                if turn_usage["total_tokens"] or "cost" in turn_usage:
                    done_payload["usage"] = dict(turn_usage)
                await self._append(run, done_payload)
                if suggest_task is not None:
                    suggestions = await suggest_task
                    if suggestions:
                        await self._append(run, {"type": "suggestions", "items": suggestions})
                if title_task is not None:
                    new_title = await title_task
                    if new_title:
                        await asyncio.to_thread(self._store.update_task, task_id, title=new_title)
                        await self._append(run, {"type": "title", "title": new_title})
                # 压缩是优化、失败不影响对话：assistant 已落库，此处触发折叠+快照落库，
                # DB 顺序 user → tool → assistant → summary，重放时 summary 之后无重复行。
                try:
                    await agent.maybe_compress_history()
                except Exception:  # noqa: BLE001 - 摘要失败静默跳过，下轮继续
                    pass
                # 长期记忆提取（默认关闭）：客户端已收到 done，这里多一次模型调用不影响其体验。
                if self._memory_enabled:
                    await self._extract_and_remember(content, final_reply)
        except Exception as exc:  # noqa: BLE001 - 兜底：任何异常都转成 error 事件，保证 run 收敛
            await self._append(run, {"type": "error", "message": str(exc)})
        finally:
            if registry is not None:
                registry.sink = None
            # 运行结束：未决审批一律按拒绝处理，避免 producer 悬挂到超时。
            for approval_id, (pending_task, future) in list(self._pending_approvals.items()):
                if pending_task == task_id and not future.done():
                    future.set_result(False)
            if not producer.done():
                producer.cancel()
            if suggest_task is not None and not suggest_task.done():
                suggest_task.cancel()
            if title_task is not None and not title_task.done():
                title_task.cancel()
            await self._finish(run)

    async def _tail(self, run: _LiveRun, after: int) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        """从 after 下标补发事件日志，然后跟随新事件直到运行结束；空闲合成 ping。"""
        idx = after
        while True:
            ping = False
            async with run.condition:
                if idx >= len(run.events) and not run.done:
                    try:
                        await asyncio.wait_for(run.condition.wait(), timeout=_STREAM_IDLE_S)
                    except asyncio.TimeoutError:
                        ping = True
                batch = run.events[idx:]
                done = run.done
            if ping and not batch:
                yield (-1, {"type": "ping"})
                continue
            for offset, event in enumerate(batch):
                yield (idx + offset, event)
            idx += len(batch)
            if done and idx >= len(run.events):
                return

    async def stream_reply(
        self,
        task_id: str,
        content: str | None = None,
        *,
        after: int = 0,
        skip_suggestions: bool = False,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """发起新的一轮（content 非空）或续传已有运行（content=None, after=N）。

        每个事件带内部下标 `_id`（SSE 编码成 `id:`），重连按 after 续传。断连只停止跟随，
        不影响运行；运行在后台独立跑完并落库。
        """
        task = await asyncio.to_thread(self._store.get_task, task_id)
        if task is None:
            yield {"type": "error", "message": f"task not found: {task_id}"}
            return
        self._sweep_runs()
        run = self._runs.get(task_id)
        # 运行中又来新消息：拒绝（前端 busy 已禁用输入，这里是防御）。
        if run is not None and not run.done and content is not None:
            yield {"type": "error", "message": "a turn is already running for this task"}
            return
        # 需要新起一轮：没有运行（且带 content），或上一轮已结束又来了新消息。
        if run is None or (run.done and content is not None):
            if content is None:
                return  # 续传请求但已无运行：无事件可补（前端会刷新历史）
            lock = self._task_locks.setdefault(task_id, asyncio.Lock())
            async with lock:
                run = self._runs.get(task_id)
                if run is None or run.done:
                    run = await self._start_run(task, content, skip_suggestions, cancellation)
        # 其余情况：尾随已有运行（进行中或已结束但在 TTL 窗口内）。
        assert run is not None
        async for event_id, event in self._tail(run, after):
            yield {**event, "_id": event_id}
