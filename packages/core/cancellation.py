import asyncio
import time

from .errors import OperationCancelled


class CancellationToken:
    """协作式取消令牌：包一层 asyncio.Event，调用方在每轮循环边界（下一次模型调用前/工具批次
    执行前）主动检查，不会打断已经在执行的工具调用——跟 pi 的 effect-gate 一个思路：副作用
    执行到一半不安全中断，只影响"是否发起下一步"。

    timeout_seconds / token_budget 是挂在同一套检查点上的两种自动触发条件：整轮循环的墙钟
    超时，和跨步累计的 token 用量上限（由调用方在每次拿到模型响应后用 record_tokens 喂用量，
    agent_loop.execute_model_step/run_tool_turn 已经这么做了）。想让预算跨多轮 arespond() 共享，
    把同一个 token 实例继续传下去即可——它不会在每轮开始时重置。
    """

    def __init__(self, *, timeout_seconds: float | None = None, token_budget: int | None = None) -> None:
        self._event = asyncio.Event()
        self._deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        self._token_budget = token_budget
        self._tokens_used = 0

    def cancel(self) -> None:
        self._event.set()

    def record_tokens(self, count: int) -> None:
        self._tokens_used += count

    @property
    def is_cancelled(self) -> bool:
        return (
            self._event.is_set()
            or (self._deadline is not None and time.monotonic() >= self._deadline)
            or (self._token_budget is not None and self._tokens_used >= self._token_budget)
        )

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled("Agent run was cancelled.")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise OperationCancelled("Agent run exceeded its timeout.")
        if self._token_budget is not None and self._tokens_used >= self._token_budget:
            raise OperationCancelled(f"Agent run exceeded its token budget ({self._token_budget} tokens).")
