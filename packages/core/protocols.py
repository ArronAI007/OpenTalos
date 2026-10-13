"""`packages/core` 对外要求的协作方契约：core 只认这些 Protocol 的形状，不 import 任何其他
`packages/*` 目录。真正的实现（`memory.WorkingMemory`、`tool.registry.ToolRegistry`、
`observability.RunRecorder`、`context.TokenBudget`、`context.OutputTrimmer`）由调用方
（`packages/agents`、`apps/api/runtime.py`）构造好之后注入，不需要显式继承这里的任何类型。
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HistoryStore(Protocol):
    """对话历史的存取与组装；由 `memory.WorkingMemory` 结构性满足。"""

    def append(self, message: Any) -> None: ...
    def messages(self) -> list[Any]: ...
    def clear(self) -> None: ...
    def compress(self, summary: str) -> bool: ...
    def snapshot(self) -> dict: ...
    def restore(self, data: dict) -> None: ...
    def build_messages(self, system_prompt: str | None, user_text: str) -> list[dict]: ...
    def assemble(
        self,
        user_query: str,
        *,
        transcript: list[Any],
        system_instructions: str | None = None,
        extra_slices: list[Any] | None = None,
    ) -> str: ...


@dataclass
class ToolInfo:
    """`ToolExecutor.get()` 的返回值形状；`tool.tool.Tool` 结构性满足（只用到这两个属性）。"""

    requires_approval: bool
    untrusted_output: bool


@dataclass
class ToolCallResult:
    """`ToolExecutor.acall()` 的返回值形状；`tool.outcome.ToolOutcome` 结构性满足。"""

    succeeded: bool
    duration_ms: float
    output: str


@runtime_checkable
class ToolExecutor(Protocol):
    """工具的查找与执行；由 `tool.registry.ToolRegistry` 结构性满足。"""

    def get(self, name: str) -> ToolInfo | None: ...
    async def acall(self, name: str, arguments: dict[str, Any], *, call_id: str | None = None) -> ToolCallResult: ...
    def function_schemas(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class TraceRecorder(Protocol):
    """单轮运行的事件记录；由 `observability.RunRecorder` 结构性满足。"""

    def log_event(self, event: str, payload: dict[str, Any], step: int | None = None) -> None: ...
    def finalize(self) -> dict[str, Any]: ...


@runtime_checkable
class MetricsSink(Protocol):
    """进程内指标埋点；由 `observability.metrics` 单例结构性满足。"""

    def inc(self, name: str, *, labels: dict[str, str] | None = None, value: int = 1) -> None: ...
    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None: ...


class NullMetricsSink:
    """`MetricsSink` 的空实现：调用方不关心指标时的默认值，两个方法都是 no-op。"""

    def inc(self, name: str, *, labels: dict[str, str] | None = None, value: int = 1) -> None:
        return None

    def observe(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        return None


@runtime_checkable
class TokenEstimator(Protocol):
    """消息列表的 token 预算估算；由 `context.TokenBudget` 结构性满足。"""

    def estimate_messages(self, messages: list[Any]) -> int: ...


@runtime_checkable
class OutputTrimmerLike(Protocol):
    """超长工具输出的截断；由 `context.OutputTrimmer` 结构性满足。"""

    def trim(self, tool_name: str, output: str, metadata: dict[str, Any] | None = None) -> Any: ...


@runtime_checkable
class SteerQueue(Protocol):
    """steering/follow-up 的排队与打断；由 `apps/api/runtime.py` 的 `_LiveRun` 结构性满足。"""

    def drain(self) -> list[str]: ...
    def clear_interrupt(self) -> None: ...

    @property
    def interrupt_event(self) -> asyncio.Event: ...
