import asyncio
import time
from typing import Any

from .outcome import FailureCode, OutcomeStatus, ToolOutcome
from .tool import Tool


class CircuitBreaker:
    """连续失败到阈值就对该工具开路，过了恢复期再放行一次试探调用。"""

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 300) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failure_counts: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def allow(self, name: str) -> bool:
        opened_at = self._opened_at.get(name)
        if opened_at is None:
            return True
        if time.monotonic() - opened_at >= self.recovery_seconds:
            del self._opened_at[name]
            self._failure_counts[name] = 0
            return True
        return False

    def record(self, name: str, *, success: bool) -> None:
        if success:
            self._failure_counts[name] = 0
            self._opened_at.pop(name, None)
            return
        count = self._failure_counts.get(name, 0) + 1
        self._failure_counts[name] = count
        if count >= self.failure_threshold:
            self._opened_at[name] = time.monotonic()


class ToolRegistry:
    def __init__(self, circuit_breaker: CircuitBreaker | None = None, timeout_seconds: float | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._circuit_breaker = circuit_breaker
        self._timeout_seconds = timeout_seconds

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def function_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_function_schema() for tool in self._tools.values()]

    async def acall(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome.error(f'Unknown tool "{name}"', code=FailureCode.NOT_FOUND)

        if self._circuit_breaker is not None and not self._circuit_breaker.allow(name):
            return ToolOutcome.error(f'Circuit open for tool "{name}"', code=FailureCode.CIRCUIT_OPEN)

        validation_error = tool.validate(arguments)
        if validation_error is not None:
            return ToolOutcome.error(validation_error, code=FailureCode.INVALID_ARGUMENTS)

        start = time.monotonic()
        try:
            if self._timeout_seconds is not None:
                outcome = await asyncio.wait_for(tool.acall(arguments), timeout=self._timeout_seconds)
            else:
                outcome = await tool.acall(arguments)
        except asyncio.TimeoutError:
            outcome = ToolOutcome.error(
                f'Tool "{name}" timed out after {self._timeout_seconds}s',
                code=FailureCode.TIMEOUT,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as error:
            outcome = ToolOutcome.error(str(error), duration_ms=int((time.monotonic() - start) * 1000))
        else:
            outcome.duration_ms = int((time.monotonic() - start) * 1000)

        if self._circuit_breaker is not None:
            self._circuit_breaker.record(name, success=outcome.status == OutcomeStatus.OK)
        return outcome
