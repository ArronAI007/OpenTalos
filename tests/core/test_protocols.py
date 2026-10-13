import asyncio

from context import OutputTrimmer, TokenBudget
from core.protocols import (
    HistoryStore,
    MetricsSink,
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
