import time
from typing import Any

from .circuit_breaker import CircuitBreaker
from .outcome import FailureCode, OutcomeStatus, ToolOutcome
from .tool import Tool


class ToolRegistry:
    def __init__(self, circuit_breaker: CircuitBreaker | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._circuit_breaker = circuit_breaker

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
            outcome = await tool.acall(arguments)
        except Exception as error:
            outcome = ToolOutcome.error(str(error), duration_ms=int((time.monotonic() - start) * 1000))
        else:
            outcome.duration_ms = int((time.monotonic() - start) * 1000)

        if self._circuit_breaker is not None:
            self._circuit_breaker.record(name, success=outcome.status == OutcomeStatus.OK)
        return outcome
