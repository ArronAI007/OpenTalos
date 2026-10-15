import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

from context import OutputTrimmer, TokenBudget
from core.agent_loop import execute_model_step
from core.protocol import StreamSummary, ToolCompletion
from core.protocols import (
    HistoryStore,
    MetricsSink,
    ModelClientProtocol,
    OutputTrimmerLike,
    SteerQueue,
    TokenEstimator,
    ToolExecutor,
    TraceRecorder,
)
from memory import WorkingMemory
from observability import RunRecorder, metrics
from tool.registry import ToolRegistry


def test_working_memory_satisfies_history_store(tmp_path):
    assert isinstance(WorkingMemory(), HistoryStore)


def test_tool_registry_satisfies_tool_executor():
    assert isinstance(ToolRegistry(), ToolExecutor)


def test_run_recorder_satisfies_trace_recorder(tmp_path):
    recorder = RunRecorder(output_dir=str(tmp_path))
    assert isinstance(recorder, TraceRecorder)
    recorder.finalize()


def test_metrics_singleton_satisfies_metrics_sink():
    assert isinstance(metrics, MetricsSink)


def test_token_budget_satisfies_token_estimator():
    assert isinstance(TokenBudget(), TokenEstimator)


def test_output_trimmer_satisfies_output_trimmer_like(tmp_path):
    trimmer = OutputTrimmer(max_lines=5, max_bytes=1_000_000, output_dir=str(tmp_path))
    assert isinstance(trimmer, OutputTrimmerLike)


class _FakeSteerQueue:
    def __init__(self) -> None:
        self._pending: list[str] = []
        self._event = asyncio.Event()

    def drain(self) -> list[str]:
        pending, self._pending = self._pending, []
        return pending

    def clear_interrupt(self) -> None:
        self._event.clear()

    @property
    def interrupt_event(self) -> asyncio.Event:
        return self._event


def test_a_minimal_fake_satisfies_steer_queue():
    assert isinstance(_FakeSteerQueue(), SteerQueue)


class _FakeModelClient:
    """只结构性满足 ModelClientProtocol 六个成员，不继承 ai.model.ModelClient/ModelBackend。"""

    def __init__(self, text: str) -> None:
        self.model_name = "fake-model"
        self.last_stream_summary: StreamSummary | None = None
        self._text = text

    async def acomplete(self, messages: list[dict], **kwargs: Any) -> Any:
        raise NotImplementedError

    async def astream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[str]:
        for char in self._text:
            yield char

    async def acomplete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> ToolCompletion:
        return ToolCompletion(text=self._text, requested_tools=[], model_id=self.model_name)

    async def astream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        on_text_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> ToolCompletion:
        raise NotImplementedError


def test_a_minimal_fake_satisfies_model_client_protocol():
    assert isinstance(_FakeModelClient("hi"), ModelClientProtocol)


async def test_execute_model_step_accepts_a_structural_fake_model_client():
    async def handle_invocation(invocation):
        raise AssertionError("no tool should be requested")

    completion = await execute_model_step(
        _FakeModelClient("hello"),
        [{"role": "user", "content": "hi"}],
        [],
        handle_invocation=handle_invocation,
    )

    assert completion.text == "hello"
