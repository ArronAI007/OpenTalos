from dataclasses import dataclass
from enum import Enum


class OutcomeStatus(Enum):
    OK = "ok"
    ERROR = "error"


class FailureCode(Enum):
    INVALID_ARGUMENTS = "invalid_arguments"
    EXECUTION_FAILED = "execution_failed"
    NOT_FOUND = "not_found"
    CIRCUIT_OPEN = "circuit_open"
    TIMEOUT = "timeout"


@dataclass
class ToolOutcome:
    status: OutcomeStatus
    output: str
    failure_code: FailureCode | None = None
    duration_ms: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status == OutcomeStatus.OK

    @classmethod
    def ok(cls, output: str, *, duration_ms: int = 0) -> "ToolOutcome":
        return cls(status=OutcomeStatus.OK, output=output, duration_ms=duration_ms)

    @classmethod
    def error(
        cls, message: str, *, code: FailureCode = FailureCode.EXECUTION_FAILED, duration_ms: int = 0
    ) -> "ToolOutcome":
        return cls(status=OutcomeStatus.ERROR, output=message, failure_code=code, duration_ms=duration_ms)
