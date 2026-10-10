import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from context import AssemblyConfig, ContextSlice, OutputTrimmer, TokenBudget
from observability import RunRecorder
from pydantic import BaseModel

from .compaction import summarize_history
from .model import ModelClient
from .protocol import ChatMessage
from memory import ShortTermMemory


class RuntimeSettings(BaseModel):
    temperature: float = 0.7
    max_tokens: int | None = None
    debug: bool = False
    log_level: str = "INFO"
    callback_timeout_seconds: float = 5.0


class AgentPhase(Enum):
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"


@dataclass
class PhaseSignal:
    phase: AgentPhase
    timestamp: float
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def emit(cls, phase: AgentPhase, agent_name: str, **data: Any) -> "PhaseSignal":
        return cls(phase=phase, timestamp=time.time(), agent_name=agent_name, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "timestamp": self.timestamp, "agent_name": self.agent_name, "data": self.data}


PhaseCallback = Callable[[PhaseSignal], Awaitable[None]] | None


class Agent(ABC):
    def __init__(
        self,
        name: str,
        model_client: ModelClient,
        system_prompt: str | None = None,
        settings: RuntimeSettings | None = None,
        context_config: AssemblyConfig | None = None,
        min_retain_turns: int = 10,
        trace_dir: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
        compaction_token_limit: int | None = None,
        output_trimmer: OutputTrimmer | None = None,
    ) -> None:
        self.name = name
        self.model_client = model_client
        self.system_prompt = system_prompt
        self.settings = settings or RuntimeSettings()
        self._short_term = ShortTermMemory(
            min_retain_turns=min_retain_turns, message_type=ChatMessage, context_config=context_config
        )
        self.recorder: RunRecorder | None = None
        # 一轮运行一份 trace：recorder 在 begin_trace()（arespond_with_callbacks 入口）创建、
        # end_trace() finalize；轮与轮之间为 None。trace_metadata 会写进 session_start，
        # 供按 HTTP 请求/task 关联 trace。
        self._trace_dir = trace_dir
        self._trace_metadata = trace_metadata or {}
        self.compaction_token_limit = compaction_token_limit
        # 不为空时，工具输出超限会被截断、完整内容落盘（OutputTrimmer 构造即建目录，所以默认不建）。
        self.output_trimmer = output_trimmer
        self._tokens = TokenBudget()
        # 压缩成功后触发的无参回调（供 runtime 落库快照）；压缩本身是纯 Surface 操作，不该在
        # 这里耦合任何持久化逻辑，所以回调由外部按需注入，None 时静默跳过。
        self.on_compression: Callable[[], Awaitable[None]] | None = None

    @abstractmethod
    async def arespond(self, input_text: str, **kwargs: object) -> str: ...

    def begin_trace(self) -> None:
        """一轮运行开始：新建一份 trace（JSONL+HTML）并记录 session_start。未配置 trace_dir 时 no-op。"""
        if self._trace_dir is None:
            return
        self.recorder = RunRecorder(output_dir=self._trace_dir)
        self.recorder.log_event(
            "session_start",
            {"agent_name": self.name, "agent_type": type(self).__name__, **self._trace_metadata},
        )

    def end_trace(self, *, status: str = "completed", error: str | None = None) -> dict[str, Any] | None:
        """一轮运行结束：记 session_end、写 HTML 统计面板并关闭文件。幂等（无 recorder 时 no-op）。"""
        if self.recorder is None:
            return None
        self.recorder.log_event("session_end", {"status": status, **({"error": error} if error else {})})
        stats = self.recorder.finalize()
        self.recorder = None
        return stats

    async def arespond_with_callbacks(
        self,
        input_text: str,
        on_start: PhaseCallback = None,
        on_finish: PhaseCallback = None,
        on_error: PhaseCallback = None,
        **kwargs: object,
    ) -> str:
        self.begin_trace()
        status, error_text = "completed", None
        try:
            await self._notify(AgentPhase.STARTED, on_start, input_text=input_text)
            try:
                result = await self.arespond(input_text, **kwargs)
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except Exception as error:
                status, error_text = "failed", str(error)
                await self._notify(AgentPhase.FAILED, on_error, error=error_text, error_type=type(error).__name__)
                raise
            await self._notify(AgentPhase.FINISHED, on_finish, result=result)
            return result
        finally:
            self.end_trace(status=status, error=error_text)

    async def _notify(self, phase: AgentPhase, callback: PhaseCallback, **data: object) -> None:
        if callback is None:
            return
        signal = PhaseSignal.emit(phase, self.name, **data)
        try:
            await asyncio.wait_for(callback(signal), timeout=self.settings.callback_timeout_seconds)
        except Exception:
            # 回调超时或回调自身抛异常都不应打断 Agent 主流程（设计如此）。
            pass

    def record_message(self, message: ChatMessage) -> None:
        self._short_term.append(message)

    def record_tool_result(self, call_id: str, tool_name: str, arguments_json: str, result: str) -> None:
        """把一次工具调用记录进 transcript，供跨轮/跨重启时由 build_messages 还原成合法的
        assistant(tool_calls) + tool(tool_call_id) 结构。arguments_json 保持原始 JSON 字符串，
        因为还原时 tool_calls 的 function.arguments 就是 JSON 字符串。"""
        self._short_term.append(
            ChatMessage(
                role="tool",
                content=result,
                metadata={"tool_call_id": call_id, "tool_name": tool_name, "arguments": arguments_json},
            )
        )

    def history_snapshot(self) -> list[ChatMessage]:
        return self._short_term.messages()

    def reset_history(self) -> None:
        self._short_term.clear()

    def compress_history(self, summary: str) -> bool:
        """把 min_retain_turns 之前的历史折叠成一条 summary 消息，回合数不足时是 no-op。"""
        return self._short_term.compress(summary)

    async def maybe_compress_history(self) -> bool:
        """历史消息的预估 token 数达到 compaction_token_limit 时，用 LLM 生成结构化摘要并折叠旧历史。

        compaction_token_limit 为 None（默认）时是 no-op，不会产生额外的模型调用；折叠成功后
        触发 on_compression 回调（若有）。压缩触发时机由调用方编排（如 runtime 在 assistant
        落库后调用），保证落库顺序与重放一致。
        """
        if self.compaction_token_limit is None:
            return False
        messages = self.history_snapshot()
        if self._tokens.estimate_messages(messages) < self.compaction_token_limit:
            return False
        summary = await summarize_history(self.model_client, messages)
        changed = self.compress_history(summary)
        if changed and self.on_compression is not None:
            await self.on_compression()
        return changed

    def snapshot_history(self) -> dict[str, Any]:
        """当前 Surface（transcript）的完整序列化，供压缩落库 / 重启恢复。"""
        return self._short_term.snapshot()

    def restore_history(self, data: dict[str, Any]) -> None:
        """用一份快照覆盖当前 transcript，用于重启后从 summary 检查点恢复而非全量重放。"""
        self._short_term.restore(data)

    def build_context(self, user_query: str, extra_slices: list[ContextSlice] | None = None) -> str:
        """跑一遍 GSSC 流水线，把 system_prompt + 历史 + user_query 组装成结构化上下文。"""
        return self._short_term.assembler.assemble(
            user_query,
            transcript=self.history_snapshot(),
            system_instructions=self.system_prompt,
            extra_slices=extra_slices,
        )

    def build_messages(self, user_text: str) -> list[dict[str, Any]]:
        """把 system_prompt + 历史（按轮次截断到 token 预算内）+ 本轮输入组装成合法的、
        OpenAI 兼容的 messages 列表——真实的、生产代码会调用的 prompt 拼装入口。
        """
        return self._short_term.build_messages(self.system_prompt, user_text)
