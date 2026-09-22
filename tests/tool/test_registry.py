import asyncio
from typing import Any
from unittest.mock import Mock

from tool.registry import CircuitBreaker, ToolRegistry
from tool.outcome import FailureCode, ToolOutcome
from tool.tool import Tool, ToolParameter


class _EchoTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="echo", description="Echoes text back.")

    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="text", type="string", description="Text to echo")]

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome.ok(arguments["text"])


class _SlowTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="slow", description="Never returns before the timeout.")

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        await asyncio.sleep(10)
        return ToolOutcome.ok("too late")


class _BrokenTool(Tool):
    def __init__(self) -> None:
        super().__init__(name="broken", description="Always raises.")

    def parameters(self) -> list[ToolParameter]:
        return []

    async def acall(self, arguments: dict[str, Any]) -> ToolOutcome:
        raise RuntimeError("kaboom")


def test_register_get_list_tools():
    registry = ToolRegistry()
    tool = _EchoTool()
    registry.register(tool)

    assert registry.get("echo") is tool
    assert registry.list_tools() == [tool]


def test_unregister_removes_the_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    registry.unregister("echo")
    assert registry.get("echo") is None


def test_function_schemas_returns_schema_per_registered_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    schemas = registry.function_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "echo"


async def test_acall_returns_successful_outcome():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    outcome = await registry.acall("echo", {"text": "hi"})
    assert outcome.succeeded is True
    assert outcome.output == "hi"


async def test_acall_returns_not_found_for_unknown_tool():
    registry = ToolRegistry()
    outcome = await registry.acall("does-not-exist", {})
    assert outcome.failure_code == FailureCode.NOT_FOUND


async def test_acall_returns_invalid_arguments_when_validation_fails():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    outcome = await registry.acall("echo", {})
    assert outcome.failure_code == FailureCode.INVALID_ARGUMENTS


async def test_acall_converts_a_raised_exception_into_an_error_outcome():
    registry = ToolRegistry()
    registry.register(_BrokenTool())
    outcome = await registry.acall("broken", {})
    assert outcome.succeeded is False
    assert outcome.output == "kaboom"
    assert outcome.failure_code == FailureCode.EXECUTION_FAILED


async def test_acall_rejects_execution_when_circuit_is_open():
    breaker = Mock(spec=CircuitBreaker)
    breaker.allow.return_value = False
    registry = ToolRegistry(circuit_breaker=breaker)
    registry.register(_EchoTool())

    outcome = await registry.acall("echo", {"text": "hi"})

    assert outcome.failure_code == FailureCode.CIRCUIT_OPEN
    breaker.record.assert_not_called()


async def test_acall_records_success_on_the_circuit_breaker():
    breaker = Mock(spec=CircuitBreaker)
    breaker.allow.return_value = True
    registry = ToolRegistry(circuit_breaker=breaker)
    registry.register(_EchoTool())

    await registry.acall("echo", {"text": "hi"})

    breaker.record.assert_called_once_with("echo", success=True)


async def test_acall_records_failure_on_the_circuit_breaker_when_the_tool_raises():
    breaker = Mock(spec=CircuitBreaker)
    breaker.allow.return_value = True
    registry = ToolRegistry(circuit_breaker=breaker)
    registry.register(_BrokenTool())

    await registry.acall("broken", {})

    breaker.record.assert_called_once_with("broken", success=False)


async def test_acall_does_not_record_on_the_circuit_breaker_for_validation_failures():
    breaker = Mock(spec=CircuitBreaker)
    breaker.allow.return_value = True
    registry = ToolRegistry(circuit_breaker=breaker)
    registry.register(_EchoTool())

    await registry.acall("echo", {})

    breaker.record.assert_not_called()


async def test_acall_times_out_a_tool_that_exceeds_the_configured_timeout():
    registry = ToolRegistry(timeout_seconds=0.01)
    registry.register(_SlowTool())

    outcome = await registry.acall("slow", {})

    assert outcome.succeeded is False
    assert outcome.failure_code == FailureCode.TIMEOUT


async def test_acall_does_not_record_timeout_failures_as_circuit_breaker_successes():
    breaker = Mock(spec=CircuitBreaker)
    breaker.allow.return_value = True
    registry = ToolRegistry(circuit_breaker=breaker, timeout_seconds=0.01)
    registry.register(_SlowTool())

    await registry.acall("slow", {})

    breaker.record.assert_called_once_with("slow", success=False)


def test_allow_is_true_for_a_tool_with_no_recorded_failures():
    breaker = CircuitBreaker()
    assert breaker.allow("search") is True


def test_allow_becomes_false_after_reaching_failure_threshold():
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record("search", success=False)
    assert breaker.allow("search") is True
    breaker.record("search", success=False)
    assert breaker.allow("search") is False


def test_a_success_resets_the_failure_count():
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record("search", success=False)
    breaker.record("search", success=True)
    breaker.record("search", success=False)
    assert breaker.allow("search") is True


def test_allow_recovers_after_recovery_seconds_have_elapsed(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr("tool.registry.time.monotonic", lambda: fake_now[0])

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    breaker.record("search", success=False)
    assert breaker.allow("search") is False

    fake_now[0] += 60
    assert breaker.allow("search") is True


def test_failure_count_resets_after_recovery(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr("tool.registry.time.monotonic", lambda: fake_now[0])

    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=60)
    breaker.record("search", success=False)
    fake_now[0] += 60
    assert breaker.allow("search") is True
    breaker.record("search", success=False)
    assert breaker.allow("search") is False
